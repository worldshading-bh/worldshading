/* global frappe */

frappe.query_reports["Stock Cancellation Impact Report"] = {
	"filters": [
		{
			"fieldname": "cancelled_from",
			"label": __("Cancelled From"),
			"fieldtype": "Date",
			"description": __("The selected cancellation period must be less than 3 years."),
			"default": frappe.datetime.add_days(frappe.datetime.get_today(), -30),
			"reqd": 1
		},
		{
			"fieldname": "cancelled_to",
			"label": __("Cancelled To"),
			"fieldtype": "Date",
			"default": frappe.datetime.get_today(),
			"reqd": 1
		},
		{
			"fieldname": "company",
			"label": __("Company"),
			"fieldtype": "Link",
			"options": "Company",
			"default": frappe.defaults.get_user_default("Company")
		},
		{
			"fieldname": "voucher_type",
			"label": __("Document Type"),
			"fieldtype": "Select",
			"options": "\nDelivery Note\nStock Entry\nSales Invoice\nPurchase Receipt\nPurchase Invoice"
		},
		{
			"fieldname": "voucher_no",
			"label": __("Document Number"),
			"fieldtype": "Data"
		},
		{
			"fieldname": "item_code",
			"label": __("Item"),
			"fieldtype": "Link",
			"options": "Item"
		},
		{
			"fieldname": "warehouse",
			"label": __("Warehouse"),
			"fieldtype": "Link",
			"options": "Warehouse"
		},
		{
			"fieldname": "only_crossed_reconciliation",
			"label": __("Only Reconciliation Warnings"),
			"fieldtype": "Check",
			"default": 1
		}
	],
	"formatter": function(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (data && data.is_total_row) {
			return "<strong>" + value + "</strong>";
		}
		if (column.fieldname === "risk_status" && data) {
			if (data.risk_status === "ACTION REQUIRED") {
				var action_tooltip = __("This cancellation crossed a later Stock Reconciliation. Physically count this item in the listed warehouse. If the physical quantity differs from ERPNext, create a current-date Stock Reconciliation with manager approval.");
				value = "<span class='indicator red' style='cursor: help; border-bottom: 1px dotted #d9534f;' title='" +
					$("<div>").text(action_tooltip).html() + "'>" + value + " ⓘ</span>";
			} else {
				var safe_tooltip = __("No later submitted Stock Reconciliation was found between the original posting and cancellation times.");
				value = "<span class='indicator green' style='cursor: help;' title='" +
					$("<div>").text(safe_tooltip).html() + "'>" + value + " ⓘ</span>";
			}
		}
		return value;
	}
};
