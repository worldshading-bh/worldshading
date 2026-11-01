"""Bounded reconciliation. Poll orders before publishing inventory."""
import json
from datetime import datetime, timedelta
from urllib.parse import urlsplit
import frappe
from frappe.utils import now_datetime, today, get_datetime
from . import domain as d
from .client import from_settings, stable_order_window,check_price_configuration
from .common import SETTINGS, MAP, ORDER, settings, mappings, log, lock,start_operation
from .item_links import get_mapping, normalize
from .stock_holds import stock_holds, stock_orders
from .inventory import stock_warehouses


def draft_hold(item_code, warehouses):
    if isinstance(warehouses,str):warehouses=[warehouses]
    placeholders=','.join(['%s']*len(warehouses))
    rows=frappe.db.sql('''SELECT COALESCE(SUM(i.stock_qty),0) FROM `tabSales Order Item` i
        JOIN `tabSales Order` s ON s.name=i.parent WHERE s.docstatus=0
        AND COALESCE(s.ws_woo_order_id,'')<>'' AND i.item_code=%s AND i.warehouse IN ('''+placeholders+')',
        [item_code]+list(warehouses))
    return rows[0][0] or 0


def product_payload(mapping, config, snapshot=None):
    item=snapshot.item(mapping['item_code']) if snapshot is not None else frappe.get_doc('Item',mapping['item_code'])
    mapping=normalize(item,mapping)
    if item.disabled or item.has_variants or not item.is_sales_item:
        raise ValueError('Mapped Item must be active and sellable')
    payload={}
    if mapping['sync_price']:
        prices=snapshot.prices(item.name) if snapshot is not None else frappe.get_all('Item Price',filters={'item_code':item.name,'price_list':config.price_list},fields=['*'])
        prices=[p for p in prices if p.currency==config.currency and not p.get('customer') and not p.get('supplier')
            and not p.get('batch_no') and (not p.valid_from or str(p.valid_from)<=today())
            and (not p.valid_upto or str(p.valid_upto)>=today())]
        payload['regular_price']=d.choose_price(prices,mapping['sale_uom'],item.stock_uom,mapping['conversion_factor'])
        if mapping['clear_sale_price']: payload['sale_price']=''
    if mapping['sync_stock']:
        payload['manage_stock']=bool(item.is_stock_item)
        if item.is_stock_item:
            warehouses=snapshot.warehouses if snapshot is not None else stock_warehouses(config)
            bins=snapshot.bins(item.name) if snapshot is not None else frappe.get_all('Bin',filters={'item_code':item.name,'warehouse':['in',warehouses]},
                fields=['actual_qty','reserved_qty','reserved_qty_for_production','reserved_qty_for_sub_contract'])
            drafts=snapshot.drafts(item.name) if snapshot is not None else draft_hold(item.name,warehouses)
            qty=d.combined_stock(bins,drafts,config.safety_stock,mapping['conversion_factor'])
            payload.update(stock_quantity=qty,stock_status='instock' if qty>0 else 'outofstock',backorders='no')
        else:
            payload.update(stock_status='instock',backorders='no')
    return payload


def sync_product(mapping, config=None, client=None, holds=None, context=None):
    config=config or settings();client=client or from_settings(config)
    if isinstance(mapping,str): mapping=get_mapping(mapping)
    with lock('product:'+str(mapping['product_id'])+':'+str(mapping.get('variation_id') or 0)):
        blocked=[]
        try:
            from .sync_state import invalidate_verification
            invalidate_verification(mapping['name'])
            blocked=stock_orders(mapping['item_code'], stock_holds() if holds is None else holds) if mapping.get('sync_stock') else []
            if blocked:
                log('Stock hold',mapping['item_code'],'Skipped','Stock held for orders requiring review: '+', '.join(blocked),
                    {'orders':blocked},item_link=mapping['name'])
            effective=dict(mapping, sync_stock=0) if blocked else mapping
            if blocked and not mapping.get('sync_price'):
                frappe.db.commit()
                return dict(item_code=mapping['item_code'],status='Stock Held',payload={},stock_blocked=len(blocked),stock_orders=blocked)
            payload=product_payload(effective,config)
            if 'regular_price' in payload and not (context is not None and context.get('price_configuration_checked')):
                check_price_configuration(client,config.currency)
                if context is not None:context['price_configuration_checked']=True
            endpoint=product_endpoint(mapping)
            before=client.get(endpoint)
            validate_product_identity(mapping,before)
            changed=bool(changed_fields(before,payload))
            if changed:
                client.put(endpoint,payload)
            after=client.get(endpoint) if changed else before
            for key,value in payload.items():
                actual=after.get(key)
                if key=='regular_price': actual=d.money(actual)
                if actual!=value:
                    raise ValueError('Woo readback did not confirm '+key)
            message='Verified Woo readback' if changed else 'Already matches ERP'
            if blocked: message+=' (price only; stock held for orders '+', '.join(blocked)+')'
            log('Product sync',mapping['item_code'],'Success' if changed else 'Skipped',message,payload,item_link=mapping['name'])
            frappe.db.commit()
            return dict(item_code=mapping['item_code'],status='Updated' if changed else 'Unchanged',payload=payload,
                        stock_blocked=len(blocked),stock_orders=blocked)
        except Exception as exc:
            log('Product sync',mapping['item_code'],'Failed',str(exc),item_link=mapping['name']);frappe.db.commit()
            return dict(item_code=mapping['item_code'],status='Failed',error=str(exc),stock_blocked=len(blocked),stock_orders=blocked)


def product_endpoint(mapping):
    endpoint='products/'+str(mapping['product_id'])
    if mapping.get('variation_id'):
        endpoint+='/variations/'+str(mapping['variation_id'])
    return endpoint


