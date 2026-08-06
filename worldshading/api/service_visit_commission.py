"""Service Visit commission engine.

Commission model (per visitor, per calendar month):

    Cohort            = Service Visits assigned to the visitor with sv.date in the month
    Converted         = cohort visits holding at least one submitted, non-return Sales Invoice
                        posted on or before the cutoff date
    Invoice Value     = net total of every submitted invoice (returns included, so credit
                        notes subtract) for the cohort, posted on or before the cutoff date
    Success Rate      = Converted / Total Visits
    Commission Pool   = Invoice Value x Pool %  x Success Rate
    Visitor share     = Pool x Visitor Share %
    Coordinator share = Pool x (100 - Visitor Share %)

A visitor earns nothing unless commission is enabled for them AND the cohort meets the
minimum monthly visit count.

The cutoff date (month end + cutoff days) is what keeps this stable: once it has passed,
the same month always computes to the same figures no matter when the query is re-run,
so history is immutable without needing to be stored.
"""

import frappe
from datetime import date
from frappe.utils import add_days, cint, flt, getdate, nowdate


# Used until the matching WS Settings fields are created, and as the fallback
# whenever a setting is left blank.
DEFAULTS = {
    "pool_percent": 10.0,
    "min_monthly_visits": 35,
    "visitor_share": 40.0,
    "invoice_cutoff_days": 20
}

STATUS_NOT_ENABLED = "not_enabled"
STATUS_BELOW_THRESHOLD = "below_threshold"
STATUS_QUALIFIED = "qualified"

# `role` on the staff capacity row. A blank role means Visitor, so rows predating the
# field keep working. "Both" is not an option today but is honoured if it is ever added.
VISITOR_ROLES = ("", "Visitor", "Both")
COORDINATOR_ROLES = ("Coordinator", "Both")

CURRENCY_PRECISION = 3


def _get_settings_doc():
    """WS Settings via the document cache - the coordinator path resolves per-user config
    for a dozen visitors in one request, and a fresh DB load each time cost ~2s."""
    try:
        return frappe.get_cached_doc("WS Settings", "WS Settings")
    except Exception:
        return frappe.get_single("WS Settings")


def _global_setting(settings, fieldname, default):
    """Read a global setting, honouring an explicitly saved 0.

    Only an unset or empty field falls back to the default. This matters most for
    `commission_invoice_cutoff_days`, where 0 is a meaningful choice (invoices must be
    posted by month end) and must not be mistaken for "not configured".
    """
    value = settings.get(fieldname)

    if value is None or value == "":
        return default

    return value


def get_commission_settings():
    """Global commission settings, falling back to DEFAULTS only for blank/absent fields."""
    settings = _get_settings_doc()

    resolved = {
        "pool_percent": flt(_global_setting(
            settings, "commission_pool_percent", DEFAULTS["pool_percent"])),
        "min_monthly_visits": cint(_global_setting(
            settings, "commission_min_monthly_visits", DEFAULTS["min_monthly_visits"])),
        "visitor_share": flt(_global_setting(
            settings, "commission_visitor_share", DEFAULTS["visitor_share"])),
        "invoice_cutoff_days": cint(_global_setting(
            settings, "commission_invoice_cutoff_days", DEFAULTS["invoice_cutoff_days"]))
    }

    # The coordinator share is independent of the visitor share, so paying e.g. 60/20
    # leaves the remaining 20% of the pool with the company. Blank keeps the historical
    # behaviour (coordinator takes the whole remainder); an explicit 0 is honoured; and
    # the value is capped at the remainder so the pool can never pay out more than 100%.
    remainder = max(100.0 - resolved["visitor_share"], 0.0)
    coordinator_share = _global_setting(settings, "commission_coordinator_share", None)

    if coordinator_share is None:
        resolved["coordinator_share"] = remainder
    else:
        resolved["coordinator_share"] = min(max(flt(coordinator_share), 0.0), remainder)

    # How many months back an earned month can still settle late invoices. Explicit 0
    # means only the payout month itself; blank falls back to 6.
    resolved["open_months"] = cint(_global_setting(settings, "commission_open_months", 6))

    # Monthly minimum for the coordinator's direct-quotation bucket. 0 = no minimum
    # (unlike the visitor gate, there is no non-zero fallback).
    resolved["direct_min_monthly"] = cint(_global_setting(
        settings, "commission_direct_min_monthly", 0))

    # Coordinator's share of the direct-quotation commission. Blank = 100% (the full
    # amount); an explicit 0 is honoured; anything unpaid stays with the company.
    direct_share = _global_setting(settings, "commission_direct_share", None)
    resolved["direct_share"] = 100.0 if direct_share is None \
        else min(max(flt(direct_share), 0.0), 100.0)

    return resolved


