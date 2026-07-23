frappe.query_reports["Employee Service Visit Performance"] = {
    filters: [
        {
            fieldname: "from_date",
            label: __("From Date"),
            fieldtype: "Date",
            default: frappe.datetime.month_start(),
            reqd: 1
        },
        {
            fieldname: "to_date",
            label: __("To Date"),
            fieldtype: "Date",
            default: frappe.datetime.get_today(),
            reqd: 1
        },
        {
            fieldname: "user",
            label: __("Taken By"),
            fieldtype: "Link",
            options: "User",
            reqd: 1
        },
        {
            fieldname: "commission_percentage",
            label: __("Commission %"),
            fieldtype: "Float"
        },
        {
            fieldname: "city",
            label: __("City"),
            fieldtype: "Link",
            options: "City"
        },
        {
            fieldname: "type",
            label: __("Visit Type"),
            fieldtype: "Select",
            options: "\nMeasurement\nConsulting\nInspection\nFixing\nInstallation Follow-up\nComplaint Visit"
        }
    ],

    onload: function(report) {
        hide_report_chart(report);
    },

    after_datatable_render: function(datatable) {
        hide_report_chart(frappe.query_report);
        render_report_summary(frappe.query_report);
    },

    get_chart_data: function() {
        return null;
    },

    formatter: function(value, row, column, data, default_formatter) {
        value = default_formatter(value, row, column, data);

        if (!data) {
            return value;
        }

        if (data.is_total_row) {
            return '<span style="font-weight:700;">' + value + '</span>';
        }

        if (column.fieldname === "workflow_state" && data.workflow_state === "Invoiced") {
            value = '<span style="color:#1a7f37;font-weight:600;">' + value + '</span>';
        }

        return value;
    }
};

function hide_report_chart(report) {
    setTimeout(function() {
        if (report && report.$chart) {
            report.$chart.empty().hide();
        }

        if (report && report.$chart_wrapper) {
            report.$chart_wrapper.hide();
        }
    }, 100);
}

function render_report_summary(report) {
    if (!report || !report.raw_data || !report.raw_data.result || !report.$report) {
        return;
    }

    var total_row = get_total_row(report.raw_data.result);
    if (!total_row) {
        return;
    }

    add_summary_style();
    report.$report.prev(".employee-service-visit-summary").remove();
    report.$report.before(get_summary_html(total_row));
}

function get_total_row(rows) {
    for (var i = rows.length - 1; i >= 0; i--) {
        if (rows[i].is_total_row) {
            return rows[i];
        }
    }
}

function get_summary_html(total_row) {
    var cards = [
        {
            label: __("Total Visits"),
            value: total_row.summary_total_visits || 0,
            indicator: "blue"
        },
        {
            label: __("Invoiced Visits"),
            value: total_row.summary_invoiced_visits || 0,
            indicator: "green"
        },
        {
            label: __("Success Rate"),
            value: format_percent(total_row.summary_success_percent),
            indicator: total_row.summary_success_percent ? "green" : "red"
        },
        {
            label: __("Invoice Total"),
            value: format_summary_currency(total_row.summary_attributed_invoice_value),
            indicator: "green"
        },
        {
            label: __("Commission") + " (" + format_percent(total_row.summary_commission_percentage) + ")",
            value: format_summary_currency(total_row.summary_commission_amount),
            indicator: "green",
            hidden: !flt(total_row.summary_commission_percentage)
        },
        {
            label: __("Avg Visits / Day"),
            value: flt(total_row.summary_avg_visits_per_working_day || 0, 2),
            indicator: "blue"
        },
        {
            label: __("Pending Quotation"),
            value: total_row.summary_pending_quotation_count || 0,
            indicator: "orange"
        },
        {
            label: __("Quotation Created"),
            value: total_row.summary_quotation_created_count || 0,
            indicator: "blue"
        },
        {
            label: __("Ordered"),
            value: total_row.summary_ordered_count || 0,
            indicator: "green"
        },
        {
            label: __("Lost / Expired"),
            value: (total_row.summary_lost_count || 0) + " / " + (total_row.summary_expired_count || 0),
            indicator: "red"
        }
    ];

    var html = '<div class="employee-service-visit-summary">';
    for (var i = 0; i < cards.length; i++) {
        if (cards[i].hidden) {
            continue;
        }

        html += get_summary_card_html(cards[i]);
    }
    html += '</div>';

    return html;
}

function get_summary_card_html(card) {
    return [
        '<div class="employee-service-visit-summary-card">',
            '<div class="employee-service-visit-summary-label">',
                '<span class="employee-service-visit-summary-dot indicator-', card.indicator, '"></span>',
                escape_summary_text(card.label),
            '</div>',
            '<div class="employee-service-visit-summary-value">', escape_summary_text(card.value), '</div>',
        '</div>'
    ].join("");
}

function escape_summary_text(value) {
    if (value === null || value === undefined) {
        value = "";
    }

    return frappe.utils.escape_html(String(value));
}

function format_percent(value) {
    value = flt(value || 0, 2);
    return value + "%";
}

function format_summary_currency(value) {
    if (typeof format_currency === "function") {
        return format_currency(value || 0);
    }

    return flt(value || 0, 3);
}

function add_summary_style() {
    if ($("#employee-service-visit-summary-style").length) {
        return;
    }

    $("head").append([
        '<style id="employee-service-visit-summary-style">',
        '.employee-service-visit-summary {',
            'display:grid;',
            'grid-template-columns:repeat(auto-fit,minmax(170px,1fr));',
            'gap:10px;',
            'padding:12px 14px;',
            'border-top:1px solid #d1d8dd;',
            'border-bottom:1px solid #d1d8dd;',
            'background:#f8fafc;',
        '}',
        '.employee-service-visit-summary-card {',
            'background:#fff;',
            'border:1px solid #d1d8dd;',
            'border-radius:6px;',
            'padding:10px 12px;',
            'min-height:72px;',
        '}',
        '.employee-service-visit-summary-label {',
            'color:#6b7280;',
            'font-size:12px;',
            'font-weight:600;',
            'line-height:16px;',
            'white-space:nowrap;',
            'overflow:hidden;',
            'text-overflow:ellipsis;',
        '}',
        '.employee-service-visit-summary-value {',
            'color:#111827;',
            'font-size:20px;',
            'font-weight:700;',
            'line-height:28px;',
            'margin-top:6px;',
            'white-space:nowrap;',
            'overflow:hidden;',
            'text-overflow:ellipsis;',
        '}',
        '.employee-service-visit-summary-dot {',
            'display:inline-block;',
            'width:8px;',
            'height:8px;',
            'border-radius:50%;',
            'margin-right:6px;',
        '}',
        '.employee-service-visit-summary-dot.indicator-blue { background:#2490ef; }',
        '.employee-service-visit-summary-dot.indicator-green { background:#28a745; }',
        '.employee-service-visit-summary-dot.indicator-orange { background:#f59e0b; }',
        '.employee-service-visit-summary-dot.indicator-red { background:#dc3545; }',
        '</style>'
    ].join(""));
}
