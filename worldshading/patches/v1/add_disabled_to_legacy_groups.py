from __future__ import unicode_literals

from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	create_custom_fields({
		"Item Group": {
			"fieldname": "disabled",
			"label": "Disabled",
			"fieldtype": "Check",
			"default": "0",
			"insert_after": "is_group",
			"description": "Disabled Item Groups are hidden from Link field searches and cannot be newly assigned to Items."
		},
		"Supplier Group": {
			"fieldname": "disabled",
			"label": "Disabled",
			"fieldtype": "Check",
			"default": "0",
			"insert_after": "is_group",
			"description": "Disabled Supplier Groups are hidden from Link field searches and cannot be newly assigned to Suppliers."
		}
	})
