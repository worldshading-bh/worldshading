"""Transactional change hints and bounded background publishing of changed links."""
from datetime import datetime
from time import monotonic
import frappe
from frappe.utils import now_datetime,get_datetime
from .common import SETTINGS,log
from .item_links import LINK,TABLE
from .stock_holds import stock_holds,stock_orders
from .sync_state import STATE,StateStore,payload_hash
from .sync import product_payload,sync_product
from .environment import site_is_allowed

REMOTE_RECHECK_SECONDS=3600
MAX_PRODUCTS_PER_RUN=25
PRODUCT_WORK_SECONDS=90


def mark_items(item_codes,kind='stock'):
    """Inside the caller's business transaction: no commit or network."""
    codes=sorted(set(code for code in item_codes if code))
    if not codes or not site_is_allowed():return
    if not frappe.db.get_single_value(SETTINGS,'enabled') or not frappe.db.table_exists(STATE):return
    filters={'parent':['in',codes],'parenttype':'Item','parentfield':TABLE,'enabled':1}
    if kind in ('stock','price'):filters['sync_'+kind]=1
    rows=frappe.get_all(LINK,filters=filters,fields=['name','parent'],order_by='name asc')
    for row in rows:
        frappe.db.sql('''INSERT INTO `tabWS WooCommerce Sync State`
            (name,creation,modified,owner,modified_by,docstatus,idx,item_link,item_code,requested_version,synced_version,attempts)
            VALUES (%s,NOW(6),NOW(6),'Administrator','Administrator',0,0,%s,%s,1,0,0)
            ON DUPLICATE KEY UPDATE requested_version=requested_version+1''',
            (row.name,row.name,row.parent))
    if rows:
        from .events import request_drain
        request_drain()


def stock_changed(doc,method=None):
    mark_items([doc.get('item_code')],'stock')


def sales_order_changed(doc,method=None):
    codes=[row.get('item_code') for key in ('items','packed_items') for row in doc.get(key) or []]
    # before_validate still sees saved rows, including removed lines.
    if doc.get('name'):
        for doctype in ('Sales Order Item','Packed Item'):
            codes.extend(row.item_code for row in frappe.get_all(doctype,filters={'parent':doc.name,'parenttype':'Sales Order'},fields=['item_code']))
    mark_items(codes,'stock')


def item_price_changed(doc,method=None):
    mark_items([doc.get('item_code')],'price')


def item_changed(doc,method=None):
    mark_items([doc.get('name')],'all')


def process_changes(mappings,config,client,snapshot=None,store=None,clock=None,sync_fn=None):
    from .snapshot import Snapshot
    now=clock or now_datetime();store=store or StateStore();sync_fn=sync_fn or sync_product
    states=store.prepare(mappings)
    snapshot=snapshot if snapshot is not None else Snapshot(mappings,config)
    result=dict(products=[],locally_unchanged=0,retry_deferred=0,batch_deferred=0,local_checked=len(mappings))
    context={};attempted=0;holds=stock_holds();started=monotonic()
    def priority(mapping):
        attempted_at=states[mapping['name']].get('last_attempt')
        return (get_datetime(attempted_at) if attempted_at else datetime.min,mapping['name'])
    for mapping in sorted(mappings,key=priority):
        name=mapping['name'];state=states[name];version=int(state.get('requested_version') or 0)
        if state.get('next_retry') and get_datetime(state['next_retry'])>now:
            result['retry_deferred']+=1;continue
        held=stock_orders(mapping['item_code'],holds) if mapping.get('sync_stock') else []
        if held and not mapping.get('sync_price'):
            store.hold(name,version)
            result['products'].append(dict(item_code=mapping['item_code'],status='Stock Held',stock_blocked=len(held),stock_orders=held,payload={}))
            continue
        counted=False
        try:
            effective=dict(mapping,sync_stock=0) if held else mapping
            payload=product_payload(effective,config,snapshot=snapshot)
            digest=payload_hash(mapping,payload)
            verified=state.get('last_verified')
            due=not verified or (now-get_datetime(verified)).total_seconds()>=REMOTE_RECHECK_SECONDS
            if not due and not state.get('attempts') and digest==state.get('last_payload_hash'):
                result['locally_unchanged']+=1
                if version!=int(state.get('synced_version') or 0):store.ack(name,version,digest,now,verified=False)
                continue
            if attempted>=MAX_PRODUCTS_PER_RUN or monotonic()-started>=PRODUCT_WORK_SECONDS:
                result['batch_deferred']+=1;continue
            attempted+=1;counted=True
            # Snapshot selects work only. Recompute inside the product lock so
            # orders/reservations committed during earlier HTTP calls are read.
            outcome=sync_fn(mapping,config,client,context=context)
            if outcome['status'] in ('Updated','Unchanged'):
                store.ack(name,version,payload_hash(mapping,outcome['payload']),now)
            elif outcome['status']=='Stock Held':store.hold(name,version)
            else:store.fail(name,version,outcome.get('error') or 'Product sync failed',now)
        except Exception as exc:
            if not counted:
                if attempted>=MAX_PRODUCTS_PER_RUN or monotonic()-started>=PRODUCT_WORK_SECONDS:
                    result['batch_deferred']+=1;continue
                attempted+=1
            store.fail(name,version,exc,now)
            log('Product sync',mapping['item_code'],'Failed',str(exc),item_link=name)
            frappe.db.commit()
            outcome=dict(item_code=mapping['item_code'],status='Failed',error=str(exc))
        result['products'].append(outcome)
    return result
