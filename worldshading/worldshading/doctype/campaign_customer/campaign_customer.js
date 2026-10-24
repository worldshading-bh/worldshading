(function() {
function clear_customer_autofill(frm) {
    var values = frm.__campaign_customer_autofill || {};
    ["mobile_number", "whatsapp_number", "email_address"].forEach(function(fieldname) {
        if (values[fieldname] && frm.doc[fieldname] === values[fieldname]) {
            frm.set_value(fieldname, "");
        }
    });
    frm.__campaign_customer_autofill = {};
}

function set_customer_autofill(frm, fieldname, value) {
    if (!value) {
        return;
    }
    frm.set_value(fieldname, value);
    frm.__campaign_customer_autofill = frm.__campaign_customer_autofill || {};
    frm.__campaign_customer_autofill[fieldname] = value;
}

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

function open_record_contact_dialog(frm) {
    var dialog;
    dialog = new frappe.ui.Dialog({
        title: __("Record Contact"),
        fields: [
            {
                fieldname: "channel",
                fieldtype: "Select",
                label: __("Channel"),
                options: "Call\nWhatsApp\nSMS\nEmail\nVisit",
                default: frm.doc.next_action && frm.doc.next_action !== "None"
                    ? frm.doc.next_action : "Call",
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
                        suggested_status(dialog.get_value("outcome"), frm.doc.status)
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
                default: frm.doc.status || "Planned",
                reqd: 1
            },
            {
                fieldname: "next_follow_up",
                fieldtype: "Datetime",
                label: __("Next Follow-up"),
                default: frm.doc.next_follow_up || ""
            },
            {
                fieldname: "next_action",
                fieldtype: "Select",
                label: __("Next Action"),
                options: "\nCall\nWhatsApp\nSMS\nEmail\nVisit\nNone",
                default: frm.doc.next_action || "Call"
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
                    name: frm.doc.name,
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
                    frm.reload_doc();
                }
            });
        }
    });
    dialog.show();
}

frappe.ui.form.on("Campaign Customer", {
    setup: function(frm) {
        frm.set_query("contact_person", function() {
            if (!frm.doc.customer) {
                return;
            }
            return {
                query: "frappe.contacts.doctype.contact.contact.contact_query",
                filters: {
                    link_doctype: "Customer",
                    link_name: frm.doc.customer
                }
            };
        });
    },

    refresh: function(frm) {
        if (!frm.is_new()) {
            frm.add_custom_button(__("Record Contact"), function() {
                open_record_contact_dialog(frm);
            });
        }
    },

    customer: function(frm) {
        var customer = frm.doc.customer;
        clear_customer_autofill(frm);
        frm.set_value("contact_person", "");

        if (!customer) {
            frm.set_value("customer_name", "");
            frm.set_value("customer_group", "");
            frm.set_value("territory", "");
            return;
        }

        frappe.db.get_value("Customer", customer, [
            "customer_name", "customer_group", "territory", "mobile_no", "email_id"
        ], function(r) {
            if (frm.doc.customer !== customer || !r.message) {
                return;
            }

            frm.set_value("customer_name", r.message.customer_name || "");
            frm.set_value("customer_group", r.message.customer_group || "");
            frm.set_value("territory", r.message.territory || "");
            if (!frm.doc.mobile_number && r.message.mobile_no) {
                set_customer_autofill(frm, "mobile_number", r.message.mobile_no);
            }
            if (!frm.doc.email_address && r.message.email_id) {
                set_customer_autofill(frm, "email_address", r.message.email_id);
            }
        });
    },

    contact_person: function(frm) {
        var contact = frm.doc.contact_person;
        if (!contact) {
            return;
        }

        frappe.db.get_value("Contact", contact, [
            "mobile_no", "phone", "email_id"
        ], function(r) {
            if (frm.doc.contact_person !== contact || !r.message) {
                return;
            }

            if (!frm.doc.mobile_number && (r.message.mobile_no || r.message.phone)) {
                set_customer_autofill(
                    frm, "mobile_number", r.message.mobile_no || r.message.phone
                );
            }
            if (!frm.doc.whatsapp_number && r.message.mobile_no) {
                set_customer_autofill(frm, "whatsapp_number", r.message.mobile_no);
            }
            if (!frm.doc.email_address && r.message.email_id) {
                set_customer_autofill(frm, "email_address", r.message.email_id);
            }
        });
    }
});
})();
