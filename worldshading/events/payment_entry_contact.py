# -*- coding: utf-8 -*-
"""Populate customer contact details on Payment Entry."""
from __future__ import unicode_literals

import frappe


SOURCE_DOCTYPES = ("Sales Invoice", "Sales Order")


def set_payment_entry_contact(doc, method=None):
	"""Fill empty contact fields from references, then the Customer contact."""
	if doc.party_type != "Customer" or not doc.party:
		return

	whatsapp_no = doc.get("whatsapp_no")
	contact_mobile = doc.get("contact_mobile")

	if not whatsapp_no or not contact_mobile:
		source_values = _get_source_values(doc)
		whatsapp_no = whatsapp_no or source_values.get("whatsapp_no")
		contact_mobile = contact_mobile or source_values.get("contact_mobile")

	if not whatsapp_no or not contact_mobile:
		customer_values = _get_customer_contact_values(doc.party)
		whatsapp_no = whatsapp_no or customer_values.get("whatsapp_no")
		contact_mobile = contact_mobile or customer_values.get("contact_mobile")

	if not doc.get("whatsapp_no") and whatsapp_no:
		doc.whatsapp_no = whatsapp_no

	if not doc.get("contact_mobile") and contact_mobile:
		doc.contact_mobile = contact_mobile


def _get_source_values(doc):
	values = {}
	references = doc.get("references") or []

	# Prefer Sales Invoice over Sales Order, independent of child-row order.
	for source_doctype in SOURCE_DOCTYPES:
		for reference in references:
			if (
				reference.get("reference_doctype") != source_doctype
				or not reference.get("reference_name")
			):
				continue

			source_values = _get_document_contact_values(
				source_doctype, reference.get("reference_name")
			)
			values["whatsapp_no"] = (
				values.get("whatsapp_no") or source_values.get("whatsapp_no")
			)
			values["contact_mobile"] = (
				values.get("contact_mobile") or source_values.get("contact_mobile")
			)

			if values.get("whatsapp_no") and values.get("contact_mobile"):
				return values

	return values


def _get_document_contact_values(doctype, name):
	meta = frappe.get_meta(doctype)
	fieldnames = [
		fieldname for fieldname in ("whatsapp_no", "contact_mobile", "mobile_no")
		if meta.has_field(fieldname)
	]
	if not fieldnames:
		return {}

	values = frappe.db.get_value(doctype, name, fieldnames, as_dict=True) or {}
	return {
		"whatsapp_no": values.get("whatsapp_no"),
		"contact_mobile": values.get("contact_mobile") or values.get("mobile_no"),
	}


def _get_customer_contact_values(customer):
	customer_meta = frappe.get_meta("Customer")
	customer_fields = [
		fieldname
		for fieldname in (
			"customer_primary_contact", "whatsapp_no", "mobile_number", "mobile_no"
		)
		if customer_meta.has_field(fieldname)
	]
	customer_values = frappe.db.get_value(
		"Customer", customer, customer_fields, as_dict=True
	) or {}

	contact_values = {}
	primary_contact = customer_values.get("customer_primary_contact")
	if primary_contact:
		contact_values = _get_document_contact_values("Contact", primary_contact)

	return {
		"whatsapp_no": (
			contact_values.get("whatsapp_no")
			or contact_values.get("contact_mobile")
			or customer_values.get("whatsapp_no")
			or customer_values.get("mobile_number")
			or customer_values.get("mobile_no")
		),
		"contact_mobile": (
			contact_values.get("contact_mobile")
			or contact_values.get("whatsapp_no")
			or customer_values.get("mobile_number")
			or customer_values.get("mobile_no")
			or customer_values.get("whatsapp_no")
		),
	}