def get_user_commission_config(user, settings=None):
    """Per-user config: the staff capacity row overrides the global settings."""
    config = dict(get_commission_settings())
    config["user"] = user
    config["commission_enabled"] = False
    config["role"] = "Visitor"
    config["is_visitor"] = True
    config["is_coordinator"] = False

    if not user:
        return config

    settings = settings or _get_settings_doc()
    has_enabled_field = _has_column("Service Visit Staff Capacity", "commission_enabled")

    for row in settings.service_visit_staff_capacity:
        if row.get("user") != user:
            continue

        # Until the gate field exists, fall back to the scheduling `active` flag so the
        # engine stays testable before the settings migration is applied.
        if has_enabled_field:
            config["commission_enabled"] = bool(cint(row.get("commission_enabled")))
        else:
            config["commission_enabled"] = bool(cint(row.get("active")))

        # Child table columns are NOT NULL, so a blank override is stored as 0. Unlike the
        # global settings above, 0 here can only mean "inherit the global value".
        if flt(row.get("commission")):
            config["pool_percent"] = flt(row.get("commission"))

        if cint(row.get("min_visits_override")):
            config["min_monthly_visits"] = cint(row.get("min_visits_override"))

        config["role"] = (row.get("role") or "").strip() or "Visitor"
        break

    config["is_visitor"] = config["role"] in VISITOR_ROLES
    config["is_coordinator"] = config["role"] in COORDINATOR_ROLES

    return config


def get_commission_result(user, month=None, cutoff_date=None):
    """Full commission breakdown for one visitor in one month."""
    from_date, to_date = get_month_range(month)

    return get_commission_result_for_range(user, from_date, to_date,
                                           cutoff_date=cutoff_date)


def get_paid_amounts(user, year, month_number, commission_type="Service Visit"):
    """What submitted Commission Payouts have already paid this user for one month,
    split by component. The PWA paid/pending display reads this - same ledger the
    payout's Fetch Details uses, so the two can never disagree."""
    paid_map = _get_paid_map(commission_type, user=user)

    return {
        "Visitor": round(flt(paid_map.get((user, "Visitor", year, month_number))),
                         CURRENCY_PRECISION),
        "Coordinator": round(flt(paid_map.get((user, "Coordinator", year, month_number))),
                             CURRENCY_PRECISION)
    }


