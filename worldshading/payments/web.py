# -*- coding: utf-8 -*-
"""Guest-accessible endpoints for the payment gateways.

Deliberately thin. Each endpoint does the least possible on the request thread and
hands real work to a background job, because BENEFIT VOIDS a transaction it cannot
get a prompt acknowledgement for.

These are whitelisted methods rather than website pages for one specific reason: a
Frappe www page renders HTML, and BENEFIT's notification handler must return the
single line "REDIRECT=<url>" with no HTML, CSS or JavaScript at all. Frappe's
handler.handle() passes a werkzeug Response straight through, which lets us send
exactly that.

BENEFIT strips the query string from every URL we give it -- both responseURL and
the URL inside our "REDIRECT=" reply come back with no parameters. So nothing here
may depend on `?t=`; the transaction is found from the payload instead. Verified
against the test terminal.

See Documentation/payments/benefit_gateway.md section 4.3.
"""
from __future__ import unicode_literals

import json

import frappe
from werkzeug.utils import redirect
from werkzeug.wrappers import Response

from frappe.utils import cint

from worldshading.payments import benefit
from worldshading.payments.gateways import ROUTER_GATEWAY, client_for, validate_method
from worldshading.payments.utils import (
	TRANSACTION_DOCTYPE,
	callback_url,
	create_transaction,
	enqueue_settlement,
	get_captured_attempt,
	get_link_attempts,
	get_transaction,
	get_transaction_by_track_id,
	link_blocked_reason,
	log_raw,
	logger,
	record_payload,
)

RESULT_PAGE = "/payment-result"


def _result_page(token):
	from frappe.utils import get_url

	return get_url("{0}?t={1}".format(RESULT_PAGE, token or ""))


def _lookup(token):
	if not token:
		return None
	try:
		return get_transaction(token)
	except frappe.DoesNotExistError:
		return None


def _find_transaction(params, data=None):
	"""Identify which ATTEMPT a callback belongs to.

	trackId comes first and is the only precise answer: it is unique per attempt and
	BENEFIT echoes it on every leg, encrypted and in the clear. The link token is a
	fallback -- it identifies the link, which may have several attempts behind it,
	so it can only resolve to "the captured one, else the latest".

	More than one route is needed because BENEFIT strips our query string, and
	because the error leg carries no encrypted payload at all.
	"""
	for source in (data or {}, params):
		track_id = source.get("trackId") or source.get("trackid")
		if track_id:
			txn = get_transaction_by_track_id(str(track_id))
			if txn:
				return txn

	for token in (params.get("t"), params.get("udf3"), (data or {}).get("udf3")):
		txn = _lookup(token)
		if txn:
			return txn

	return None


def _process(params):
	"""Apply a gateway callback to its transaction. Returns the transaction or None.

	Safe to run more than once for the same payment: the notification and the final
	redirect both carry the same result, and settlement is idempotent.
	"""
	trandata = params.get("trandata")

	data = benefit.parse_trandata(trandata) if trandata else {}
	txn = _find_transaction(params, data)

	if not txn:
		logger().error("no transaction matched callback: %s", sorted(params.keys()))
		return None

	# These endpoints are BENEFIT's. Once a second gateway exists, one link can hold
	# attempts on both -- a customer who tries Credit and then Debit -- and the token
	# fallback could otherwise land a BENEFIT callback on an MPGS attempt and decode
	# it with the wrong scheme. trackId normally prevents this; this is the backstop.
	if txn.gateway != benefit.GATEWAY:
		logger().error(
			"callback for %s matched %s, which belongs to %s -- ignoring",
			benefit.GATEWAY, txn.name, txn.gateway,
		)
		return None

	record_payload(txn, "notification_payload", json.dumps(params, default=str))

	if not data:
		# The error leg -- plain parameters, no encrypted payload. Never let it
		# downgrade a payment the bank already captured.
		if txn.status != "Captured":
			txn.db_set("status", "Failed", update_modified=False)
			txn.db_set(
				"gateway_message",
				params.get("ErrorText") or params.get("Error") or "Payment could not be completed",
				update_modified=False,
			)
		frappe.db.commit()
		return txn

	record_payload(txn, "result_payload", json.dumps(data, default=str))

	captured = benefit.apply_result(txn, data)
	frappe.db.commit()

	if captured:
		# After the commit, deliberately. See enqueue_settlement().
		enqueue_settlement(txn.name)

	return txn


