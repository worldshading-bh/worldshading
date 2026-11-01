"""Durable, idempotent Woo order -> draft ERP Sales Order adapter."""
import json
import frappe
from frappe.utils import now_datetime, get_datetime, add_to_date, add_days, today
from . import domain as d
from .common import ORDER, settings, mappings, log, lock,start_operation
from .item_links import normalize


def store_payload(payload):
    order_id = d.validate_source_order(payload)
    name = str(order_id)
    inbox = frappe.get_doc(ORDER, name) if frappe.db.exists(ORDER, name) else frappe.get_doc(dict(doctype=ORDER, woo_order_id=order_id))
    incoming = payload.get('date_modified_gmt') or payload.get('date_created_gmt')
    if inbox.source_modified and incoming and get_datetime(incoming) < get_datetime(inbox.source_modified):
        return inbox, False
    try:
        previous = json.loads(inbox.payload) if inbox.payload else None
        if not isinstance(previous,dict):previous=None
    except (ValueError,TypeError):
        previous=None  # A fresh authenticated Woo event can repair a corrupt inbox copy.
    changed = previous is None or d.order_fingerprint(previous) != d.order_fingerprint(payload) or inbox.woo_status != payload.get('status')
    if changed:
        inbox.status='Pending'; inbox.attempts=0; inbox.next_retry=None
    inbox.payload = json.dumps(payload, ensure_ascii=False)
    inbox.woo_status = payload.get('status')
    inbox.source_modified = incoming
    inbox.currency = payload.get('currency')
    inbox.total = float(d.number(payload.get('total')))
    if not inbox.status:
        inbox.status = 'Pending'
    inbox.save(ignore_permissions=True)
    return inbox, True


def customer_for(order, config):
    billing = order.get('billing') or {}
    email = (billing.get('email') or '').strip().lower()
    key = d.customer_key(order, config.store_url)
    existing = frappe.db.get_value('Customer', {'ws_woo_customer_key': key}, 'name')
    legacy = frappe.db.get_value('Customer', {'ws_woo_customer_key': d.legacy_customer_key(order)}, 'name')
    if existing and legacy and existing != legacy:
        raise ValueError('Conflicting Woo customer links; review the existing customers')
    if existing or legacy:
        return existing or legacy
    display = ' '.join(filter(None, [billing.get('first_name'), billing.get('last_name')])).strip() or 'Woo Guest '+str(order['id'])
    customer = frappe.get_doc(dict(doctype='Customer', customer_name=display, customer_type='Individual',
                                  naming_series='CM.####',customer_group=config.customer_group,
                                  territory=config.territory,ws_woo_customer_key=key))
    customer.insert(ignore_permissions=True)
    if email or billing.get('phone'):
        contact = frappe.get_doc(dict(doctype='Contact',first_name=billing.get('first_name') or display,
            last_name=billing.get('last_name'),links=[dict(link_doctype='Customer',link_name=customer.name)]))
        if email: contact.append('email_ids',dict(email_id=email,is_primary=1))
        if billing.get('phone'): contact.append('phone_nos',dict(phone=billing['phone'],is_primary_phone=1))
        contact.insert(ignore_permissions=True)
    return customer.name


def order_addresses(order, customer):
    """Keep per-order snapshots so repeat buyers can use different delivery addresses."""
    result={}
    title='Woo order '+str(order['id'])
    billing=order.get('billing') or {}
    for kind in ['Billing','Shipping']:
        data=order.get(kind.lower()) or {}
        if not data.get('address_1'): continue
        country=frappe.db.get_value('Country',{'code':(data.get('country') or '').lower()},'name')
        if not country: raise ValueError('Woo address country does not match an ERP Country')
        existing=frappe.db.get_value('Address',{'address_title':title,'address_type':kind},'name')
        address=frappe.get_doc('Address',existing) if existing else frappe.get_doc(dict(doctype='Address',
            address_title=title,address_type=kind,links=[dict(link_doctype='Customer',link_name=customer)]))
        address.update(dict(address_line1=data['address_1'],address_line2=data.get('address_2'),city=data.get('city') or '-',
            state=data.get('state'),country=country,pincode=data.get('postcode'),email_id=billing.get('email'),phone=billing.get('phone')))
        address.save(ignore_permissions=True)
        result[kind]=address.name
    return result


