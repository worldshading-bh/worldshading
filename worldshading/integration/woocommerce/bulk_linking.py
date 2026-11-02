"""Bounded catalog matching. Preview never writes; application never publishes."""
import json
from datetime import timedelta
from time import monotonic
from urllib.parse import urlsplit
import frappe
from frappe.utils import get_datetime, now_datetime
from .common import manager_only, settings, lock, log, SETTINGS, start_operation
from .client import from_settings
from .item_links import LINK, TABLE, normalize
from .linking import _id, _existing, _eligible, _verified_target, _sku_identity


def selling_uom(item):
    units=[]
    for unit in [item.stock_uom] + [r.uom for r in item.uoms or []]:
        if not unit or unit in units:continue
        try:normalize(item,dict(product_id=1,variation_id=0,sku='check',sale_uom=unit))
        except ValueError:continue
        units.append(unit)
    preferred=item.get('sales_uom')
    if preferred:
        if preferred not in units:raise ValueError('Sales UOM needs a valid Item conversion')
        return preferred
    if len(units)!=1:raise ValueError('Choose a Sales UOM in the Item; multiple or missing valid UOMs')
    return units[0]


def candidate(target):
    result=dict(target,status='Skipped',reason='',item_code=None,sale_uom=None,modified=None)
    if _existing(target['product_id'],target['variation_id']):
        result['reason']='Already linked; existing link preserved';return result
    sku=target['sku']
    if not sku.strip() or target.get('sku_inherited'):
        result['reason']='No own SKU';return result
    matches=frappe.get_list('Item',fields=['name','item_code'],filters=dict(item_code=sku,disabled=0,has_variants=0,is_sales_item=1),limit_page_length=2)
    if len(matches)!=1 or matches[0].item_code!=sku:
        result['reason']='No exact active Item Code match';return result
    item=frappe.get_doc('Item',matches[0].name)
    item.check_permission('read');_eligible(item)
    result['item_code']=item.name
    result['modified']=str(item.modified)
    result['status']='Review'
    if frappe.db.exists(LINK,dict(parent=item.name,parenttype='Item',parentfield=TABLE)):
        result['reason']='Item already has a WooCommerce link';return result
    try:result['sale_uom']=selling_uom(item)
    except ValueError as exc:
        result['reason']=str(exc);return result
    result.update(status='Ready',reason='Exact SKU / Item Code; valid selling UOM')
    return result


def catalog_chunk(config,client,page=1,variation_page=1):
    page,variation_page=_id(page),_id(variation_page)
    if page>100000 or variation_page>1000:raise ValueError('Catalog cursor is out of range')
    parents=client.get('products',dict(context='edit',per_page=1,page=page,orderby='id',order='asc'))
    if not isinstance(parents,list) or len(parents)>1:raise ValueError('Invalid catalog response')
    if not parents:return dict(rows=[],done=True,page=page,variation_page=variation_page)
    parent=parents[0]
    pid=_id(parent.get('id'))
    variable=parent.get('type')=='variable'
    rows=client.get('products/%s/variations'%pid,dict(context='edit',per_page=25,page=variation_page,orderby='id',order='asc')) if variable else [parent]
    if not isinstance(rows,list) or len(rows)>25:raise ValueError('Invalid variation response')
    results=[]
    for row in rows:
        vid=_id(row.get('id')) if variable else 0
        if row.get('parent_id') not in (None,pid):raise ValueError('Variation belongs to another parent')
        sku=row.get('sku')
        if not isinstance(sku,str):raise ValueError('Invalid WooCommerce SKU')
        target=dict(product_id=pid,variation_id=vid,sku=sku,
                    sku_inherited=bool(variable and (not sku or sku==parent.get('sku'))),
                    label=(parent.get('name') or str(pid)) + (' / '+', '.join(str(a.get('option') or '') for a in row.get('attributes') or []) if variable else ''))
        if parent.get('type') not in ('simple','variable'):
            results.append(dict(target,status='Skipped',reason='Unsupported product type'));continue
        results.append(candidate(target))
    more=variable and len(rows)==25
    return dict(rows=results,done=False,page=page if more else page+1,variation_page=variation_page+1 if more else 1)


@frappe.whitelist()
def preview(page=1,variation_page=1):
    manager_only()
    config=settings(False)
    return catalog_chunk(config,from_settings(config),page,variation_page)