def get_commission_result_for_range(user, from_date, to_date, pool_percent=None,
                                    cutoff_date=None):
    """Same calculation over an arbitrary date range.

    The desk report filters on a free date range rather than a month, so it enters here.
    `pool_percent` lets the report's Commission % filter override the configured rate.
    `cutoff_date` overrides the configured invoice cutoff - the payout settlement passes
    today so an earned month is always valued on everything invoiced so far.
    """
    from_date = getdate(from_date)
    to_date = getdate(to_date)
    config = get_user_commission_config(user)

    if pool_percent not in (None, ""):
        config["pool_percent"] = flt(pool_percent)

    cutoff_date = getdate(cutoff_date) if cutoff_date \
        else add_days(to_date, config["invoice_cutoff_days"])

    all_visits = _get_cohort_visits(user, from_date, to_date)
    invoice_map = _get_invoice_map(
        [d.get("service_visit") for d in all_visits], cutoff_date)

    # Only visits whose date has arrived count as work done. A visit booked for the 28th
    # is not a miss on the 25th, so it must not sit in the success-rate denominator or
    # count toward the monthly minimum until it happens. Once the month is over every
    # date has passed, so a closed month is unaffected by this.
    today = getdate(nowdate())
    upcoming_visits = 0
    total_visits = 0
    converted_visits = 0
    invoice_value = 0.0
    visit_list = []

    for visit in all_visits:
        invoice = invoice_map.get(visit.get("service_visit")) or {}
        normal_count = cint(invoice.get("normal_count"))
        is_upcoming = getdate(visit.get("visit_date")) > today

        if is_upcoming:
            upcoming_visits += 1
        else:
            total_visits += 1

            if invoice:
                invoice_value += flt(invoice.get("net_value"))

            if normal_count:
                converted_visits += 1

        visit_list.append({
            "is_upcoming": 1 if is_upcoming else 0,
            "service_visit": visit.get("service_visit"),
            "visit_date": visit.get("visit_date"),
            "customer_name": visit.get("customer_name"),
            "visit_type": visit.get("visit_type"),
            "workflow_state": visit.get("workflow_state"),
            "sales_invoice": ", ".join([
                d.get("sales_invoice") for d in invoice.get("invoices") or []]),
            "invoices": invoice.get("invoices") or [],
            "normal_count": normal_count,
            "is_invoiced": 1 if normal_count else 0,
            "invoice_date": invoice.get("invoice_date"),
            "invoice_net_total": flt(invoice.get("net_value"))
        })

    visit_list.sort(
        key=lambda row: (str(row.get("visit_date") or ""), row.get("service_visit") or ""),
        reverse=True
    )

    # A month of net credit notes must not produce negative commission.
    invoice_value = max(invoice_value, 0.0)

    success_rate = (float(converted_visits) / float(total_visits)) if total_visits else 0.0
    pool_amount = invoice_value * (config["pool_percent"] / 100.0) * success_rate
    coordinator_share = config["coordinator_share"]

    # A Coordinator-only row earns from the coordinator side, never a visitor share.
    if not config["commission_enabled"] or not config["is_visitor"]:
        status = STATUS_NOT_ENABLED
    elif total_visits < config["min_monthly_visits"]:
        status = STATUS_BELOW_THRESHOLD
    else:
        status = STATUS_QUALIFIED

    is_qualified = status == STATUS_QUALIFIED
    visitor_amount = pool_amount * (config["visitor_share"] / 100.0) if is_qualified else 0.0
    coordinator_amount = pool_amount * (coordinator_share / 100.0) if is_qualified else 0.0

    return {
        "user": user,
        "month": "{0:04d}-{1:02d}".format(from_date.year, from_date.month),
        "from_date": from_date,
        "to_date": to_date,
        "cutoff_date": cutoff_date,
        "cutoff_days": config["invoice_cutoff_days"],
        "is_final": getdate(nowdate()) > getdate(cutoff_date),

        "status": status,
        "is_qualified": is_qualified,
        "commission_enabled": config["commission_enabled"],
        "min_monthly_visits": config["min_monthly_visits"],
        "visits_short_of_minimum": max(config["min_monthly_visits"] - total_visits, 0),

        "total_visits": total_visits,
        "upcoming_visits": upcoming_visits,
        "converted_visits": converted_visits,
        "success_percent": round(success_rate * 100.0, 2),
        "invoice_value": round(invoice_value, CURRENCY_PRECISION),

        "pool_percent": config["pool_percent"],
        # What the pool is worth regardless of qualification, so the PWA can show a
        # blocked visitor what they are leaving on the table.
        "pool_amount": round(pool_amount, CURRENCY_PRECISION),
        "visitor_share_percent": config["visitor_share"],
        "visitor_amount": round(visitor_amount, CURRENCY_PRECISION),
        "coordinator_share_percent": coordinator_share,
        "coordinator_amount": round(coordinator_amount, CURRENCY_PRECISION),

        # Every cohort visit, invoiced or not. The invoiced subset is derived on the
        # client from is_invoiced rather than shipped twice.
        "visit_list": visit_list,
        "currency": frappe.defaults.get_global_default("currency") or "BHD"
    }


