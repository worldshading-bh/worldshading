# -*- coding: utf-8 -*-
"""One row per payment gateway.

Replaces the per-gateway Settings singles. Adding a gateway is now a record, not a
new doctype.

Frappe reaches this class through the Payment Gateway record:

    Payment Gateway "Benefit"
        gateway_settings   = "WS Payment Gateway"
        gateway_controller = "Benefit"          -> this row

which is the second branch of frappe.integrations.utils.get_payment_gateway_controller.
The first branch -- a Single named "<Gateway> Settings" -- is what we used before.

Why not put these fields on the core Payment Gateway doctype instead: ERPNext calls
methods on the controller (get_payment_url, validate_transaction_currency), and a
doctype's methods come from its own Python file. Payment Gateway's file lives in
frappe core and is `class PaymentGateway(Document): pass`. Frappe v13 added an
`override_doctype_class` hook that would have made that viable; v12 has no such hook,
so the only route would be editing Frappe itself.

See Documentation/payments/.
"""
from __future__ import unicode_literals

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import call_hook_method, get_url

from worldshading.payments.utils import create_transaction

TYPE_ROUTER = "Router"
TYPE_BENEFIT = "Benefit"
TYPE_MPGS = "KFH MPGS"

CHOOSER_PAGE = "/payment-methods"

# What each gateway type can take. Currencies are a property of the acquirer, not of
# a setting somebody can mistype.
CURRENCIES_BY_TYPE = {
	TYPE_BENEFIT: ["BHD"],
	TYPE_MPGS: ["BHD"],
}

BENEFIT_TEST_ENDPOINT = "https://test.benefit-gateway.bh/payment/API/hosted.htm"

# Production host per Integration Guide section 3.1. The guide names the host but not
# the full production path; confirm with BENEFIT before go-live.
BENEFIT_PRODUCTION_ENDPOINT = "https://www.benefit-gateway.bh/payment/API/hosted.htm"


