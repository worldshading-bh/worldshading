/* global frappe, __ */

function can_show_purchase_receipt_update_pricing(doc) {
	return Boolean(doc && Number(doc.docstatus) === 1 && !Number(doc.is_return || 0));
}

function get_purchase_receipt_pricing_route_options(doc, pricing_strategy) {
	return {
		"company": doc.company,
		"pricing_strategy": pricing_strategy,
		"purchase_receipt": doc.name
	};
}

function show_purchase_receipt_update_pricing_dialog(frm) {
	var dialog = new frappe.ui.Dialog({
		"title": __("Update Pricing"),
		"fields": [{
			"fieldname": "pricing_strategy",
			"label": __("Pricing Strategy"),
			"fieldtype": "Link",
			"options": "Pricing Strategy Template",
			"reqd": 1,
			"get_query": function () {
				return {"filters": {"company": frm.doc.company, "enabled": 1}};
			}
		}],
		"primary_action_label": __("Open Pricing Report"),
		"primary_action": function (values) {
			frappe.route_options = get_purchase_receipt_pricing_route_options(
				frm.doc, values.pricing_strategy
			);
			dialog.hide();
			frappe.set_route("query-report", "Pricing Strategy Analysis");
		}
	});
	dialog.show();
}

frappe.ui.form.on("Purchase Receipt", {
	"refresh": function (frm) {
		if (!can_show_purchase_receipt_update_pricing(frm.doc)) {
			return;
		}
		frm.add_custom_button(__("Update Pricing"), function () {
			show_purchase_receipt_update_pricing_dialog(frm);
		});
	}
});
