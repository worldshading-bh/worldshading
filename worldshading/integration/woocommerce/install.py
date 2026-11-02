"""Connector-only setup; never invokes a full migration or imports demo records."""
import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from .environment import configured_urls,require_site,site_is_allowed

DOCTYPES=['ws_woocommerce_warehouse','ws_woocommerce_settings','ws_woocommerce_item_link',
    'ws_woocommerce_order','ws_woocommerce_sync_log','ws_woocommerce_sync_state']

CUSTOM_FIELDS={
    'Item': [
        dict(fieldname='ws_woocommerce_section',label='WooCommerce',fieldtype='Section Break',insert_after='item_defaults'),
        dict(fieldname='ws_woocommerce_links',label='WooCommerce Links',fieldtype='Table',options='WS WooCommerce Item Link',insert_after='ws_woocommerce_section'),
        dict(fieldname='ws_woocommerce_status',label='WooCommerce Sync Status',fieldtype='HTML',insert_after='ws_woocommerce_links'),
    ],
    'Sales Order': [
        dict(fieldname='ws_woo_order_id',label='WooCommerce Order ID',fieldtype='Data',unique=1,read_only=1,insert_after='po_no'),
        dict(fieldname='ws_woo_status',label='WooCommerce Status',fieldtype='Data',read_only=1,insert_after='ws_woo_order_id'),
        dict(fieldname='ws_woo_paid',label='WooCommerce Paid',fieldtype='Check',read_only=1,insert_after='ws_woo_status'),
        dict(fieldname='ws_woo_payment_method',label='WooCommerce Payment Method',fieldtype='Data',read_only=1,insert_after='ws_woo_paid'),
    ],
    'Customer': [dict(fieldname='ws_woo_customer_key',label='WooCommerce Customer Key',fieldtype='Data',unique=1,read_only=1,insert_after='customer_name')]
}


def preflight():
    """Read-only scope/compatibility check; review backup and DDL impact separately."""
    require_site()
    for slug in DOCTYPES:
        name=slug.replace('_',' ').title().replace('Ws Woocommerce','WS WooCommerce')
        if frappe.db.exists('DocType',name):
            existing=frappe.db.get_value('DocType',name,['module','custom'],as_dict=True)
            if existing.module!='Worldshading' or existing.custom:
                raise ValueError('Conflicting existing connector DocType: '+name)
    for doctype,fields in CUSTOM_FIELDS.items():
        for field in fields:
            existing=frappe.db.get_value('Custom Field',{'dt':doctype,'fieldname':field['fieldname']},['fieldtype','options'],as_dict=True)
            if existing and (existing.fieldtype!=field['fieldtype'] or (existing.options or '')!=(field.get('options') or '')):
                raise ValueError('Conflicting existing Custom Field: '+doctype+'.'+field['fieldname'])
    erp,store=configured_urls()
    return dict(erp_url=erp,store_url=store,doctypes=DOCTYPES,
        custom_fields={dt:[field['fieldname'] for field in fields] for dt,fields in CUSTOM_FIELDS.items()},
        requires_schema_review=True)


def execute():
    preflight()
    for slug in DOCTYPES:
        frappe.reload_doc('worldshading','doctype',slug,force=True)
    frappe.reload_doc('worldshading','page','ws_woocommerce_guide',force=True)
    frappe.reload_doc('worldshading','page','ws_woocommerce_link',force=True)
    create_custom_fields(CUSTOM_FIELDS,update=True)
    frappe.clear_cache()
    migrate_order_cutoff()
    migrate_item_links()
    frappe.db.commit()


def after_migrate():
    # A shared app checkout may serve unrelated sites. Do not install there.
    if site_is_allowed():execute()


