frappe.query_reports["Sales Target Performance"] = {
    filters: [
        {
            fieldname: "sales_target",
            label: __("Sales Target"),
            fieldtype: "Link",
            options: "Sales Target",
            reqd: 1,
            get_query: function() {
                return {
                    filters: {
                        docstatus: 1
                    }
                };
            }
        },
        {
            fieldname: "sales_employee",
            label: __("Sales Employee"),
            fieldtype: "Link",
            options: "Employee"
        },
        {
            fieldname: "as_of_date",
            label: __("As of Date"),
            fieldtype: "Date",
            default: frappe.datetime.get_today()
        }
    ],

    onload: function(report) {
        report.$report.off("click.sales_target_performance");
        report.$report.on(
            "click.sales_target_performance",
            ".sales-target-invoice-link",
            function(event) {
                event.preventDefault();
                var link = $(this);
                open_sales_target_invoices({
                    company: decodeURIComponent(link.attr("data-company")),
                    sales_employee: decodeURIComponent(link.attr("data-employee")),
                    from_date: decodeURIComponent(link.attr("data-from-date")),
                    effective_to_date: decodeURIComponent(link.attr("data-to-date"))
                });
            }
        );
    },

    formatter: function(value, row, column, data, default_formatter) {
        value = default_formatter(value, row, column, data);

        if (!data) {
            return value;
        }

        if (column.fieldname === "status") {
            var indicators = {
                "Not Started": "grey",
                "Behind": "orange",
                "On Track": "blue",
                "Achieved": "green",
                "Not Achieved": "red"
            };
            var indicator = indicators[data.status] || "grey";
            return '<span class="indicator-pill ' + indicator + '">' + value + '</span>';
        }

        if (column.fieldname === "invoice_count" && data.invoice_count > 0) {
            return '<a href="#" class="sales-target-invoice-link"' +
                ' data-company="' + safe_route_attribute(data.company) + '"' +
                ' data-employee="' + safe_route_attribute(data.sales_employee) + '"' +
                ' data-from-date="' + safe_route_attribute(data.from_date) + '"' +
                ' data-to-date="' + safe_route_attribute(data.effective_to_date) + '">' +
                value + '</a>';
        }

        return value;
    }
};

function safe_route_attribute(value) {
    return encodeURIComponent(String(value || ""));
}

function open_sales_target_invoices(data) {
    frappe.set_route("List", "Sales Invoice", {
        company: data.company,
        pb_sales_employee: data.sales_employee,
        posting_date: ["between", [data.from_date, data.effective_to_date]],
        docstatus: 1
    });
}
