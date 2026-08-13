# -*- coding: utf-8 -*-
"""Shared plumbing for the online payment gateways.

Nothing gateway-specific lives here. Amount formatting, track IDs, the transaction
record and settlement are the same problems for BENEFIT and for MPGS, so they are
solved once.

See Documentation/payments/README.md for the architecture.
"""
from __future__ import unicode_literals

import json

import frappe
from frappe import _
from frappe.model.naming import getseries
from frappe.utils import add_days, cint, flt, get_datetime, get_url, now, now_datetime, nowdate

TRANSACTION_DOCTYPE = "WS Payment Transaction"

# Money is not a float. How many decimals a currency carries is a property of the
# currency, and getting it wrong is the classic Gulf integration bug: BHD has THREE
# decimals, so 12.5 BHD is "12.500" and never "12.50".
#
# Kept explicit rather than derived from the Currency doctype, because that record is
# editable in the UI and a well-meaning edit must not change what we send a bank.
CURRENCY_DECIMALS = {
	"BHD": 3,
	"KWD": 3,
	"OMR": 3,
	"JOD": 3,
	"TND": 3,
	"LYD": 3,
	"IQD": 3,
	"JPY": 0,
	"KRW": 0,
}

DEFAULT_DECIMALS = 2


def currency_decimals(currency):
	return CURRENCY_DECIMALS.get((currency or "").upper(), DEFAULT_DECIMALS)


def format_amount(amount, currency):
	"""Return the amount as the decimal string the gateway expects.

	BENEFIT documents a plain decimal string with the currency's own precision --
	"12.00", "60.000" -- not minor units. Confirm MPGS separately before reusing this
	there; see Documentation/payments/kfh_mpgs.md section 5.
	"""
	decimals = currency_decimals(currency)
	value = flt(amount, decimals)

	if value <= 0:
		frappe.throw(_("Payment amount must be greater than zero"))

	return ("{0:." + str(decimals) + "f}").format(value)


def new_track_id():
	"""A numeric, merchant-unique reference for the gateway.

	BENEFIT requires ``trackId`` to be numeric, so ERPNext document names
	("ACC-PRQ-2026-00187") cannot be passed through. A date prefix plus a per-day
	counter stays numeric, stays unique, and is still readable in a bank portal when
	somebody is chasing a specific payment.
	"""
	day = nowdate().replace("-", "")[2:]  # YYMMDD
	return "{0}{1}".format(day, getseries("WS-PAY-TRACK-" + day, 6))


def logger():
	return frappe.logger("worldshading.payments", with_more_info=False)


def log_raw(label, payload):
	"""Write a gateway payload to the log file before anything else touches it.

	BENEFIT's own guidance for the notification handler is: log the raw response to
	a file first, so there is a record even if every later step fails. Chapter 7 of
	the Integration Guide makes transaction logging mandatory, not advisory.
	"""
	try:
		logger().info("%s | %s", label, payload)
	except Exception:
		# Logging must never be the reason a payment callback fails.
		pass


def get_client_ip():
	"""Best-effort customer IP.

	Integration Guide chapter 7 requires transaction logs to include it. It is not
	part of any gateway payload, so we capture it ourselves.
	"""
	try:
		request = getattr(frappe.local, "request", None)
		if not request:
			return None

		forwarded = request.headers.get("X-Forwarded-For")
		if forwarded:
			return forwarded.split(",")[0].strip()

		return request.remote_addr
	except Exception:
		return None


def callback_url(method, token=None):
	"""Build a callback URL.

	Pass a token ONLY for links we hand to the customer (the checkout link in the
	Payment Request email). Never for URLs given to BENEFIT: it strips the query
	string off both responseURL/errorURL and the URL in our "REDIRECT=" reply, so a
	token there silently disappears. Verified against the test terminal -- the
	notification came back with no `t` at all.

	Correlation on the way back is done from the payload instead: udf3 carries our
	token and trackId carries our reference, and BENEFIT echoes both.

	Kept short regardless -- BENEFIT rejects any URL over 254 characters in total
	(Integration Guide section 3.1).
	"""
	path = "/api/method/worldshading.payments.web.{0}".format(method)

	if token:
		path = "{0}?t={1}".format(path, token)

	return get_url(path)


def create_transaction(gateway, amount, currency, reference_doctype, reference_docname,
	token=None, attempt=1, **kwargs):
	"""Create one payment ATTEMPT.

	`token` identifies the payment link and is shared by every attempt made through
	it; pass the existing one when a customer retries. `track_id` is minted fresh
	every time, because BENEFIT wants a merchant-unique reference per transaction and
	reusing one across a decline-then-retry makes reconciliation ambiguous.
	"""
	doc = frappe.get_doc({
		"doctype": TRANSACTION_DOCTYPE,
		"gateway": gateway,
		"status": "Initiated",
		"token": token or frappe.generate_hash(length=16),
		"attempt": attempt,
		"track_id": new_track_id(),
		"amount": flt(amount),
		"currency": currency,
		"reference_doctype": reference_doctype,
		"reference_name": reference_docname,
		"payment_request": reference_docname if reference_doctype == "Payment Request" else None,
		"payer_name": kwargs.get("payer_name"),
		"payer_email": kwargs.get("payer_email"),
		"customer_ip": get_client_ip(),
	})
	doc.insert(ignore_permissions=True)

	return doc


