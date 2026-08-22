# -*- coding: utf-8 -*-
"""KFH MPGS (Mastercard Payment Gateway Services) client — Hosted Checkout.

Plain JSON over HTTPS with HTTP Basic auth. No AES envelope, which is what made
BENEFIT fiddly. What MPGS asks for instead is a page on our side that loads their
Checkout JavaScript -- see www/mpgs-checkout/.

Everything below is verified against Mastercard's own Postman collection
("Gateway API Operations", v100) rather than prose, because the prose disagrees with
it in one important place: the guide says a "PAY, AUTHORIZE or VERIFY transaction",
but every worked example sets interaction.operation to PURCHASE. PAY is the
apiOperation for a session-based transaction, not an interaction operation.

Gateway facts established by probing the live host:

    host           https://test-bh-kfh.mtf.gateway.mastercard.com
    API version    100  (101+ return 404 on /information)
    gateway build  26.7.0-123R

See Documentation/payments/kfh_mpgs.md.
"""
from __future__ import unicode_literals

import json

import frappe
import requests
from frappe import _
from frappe.utils import get_url

from worldshading.payments.utils import callback_url, format_amount, log_raw, logger

GATEWAY = "KFH MPGS"

# interaction.operation. PURCHASE = authorise and capture in one go, which is what
# collecting against an invoice means. AUTHORIZE would only hold the funds and leave
# a capture step for later.
OPERATION_PURCHASE = "PURCHASE"

# Hosted Checkout on a web page, as opposed to a mobile app.
CHECKOUT_MODE = "WEBSITE"

# order.status from RETRIEVE ORDER -> our transaction status.
# Only CAPTURED means the money is ours. AUTHORIZED is deliberately NOT success: we
# ask for PURCHASE, so an authorised-but-uncaptured order means something went
# differently than we asked and a human should look.
_STATUS_BY_ORDER_STATUS = {
	"CAPTURED": "Captured",
	"FAILED": "Failed",
	"CANCELLED": "Cancelled",
	"EXPIRED": "Failed",
	"DECLINED": "Failed",
	# 3-D Secure refused the payer before any authorisation was attempted. A real
	# outcome, and terminal -- leaving it at Redirected would make reconciliation
	# chase a transaction the gateway has already finished with.
	"AUTHENTICATION_UNSUCCESSFUL": "Failed",
	"AUTHENTICATION_FAILED": "Failed",
}

# Still in flight. Not an outcome, so the transaction stays as it is and
# reconciliation is right to come back to it later.
#
# AUTHENTICATED belongs here and is worth understanding: 3-D Secure has passed but no
# payment has been attempted. For a PURCHASE that should be momentary -- if an order
# is still sitting at AUTHENTICATED later, the gateway authenticated the payer and
# then could not authorise, which usually means the acquirer on the profile cannot
# service the request. Money has NOT moved.
_IN_PROGRESS_ORDER_STATUS = (
	"AUTHENTICATION_INITIATED", "AUTHENTICATED", "INITIATED", "PENDING",
)

_TIMEOUT = (10, 30)

CHECKOUT_PAGE = "/mpgs-checkout"


class MPGSOrderNotFoundError(frappe.ValidationError):
	"""The merchant account has no order for the requested track ID."""
	pass


def is_order_not_found_error(error):
	"""Return whether an MPGS error definitively says that an order is absent."""
	cause = (error.get("cause") or "").strip().upper()
	explanation = (error.get("explanation") or "").strip().lower()

	return (
		cause in ("INVALID_REQUEST", "NOT_FOUND")
		and "unable to find order" in explanation
	)


def merchant_references(track_id):
	"""Return the unique references enforced by the MPGS merchant profile."""
	track_id = str(track_id)
	return {
		"order": "ORD-{0}".format(track_id),
		"transaction": "TXN-{0}".format(track_id),
	}


def get_settings(gateway=None):
	from worldshading.payments.utils import _gateway_settings

	settings = _gateway_settings(gateway or GATEWAY)

	if not settings:
		frappe.throw(_("{0} is not configured").format(gateway or GATEWAY))

	return settings


