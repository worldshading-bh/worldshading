var sales_target_performance_report = null;

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
                        docstatus: 1,
                        target_model: "Recurring Plan"
                    }
                };
            }
        },
        {
            fieldname: "frequency",
            label: __("Frequency"),
            fieldtype: "Select",
            options: "\nDaily\nWeekly\nMonthly\nQuarterly\nAnnual"
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
        sales_target_performance_report = report;
        if (!report.$sales_target_team_summary) {
            report.$sales_target_team_summary = $(
                '<div class="sales-target-team-summary" ' +
                    'style="display:grid; ' +
                    'grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); ' +
                    'gap:10px; padding:12px 14px; margin:0; ' +
                    'border-top:1px solid #d1d8dd; ' +
                    'border-bottom:1px solid #d1d8dd; ' +
                    'background:#f8fafc;"></div>'
            ).insertBefore(report.$report);
        }
        clear_team_summary(report);

        if (!report.sales_target_summary_refresh_wrapped) {
            var original_refresh = report.refresh;
            report.refresh = function() {
                clear_team_summary(report);
                return original_refresh.apply(report, arguments);
            };
            report.sales_target_summary_refresh_wrapped = true;
        }

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

    after_datatable_render: function() {
        render_team_summary(sales_target_performance_report);
    },

    formatter: function(value, row, column, data, default_formatter) {
        var raw_value = value;
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
            return '<span class="indicator ' + indicator + '">' + value + '</span>';
        }

        if (column.fieldname === "achievement_percent") {
            var achievement_indicator = Number(raw_value) >= 100 ? "green" : "red";
            var achievement_value = frappe.format(raw_value, {
                fieldtype: "Percent"
            }, {
                only_value: true
            });
            return '<div style="text-align: right;">' +
                '<span class="indicator ' + achievement_indicator + '">' +
                    escape_html(achievement_value) +
                '</span>' +
            '</div>';
        }

        if (column.fieldname === "sales_employee") {
            return build_invoice_link(escape_html(raw_value), data);
        }

        if (column.fieldname === "invoice_count" && data.invoice_count > 0) {
            return build_invoice_link(value, data);
        }

        return value;
    }
};

function clear_team_summary(report) {
    if (report && report.$sales_target_team_summary) {
        report.$sales_target_team_summary.empty().toggle(false);
    }
}

function render_team_summary(report) {
    if (!report || !report.$sales_target_team_summary) {
        return;
    }

    var summary = report.raw_data && report.raw_data.report_summary || [];
    report.$sales_target_team_summary.empty();

    summary.forEach(function(item) {
        var allowed_indicators = ["green", "red", "orange", "blue", "grey"];
        var indicator = allowed_indicators.indexOf(item.indicator) !== -1 ?
            item.indicator : "blue";
        var formatted_value = frappe.format(item.value, {
            fieldtype: item.datatype,
            options: "currency"
        }, {
            only_value: true
        }, {
            currency: item.currency
        });
        report.$sales_target_team_summary.append(
            '<div class="sales-target-summary-card" ' +
                'style="border:1px solid #d1d8dd; border-radius:6px; ' +
                'padding:10px 12px; min-width:0; background:#fff;">' +
                '<div class="text-muted small">' + escape_html(item.label) + '</div>' +
                '<div class="h4 indicator ' + indicator + '" ' +
                    'style="margin:6px 0 0;">' +
                    escape_html(formatted_value) +
                '</div>' +
            '</div>'
        );
    });

    report.$sales_target_team_summary.toggle(Boolean(summary.length));
}

function build_invoice_link(value, data) {
    return '<a href="#" class="sales-target-invoice-link"' +
        ' data-company="' + safe_route_attribute(data.company) + '"' +
        ' data-employee="' + safe_route_attribute(data.sales_employee) + '"' +
        ' data-from-date="' + safe_route_attribute(data.from_date) + '"' +
        ' data-to-date="' + safe_route_attribute(data.effective_to_date) + '">' +
        value + '</a>';
}

function safe_route_attribute(value) {
    return encodeURIComponent(String(value || ""));
}

function escape_html(value) {
    value = value == null ? "" : value;
    return String(value).replace(/[&<>"']/g, function(character) {
        return {
            "&": "&amp;",
            "<": "&lt;",
            ">": "&gt;",
            '"': "&quot;",
            "'": "&#39;"
        }[character];
    });
}

function open_sales_target_invoices(data) {
    frappe.set_route("List", "Sales Invoice", {
        company: data.company,
        pb_sales_employee: data.sales_employee,
        posting_date: ["between", [data.from_date, data.effective_to_date]],
        docstatus: 1
    });
}