def migrate_item_links():
    """One-way idempotent copy. Never resurrect links removed after migration."""
    from .item_links import LINK,TABLE,CONFIG_FIELDS,validate_item
    settings='WS WooCommerce Settings'
    if frappe.db.get_single_value(settings,'item_links_migrated'):
        return
    if not frappe.db.table_exists('WS WooCommerce Product Map'):
        frappe.db.set_value(settings,settings,'item_links_migrated',1,update_modified=False)
        return
    legacy=frappe.get_all('WS WooCommerce Product Map',fields=['*'])
    for previous in legacy:
        existing=frappe.db.get_value(LINK,previous.name,['parent','parenttype','parentfield'],as_dict=True)
        if existing:
            if existing.parent!=previous.item_code or existing.parenttype!='Item' or existing.parentfield!=TABLE:
                raise ValueError('Existing Woo child identity conflicts with migration')
            continue
        item=frappe.get_doc('Item',previous.item_code)
        values={field:previous.get(field) for field in CONFIG_FIELDS}
        values['__islocal']=1  # v12 otherwise issues UPDATE for a supplied child name.
        item.append(TABLE,values)
        validate_item(item)
        item.save(ignore_permissions=True)
        persisted=frappe.db.get_value(LINK,previous.name,['parent','parenttype','parentfield'],as_dict=True)
        if not persisted or persisted.parent!=previous.item_code or persisted.parenttype!='Item' or persisted.parentfield!=TABLE:
            raise ValueError('Woo child migration did not persist the expected Item link')
    # Old logs reference item codes. Associate only unambiguous historic targets.
    for previous in legacy:
        if sum(row.item_code==previous.item_code for row in legacy)==1:
            frappe.db.sql('''UPDATE `tabWS WooCommerce Sync Log` SET item_link=%s
                WHERE operation='Product sync' AND reference=%s AND COALESCE(item_link,'')='' ''',
                (previous.name,previous.item_code))
    frappe.db.set_value(settings,settings,'item_links_migrated',1,update_modified=False)


def migrate_order_cutoff(time_zone=None):
    """Expose an existing UTC cutoff in site time once, without changing its meaning."""
    from .timezones import utc_to_site
    settings = 'WS WooCommerce Settings'
    if frappe.db.get_single_value(settings, 'order_since_local'):
        return False
    value = frappe.db.get_single_value(settings, 'order_since')
    if not value:
        return False
    frappe.db.set_value(settings, settings, 'order_since_local', utc_to_site(value, time_zone), update_modified=False)
    return True


def upgrade_refinements():
    """Metadata-only release upgrade for an already installed connector; no core DDL."""
    preflight()
    for slug in DOCTYPES:
        name = slug.replace('_', ' ').title().replace('Ws Woocommerce', 'WS WooCommerce')
        if not frappe.db.exists('DocType', name):
            raise ValueError('Install the connector first; missing DocType: ' + name)
    for slug in DOCTYPES:
        frappe.reload_doc('worldshading', 'doctype', slug, force=True)
    frappe.reload_doc('worldshading', 'page', 'ws_woocommerce_guide', force=True)
    migrate_order_cutoff()
    frappe.clear_cache()
    frappe.db.commit()
    return dict(updated=True, cutoff_preserved=True, automatic_sync_changed=False)


def upgrade_linking():
    """Install the authenticated linking Page; no DocType or core field reload."""
    preflight()
    if not frappe.db.exists('DocType', 'WS WooCommerce Item Link'):
        raise ValueError('Install the WooCommerce connector before adding its linking Page')
    frappe.reload_doc('worldshading', 'page', 'ws_woocommerce_link', force=True)
    frappe.clear_cache()
    frappe.db.commit()
    return dict(updated=True, page='ws-woocommerce-link', automatic_sync_changed=False)


def upgrade_bulk_linking():
    """Reload connector Settings and linking Page only; never run migrate or tests."""
    preflight()
    if not frappe.db.exists('DocType','WS WooCommerce Item Link'):
        raise ValueError('Install the connector first')
    frappe.reload_doc('worldshading','doctype','ws_woocommerce_settings',force=True)
    frappe.reload_doc('worldshading','page','ws_woocommerce_link',force=True)
    frappe.reload_doc('worldshading','page','ws_woocommerce_guide',force=True)
    frappe.clear_cache()
    frappe.db.commit()
    return dict(updated=True,automatic_sync_changed=False,auto_link_skus_changed=False)
