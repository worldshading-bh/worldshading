# -*- coding: utf-8 -*-
"""Customer-facing outcome page for an online payment.

Reads state only. Every decision about whether a payment succeeded was already made
in the callback handlers -- this page must never be able to change an outcome, because
its URL is in the customer's browser history and can be reloaded at will.
"""
from __future__ import unicode_literals

import frappe
from frappe import _

no_cache = 1

# Deliberately terse. The customer does not need our vocabulary, and a bank decline
# reason is not ours to relay in detail.
MESSAGES = {
	"Captured": (
		"success",
		"Payment received",
		"Thank you. Your payment has been received and a receipt will follow by email.",
	),
	"Redirected": (
		"pending",
		"Payment in progress",
		"We have not had confirmation from the bank yet. If you completed the payment, "
		"please give it a minute and refresh this page before trying again.",
	),
	"Initiated": (
		"pending",
		"Payment not completed",
		"This payment was not completed. You can use your payment link again to retry.",
	),
	"Cancelled": (
		"failed",
		"Payment cancelled",
		"The payment was cancelled. You can use your payment link again when you are ready.",
	),
	"Denied By Risk": (
		"failed",
		"Payment declined",
		"The payment was declined. Please try again later, or contact your bank.",
	),
	"Voided": (
		"failed",
		"Payment reversed",
		"The payment was reversed and you have not been charged. Please try again, or "
		"contact us if this keeps happening.",
	),
	"Failed": (
		"failed",
		"Payment not completed",
		"The payment was not completed and you have not been charged. Please try again, "
		"or contact us if this keeps happening.",
	),
}

UNKNOWN = (
	"failed",
	"Payment reference not recognised",
	"We could not find this payment. Please use the link from your payment request, or "
	"contact us and quote the document you were paying for.",
)


def get_context(context):
	context.no_cache = 1
	context.title = _("Payment")

	token = frappe.form_dict.get("t")

	txn = None
	if token:
		# The link may have several attempts behind it -- a decline, then a retry.
		# get_transaction() returns the captured one if there is one, else the most
		# recent, which is what the customer should be shown either way.
		from worldshading.payments.utils import get_transaction

		try:
			txn = get_transaction(token)
		except frappe.DoesNotExistError:
			txn = None

	if not txn:
		state, heading, message = UNKNOWN
		context.update({
			"state": state,
			"heading": heading,
			"message": message,
			"reference": None,
			"amount": None,
		})
		return context

	state, heading, message = MESSAGES.get(txn.status, MESSAGES["Failed"])

	# A link that can no longer be used needs its own explanation -- otherwise a
	# customer whose invoice was settled in cash sees "Payment not completed" and
	# tries again, which is exactly what the guard exists to prevent.
	if txn.status != "Captured":
		from worldshading.payments.utils import link_blocked_reason

		blocked = link_blocked_reason(txn)
		if blocked:
			state, heading, message = "failed", _("This payment link is closed"), blocked

	context.update({
		"state": state,
		"heading": heading,
		"message": message,
		# Shown so the customer has something to quote if they call us. The gateway
		# payment ID is the reference the bank's own support desk will ask for.
		"reference": txn.payment_id or txn.track_id,
		"amount": frappe.utils.fmt_money(txn.amount, currency=txn.currency) if txn.amount else None,
		"is_paid": txn.status == "Captured",
	})

	return context
