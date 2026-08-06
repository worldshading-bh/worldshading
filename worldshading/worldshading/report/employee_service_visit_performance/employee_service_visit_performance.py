from __future__ import unicode_literals

import frappe
from frappe.utils import add_days, cint, flt, getdate, nowdate

from worldshading.api.service_visit_commission import (
    MONTH_NAMES,
    direct_flag_condition,
    get_commission_result_for_range,
    get_coordinator_commission_result,
    get_month_range,
    get_paid_amounts,
    get_user_commission_config
)


def execute(filters=None):
    filters = filters or {}
    validate_filters(filters)

    # A user whose staff-capacity role is Coordinator earns per visitor + direct
    # quotations, not from a visit cohort - same auto-detection as the PWA.
    if get_user_commission_config(filters.get("user")).get("role") == "Coordinator":
        return execute_coordinator_report(filters)

    columns = get_columns()
    visit_rows = get_visit_rows(filters)
    data = build_detail_rows(visit_rows)
    data.append(get_total_row(visit_rows, filters))
    report_summary = get_report_summary(visit_rows, filters)

    return columns, data, None, None, report_summary, 1


def execute_coordinator_report(filters):
    """Coordinator commission for every month the date range touches.

    Commission months are atomic (success rate, gates and payouts are all monthly), so a
    multi-month range renders one section per month plus a grand total - never a blended
    figure that would reconcile with no payout.
    """
    user = filters.get("user")
    from_date = getdate(filters.get("from_date"))
    to_date = getdate(filters.get("to_date"))

    months = []
    year, month = from_date.year, from_date.month
    while (year, month) <= (to_date.year, to_date.month):
        months.append((year, month))
        month += 1
        if month == 13:
            year, month = year + 1, 1

    data = []
    totals = {"amount": 0.0, "coordinated": 0, "qualified": 0, "sources": 0,
              "direct_visits": 0, "direct_invoiced": 0, "paid": 0.0, "pending": 0.0}
    single_month = len(months) == 1

    for year, month in months:
        month_key = "{0:04d}-{1:02d}".format(year, month)
        month_from, month_to = get_month_range(month_key)
        result = get_coordinator_commission_result(user, month_key, cutoff_date=nowdate())
        sources = result.get("visitors") or []

        if not sources:
            continue

        month_total = flt(result.get("total_amount"))
        paid = get_paid_amounts(user, year, month)["Coordinator"]
        month_label = "{0} {1}".format(MONTH_NAMES[month - 1], year)

        if not single_month:
            data.append({"is_month_row": 1, "source": month_label.upper()})

        for row in sources:
            invoice_value = flt(row.get("invoice_value"))
            amount = flt(row.get("amount"))

            if row.get("is_qualified"):
                status = "Qualified"
            elif row.get("status") == "below_threshold":
                status = "{0} more visits needed".format(row.get("visits_short_of_minimum"))
            else:
                status = "Not on commission"

            data.append({
                "source": row.get("full_name"),
                "total_visits": row.get("total_visits"),
                "invoiced": row.get("converted_visits"),
                "success": row.get("success_percent"),
                "invoice_value": invoice_value,
                "rate": round(amount / invoice_value * 100, 2) if invoice_value else 0,
                "amount": amount,
                "status": status
            })

            if row.get("user") == "__direct__":
                totals["direct_visits"] += cint(row.get("total_visits"))
                totals["direct_invoiced"] += cint(row.get("converted_visits"))
                data.extend(_get_direct_visit_rows(user, month_from, month_to))

        if not single_month:
            data.append({"is_month_row": 1, "source": "{0} total".format(month_label),
                         "amount": month_total})

        totals["amount"] += month_total
        totals["coordinated"] += cint(result.get("coordinated_visits"))
        totals["qualified"] += len([v for v in sources if v.get("is_qualified")])
        totals["sources"] += len(sources)
        totals["paid"] += paid
        totals["pending"] += max(month_total - paid, 0)

    data.append({
        "is_total_row": 1,
        "source": "TOTAL",
        "amount": round(totals["amount"], 3),
        "summary_mode": "coordinator",
        "summary_total_amount": round(totals["amount"], 3),
        "summary_coordinated_visits": totals["coordinated"],
        "summary_qualified": totals["qualified"],
        "summary_sources": totals["sources"],
        "summary_direct_visits": totals["direct_visits"],
        "summary_direct_invoiced": totals["direct_invoiced"],
        "summary_paid": round(totals["paid"], 3),
        "summary_pending": round(totals["pending"], 3)
    })

    return get_coordinator_columns(), data, None, None, None, 1