def validate_product_identity(mapping, product):
    if not isinstance(product,dict) or product.get('sku')!=mapping['sku']:
        raise ValueError('Woo SKU does not match approved mapping')
    if not mapping.get('variation_id') and product.get('type')!='simple':
        raise ValueError('Only simple products or explicit variations may be synced')


def changed_fields(current, expected):
    return sorted(key for key,value in expected.items()
                  if (d.money(current.get(key))!=d.money(value) if key=='regular_price'
                      else current.get(key)!=value))


def preview_product(mapping, config=None, client=None):
    """Read current and expected values without writes, imports or cursor changes."""
    config=config or settings(False)
    client=client or from_settings(config)
    if isinstance(mapping,str):
        mapping=get_mapping(mapping)
    expected=product_payload(mapping,config)
    if 'regular_price' in expected:check_price_configuration(client,config.currency)
    product=client.get(product_endpoint(mapping))
    validate_product_identity(mapping,product)
    product_url=product.get('permalink') or ''
    try:
        parsed=urlsplit(product_url)
        if parsed.scheme!='https' or parsed.netloc!=urlsplit(config.store_url).netloc:
            product_url=''
    except ValueError:
        product_url=''
    if not product_url:product_url=config.store_url.rstrip('/')+'/?p='+str(mapping['product_id'])
    blocked=stock_orders(mapping['item_code'],stock_holds()) if mapping.get('sync_stock') else []
    return dict(item_code=mapping['item_code'],product_url=product_url,current={key:product.get(key) for key in expected},
                expected=expected,changed_fields=changed_fields(product,expected),stock_blocked=len(blocked),stock_orders=blocked,
                warehouses=stock_warehouses(config) if mapping.get('sync_stock') else [],
                message='Preview only. No records were changed. Sync checks recent orders before publishing stock.')


def poll_orders(config=None,client=None):
    from .orders import import_order
    config=config or settings();client=client or from_settings(config)
    start=max(get_datetime(config.order_since),get_datetime(config.poll_cursor or config.order_since)-timedelta(minutes=2))
    end=datetime.utcnow()-timedelta(seconds=5)
    if start>=end: return 0
    count=0
    batch=stable_order_window(client,dict(modified_after=start.strftime('%Y-%m-%dT%H:%M:%S'),
        modified_before=end.strftime('%Y-%m-%dT%H:%M:%S'),dates_are_gmt='true'))
    for order in batch:
        if not d.order_in_window(order,config.order_since): continue
        import_order(order);count+=1
    frappe.db.set_value(SETTINGS,SETTINGS,'poll_cursor',end,update_modified=False)
    frappe.db.commit()
    return count


def run_cycle(mapping_name=None, export_products=True, changes_only=False, pending_only=False):
    previous=getattr(frappe.flags,'ws_woo_draining',False)
    frappe.flags.ws_woo_draining=True
    try:
        result=_run_cycle(mapping_name,export_products,changes_only,pending_only)
    finally:
        frappe.flags.ws_woo_draining=previous
    # The cycle lock has been released. Catch work arriving after our target
    # selection, including Items outside a single-product manual sync.
    if not previous:
        from .events import notify,warn
        try:notify()
        except Exception:warn()
    return result


def _run_cycle(mapping_name=None, export_products=True, changes_only=False, pending_only=False):
    start_operation()
    config=settings()
    with lock('cycle'):
        selected=mappings() if export_products else []
        if mapping_name is not None:
            selected=[mapping for mapping in selected if mapping['name']==mapping_name]
            if not selected:
                raise ValueError('Choose an enabled product mapping')
        from .orders import retry_due
        client=from_settings(config)
        result={'orders':0,'retries':0,'products':[]}
        try:
            result['orders']=poll_orders(config,client)
            result['retries']=retry_due()
            holds=stock_holds()
            blocked=holds['review_required']
            result['review_required']=blocked
            # Refresh exposure for each target: webhooks may add a review order
            # while a longer cycle is exporting other products.
            if changes_only:
                from .changes import process_changes
                if pending_only:
                    from .events import pending_links
                    pending=pending_links()
                    selected=[mapping for mapping in selected if mapping['name'] in pending]
                result.update(process_changes(selected,config,client))
            else:
                context={}
                result['products']=[sync_product(m,config,client,context=context) for m in selected]
            result['stock_blocked']=sum(bool(p.get('stock_blocked')) for p in result['products'])
            summary='Orders checked: %s. Retries: %s. Products updated: %s. Unchanged: %s. Errors: %s. Orders requiring review: %s.' % (
                result['orders'],result['retries'],sum(p['status']=='Updated' for p in result['products']),
                sum(p['status']=='Unchanged' for p in result['products']),sum(p['status']=='Failed' for p in result['products']),blocked)
            if result.get('stock_blocked'):summary+=' Stock held for %s affected products; other exports continue.'%result['stock_blocked']
            if changes_only:summary+=' Local checks: %s. No product request needed: %s. Retry deferred: %s. Batch deferred: %s.'%(
                result['local_checked'],result['locally_unchanged'],result['retry_deferred'],result['batch_deferred'])
            frappe.db.set_value(SETTINGS,SETTINGS,dict(last_run=now_datetime(),last_result=summary),update_modified=False)
            frappe.db.commit()
            return result
        except Exception as exc:
            log('Reconcile','cycle','Failed',str(exc))
            frappe.db.set_value(SETTINGS,SETTINGS,dict(last_run=now_datetime(),last_result='Failed: '+str(exc)[:1000]),update_modified=False)
            frappe.db.commit()
            raise