def get_coordinator_commission_result(user, month=None, cutoff_date=None):
    """Commission earned by a visit coordinator in one month, broken down per visitor.

    The coordinator takes the non-visitor slice of each visitor's pool, weighted by how
    much of that visitor's invoice value came from visits this coordinator scheduled.
    A visitor who does not qualify produces no pool, so contributes nothing.

    Deliberately batched: one query for the month's visits and one for their invoices,
    then every visitor is computed in memory. Calling get_commission_result() per visitor
    would issue two queries each - roughly 24 on a phone request.
    """
    from_date, to_date = get_month_range(month)
    config = get_user_commission_config(user)
    settings = get_commission_settings()
    cutoff_date = getdate(cutoff_date) if cutoff_date \
        else add_days(to_date, config["invoice_cutoff_days"])
    coordinator_share = settings["coordinator_share"]

    result = {
        "user": user,
        "month": "{0:04d}-{1:02d}".format(from_date.year, from_date.month),
        "from_date": from_date,
        "to_date": to_date,
        "cutoff_date": cutoff_date,
        "is_final": getdate(nowdate()) > getdate(cutoff_date),
        "is_coordinator": config["is_coordinator"],
        "commission_enabled": config["commission_enabled"],
        "coordinator_share_percent": coordinator_share,
        "total_amount": 0.0,
        "coordinated_visits": 0,
        "visitors": [],
        "currency": frappe.defaults.get_global_default("currency") or "BHD"
    }

    if not user or not config["is_coordinator"] or not config["commission_enabled"]:
        return result

    rows = _get_month_visitor_rows(from_date, to_date)

    if not rows:
        return result

    invoice_map = _get_invoice_map(
        list(set([d.get("service_visit") for d in rows])), cutoff_date)

    # visitor -> their whole month, plus the slice this coordinator scheduled
    visitors = {}
    # Distinct visits: a visit taken by two people appears twice in `rows`, and counting
    # those pairs would overstate how many visits she actually scheduled.
    coordinated_visit_names = set()

    for row in rows:
        visitor = row.get("visitor")
        invoice = invoice_map.get(row.get("service_visit")) or {}
        value = flt(invoice.get("net_value"))
        is_converted = 1 if cint(invoice.get("normal_count")) else 0

        entry = visitors.setdefault(visitor, {
            "total_visits": 0, "converted_visits": 0, "invoice_value": 0.0,
            "coordinated_visits": 0, "coordinated_value": 0.0
        })
        entry["total_visits"] += 1
        entry["converted_visits"] += is_converted
        entry["invoice_value"] += value

        if row.get("visit_coordinator") == user:
            entry["coordinated_visits"] += 1
            entry["coordinated_value"] += value
            coordinated_visit_names.add(row.get("service_visit"))

    breakdown = []
    total_amount = 0.0

    for visitor, entry in visitors.items():
        if not entry["coordinated_visits"]:
            continue

        visitor_config = get_user_commission_config(visitor)

        # Only visitors actually on the commission scheme belong on a coordinator's page.
        # Everyone else generates no pool, so listing them is noise.
        if not visitor_config["commission_enabled"] or not visitor_config["is_visitor"]:
            continue

        total_visits = entry["total_visits"]
        invoice_value = max(entry["invoice_value"], 0.0)
        success_rate = (float(entry["converted_visits"]) / float(total_visits)) if total_visits else 0.0
        pool_amount = invoice_value * (visitor_config["pool_percent"] / 100.0) * success_rate

        if total_visits < visitor_config["min_monthly_visits"]:
            status = STATUS_BELOW_THRESHOLD
        else:
            status = STATUS_QUALIFIED

        # Share of that visitor's value this coordinator is responsible for. 1.0 while
        # she schedules everything; it is what prevents double paying once there are two.
        weight = (max(entry["coordinated_value"], 0.0) / invoice_value) if invoice_value else 0.0
        amount = (pool_amount * (coordinator_share / 100.0) * weight
                  if status == STATUS_QUALIFIED else 0.0)
        total_amount += amount

        breakdown.append({
            "user": visitor,
            "full_name": frappe.db.get_value("User", visitor, "full_name") or visitor,
            "status": status,
            "is_qualified": status == STATUS_QUALIFIED,
            "min_monthly_visits": visitor_config["min_monthly_visits"],
            "visits_short_of_minimum": max(visitor_config["min_monthly_visits"] - total_visits, 0),
            "total_visits": total_visits,
            "converted_visits": entry["converted_visits"],
            "success_percent": round(success_rate * 100.0, 2),
            "invoice_value": round(invoice_value, CURRENCY_PRECISION),
            "pool_amount": round(pool_amount, CURRENCY_PRECISION),
            "coordinated_visits": entry["coordinated_visits"],
            "weight_percent": round(weight * 100.0, 2),
            "amount": round(amount, CURRENCY_PRECISION)
        })

    # Earners first, then the biggest missed opportunity.
    breakdown.sort(key=lambda d: (-d["amount"], -d["pool_amount"]))

    direct = _get_direct_quotation_result(user, config, settings, from_date, to_date,
                                          cutoff_date)

    if direct:
        breakdown.append(direct)
        total_amount += direct["amount"]

    result["visitors"] = breakdown
    result["coordinated_visits"] = len(coordinated_visit_names) + (
        direct["total_visits"] if direct else 0)
    result["total_amount"] = round(total_amount, CURRENCY_PRECISION)

    return result


