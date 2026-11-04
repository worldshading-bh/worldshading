frappe.ui.form.on("Sales Target", {
    refresh: function(frm) {
        set_employee_query(frm);
        update_frequency_totals(frm);
    },

    company: function(frm) {
        set_employee_query(frm);

        if (!frm.doc.company) {
            return;
        }

        if ((frm.doc.targets || []).length) {
            frappe.msgprint(__(
                "Company changed. Please confirm that every selected employee belongs to the new company."
            ));
        }

        frappe.db.get_value(
            "Company",
            frm.doc.company,
            "default_currency",
            function(value) {
                var currency = value && value.default_currency;
                frm.set_value("currency", currency || "");
                (frm.doc.targets || []).forEach(function(row) {
                    row.currency = currency || "";
                });
                frm.refresh_field("targets");
            }
        );
    }
});

frappe.ui.form.on("Sales Target Detail", {
    daily_target: function(frm) {
        update_frequency_totals(frm);
    },

    weekly_target: function(frm) {
        update_frequency_totals(frm);
    },

    monthly_target: function(frm) {
        update_frequency_totals(frm);
    },

    quarterly_target: function(frm) {
        update_frequency_totals(frm);
    },

    annual_target: function(frm) {
        update_frequency_totals(frm);
    },

    targets_add: function(frm) {
        update_frequency_totals(frm);
    },

    targets_remove: function(frm) {
        update_frequency_totals(frm);
    }
});

function set_employee_query(frm) {
    frm.set_query("sales_employee", "targets", function() {
        return {
            filters: {
                status: "Active",
                company: frm.doc.company
            }
        };
    });
}

function update_frequency_totals(frm) {
    var frequency_fields = [
        ["daily_target", "total_daily_target"],
        ["weekly_target", "total_weekly_target"],
        ["monthly_target", "total_monthly_target"],
        ["quarterly_target", "total_quarterly_target"],
        ["annual_target", "total_annual_target"]
    ];

    frequency_fields.forEach(function(fields) {
        var total = (frm.doc.targets || []).reduce(function(value, row) {
            return value + flt(row[fields[0]] || 0);
        }, 0);
        frm.set_value(fields[1], Math.round(total * 1000) / 1000);
    });
}