@frappe.whitelist(allow_guest=True, methods=["GET"])
def checkout(t=None, m=None):
	"""The customer clicked the pay link.

	The BENEFIT session is created here, not when the Payment Request was raised,
	because a payment URL is short-lived and the email may be opened days later.

	Every click that reaches the gateway is its own ATTEMPT with its own track ID.
	A decline followed by a retry must not reuse the previous reference: BENEFIT
	wants it merchant-unique, and two payments under one reference make
	reconciliation ambiguous even where the gateway tolerates it.
	"""
	attempts = get_link_attempts(t)

	if not attempts:
		return redirect(_result_page(t))

	if get_captured_attempt(attempts):
		# Already paid through this link. Never send a customer to pay twice.
		return redirect(_result_page(t))

	latest = frappe.get_doc(TRANSACTION_DOCTYPE, attempts[0].name)

	# Cancelled request, invoice already settled some other way, link too old.
	# The result page re-evaluates this and explains it to the customer.
	if link_blocked_reason(latest):
		return redirect(_result_page(t))

	# Which gateway the customer picked. Untrusted -- it arrives from their browser --
	# so validate_method only accepts one that is currently on offer. Falls back to
	# the link's own gateway for a direct, single-gateway link.
	gateway = validate_method(m) if m else latest.gateway

	if latest.status == "Initiated" and latest.gateway in (gateway, ROUTER_GATEWAY):
		# Never reached a gateway, so its track ID is still unused. If it is the
		# router's placeholder, adopt it for the chosen gateway so the customer's
		# first real try is attempt 1 rather than 2.
		txn = latest
		if latest.gateway != gateway:
			txn.db_set("gateway", gateway, update_modified=False)
	else:
		txn = create_transaction(
			gateway=gateway,
			amount=latest.amount,
			currency=latest.currency,
			reference_doctype=latest.reference_doctype,
			reference_docname=latest.reference_name,
			token=t,
			attempt=cint(latest.attempt) + 1,
			payer_name=latest.payer_name,
			payer_email=latest.payer_email,
		)

	try:
		payment_id, url = client_for(txn.gateway).initiate(txn)
	except Exception:
		logger().error("checkout failed for %s", txn.name)
		frappe.log_error(frappe.get_traceback(), "Payment checkout failed: {0}".format(txn.name))
		txn.db_set("status", "Failed", update_modified=False)
		txn.db_set("gateway_message", "Could not reach the payment gateway", update_modified=False)
		frappe.db.commit()
		return redirect(_result_page(txn.token))

	txn.db_set("payment_id", payment_id, update_modified=False)
	txn.db_set("status", "Redirected", update_modified=False)
	txn.db_set("redirect_url", url, update_modified=False)
	frappe.db.commit()

	return redirect(url)


@frappe.whitelist(allow_guest=True, xss_safe=True, methods=["POST", "GET"])
def notify(**kwargs):
	"""Server-to-server notification from BENEFIT.

	The contract, in order of importance:

	1. Answer with exactly "REDIRECT=<url>" -- upper case, no markup.
	2. Answer QUICKLY. No acknowledgement means BENEFIT voids the transaction, so
	   the customer would be debited and reversed while we showed success.
	3. Only then do our own work -- which is why settlement is enqueued, not run.

	Because of (2) this function acknowledges even when our own processing fails.
	Losing our bookkeeping is recoverable; a wrongly voided payment is not. The raw
	payload is on disk and on the record either way, and the final browser redirect
	carries the same result a second time.
	"""
	# Before anything else, per BENEFIT's own guidance for this handler.
	log_raw("benefit.notify", json.dumps(kwargs, default=str))

	try:
		_process(kwargs)
	except Exception:
		frappe.db.rollback()
		frappe.log_error(frappe.get_traceback(), "Payment notification failed")

	# No token in the URL: BENEFIT would strip it. The result leg re-identifies the
	# payment from its own payload.
	return Response(
		"REDIRECT=" + callback_url("result"), mimetype="text/plain", status=200
	)


@frappe.whitelist(allow_guest=True, xss_safe=True, methods=["POST", "GET"])
def result(**kwargs):
	"""Final browser redirect from BENEFIT, after it has our acknowledgement.

	Carries the same outcome as the notification. Processed again on purpose: it is
	the safety net for a notification we failed to handle, and settlement is
	idempotent so a duplicate costs nothing.
	"""
	log_raw("benefit.result", json.dumps(kwargs, default=str))

	txn = None
	try:
		txn = _process(kwargs)
	except Exception:
		frappe.db.rollback()
		frappe.log_error(frappe.get_traceback(), "Payment result handling failed")

	return redirect(_result_page(txn.token if txn else None))


