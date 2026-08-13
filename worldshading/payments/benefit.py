# -*- coding: utf-8 -*-
"""BENEFIT Payment Gateway client (REST / bank-hosted purchase).

We use the REST API, not the plug-in. BENEFIT ships the plug-in only as Java, .NET
and PHP binaries -- there is no Python build -- so we implement the AES envelope
ourselves in crypto.py. The onboarding email also marks API integration as the
recommended route.

Reference: BENEFIT Payment Gateway Integration Guide v1.4, chapter 4.
See Documentation/payments/benefit_gateway.md.
"""
from __future__ import unicode_literals

import json

import frappe
import requests
from frappe import _
from six.moves.urllib.parse import parse_qs, urlparse

from worldshading.payments import crypto
from worldshading.payments.utils import callback_url, format_amount, log_raw, logger

GATEWAY = "Benefit"
SETTINGS_DOCTYPE = "Benefit Settings"

# Integration Guide section 4.5. Production collection uses purchase only.
ACTION_PURCHASE = "1"

# ISO numeric currency codes. BENEFIT wants the number, not the letters.
CURRENCY_CODES = {"BHD": "048"}

# Vendor plugin marks this do-not-change. BENEFIT is a debit network.
CARD_TYPE_DEBIT = "D"

# Integration Guide page 58. CAPTURED is the only success for a purchase.
RESULT_CAPTURED = "CAPTURED"
RESULT_NOT_CAPTURED = "NOT CAPTURED"
RESULT_VOIDED = "VOIDED"
RESULT_DENIED_BY_RISK = "DENIED BY RISK"
RESULT_HOST_TIMEOUT = "HOST TIMEOUT"

# Gateway result -> our transaction status.
_STATUS_BY_RESULT = {
	RESULT_CAPTURED: "Captured",
	RESULT_NOT_CAPTURED: "Failed",
	RESULT_VOIDED: "Voided",
	RESULT_DENIED_BY_RISK: "Denied By Risk",
	RESULT_HOST_TIMEOUT: "Failed",
	"CANCELED": "Cancelled",
	"CANCELLED": "Cancelled",
}

# Integration Guide chapter 5. Shown to staff, never to the customer.
AUTH_RESPONSE_CODES = {
	"00": "Approved",
	"05": "Please contact issuer",
	"14": "Invalid card number",
	"33": "Expired card",
	"36": "Restricted card",
	"38": "Allowable PIN tries exceeded",
	"51": "Not sufficient funds",
	"54": "Expired card",
	"55": "Incorrect PIN",
	"61": "Exceeds withdrawal amount limit",
	"62": "Restricted card",
	"65": "Exceeds withdrawal frequency limit",
	"75": "Allowable number of PIN tries exceeded",
	"76": "Ineligible account",
	"78": "Refer to Issuer",
	"91": "Issuer is inoperative",
}

_TIMEOUT = (10, 30)  # connect, read


def get_settings(gateway=None):
	"""The configuration row for a BENEFIT gateway.

	Takes a gateway name so more than one BENEFIT terminal could exist. Defaults to
	the standard one for the decrypt path, which has to read the resource key before
	it knows which transaction the payload belongs to.
	"""
	from worldshading.payments.utils import _gateway_settings

	settings = _gateway_settings(gateway or GATEWAY)

	if not settings:
		frappe.throw(_("{0} is not configured").format(gateway or GATEWAY))

	return settings


def currency_code(currency):
	code = CURRENCY_CODES.get((currency or "").upper())
	if not code:
		frappe.throw(
			_("BENEFIT does not accept {0}. Only BHD is enabled on this terminal.").format(currency)
		)
	return code


def source_document(txn):
	"""The document the customer is actually paying -- usually the Sales Invoice.

	`reference_name` on the transaction is the Payment Request; one hop further is
	the thing a human recognises, and that is what belongs in the bank's portal.
	"""
	if txn.payment_request:
		reference = frappe.db.get_value(
			"Payment Request", txn.payment_request, "reference_name"
		)
		if reference:
			return reference

	return txn.reference_name or ""


def build_trandata(settings, txn):
	"""The plaintext payload, before encryption.

	A single-element JSON array -- that is not a typo, it is what both the guide and
	BENEFIT's own Python plugin do for the outer body and the inner payload.

	The UDFs are populated deliberately. BENEFIT's Python integration guide asks for
	invoice/customer identifiers in them because they show up in the merchant portal
	and are what you have to work with in a dispute. (An older ASP sample annotates
	udf1 "always keep it empty"; the current Python sample and guide contradict it,
	and the portal view is worth more than the stale comment.)

	  udf1  the document being paid, e.g. the Sales Invoice
	  udf2  the Payment Request
	  udf3  our link token -- also our fallback for matching a callback

	cardType "D" mirrors the vendor plugin, which marks it do-not-change. BENEFIT is
	a Bahraini debit network; the hosted page defaults to Debit regardless.

	Note we do NOT send `resourceKey` inside the payload. The vendor sample includes
	it, but it is the very key the payload is encrypted with, so it tells the gateway
	nothing it does not already have. Verified unnecessary against the live terminal.
	"""
	return json.dumps([{
		"amt": format_amount(txn.amount, txn.currency),
		"action": ACTION_PURCHASE,
		"cardType": CARD_TYPE_DEBIT,
		"password": settings.get_password("tranportal_password"),
		"id": settings.tranportal_id,
		"currencycode": currency_code(txn.currency),
		"trackId": txn.track_id,
		"udf1": source_document(txn),
		"udf2": txn.reference_name or "",
		"udf3": txn.token,
		"udf4": "",
		"udf5": "",
		"responseURL": callback_url("notify"),
		"errorURL": callback_url("error"),
	}])


