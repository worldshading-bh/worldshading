# -*- coding: utf-8 -*-
"""Payment method chooser.

The customer decides here how to pay, because nobody could decide it earlier: a
Payment Request is raised by staff, who cannot know whether the customer holds a
Bahraini debit card or a credit card.

Read-only. Picking a method does nothing on its own -- the gateway session is only
created once the customer clicks through to `web.checkout`, which validates the
choice again server-side.
"""
from __future__ import unicode_literals

import frappe
from frappe import _
from frappe.utils import fmt_money

from worldshading.payments.gateways import available_methods
from worldshading.payments.utils import (
	_gateway_settings,
	get_transaction,
	link_blocked_reason,
)

no_cache = 1


def get_context(context):
	context.no_cache = 1
	context.title = _("Payment")

	token = frappe.form_dict.get("t")

	txn = None
	if token:
		try:
			txn = get_transaction(token)
		except frappe.DoesNotExistError:
			txn = None

	if not txn:
		context.update({
			"blocked": _(
				"We could not find this payment. Please use the link from your payment "
				"request, or contact us and quote the document you were paying for."
			),
			"methods": [],
		})
		return context

	context.token = txn.token
	context.amount = fmt_money(txn.amount, currency=txn.currency) if txn.amount else None
	context.reference = txn.reference_name

	# Already paid, cancelled, settled another way, or the link has aged out. Say so
	# here rather than letting the customer pick a method and fail at the bank.
	if txn.status == "Captured" or txn.settled:
		context.update({
			"blocked": _("This payment has already been received. Thank you."),
			"methods": [],
		})
		return context

	blocked = link_blocked_reason(txn)
	if blocked:
		context.update({"blocked": blocked, "methods": []})
		return context

	methods = [m for m in available_methods() if txn.currency in _currencies(m.gateway)]

	if not methods:
		context.update({
			"blocked": _(
				"No payment method is available for this document at the moment. "
				"Please contact us."
			),
			"methods": [],
		})
		return context

	router = _gateway_settings(txn.gateway)
	context.heading = (
		(router.get("heading") if router else None) or _("Choose how you would like to pay")
	)

	context.blocked = None
	context.methods = methods

	return context


def _currencies(gateway):
	"""What a gateway accepts. A gateway that cannot be loaded offers nothing."""
	settings = _gateway_settings(gateway)

	return getattr(settings, "supported_currencies", []) if settings else []
