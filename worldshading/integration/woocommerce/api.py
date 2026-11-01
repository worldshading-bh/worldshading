import json
import re
import frappe
from .common import SETTINGS, MAP, ORDER, LOG, settings, manager_only,start_operation
from .client import from_settings, check_connection
from .domain import verify_signature,validate_source_order,order_in_window


@frappe.whitelist()
def test_connection():
    manager_only();config=settings(False);client=from_settings(config)
    return check_connection(client,config.currency)


@frappe.whitelist()
def reconcile():
    manager_only(write=True)
    from .sync import run_cycle
    return run_cycle()


@frappe.whitelist()
def import_orders():
    manager_only(write=True)
    from .sync import run_cycle
    return run_cycle(export_products=False)


@frappe.whitelist()
def preview_product(name):
    manager_only()
    from .item_links import get_mapping
    frappe.get_doc('Item',get_mapping(name)['item_code']).check_permission('read')
    from .sync import preview_product as preview
    return preview(name)


@frappe.whitelist()
def sync_product(name):
    manager_only(write=True)
    from .item_links import get_mapping
    frappe.get_doc('Item',get_mapping(name)['item_code']).check_permission('read')
    from .sync import run_cycle
    # A manual export must reconcile new Woo purchases first, just like the timer.
    return run_cycle(mapping_name=name)


@frappe.whitelist()
def item_status(item_code):
    manager_only()
    frappe.get_doc('Item',item_code).check_permission('read')
    from .item_links import status_for_item
    from .stock_holds import stock_holds, stock_orders
    from .item_links import LINK, TABLE
    holds=stock_holds()
    stock_enabled=frappe.db.exists(LINK,dict(parent=item_code,parenttype='Item',parentfield=TABLE,enabled=1,sync_stock=1))
    return dict(links=status_for_item(item_code),review_required=holds['review_required'],
                stock_orders=stock_orders(item_code,holds) if stock_enabled else [])


@frappe.whitelist()
def order_review(name):
    """Read-only mapping checklist, without exposing customer/order payload data."""
    manager_only()
    from .domain import match_line
    from .item_links import LINK,TABLE,CONFIG_FIELDS,normalize
    row=frappe.get_doc(ORDER,name)
    row.check_permission('read')
    try:
        payload=json.loads(row.payload)
        if not isinstance(payload,dict) or not isinstance(payload.get('line_items'),list):
            raise ValueError('Invalid product lines')
    except (ValueError,TypeError):
        return dict(lines=[],error='Stored product lines are unreadable. Restore the order payload from WooCommerce before retrying.')
    links=frappe.get_all(LINK,filters=dict(enabled=1,parenttype='Item',parentfield=TABLE),fields=CONFIG_FIELDS+['parent'])
    approved=[dict(link,item_code=link.parent) for link in links]
    result=[]
    for index,line in enumerate(payload.get('line_items') or [],1):
        if not isinstance(line,dict):
            result.append(dict(line=index,name='Invalid product line',error='Restore this line from WooCommerce before retrying.'))
            continue
        entry=dict(line=index,name=line.get('name'),sku=line.get('sku'),product_id=line.get('product_id'),
                   variation_id=line.get('variation_id') or 0,item_code=None,error=None)
        try:
            match=match_line(line,approved)
            normalize(frappe.get_doc('Item',match['item_code']),match)
            entry['item_code']=match['item_code']
        except (ValueError,TypeError,AttributeError) as exc:entry['error']=str(exc)
        result.append(entry)
    return dict(lines=result)


@frappe.whitelist()
def retry_order(name):
    manager_only(write=True)
    from .orders import import_order
    from .common import lock
    with lock('order:'+str(name)):
        row=frappe.get_doc(ORDER,name)
        payload=json.loads(row.payload)
        validate_source_order(payload)
        if str(payload['id'])!=str(name):raise ValueError('Stored order identity does not match its inbox record')
        row.status='Pending';row.attempts=0;row.next_retry=None;row.save(ignore_permissions=True)
        frappe.db.commit()
    return import_order(payload)


@frappe.whitelist()
def ignore_order(name,reason):
    manager_only(write=True)
    if not str(reason or '').strip(): raise ValueError('A review reason is required')
    from .common import log,lock
    with lock('order:'+str(name)):
        row=frappe.get_doc(ORDER,name)
        row.status='Ignored';row.next_retry=None;row.save(ignore_permissions=True)
        log('Order review',name,'Skipped','Operator ignored this import: '+str(reason)[:500])
        frappe.db.commit()
    return {'status':'Ignored','sales_order':row.sales_order}


@frappe.whitelist()
def dashboard():
    manager_only()
    # Local counters must also render on a blank first-install form, before
    # credentials/URL are saved. Network actions still validate settings.
    config=frappe.get_single(SETTINGS)
    return {'mappings':frappe.db.count(MAP,{'enabled':1}),'imported':frappe.db.count(ORDER,{'status':'Imported'}),
            'review':frappe.db.count(ORDER,{'status':['in',['Needs Review','Failed','Pending']]}),
            'enabled':bool(config.enabled),'automatic_sync':bool(config.automatic_sync),
            'last_run':frappe.db.get_single_value(SETTINGS,'last_run')}


@frappe.whitelist(allow_guest=True)
def webhook():
    config=settings(False)
    if frappe.request.method!='POST':
        frappe.throw('POST is required',frappe.PermissionError)
    body=frappe.request.get_data()
    if len(body)>2*1024*1024:
        raise ValueError('Webhook payload exceeds size limit')
    # Woo's initial URL reachability ping is unsigned and contains no order data.
    # It is acknowledged without reading or changing inbox/customer/order records.
    if re.fullmatch(br'webhook_id=[0-9]{1,12}',body):
        return {'accepted':True,'ping':True}
    secret=config.get_password('webhook_secret',raise_exception=False)
    if not verify_signature(body,frappe.get_request_header('X-WC-Webhook-Signature'),secret):
        frappe.throw('Invalid Woo webhook signature',frappe.PermissionError)
    source=frappe.get_request_header('X-WC-Webhook-Source') or ''
    if source.rstrip('/')!=config.store_url.rstrip('/'):
        frappe.throw('Unexpected Woo webhook source',frappe.PermissionError)
    payload=json.loads(body.decode('utf-8'))
    topic=frappe.get_request_header('X-WC-Webhook-Topic')
    if topic not in ('order.created','order.updated'):
        raise ValueError('Unsupported Woo webhook topic')
    if not config.enabled or not config.automatic_sync:
        # HTTP 200 keeps Woo from disabling the endpoint. No cursor advances;
        # a later manual or automatic poll recovers orders from this interval.
        return {'accepted':False,'paused':True,'message':'Automatic import is off. Use Import Orders to retrieve recent orders.'}
    validate_source_order(payload)
    if not order_in_window(payload,config.order_since):
        return {'accepted':False,'outside_import_window':True,'message':'Order created before the configured UTC import start.'}
    start_operation()
    frappe.set_user(config.integration_user)
    from .orders import store_payload
    from .common import lock,LockBusy
    try:
        with lock('order:'+str(payload.get('id'))):
            inbox,_=store_payload(payload)
            frappe.db.commit()
    except LockBusy:
        frappe.local.response['http_status_code']=503
        return {'accepted':False,'retry':True,'message':'Order is being processed. Retry delivery.'}
    # Commit before releasing the source-order lock; the worker drains this inbox.
    return {'accepted':True,'order_id':inbox.woo_order_id}