def _get_direct_quotation_result(user, config, settings, from_date, to_date, cutoff_date):
    """The coordinator's direct-quotation bucket, shaped like a per-visitor row.

    Flagged visits are quoted by the coordinator without any real visit, so the whole
    amount is theirs: invoice value x pool % x direct success rate, no share split.
    Returns None when the month has no flagged visits.
    """
    if not _has_column("Service Visit", "is_direct_quotation"):
        return None

    visits = frappe.db.sql(
        """
        SELECT sv.name
        FROM `tabService Visit` sv
        WHERE
            sv.docstatus = 1
            AND IFNULL(sv.workflow_state, '') != 'Cancelled'
            AND IFNULL(sv.is_direct_quotation, 0) = 1
            AND sv.visit_coordinator = %(user)s
            AND sv.date BETWEEN %(from_date)s AND %(to_date)s
            AND sv.date <= %(today)s
        """,
        {"user": user, "from_date": from_date, "to_date": to_date, "today": nowdate()},
        as_dict=True
    )

    if not visits:
        return None

    invoice_map = _get_invoice_map([d.name for d in visits], cutoff_date)

    total_visits = len(visits)
    converted_visits = 0
    invoice_value = 0.0

    for visit in visits:
        invoice = invoice_map.get(visit.name) or {}
        invoice_value += flt(invoice.get("net_value"))

        if cint(invoice.get("normal_count")):
            converted_visits += 1

    invoice_value = max(invoice_value, 0.0)
    success_rate = float(converted_visits) / float(total_visits)
    computed = invoice_value * (config["pool_percent"] / 100.0) * success_rate
    earned = computed * (settings["direct_share"] / 100.0)

    minimum = settings["direct_min_monthly"]
    qualified = total_visits >= minimum

    return {
        "user": "__direct__",
        "full_name": "Direct quotations",
        "status": STATUS_QUALIFIED if qualified else STATUS_BELOW_THRESHOLD,
        "is_qualified": qualified,
        "min_monthly_visits": minimum,
        "visits_short_of_minimum": max(minimum - total_visits, 0),
        "total_visits": total_visits,
        "converted_visits": converted_visits,
        "success_percent": round(success_rate * 100.0, 2),
        "invoice_value": round(invoice_value, CURRENCY_PRECISION),
        "pool_amount": round(earned, CURRENCY_PRECISION),
        "coordinated_visits": total_visits,
        "weight_percent": 100.0,
        "amount": round(earned, CURRENCY_PRECISION) if qualified else 0.0
    }


def _get_month_visitor_rows(from_date, to_date):
    """One row per (visitor x visit) for the month, carrying the visit's coordinator."""
    return frappe.db.sql(
        """
        SELECT
            ua.user AS visitor,
            sv.name AS service_visit,
            sv.visit_coordinator
        FROM (
            SELECT DISTINCT parent, user
            FROM `tabWS User Assignment`
            WHERE
                parenttype = 'Service Visit'
                AND parentfield = 'assigned_users'
        ) ua
        INNER JOIN `tabService Visit` sv ON sv.name = ua.parent
        WHERE
            sv.docstatus = 1
            AND IFNULL(sv.workflow_state, '') != 'Cancelled'
            AND sv.date BETWEEN %(from_date)s AND %(to_date)s
            AND sv.date <= %(today)s
            {direct_flag}
        """.format(direct_flag=direct_flag_condition()),
        {"from_date": from_date, "to_date": to_date, "today": nowdate()},
        as_dict=True
    )


