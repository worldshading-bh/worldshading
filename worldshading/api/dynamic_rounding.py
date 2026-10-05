# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP

import frappe
from frappe import _
from frappe.utils import cint, flt
from erpnext.controllers.taxes_and_totals import calculate_taxes_and_totals


PILOT_USER = "hilal@worldshading.com"
SUPPORTED_DOCTYPES = ("Quotation", "Sales Order", "Sales Invoice")
ACTIVE_ROUNDING_DOCTYPES = ("Quotation", "Sales Order", "Sales Invoice")


class DynamicRoundingConfigurationError(ValueError):
	pass


def is_pilot_user(user):
	return user == PILOT_USER


def _get_value(rule, fieldname):
	if isinstance(rule, dict):
		return rule.get(fieldname)
	return getattr(rule, fieldname, None)


def _to_decimal(value, fieldname):
	try:
		decimal_value = Decimal(str(value))
	except (InvalidOperation, TypeError, ValueError):
		raise DynamicRoundingConfigurationError(
			_("Dynamic rounding field {0} has an invalid value.").format(fieldname)
		)
	if not decimal_value.is_finite():
		raise DynamicRoundingConfigurationError(
			_("Dynamic rounding field {0} has an invalid value.").format(fieldname)
		)
	return decimal_value


def _prepare_rules(rules):
	prepared = []
	valid_methods = ("Nearest", "Lowest", "Highest")

	for rule in rules or []:
		minimum_amount = _to_decimal(_get_value(rule, "minimum_amount"), "Minimum Amount")
		maximum_amount = _to_decimal(_get_value(rule, "maximum_amount"), "Maximum Amount")
		rounding_value = _to_decimal(_get_value(rule, "rounding_value"), "Rounding Value")
		rounding_method = _get_value(rule, "rounding_method")

		if maximum_amount <= minimum_amount:
			raise DynamicRoundingConfigurationError(
				_("Dynamic rounding maximum amount must be greater than minimum amount.")
			)
		if rounding_value <= 0:
			raise DynamicRoundingConfigurationError(
				_("Dynamic rounding value must be greater than zero.")
			)
		if rounding_method not in valid_methods:
			raise DynamicRoundingConfigurationError(
				_("Dynamic rounding method must be Nearest, Lowest, or Highest.")
			)

		prepared.append({
			"minimum_amount": minimum_amount,
			"maximum_amount": maximum_amount,
			"rounding_method": rounding_method,
			"rounding_value": rounding_value,
		})

	prepared.sort(key=lambda row: (row["minimum_amount"], row["maximum_amount"]))

	for index in range(1, len(prepared)):
		if prepared[index]["minimum_amount"] < prepared[index - 1]["maximum_amount"]:
			raise DynamicRoundingConfigurationError(
				_("Dynamic rounding amount ranges must not overlap.")
			)

	return prepared


def calculate_dynamic_rounding(amount, rules, doctype=None, is_return=False):
	amount = _to_decimal(amount, "Grand Total")
	absolute_amount = abs(amount)
	prepared_rules = _prepare_rules(rules)
	matched_rule = None

	for rule in prepared_rules:
		if rule["minimum_amount"] <= absolute_amount < rule["maximum_amount"]:
			matched_rule = rule
			break

	if not matched_rule:
		return None

	rounding_modes = {
		"Nearest": ROUND_HALF_UP,
		"Lowest": ROUND_FLOOR,
		"Highest": ROUND_CEILING,
	}
	rounding_value = matched_rule["rounding_value"]
	# Sales returns reverse the positive rounding direction, including Lowest/Highest.
	mirror_return = doctype == "Sales Invoice" and cint(is_return) and amount < 0
	rounding_amount = absolute_amount if mirror_return else amount
	units = (rounding_amount / rounding_value).quantize(
		Decimal("1"), rounding=rounding_modes[matched_rule["rounding_method"]]
	)
	rounded_total = units * rounding_value
	if mirror_return:
		rounded_total = -rounded_total

	result = dict(matched_rule)
	result.update({
		"original_total": amount,
		"rounded_total": rounded_total,
		"rounding_adjustment": rounded_total - amount,
	})
	return result