def create_match(config,client,review):
    pid,vid=_id(review.get('product_id')),_id(review.get('variation_id'),zero=True)
    # Resolve current own SKU and its unique stored identity, not inherited display SKU.
    parent,target=_verified_target(client,pid,vid)
    sku=target['sku']
    if not sku.strip() or vid and sku==parent.get('sku') or sku!=review.get('sku'):
        raise ValueError('WooCommerce SKU changed or is inherited; preview again')
    if _sku_identity(client,sku)!=(pid,vid):raise ValueError('SKU is not unique for this target')
    with lock('mapping:%s:%s'%(pid,vid)):
        if _existing(pid,vid):return dict(status='Skipped',reason='Already linked; existing link preserved')
        current=candidate(dict(product_id=pid,variation_id=vid,sku=sku))
        if current['status']!='Ready':raise ValueError(current['reason'])
        if any(current.get(key)!=review.get(key) for key in ('item_code','sale_uom','modified')):
            raise ValueError('Item or selling UOM changed; preview again')
        item=frappe.get_doc('Item',current['item_code'])
        item.check_permission('write')
        # Frappe normal Item save retains timestamp/concurrency checks and all validation.
        if str(item.modified)!=current['modified']:raise ValueError('Item changed; preview again')
        item.append(TABLE,dict(product_id=pid,variation_id=vid,sku=sku,sale_uom=current['sale_uom'],enabled=1,sync_stock=1,sync_price=0,clear_sale_price=0))
        previous=item.flags.get('ws_woo_link_only');item.flags['ws_woo_link_only']=True
        try:item.save()
        finally:item.flags['ws_woo_link_only']=previous
        # A new active mapping is eligible for the normal stock worker. No remote writes here.
        from .changes import mark_items
        mark_items([item.name],'stock')
        log('Item linking',item.name,'Success','SKU matched; active stock-only link created',dict(product_id=pid,variation_id=vid))
        frappe.db.commit()
        return dict(status='Linked',item_code=item.name,sale_uom=current['sale_uom'])


def apply_rows(config,client,rows):
    results=[]
    for row in rows:
        try:
            result=create_match(config,client,row)
        except Exception as exc:
            frappe.db.rollback()
            result=dict(status='Failed',reason=str(exc))
            log('Item linking',row.get('item_code') or '%s:%s'%(row.get('product_id'),row.get('variation_id')),'Failed',str(exc))
            frappe.db.commit()
        results.append(dict(row,result=result,status=result['status'],reason=result.get('reason','')))
    return dict(rows=results)


@frappe.whitelist()
def apply(rows):
    manager_only(write=True)
    config=settings()  # Saving active mappings requires an enabled connector.
    if isinstance(rows,str):rows=json.loads(rows)
    if not isinstance(rows,list) or not 1<=len(rows)<=25 or any(not isinstance(r,dict) for r in rows):
        raise ValueError('Review and apply between 1 and 25 matches at a time')
    return apply_rows(config,from_settings(config),rows)


def recover(config):
    """Opt-in, bounded recovery work only. Never called by stock change events."""
    if not config.enabled or not config.automatic_sync or not config.get('auto_link_skus'):
        return dict(skipped=True)
    start_operation()
    with lock('sku-catalog'):
        raw=frappe.db.get_single_value(SETTINGS,'sku_link_cursor')
        cursor=json.loads(raw) if raw else dict(page=1,variation_page=1)
        due=cursor.get('next_scan')
        if due and get_datetime(due)>now_datetime():return dict(skipped=True)
        client=from_settings(config);started=monotonic();results=[]
        for unused in range(10):
            chunk=catalog_chunk(config,client,cursor.get('page',1),cursor.get('variation_page',1))
            ready=[r for r in chunk['rows'] if r['status']=='Ready']
            outcome=dict(rows=[])
            for row in ready:
                # Discovery may consume the budget. Always allow one candidate
                # so a slow but healthy catalog cannot starve this cursor forever.
                if outcome['rows'] and monotonic()-started>=60:break
                outcome['rows'].extend(apply_rows(config,client,[row])['rows'])
            results.extend(outcome['rows'])
            if len(outcome['rows'])<len(ready):break
            # Transient failures retry this chunk, idempotently preserving successes.
            if any(r['status']=='Failed' for r in outcome['rows']):break
            cursor=dict(page=chunk['page'],variation_page=chunk['variation_page'])
            if chunk['done']:cursor=dict(page=1,variation_page=1,next_scan=str(now_datetime()+timedelta(hours=1)))
            frappe.db.set_value(SETTINGS,SETTINGS,'sku_link_cursor',json.dumps(cursor),update_modified=False)
            frappe.db.commit()
            if chunk['done'] or monotonic()-started>=60:break
        return dict(rows=results)
