# -*- coding: utf-8 -*-
from __future__ import unicode_literals
import frappe


def sync_quotation_link(doc, method=None):
	"""After Quotation is saved, link it on the source Service Visit."""

	if not doc.get("service_visit"):
		return

	frappe.db.set_value(
		"Service Visit",
		doc.service_visit,
		"quotation",
		doc.name,
		update_modified=False,
	)


def mark_visit_quotation_created(doc, method=None):
	"""After Quotation submit, move the linked Service Visit to Quotation Created."""

	if not doc.get("service_visit"):
		return

	_set_service_visit_workflow_state(
		doc.service_visit,
		"Quotation Created",
		["Pending Quotation"],
		"Quotation <b>{0}</b> was created and submitted.".format(doc.name)
	)


def sync_quotation_status_to_visit(doc, method=None):
	"""Sync final Quotation status changes back to the linked Service Visit."""

	if not doc.get("service_visit"):
		return

	if doc.get("status") == "Lost":
		_set_service_visit_workflow_state(
			doc.service_visit,
			"Lost",
			["Pending Quotation", "Quotation Created"],
			"Quotation <b>{0}</b> was marked as Lost.".format(doc.name)
		)

	elif doc.get("status") == "Expired":
		_set_service_visit_workflow_state(
			doc.service_visit,
			"Expired",
			["Pending Quotation", "Quotation Created"],
			"Quotation <b>{0}</b> was marked as Expired.".format(doc.name)
		)

	elif doc.get("status") == "Open":
		_set_service_visit_workflow_state(
			doc.service_visit,
			"Quotation Created",
			["Lost", "Expired"],
			"Quotation <b>{0}</b> was reopened.".format(doc.name)
		)


def _set_service_visit_workflow_state(service_visit, target_state, allowed_current_states=None, comment=None):
	sv = frappe.get_doc("Service Visit", service_visit)

	if allowed_current_states and sv.workflow_state not in allowed_current_states:
		return

	sv.db_set("workflow_state", target_state)

	if comment:
		frappe.get_doc({
			"doctype": "Comment",
			"comment_type": "Comment",
			"reference_doctype": "Service Visit",
			"reference_name": sv.name,
			"content": comment
		}).insert(ignore_permissions=True)


def sync_sales_order_link(doc, method=None):
	"""After Sales Order is saved, link it on the source Service Visit."""

	if not doc.get("service_visit"):
		return

	frappe.db.set_value(
		"Service Visit",
		doc.service_visit,
		"sales_order",
		doc.name,
		update_modified=False,
	)


def mark_visit_ordered(doc, method=None):
	"""After Sales Order submit, move the linked Service Visit to Ordered."""

	if not doc.get("service_visit"):
		return

	_set_service_visit_workflow_state(
		doc.service_visit,
		"Ordered",
		["Pending Quotation", "Quotation Created", "Lost", "Expired"],
		"Sales Order <b>{0}</b> was submitted.".format(doc.name)
	)


def sync_sales_invoice_link(doc, method=None):
	"""After Sales Invoice is saved, link it on the source Service Visit."""

	if not doc.get("service_visit") or doc.get("is_return"):
		return

	frappe.db.set_value(
		"Service Visit",
		doc.service_visit,
		"sales_invoice",
		doc.name,
		update_modified=False,
	)


def mark_visit_invoiced(doc, method=None):
	"""After Sales Invoice submit, move the linked Service Visit to Invoiced."""

	if not doc.get("service_visit") or doc.get("is_return"):
		return

	_set_service_visit_workflow_state(
		doc.service_visit,
		"Invoiced",
		["Pending Quotation", "Quotation Created", "Lost", "Expired", "Ordered"],
		"Sales Invoice <b>{0}</b> was submitted.".format(doc.name)
	)


def mark_visit_pending_schedule_from_payment(doc, method=None):
	"""After Payment Entry submit, move the linked Service Visit to Pending Schedule."""

	if not doc.get("service_visit"):
		return

	_sync_service_visit_payment_row(doc)

	_set_service_visit_workflow_state(
		doc.service_visit,
		"Pending Schedule",
		["Pending Payment"],
		"Payment Entry <b>{0}</b> was submitted.".format(doc.name)
	)


