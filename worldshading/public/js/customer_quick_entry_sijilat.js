frappe.provide("frappe.ui.form");

(function () {
    var ExistingCustomerQuickEntryForm = frappe.ui.form.CustomerQuickEntryForm;

    if (!ExistingCustomerQuickEntryForm) {
        return;
    }

    frappe.ui.form.CustomerQuickEntryForm = ExistingCustomerQuickEntryForm.extend({
        init: function (doctype, after_insert, init_callback, doc) {
            this._sijilat_state = null;
            this._super(doctype, after_insert, init_callback, doc);
        },

        get_variant_fields: function () {
            var variant_fields = this._super();

            variant_fields.unshift({
                label: __("VAT Number"),
                fieldname: "tax_id",
                fieldtype: "Data"
            });

            return variant_fields;
        },

        render_dialog: function () {
            // tax_id is supplied by get_variant_fields(), like the other
            // reliable Quick Entry fields. Remove its metadata copy first.
            this.mandatory = (this.mandatory || []).filter(function (field) {
                return !field || field.fieldname !== "tax_id";
            });
            this._super();

            this._apply_compact_field_visibility();
            this._set_cr_number_description();
            this._install_sijilat_controls();
            this._install_sijilat_invalidation();
            this._register_verified_save_action();
            this._refresh_sijilat_controls();
        },

        render_edit_in_full_page_link: function () {
            // This controlled Quick Entry must remain in the verification flow.
        },

        _apply_compact_field_visibility: function () {
            ["customer_category"].forEach(function (fieldname) {
                var field = this.dialog.get_field(fieldname);
                if (!field) {
                    return;
                }

                field.df.hidden = 1;
                field.refresh();
            }, this);
        },

        _set_cr_number_description: function () {
            var cr_field = this.dialog.get_field("cr_no");
            if (!cr_field) {
                return;
            }

            cr_field.df.description = __(
                "Example: 1234-1 (CR number-branch number)"
            );
            cr_field.refresh();
        },

        _details_are_unlocked: function () {
            var customer_type = this.dialog.get_value("customer_type");
            var territory = this.dialog.get_value("territory");

            if (!customer_type) {
                return false;
            }
            if (customer_type !== "Company") {
                return true;
            }
            if (!territory) {
                return false;
            }
            if (territory !== "Bahrain") {
                return true;
            }

            return Boolean(
                this._sijilat_state &&
                this._sijilat_state.fingerprint ===
                    this._verification_fingerprint()
            );
        },

        _refresh_detail_fields: function () {
            var show_details = this._details_are_unlocked();
            var detail_fields = [
                "customer_group",
                "tax_id",
                "first_name",
                "last_name",
                "email_id",
                "mobile_no",
                "whatsapp_no",
                "address_line1",
                "address_line2",
                "pincode",
                "city",
                "country"
            ];

            detail_fields.forEach(function (fieldname) {
                var field = this.dialog.get_field(fieldname);
                if (!field) {
                    return;
                }

                if (fieldname === "tax_id") {
                    field.df.depends_on = null;
                    field.df.hidden_due_to_dependency = 0;
                }
                field.toggle(show_details);
            }, this);

            (this.dialog.fields || []).forEach(function (field) {
                if (
                    field &&
                    field.df &&
                    field.df.fieldtype === "Section Break" &&
                    (
                        field.df.label === __("Primary Contact Details") ||
                        field.df.label === __("Primary Address Details")
                    )
                ) {
                    $(field.wrapper).toggle(show_details);
                }
            });
        },

        _requires_sijilat_verification: function () {
            return (
                this.dialog.get_value("customer_type") === "Company" &&
                this.dialog.get_value("territory") === "Bahrain"
            );
        },

        _verification_fingerprint: function () {
            var name = (this.dialog.get_value("customer_name") || "")
                .trim()
                .replace(/\s+/g, " ");
            var cr_no = (this.dialog.get_value("cr_no") || "")
                .trim()
                .replace(/\s*-\s*/g, "-");

            return [
                this.dialog.get_value("customer_type") || "",
                this.dialog.get_value("territory") || "",
                name,
                cr_no
            ].join("|");
        },

        _install_sijilat_controls: function () {
            var me = this;
            var cr_field = this.dialog.get_field("cr_no");
            var territory_field = this.dialog.get_field("territory");

            if (!cr_field || this._sijilat_wrapper) {
                return;
            }

            this._sijilat_wrapper = $(
                '<div class="ws-sijilat-quick-entry" style="margin:8px 0 14px;">' +
                    '<button type="button" class="btn btn-default btn-sm ws-sijilat-check">' +
                        __("Verify CR") +
                    '</button>' +
                    '<div class="ws-sijilat-status" style="margin-top:8px;"></div>' +
                '</div>'
            );
            this._sijilat_wrapper.insertAfter(
                territory_field ? territory_field.wrapper : cr_field.wrapper
            );
            this._sijilat_wrapper.find(".ws-sijilat-check").on("click", function () {
                me._check_sijilat();
            });
        },

        _install_sijilat_invalidation: function () {
            var me = this;

            ["customer_type", "territory", "customer_name", "cr_no"].forEach(
                function (fieldname) {
                    var field = me.dialog.get_field(fieldname);
                    if (!field || field._ws_sijilat_onchange_installed) {
                        return;
                    }

                    var original_onchange = field.df.onchange;
                    field.df.onchange = function () {
                        if (original_onchange) {
                            original_onchange.apply(this, arguments);
                        }
                        me._sijilat_state = null;
                        me._set_sijilat_status("");
                        me._refresh_sijilat_controls();
                    };
                    field._ws_sijilat_onchange_installed = true;
                }
            );
        },

        _refresh_sijilat_controls: function () {
            if (!this._sijilat_wrapper) {
                return;
            }
            var verification_required = this._requires_sijilat_verification();
            var verification_complete = Boolean(
                this._sijilat_state &&
                this._sijilat_state.fingerprint ===
                    this._verification_fingerprint()
            );

            this._sijilat_wrapper.toggle(verification_required);
            this._sijilat_wrapper.find(".ws-sijilat-check").toggle(
                verification_required && !verification_complete
            );
            this._refresh_detail_fields();
        },

        _set_sijilat_status: function (message, indicator) {
            if (!this._sijilat_wrapper) {
                return;
            }

            var colors = {
                green: "#16865c",
                orange: "#b45309",
                red: "#c92a2a",
                blue: "#2470dc"
            };
            var status = this._sijilat_wrapper.find(".ws-sijilat-status");

            if (!message) {
                status.empty();
                return;
            }

            status.html(
                '<div style="padding:8px 10px;border-radius:4px;background:#f7f7f7;' +
                'color:' + (colors[indicator] || "#4c5a67") + ';font-weight:600;">' +
                frappe.utils.escape_html(message) +
                '</div>'
            );
        },

        _get_required_values: function () {
            var values = this.dialog.get_values();

            if (!values) {
                return null;
            }
            if (!values.first_name) {
                frappe.msgprint(__("First Name is required"));
                return null;
            }
            if (!values.mobile_no) {
                frappe.msgprint(__("Mobile Number is required"));
                return null;
            }
            if (values.customer_type === "Company" && !values.cr_no) {
                frappe.msgprint(__("CR No is required for Company"));
                return null;
            }

            return values;
        },

        _get_sijilat_input_values: function () {
            var values = {
                customer_type: this.dialog.get_value("customer_type"),
                customer_name: this.dialog.get_value("customer_name"),
                cr_no: this.dialog.get_value("cr_no"),
                territory: this.dialog.get_value("territory")
            };

            if (!values.customer_type) {
                frappe.msgprint(__("Customer Type is required"));
                return null;
            }
            if (!values.customer_name) {
                frappe.msgprint(__("Company Name is required"));
                return null;
            }
            if (!values.cr_no) {
                frappe.msgprint(__("CR No is required for Company"));
                return null;
            }
            if (!values.territory) {
                frappe.msgprint(__("Territory is required"));
                return null;
            }

            return values;
        },

        _check_sijilat: function () {
            var me = this;
            var values = this._get_sijilat_input_values();

            if (!values || !this._requires_sijilat_verification()) {
                return;
            }

            var normalized_cr = (values.cr_no || "")
                .trim()
                .replace(/\s*-\s*/g, "-");
            if (!/^[0-9]{4,6}-[0-9]{1,3}$/.test(normalized_cr)) {
                this._sijilat_state = null;
                this._set_sijilat_status(
                    __("Use CR format 12345-1, including the branch number."),
                    "red"
                );
                return;
            }

            this.dialog.set_value("cr_no", normalized_cr);
            this._set_sijilat_status(__("Checking CR..."), "blue");

            frappe.call({
                method: "worldshading.api.sijilat_quick_entry.preview_customer_cr",
                args: {
                    customer_name: values.customer_name,
                    cr_no: normalized_cr,
                    customer_type: values.customer_type,
                    territory: values.territory
                },
                freeze: true,
                freeze_message: __("Verifying CR..."),
                callback: function (response) {
                    if (response.message) {
                        me._handle_sijilat_result(response.message);
                    }
                }
            });
        },

        _handle_sijilat_result: function (result) {
            if (result.outcome === "verified") {
                this._show_verified_preview(result);
                return;
            }
            if (result.outcome === "temporary_error") {
                this._show_temporary_error(result);
                return;
            }

            this._sijilat_state = null;
            this._set_sijilat_status(result.message || __("CR verification failed"), "red");

            if (result.outcome === "duplicate" && result.existing_customer) {
                frappe.msgprint({
                    title: __("Customer Already Exists"),
                    indicator: "red",
                    message: __("This CR belongs to {0} ({1}).", [
                        frappe.utils.escape_html(result.existing_customer_name || ""),
                        frappe.utils.escape_html(result.existing_customer)
                    ])
                });
            } else {
                frappe.msgprint({
                    title: __("CR Verification Failed"),
                    indicator: "red",
                    message: frappe.utils.escape_html(result.message || "")
                });
            }
        },

        _show_verified_preview: function (result) {
            var me = this;
            var details = frappe.utils.escape_html(result.details || "")
                .replace(/\n/g, "<br>");
            var html = [
                '<div class="alert alert-success">',
                '<strong>', __("Active CR verified"), '</strong></div>',
                '<table class="table table-bordered">',
                '<tr><td style="width:35%;font-weight:600;">', __("Official Name"),
                '</td><td>', frappe.utils.escape_html(result.official_customer_name || ""), '</td></tr>',
                '<tr><td style="font-weight:600;">', __("Name Match"),
                '</td><td>', Number(result.name_similarity_score || 0).toFixed(2), '%</td></tr>',
                '<tr><td style="font-weight:600;">', __("CR Expiry"),
                '</td><td>', frappe.utils.escape_html(result.expiry_date || ""), '</td></tr>',
                '</table>',
                '<div style="max-height:240px;overflow:auto;padding:10px;border:1px solid #d1d8dd;">',
                details, '</div>'
            ].join("");
            var dialog = new frappe.ui.Dialog({
                title: __("CR Verification"),
                size: "large",
                fields: [{fieldtype: "HTML", options: html}]
            });

            dialog.set_primary_action(__("Use Verified Details"), function () {
                dialog.get_primary_btn().prop("disabled", true);

                frappe.run_serially([
                    function () {
                        return me.dialog.set_value(
                            "customer_name",
                            result.official_customer_name
                        );
                    },
                    function () {
                        return me.dialog.set_value("cr_no", result.normalized_cr);
                    },
                    function () {
                        me._sijilat_state = {
                            outcome: "verified",
                            token: result.verification_token,
                            fingerprint: me._verification_fingerprint()
                        };
                        me._refresh_sijilat_controls();
                        me._set_sijilat_status(
                            __("CR verified successfully. Complete the remaining details."),
                            "green"
                        );
                        dialog.hide();
                    }
                ]);
            });
            dialog.show();
        },

        _show_temporary_error: function (result) {
            var me = this;

            frappe.confirm(
                frappe.utils.escape_html(result.message || ""),
                function () {
                    me._sijilat_state = {
                        outcome: "temporary_bypass",
                        fingerprint: me._verification_fingerprint()
                    };
                    me._refresh_sijilat_controls();
                    me._set_sijilat_status(
                        __("Proceeding without verification because the verification service is unavailable."),
                        "orange"
                    );
                },
                function () {
                    me._sijilat_state = null;
                    me._set_sijilat_status(__("CR verification is still required."), "red");
                }
            );
        },

        _register_verified_save_action: function () {
            var me = this;

            this.dialog.set_primary_action(__("Save"), function () {
                if (me.dialog.working) {
                    return;
                }

                var values = me._get_required_values();
                if (!values) {
                    return;
                }

                if (me._requires_sijilat_verification()) {
                    if (
                        !me._sijilat_state ||
                        me._sijilat_state.fingerprint !== me._verification_fingerprint()
                    ) {
                        frappe.msgprint({
                            title: __("CR Verification Required"),
                            indicator: "orange",
                            message: __("Verify this Company CR before saving the Customer.")
                        });
                        return;
                    }

                    me.dialog.doc.business_verification_status = "Pending";
                }

                me.dialog.working = true;
                me.dialog.set_message(__("Saving..."));
                me.insert().then(function () {
                    me.dialog.clear_message();
                });
            });
        },

        insert: function () {
            var me = this;
            var verification_token = (
                this._sijilat_state && this._sijilat_state.outcome === "verified"
            ) ? this._sijilat_state.token : null;
            var insertion = this._super();

            if (!verification_token) {
                return insertion;
            }

            return insertion.then(function (doc) {
                if (!doc || !doc.name || doc.__islocal) {
                    return doc;
                }

                return frappe.call({
                    method: "worldshading.api.sijilat_quick_entry.finalize_customer_cr",
                    args: {
                        customer: doc.name,
                        verification_token: verification_token
                    }
                }).then(function (response) {
                    if (response.message) {
                        frappe.show_alert({
                            indicator: "green",
                            message: __("Customer created and CR verified")
                        }, 7);
                    }
                    return doc;
                });
            });
        }
    });
})();