def get_link_attempts(token):
	"""Every attempt made through one payment link, newest first."""
	if not token:
		return []

	return frappe.get_all(
		TRANSACTION_DOCTYPE,
		filters={"token": token},
		fields=["name", "attempt", "status", "settled", "track_id"],
		order_by="attempt desc, creation desc",
	)


def get_captured_attempt(attempts):
	"""The attempt that actually took the money, if any."""
	for attempt in attempts:
		if attempt.status == "Captured" or attempt.settled:
			return attempt
	return None


def get_transaction(token):
	"""The attempt a payment link currently represents.

	A captured attempt always wins -- that is the one that took the money, whatever
	happened afterwards. Otherwise the most recent try.
	"""
	attempts = get_link_attempts(token)

	if not attempts:
		frappe.throw(_("Payment reference not recognised"), frappe.DoesNotExistError)

	chosen = get_captured_attempt(attempts) or attempts[0]

	return frappe.get_doc(TRANSACTION_DOCTYPE, chosen.name)


def link_validity_days(gateway):
	settings = _gateway_settings(gateway)
	return cint(settings.get("link_valid_days")) if settings else 0


def link_blocked_reason(txn):
	"""Why this payment link can no longer be used, or None if it still can.

	Guards against the case that actually happens: an invoice gets settled by cash
	at the counter, nobody cancels the Payment Request, and weeks later the customer
	finds the old email and pays again.
	"""
	if txn.payment_request:
		request = frappe.db.get_value(
			"Payment Request", txn.payment_request,
			["docstatus", "status", "reference_doctype", "reference_name"], as_dict=True,
		)

		if not request:
			return _("This payment request no longer exists.")
		if request.docstatus == 2:
			return _("This payment request has been cancelled.")
		if request.status == "Paid":
			return _("This request has already been paid.")

		reference_doctype = request.reference_doctype
		reference_name = request.reference_name
	else:
		reference_doctype = txn.reference_doctype
		reference_name = txn.reference_name

	# Whatever settled it -- cash, another gateway, a credit note -- if nothing is
	# owed then nothing should be collectable through this link.
	if reference_doctype and reference_name:
		if frappe.get_meta(reference_doctype).has_field("outstanding_amount"):
			outstanding = frappe.db.get_value(
				reference_doctype, reference_name, "outstanding_amount"
			)
			if outstanding is not None and flt(outstanding) <= 0:
				return _("This document has already been paid in full.")

	days = link_validity_days(txn.gateway)
	if days and txn.creation:
		if now_datetime() > add_days(get_datetime(txn.creation), days):
			return _("This payment link has expired.")

	return None


def get_transaction_by_track_id(track_id):
	name = frappe.db.get_value(TRANSACTION_DOCTYPE, {"track_id": track_id}, "name")
	return frappe.get_doc(TRANSACTION_DOCTYPE, name) if name else None


def enqueue_settlement(txn_name):
	"""Push settlement to a worker.

	BENEFIT gives us a few seconds to acknowledge a notification before it VOIDS the
	transaction, so no ERP work may happen on the request thread. See
	Documentation/payments/benefit_gateway.md section 4.3.
	"""
	# NOT enqueue_after_commit. Frappe flushes that queue from inside db.commit()
	# (database.py:995), so a job registered AFTER the commit waits for a commit that
	# never comes and is silently dropped -- which is exactly what happened on the
	# first live transaction. Callers commit first, then enqueue; the data is already
	# durable by then, so there is no race for enqueue_after_commit to protect against.
	frappe.enqueue(
		"worldshading.payments.utils.settle",
		queue="short",
		timeout=300,
		txn_name=txn_name,
	)


GATEWAY_DOCTYPE = "WS Payment Gateway"


def _gateway_settings(gateway):
	"""The gateway's configuration row.

	One doctype, one row per gateway -- so adding a gateway is a record, not another
	Settings doctype. Everything downstream goes through here, which is why the
	switch away from per-gateway singles touched almost nothing else.
	"""
	if not gateway:
		return None

	if not frappe.db.exists(GATEWAY_DOCTYPE, gateway):
		logger().error("no %s row for gateway %s", GATEWAY_DOCTYPE, gateway)
		return None

	return frappe.get_doc(GATEWAY_DOCTYPE, gateway)


