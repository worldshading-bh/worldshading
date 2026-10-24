(function() {
var active_listview;

function suggested_status(outcome, current_status) {
	var suggestions = {
		"No Answer": "Follow Up",
		"Busy": "Follow Up",
		"Call Back Later": "Follow Up",
		"Message Sent": "Follow Up",
		"Replied": "Follow Up",
		"Interested": "Interested",
		"Not Interested": "Not Interested",
		"Wrong Number": "Follow Up",
		"Visit Scheduled": "Follow Up",
		"Order Confirmed": "Converted"
	};
	return suggestions[outcome] || current_status || "Planned";
}

function open_record_contact_dialog(doc) {
	var dialog;
	dialog = new frappe.ui.Dialog({
		title: __("Record Contact"),
		fields: [
			{
				fieldname: "channel",
				fieldtype: "Select",
				label: __("Channel"),
				options: "Call\nWhatsApp\nSMS\nEmail\nVisit",
				default: doc.next_action && doc.next_action !== "None"
					? doc.next_action : "Call",
				reqd: 1
			},
			{
				fieldname: "outcome",
				fieldtype: "Select",
				label: __("Outcome"),
				options: "No Answer\nBusy\nCall Back Later\nMessage Sent\nReplied\n" +
					"Interested\nNot Interested\nWrong Number\nVisit Scheduled\n" +
					"Order Confirmed\nOther",
				reqd: 1,
				onchange: function() {
					dialog.fields_dict.status.set_value(
						suggested_status(dialog.get_value("outcome"), doc.status)
					);
				}
			},
			{
				fieldname: "notes",
				fieldtype: "Small Text",
				label: __("Notes"),
				reqd: 1
			},
			{
				fieldname: "status",
				fieldtype: "Select",
				label: __("Status"),
				options: "Planned\nFollow Up\nInterested\nNot Interested\nConverted\nClosed",
				default: doc.status || "Planned",
				reqd: 1
			},
			{
				fieldname: "next_follow_up",
				fieldtype: "Datetime",
				label: __("Next Follow-up"),
				default: doc.next_follow_up || ""
			},
			{
				fieldname: "next_action",
				fieldtype: "Select",
				label: __("Next Action"),
				options: "\nCall\nWhatsApp\nSMS\nEmail\nVisit\nNone",
				default: doc.next_action || "Call"
			}
		],
		primary_action_label: __("Save Contact"),
		primary_action: function(values) {
			if ((values.status === "Follow Up" || values.status === "Interested") &&
					!values.next_follow_up) {
				frappe.msgprint(__("Next Follow-up is required for this status."));
				return;
			}
			frappe.call({
				method: "worldshading.worldshading.doctype.campaign_customer." +
					"campaign_customer.record_contact",
				args: {
					name: doc.name,
					channel: values.channel,
					outcome: values.outcome,
					notes: values.notes,
					status: values.status,
					next_follow_up: values.next_follow_up || null,
					next_action: values.next_action || null
				},
				freeze: true,
				freeze_message: __("Saving contact..."),
				callback: function(r) {
					if (r.exc) {
						return;
					}
					dialog.hide();
					if (active_listview) {
						active_listview.refresh();
					}
				}
			});
		}
	});
	dialog.show();
}

var status_colors = {
	"Planned": "gray",
	"Follow Up": "orange",
	"Interested": "blue",
	"Not Interested": "red",
	"Converted": "green",
	"Closed": "darkgrey"
};

frappe.listview_settings["Campaign Customer"] = {
	add_fields: [
		"status", "caller", "planned_contact_date", "next_follow_up",
		"last_outcome", "latest_note", "next_action"
	],
	onload: function(listview) {
		active_listview = listview;
	},
	get_indicator: function(doc) {
		return [
			__(doc.status),
			status_colors[doc.status] || "gray",
			"status,=," + doc.status
		];
	},
	button: {
		show: function(doc) {
			return ["Converted", "Closed"].indexOf(doc.status) === -1;
		},
		get_label: function() {
			return __("Record Contact");
		},
		get_description: function(doc) {
			return __("Record contact for {0}", [doc.customer_name || doc.customer]);
		},
		action: function(doc) {
			open_record_contact_dialog(doc);
		}
	}
};
})();