def _recalculate_sales_invoice_outstanding(doc):
	calculator = object.__new__(calculate_taxes_and_totals)
	calculator.doc = doc
	calculator.calculate_outstanding_amount()


def validate_sales_invoice_payment_change(doc, method=None):
	_reconcile_sales_invoice_change(doc)


def _reconcile_sales_invoice_change(doc):
	if not cint(getattr(doc, "is_pos", 0)) or cint(getattr(doc, "is_return", 0)):
		return

	payable_total = flt(
		doc.rounded_total or doc.grand_total,
		doc.precision("rounded_total"),
	)
	paid_amount = flt(doc.paid_amount, doc.precision("paid_amount"))
	overpayment = flt(
		paid_amount - payable_total,
		doc.precision("change_amount"),
	)
	cash_amount = flt(sum(
		flt(payment.amount)
		for payment in (getattr(doc, "payments", None) or [])
		if payment.type == "Cash" and flt(payment.amount) > 0
	), doc.precision("paid_amount"))

	if overpayment > 0 and overpayment > cash_amount:
		frappe.throw(_(
			"Payment exceeds the rounded total by {0}, but there is not enough "
			"Cash payment to return this amount as change. Please correct the "
			"non-cash payment."
		).format("{0:.3f}".format(overpayment)))

	doc.write_off_amount = 0
	doc.base_write_off_amount = 0
	doc.change_amount = overpayment if overpayment > 0 else 0
	doc.base_change_amount = flt(
		doc.change_amount * doc.conversion_rate,
		doc.precision("base_change_amount"),
	)

	if doc.party_account_currency == doc.currency:
		doc.outstanding_amount = flt(
			payable_total - flt(doc.total_advance) - paid_amount + doc.change_amount,
			doc.precision("outstanding_amount"),
		)
	else:
		doc.outstanding_amount = flt(
			doc.base_rounded_total - flt(doc.total_advance)
			- flt(doc.base_paid_amount) + doc.base_change_amount,
			doc.precision("outstanding_amount"),
		)


@frappe.whitelist()
def get_dynamic_rounding_client_settings():
	settings = frappe.get_single("WS Settings")
	if not cint(settings.get("enable_dynamic_rounding")):
		return {"enabled": False, "rules": []}

	try:
		rules = _prepare_rules(settings.get("dynamic_rounding_rules") or [])
	except DynamicRoundingConfigurationError as error:
		return {"enabled": False, "rules": [], "error": str(error)}

	return {
		"enabled": True,
		"rules": [{
			"minimum_amount": float(rule["minimum_amount"]),
			"maximum_amount": float(rule["maximum_amount"]),
			"rounding_method": rule["rounding_method"],
			"rounding_value": float(rule["rounding_value"]),
		} for rule in rules],
	}


def apply_dynamic_rounding(doc, method=None):
	if doc.doctype not in ACTIVE_ROUNDING_DOCTYPES:
		return False

	if doc.is_rounded_total_disabled():
		return False

	settings = frappe.get_single("WS Settings")
	if not cint(settings.get("enable_dynamic_rounding")):
		return False

	rules = settings.get("dynamic_rounding_rules") or []

	try:
		result = calculate_dynamic_rounding(
			doc.grand_total, rules, doc.doctype, getattr(doc, "is_return", False)
		)
	except DynamicRoundingConfigurationError as error:
		frappe.throw(
			_("Dynamic rounding configuration error: {0}").format(str(error))
		)
		return False

	if not result:
		frappe.throw(
			_("No dynamic rounding rule matches this amount. Please check WS Settings.")
		)
		return False

	rounded_total = flt(
		result["rounded_total"], doc.precision("rounded_total")
	)
	if result["original_total"] and not rounded_total:
		frappe.throw(
			_("Dynamic rounding cannot reduce a non-zero total to zero in ERPNext v12.")
		)
		return False

	doc.rounded_total = rounded_total
	doc.rounding_adjustment = flt(
		doc.rounded_total - doc.grand_total,
		doc.precision("rounding_adjustment"),
	)
	doc.base_rounded_total = flt(
		doc.rounded_total * doc.conversion_rate,
		doc.precision("base_rounded_total"),
	)
	doc.base_rounding_adjustment = flt(
		doc.base_rounded_total - doc.base_grand_total,
		doc.precision("base_rounding_adjustment"),
	)
	if (doc.doctype == "Sales Invoice" and cint(getattr(doc, "is_pos", 0))
			and not cint(getattr(doc, "is_return", 0))):
		doc.write_off_amount = 0
		doc.base_write_off_amount = 0
		doc.change_amount = 0
		doc.base_change_amount = 0
	if doc.doctype == "Sales Invoice":
		_recalculate_sales_invoice_outstanding(doc)
		validate_sales_invoice_payment_change(doc)
	doc.set_total_in_words()
	if not (doc.doctype == "Sales Invoice" and getattr(doc, "is_return", False)):
		doc.set_payment_schedule()
		doc.validate_payment_schedule_amount()

	return True