def get_commission_results(month=None, users=None):
    """Commission breakdown for every commission-enabled visitor in a month."""
    if not users:
        users = get_commission_users()

    return [get_commission_result(user, month) for user in users]


MONTH_NAMES = ["January", "February", "March", "April", "May", "June",
               "July", "August", "September", "October", "November", "December"]


def _resolve_year(month_number, reference_month_number, reference_year):
    """A month name has no year: it belongs to the reference year unless it comes AFTER
    the reference month, in which case it can only mean the previous year (a January
    payout listing December rows)."""
    return reference_year if month_number <= reference_month_number else reference_year - 1


def build_settlement_rows(payout_month, posting_date, commission_type="Service Visit"):
    """Delta settlement for one payout run.

    For the payout month and every earlier month still inside the open window, each
    earned month is recomputed on everything invoiced to date and diffed against what
    submitted Commission Payouts already paid for it. Only positive differences become
    rows - a month that later shrinks (returns) simply stays ahead of its earned value
    until new invoices catch up.
    """
    if commission_type != "Service Visit":
        frappe.throw("Commission type {0} has no calculator yet.".format(commission_type))

    if payout_month not in MONTH_NAMES:
        frappe.throw("Invalid payout month.")

    posting_date = getdate(posting_date)
    payout_number = MONTH_NAMES.index(payout_month) + 1
    payout_year = _resolve_year(payout_number, posting_date.month, posting_date.year)

    settings = get_commission_settings()
    today = getdate(nowdate())
    paid_map = _get_paid_map(commission_type)

    # Payout month first, then walking back through the open window.
    months = []
    year, number = payout_year, payout_number
    for _ in range(settings["open_months"] + 1):
        months.append((year, number))
        number -= 1
        if number == 0:
            year, number = year - 1, 12

    staff = _get_settings_doc().service_visit_staff_capacity
    rows = []

    for staff_row in staff:
        user = staff_row.get("user")

        if not user or not cint(staff_row.get("commission_enabled")):
            continue

        config = get_user_commission_config(user)
        employee, employee_name = _get_active_employee(user)

        for year, number in months:
            month_key = "{0:04d}-{1:02d}".format(year, number)
            from_date, to_date = get_month_range(month_key)

            is_payout_month = (year, number) == (payout_year, payout_number)

            if config["is_visitor"]:
                result = get_commission_result_for_range(
                    user, from_date, to_date, cutoff_date=today)
                rows.extend(_settlement_row(
                    paid_map, commission_type, user, employee, employee_name,
                    "Visitor", year, number, result["visitor_amount"], result,
                    is_payout_month))

            if config["is_coordinator"]:
                result = get_coordinator_commission_result(
                    user, month_key, cutoff_date=today)
                rows.extend(_settlement_row(
                    paid_map, commission_type, user, employee, employee_name,
                    "Coordinator", year, number, result["total_amount"], {
                        "total_visits": result.get("coordinated_visits"),
                        "invoice_value": sum(
                            v.get("invoice_value") or 0
                            for v in result.get("visitors") or [] if v.get("is_qualified")),
                        "is_qualified": result.get("total_amount", 0) > 0
                    }, is_payout_month))

    # Oldest month first, then employee, so the grid reads chronologically.
    rows.sort(key=lambda d: (d["_year"], d["_month_number"], d["employee"], d["component"]))
    for row in rows:
        row.pop("_year", None)
        row.pop("_month_number", None)

    return rows


def _settlement_row(paid_map, commission_type, user, employee, employee_name,
                    component, year, number, earned, result, is_payout_month=False):
    earned = round(flt(earned), CURRENCY_PRECISION)
    paid = round(flt(paid_map.get((user, component, year, number))), CURRENCY_PRECISION)
    delta = round(earned - paid, CURRENCY_PRECISION)

    if delta <= 0.004:
        return []

    invoice_value = flt(result.get("invoice_value"))
    month_label = "{0} {1}".format(MONTH_NAMES[number - 1], year)

    if is_payout_month:
        description = "This month's commission ({0})".format(month_label)
    elif paid > 0:
        description = "Balance for {0} - late invoices ({1} earned, {2} already paid)".format(
            month_label, earned, paid)
    else:
        description = "{0} commission - first settlement".format(month_label)

    return [{
        "description": description,
        "_year": year,
        "_month_number": number,
        "user": user,
        "employee": employee,
        "employee_name": employee_name,
        "component": component,
        "earned_month": MONTH_NAMES[number - 1],
        "earned_amount": earned,
        "previously_paid": paid,
        "amount": delta,
        "total_visits": cint(result.get("total_visits")),
        "invoiced_visits": cint(result.get("converted_visits")),
        "success_percent": flt(result.get("success_percent")),
        "invoice_value": round(invoice_value, CURRENCY_PRECISION),
        "commission_rate": round(earned / invoice_value * 100, 2) if invoice_value else 0,
        "qualified": 1 if result.get("is_qualified") else 0,
        "min_visits": cint(result.get("min_monthly_visits"))
    }]


