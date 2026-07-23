from __future__ import unicode_literals

import frappe
from frappe.utils import add_days, flt, getdate


def execute(filters=None):
    filters = filters or {}
    validate_filters(filters)

    columns = get_columns()
    visit_rows = get_visit_rows(filters)
    data = build_detail_rows(visit_rows)
    data.append(get_total_row(visit_rows, filters))
    report_summary = get_report_summary(visit_rows, filters)

    return columns, data, None, None, report_summary, 1


def validate_filters(filters):
    if not filters.get("from_date"):
        frappe.throw("From Date is required")

    if not filters.get("to_date"):
        frappe.throw("To Date is required")

    if not filters.get("user"):
        frappe.throw("Taken By is required")

    if filters.get("from_date") > filters.get("to_date"):
        frappe.throw("From Date cannot be after To Date")

    if filters.get("commission_percentage") and flt(filters.get("commission_percentage")) < 0:
        frappe.throw("Commission % cannot be negative")


def get_visit_rows(filters):
    conditions = [
        "sv.docstatus != 2",
        "sv.date BETWEEN %(from_date)s AND %(to_date)s",
        "ua.user IS NOT NULL",
        "ua.user != ''"
    ]

    if filters.get("user"):
        conditions.append("ua.user = %(user)s")

    if filters.get("city"):
        conditions.append("sv.city = %(city)s")

    if filters.get("type"):
        conditions.append("sv.type = %(type)s")

    return frappe.db.sql(
        """
        SELECT
            ua.user AS user,
            COALESCE(emp.employee_name, usr.full_name, ua.user) AS employee_name,
            sv.name AS service_visit,
            sv.date AS visit_date,
            sv.customer_name AS customer_name,
            sv.type AS visit_type,
            sv.workflow_state AS workflow_state,
            sv.quotation AS quotation,
            sv.sales_order AS sales_order,
            sv.sales_invoice AS active_sales_invoice,
            inv.sales_invoice AS sales_invoice,
            inv.invoice_date AS invoice_date,
            IFNULL(inv.invoice_net_total, 0) AS invoice_net_total,
            IFNULL(inv.normal_invoice_count, 0) AS normal_invoice_count
        FROM (
            SELECT DISTINCT parent, user
            FROM `tabWS User Assignment`
            WHERE
                parenttype = 'Service Visit'
                AND parentfield = 'assigned_users'
        ) ua
        INNER JOIN `tabService Visit` sv ON sv.name = ua.parent
        LEFT JOIN `tabUser` usr ON usr.name = ua.user
        LEFT JOIN (
            SELECT
                user_id,
                MAX(employee_name) AS employee_name
            FROM `tabEmployee`
            WHERE
                user_id IS NOT NULL
                AND user_id != ''
            GROUP BY user_id
        ) emp ON emp.user_id = ua.user
        LEFT JOIN (
            SELECT
                service_visit,
                GROUP_CONCAT(
                    CASE
                        WHEN IFNULL(is_return, 0) = 1 THEN CONCAT(name, ' (Return)')
                        ELSE name
                    END
                    ORDER BY posting_date, name
                    SEPARATOR ', '
                ) AS sales_invoice,
                MIN(posting_date) AS invoice_date,
                SUM(base_net_total) AS invoice_net_total,
                SUM(CASE WHEN IFNULL(is_return, 0) = 0 THEN 1 ELSE 0 END) AS normal_invoice_count
            FROM `tabSales Invoice`
            WHERE
                docstatus = 1
                AND service_visit IS NOT NULL
                AND service_visit != ''
            GROUP BY service_visit
        ) inv ON inv.service_visit = sv.name
        WHERE {conditions}
        ORDER BY ua.user, sv.date, sv.name
        """.format(conditions=" AND ".join(conditions)),
        filters,
        as_dict=True
    )


def build_detail_rows(visit_rows):
    return [get_detail_row(row) for row in visit_rows]