def _api_base(settings):
	host = (settings.mpgs_api_host or "").rstrip("/")
	version = (settings.mpgs_api_version or "").strip()

	if not host or not version or not settings.mpgs_merchant_id:
		frappe.throw(_("{0} needs an API host, version and merchant ID").format(GATEWAY))

	return "{0}/api/rest/version/{1}/merchant/{2}".format(
		host, version, settings.mpgs_merchant_id
	)


def _auth(settings):
	"""HTTP Basic, username "merchant.<merchant ID>"."""
	password = settings.get_password("mpgs_api_password", raise_exception=False)

	if not password:
		frappe.throw(_("{0} API password is not set").format(GATEWAY))

	return ("merchant.{0}".format(settings.mpgs_merchant_id), password)


def _request(settings, method, path, payload=None):
	url = "{0}{1}".format(_api_base(settings), path)

	log_raw("mpgs.request", "%s %s %s" % (method, url, json.dumps(payload or {})))

	response = requests.request(
		method,
		url,
		auth=_auth(settings),
		json=payload,
		headers={"Content-Type": "application/json", "Accept": "application/json"},
		timeout=_TIMEOUT,
	)

	log_raw("mpgs.response", "%s %s" % (response.status_code, response.text))

	try:
		body = response.json()
	except ValueError:
		frappe.throw(_("MPGS returned an unreadable response"))

	# The gateway names the offending field on a bad request, which is worth
	# surfacing rather than swallowing -- it is how the shape gets corrected.
	if body.get("result") == "ERROR":
		error = body.get("error") or {}
		logger().error(
			"mpgs %s %s -> %s %s",
			method, path, error.get("cause"), error.get("explanation"),
		)
		message = _("MPGS rejected the request: {0} {1}").format(
			error.get("cause") or "", error.get("explanation") or ""
		)
		if method == "GET" and path.startswith("/order/") and is_order_not_found_error(error):
			raise MPGSOrderNotFoundError(message)

		frappe.throw(
			message
		)

	return body


def ping(gateway=None):
	"""Check credentials without creating anything.

	Retrieves an order that cannot exist. A correct password gets a polite "no such
	order"; a wrong one gets 401. Nothing is charged, nothing is stored, so this is
	safe to run against production.

	    bench --site erp.worldshading.com execute worldshading.payments.mpgs.ping
	"""
	settings = get_settings(gateway)

	url = "{0}/order/{1}".format(_api_base(settings), "ws-connectivity-check")

	response = requests.get(
		url,
		auth=_auth(settings),
		headers={"Accept": "application/json"},
		timeout=_TIMEOUT,
	)

	try:
		body = response.json()
	except ValueError:
		body = {"raw": response.text[:400]}

	cause = (body.get("error") or {}).get("cause")

	if response.status_code == 401:
		verdict = "FAILED - credentials rejected. Check the API password and that the username is merchant.<merchant ID>."
	elif cause in ("NOT_FOUND", "INVALID_REQUEST") or response.status_code in (200, 404):
		verdict = "OK - authenticated. The gateway answered as itself."
	else:
		verdict = "UNCLEAR - see the response below."

	print("\n  host       : %s" % settings.mpgs_api_host)
	print("  version    : %s" % settings.mpgs_api_version)
	print("  merchant   : merchant.%s" % settings.mpgs_merchant_id)
	print("  HTTP       : %s" % response.status_code)
	print("  response   : %s" % json.dumps(body)[:400])
	print("\n  %s\n" % verdict)

	return {"http": response.status_code, "body": body, "verdict": verdict}


