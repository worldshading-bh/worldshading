# -*- coding: utf-8 -*-
"""Launcher for the MPGS hosted payment page.

MPGS does not hand back a URL to redirect to, the way BENEFIT does. It requires
Mastercard's Checkout JavaScript to be loaded from a page on our own site, which
then opens the hosted payment page. This page is that launcher and nothing more --
the customer sees it for a fraction of a second.

Card details are still entered on Mastercard's page, never here, so this changes
nothing about PCI scope.
"""
from __future__ import unicode_literals

import frappe
from frappe import _

from worldshading.payments import mpgs
from worldshading.payments.utils import get_transaction

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

	if not txn or not txn.session_id:
		# Nothing to launch. Send them somewhere that explains itself rather than
		# leaving a blank page with a dead script on it.
		context.update({"error": True, "result_url": "/payment-result?t=" + (token or "")})
		return context

	settings = mpgs.get_settings(txn.gateway)

	context.update({
		"error": False,
		"session_id": txn.session_id,
		# Served from the gateway host itself -- the library and the session must
		# come from the same deployment.
		"checkout_js": "{0}/static/checkout/checkout.min.js".format(
			(settings.mpgs_api_host or "").rstrip("/")
		),
		"result_url": "/payment-result?t=" + txn.token,
	})

	return context