def build_sales_order(order, config, inbox, parsed):
    approved_maps = mappings()
    matched = list(zip(parsed['lines'], d.match_order_lines([line['source'] for line in parsed['lines']], approved_maps)))
    matched = [(line,normalize(frappe.get_doc('Item',mapping['item_code']),mapping)) for line,mapping in matched]
    if inbox.sales_order:
        so = frappe.get_doc('Sales Order', inbox.sales_order)
        if so.docstatus != 0 or str(so.modified) != str(inbox.erp_modified):
            raise ValueError('ERP Sales Order was submitted or manually edited; review the Woo change')
        so.set('items', []); so.set('taxes', [])
    else:
        so = frappe.new_doc('Sales Order')
        so.naming_series = config.sales_order_series or 'WOO-.YYYY.-.#####'
        so.customer = customer_for(order, config)
    addresses=order_addresses(order,so.customer)
    created = (order.get('date_created') or today()).split('T')[0]
    so.update(dict(company=config.company,currency=config.currency,conversion_rate=1,
        transaction_date=created,delivery_date=add_days(today(),config.delivery_days or 0),
        selling_price_list=config.price_list,price_list_currency=config.currency,plc_conversion_rate=1,
        ignore_pricing_rule=1,taxes_and_charges=None,
        additional_discount_percentage=0,discount_amount=0,
        ws_woo_order_id=str(order['id']),po_no='WOO-'+str(order['id']),ws_woo_status=order['status'],
        ws_woo_paid=1 if order.get('date_paid') or order.get('date_paid_gmt') else 0,
        ws_woo_payment_method=order.get('payment_method') or '',customer_address=addresses.get('Billing'),
        shipping_address_name=addresses.get('Shipping') or addresses.get('Billing')))
    for line, mapping in matched:
        item = frappe.get_doc('Item', mapping['item_code'])
        if item.disabled or item.has_variants:
            raise ValueError('Mapped item is disabled or is a template')
        so.append('items', dict(item_code=item.name,item_name=item.item_name,description=item.description or item.item_name,
            qty=float(line['qty']),rate=float(line['rate']),price_list_rate=float(line['rate']),
            uom=mapping['sale_uom'],stock_uom=item.stock_uom,conversion_factor=mapping['conversion_factor'],
            warehouse=config.warehouse,delivery_date=so.delivery_date))
    for amount, account, description in [(parsed['tax'],config.tax_account,'WooCommerce tax (actual)'),
            (parsed['shipping'],config.shipping_account,'WooCommerce shipping'),
            (parsed['fees'],config.fee_account,'WooCommerce fees')]:
        if amount:
            so.append('taxes',dict(charge_type='Actual',account_head=account,tax_amount=float(amount),
                                  description=description,add_deduct_tax='Add',included_in_print_rate=0))
    from .document_rules import preserve_woo_total
    so.flags.ws_woo_import=True
    preserve_woo_total(so)
    so.save(ignore_permissions=True)
    difference = parsed['total'] - d.number(so.grand_total)
    if abs(difference) > d.number('.001'):
        raise ValueError('ERP Sales Order total does not match Woo: %s versus %s' % (d.money(so.grand_total),d.money(parsed['total'])))
    if difference:
        so.append('taxes',dict(charge_type='Actual',account_head=config.fee_account,
            tax_amount=float(difference),description='WooCommerce rounding adjustment',add_deduct_tax='Add'))
        so.save(ignore_permissions=True)
    if d.money(so.grand_total) != d.money(parsed['total']):
        raise ValueError('ERP total reconciliation failed after rounding')
    return so


