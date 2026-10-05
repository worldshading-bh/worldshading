(function () {
	"use strict";

	var PILOT_USER = "hilal@worldshading.com";
	var SUPPORTED_DOCTYPES = ["Quotation", "Sales Order", "Sales Invoice"];
	var namespace;

	window.worldshading = window.worldshading || {};
	window.worldshading.dynamic_rounding = window.worldshading.dynamic_rounding || {
		settings: { enabled: false, rules: [] }
	};
	namespace = window.worldshading.dynamic_rounding;

	function calculate_dynamic_total(amount, rules, doctype, is_return) {
		var digits = precision("rounded_total");
		var scale = Math.pow(10, digits);
		var amount_units = Math.round(flt(amount) * scale);
		var absolute_amount_units = Math.abs(amount_units);
		var matched_rule = null;
		var rounding_value_units;
		var quotient;
		var units;

		(rules || []).some(function (rule) {
			var minimum_units = Math.round(flt(rule.minimum_amount) * scale);
			var maximum_units = Math.round(flt(rule.maximum_amount) * scale);

			if (
				absolute_amount_units >= minimum_units
				&& absolute_amount_units < maximum_units
			) {
				matched_rule = rule;
				return true;
			}
			return false;
		});

		rounding_value_units = matched_rule
			? Math.round(flt(matched_rule.rounding_value) * scale)
			: 0;
		if (!matched_rule || rounding_value_units <= 0) {
			return null;
		}

		// Mirror positive rounding only for negative Sales Invoice returns.
		var mirror_return = doctype === "Sales Invoice" && cint(is_return) && flt(amount) < 0;
		quotient = (mirror_return ? absolute_amount_units : amount_units) / rounding_value_units;
		if (matched_rule.rounding_method === "Lowest") {
			units = Math.floor(quotient + 0.000000001);
		} else if (matched_rule.rounding_method === "Highest") {
			units = Math.ceil(quotient - 0.000000001);
		} else if (matched_rule.rounding_method === "Nearest") {
			units = quotient >= 0
				? Math.floor(quotient + 0.5)
				: Math.ceil(quotient - 0.5);
		} else {
			return null;
		}

		if (mirror_return) {
			units = -units;
		}
		return flt(
			(units * rounding_value_units) / scale,
			digits
		);
	}

	namespace.calculate = calculate_dynamic_total;

	function apply_dynamic_rounding(calculator) {
		var settings = calculator.frm.__ws_dynamic_rounding_settings
			|| { enabled: false, rules: [] };
		var doc = calculator.frm.doc;
		var rounded_total;
		var rounding_disabled;

		if (
			!settings.enabled
			|| SUPPORTED_DOCTYPES.indexOf(doc.doctype) === -1
			|| doc.docstatus > 0
		) {
			return;
		}

		rounding_disabled = cint(doc.disable_rounded_total)
			|| cint(frappe.sys_defaults.disable_rounded_total);
		if (rounding_disabled) {
			return;
		}

		rounded_total = calculate_dynamic_total(
			doc.grand_total, settings.rules, doc.doctype, doc.is_return
		);
		if (rounded_total === null || (flt(doc.grand_total) && !rounded_total)) {
			return;
		}

		doc.rounded_total = rounded_total;
		doc.rounding_adjustment = flt(
			doc.rounded_total - doc.grand_total,
			precision("rounding_adjustment")
		);
		calculator.set_in_company_currency(
			doc,
			["rounding_adjustment", "rounded_total"]
		);
		doc.base_rounding_adjustment = flt(
			doc.base_rounded_total - doc.base_grand_total,
			precision("base_rounding_adjustment")
		);
		if (doc.doctype === "Sales Invoice" && cint(doc.is_pos) && !cint(doc.is_return)) {
			doc.write_off_amount = 0;
			doc.base_write_off_amount = 0;
		}
	}

	function reconcile_sales_invoice_change(calculator) {
		var doc = calculator.frm.doc;
		var payable_total;
		var paid_amount;
		var overpayment;
		var cash_amount = 0;

		if (doc.doctype !== "Sales Invoice" || !cint(doc.is_pos) || cint(doc.is_return)) {
			return;
		}

		payable_total = flt(
			doc.rounded_total || doc.grand_total,
			precision("rounded_total")
		);
		paid_amount = flt(doc.paid_amount, precision("paid_amount"));
		overpayment = flt(
			paid_amount - payable_total,
			precision("change_amount")
		);
		(doc.payments || []).forEach(function (payment) {
			if (payment.type === "Cash" && flt(payment.amount) > 0) {
				cash_amount += flt(payment.amount);
			}
		});
		cash_amount = flt(cash_amount, precision("paid_amount"));

		doc.write_off_amount = 0;
		doc.base_write_off_amount = 0;
		doc.change_amount = overpayment > 0 && overpayment <= cash_amount
			? overpayment
			: 0;
		doc.base_change_amount = flt(
			doc.change_amount * doc.conversion_rate,
			precision("base_change_amount")
		);

		if (doc.party_account_currency === doc.currency) {
			doc.outstanding_amount = flt(
				payable_total - flt(doc.total_advance) - paid_amount + doc.change_amount,
				precision("outstanding_amount")
			);
		} else {
			doc.outstanding_amount = flt(
				flt(doc.base_rounded_total) - flt(doc.total_advance)
				- flt(doc.base_paid_amount) + doc.base_change_amount,
				precision("outstanding_amount")
			);
		}
	}

	function wrap_form_method(frm, method_name, apply_before) {
		var original_method;
		var wrapped_method;

		if (!frm.cscript || typeof frm.cscript[method_name] !== "function") {
			return;
		}
		if (frm.cscript[method_name].__ws_dynamic_rounding) {
			return;
		}

		original_method = frm.cscript[method_name];
		wrapped_method = function () {
			var result;

			if (apply_before) {
				apply_dynamic_rounding(this);
			}
			result = original_method.apply(this, arguments);
			if (
				method_name === "calculate_outstanding_amount"
				|| method_name === "calculate_change_amount"
				|| method_name === "calculate_write_off_amount"
			) {
				reconcile_sales_invoice_change(this);
			}
			if (!apply_before) {
				apply_dynamic_rounding(this);
			}
			return result;
		};
		wrapped_method.__ws_dynamic_rounding = true;
		wrapped_method.__ws_original = original_method;
		frm.cscript[method_name] = wrapped_method;
	}

	function install_form_rounding(frm) {
		wrap_form_method(frm, "set_rounded_total", false);

		if (frm.doc.doctype === "Sales Invoice") {
			wrap_form_method(frm, "calculate_outstanding_amount", true);
			wrap_form_method(frm, "calculate_change_amount", true);
			wrap_form_method(frm, "calculate_write_off_amount", true);
		}
	}

	function load_client_settings(frm) {
		var request_generation = (frm.__ws_dynamic_rounding_request_generation || 0) + 1;
		frm.__ws_dynamic_rounding_request_generation = request_generation;
		frm.__ws_dynamic_rounding_settings = { enabled: false, rules: [] };

		frappe.call({
			method: "worldshading.api.dynamic_rounding.get_dynamic_rounding_client_settings",
			callback: function (response) {
				var settings = response.message || { enabled: false, rules: [] };
				var is_obsolete_form = typeof cur_frm !== "undefined" && cur_frm !== frm;

				if (
					request_generation !== frm.__ws_dynamic_rounding_request_generation
					|| is_obsolete_form
				) {
					return;
				}

				frm.__ws_dynamic_rounding_settings = settings;
				namespace.settings = settings;
				if (settings.error) {
					frappe.msgprint({
						title: __("Dynamic Rounding"),
						indicator: "orange",
						message: settings.error
					});
				}

				if (
					frm.doc.docstatus === 0
					&& frm.cscript
					&& typeof frm.cscript.calculate_taxes_and_totals === "function"
				) {
					frm.cscript.calculate_taxes_and_totals(false);
					frm.refresh_fields();
				}
			}
		});
	}

	function format_amount(value, currency) {
		return format_currency(flt(value), currency);
	}

	function show_preview(frm) {
		var grand_total = flt(frm.doc.grand_total);
		var has_core_rounded_total = frm.doc.rounded_total !== null
			&& frm.doc.rounded_total !== undefined
			&& frm.doc.rounded_total !== "";
		var core_rounded_total = has_core_rounded_total
			? flt(frm.doc.rounded_total)
			: grand_total;
		var currency = frm.doc.currency || frappe.defaults.get_default("currency");

		frappe.call({
			method: "worldshading.api.dynamic_rounding.get_dynamic_rounding_preview",
			args: {
				doctype: frm.doctype,
				grand_total: grand_total,
				core_rounded_total: core_rounded_total,
				currency: currency,
				is_return: cint(frm.doc.is_return)
			},
			freeze: true,
			freeze_message: __("Calculating dynamic rounding preview..."),
			callback: function (response) {
				var result = response.message;

				if (!result) {
					return;
				}

				if (result.error) {
					frappe.msgprint({
						title: __("Dynamic Rounding Preview"),
						indicator: "orange",
						message: __(result.error)
					});
					return;
				}

				frappe.msgprint({
					title: __("Dynamic Rounding Preview"),
					indicator: "blue",
					message: [
						"<p><strong>" + __("Preview only. Document totals are unchanged.") + "</strong></p>",
						"<table class=\"table table-bordered\">",
						"<tr><td>" + __("Grand Total") + "</td><td>" + format_amount(result.original_total, currency) + "</td></tr>",
						"<tr><td>" + __("Core Rounded Total") + "</td><td>" + format_amount(result.core_rounded_total, currency) + "</td></tr>",
						"<tr><td>" + __("Dynamic Rounded Total") + "</td><td>" + format_amount(result.dynamic_rounded_total, currency) + "</td></tr>",
						"<tr><td>" + __("Dynamic Adjustment") + "</td><td>" + format_amount(result.dynamic_adjustment, currency) + "</td></tr>",
						"<tr><td>" + __("Difference From Core") + "</td><td>" + format_amount(result.difference_from_core, currency) + "</td></tr>",
						"<tr><td>" + __("Matched Range") + "</td><td>" + format_amount(result.minimum_amount, currency) + " &le; " + __("amount") + " &lt; " + format_amount(result.maximum_amount, currency) + "</td></tr>",
						"<tr><td>" + __("Rule") + "</td><td>" + __(result.rounding_method) + " " + format_amount(result.rounding_value, currency) + "</td></tr>",
						"</table>"
					].join("")
				});
			}
		});
	}

	function add_preview_button(frm) {
		if (frappe.session.user !== PILOT_USER) {
			return;
		}

		frm.add_custom_button(__("Preview Dynamic Rounding"), function () {
			show_preview(frm);
		}, __("Tools"));
	}

	SUPPORTED_DOCTYPES.forEach(function (doctype) {
		frappe.ui.form.on(doctype, {
			refresh: function (frm) {
				install_form_rounding(frm);
				add_preview_button(frm);
				load_client_settings(frm);
			}
		});
	});
}());
