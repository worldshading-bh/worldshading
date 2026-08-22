# -*- coding: utf-8 -*-
"""Daily reference exchange rates for ERPNext v12.

Rates are fetched from Frankfurter and stored in ERPNext's standard Currency
Exchange DocType. Transactions therefore keep using ERPNext's normal lookup and
do not depend on an external API while a user is saving a document.
"""

from __future__ import unicode_literals

import time
from datetime import datetime

import frappe
from frappe import _
from frappe.utils import cint, date_diff, flt, getdate, now_datetime


PROVIDER_NAME = "Frankfurter"
RATE_URL = "https://api.frankfurter.dev/v2/rate/{0}/{1}"
REQUEST_TIMEOUT = 10
REQUEST_ATTEMPTS = 3
DEFAULT_MAX_AGE_DAYS = 4

WS_SETTINGS_CLIENT_SCRIPT = """// World Shading managed currency exchange button.
frappe.ui.form.on("WS Settings", {
    fetch_currency_exchange_now: function (frm) {
        function fetch_rates() {
            frappe.call({
                method: "worldshading.api.currency_exchange.fetch_now",
                freeze: true,
                freeze_message: __("Fetching exchange rates..."),
                callback: function (r) {
                    if (!r.exc && r.message) {
                        frappe.msgprint({
                            title: __("Currency Exchange"),
                            message: frappe.utils.escape_html(r.message.message || ""),
                            indicator: r.message.failed && r.message.failed.length ? "orange" : "green"
                        });
                        frm.reload_doc();
                    }
                }
            });
        }

        if (frm.is_dirty()) {
            frm.save().then(fetch_rates);
        } else {
            fetch_rates();
        }
    }
});
"""


def _utc_today():
	return datetime.utcnow().date()


def setup_ws_settings_fields():
	"""Install the settings fields on the UI-created WS Settings DocType."""
	from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

	if not frappe.db.exists("DocType", "WS Settings"):
		return False

	legacy_value = None

	if frappe.get_meta("WS Settings").has_field("currency_exchange_pairs"):
		legacy_value = frappe.db.get_single_value(
			"WS Settings", "currency_exchange_pairs")

	create_custom_fields({
		"WS Settings": [
			{
				"fieldname": "currency_exchange_section",
				"label": "Currency Exchange",
				"fieldtype": "Section Break",
				"insert_after": "work_order_admin",
				"collapsible": 1
			},
			{
				"fieldname": "enable_auto_currency_exchange",
				"label": "Automatic Daily Fetch",
				"fieldtype": "Check",
				"insert_after": "currency_exchange_section",
				"default": "0",
				"description": ""
			},
			{
				"fieldname": "currency_exchange_pairs",
				"label": "Currency Pairs",
				"fieldtype": "Table",
				"options": "Currency Exchange Pair",
				"insert_after": "enable_auto_currency_exchange",
				"depends_on": "eval:doc.enable_auto_currency_exchange==1",
				"description": ""
			},
			{
				"fieldname": "currency_exchange_max_age_days",
				"label": "Accept Rates Up To (Days Old)",
				"fieldtype": "Int",
				"insert_after": "currency_exchange_pairs",
				"default": str(DEFAULT_MAX_AGE_DAYS),
				"depends_on": "eval:doc.enable_auto_currency_exchange==1",
				"description": "Allows Friday's published rate through weekends and holidays."
			},
			{
				"fieldname": "currency_exchange_column",
				"fieldtype": "Column Break",
				"insert_after": "currency_exchange_max_age_days"
			},
			{
				"fieldname": "currency_exchange_provider",
				"label": "Source",
				"fieldtype": "Data",
				"insert_after": "currency_exchange_column",
				"default": PROVIDER_NAME,
				"read_only": 1
			},
			{
				"fieldname": "fetch_currency_exchange_now",
				"label": "Fetch Rates Now",
				"fieldtype": "Button",
				"insert_after": "currency_exchange_provider"
			},
			{
				"fieldname": "currency_exchange_last_sync",
				"label": "Last Successful Fetch",
				"fieldtype": "Datetime",
				"insert_after": "fetch_currency_exchange_now",
				"read_only": 1
			},
			{
				"fieldname": "currency_exchange_last_status",
				"label": "Last Fetch Status",
				"fieldtype": "Small Text",
				"insert_after": "currency_exchange_last_sync",
				"read_only": 1
			}
		]
	}, update=True)

	if cint(frappe.db.get_single_value(
		"WS Settings", "currency_exchange_max_age_days")) <= 0:
		frappe.db.set_value(
			"WS Settings", None, "currency_exchange_max_age_days",
			DEFAULT_MAX_AGE_DAYS, update_modified=False)
	if not frappe.db.get_single_value(
		"WS Settings", "currency_exchange_provider"):
		frappe.db.set_value(
			"WS Settings", None, "currency_exchange_provider",
			PROVIDER_NAME, update_modified=False)

	_ensure_ws_settings_client_script()

	# This field was briefly shipped as Small Text. Preserve those values when the
	# field is upgraded to a proper child table, then leave the legacy Singles row
	# harmlessly unused.
	if isinstance(legacy_value, str) and legacy_value.strip():
		legacy_pairs = parse_currency_pairs(legacy_value)
		settings = frappe.get_single("WS Settings")
		existing = set((row.from_currency, row.to_currency)
			for row in (settings.get("currency_exchange_pairs") or []))
		for from_currency, to_currency in legacy_pairs:
			if (from_currency, to_currency) not in existing:
				settings.append("currency_exchange_pairs", {
					"enabled": 1,
					"from_currency": from_currency,
					"to_currency": to_currency
				})
		settings.save(ignore_permissions=True)