def gateway_mode_of_payment(gateway):
	"""The Mode of Payment to stamp on the Payment Entry for this gateway.

	Returns None rather than raising: a missing Mode of Payment should surface as
	ERPNext's own mandatory-field error on the Payment Entry, which names the field,
	not as an obscure failure in this helper.
	"""
	settings = _gateway_settings(gateway)

	return settings.get("mode_of_payment") if settings else None


def settle(txn_name):
	"""Turn a captured gateway transaction into a Payment Entry. Idempotent.

	Both the server-to-server notification and the final browser redirect carry the
	same successful result, and either may arrive first or twice. Creating two
	Payment Entries for one payment would be a real accounting error, so the row is
	locked and the ``settled`` flag checked inside that lock.
	"""
	# SELECT ... FOR UPDATE holds the row until this transaction commits, so two
	# concurrent workers cannot both pass the check below.
	row = frappe.db.sql(
		"""select settled, status from `tab{0}` where name = %s for update""".format(
			TRANSACTION_DOCTYPE
		),
		txn_name,
		as_dict=True,
	)

	if not row:
		logger().error("settle: transaction %s not found", txn_name)
		return

	if row[0].get("settled"):
		return

	txn = frappe.get_doc(TRANSACTION_DOCTYPE, txn_name)

	if txn.status != "Captured":
		return

	if not txn.payment_request:
		# Nothing to post against. The transaction record still holds the result.
		txn.db_set("settled", 1, update_modified=False)
		frappe.db.commit()
		return

	payment_request = frappe.get_doc("Payment Request", txn.payment_request)

	if payment_request.docstatus != 1:
		logger().error(
			"settle: Payment Request %s is not submitted (docstatus %s)",
			payment_request.name, payment_request.docstatus,
		)
		return

	if payment_request.status == "Paid":
		# Somebody -- or something -- already settled it. Record that and stop.
		txn.db_set("settled", 1, update_modified=False)
		frappe.db.commit()
		return

	# Note: ERPNext's own check_if_payment_entry_exists() is not used here. It throws
	# rather than returns, and it only looks at whether ANY Payment Entry references
	# the document -- which is legitimately true for a Partially Paid request. The
	# `settled` flag above, taken under a row lock, is the correct guard.

	try:
		# This is set_as_paid() unrolled. We need to stamp a field on the Payment
		# Entry before validation runs, and set_as_paid() inserts and submits in one
		# step with no way in.
		#
		# We do not use the documented on_payment_authorized() hook either: it wraps
		# set_as_paid() in webshop redirect logic that is meaningless for a Payment
		# Request emailed to a customer.
		payment_entry = payment_request.create_payment_entry(submit=False)

		# mode_of_payment is mandatory on Payment Entry on this site (a Property
		# Setter), and ERPNext's get_payment_entry() never populates it. The first
		# live settlement died on exactly this. Take it from the gateway's Settings.
		mode_of_payment = gateway_mode_of_payment(txn.gateway)
		if mode_of_payment:
			payment_entry.mode_of_payment = mode_of_payment

		# Money lands in the account of the gateway that actually took it, not the
		# one on the Payment Request. With a router in front, the request's account
		# belongs to the router and says nothing about where the funds really went.
		from worldshading.payments.gateways import deposit_account

		account = deposit_account(txn.gateway)
		if account:
			payment_entry.paid_to = account

		# Leave workflow_state ALONE. Payment Entry has an active workflow: a new
		# document must enter at the first state (Draft), and frappe's
		# set_workflow_state_on_action moves it to the docstatus-1 state
		# ("Completed") as part of submit. Setting it here would be rejected as an
		# illegal transition, because a brand new doc has no _doc_before_save to
		# transition from.
		payment_entry.insert(ignore_permissions=True)

		# Submitting fires ERPNext's update_payment_req_status, which moves the
		# Payment Request to Paid / Partially Paid on its own. We never set that
		# status ourselves.
		payment_entry.submit()

		# Mirrors the second half of set_as_paid(). A no-op unless the reference is
		# a Shopping Cart order, which ours never are.
		payment_request.make_invoice()

		txn.db_set("payment_entry", payment_entry.name, update_modified=False)
		txn.db_set("settled", 1, update_modified=False)
		txn.db_set("settled_on", now(), update_modified=False)
		frappe.db.commit()

		logger().info(
			"settled %s -> Payment Entry %s", txn_name, payment_entry.name
		)
	except Exception:
		frappe.db.rollback()
		frappe.log_error(
			frappe.get_traceback(),
			"Payment settlement failed: {0}".format(txn_name),
		)
		# Leave settled = 0 so a later reconciliation can retry. The money is
		# captured at the bank either way; the transaction record proves it.
		raise


def record_payload(txn, field, payload):
	"""Store a raw gateway payload on the transaction without touching modified."""
	if isinstance(payload, dict):
		payload = json.dumps(payload, indent=1, sort_keys=True, default=str)

	txn.db_set(field, payload, update_modified=False)