def _sync_service_visit_payment_row(doc):
	service_visit = frappe.get_doc("Service Visit", doc.service_visit)

	payment_row = None

	for row in service_visit.payments:
		if row.payment_entry == doc.name:
			payment_row = row
			break

	if not payment_row:
		payment_row = service_visit.append("payments", {})

	payment_row.mode_of_payment = doc.get("mode_of_payment")
	payment_row.amount = doc.get("paid_amount") or doc.get("received_amount") or 0
	payment_row.paid = 1
	payment_row.payment_entry = doc.name
	payment_row.reference_no = doc.get("reference_no")

	_set_child_value_if_field_exists(
		payment_row,
		"date",
		doc.get("reference_date") or doc.get("posting_date")
	)

	_set_child_value_if_field_exists(
		payment_row,
		"reference_date",
		doc.get("reference_date")
	)

	_set_child_value_if_field_exists(
		payment_row,
		"pb_branch",
		doc.get("pb_branch")
	)

	_set_child_value_if_field_exists(
		payment_row,
		"pb_pos_profile",
		doc.get("pb_pos_profile")
	)

	if payment_row.meta.has_field("notes") and not payment_row.get("notes"):
		payment_row.notes = "Payment Entry {0}".format(doc.name)

	service_visit.save(ignore_permissions=True)


def _set_child_value_if_field_exists(row, fieldname, value):
	if value and row.meta.has_field(fieldname):
		row.set(fieldname, value)


def unlink_sales_invoice_on_cancel(doc, method=None):
	"""Before Sales Invoice cancel, fall back to the remaining linked sales stage."""

	if not doc.get("service_visit"):
		return

	sv_name = doc.service_visit
	sv = frappe.get_doc("Service Visit", sv_name)

	if sv.get("sales_invoice") == doc.name:
		frappe.db.set_value(
			"Service Visit",
			sv_name,
			"sales_invoice",
			None,
			update_modified=False,
		)

	if _is_submitted_link("Sales Order", sv.get("sales_order")):
		target_state = "Ordered"
	elif _is_submitted_link("Quotation", sv.get("quotation")):
		target_state = "Quotation Created"
	else:
		target_state = "Pending Quotation"

	_set_service_visit_workflow_state(
		sv_name,
		target_state,
		["Invoiced"],
		"Sales Invoice <b>{0}</b> was cancelled.".format(doc.name)
	)


def _is_submitted_link(doctype, name):
	if not name:
		return False

	return frappe.db.get_value(doctype, name, "docstatus") == 1


def unlink_quotation_from_visit(doc, method=None):
	"""Before Quotation is deleted, clear every Service Visit pointing to it."""

	for sv in _get_service_visits_linked_to_quotation(doc.name):
		frappe.db.set_value(
			"Service Visit",
			sv.name,
			"quotation",
			None,
			update_modified=False,
		)


def _get_service_visits_linked_to_quotation(quotation):
	return frappe.get_all(
		"Service Visit",
		filters={"quotation": quotation},
		fields=["name"]
	)


def unlink_sales_order_from_visit(doc, method=None):
	"""Before Sales Order is deleted, clear Service Visit sales_order if it points to this doc."""

	if not doc.get("service_visit"):
		return

	sv = doc.service_visit

	if frappe.db.get_value("Service Visit", sv, "sales_order") == doc.name:

		frappe.db.set_value(
			"Service Visit",
			sv,
			"sales_order",
			None,
			update_modified=False,
		)


def unlink_quotation_on_cancel(doc, method=None):
	"""Before Quotation is cancelled, clear every Service Visit pointing to it."""

	for sv in _get_service_visits_linked_to_quotation(doc.name):
		frappe.db.set_value(
			"Service Visit",
			sv.name,
			"quotation",
			None,
			update_modified=False,
		)

		_set_service_visit_workflow_state(
			sv.name,
			"Pending Quotation",
			["Quotation Created", "Lost", "Expired"],
			"Quotation <b>{0}</b> was cancelled.".format(doc.name)
		)


def unlink_sales_order_on_cancel(doc, method=None):
	"""Before Sales Order is cancelled, clear Service Visit sales_order link."""

	if not doc.get("service_visit"):
		return

	sv = doc.service_visit

	if frappe.db.get_value("Service Visit", sv, "sales_order") == doc.name:

		frappe.db.set_value(
			"Service Visit",
			sv,
			"sales_order",
			None,
			update_modified=False,
		)

		if frappe.db.get_value("Service Visit", sv, "quotation"):
			target_state = "Quotation Created"
		else:
			target_state = "Pending Quotation"

		_set_service_visit_workflow_state(
			sv,
			target_state,
			["Ordered"],
			"Sales Order <b>{0}</b> was cancelled.".format(doc.name)
		)

def unlink_service_visit_payment(doc, method):
    if not doc.get("service_visit"):
        return

    service_visit = frappe.get_doc(
        "Service Visit",
        doc.service_visit
    )

    updated_rows = []

    for row in service_visit.payments:

        if row.payment_entry != doc.name:
            updated_rows.append(row)

    service_visit.set("payments", updated_rows)

    service_visit.save(ignore_permissions=True)
