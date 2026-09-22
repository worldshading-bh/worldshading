from __future__ import unicode_literals

from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	create_custom_fields({
		"Payment Entry": [
			{
				"fieldname": "invoice_balance_snapshot_section",
				"label": "Invoice Balances After This Payment",
				"fieldtype": "Section Break",
				"insert_after": "references",
				"collapsible": 1,
			},
			{
				"fieldname": "invoice_balance_snapshot",
				"label": "Invoice Balance Snapshot",
				"fieldtype": "Table",
				"options": "Payment Entry Invoice Balance",
				"insert_after": "invoice_balance_snapshot_section",
				"read_only": 1,
			},
		]
	}, update=True)
