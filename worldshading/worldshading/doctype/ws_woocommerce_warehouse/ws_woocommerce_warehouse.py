import frappe
from frappe.model.document import Document


class WSWooCommerceWarehouse(Document):
    def validate(self):
        self.validate_selection(include=True)

    def on_trash(self):
        self.validate_selection(include=False)

    def validate_selection(self,include):
        from worldshading.integration.woocommerce.common import SETTINGS,manager_only
        from worldshading.integration.woocommerce.inventory import stock_warehouses
        manager_only()  # Frappe v12 otherwise grants child API access implicitly.
        if (self.parent,self.parenttype,self.parentfield)!=(SETTINGS,SETTINGS,'stock_warehouses'):
            raise ValueError('Online stock warehouse must belong to WooCommerce Settings')
        stored=frappe.db.get_value(self.doctype,self.name,['parent','parenttype','parentfield'],as_dict=True)
        if stored and (stored.parent,stored.parenttype,stored.parentfield)!=(self.parent,self.parenttype,self.parentfield):
            raise ValueError('An existing stock warehouse row cannot be reassigned')
        config=frappe.get_single(SETTINGS)
        config.check_permission('write')
        rows=[row for row in config.stock_warehouses if row.name!=self.name]
        config.set('stock_warehouses',rows+([self] if include else []))
        stock_warehouses(config)
