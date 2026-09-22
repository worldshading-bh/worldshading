# -*- coding: utf-8 -*-
"""Control automatic Payment Request email behavior."""
from __future__ import unicode_literals

import frappe


def mute_automatic_email_on_submit(doc, method=None):
	"""Submit inward Payment Requests without sending the core email."""
	if doc.payment_request_type == "Inward":
		doc.flags.mute_email = True


def generate_payment_url_without_email(doc, method=None):
	"""Generate the submitted request URL without triggering an email."""
	if (
		doc.payment_request_type != "Inward"
		or not doc.payment_gateway
	):
		return

	try:
		if not doc.payment_url:
			doc.set_payment_request_url()

		set_payment_link_token(doc)
	except Exception:
		frappe.log_error(
			frappe.get_traceback(),
			"Payment Request URL generation failed: {0}".format(doc.name),
		)


def set_payment_link_token(doc):
	"""Copy the canonical gateway link token onto the Payment Request."""
	transactions = frappe.get_all(
		"WS Payment Transaction",
		filters={"payment_request": doc.name},
		fields=["token"],
		order_by="creation desc",
		limit_page_length=1,
	)

	if not transactions or not transactions[0].token:
		return

	token = transactions[0].token
	doc.token = token
	frappe.db.set_value(
		"Payment Request",
		doc.name,
		"token",
		token,
		update_modified=False,
	)
