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

    customer: function(frm) {
        var customer = frm.doc.customer;
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
                frm.set_value("mobile_number", r.message.mobile_no);
            }
            if (!frm.doc.email_address && r.message.email_id) {
                frm.set_value("email_address", r.message.email_id);
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
                frm.set_value("mobile_number", r.message.mobile_no || r.message.phone);
            }
            if (!frm.doc.whatsapp_number && r.message.mobile_no) {
                frm.set_value("whatsapp_number", r.message.mobile_no);
            }
            if (!frm.doc.email_address && r.message.email_id) {
                frm.set_value("email_address", r.message.email_id);
            }
        });
    }
});
