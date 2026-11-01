import frappe
from frappe.model.document import Document


class WSWooCommerceItemLink(Document):
    def validate(self):
        # v12 grants child DocType permissions unconditionally. Direct child API
        # saves must enforce the same policy as saving the parent Item.
        self.require_manager()
        from worldshading.integration.woocommerce.item_links import TABLE,validate_item
        item=self.parent_item()
        rows=[row for row in item.get(TABLE) or [] if row.name!=self.name]
        item.set(TABLE,rows+[self])
        validate_item(item)

    def on_trash(self):
        self.require_manager()
        self.parent_item()

    def parent_item(self):
        from worldshading.integration.woocommerce.item_links import LINK,TABLE
        if self.parenttype!='Item' or self.parentfield!=TABLE:
            raise ValueError('Woo link must belong to the Item WooCommerce table')
        stored=frappe.db.get_value(LINK,self.name,['parent','parenttype','parentfield'],as_dict=True)
        if stored and (stored.parent!=self.parent or stored.parenttype!=self.parenttype or stored.parentfield!=self.parentfield):
            raise ValueError('An existing Woo link cannot be reassigned to another parent')
        item=frappe.get_doc('Item',self.parent)
        item.check_permission('write')
        return item

    def require_manager(self):
        if 'System Manager' not in frappe.get_roles():
            frappe.throw('System Manager access is required to change WooCommerce links',frappe.PermissionError)
