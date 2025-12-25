frappe.provide('frappe.ui.form');

frappe.ui.form.CustomerQuickEntryForm = frappe.ui.form.QuickEntryForm.extend({
    init: function (doctype, after_insert) {
        this.skip_redirect_on_error = true;
        this._super(doctype, after_insert);
    },

    render_dialog: function () {
        this.mandatory = this.mandatory.concat(this.get_variant_fields());
        this._super();
    
        let me = this;
    
        // 🔴 Force bold + red style for Mobile
        let mobile_field = me.dialog.get_field("mobile_no");
        if (mobile_field) {
            mobile_field.df.reqd = 1;
            mobile_field.refresh();
        }

        // 🔴 Force bold + red style for First Name
        let fname_field = me.dialog.get_field("first_name");
        if (fname_field) {
            fname_field.df.reqd = 1;
            fname_field.refresh();
        }

        // 🔀 Reorder fields → Series → Type → Customer Name → rest
        let series_field = this.dialog.get_field("naming_series");
        let type_field = this.dialog.get_field("customer_type");
        let name_field = this.dialog.get_field("customer_name");
    
        if (series_field && type_field) {
            $(type_field.wrapper).insertAfter(series_field.wrapper);
        }
        if (type_field && name_field) {
            $(name_field.wrapper).insertAfter(type_field.wrapper);
        }
    
        // 🏷️ Dynamic label + Hide/Show fields + Re-apply defaults
        if (type_field && name_field) {
            const update_label_and_visibility = () => {
                let type_val = type_field.get_value();

                // Update Customer Name label
                if (type_val === "Company") {
                    name_field.df.label = "Company Name";
                } else {
                    name_field.df.label = "Customer Name";
                }
                name_field.refresh();

                // List of fields to hide/show
                let fields_to_toggle = [
                    "customer_name",
                    "customer_group",
                    "territory",
                    "first_name",
                    "last_name",
                    "email_id",
                    "mobile_no",
                    "address_line1",
                    "address_line2",
                    "pincode",
                    "city",
                    "country"
                ];

                fields_to_toggle.forEach(f => {
                    let fld = me.dialog.get_field(f);
                    if (fld) {
                        fld.df.hidden = !type_val;
                        fld.refresh();

                        // Clear values when type is empty
                        if (!type_val) {
                            fld.set_value("");
                        }
                    }
                });

                // 🟢 Re-apply defaults whenever type is selected
                if (type_val) {
                    let country_field = me.dialog.get_field("country");
                    if (country_field && !country_field.get_value()) {
                        country_field.set_value("Bahrain");
                    }

                    let territory_field = me.dialog.get_field("territory");
                    if (territory_field && !territory_field.get_value()) {
                        territory_field.set_value("Bahrain");
                    }
                }
            };

            // Initial check
            update_label_and_visibility();

            // On change
            type_field.df.onchange = update_label_and_visibility;
        }
    
        // ✅ Override Save button with validation
        this.dialog.set_primary_action(__('Save'), function () {
            let values = me.dialog.get_values();

            if (!values.first_name) {
                frappe.msgprint(__('First Name is required'));
                return;
            }
            if (!values.mobile_no) {
                frappe.msgprint(__('Mobile Number is required'));
                return;
            }
    
            me.save();
        });
    },
    
    get_variant_fields: function () {
        var variant_fields = [
            {
                fieldtype: "Section Break",
                label: __("Primary Contact Details"),
                collapsible: 0
            },
            {
                label: __("First Name"),
                fieldname: "first_name",
                fieldtype: "Data",
                reqd: 1
            },
            {
                label: __("Last Name"),
                fieldname: "last_name",
                fieldtype: "Data",
                reqd: 0
            },
            {
                fieldtype: "Column Break"
            },

            {
                label: __("Mobile Number"),
                fieldname: "mobile_no",
                fieldtype: "Data",
                reqd: 1
            },
            {
                label: __("Email Id"),
                fieldname: "email_id",
                fieldtype: "Data",
                reqd: 0  
            },
            {
                fieldtype: "Section Break",
                label: __("Primary Address Details"),
                collapsible: 0
            },
            {
                label: __("Address Line 1"),
                fieldname: "address_line1",
                fieldtype: "Data",
                reqd: 1
            },
            {
                label: __("Address Line 2"),
                fieldname: "address_line2",
                fieldtype: "Data"
            },
            {
                label: __("ZIP Code"),
                fieldname: "pincode",
                fieldtype: "Data"
            },
            {
                fieldtype: "Column Break"
            },
            {
                label: __("City"),
                fieldname: "city",
                fieldtype: "Link",
                options: "City",
                reqd: 1
            },
            {
                label: __("Country"),
                fieldname: "country",
                fieldtype: "Link",
                options: "Country",
                reqd: 1
            },
            {
                label: __("Customer POS Id"),
                fieldname: "customer_pos_id",
                fieldtype: "Data",
                hidden: 1
            }
        ];

        return variant_fields;
    },
});
