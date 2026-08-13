# -*- coding: utf-8 -*-
"""Which gateway handles what, and how the customer is offered the choice.

The Payment Request is raised before anyone knows how the customer intends to pay --
staff cannot tell a debit card from a credit card in advance -- so the gateway cannot
be decided there. ERPNext insists a Payment Request has exactly one gateway, so we
give it a router: a Payment Gateway whose only job is to return the chooser page.

    Payment Request -> "WS Payments" -> /payment-methods -> Debit  -> Benefit
                                                         -> Credit -> KFH MPGS

The link is gateway-neutral; each ATTEMPT records the gateway that actually handled
it. A customer who tries Credit, fails, and retries with Debit produces two attempts
on two gateways under one link, and settlement, guards and reconciliation all keep
working untouched.

Adding a gateway means: a WS Payment Gateway row, a client module with `initiate()` /
`apply_result()`, and one entry in `client_for()`. Nothing else changes.
"""
from __future__ import unicode_literals

import frappe
from frappe import _
from frappe.utils import cint

# The router. Not a real gateway -- it takes no money and has no credentials.
ROUTER_GATEWAY = "WS Payments"


def client_for(gateway):
	"""The module that talks to a gateway.

	Imported lazily so a broken or half-built client cannot break the whole payments
	module at import time.
	"""
	from worldshading.payments import benefit, mpgs

	clients = {
		benefit.GATEWAY: benefit,
		mpgs.GATEWAY: mpgs,
	}

	client = clients.get(gateway)

	if not client:
		frappe.throw(_("No payment client is configured for {0}").format(gateway))

	return client


def settings_for(gateway):
	"""The gateway's Settings single, by the same convention Frappe uses."""
	from worldshading.payments.utils import _gateway_settings

	return _gateway_settings(gateway)


def available_methods():
	"""The payment methods to offer the customer, in display order.

	Driven by the gateway rows themselves rather than a separate list, so there is
	one place to enable a method and it cannot drift out of step with its
	credentials.
	"""
	from worldshading.worldshading.doctype.ws_payment_gateway.ws_payment_gateway import (
		enabled_gateways,
	)

	return [
		frappe._dict({
			"gateway": row.name,
			"label": row.method_label or row.name,
			"description": row.method_description or "",
			"sort_order": cint(row.sort_order),
		})
		for row in enabled_gateways()
	]


def validate_method(gateway):
	"""Guard the value that arrives from the chooser page.

	It comes from the customer's browser, so it is untrusted: only a gateway that is
	currently on offer may be selected.
	"""
	if not gateway:
		frappe.throw(_("Please choose a payment method"))

	if gateway not in [m.gateway for m in available_methods()]:
		frappe.throw(_("{0} is not available").format(gateway))

	return gateway


def deposit_account(gateway):
	"""Where this gateway's money should land.

	Falls back to None so ERPNext keeps whatever the Payment Request's own gateway
	account specified -- which is the router's, and almost certainly not what finance
	wants once there is more than one gateway.
	"""
	settings = settings_for(gateway)

	return settings.get("deposit_account") if settings else None
