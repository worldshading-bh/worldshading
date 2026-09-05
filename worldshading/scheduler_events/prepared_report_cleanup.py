from __future__ import unicode_literals

import frappe
from frappe.model.delete_doc import (
	check_if_doc_is_dynamically_linked,
	check_if_doc_is_linked,
)
from frappe.utils import add_days, cint, now_datetime


def execute():
	settings = frappe.get_single('WS Settings')
	if not cint(settings.get('enable_prepared_report_cleanup')):
		return

	expiry_days = cint(settings.get('expiry_days'))
	if expiry_days <= 0:
		frappe.log_error(
			'Expiry Days must be greater than zero in WS Settings.',
			'Prepared Report Cleanup Configuration'
		)
		return

	expiry_date = add_days(now_datetime(), -expiry_days)
	prepared_reports = frappe.get_all(
		'Prepared Report',
		filters={'creation': ['<', expiry_date]},
		fields=['name'],
		order_by='creation asc',
		limit_page_length=0
	)

	for report in prepared_reports:
		try:
			prepared_report = frappe.get_doc('Prepared Report', report.name)

			# Prepared Report removes its result attachment in on_trash, before
			# Frappe's normal link validation. Check links first so a retained
			# report always keeps its result file.
			check_if_doc_is_linked(prepared_report)
			check_if_doc_is_dynamically_linked(prepared_report)

			frappe.delete_doc(
				'Prepared Report',
				report.name,
				ignore_permissions=True
			)
		except frappe.LinkExistsError:
			# Linked reports are business records and must be retained.
			continue
		except Exception:
			frappe.log_error(
				frappe.get_traceback(),
				'Prepared Report Cleanup Error: {0}'.format(report.name)
			)