# ---------------------------------------------------------------- KFH MPGS


def _mpgs_settle(txn):
	"""Ask MPGS what really happened, then act on it.

	The return URL's resultIndicator is only a hint -- Mastercard say plainly not to
	treat it as evidence -- so the order is always retrieved before any money is
	posted. MPGS documents Retrieve Order properly, which is why this needs none of
	the hedging BENEFIT's Inquiry does.
	"""
	from worldshading.payments import mpgs

	order = mpgs.retrieve_order(txn)
	record_payload(txn, "result_payload", json.dumps(order, default=str))

	captured = mpgs.apply_result(txn, order)
	frappe.db.commit()

	if captured:
		enqueue_settlement(txn.name)

	return captured


@frappe.whitelist(allow_guest=True, xss_safe=True, methods=["POST", "GET"])
def mpgs_return(**kwargs):
	"""Where MPGS returns the payer after the hosted page.

	Carries `resultIndicator`, which we compare against the `successIndicator`
	stored when the session was created. That comparison decides what to SHOW the
	customer; what gets POSTED is decided by retrieving the order.
	"""
	log_raw("mpgs.return", json.dumps(kwargs, default=str))

	txn = None
	try:
		txn = _find_transaction(kwargs)

		if txn and txn.gateway == mpgs_gateway():
			indicator = kwargs.get("resultIndicator")
			if indicator and txn.success_indicator:
				matched = str(indicator) == str(txn.success_indicator)
				logger().info(
					"mpgs.return %s indicator %s", txn.name, "matched" if matched else "MISMATCH"
				)

			_mpgs_settle(txn)
	except Exception:
		frappe.db.rollback()
		frappe.log_error(frappe.get_traceback(), "MPGS return handling failed")

	return redirect(_result_page(txn.token if txn else kwargs.get("t")))


@frappe.whitelist(allow_guest=True, xss_safe=True, methods=["POST"])
def mpgs_webhook(**kwargs):
	"""Server-to-server notification from MPGS.

	Authenticated by the shared secret the gateway puts in X-Notification-Secret.
	An unverified caller is refused outright -- unlike BENEFIT, nothing here needs
	us to answer optimistically, because MPGS does not void an unacknowledged
	payment.
	"""
	from worldshading.payments import mpgs

	log_raw("mpgs.webhook", json.dumps(kwargs, default=str))

	supplied = frappe.get_request_header("X-Notification-Secret")

	try:
		txn = _find_transaction(kwargs, _webhook_order(kwargs))

		if not txn:
			logger().error("mpgs.webhook: no transaction matched")
			return _ok()

		settings = mpgs.get_settings(txn.gateway)

		if not mpgs.verify_webhook_secret(settings, supplied):
			logger().error("mpgs.webhook: bad or missing notification secret")
			frappe.local.response["http_status_code"] = 401
			return _ok()

		record_payload(txn, "notification_payload", json.dumps(kwargs, default=str))
		_mpgs_settle(txn)
	except Exception:
		frappe.db.rollback()
		frappe.log_error(frappe.get_traceback(), "MPGS webhook handling failed")

	return _ok()


def _ok():
	return Response("OK", mimetype="text/plain", status=200)


def mpgs_gateway():
	from worldshading.payments import mpgs

	return mpgs.GATEWAY


def _webhook_order(params):
	"""The order object out of a webhook body, for correlation.

	MPGS posts the order as JSON; `order.id` is our track_id, so this resolves to
	the exact attempt.
	"""
	order = params.get("order")

	if isinstance(order, dict):
		return {"trackId": order.get("id")}

	if isinstance(order, str):
		try:
			return {"trackId": (json.loads(order) or {}).get("id")}
		except ValueError:
			return None

	return None


@frappe.whitelist(allow_guest=True, xss_safe=True, methods=["POST", "GET"])
def error(**kwargs):
	"""BENEFIT's errorURL -- plain parameters, never encrypted.

	Also where BENEFIT lands us when it voided a transaction because we failed to
	acknowledge in time.
	"""
	log_raw("benefit.error", json.dumps(kwargs, default=str))

	txn = None
	try:
		txn = _process(kwargs)
	except Exception:
		frappe.db.rollback()
		frappe.log_error(frappe.get_traceback(), "Payment error handling failed")

	return redirect(_result_page(txn.token if txn else None))