def _get_paid_map(commission_type, user=None):
    """{(user, component, year, month_number): total already paid} from submitted payouts.

    The per-user filter keeps the PWA lookup constant-size as payout history grows;
    the settlement run omits it and reads everyone at once.
    """
    conditions = "p.commission_type = %(commission_type)s"

    if user:
        conditions += " AND d.user = %(user)s"

    rows = frappe.db.sql(
        """
        SELECT
            d.user, d.component, d.earned_month, d.amount,
            p.payout_month, p.posting_date
        FROM `tabCommission Payout Detail` d
        INNER JOIN `tabCommission Payout` p ON p.name = d.parent AND p.docstatus = 1
        WHERE {conditions}
        """.format(conditions=conditions),
        {"commission_type": commission_type, "user": user},
        as_dict=True
    )

    paid = {}

    for row in rows:
        if row.payout_month not in MONTH_NAMES or row.earned_month not in MONTH_NAMES:
            continue

        posting = getdate(row.posting_date)
        payout_number = MONTH_NAMES.index(row.payout_month) + 1
        payout_year = _resolve_year(payout_number, posting.month, posting.year)
        earned_number = MONTH_NAMES.index(row.earned_month) + 1
        earned_year = _resolve_year(earned_number, payout_number, payout_year)

        key = (row.user, row.component, earned_year, earned_number)
        paid[key] = flt(paid.get(key)) + flt(row.amount)

    return paid


def _get_active_employee(user):
    employee = frappe.db.get_value(
        "Employee", {"user_id": user, "status": "Active"},
        ["name", "employee_name"], as_dict=True)

    if not employee:
        frappe.throw(
            "No active Employee is linked to user {0}. "
            "Set User ID on their Employee record first.".format(user))

    return employee.name, employee.employee_name


def get_commission_users():
    settings = _get_settings_doc()
    users = []

    for row in settings.service_visit_staff_capacity:
        if row.get("user") and row.get("user") not in users:
            users.append(row.get("user"))

    return users


def get_orphaned_invoices(month=None):
    """Invoices for the month's visits that missed the cutoff and so count nowhere.

    These are silently dropped by the cohort model, so they are surfaced deliberately
    rather than left invisible.
    """
    from_date, to_date = get_month_range(month)
    cutoff_date = add_days(to_date, get_commission_settings()["invoice_cutoff_days"])

    return frappe.db.sql(
        """
        SELECT
            si.name AS sales_invoice,
            si.posting_date,
            si.base_net_total,
            si.is_return,
            sv.name AS service_visit,
            sv.date AS visit_date,
            sv.customer_name
        FROM `tabSales Invoice` si
        INNER JOIN `tabService Visit` sv ON sv.name = si.service_visit
        WHERE
            si.docstatus = 1
            AND sv.docstatus = 1
            AND sv.date BETWEEN %(from_date)s AND %(to_date)s
            AND si.posting_date > %(cutoff_date)s
        ORDER BY si.posting_date
        """,
        {"from_date": from_date, "to_date": to_date, "cutoff_date": cutoff_date},
        as_dict=True
    )


def get_month_invoice_map(visit_names, month=None, cutoff_date=None):
    """Invoice detail for a set of visits.

    Lets the combined "all visitors" view apply the same invoice window as the
    per-visitor commission figures, so the two never disagree about what counts.
    """
    if cutoff_date is None:
        from_date, to_date = get_month_range(month)
        cutoff_date = add_days(to_date, get_commission_settings()["invoice_cutoff_days"])

    return _get_invoice_map(visit_names, cutoff_date)


