"""Session-authenticated Item linking; never publishes stock or prices."""
import re
from urllib.parse import urlsplit
import frappe
from frappe.utils import get_datetime
from .common import manager_only, settings, lock
from .client import from_settings
from .item_links import LINK, TABLE, normalize


def _check_source(config, source_host):
    if not isinstance(source_host,str) or source_host != urlsplit(config.store_url).hostname:
        raise ValueError('Open this linking popup from the configured WooCommerce store')


def _id(value, zero=False):
    text = str(value)
    if not re.fullmatch(r'[0-9]{1,12}', text) or (int(text) == 0 and not zero):
        raise ValueError('Choose a valid WooCommerce product or variation ID')
    return int(text)


def _eligible(item):
    if item.disabled or item.has_variants or not item.is_sales_item:
        raise ValueError('Choose an active sellable Item or Item variant')


def _existing(product_id, variation_id):
    row = frappe.db.get_value(LINK, {'target_key':'%s:%s' % (product_id, variation_id)},
        ['name','parent','parenttype','parentfield','sale_uom','sku','enabled'], as_dict=True)
    if row and (row.parenttype != 'Item' or row.parentfield != TABLE):
        raise ValueError('Existing WooCommerce link has an invalid owner; review it in ERPNext')
    return row


def _summary(row):
    if not row:
        return None
    frappe.get_doc('Item', row.parent).check_permission('read')
    return dict(item_code=row.parent, sale_uom=row.sale_uom, enabled=bool(int(row.enabled or 0)))


def _parent(client, product_id):
    parent = client.get('products/' + str(product_id))
    if not isinstance(parent, dict) or parent.get('id') != product_id or parent.get('type') not in ('simple','variable'):
        raise ValueError('Choose an existing simple or variable WooCommerce product')
    return parent


def _brief(product_id, row, variation):
    identity = _id(row.get('id'))
    sku = row.get('sku')
    if not isinstance(sku, str):
        raise ValueError('WooCommerce returned an invalid SKU')
    if variation and row.get('parent_id') not in (None, product_id):
        raise ValueError('WooCommerce variation belongs to another product')
    variation_id = identity if variation else 0
    label = ', '.join(str(a.get('option') or 'Any ' + str(a.get('name') or 'option'))
                      for a in row.get('attributes') or [] if isinstance(a, dict)) if variation else row.get('name')
    return dict(product_id=product_id, variation_id=variation_id, sku=sku, label=label or str(identity),
                linkable=bool(sku.strip()), link=_summary(_existing(product_id, variation_id)))


@frappe.whitelist()
def product_targets(product_id, page=1, variation_id=None, source_host=None):
    manager_only()
    product_id = _id(product_id)
    page = _id(page)
    if page > 100:
        raise ValueError('Product variation page is out of range')
    config = settings(False)
    _check_source(config,source_host)
    client = from_settings(config)
    parent = _parent(client, product_id)
    variable = parent['type'] == 'variable'
    direct = variation_id not in (None, '')
    if direct:
        variation_id = _id(variation_id, zero=True)
        if variable and not variation_id or not variable and variation_id:
            raise ValueError('Choose the exact variation for this product')
        rows = [client.get('products/%s/variations/%s' % (product_id,variation_id))] if variable else [parent]
        if not isinstance(rows[0],dict) or rows[0].get('id') != (variation_id or product_id):
            raise ValueError('WooCommerce returned a different variation')
    else:
        rows = client.get('products/%s/variations' % product_id, dict(per_page=25, page=page, orderby='id', order='asc')) if variable else [parent]
    if not isinstance(rows, list) or len(rows) > 25:
        raise ValueError('WooCommerce returned an invalid variation list')
    return dict(product_name=parent.get('name') or str(product_id), store_url=config.store_url,
                targets=[_brief(product_id,row,variable) for row in rows],
                page=page, has_more=not direct and variable and len(rows)==25)


