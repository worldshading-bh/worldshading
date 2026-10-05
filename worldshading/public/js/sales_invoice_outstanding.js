frappe.ui.form.on("Sales Invoice", {
	refresh: function (frm) {
		if (frm.doc.docstatus !== 1 || !frappe.user.has_role("System Manager")) {
			return;
		}

		frm.add_custom_button(__("Recalculate Outstanding"), function () {
			if (frm.is_dirty()) {
				frappe.msgprint(__("Please save or discard your changes before recalculating outstanding."));
				return;
			}
			frappe.call({
				method: "worldshading.api.sales_invoice_outstanding.recalculate_outstanding",
				type: "POST",
				args: { invoice_name: frm.doc.name },
				freeze: true,
				freeze_message: __("Recalculating outstanding from the ledger..."),
				callback: function (response) {
					var result = response.message;
					if (!result) {
						return;
					}
					frm.reload_doc();
					frappe.msgprint({
						title: __("Outstanding Recalculated"),
						indicator: "green",
						message: __("Outstanding: {0} → {1}", [
							format_currency(result.previous_outstanding, result.currency),
							format_currency(result.outstanding_amount, result.currency)
						])
					});
				}
			});
		}, __("Tools"));
	}
});