def test_session(gateway=None, amount="1.000", currency="BHD"):
	"""Create a throwaway checkout session to prove the request shape.

	Creates no order and moves no money -- a session is only an intent, and this one
	is never opened. What it does prove is the part we could not verify from
	documentation alone:

	  * interaction.operation PURCHASE is accepted (the guide's prose says "PAY")
	  * the BHD amount format is right -- three decimals, as a string
	  * the acquirer on the profile can actually service the request

	That last one matters most. Mastercard warn that an acquirer lacking a
	capability causes rejections rather than setup errors, and the AUB_S2I link on
	this profile is unconfigured.

	    bench --site erp.worldshading.com execute worldshading.payments.mpgs.test_session
	"""
	from frappe.utils import now_datetime

	settings = get_settings(gateway)

	order_id = "wstest{0}".format(now_datetime().strftime("%y%m%d%H%M%S%f"))
	references = merchant_references(order_id)

	payload = {
		"apiOperation": "INITIATE_CHECKOUT",
		"checkoutMode": CHECKOUT_MODE,
		"interaction": {
			"operation": OPERATION_PURCHASE,
			"merchant": {
				"name": settings.mpgs_merchant_name or settings.name,
				"url": get_url("/"),
			},
			"returnUrl": callback_url("mpgs_return", "test"),
		},
		"order": {
			"currency": currency,
			"amount": amount,
			"id": order_id,
			"reference": references["order"],
			"description": "Connectivity test - not a real payment",
		},
		"transaction": {
			"reference": references["transaction"],
		},
	}

	print("\n  REQUEST:\n  %s\n" % json.dumps(payload, indent=2).replace("\n", "\n  "))

	response = requests.post(
		"{0}/session".format(_api_base(settings)),
		auth=_auth(settings),
		json=payload,
		headers={"Content-Type": "application/json", "Accept": "application/json"},
		timeout=_TIMEOUT,
	)

	try:
		body = response.json()
	except ValueError:
		body = {"raw": response.text[:600]}

	print("  HTTP %s" % response.status_code)
	print("  RESPONSE:\n  %s\n" % json.dumps(body, indent=2).replace("\n", "\n  "))

	session_id = (body.get("session") or {}).get("id")

	if session_id:
		print("  OK - session created: %s" % session_id)
		print("  successIndicator   : %s" % body.get("successIndicator"))
		print("  PURCHASE, the BHD amount format and the acquirer are all accepted.\n")
	else:
		error = body.get("error") or {}
		print("  FAILED - %s: %s\n" % (error.get("cause"), error.get("explanation")))

	return body


def initiate(txn):
	"""Create a checkout session and return where to send the customer.

	Unlike BENEFIT, the customer does not go straight to the bank: MPGS requires
	their Checkout JavaScript, so we send them to our own launcher page which loads
	it and opens the hosted payment page immediately.

	`order.id` is our own track_id. MPGS order IDs are merchant-defined, so
	correlation on the way back is exact and does not depend on a query string
	surviving -- which is the trap BENEFIT sprang on us.
	"""
	settings = get_settings(txn.gateway)
	settings.validate_enabled()

	interaction = {
		# PURCHASE authorises and captures in one step. This is intentionally fixed:
		# AUTHORIZE would leave funds held but not collected.
		"operation": OPERATION_PURCHASE,
		"merchant": {
			# Shown to the payer on the hosted page, so it must read as the
			# business, not as our internal gateway name.
			"name": settings.mpgs_merchant_name or frappe.db.get_default("company") or settings.name,
			"url": get_url("/"),
		},
		# The token has to travel in the URL: MPGS appends `resultIndicator` to
		# whatever we give it, and that alone identifies nothing. Unlike BENEFIT
		# it does not strip our query string -- but the webhook does not depend
		# on this either way, since order.id carries the track ID.
		"returnUrl": callback_url("mpgs_return", txn.token),
	}

	references = merchant_references(txn.track_id)

	payload = {
		"apiOperation": "INITIATE_CHECKOUT",
		"checkoutMode": CHECKOUT_MODE,
		"interaction": interaction,
		"order": {
			"currency": txn.currency,
			"amount": format_amount(txn.amount, txn.currency),
			"id": txn.track_id,
			"reference": references["order"],
			"description": _description(txn),
		},
		"transaction": {
			"reference": references["transaction"],
		},
	}

	body = _request(settings, "POST", "/session", payload)

	session_id = (body.get("session") or {}).get("id")
	success_indicator = body.get("successIndicator")

	if not session_id:
		frappe.throw(_("MPGS did not return a checkout session"))

	# successIndicator is the ONLY way to read the return-URL result, so it has to be
	# stored before the customer leaves.
	txn.db_set("session_id", session_id, update_modified=False)
	txn.db_set("success_indicator", success_indicator or "", update_modified=False)
	frappe.db.commit()

	# Our launcher page, which loads Mastercard's Checkout library and opens the
	# hosted page. There is no redirect-only alternative: /checkout/pay/<session>
	# looks like one, but only renders for a session the library has already
	# initialised -- a fresh session gets "unable to complete your payment".
	return "", get_url("{0}?t={1}".format(CHECKOUT_PAGE, txn.token))


