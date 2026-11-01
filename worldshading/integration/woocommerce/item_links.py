"""Item-owned Woo links. Conversion is always read from the Item's current UOMs."""
import frappe
from .domain import number

LINK='WS WooCommerce Item Link'
TABLE='ws_woocommerce_links'
CONFIG_FIELDS=['name','enabled','product_id','variation_id','sku','sale_uom','sync_stock','sync_price','clear_sale_price']


def normalize(item, row):
    product_id=int(row.get('product_id') or 0)
    variation_id=int(row.get('variation_id') or 0)
    if product_id<=0 or variation_id<0 or not str(row.get('sku') or '').strip():
        raise ValueError('Woo product ID, variation ID and SKU must be valid')
    uom=row.get('sale_uom')
    factors=[number(unit.conversion_factor) for unit in item.uoms if unit.uom==uom]
    if uom==item.stock_uom:
        factor=number(1)
    elif len(factors)==1 and factors[0]>0:
        factor=factors[0]
    else:
        raise ValueError('Choose a selling UOM with one positive conversion in Item UOMs: '+str(uom))
    result={field:row.get(field) for field in CONFIG_FIELDS}
    result.update(item_code=item.name,conversion_factor=float(factor),
                  product_id=product_id,variation_id=variation_id,target_key='%s:%s'%(product_id,variation_id))
    return result


def validate_item(item, method=None):
    if not frappe.db.table_exists(LINK):return
    rows=item.get(TABLE) or []
    # Preserve prior manager-only connector configuration permissions.
    if 'System Manager' not in frappe.get_roles():
        previous=frappe.get_all(LINK,filters=dict(parent=item.name,parenttype='Item',parentfield=TABLE),fields=CONFIG_FIELDS)
        def signature(values):
            return sorted(tuple(str(row.get(field) or '') for field in CONFIG_FIELDS) for row in values)
        if signature(previous)!=signature(rows):
            frappe.throw('System Manager access is required to change WooCommerce links',frappe.PermissionError)
    targets=set();stock_links=0
    for row in rows:
        mapping=normalize(item,row)
        target=mapping['target_key']
        if target in targets:
            raise ValueError('A Woo product or variation may only be linked once')
        targets.add(target)
        if frappe.db.exists(LINK,{'target_key':target,'name':['!=',row.get('name') or '']}):
            raise ValueError('This Woo product or variation is already linked to an Item')
        if row.get('enabled'):
            if item.disabled or item.has_variants or not item.is_sales_item:
                raise ValueError('Enable Woo links only on an active sellable Item or variant')
            stock_links+=int(bool(row.get('sync_stock')))
        row.set('target_key',target)
    if stock_links>1:
        raise ValueError('Only one enabled stock-sync link is supported per Item')


def get_mapping(name):
    row=frappe.get_doc(LINK,name)
    if row.parenttype!='Item' or row.parentfield!=TABLE:
        raise ValueError('Woo link must belong to the Item WooCommerce table')
    item=frappe.get_doc('Item',row.parent)
    return normalize(item,row)


def all_mappings():
    # Read target identities first. Normalize only the Item actually being used:
    # a stale UOM on another link must not stop all imports/exports.
    rows=frappe.get_all(LINK,filters=dict(enabled=1,parenttype='Item',parentfield=TABLE),fields=CONFIG_FIELDS+['parent'])
    return [dict(row,item_code=row.parent) for row in rows]


def status_for_item(item_code):
    """Return log-derived status; never save Item or its children."""
    rows=frappe.get_all(LINK,filters=dict(parent=item_code,parenttype='Item',parentfield=TABLE),fields=['name','sku','enabled'],order_by='idx asc')
    result=[]
    for row in rows:
        filters=dict(operation='Product sync',item_link=row.name)
        latest=frappe.get_all('WS WooCommerce Sync Log',filters=filters,fields=['creation','status','message'],order_by='creation desc',limit_page_length=1)
        success=frappe.get_all('WS WooCommerce Sync Log',filters=dict(filters,status=['in',['Success','Skipped']]),fields=['creation'],order_by='creation desc',limit_page_length=1)
        attempt=latest[0] if latest else {}
        result.append(dict(name=row.name,sku=row.sku,enabled=row.enabled,last_checked=attempt.get('creation'),
                           last_success=success[0].creation if success else None,
                           status=attempt.get('status') or 'Not checked',
                           error=attempt.get('message') if attempt.get('status')=='Failed' else None))
    return result
