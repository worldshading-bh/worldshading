from __future__ import unicode_literals

from frappe import _


def get_data():
	return {

		# Required in Frappe v12
		"fieldname": "name",

		# Explicit custom field mappings
		"non_standard_fieldnames": {

			"Quotation": "service_visit",

			"Sales Order": "service_visit",

			"Sales Invoice": "service_visit",

			"Payment Entry": "service_visit",

		},

		"transactions": [

			{
				"label": _("Reference"),

				"items": [
					"Quotation",
					"Sales Order",
					"Sales Invoice",
					"Payment Entry"
				],
			},

		],

	}
