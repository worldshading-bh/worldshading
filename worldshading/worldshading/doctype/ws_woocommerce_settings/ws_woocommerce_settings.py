import frappe
from frappe.model.document import Document
from worldshading.integration.woocommerce.environment import validate_store,webhook_url


class WSWooCommerceSettings(Document):
    def validate(self):
        # Editing a stale settings form must not roll the polling cursor backwards.
        for field in ['poll_cursor','last_run','last_result','item_links_migrated','sku_link_cursor']:
            self.set(field,frappe.db.get_single_value(self.doctype,field))
        from worldshading.integration.woocommerce.timezones import update_order_cutoff
        update_order_cutoff(self)
        self.store_url = validate_store(self.store_url)
        if self.enabled and frappe.db.get_single_value('Woocommerce Settings', 'enable_sync'):
            frappe.throw('The legacy WooCommerce connector must be disabled')
        from worldshading.integration.woocommerce.inventory import stock_warehouses
        stock_warehouses(self)
        prices = frappe.db.get_value('Price List', self.price_list, ['currency','selling','enabled'], as_dict=True)
        if not prices or not prices.selling or not prices.enabled or prices.currency != self.currency:
            frappe.throw('Choose an enabled selling price list in the connector currency')
        if frappe.db.get_value('Company', self.company, 'default_currency') != self.currency:
            frappe.throw('This connector requires company and Woo store currencies to match')
        for field in ['tax_account','shipping_account','fee_account']:
            account = frappe.db.get_value('Account', self.get(field), ['company','is_group','disabled'], as_dict=True)
            if not account or account.company != self.company or account.is_group or account.disabled:
                frappe.throw('Choose an active ledger account in this company: '+field)
        if self.safety_stock < 0 or self.delivery_days < 0 or not 1 <= int(self.max_attempts or 0) <= 20:
            frappe.throw('Invalid safety stock, delivery lead time or retry limit')
        self.webhook_url = webhook_url()
