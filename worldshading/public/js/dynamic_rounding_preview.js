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

	function calculate_dynamic_total(amount, rules) {
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

		quotient = amount_units / rounding_value_units;
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

		return flt(
			(units * rounding_value_units) / scale,
			digits
		);
	}

	namespace.calculate = calculate_dynamic_total;

	function install_client_rounding() {
		var original_set_rounded_total;

		if (namespace.installed || !erpnext.taxes_and_totals) {
			return;
		}

		original_set_rounded_total = erpnext.taxes_and_totals.prototype.set_rounded_total;
		erpnext.taxes_and_totals.prototype.set_rounded_total = function () {
			var doc = this.frm.doc;
			var rounded_total;
			var rounding_disabled;

			original_set_rounded_total.apply(this, arguments);

			if (
				!namespace.settings.enabled
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
				doc.grand_total,
				namespace.settings.rules
			);
			if (rounded_total === null || (flt(doc.grand_total) && !rounded_total)) {
				return;
			}

			doc.rounded_total = rounded_total;
			doc.rounding_adjustment = flt(
				doc.rounded_total - doc.grand_total,
				precision("rounding_adjustment")
			);
			this.set_in_company_currency(doc, ["rounding_adjustment", "rounded_total"]);
			doc.base_rounding_adjustment = flt(
				doc.base_rounded_total - doc.base_grand_total,
				precision("base_rounding_adjustment")
			);
		};

		namespace.installed = true;
	}

	function load_client_settings(frm) {
		var request_generation = (namespace.request_generation || 0) + 1;
		var requested_document_name = frm.doc.name;
		namespace.request_generation = request_generation;

		frappe.call({
			method: "worldshading.api.dynamic_rounding.get_dynamic_rounding_client_settings",
			callback: function (response) {
				var settings = response.message || { enabled: false, rules: [] };
				var is_obsolete_form = typeof cur_frm !== "undefined" && cur_frm !== frm;

				if (
					request_generation !== namespace.request_generation
					|| is_obsolete_form
					|| frm.doc.name !== requested_document_name
				) {
					return;
				}

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
					frm.cscript.calculate_taxes_and_totals();
					frm.refresh_fields();
				}
			}
		});
	}

	install_client_rounding();

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
				currency: currency
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
				add_preview_button(frm);
				load_client_settings(frm);
			}
		});
	});
}());
