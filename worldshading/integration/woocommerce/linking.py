"""Session-authenticated Item linking; never publishes stock or prices."""
import re
from urllib.parse import urlsplit
import frappe
from frappe.utils import get_datetime
from .common import manager_only, settings, lock
from .client import from_settings
from .link_persistence import persist
from .item_links import LINK, TABLE, CONFIG_FIELDS, normalize


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


def _parent(client, product_id, edit=False):
    endpoint = 'products/' + str(product_id)
    parent = client.get(endpoint,dict(context='edit')) if edit else client.get(endpoint)
    if not isinstance(parent, dict) or parent.get('id') != product_id or parent.get('type') not in ('simple','variable'):
        raise ValueError('Choose an existing simple or variable WooCommerce product')
    return parent


def _verified_target(client, product_id, variation_id):
    """Validate target identity. Variation responses may still inherit a parent SKU."""
    parent = _parent(client,product_id,edit=True)
    if bool(variation_id) != (parent['type']=='variable'):
        raise ValueError('Choose an exact sellable product or variation')
    row = client.get('products/%s/variations/%s' % (product_id,variation_id),dict(context='edit')) if variation_id else parent
    if not isinstance(row,dict) or row.get('id') != (variation_id or product_id):
        raise ValueError('WooCommerce returned a different product or variation')
    if variation_id and row.get('parent_id') not in (None,product_id):
        raise ValueError('WooCommerce variation belongs to another product')
    if not isinstance(row.get('sku'),str):
        raise ValueError('WooCommerce returned an invalid SKU')
    return parent,row


def _sku_identity(client, sku):
    # SKU filtering includes variations in Woo REST v3. Commas can expand the
    # filter, so compare the exact stored value and reject incomplete results.
    rows = client.get('products',dict(sku=sku,context='edit',per_page=100,page=1))
    if not isinstance(rows,list) or len(rows)>=100 or any(not isinstance(r,dict) for r in rows):
        raise ValueError('SKU lookup was incomplete; choose the product in WooCommerce')
    matches = [r for r in rows if r.get('sku')==sku]
    if len(matches)!=1:
        raise ValueError('SKU must identify exactly one WooCommerce product or variation')
    row = matches[0]
    if row.get('type')=='simple':
        return _id(row.get('id')),0
    if row.get('type')=='variation':
        return _id(row.get('parent_id')),_id(row.get('id'))
    raise ValueError('This SKU belongs to a parent or unsupported product; choose an exact variation')


@frappe.whitelist()
def find_by_sku(sku):
    """Read-only discovery. IDs are filled by the server, never saved here."""
    manager_only()
    config = settings(False)
    if not isinstance(sku,str) or not sku.strip() or len(sku)>140:
        raise ValueError('Enter a WooCommerce SKU of up to 140 characters')
    client = from_settings(config)
    product_id,variation_id = _sku_identity(client,sku)
    parent,row = _verified_target(client,product_id,variation_id)
    if row['sku'] != sku or variation_id and sku==parent.get('sku'):
        raise ValueError('Woo SKU changed or is inherited; reload before linking')
    return dict(product_name=parent.get('name') or str(product_id),store_url=config.store_url,
                source_host=urlsplit(config.store_url).hostname,page=1,has_more=False,
                targets=[_brief(product_id,row,bool(variation_id))])