def _get_direct_visit_rows(user, from_date, to_date):
    """The flagged visits behind the Direct quotations line, as clickable child rows."""
    rows = frappe.db.sql(
        """
        SELECT
            sv.name AS service_visit,
            sv.date AS visit_date,
            sv.customer_name,
            sv.workflow_state,
            sv.quotation,
            sv.sales_order,
            GROUP_CONCAT(
                CASE
                    WHEN IFNULL(si.is_return, 0) = 1 THEN CONCAT(si.name, ' (Return)')
                    ELSE si.name
                END
                ORDER BY si.posting_date, si.name
                SEPARATOR ', '
            ) AS sales_invoice,
            IFNULL(SUM(si.base_net_total), 0) AS invoice_value
        FROM `tabService Visit` sv
        LEFT JOIN `tabSales Invoice` si
            ON si.service_visit = sv.name AND si.docstatus = 1
        WHERE
            sv.docstatus = 1
            AND IFNULL(sv.workflow_state, '') != 'Cancelled'
            AND IFNULL(sv.is_direct_quotation, 0) = 1
            AND sv.visit_coordinator = %(user)s
            AND sv.date BETWEEN %(from_date)s AND %(to_date)s
            AND sv.date <= %(today)s
        GROUP BY sv.name
        ORDER BY sv.date, sv.name
        """,
        {"user": user, "from_date": from_date, "to_date": to_date, "today": nowdate()},
        as_dict=True
    )

    return [{
        "source": "",
        "service_visit": row.service_visit,
        "visit_date": row.visit_date,
        "customer": row.customer_name,
        "quotation": row.quotation,
        "sales_order": row.sales_order,
        "sales_invoice": row.sales_invoice,
        "status": row.workflow_state,
        "invoice_value": flt(row.invoice_value)
    } for row in rows]


