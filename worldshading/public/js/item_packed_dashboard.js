/* global frappe, __ */

;(function () {
	"use strict";

	var transaction_types = [
		"Quotation", "Sales Order", "Delivery Note", "Sales Invoice"
	];

	function get_packed_group(frm) {
		return frm.dashboard.transactions_area
			.find(".form-documents .col-xs-6")
			.filter(function () {
				return $(this).find("h6").first().text().trim() ===
					__("Sell - Packed Items");
			})
			.first();
	}

	function configure_packed_links(frm) {
		try {
			var group = get_packed_group(frm);
			if (!group.length) {
				return;
			}

			group.find(".document-link").each(function () {
				var row = $(this);
				var transaction_type = row.attr("data-doctype");
				if (transaction_types.indexOf(transaction_type) === -1) {
					return;
				}

				row.find(".count").empty().addClass("hidden");
				row.find(".open-notification").empty().addClass("hidden");
				row.find(".btn-new").remove();
				row.find(".badge-link").off("click").on("click", function (event) {
					event.preventDefault();
					event.stopImmediatePropagation();
					var route_options = {};
					route_options["Packed Item.item_code"] = frm.doc.name;
					route_options["Packed Item.parenttype"] = transaction_type;
					frappe.set_route("List", transaction_type, "List", route_options);
				});
			});

			frappe.call({
				method: "worldshading.api.item_packed_dashboard." +
					"get_packed_transaction_counts",
				args: {item_code: frm.doc.name},
				callback: function (response) {
					var counts = response.message || {};
					transaction_types.forEach(function (transaction_type) {
						var count = counts[transaction_type] || 0;
						var row = group.find(
							".document-link[data-doctype='" + transaction_type + "']"
						);
						var badge = row.find(".count");
						badge.empty().addClass("hidden");
						if (count) {
							badge.removeClass("hidden").text(count > 99 ? "99+" : count);
						}
					});
				},
				error: function () {
					// The enhancement must not affect Item form availability.
				}
			});
		} catch (error) {
			console.warn("Packed item dashboard could not be initialized.", error);
		}
	}

	frappe.ui.form.on("Item", {
		dashboard_update: configure_packed_links
	});
}());