def _ensure_ws_settings_client_script():
	name = "WS Settings-Client"
	if frappe.db.exists("Custom Script", name):
		doc = frappe.get_doc("Custom Script", name)
		if doc.script != WS_SETTINGS_CLIENT_SCRIPT:
			doc.script = WS_SETTINGS_CLIENT_SCRIPT
			doc.save(ignore_permissions=True)
	else:
		frappe.get_doc({
			"doctype": "Custom Script",
			"dt": "WS Settings",
			"script": WS_SETTINGS_CLIENT_SCRIPT
		}).insert(ignore_permissions=True)


def parse_currency_pairs(value):
	"""Return unique, normalized pairs from newline/comma separated settings."""
	pairs = []
	seen = set()
	if isinstance(value, (list, tuple)):
		for row in value:
			if not cint(row.get("enabled", 1)):
				continue
			from_currency = (row.get("from_currency") or "").strip().upper()
			to_currency = (row.get("to_currency") or "").strip().upper()
			_validate_pair(from_currency, to_currency)
			if from_currency != to_currency and (from_currency, to_currency) not in seen:
				seen.add((from_currency, to_currency))
				pairs.append((from_currency, to_currency))
		return pairs

	value = (value or "").replace(",", "\n")

	for line in value.splitlines():
		line = line.strip().upper().replace(" ", "")
		separator = "/" if "/" in line else (":" if ":" in line else None)
		if not separator:
			raise ValueError(_("Invalid currency pair: {0}. Use USD/BHD.").format(line))

		parts = line.split(separator)
		if len(parts) != 2:
			raise ValueError(_("Invalid currency pair: {0}. Use ISO codes such as USD/BHD.").format(line))
		_validate_pair(parts[0], parts[1])
		if parts[0] == parts[1]:
			continue

		pair = (parts[0], parts[1])
		if pair not in seen:
			seen.add(pair)
			pairs.append(pair)

	return pairs


def _validate_pair(from_currency, to_currency):
	if not all(len(part) == 3 and part.isalpha()
		for part in (from_currency, to_currency)):
		raise ValueError(_("Invalid currency pair. Select valid ISO currency codes."))


def _validate_payload(payload, from_currency, to_currency):
	if not isinstance(payload, dict):
		raise ValueError("Provider returned an invalid response")
	if not payload.get("date"):
		raise ValueError("Provider response has no effective date")
	if payload.get("base") != from_currency or payload.get("quote") != to_currency:
		raise ValueError("Provider returned a different currency pair")

	rate = flt(payload.get("rate"))
	if rate <= 0:
		raise ValueError("Provider returned an invalid exchange rate")

	rate_date = getdate(payload.get("date"))
	if rate_date > _utc_today():
		raise ValueError("Provider returned a future exchange-rate date")
	return {"date": rate_date, "rate": rate}