def initiate(txn):
	"""Create the payment at BENEFIT and return the URL to send the customer to.

	Called when the customer clicks the pay link, never when the Payment Request is
	created -- a BENEFIT payment URL is short-lived, and a Payment Request email may
	well be opened days later.
	"""
	settings = get_settings(txn.gateway)
	settings.validate_enabled()

	plaintext = build_trandata(settings, txn)
	resource_key = settings.get_password("resource_key")

	body = [{
		"id": settings.tranportal_id,
		"trandata": crypto.encrypt(resource_key, plaintext),
	}]

	endpoint = settings.get_endpoint()

	# The plaintext contains the tranportal password. Log the encrypted form only.
	log_raw("benefit.initiate.request", json.dumps(body))

	response = requests.post(
		endpoint,
		data=json.dumps(body),
		headers={"Content-Type": "application/json", "Accept": "application/json"},
		timeout=_TIMEOUT,
	)
	response.raise_for_status()

	log_raw("benefit.initiate.response", response.text)

	return parse_init_response(response.text)


def parse_init_response(text):
	"""Parse the initial response, which is plain JSON -- not encrypted.

	Returns ``(payment_id, redirect_url)``.
	"""
	try:
		payload = json.loads(text)
	except ValueError:
		frappe.throw(_("BENEFIT returned an unreadable response"))

	if isinstance(payload, list):
		if not payload:
			frappe.throw(_("BENEFIT returned an empty response"))
		payload = payload[0]

	status = str(payload.get("status") or "").strip()

	if status != "1":
		error = payload.get("error") or ""
		error_text = payload.get("errorText") or ""
		logger().error("benefit.initiate failed: %s %s", error, error_text)
		frappe.throw(
			_("BENEFIT rejected the payment request: {0} {1}").format(error, error_text)
		)

	result = (payload.get("result") or "").strip()

	# What the gateway ACTUALLY returns (verified against the test terminal):
	#
	#   "result": "https://test.benefit-gateway.bh/payment/paymentpage.htm?PaymentID=119..."
	#
	# i.e. the complete payment page URL with PaymentID already in the query string.
	# The Integration Guide (section 4.1) documents "<paymentId>:<payment page URL>"
	# instead. Both forms are handled -- the documented one second -- because the
	# guide may be describing an older or a differently configured deployment, and we
	# should not break if this terminal is switched to it.
	if result[:4].lower() == "http":
		payment_id = ""
		for key, values in parse_qs(urlparse(result).query).items():
			if key.lower() == "paymentid" and values:
				payment_id = values[0]
				break

		if not payment_id:
			frappe.throw(_("BENEFIT returned a payment URL with no PaymentID: {0}").format(result))

		return payment_id, result

	# Documented form. Split once only -- the URL carries its own colon after
	# "https", and splitting on every colon shreds it.
	payment_id, separator_found, url = result.partition(":")

	if not separator_found or not url.strip():
		frappe.throw(_("BENEFIT returned an unexpected result: {0}").format(result))

	payment_id = payment_id.strip()
	url = url.strip()

	joiner = "&" if "?" in url else "?"

	return payment_id, "{0}{1}PaymentID={2}".format(url, joiner, payment_id)


def parse_trandata(trandata):
	"""Decrypt and parse an encrypted payload from BENEFIT."""
	settings = get_settings()
	plaintext = crypto.decrypt(settings.get_password("resource_key"), trandata)

	payload = json.loads(plaintext)
	if isinstance(payload, list):
		payload = payload[0] if payload else {}

	return payload


def apply_result(txn, data):
	"""Copy a decrypted gateway result onto the transaction record.

	Returns True when the payment was captured.
	"""
	result = (data.get("result") or "").strip().upper()

	txn.db_set("result", result, update_modified=False)
	txn.db_set("payment_id", data.get("paymentId") or txn.payment_id, update_modified=False)
	txn.db_set("transaction_id", data.get("transId") or "", update_modified=False)
	txn.db_set("reference_number", data.get("ref") or "", update_modified=False)
	txn.db_set("auth_code", data.get("authCode") or "", update_modified=False)

	auth_response_code = str(data.get("authRespCode") or "")
	txn.db_set("auth_response_code", auth_response_code, update_modified=False)
	txn.db_set(
		"gateway_message",
		AUTH_RESPONSE_CODES.get(auth_response_code, ""),
		update_modified=False,
	)

	status = _STATUS_BY_RESULT.get(result, "Failed")
	txn.db_set("status", status, update_modified=False)

	return status == "Captured"