def get_coordinator_columns():
    return [
        {"label": "Source", "fieldname": "source", "fieldtype": "Data", "width": 180},
        {"label": "Service Visit", "fieldname": "service_visit", "fieldtype": "Link",
         "options": "Service Visit", "width": 130},
        {"label": "Date", "fieldname": "visit_date", "fieldtype": "Date", "width": 95},
        {"label": "Customer", "fieldname": "customer", "fieldtype": "Data", "width": 160},
        {"label": "Quotation", "fieldname": "quotation", "fieldtype": "Link",
         "options": "Quotation", "width": 130},
        {"label": "Sales Order", "fieldname": "sales_order", "fieldtype": "Link",
         "options": "Sales Order", "width": 130},
        {"label": "Sales Invoice", "fieldname": "sales_invoice", "fieldtype": "Data",
         "width": 150},
        {"label": "Visits", "fieldname": "total_visits", "fieldtype": "Int", "width": 70},
        {"label": "Invoiced", "fieldname": "invoiced", "fieldtype": "Int", "width": 80},
        {"label": "Success", "fieldname": "success", "fieldtype": "Percent", "width": 85},
        {"label": "Invoice Value", "fieldname": "invoice_value", "fieldtype": "Currency",
         "width": 120},
        {"label": "Rate", "fieldname": "rate", "fieldtype": "Percent", "width": 75},
        {"label": "Amount", "fieldname": "amount", "fieldtype": "Currency", "width": 110},
        {"label": "Status", "fieldname": "status", "fieldtype": "Data", "width": 140}
    ]


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
        # Submitted only. Draft visits are not performed work: counting them inflated the
        # visit total and dragged the success rate down.
        "sv.docstatus = 1",
        "sv.date BETWEEN %(from_date)s AND %(to_date)s",
        # Work done, not work booked - a visit dated in the future has not happened yet.
        # Matches the commission engine so the visit total and the minimum-visits gate
        # can never disagree.
        "sv.date <= %(as_of_date)s",
        # Direct-quotation visits belong to the coordinator's bucket, never to a
        # visitor cohort (fragment is empty when the column does not exist yet).
        "1=1" + direct_flag_condition(),
        "ua.user IS NOT NULL",
        "ua.user != ''"
    ]

    if filters.get("user"):
        conditions.append("ua.user = %(user)s")

    if filters.get("city"):
        conditions.append("sv.city = %(city)s")

    if filters.get("type"):
        conditions.append("sv.type = %(type)s")

    # Invoices count whenever they are posted, same as the PWA and the Commission Payout
    # settlement - a late invoice for a July visit still belongs to July. Bounding at
    # today keeps the query deterministic.
    params = dict(filters)
    params["as_of_date"] = nowdate()
    params["invoice_cutoff_date"] = nowdate()

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
                AND posting_date <= %(invoice_cutoff_date)s
            GROUP BY service_visit
        ) inv ON inv.service_visit = sv.name
        WHERE {conditions}
        ORDER BY ua.user, sv.date, sv.name
        """.format(conditions=" AND ".join(conditions)),
        params,
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

    working_days = get_working_days(filters.get("from_date"), filters.get("to_date"))
    avg_visits_per_working_day = 0
    if working_days:
        avg_visits_per_working_day = float(total_visits) / float(working_days)

    summary = {
        "total_visits": total_visits,
        "invoiced_visits": invoiced_visits,
        "pending_quotation_count": pending_quotation_count,
        "quotation_created_count": quotation_created_count,
        "ordered_count": ordered_count,
        "lost_count": lost_count,
        "expired_count": expired_count,
        "attributed_invoice_value": attributed_invoice_value,
        "success_percent": round(success_percent, 2),
        "working_days": working_days,
        "avg_visits_per_working_day": round(avg_visits_per_working_day, 2)
    }
    summary.update(get_commission_summary(filters))

    return summary


def get_commission_summary(filters):
    """Commission figures straight from the shared engine.

    The report used to do its own flat `invoice value x %` sum, which no longer matches
    how anyone is paid: the pool is scaled by the success rate, split between visitor and
    coordinator, and pays nothing below the minimum monthly visits.
    """
    blank = {
        "commission_status": "",
        "commission_enabled": 0,
        "pool_percent": 0,
        "pool_amount": 0,
        "visitor_share_percent": 0,
        "visitor_amount": 0,
        "coordinator_share_percent": 0,
        "coordinator_amount": 0,
        "min_monthly_visits": 0,
        "visits_short_of_minimum": 0
    }

    if not filters.get("user"):
        return blank

    # The pool % lives in WS Settings (global, per-user override). The old "Commission %"
    # filter was removed from the UI: Frappe persists filter values per user, so a stale
    # entry silently overrode the configured rate and made the report disagree with the
    # PWA and with payroll. The parameter is still accepted for scripted what-if runs.
    result = get_commission_result_for_range(
        filters.get("user"),
        filters.get("from_date"),
        filters.get("to_date"),
        pool_percent=filters.get("commission_percentage"),
        # Same valued-to-date basis as the PWA and the payout settlement.
        cutoff_date=nowdate()
    )

    return {
        "commission_status": result.get("status"),
        "commission_enabled": 1 if result.get("commission_enabled") else 0,
        "pool_percent": result.get("pool_percent"),
        "pool_amount": result.get("pool_amount"),
        "visitor_share_percent": result.get("visitor_share_percent"),
        "visitor_amount": result.get("visitor_amount"),
        "coordinator_share_percent": result.get("coordinator_share_percent"),
        "coordinator_amount": result.get("coordinator_amount"),
        "min_monthly_visits": result.get("min_monthly_visits"),
        "visits_short_of_minimum": result.get("visits_short_of_minimum")
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

    if summary.get("commission_enabled"):
        is_qualified = summary.get("commission_status") == "qualified"

        report_summary.extend([
            {
                "value": summary.get("pool_amount"),
                "label": "Commission Pool ({0}% x success)".format(
                    flt(summary.get("pool_percent"))),
                "datatype": "Currency",
                "indicator": "Blue"
            },
            {
                "value": summary.get("visitor_amount"),
                "label": "Visitor Share ({0}%)".format(
                    flt(summary.get("visitor_share_percent"))),
                "datatype": "Currency",
                "indicator": "Green" if is_qualified else "Grey"
            },
            {
                "value": summary.get("coordinator_amount"),
                "label": "Coordinator Share ({0}%)".format(
                    flt(summary.get("coordinator_share_percent"))),
                "datatype": "Currency",
                "indicator": "Green" if is_qualified else "Grey"
            }
        ])

        if not is_qualified:
            # Say why nothing is payable, rather than showing a bare zero.
            report_summary.append({
                "value": summary.get("visits_short_of_minimum"),
                "label": "Visits Short Of Minimum ({0})".format(
                    cint(summary.get("min_monthly_visits"))),
                "datatype": "Int",
                "indicator": "Orange"
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
        "summary_pool_percent": summary.get("pool_percent"),
        "summary_pool_amount": summary.get("pool_amount"),
        "summary_visitor_amount": summary.get("visitor_amount"),
        "summary_coordinator_amount": summary.get("coordinator_amount"),
        "summary_commission_status": summary.get("commission_status"),
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
        "sales_order": "Ordered: {0} / Lost: {1} / Expired: {2}".format(
            summary.get("ordered_count"),
            summary.get("lost_count"),
            summary.get("expired_count")
        ),
        "sales_invoice": get_total_row_commission_label(summary),
        "invoice_date": "Value",
        "invoice_net_total": summary.get("attributed_invoice_value")
    }


def get_total_row_commission_label(summary):
    if not summary.get("commission_enabled"):
        return "No commission"

    if summary.get("commission_status") != "qualified":
        return "Needs {0} more visits".format(cint(summary.get("visits_short_of_minimum")))

    return "Pool {0} / Visitor {1}".format(
        flt(summary.get("pool_amount"), 3),
        flt(summary.get("visitor_amount"), 3)
    )


def get_working_days(from_date, to_date):
    if not from_date or not to_date:
        return 0

    from_date = getdate(from_date)
    to_date = getdate(to_date)
    today = getdate(nowdate())

    # Days not yet worked must not dilute the average. Visits are counted only up to
    # today, so the divisor stops there too. No effect once the period has ended.
    if to_date > today:
        to_date = today

    if to_date < from_date:
        return 0
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
