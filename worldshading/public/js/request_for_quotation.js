frappe.ui.form.on("Request for Quotation", {
	setup: function (frm) {
		frm.fields_dict.suppliers.grid.get_field("supplier").get_query = function () {
			return {
				query: "worldshading.api.request_for_quotation.supplier_query",
				filters: {
					item_codes: (frm.doc.items || []).map(function (row) {
						return row.item_code;
					}).filter(Boolean)
				}
			};
		};
	},

	refresh: function (frm) {
		if (frm.doc.docstatus !== 0) return;

		frm.add_custom_button(__("Add Suppliers by Item Group"), function () {
			fetch_matching_suppliers(frm);
		}, __("Suppliers"));
	},

	fetch_matching_suppliers: function (frm) {
		fetch_matching_suppliers(frm);
	}
});

function fetch_matching_suppliers(frm) {
	var item_codes = (frm.doc.items || []).map(function (row) {
		return row.item_code;
	}).filter(Boolean);

	if (!item_codes.length) {
		frappe.msgprint(__("Add RFQ items before fetching suppliers."));
		return;
	}

	frappe.call({
		method: "worldshading.api.request_for_quotation.get_suppliers_for_items",
		args: { item_codes: item_codes },
		freeze: true,
		freeze_message: __("Finding suppliers by Item Group..."),
		callback: function (r) {
			var result = r.message || {};
			var suppliers = result.suppliers || [];
			var existing = {};
			var added = 0;
			var grid_rows = frm.get_field("suppliers").grid.grid_rows || [];

			// ERPNext may create an empty first row automatically. Remove only
			// blank rows so the first matched supplier starts at row 1.
			grid_rows.slice().reverse().forEach(function (grid_row) {
				if (!grid_row.doc.supplier) grid_row.remove();
			});

			(frm.doc.suppliers || []).forEach(function (row) {
				if (row.supplier) existing[row.supplier] = true;
			});

			suppliers.forEach(function (supplier) {
				if (existing[supplier.name]) return;
				var row = frm.add_child("suppliers");
				row.supplier = supplier.name;
				existing[supplier.name] = true;
				added += 1;
				frm.script_manager.trigger("supplier", row.doctype, row.name);
			});

			frm.refresh_field("suppliers");
			if (!suppliers.length) {
				frappe.msgprint(__("No eligible suppliers are configured for the RFQ Item Groups."));
			} else {
				frappe.show_alert({
					message: __("{0} supplier(s) added; {1} already present.",
						[added, suppliers.length - added]),
					indicator: added ? "green" : "blue"
				});
			}
		}
	});
}