def import_order(payload):
    config = settings()
    d.validate_source_order(payload)
    if not d.order_in_window(payload,config.order_since):
        return {'status':'Skipped','sales_order':None,'reason':'Order created before the configured UTC import start'}
    start_operation()
    with lock('order:'+str(payload.get('id'))):
        inbox, fresh = store_payload(payload)
        if not fresh:
            frappe.db.commit()
            return {'status':'Skipped','sales_order':inbox.sales_order,'reason':'Older Woo event'}
        if inbox.status=='Ignored':
            frappe.db.commit()
            return {'status':'Ignored','sales_order':inbox.sales_order}
        if inbox.status in ('Failed','Needs Review') and (int(inbox.attempts or 0)>=config.max_attempts or
                (inbox.next_retry and get_datetime(inbox.next_retry)>now_datetime())):
            frappe.db.commit()
            return {'status':inbox.status,'sales_order':inbox.sales_order,'error':inbox.error,'retry_deferred':True}
        inbox.attempts = int(inbox.attempts or 0) + 1
        frappe.db.sql('SAVEPOINT ws_woo_order')
        try:
            parsed = d.prepare_order(payload, config.currency)
            fingerprint = d.order_fingerprint(payload)
            if inbox.sales_order and frappe.db.get_value('Sales Order',inbox.sales_order,'docstatus') not in (0,1):
                raise ValueError('Linked ERP Sales Order was cancelled or deleted; review is required')
            if inbox.sales_order:
                customer=frappe.db.get_value('Sales Order',inbox.sales_order,'customer')
                if not d.customer_key_matches(frappe.db.get_value('Customer',customer,'ws_woo_customer_key'), payload, config.store_url):
                    raise ValueError('Woo customer identity changed; review the ERP buyer before applying this update')
            if inbox.sales_order and fingerprint == inbox.fingerprint:
                frappe.db.set_value('Sales Order', inbox.sales_order, {
                    'ws_woo_status':payload.get('status'),'ws_woo_paid':1 if payload.get('date_paid') or payload.get('date_paid_gmt') else 0,
                    'ws_woo_payment_method':payload.get('payment_method') or ''}, update_modified=False)
                inbox.status='Imported'; inbox.error=None; inbox.next_retry=None
                inbox.save(ignore_permissions=True); frappe.db.commit()
                return {'status':'Unchanged','sales_order':inbox.sales_order}
            so = build_sales_order(payload,config,inbox,parsed)
            inbox.sales_order=so.name; inbox.erp_modified=so.modified; inbox.fingerprint=fingerprint
            inbox.status='Imported'; inbox.error=None; inbox.next_retry=None
            log('Order import',payload['id'],'Success','Imported as draft '+so.name,{'grand_total':so.grand_total,'currency':so.currency})
        except Exception as exc:
            frappe.db.sql('ROLLBACK TO SAVEPOINT ws_woo_order')
            inbox.status = 'Needs Review' if isinstance(exc, (ValueError,frappe.ValidationError)) else 'Failed'
            inbox.error=str(exc)[:1000]
            inbox.next_retry=add_to_date(now_datetime(),seconds=d.retry_delay(inbox.attempts)) if inbox.attempts < config.max_attempts else None
            log('Order import',payload['id'],'Failed',inbox.error)
        inbox.save(ignore_permissions=True); frappe.db.commit()
        return {'status':inbox.status,'sales_order':inbox.sales_order,'error':inbox.error}


def retry_due(force=False):
    config=settings(); count=0
    condition='' if force else 'AND attempts < %(attempts)s AND (next_retry IS NULL OR next_retry <= %(now)s)'
    rows=frappe.db.sql('''SELECT name,payload,attempts,next_retry FROM `tabWS WooCommerce Order`
        WHERE status IN ('Pending','Failed','Needs Review') '''+condition+''' ORDER BY creation ASC LIMIT 100''',
        {'attempts':config.max_attempts,'now':now_datetime()},as_dict=True)
    for row in rows:
        if force or (int(row.attempts or 0) < config.max_attempts and (not row.next_retry or get_datetime(row.next_retry) <= now_datetime())):
            try:
                payload=json.loads(row.payload)
                if not isinstance(payload,dict) or str(payload.get('id'))!=str(row.name):
                    raise ValueError('Stored order identity is invalid')
                d.validate_source_order(payload)
            except (ValueError,TypeError):
                # Keep corrupted inbox data visible, but never let one row abort
                # all order processing and the independent price exports.
                with lock('order:'+str(row.name)):
                    inbox=frappe.get_doc(ORDER,row.name)
                    if inbox.payload!=row.payload or inbox.status not in ('Pending','Failed','Needs Review'):
                        continue
                    inbox.status='Needs Review';inbox.attempts=config.max_attempts;inbox.next_retry=None
                    inbox.error='Stored order payload or identity is unreadable. Restore it from WooCommerce before retrying. Stock is held conservatively; prices can continue.'
                    inbox.save(ignore_permissions=True)
                    log('Order import',row.name,'Failed',inbox.error)
                    frappe.db.commit()
            else:
                if d.order_in_window(payload,config.order_since):
                    import_order(payload)
                else:
                    with lock('order:'+str(row.name)):
                        inbox=frappe.get_doc(ORDER,row.name)
                        if inbox.payload!=row.payload or inbox.status not in ('Pending','Failed','Needs Review'):continue
                        inbox.status='Needs Review' if inbox.sales_order else 'Ignored'
                        inbox.attempts=config.max_attempts;inbox.next_retry=None
                        inbox.error='Order is older than the configured UTC import start; no historical Sales Order was created.'
                        inbox.save(ignore_permissions=True);log('Order review',row.name,'Skipped',inbox.error)
                        frappe.db.commit()
            count+=1
    return count