def _description(txn):
	from worldshading.payments.benefit import source_document

	document = source_document(txn)

	return "Payment for {0}".format(document) if document else "Payment"


def retrieve_order(txn):
	"""The authoritative record of what happened. Used by reconciliation.

	MPGS documents this properly, unlike BENEFIT's Inquiry -- which is why
	reconciliation for MPGS needs no "unverified" flag.
	"""
	settings = get_settings(txn.gateway)

	return _request(settings, "GET", "/order/{0}".format(txn.track_id))


def apply_result(txn, order):
	"""Copy a RETRIEVE ORDER or webhook payload onto the transaction.

	Returns True when the money is actually ours.
	"""
	status = (order.get("status") or "").strip().upper()
	result = (order.get("result") or "").strip().upper()

	transaction = _latest_transaction(order)
	audit = transaction_audit_values(transaction)

	txn.db_set("result", status or result, update_modified=False)
	txn.db_set("payment_id", str(order.get("id") or txn.track_id), update_modified=False)
	txn.db_set("transaction_id", audit["transaction_id"], update_modified=False)
	txn.db_set("reference_number", audit["reference_number"], update_modified=False)

	response = transaction.get("response") or {}
	txn.db_set("auth_code", audit["auth_code"], update_modified=False)
	txn.db_set(
		"auth_response_code", str(response.get("gatewayCode") or ""), update_modified=False
	)

	# Prefer the authentication status when 3-D Secure is what stopped the payment.
	# gatewayRecommendation reads "PROCEED" even on a declined authentication, which
	# is worse than useless to whoever opens the record later.
	authentication = (order.get("authenticationStatus") or "").strip()
	message = response.get("acquirerMessage") or response.get("gatewayRecommendation") or ""

	if authentication and authentication != "AUTHENTICATION_SUCCESSFUL":
		message = authentication.replace("_", " ").title()

	txn.db_set("gateway_message", str(message), update_modified=False)

	our_status = _STATUS_BY_ORDER_STATUS.get(status)

	if not our_status:
		if status in _IN_PROGRESS_ORDER_STATUS:
			our_status = txn.status
		else:
			# An order status we do not recognise must never be read as success.
			logger().error("mpgs: unrecognised order status %r on %s", status, txn.name)
			our_status = "Failed" if result == "FAILURE" else txn.status

	txn.db_set("status", our_status, update_modified=False)

	return our_status == "Captured"


def _latest_transaction(order):
	"""The most recent transaction on the order, or an empty dict."""
	transactions = order.get("transaction") or []

	if isinstance(transactions, dict):
		return transactions

	return transactions[-1] if transactions else {}


def transaction_audit_values(transaction):
	"""Extract the staff-facing identifiers from an MPGS transaction."""
	details = transaction.get("transaction") or {}
	return {
		"transaction_id": str(details.get("id") or ""),
		"reference_number": str(details.get("receipt") or ""),
		"auth_code": str(details.get("authorizationCode") or ""),
	}


def verify_webhook_secret(settings, supplied):
	"""Check the X-Notification-Secret header the gateway sends.

	A shared secret, not a signature -- so compare it in constant time and treat a
	missing or wrong value as "not from the gateway".
	"""
	import hmac

	expected = settings.get_password("mpgs_webhook_secret", raise_exception=False)

	if not expected or not supplied:
		return False

	try:
		return hmac.compare_digest(str(expected), str(supplied))
	except Exception:
		return False