def get_summary_values(rows, filters=None):
    filters = filters or {}
    total_visits = len(rows)
    invoiced_visits = 0
    pending_quotation_count = 0
    quotation_created_count = 0
    ordered_count = 0
    lost_count = 0
    expired_count = 0
    attributed_invoice_value = 0

    for row in rows:
        state = row.get("workflow_state") or ""

        if row.get("normal_invoice_count"):
            invoiced_visits += 1
            attributed_invoice_value += row.get("invoice_net_total") or 0

        if state == "Pending Quotation":
            pending_quotation_count += 1
        elif state == "Quotation Created":
            quotation_created_count += 1
        elif state == "Ordered":
            ordered_count += 1
        elif state == "Lost":
            lost_count += 1
        elif state == "Expired":
            expired_count += 1

    success_percent = 0
    if total_visits:
        success_percent = (float(invoiced_visits) / float(total_visits)) * 100

    commission_percentage = get_effective_commission_percentage(filters)
    commission_amount = 0
    if commission_percentage:
        commission_amount = (attributed_invoice_value * commission_percentage) / 100

    working_days = get_working_days(filters.get("from_date"), filters.get("to_date"))
    avg_visits_per_working_day = 0
    if working_days:
        avg_visits_per_working_day = float(total_visits) / float(working_days)

    return {
        "total_visits": total_visits,
        "invoiced_visits": invoiced_visits,
        "pending_quotation_count": pending_quotation_count,
        "quotation_created_count": quotation_created_count,
        "ordered_count": ordered_count,
        "lost_count": lost_count,
        "expired_count": expired_count,
        "attributed_invoice_value": attributed_invoice_value,
        "success_percent": round(success_percent, 2),
        "commission_percentage": commission_percentage,
        "commission_amount": commission_amount,
        "working_days": working_days,
        "avg_visits_per_working_day": round(avg_visits_per_working_day, 2)
    }


def get_report_summary(rows, filters=None):
    summary = get_summary_values(rows, filters)

    report_summary = [
        {
            "value": summary.get("total_visits"),
            "label": "Total Visits",
            "datatype": "Int",
            "indicator": "Blue"
        },
        {
            "value": summary.get("invoiced_visits"),
            "label": "Invoiced Visits",
            "datatype": "Int",
            "indicator": "Green"
        },
        {
            "value": summary.get("success_percent"),
            "label": "Success %",
            "datatype": "Percent",
            "indicator": "Green" if summary.get("success_percent") else "Red"
        },
        {
            "value": summary.get("attributed_invoice_value"),
            "label": "Invoice Total",
            "datatype": "Currency",
            "indicator": "Green"
        },
    ]

    if summary.get("commission_percentage"):
        report_summary.append({
            "value": summary.get("commission_amount"),
            "label": "Commission Amount",
            "datatype": "Currency",
            "indicator": "Green"
        })

    report_summary.extend([
        {
            "value": summary.get("avg_visits_per_working_day"),
            "label": "Avg Visits / Day",
            "datatype": "Float",
            "indicator": "Blue"
        },
        {
            "value": summary.get("pending_quotation_count"),
            "label": "Pending Quotation",
            "datatype": "Int",
            "indicator": "Orange"
        },
        {
            "value": summary.get("quotation_created_count"),
            "label": "Quotation Created",
            "datatype": "Int",
            "indicator": "Blue"
        },
        {
            "value": summary.get("ordered_count"),
            "label": "Ordered",
            "datatype": "Int",
            "indicator": "Green"
        },
        {
            "value": summary.get("lost_count"),
            "label": "Lost",
            "datatype": "Int",
            "indicator": "Red"
        },
        {
            "value": summary.get("expired_count"),
            "label": "Expired",
            "datatype": "Int",
            "indicator": "Grey"
        }
    ])

    return report_summary


def get_total_row(rows, filters=None):
    summary = get_summary_values(rows, filters)

    return {
        "is_total_row": 1,
        "summary_total_visits": summary.get("total_visits"),
        "summary_invoiced_visits": summary.get("invoiced_visits"),
        "summary_success_percent": summary.get("success_percent"),
        "summary_attributed_invoice_value": summary.get("attributed_invoice_value"),
        "summary_commission_percentage": summary.get("commission_percentage"),
        "summary_commission_amount": summary.get("commission_amount"),
        "summary_working_days": summary.get("working_days"),
        "summary_avg_visits_per_working_day": summary.get("avg_visits_per_working_day"),
        "summary_pending_quotation_count": summary.get("pending_quotation_count"),
        "summary_quotation_created_count": summary.get("quotation_created_count"),
        "summary_ordered_count": summary.get("ordered_count"),
        "summary_lost_count": summary.get("lost_count"),
        "summary_expired_count": summary.get("expired_count"),
        "service_visit": "TOTAL",
        "visit_date": None,
        "customer_name": "Visits: {0}".format(summary.get("total_visits")),
        "visit_type": "Invoiced: {0}".format(summary.get("invoiced_visits")),
        "workflow_state": "Success: {0}%".format(summary.get("success_percent")),
        "quotation": "Pending: {0} / Quoted: {1}".format(
            summary.get("pending_quotation_count"),
            summary.get("quotation_created_count")
        ),
        "sales_order": "Ordered: {0}".format(summary.get("ordered_count")),
        "sales_invoice": "Lost: {0} / Expired: {1}".format(
            summary.get("lost_count"),
            summary.get("expired_count")
        ),
        "invoice_date": "Value",
        "invoice_net_total": summary.get("attributed_invoice_value")
    }