def sync_dynamic_rounding_after_submit(doc, method=None):
	"""Persist only derived Sales Order totals after an allowed submitted update."""
	if doc.doctype != "Sales Order" or doc.is_rounded_total_disabled():
		return False

	settings = frappe.get_single("WS Settings")
	if not cint(settings.get("enable_dynamic_rounding")):
		return False

	try:
		result = calculate_dynamic_rounding(
			doc.grand_total,
			settings.get("dynamic_rounding_rules") or [],
			doc.doctype,
			False,
		)
	except DynamicRoundingConfigurationError as error:
		frappe.throw(_("Dynamic rounding configuration error: {0}").format(str(error)))
		return False

	if not result:
		frappe.throw(_("No dynamic rounding rule matches this amount. Please check WS Settings."))
		return False

	doc.rounded_total = flt(result["rounded_total"], doc.precision("rounded_total"))
	doc.rounding_adjustment = flt(
		doc.rounded_total - doc.grand_total, doc.precision("rounding_adjustment")
	)
	doc.base_rounded_total = flt(
		doc.rounded_total * doc.conversion_rate, doc.precision("base_rounded_total")
	)
	doc.base_rounding_adjustment = flt(
		doc.base_rounded_total - doc.base_grand_total,
		doc.precision("base_rounding_adjustment"),
	)
	doc.set_total_in_words()

	values = {
		"rounded_total": doc.rounded_total,
		"rounding_adjustment": doc.rounding_adjustment,
		"base_rounded_total": doc.base_rounded_total,
		"base_rounding_adjustment": doc.base_rounding_adjustment,
	}
	if hasattr(doc, "in_words"):
		values["in_words"] = doc.in_words
	if hasattr(doc, "base_in_words"):
		values["base_in_words"] = doc.base_in_words
	frappe.db.set_value(doc.doctype, doc.name, values, update_modified=False)
	return True


@frappe.whitelist()
def get_dynamic_rounding_preview(doctype, grand_total, core_rounded_total=None, currency=None,
		is_return=False):
	if not is_pilot_user(frappe.session.user):
		return None

	if doctype not in SUPPORTED_DOCTYPES:
		frappe.throw(_("Dynamic rounding preview is not available for {0}.").format(doctype))

	settings = frappe.get_single("WS Settings")
	if not cint(settings.get("enable_dynamic_rounding")):
		return {"error": _("Dynamic rounding is disabled in WS Settings.")}

	try:
		result = calculate_dynamic_rounding(
			grand_total, settings.get("dynamic_rounding_rules") or [], doctype, is_return
		)
	except DynamicRoundingConfigurationError as error:
		return {"error": str(error)}

	if not result:
		return {
			"error": _("No dynamic rounding rule matches this amount.")
		}

	core_total = _to_decimal(
		core_rounded_total if core_rounded_total not in (None, "") else grand_total,
		"Core Rounded Total",
	)

	return {
		"currency": currency,
		"original_total": float(result["original_total"]),
		"core_rounded_total": float(core_total),
		"dynamic_rounded_total": float(result["rounded_total"]),
		"dynamic_adjustment": float(result["rounding_adjustment"]),
		"difference_from_core": float(result["rounded_total"] - core_total),
		"minimum_amount": float(result["minimum_amount"]),
		"maximum_amount": float(result["maximum_amount"]),
		"rounding_method": result["rounding_method"],
		"rounding_value": float(result["rounding_value"]),
	}