def _get_cohort_visits(user, from_date, to_date):
    if not user:
        return []

    return frappe.db.sql(
        """
        SELECT
            sv.name AS service_visit,
            sv.date AS visit_date,
            sv.customer_name,
            sv.type AS visit_type,
            sv.workflow_state
        FROM (
            SELECT DISTINCT parent, user
            FROM `tabWS User Assignment`
            WHERE
                parenttype = 'Service Visit'
                AND parentfield = 'assigned_users'
        ) ua
        INNER JOIN `tabService Visit` sv ON sv.name = ua.parent
        WHERE
            ua.user = %(user)s
            AND sv.docstatus = 1
            AND IFNULL(sv.workflow_state, '') != 'Cancelled'
            AND sv.date BETWEEN %(from_date)s AND %(to_date)s
            {direct_flag}
        ORDER BY sv.date, sv.name
        """.format(direct_flag=direct_flag_condition()),
        {"user": user, "from_date": from_date, "to_date": to_date},
        as_dict=True
    )


def _get_invoice_map(visit_names, cutoff_date):
    """Invoice totals per visit, counting only invoices posted on or before the cutoff."""
    visit_names = [d for d in (visit_names or []) if d]

    if not visit_names:
        return {}

    # Fetched per invoice rather than pre-aggregated, so each invoice can be shown with
    # its own value when a visit has more than one.
    # Commission is based on base_net_total: company currency, after item discounts and
    # EXCLUDING VAT. Confirmed with accounts - do not switch this to grand/rounded total,
    # which would pay commission on tax.
    rows = frappe.db.sql(
        """
        SELECT
            service_visit,
            name AS sales_invoice,
            posting_date,
            base_net_total AS net_total,
            IFNULL(is_return, 0) AS is_return
        FROM `tabSales Invoice`
        WHERE
            docstatus = 1
            AND service_visit IN %(visit_names)s
            AND posting_date <= %(cutoff_date)s
        ORDER BY posting_date, name
        """,
        {"visit_names": visit_names, "cutoff_date": cutoff_date},
        as_dict=True
    )

    invoice_map = {}

    for row in rows:
        entry = invoice_map.setdefault(row.get("service_visit"), {
            "net_value": 0.0,
            "normal_count": 0,
            "return_count": 0,
            "invoice_date": None,
            "invoices": []
        })

        is_return = cint(row.get("is_return"))
        entry["net_value"] += flt(row.get("net_total"))

        if is_return:
            entry["return_count"] += 1
        else:
            entry["normal_count"] += 1

        if entry["invoice_date"] is None:
            entry["invoice_date"] = row.get("posting_date")

        entry["invoices"].append({
            "sales_invoice": row.get("sales_invoice"),
            "posting_date": row.get("posting_date"),
            "net_total": flt(row.get("net_total")),
            "is_return": is_return
        })

    return invoice_map


def get_month_range(month=None):
    """'YYYY-MM' (or None for the current month) -> first and last date of that month."""
    month = (month or "")[:7] or nowdate()[:7]
    parts = month.split("-")

    if len(parts) != 2:
        frappe.throw("Invalid month.")

    try:
        year = int(parts[0])
        month_number = int(parts[1])
    except ValueError:
        frappe.throw("Invalid month.")

    if month_number < 1 or month_number > 12:
        frappe.throw("Invalid month.")

    from_date = date(year, month_number, 1)

    if month_number == 12:
        to_date = date(year, 12, 31)
    else:
        to_date = add_days(date(year, month_number + 1, 1), -1)

    return from_date, getdate(to_date)


def _has_column(doctype, fieldname):
    try:
        return frappe.db.has_column(doctype, fieldname)
    except Exception:
        return False


def direct_flag_condition():
    """SQL fragment excluding direct-quotation visits from visitor cohorts.

    A flagged visit lives ONLY in the coordinator's direct bucket - even when the
    coordinator has put their own name in Taken By (the accepted convention). Guarded so
    environments without the column (e.g. a clone before its field sync) keep working.
    """
    if _has_column("Service Visit", "is_direct_quotation"):
        return " AND IFNULL(sv.is_direct_quotation, 0) = 0"

    return ""