@frappe.whitelist()
def match_item(product_id, variation_id, source_host):
    """Suggest one existing Item; never create links or select an arbitrary UOM."""
    manager_only()
    config = settings(False)
    _check_source(config,source_host)
    product_id,variation_id = _id(product_id),_id(variation_id,zero=True)
    if _existing(product_id,variation_id):
        return dict(item_code=None,reason='Already linked. Reload to view its current Item.')
    client = from_settings(config)
    parent,row = _verified_target(client,product_id,variation_id)
    sku = row['sku']
    if not sku.strip() or variation_id and sku==parent.get('sku'):
        return dict(item_code=None,reason='This variation has no verified own SKU. Choose its ERPNext Item manually.')
    if _sku_identity(client,sku)!=(product_id,variation_id):
        raise ValueError('SKU identifies a different WooCommerce target')
    matches = frappe.get_list('Item',fields=['name','item_code'],filters=dict(item_code=sku,disabled=0,has_variants=0,is_sales_item=1),limit_page_length=2)
    # MariaDB equality can be case-insensitive; automatic matching is exact.
    if len(matches)!=1 or matches[0].item_code != sku:
        return dict(item_code=None,reason='No exact active ERP Item Code matches this SKU. Choose an Item manually.')
    item = frappe.get_doc('Item',matches[0].name)
    item.check_permission('read')
    _eligible(item)
    if frappe.db.exists(LINK,dict(parent=item.name,parenttype='Item',parentfield=TABLE,
                                  target_key=['!=','%s:%s' % (product_id,variation_id)])):
        return dict(item_code=None,reason='The matching Item has another WooCommerce link. Review it before linking manually.')
    return dict(item_code=item.name,reason='Exact SKU / Item Code match found. Confirm the selling UOM and save the link.')


def _brief(product_id, row, variation, parent_sku=''):
    identity = _id(row.get('id'))
    returned_sku = row.get('sku')
    if not isinstance(returned_sku, str):
        raise ValueError('WooCommerce returned an invalid SKU')
    sku = returned_sku or (parent_sku if variation else '')
    if not isinstance(sku,str):
        raise ValueError('WooCommerce returned an invalid parent SKU')
    if variation and row.get('parent_id') not in (None, product_id):
        raise ValueError('WooCommerce variation belongs to another product')
    variation_id = identity if variation else 0
    label = ', '.join(str(a.get('option') or 'Any ' + str(a.get('name') or 'option'))
                      for a in row.get('attributes') or [] if isinstance(a, dict)) if variation else row.get('name')
    return dict(product_id=product_id, variation_id=variation_id, sku=sku, sku_inherited=bool(variation and (not returned_sku or returned_sku==parent_sku)),label=label or str(identity),
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
        rows = [client.get('products/%s/variations/%s' % (product_id,variation_id),dict(context='edit'))] if variable else [parent]
        if not isinstance(rows[0],dict) or rows[0].get('id') != (variation_id or product_id):
            raise ValueError('WooCommerce returned a different variation')
    else:
        rows = client.get('products/%s/variations' % product_id, dict(context='edit',per_page=25, page=page, orderby='id', order='asc')) if variable else [parent]
    if not isinstance(rows, list) or len(rows) > 25:
        raise ValueError('WooCommerce returned an invalid variation list')
    return dict(product_name=parent.get('name') or str(product_id), store_url=config.store_url,
                targets=[_brief(product_id,row,variable,parent.get('sku') or '') for row in rows],
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
    return dict(item_code=item.name,item_name=item.item_name,modified=str(item.modified),uoms=uoms,
                default_uom=item.get('sales_uom') if any(u['uom']==item.get('sales_uom') for u in uoms) else uoms[0]['uom'] if len(uoms)==1 else '')


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
        before={key:row.get(key) for key in CONFIG_FIELDS} if row else None
        if row:
            row.set('sku',sku)
            row.set('sale_uom',sale_uom)
        else:
            row=item.append(TABLE,dict(product_id=product_id,variation_id=variation_id,sku=sku,sale_uom=sale_uom,
                                   enabled=0,sync_stock=1,sync_price=0,clear_sale_price=0))
        persist(item,row,expected_modified,before)
        frappe.db.commit()  # Persist before releasing the target lock.
        return dict(item_code=item.name,sale_uom=sale_uom,enabled=False,unchanged=False,modified=str(item.modified))


@frappe.whitelist()
def product_sheet(product_id, source_host, page=1):
    """One bounded page of a parent product, irrespective of the launching variation."""
    data=product_targets(product_id,page=page,source_host=source_host)
    from .bulk_linking import candidate
    for target in data['targets']:
        if not target['link']:
            target['suggestion']=candidate(target)
    return data
