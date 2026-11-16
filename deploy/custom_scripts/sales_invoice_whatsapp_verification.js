// WhatsApp verirification in invoice
frappe.ui.form.on("Sales Invoice", {

    before_workflow_action(frm) {

        // ==================================================
        // Only specific actions
        // ==================================================
        if (
            frm.selected_workflow_action !== "Complete" &&
            frm.selected_workflow_action !== "Request Cutting"
        ) {
            return;
        }
        // ==================================================
        // Skip Returns
        // ==================================================
        if (frm.doc.is_return) {
            return;
        }
        if (frm.__ws_whatsapp_pending) {
            frappe.msgprint("WhatsApp verification is already in progress.");
            return Promise.reject(new Error("WhatsApp verification already in progress"));
        }
        frm.__ws_whatsapp_pending = true;
        frappe.validated = false;

        // ==================================================
        // Proper workflow halt
        // ==================================================
        return new Promise((outer_resolve, outer_reject) => {
            // WS_WHATSAPP_WORKFLOW_FAILURE_HANDLING_V1
            let settled = false;
            let processing = false;
            let active_dialog = null;
            let wait_timer = null;

            function finish(error, cancelled) {
                if (settled) return;
                settled = true;
                if (wait_timer) clearTimeout(wait_timer);
                frm.__ws_whatsapp_pending = false;
                frappe.validated = !error && !cancelled;
                if (active_dialog) {
                    active_dialog.get_primary_btn().prop("disabled", false);
                }
                if (error || cancelled) {
                    if (!cancelled) {
                        frappe.msgprint({
                            title: "Invoice submission stopped",
                            indicator: "red",
                            message: "WhatsApp verification or invoice saving did not complete. " +
                                "The workflow has not been continued by this attempt. " +
                                "Check any error shown, reload the invoice to check its current status, and retry."
                        });
                    }
                    outer_reject(error || new Error("WhatsApp verification cancelled"));
                    if (active_dialog) active_dialog.hide();
                } else {
                    outer_resolve();
                }
            }
            function resolve() { finish(null, false); }
            function reject(error) { finish(error || new Error("WhatsApp verification failed"), false); }
            function start_wait_timer() {
                if (!wait_timer) {
                    wait_timer = setTimeout(function () {
                        reject(new Error("WhatsApp verification save timed out"));
                    }, 120000);
                }
            }


            // ==================================================
            // Suggested Mobile
            // ==================================================
            let suggested_mobile = frm.doc.contact_mobile || "";

            // ==================================================
            // Default Values
            // ==================================================
            let default_country_code = "+973 Bahrain";
            let default_phone = "";
            let has_existing_whatsapp = false;

            let contact_doc = null;


            // ==================================================
            // Apply WhatsApp to SI
            // ==================================================
            function apply_whatsapp(full_number) {
                if (settled) return Promise.reject(new Error("Verification attempt ended"));
                if (frm.doc.whatsapp_no === full_number && !frm.is_dirty()) {
                    return Promise.resolve();
                }
                start_wait_timer();
                return Promise.resolve(frm.set_value("whatsapp_no", full_number)).then(function () {
                    if (settled) throw new Error("Verification attempt ended");
                    // v12 frm.save catches some errors internally. Use its callbacks
                    // and require an actual matching saved document in the response.
                    return new Promise(function (saved, failed) {
                        frm.save("Save", function (r) {
                            const doc = r && r.docs && r.docs.find(function (d) {
                                return d.doctype === "Sales Invoice" && d.name === frm.doc.name;
                            });
                            if (r && !r.exc && doc && doc.whatsapp_no === full_number && doc.docstatus === 0) {
                                saved();
                            } else {
                                failed(new Error("Invoice save was not confirmed"));
                            }
                        }, null, function () {
                            failed(new Error("Invoice save failed"));
                        });
                    });
                });
            }

            // ==================================================
            // Open Dialog
            // ==================================================
            function open_dialog() {

                let fields = [

                    {
                        fieldtype: "HTML",
                        options: `
                            <div style="
                                margin-bottom:15px;
                                color:#666;
                            ">
                                Please verify the customer's WhatsApp number.
                            </div>
                        `
                    },

                    {
                        label: "Country Code",
                        fieldname: "country_code",
                        fieldtype: "Select",

                        options: `
+973 Bahrain
+966 Saudi Arabia
+971 United Arab Emirates
+968 Oman
+965 Kuwait
+974 Qatar
+82 South Korea
+86 China
+91 India
+66 Thailand
+81 Japan
+880 Bangladesh
+94 Sri Lanka
+92 Pakistan
+49 Germany
+33 France
+39 Italy
+44 United Kingdom
+34 Spain
+46 Sweden
+31 Netherlands
+1 United States
+1 Canada
+61 Australia
+63 Philippines
+62 Indonesia
+7 Russia
                        `,

                        default: default_country_code,
                        reqd: 1
                    },

                    {
                        label: "WhatsApp Number",
                        fieldname: "whatsapp_no",
                        fieldtype: "Data",
                        default: default_phone,
                        reqd: 1
                    }

                ];

                // ==================================================
                // Show Suggested Mobile
                // ==================================================
                if (
                    !has_existing_whatsapp &&
                    suggested_mobile &&
                    !(
                        contact_doc &&
                        contact_doc.dynamic_whatsapp
                    )
                ) {

                    fields.push({

                        fieldtype: "HTML",

                        options: `
                            <div style="
                                margin-top:-10px;
                                margin-bottom:15px;
                                font-size:12px;
                                color:#777;
                            ">
                                Contact Mobile:
                                <b>${suggested_mobile}</b>
                            </div>
                        `
                    });

                }

                const dialog = new frappe.ui.Dialog({

                    title: "Verify WhatsApp Number",

                    fields: fields,

                    primary_action_label: "Confirm",

                    primary_action(values) {
                        if (processing || settled) return;
                        try {

                        if (!values.whatsapp_no) {

                            frappe.msgprint(
                                "WhatsApp number is required"
                            );

                            return;
                        }

                        // ==================================================
                        // Normalize Country Code
                        // ==================================================
                        let cc = String(values.country_code || "").match(/\+\d+/);

                        cc = cc ? cc[0].replace("+", "") : "973";

                        // ==================================================
                        // Normalize Phone
                        // ==================================================
                        let phone = String(values.whatsapp_no || "").replace(/\D/g, "");

                        // Remove leading zero
                        if (phone.startsWith("0")) {
                            phone = phone.slice(1);
                        }

                        // ==================================================
                        // Smart Full Number Logic
                        // Avoid duplicate country code
                        // ==================================================
                        let full_number = "";

                        if (phone.startsWith(cc)) {

                            full_number = phone;

                        } else {

                            full_number = cc + phone;

                        }

                        if (!phone || !cc) {
                            frappe.msgprint("Please enter a valid WhatsApp number and country code.");
                            return;
                        }
                        processing = true;
                        dialog.get_primary_btn().prop("disabled", true);
                        start_wait_timer();

                        // ==================================================
                        // No Contact Person
                        // ==================================================
                        if (!frm.doc.contact_person) {

                            apply_whatsapp(full_number)
                                .then(() => {

                                    resolve();

                                    dialog.hide();

                                }).catch(reject);

                            return;
                        }

                        // ==================================================
                        // Dynamic WhatsApp Contact
                        // ==================================================
                        if (
                            contact_doc &&
                            contact_doc.dynamic_whatsapp
                        ) {

                            apply_whatsapp(full_number)
                                .then(() => {

                                    frappe.show_alert({
                                        message: "WhatsApp updated for this invoice",
                                        indicator: "orange"
                                    });

                                    resolve();

                                    dialog.hide();

                                }).catch(reject);

                            return;
                        }

                        // ==================================================
                        // Existing WhatsApp Already Same
                        // Skip unnecessary Contact update
                        // ==================================================
                        if (
                            contact_doc &&
                            !contact_doc.dynamic_whatsapp
                        ) {

                            let existing_row = null;

                            (contact_doc.phone_nos || []).forEach(row => {

                                if (row.is_whatsapp) {
                                    existing_row = row;
                                }

                            });

                            if (
                                existing_row &&
                                existing_row.country_code === values.country_code &&
                                existing_row.phone === phone
                            ) {

                                apply_whatsapp(full_number)
                                    .then(() => {

                                        resolve();

                                        dialog.hide();

                                    }).catch(reject);

                                return;
                            }

                        }

                        // ==================================================
                        // Update Contact WhatsApp
                        // ==================================================
                        Promise.resolve(frappe.call({

                            method: "worldshading.api.contact.update_contact_whatsapp",

                            args: {
                                contact: frm.doc.contact_person,
                                country_code: values.country_code,
                                whatsapp_no: phone
                            },

                            freeze: true,
                            freeze_message: "Updating WhatsApp Number..."

                        })).then(r => {

                            if (!r.message || r.message.status !== "success") {

                                reject(new Error("Contact update was not confirmed"));

                                return;
                            }

                            apply_whatsapp(r.message.whatsapp_no)
                                .then(() => {

                                    frappe.show_alert({
                                        message: "WhatsApp updated successfully",
                                        indicator: "green"
                                    });

                                    resolve();

                                    dialog.hide();

                                }).catch(reject);

                        }).catch(reject);
                        } catch (error) {
                            reject(error);
                        }
                    }

                });

                active_dialog = dialog;
                dialog.onhide = function () {
                    if (!settled) finish(null, true);
                };
                dialog.show();

            }

            // ==================================================
            // No Contact Person
            // ==================================================
            if (!frm.doc.contact_person) {

                open_dialog();

                return;
            }

            // ==================================================
            // Load Contact
            // ==================================================
            frappe.db.get_doc("Contact", frm.doc.contact_person)

                .then(contact => {

                    contact_doc = contact;

                    let whatsapp_row = null;

                    (contact.phone_nos || []).forEach(row => {

                        if (row.is_whatsapp) {
                            whatsapp_row = row;
                        }

                    });

                    // ==================================================
                    // Locked WhatsApp
                    // No editing allowed
                    // ==================================================
                    if (
                        contact.is_whatsapp_locked &&
                        whatsapp_row
                    ) {

                        let locked_number = (
                            (whatsapp_row.country_code || "")
                                .replace(/\D/g, "") +
                            (whatsapp_row.phone || "")
                                .replace(/\D/g, "")
                        );

                        // ==================================================
                        // SI already has correct number
                        // ==================================================
                        if (frm.doc.whatsapp_no === locked_number) {

                            frappe.confirm(

                                `This invoice will be sent to the WhatsApp number:<br><br><b>${locked_number}</b>`,

                                function () {

                                    resolve();

                                },

                                function () {

                                    finish(null, true);

                                }

                            );

                            return;
                        }

                        // ==================================================
                        // Force update SI WhatsApp
                        // ==================================================
                        apply_whatsapp(locked_number)

                            .then(() => {
                                if (settled) return;
                                if (wait_timer) clearTimeout(wait_timer);
                                wait_timer = null;

                                frappe.confirm(

                                    `This invoice will be sent to the WhatsApp number:<br><br><b>${locked_number}</b>`,

                                    function () {

                                            resolve();

                                    },

                                    function () {

                                        finish(null, true);

                                    }

                                );

                            }).catch(reject);

                        return;
                    }

                    // ==================================================
                    // Existing WhatsApp Found
                    // Prefill popup for verification
                    // ==================================================
                    if (
                        whatsapp_row &&
                        !contact.dynamic_whatsapp
                    ) {

                        has_existing_whatsapp = true;

                        default_country_code =
                            whatsapp_row.country_code || "+973 Bahrain";

                        default_phone =
                            whatsapp_row.phone || "";

                    }

                    // ==================================================
                    // Dynamic WhatsApp OR No WhatsApp
                    // ==================================================
                    open_dialog();

                })

                .catch(reject);

        });

    }

});
