from __future__ import unicode_literals

from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	create_custom_fields({
		"Payment Entry": [
			{
				"fieldname": "quotation",
				"label": "Quotation",
				"fieldtype": "Link",
				"options": "Quotation",
				"insert_after": "reference_date",
				"read_only": 1,
				"in_standard_filter": 1,
			},
		]
	}, update=True)
