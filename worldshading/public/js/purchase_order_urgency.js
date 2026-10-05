(function () {
	"use strict";

	var method = "worldshading.api.purchase_order_urgency.set_purchase_order_urgency";

	frappe.ui.form.on("Purchase Order", {
		refresh: function (frm) {
			frm.remove_custom_button(__("Mark as Urgent"), __("Urgency"));
			frm.remove_custom_button(__("Mark as Normal"), __("Urgency"));

			if (frm.is_new() || frm.doc.docstatus === 2 || !can_update(frm)) {
				return;
			}

			if (Number(frm.doc.custom_is_urgent)) {
				frm.add_custom_button(__("Mark as Normal"), function () {
					mark_as_normal(frm);
				}, __("Urgency"));
			} else {
				frm.add_custom_button(__("Mark as Urgent"), function () {
					show_urgent_dialog(frm);
				}, __("Urgency"));
			}
		}
	});

	function can_update(frm) {
		var has_write_permission = Boolean(frm.perm && frm.perm[0] && frm.perm[0].write);
		var workflow_is_read_only = frappe.workflow && frappe.workflow.is_read_only &&
			frappe.workflow.is_read_only(frm.doc.doctype || "Purchase Order", frm.doc.name);

		return has_write_permission && !workflow_is_read_only;
	}

	function show_urgent_dialog(frm) {
		var dialog = new frappe.ui.Dialog({
			title: __("Mark Purchase Order as Urgent"),
			fields: [{
				fieldname: "reason",
				fieldtype: "Small Text",
				label: __("Urgency Reason"),
				reqd: 1
			}],
			primary_action_label: __("Mark as Urgent"),
			primary_action: function (values) {
				update_urgency(frm, 1, values.reason, dialog);
			}
		});

		dialog.show();
	}

	function mark_as_normal(frm) {
		frappe.confirm(
			__("Remove the urgent label from this Purchase Order?"),
			function () {
				update_urgency(frm, 0, "");
			}
		);
	}

	function update_urgency(frm, urgent, reason, dialog) {
		frappe.call({
			method: method,
			args: {
				po_name: frm.doc.name,
				urgent: urgent,
				reason: reason || ""
			},
			freeze: true,
			freeze_message: urgent ? __("Marking Purchase Order as urgent...") :
				__("Removing urgent label..."),
			callback: function () {
				if (dialog) {
					dialog.hide();
				}
				frappe.show_alert({
					message: urgent ? __("Purchase Order marked as urgent") :
						__("Purchase Order marked as normal"),
					indicator: urgent ? "red" : "green"
				});
				frm.reload_doc();
			}
		});
	}
})();
