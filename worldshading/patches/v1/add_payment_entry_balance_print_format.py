from __future__ import unicode_literals

import io

import frappe


PRINT_FORMAT_NAME = "Payment Receipt with Balance Snapshot"


def execute():
	template_path = frappe.get_app_path(
		"worldshading", "templates", "print_formats",
		"payment_entry_with_balance_snapshot.html"
	)
	with io.open(template_path, "r", encoding="utf-8") as template_file:
		html = template_file.read()

	if frappe.db.exists("Print Format", PRINT_FORMAT_NAME):
		print_format = frappe.get_doc("Print Format", PRINT_FORMAT_NAME)
	else:
		print_format = frappe.new_doc("Print Format")
		print_format.name = PRINT_FORMAT_NAME

	print_format.update({
		"doc_type": "Payment Entry",
		"module": "Worldshading",
		"standard": "No",
		"custom_format": 1,
		"print_format_type": "Jinja",
		"disabled": 0,
		"raw_printing": 0,
		"html": html,
		"css": "@media print { footer { page-break-after: always; } }",
	})
	print_format.save(ignore_permissions=True)
