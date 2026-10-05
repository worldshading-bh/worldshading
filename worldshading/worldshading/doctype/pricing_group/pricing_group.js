/* global frappe, __ */

function get_pricing_group_strategy_query(company) {
	return {"filters": {"company": company, "enabled": 1}};
}

function should_clear_pricing_group_strategy(company, strategy_company) {
	return Boolean(company && strategy_company && company !== strategy_company);
}

function build_pricing_group_items_html(items, is_new) {
	if (is_new) {
		return '<p class="text-muted">' + __("Save this Pricing Group before assigning Items.") + '</p>';
	}
	items = items || [];
	if (!items.length) {
		return '<p class="text-muted">' + __("0 Items included. Assign this Pricing Group from the Item master.") + '</p>';
	}
	var escape = frappe.utils.escape_html;
	var rows = items.map(function (item) {
		return "<tr>" +
			"<td>" + escape(item.item_code) + "</td>" +
			"<td>" + escape(item.item_name) + "</td>" +
			"<td>" + escape(item.item_group) + "</td>" +
			"<td>" + escape(item.brand) + "</td>" +
			"<td>" + escape(item.stock_uom) + "</td>" +
			"</tr>";
	}).join("");
	return '<p><strong>' + __("{0} Items included", [items.length]) + '</strong></p>' +
		'<div class="table-responsive"><table class="table table-bordered table-condensed">' +
		'<thead><tr><th>' + __("Item Code") + '</th><th>' + __("Item Name") +
		'</th><th>' + __("Item Group") + '</th><th>' + __("Brand") +
		'</th><th>' + __("Stock UOM") +
		'</th></tr></thead><tbody>' + rows + '</tbody></table></div>';
}

function show_pricing_group_items(frm, items) {
	var field = frm.fields_dict.included_items_html;
	if (field && field.$wrapper) {
		field.$wrapper.html(build_pricing_group_items_html(items, frm.is_new()));
	}
}

function load_pricing_group_items(frm) {
	if (frm.is_new()) {
		show_pricing_group_items(frm, []);
		return;
	}
	frappe.call({
		"method": "worldshading.worldshading.doctype.pricing_group.pricing_group.get_pricing_group_items",
		"args": {"pricing_group": frm.doc.name},
		"callback": function (response) {
			show_pricing_group_items(frm, response.message || []);
		}
	});
}

function open_pricing_group_items(frm) {
	frappe.route_options = {"pricing_group": frm.doc.name};
	frappe.set_route("List", "Item");
}

frappe.ui.form.on("Pricing Group", {
	"setup": function (frm) {
		frm.set_query("pricing_strategy", function () {
			return get_pricing_group_strategy_query(frm.doc.company);
		});
	},
	"refresh": function (frm) {
		load_pricing_group_items(frm);
		if (!frm.is_new()) {
			frm.add_custom_button(__("View Items"), function () {
				open_pricing_group_items(frm);
			});
		}
	},
	"after_save": function (frm) {
		load_pricing_group_items(frm);
	},
	"company": function (frm) {
		if (!frm.doc.pricing_strategy) {
			return;
		}
		frappe.db.get_value(
			"Pricing Strategy Template", frm.doc.pricing_strategy, "company"
		).then(function (response) {
			var strategy_company = response.message && response.message.company;
			if (should_clear_pricing_group_strategy(frm.doc.company, strategy_company)) {
				frm.set_value("pricing_strategy", "");
			}
		});
	}
});
