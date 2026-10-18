(function () {
	"use strict";

	var method = "worldshading.api.journal_entry_urgency.set_journal_entry_urgency";

	frappe.ui.form.on("Journal Entry", {
		refresh: function (frm) {
			frm.remove_custom_button(__("Mark as Urgent"), __("Urgency"));
			frm.remove_custom_button(__("Mark as Normal"), __("Urgency"));

			if (!frappe.meta.get_docfield("Journal Entry", "custom_is_urgent") || frm.is_new() || frm.doc.docstatus === 2 || !can_update(frm)) {
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
		var permissions = frappe.perm.get_perm(frm.doc.doctype || "Journal Entry", frm.doc);
		return Boolean(permissions && permissions[0] && permissions[0].write);
	}

	function show_urgent_dialog(frm) {
		var dialog = new frappe.ui.Dialog({
			title: __("Mark Journal Entry as Urgent"),
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
			__("Remove the urgent label from this Journal Entry?"),
			function () {
				update_urgency(frm, 0, "");
			}
		);
	}

	function update_urgency(frm, urgent, reason, dialog) {
		frappe.call({
			method: method,
			args: {
				je_name: frm.doc.name,
				urgent: urgent,
				reason: reason || ""
			},
			freeze: true,
			freeze_message: urgent ? __("Marking Journal Entry as urgent...") :
				__("Removing urgent label..."),
			callback: function () {
				if (dialog) {
					dialog.hide();
				}
				frappe.show_alert({
					message: urgent ? __("Journal Entry marked as urgent") :
						__("Journal Entry marked as normal"),
					indicator: urgent ? "red" : "green"
				});
				frm.reload_doc();
			}
		});
	}
})();