def get_working_days(from_date, to_date):
    if not from_date or not to_date:
        return 0

    from_date = getdate(from_date)
    to_date = getdate(to_date)
    holiday_dates = get_holiday_dates(from_date, to_date)
    working_days = 0

    current_date = from_date
    while current_date <= to_date:
        # Friday is the weekly off day for this report's productivity metric.
        if current_date.weekday() != 4 and current_date not in holiday_dates:
            working_days += 1

        current_date = add_days(current_date, 1)

    return working_days


def get_holiday_dates(from_date, to_date):
    holiday_list = get_default_holiday_list()
    if not holiday_list:
        return set()

    return set(frappe.db.sql_list(
        """
        SELECT holiday_date
        FROM `tabHoliday`
        WHERE
            parent = %s
            AND holiday_date BETWEEN %s AND %s
        """,
        (holiday_list, from_date, to_date)
    ))


def get_default_holiday_list():
    company = frappe.defaults.get_user_default("Company")
    if not company:
        company = frappe.db.get_single_value("Global Defaults", "default_company")

    if company:
        holiday_list = frappe.db.get_value("Company", company, "default_holiday_list")
        if holiday_list:
            return holiday_list

    return frappe.db.get_value("Holiday List", {"is_default": 1}, "name")


def get_effective_commission_percentage(filters):
    if filters.get("commission_percentage") not in (None, ""):
        return flt(filters.get("commission_percentage"))

    return get_commission_percentage(filters.get("user"))


def get_commission_percentage(user=None):
    if not user:
        return 0

    settings = frappe.get_single("WS Settings")

    for row in settings.service_visit_staff_capacity:
        if row.user == user:
            return flt(row.get("commission"))

    return 0


def get_detail_row(row):
    return {
        "user": row.get("user"),
        "employee_name": row.get("employee_name"),
        "service_visit": row.get("service_visit"),
        "visit_date": row.get("visit_date"),
        "customer_name": row.get("customer_name"),
        "visit_type": row.get("visit_type"),
        "workflow_state": row.get("workflow_state"),
        "quotation": row.get("quotation"),
        "sales_order": row.get("sales_order"),
        "sales_invoice": row.get("sales_invoice"),
        "invoice_date": row.get("invoice_date"),
        "invoice_net_total": row.get("invoice_net_total") or 0,
        "normal_invoice_count": row.get("normal_invoice_count") or 0
    }


def get_columns():
    return [
        {"label": "Service Visit", "fieldname": "service_visit", "fieldtype": "Link", "options": "Service Visit", "width": 100},
        {"label": "Visit Date", "fieldname": "visit_date", "fieldtype": "Date", "width": 100},
        {"label": "Customer", "fieldname": "customer_name", "fieldtype": "Data", "width": 150},
        {"label": "Visit Type", "fieldname": "visit_type", "fieldtype": "Data", "width": 130},
        {"label": "Workflow State", "fieldname": "workflow_state", "fieldtype": "Data", "width": 140},
        {"label": "Quotation", "fieldname": "quotation", "fieldtype": "Link", "options": "Quotation", "width": 140},
        {"label": "Sales Order", "fieldname": "sales_order", "fieldtype": "Link", "options": "Sales Order", "width": 140},
        {"label": "Sales Invoice", "fieldname": "sales_invoice", "fieldtype": "Data", "width": 150},
        {"label": "Invoice Date", "fieldname": "invoice_date", "fieldtype": "Date", "width": 100},
        {"label": "Invoice Net Total", "fieldname": "invoice_net_total", "fieldtype": "Currency", "width": 130}
    ]
