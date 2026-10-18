(function () {
	"use strict";

	var method = "worldshading.api.gl_payment_urgency.set_gl_payment_urgency";

	frappe.ui.form.on("GL Payment", {
		refresh: function (frm) {
			frm.remove_custom_button(__("Mark as Urgent"), __("Urgency"));
			frm.remove_custom_button(__("Mark as Normal"), __("Urgency"));

			if (!frappe.meta.get_docfield("GL Payment", "custom_is_urgent") || frm.is_new() || frm.doc.docstatus === 2 || !can_update(frm)) {
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
		// Workflow read-only mode strips write from frm.perm. Check the document's
		// underlying permissions, including owner, user and sharing restrictions.
		var permissions = frappe.perm.get_perm(frm.doc.doctype || "GL Payment", frm.doc);
		return Boolean(permissions && permissions[0] && permissions[0].write);
	}

	function show_urgent_dialog(frm) {
		var dialog = new frappe.ui.Dialog({
			title: __("Mark GL Payment as Urgent"),
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
			__("Remove the urgent label from this GL Payment?"),
			function () {
				update_urgency(frm, 0, "");
			}
		);
	}

	function update_urgency(frm, urgent, reason, dialog) {
		frappe.call({
			method: method,
			args: {
				glp_name: frm.doc.name,
				urgent: urgent,
				reason: reason || ""
			},
			freeze: true,
			freeze_message: urgent ? __("Marking GL Payment as urgent...") :
				__("Removing urgent label..."),
			callback: function () {
				if (dialog) {
					dialog.hide();
				}
				frappe.show_alert({
					message: urgent ? __("GL Payment marked as urgent") :
						__("GL Payment marked as normal"),
					indicator: urgent ? "red" : "green"
				});
				frm.reload_doc();
			}
		});
	}
})();
