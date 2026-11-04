frappe.ui.form.on("Sales Target", {
    refresh: function(frm) {
        set_employee_query(frm);
        update_target_total(frm);
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
    },

    period_type: function(frm) {
        set_period_defaults(frm);
    }
});

frappe.ui.form.on("Sales Target Detail", {
    target_amount: function(frm) {
        update_target_total(frm);
    },

    targets_add: function(frm) {
        update_target_total(frm);
    },

    targets_remove: function(frm) {
        update_target_total(frm);
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

function update_target_total(frm) {
    var total = (frm.doc.targets || []).reduce(function(value, row) {
        return value + flt(row.target_amount || 0);
    }, 0);

    frm.set_value("total_target_amount", Math.round(total * 1000) / 1000);
}

function set_period_defaults(frm) {
    var period_type = frm.doc.period_type;
    if (!period_type || period_type === "Custom") {
        return;
    }

    var today = frappe.datetime.get_today();
    var from_date;
    var to_date;

    if (period_type === "Daily") {
        from_date = today;
        to_date = today;
    } else if (period_type === "Weekly") {
        from_date = today;
        to_date = frappe.datetime.add_days(today, 6);
    } else if (period_type === "Monthly") {
        from_date = frappe.datetime.month_start();
        to_date = frappe.datetime.month_end();
    } else if (period_type === "Quarterly") {
        var year = parseInt(today.slice(0, 4), 10);
        var month = parseInt(today.slice(5, 7), 10);
        var start_month = Math.floor((month - 1) / 3) * 3 + 1;
        var end_month = start_month + 2;
        from_date = year + "-" + pad_date_part(start_month) + "-01";
        to_date = year + "-" + pad_date_part(end_month) + "-" +
            pad_date_part(new Date(Date.UTC(year, end_month, 0)).getUTCDate());
    } else if (period_type === "Annual") {
        var current_year = today.slice(0, 4);
        from_date = current_year + "-01-01";
        to_date = current_year + "-12-31";
    }

    if (!frm.doc.from_date && from_date) {
        frm.set_value("from_date", from_date);
    }
    if (!frm.doc.to_date && to_date) {
        frm.set_value("to_date", to_date);
    }
}

function pad_date_part(value) {
    return value < 10 ? "0" + value : String(value);
}