def fetch_rate(from_currency, to_currency, transaction_date=None):
	"""Fetch and validate one reference rate; no database writes happen here."""
	import requests

	params = {}
	if transaction_date:
		params["date"] = getdate(transaction_date).isoformat()

	last_error = None
	for attempt in range(REQUEST_ATTEMPTS):
		try:
			response = requests.get(
				RATE_URL.format(from_currency, to_currency),
				params=params, timeout=REQUEST_TIMEOUT)
			response.raise_for_status()
			return _validate_payload(response.json(), from_currency, to_currency)
		except (requests.Timeout, requests.ConnectionError) as error:
			last_error = error
			if attempt < REQUEST_ATTEMPTS - 1:
				time.sleep(1)

	if last_error:
		raise last_error
	raise ValueError("Exchange-rate request failed")


def _existing_rate(rate_date, from_currency, to_currency):
	return frappe.db.get_value("Currency Exchange", {
		"date": rate_date,
		"from_currency": from_currency,
		"to_currency": to_currency
	}, "name")


def store_rate(rate_date, from_currency, to_currency, rate):
	"""Insert only when no manual or automatic record already exists that day."""
	existing = _existing_rate(rate_date, from_currency, to_currency)
	if existing:
		return {"status": "existing", "name": existing}

	doc = frappe.new_doc("Currency Exchange")
	doc.date = rate_date
	doc.from_currency = from_currency
	doc.to_currency = to_currency
	doc.exchange_rate = rate
	# Set these explicitly after new_doc. This production site has customized
	# Currency Exchange metadata and did not retain the values passed in a dict.
	doc.for_buying = 1
	doc.for_selling = 1
	doc.insert(ignore_permissions=True)
	return {"status": "created", "name": doc.name}


def _fetch_pair(from_currency, to_currency, max_age_days):
	fetched = fetch_rate(from_currency, to_currency)
	if date_diff(_utc_today(), fetched["date"]) > max_age_days:
		raise ValueError(
			"Latest provider rate is older than {0} days".format(max_age_days))
	result = [store_rate(
		fetched["date"], from_currency, to_currency, fetched["rate"])]

	reverse_rate = 1.0 / fetched["rate"]
	result.append(store_rate(
		fetched["date"], to_currency, from_currency, reverse_rate))
	return fetched, result


def _set_status(message, successful=False):
	frappe.db.set_value(
		"WS Settings", None, "currency_exchange_last_status", message,
		update_modified=False)
	if successful:
		frappe.db.set_value(
			"WS Settings", None, "currency_exchange_last_sync", now_datetime(),
			update_modified=False)


def run_daily(force=False):
	"""Scheduled entry point. Each configured pair succeeds or fails independently."""
	settings = frappe.get_single("WS Settings")
	if not force and not cint(settings.get("enable_auto_currency_exchange")):
		return {"skipped": True, "message": "Automatic currency exchange is disabled."}

	pairs = parse_currency_pairs(settings.get("currency_exchange_pairs"))
	if not pairs:
		message = "No currency pairs are configured in WS Settings."
		_set_status(message)
		if force:
			frappe.throw(_(message))
		return {"skipped": True, "message": message}

	created = 0
	existing = 0
	errors = []
	dates = []
	max_age_days = cint(settings.get("currency_exchange_max_age_days"))
	if max_age_days <= 0:
		max_age_days = DEFAULT_MAX_AGE_DAYS

	for from_currency, to_currency in pairs:
		try:
			fetched, stored = _fetch_pair(
				from_currency, to_currency, max_age_days)
			dates.append(fetched["date"].isoformat())
			for row in stored:
				if row["status"] == "created":
					created += 1
				else:
					existing += 1
		except Exception:
			errors.append("{0}/{1}".format(from_currency, to_currency))
			frappe.log_error(frappe.get_traceback(),
				"Currency exchange fetch failed: {0}/{1}".format(from_currency, to_currency))

	status = "Created {0}; already existed {1}; failed {2}. Provider date: {3}.".format(
		created, existing, len(errors), ", ".join(sorted(set(dates))) or "none")
	_set_status(status, successful=bool(dates) and not errors)

	return {
		"created": created,
		"existing": existing,
		"failed": errors,
		"provider_dates": sorted(set(dates)),
		"message": status
	}


@frappe.whitelist()
def fetch_now():
	if "System Manager" not in frappe.get_roles():
		frappe.throw(_("Only a System Manager can fetch exchange rates."), frappe.PermissionError)
	return run_daily(force=True)