@frappe.whitelist()
def search_items(doctype, txt, searchfield, start, page_len, filters=None):
    manager_only()
    settings(False)
    if doctype != 'Item':
        raise ValueError('Only Item search is supported')
    start = max(0, min(int(start or 0), 10000))
    page_len = max(1, min(int(page_len or 20), 20))
    term = '%' + str(txt or '')[:100] + '%'
    rows = frappe.get_list('Item', fields=['name','item_name'],
        filters=dict(disabled=0,has_variants=0,is_sales_item=1),
        or_filters=[['Item','name','like',term],['Item','item_name','like',term]],
        order_by='name asc',limit_start=start,limit_page_length=page_len)
    return [[row.name,row.item_name] for row in rows]


@frappe.whitelist()
def item_uoms(item_code):
    manager_only()
    settings(False)
    item = frappe.get_doc('Item', item_code)
    item.check_permission('read')
    _eligible(item)
    uoms = []
    for uom in [item.stock_uom] + sorted(set(unit.uom for unit in item.uoms if unit.uom and unit.uom != item.stock_uom)):
        try:
            normalized = normalize(item, dict(product_id=1,variation_id=0,sku='uom-check',sale_uom=uom))
        except ValueError:
            continue
        uoms.append(dict(uom=uom,conversion_factor=normalized['conversion_factor']))
    return dict(item_code=item.name,item_name=item.item_name,modified=str(item.modified),uoms=uoms)


def _remote_identity(client, product_id, variation_id):
    parent = _parent(client, product_id)
    if variation_id:
        if parent['type'] != 'variable':
            raise ValueError('Selected product does not have variations')
        row = client.get('products/%s/variations/%s' % (product_id,variation_id))
        if not isinstance(row,dict) or row.get('id') != variation_id or row.get('parent_id') not in (None,product_id):
            raise ValueError('WooCommerce variation does not belong to this product')
    else:
        if parent['type'] != 'simple':
            raise ValueError('Choose an explicit variation for this product')
        row = parent
    sku = row.get('sku')
    if not isinstance(sku,str) or not sku.strip():
        raise ValueError('Set a SKU on the WooCommerce product or variation first')
    return sku


@frappe.whitelist()
def save_link(item_code, sale_uom, product_id, variation_id, expected_sku, expected_modified, source_host=None):
    manager_only(write=True)
    config = settings(False)
    _check_source(config,source_host)
    product_id,variation_id = _id(product_id),_id(variation_id,zero=True)
    # Only GETs to the configured Woo store; browser-supplied identity is never authoritative.
    sku = _remote_identity(from_settings(config),product_id,variation_id)
    if sku != expected_sku:
        raise ValueError('WooCommerce SKU changed; reload the popup before linking')
    with lock('mapping:%s:%s' % (product_id,variation_id)):
        item = frappe.get_doc('Item', item_code)
        item.check_permission('write')
        _eligible(item)
        normalize(item,dict(product_id=product_id,variation_id=variation_id,sku=sku,sale_uom=sale_uom))
        existing = _existing(product_id,variation_id)
        if existing and existing.parent != item.name:
            raise ValueError('This WooCommerce target is already linked to another Item')
        row = next((r for r in item.get(TABLE) or [] if existing and r.name == existing.name),None)
        if existing and row is None:
            raise ValueError('Item links changed; reload the popup')
        if row and row.sku == sku and row.sale_uom == sale_uom:
            return dict(item_code=item.name,sale_uom=sale_uom,enabled=bool(int(row.enabled or 0)),unchanged=True,modified=str(item.modified))
        if row and row.enabled:
            raise ValueError('Disable this link in the ERPNext Item before changing its SKU or UOM')
        if not expected_modified or get_datetime(expected_modified) != get_datetime(item.modified):
            raise ValueError('The Item changed; select it again to reload its current UOMs before saving')
        if row:
            row.set('sku',sku)
            row.set('sale_uom',sale_uom)
        else:
            item.append(TABLE,dict(product_id=product_id,variation_id=variation_id,sku=sku,sale_uom=sale_uom,
                                   enabled=0,sync_stock=1,sync_price=0,clear_sale_price=0))
        previous = item.flags.get('ws_woo_link_only')
        item.flags['ws_woo_link_only'] = True
        try:
            item.save()
        finally:
            item.flags['ws_woo_link_only'] = previous
        frappe.db.commit()  # Persist before releasing the target lock.
        return dict(item_code=item.name,sale_uom=sale_uom,enabled=False,unchanged=False,modified=str(item.modified))