class WSPaymentGateway(Document):
	def validate(self):
		if not self.enabled:
			return

		if self.gateway_type != TYPE_ROUTER:
			self.validate_payment_configuration()

		if self.gateway_type == TYPE_BENEFIT:
			self.validate_benefit_credentials()
		elif self.gateway_type == TYPE_MPGS:
			self.validate_mpgs_credentials()

	def on_update(self):
		# Deliberately NOT in validate(). The Payment Gateway record we create points
		# back here through gateway_controller, a Dynamic Link -- and during validate()
		# this row does not exist yet, so that link fails validation with
		# "Could not find Gateway Controller". After the save it resolves cleanly.
		self.register_payment_gateway()

	def register_payment_gateway(self):
		"""Create or repoint the Payment Gateway record so Frappe finds this row.

		frappe's create_payment_gateway() only inserts when missing, so an existing
		record keeps its empty gateway_settings/gateway_controller forever. We set
		them explicitly -- without them Frappe falls back to looking for a
		"<Gateway> Settings" single that no longer exists.
		"""
		if not frappe.db.exists("Payment Gateway", self.name):
			frappe.get_doc({
				"doctype": "Payment Gateway",
				"gateway": self.name,
				"gateway_settings": self.doctype,
				"gateway_controller": self.name,
			}).insert(ignore_permissions=True)
		else:
			frappe.db.set_value("Payment Gateway", self.name, {
				"gateway_settings": self.doctype,
				"gateway_controller": self.name,
			}, update_modified=False)

		call_hook_method("payment_gateway_enabled", gateway=self.name)

	# ------------------------------------------------------------------ credentials

	def validate_payment_configuration(self):
		missing = []

		if not self.method_label:
			missing.append(_("Method Label"))
		if not self.deposit_account:
			missing.append(_("Deposit Account"))
		if not self.mode_of_payment:
			missing.append(_("Mode of Payment"))

		if missing:
			frappe.throw(
				_("{0} cannot be enabled without: {1}").format(self.name, ", ".join(missing))
			)

		account_type = frappe.db.get_value("Account", self.deposit_account, "account_type")
		if account_type not in ("Bank", "Cash"):
			frappe.throw(
				_("Deposit Account {0} must have Account Type Bank or Cash.").format(
					self.deposit_account
				)
			)

	def validate_benefit_credentials(self):
		missing = []

		if not self.tranportal_id:
			missing.append(_("Tranportal ID"))
		if not self.get_password("tranportal_password", raise_exception=False):
			missing.append(_("Tranportal Password"))

		resource_key = self.get_password("resource_key", raise_exception=False)
		if not resource_key:
			missing.append(_("Terminal Resource Key"))

		if missing:
			frappe.throw(
				_("{0} cannot be enabled without: {1}").format(self.name, ", ".join(missing))
			)

		# Catch a truncated or padded key at save time, not when a customer is
		# already looking at a payment page.
		if len(resource_key) not in (16, 24, 32):
			frappe.throw(
				_("Terminal Resource Key must be 16, 24 or 32 characters (got {0}).").format(
					len(resource_key)
				)
			)

	def validate_mpgs_credentials(self):
		missing = []

		if not self.mpgs_merchant_id:
			missing.append(_("Merchant ID"))
		if not self.get_password("mpgs_api_password", raise_exception=False):
			missing.append(_("API Password"))
		if not self.mpgs_api_host:
			missing.append(_("API Host"))
		if not self.mpgs_api_version:
			missing.append(_("API Version"))
		if not self.get_password("mpgs_webhook_secret", raise_exception=False):
			missing.append(_("Webhook Notification Secret"))

		if missing:
			frappe.throw(
				_("{0} cannot be enabled without: {1}").format(self.name, ", ".join(missing))
			)

		if not self.mpgs_api_host.strip().lower().startswith("https://"):
			frappe.throw(_("MPGS API Host must use HTTPS."))

	def validate_enabled(self):
		if not self.enabled:
			frappe.throw(_("{0} is not enabled.").format(self.name))

	def get_endpoint(self):
		"""BENEFIT API endpoint. Anything but "Production" falls back to test, so an
		unexpected value sends money to the sandbox rather than the live bank."""
		if self.api_endpoint:
			return self.api_endpoint.strip()

		if self.environment == "Production":
			return BENEFIT_PRODUCTION_ENDPOINT

		return BENEFIT_TEST_ENDPOINT

	# -------------------------------------------------------------------- currency

	@property
	def supported_currencies(self):
		if self.gateway_type != TYPE_ROUTER:
			return CURRENCIES_BY_TYPE.get(self.gateway_type, [])

		# The router accepts whatever its enabled gateways accept. Computed, so it
		# cannot drift out of step and shrinks when one is switched off.
		currencies = set()
		for row in enabled_gateways():
			currencies.update(CURRENCIES_BY_TYPE.get(row.gateway_type, []))

		return sorted(currencies)

	def validate_transaction_currency(self, currency):
		supported = self.supported_currencies

		if not supported:
			frappe.throw(_("No payment gateway is currently enabled."))

		if currency not in supported:
			frappe.throw(
				_("Online payment is not available in {0}. Supported: {1}").format(
					currency, ", ".join(supported)
				)
			)

	# ----------------------------------------------------------------- payment link

	def get_payment_url(self, **kwargs):
		"""The link that goes into the Payment Request email.

		For the router that is our chooser page; the customer picks a method and the
		real gateway is recorded on the attempt. For a single gateway it is our
		checkout endpoint, which creates the bank session at click time -- a bank
		payment URL is short-lived and an email may be opened days later.
		"""
		self.validate_enabled()

		currency = kwargs.get("currency")
		self.validate_transaction_currency(currency)

		txn = create_transaction(
			gateway=self.name,
			amount=kwargs.get("amount"),
			currency=currency,
			reference_doctype=kwargs.get("reference_doctype"),
			reference_docname=kwargs.get("reference_docname"),
			payer_name=kwargs.get("payer_name"),
			payer_email=kwargs.get("payer_email"),
		)

		if self.gateway_type == TYPE_ROUTER:
			return get_url("{0}?t={1}".format(CHOOSER_PAGE, txn.token))

		from worldshading.payments.utils import callback_url

		return callback_url("checkout", txn.token)


def enabled_gateways():
	"""Every enabled gateway that can actually take money, in display order."""
	return frappe.get_all(
		"WS Payment Gateway",
		filters={"enabled": 1, "gateway_type": ["!=", TYPE_ROUTER]},
		fields=["name", "gateway_type", "method_label", "method_description", "sort_order"],
		order_by="sort_order asc, method_label asc",
	)
