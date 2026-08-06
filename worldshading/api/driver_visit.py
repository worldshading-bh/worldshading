import json
import os
import frappe
import telnetlib
import time
from datetime import date
from frappe.utils import cint, date_diff, flt, get_bench_path, get_datetime, getdate, now_datetime, nowdate
from frappe.utils.html_utils import sanitize_html
from worldshading.api.utility import merge_documents
from worldshading.api.service_visit_commission import (
    get_commission_result,
    get_coordinator_commission_result,
    get_month_invoice_map,
    get_paid_amounts
)
from worldshading.worldshading.report.employee_service_visit_performance.employee_service_visit_performance import get_summary_values
from worldshading.worldshading.report.employee_service_visit_performance.employee_service_visit_performance import get_visit_rows


try:
    from frappe.model.workflow import apply_workflow, get_transitions
except Exception:
    apply_workflow = None
    get_transitions = None


DRIVER_ACTIONS = {
    "start_visit": {
        "label": "Start Visit",
        "actions": ["Start Visit"],
        "comment_title": "Driver started the visit"
    },
    "complete_visit": {
        "label": "Complete Visit",
        "actions": ["Complete Visit"],
        "comment_title": "Completed the visit"
    },
    "request_reschedule": {
        "label": "Request Reschedule",
        "actions": ["Request Reschedule"],
        "comment_title": "Driver requested reschedule",
        "requires_note": 1
    },
    "mark_lost": {
        "label": "Mark Lost",
        "actions": ["Mark Lost", "Lost"],
        "comment_title": "Driver marked visit as lost",
        "requires_note": 1
    }
}


FOLLOWUP_QUOTATION_ACTIONS = {
    "send_quotation": {
        "label": "Send Quotation",
        "actions": ["Send Quotation"]
    },
    "call_client": {
        "label": "Call Client",
        "actions": ["Call Client"]
    },
    "lost": {
        "label": "Lost",
        "actions": ["Lost"]
    },
    "follow_up": {
        "label": "Follow-up",
        "actions": ["Follow-up"]
    },
    "request_payment": {
        "label": "Request Payment",
        "actions": ["Request Payment"]
    },
    "book_revisit": {
        "label": "Book Revisit",
        "actions": ["Book Revisit"]
    }
}

REVISIT_LOST_REASON = "Revisit Requested"

REVISIT_COPY_FIELDS = [
    "time",
    "customer", "customer_name", "customer_type", "cr_no", "first_name", "last_name",
    "mobile_number", "whatsapp_no", "email_id", "google_maps_link", "location_latitude",
    "location_longitude", "google_place_id", "location_address", "location_method",
    "project_name", "flat_no", "road_no", "building_no", "site_address", "block",
    "city", "country", "customer_address", "address_display", "contact_person",
    "type", "subject"
]


PBX_AMI_HOST = "109.63.116.44"
PBX_AMI_PORT = 7777
PBX_AMI_USERNAME = "erpnext_user"
PBX_AMI_PASSWORD = "WorldShading*123#"
PBX_AMI_EVENT_CAPTURE_SECONDS = 75
PBX_MIN_CUSTOMER_BILLABLE_SECONDS = 1


VISIT_FIELDS = [
    "name",
    "subject",
    "customer_name",
    "mobile_number",
    "whatsapp_no",
    "contact_person",
    "type",
    "date",
    "time",
    "city",
    "country",
    "workflow_state",
    "site_address",
    "flat_no",
    "road_no",
    "building_no",
    "block",
    "visit_notes",
    "reference_image",
    "visit_attachment",
    "reference_images_json"
]

OPTIONAL_VISIT_FIELDS = [
    "google_maps_link",
    "location_latitude",
    "location_longitude",
    "google_place_id",
    "location_address",
    "location_method"
]


@frappe.whitelist()
def get_driver_context():
    user = frappe.session.user
    full_name, user_image = frappe.db.get_value("User", user, ["full_name", "user_image"])
    visitor_id = _get_visitor_id_for_user(user)
    is_ceo = _is_ceo_user(user)

    return {
        "user": user,
        "full_name": full_name or user,
        "visitor_id": visitor_id,
        "user_image": user_image,
        "is_ceo": is_ceo,
        "visitor_options": _get_visitor_options() if is_ceo else []
    }


@frappe.whitelist()
def get_push_public_key():
    public_key = (frappe.conf.get("vapid_public_key") or "").strip()

    if not public_key:
        frappe.throw("Push notification public key is not configured.")

    return public_key


@frappe.whitelist()
def save_push_subscription(subscription=None):
    if frappe.session.user == "Guest":
        frappe.throw("Please login to enable notifications.")

    data = _parse_push_subscription(subscription)
    keys = data.get("keys") or {}
    endpoint = (data.get("endpoint") or "").strip()
    p256dh_key = (keys.get("p256dh") or "").strip()
    auth_key = (keys.get("auth") or "").strip()

    if not endpoint or not p256dh_key or not auth_key:
        frappe.throw("Push subscription details are incomplete.")

    existing = frappe.get_all(
        "PWA Push Subscription",
        filters={"endpoint": endpoint},
        fields=["name"],
        limit_page_length=1
    )

    if existing:
        doc = frappe.get_doc("PWA Push Subscription", existing[0].name)
    else:
        doc = frappe.new_doc("PWA Push Subscription")

    doc.set("user", frappe.session.user)
    doc.set("endpoint", endpoint)
    doc.set("p256dh_key", p256dh_key)
    doc.set("auth_key", auth_key)
    doc.set("enabled", 1)
    doc.set("last_seen", now_datetime())
    doc.save(ignore_permissions=True)

    return {
        "name": doc.name,
        "enabled": doc.get("enabled")
    }


@frappe.whitelist()
def disable_push_subscription(endpoint=None):
    if frappe.session.user == "Guest":
        frappe.throw("Please login to disable notifications.")

    endpoint = (endpoint or "").strip()

    if not endpoint:
        frappe.throw("Push subscription endpoint is required.")

    subscriptions = frappe.get_all(
        "PWA Push Subscription",
        filters={
            "endpoint": endpoint,
            "user": frappe.session.user
        },
        fields=["name"],
        limit_page_length=5
    )

    for subscription in subscriptions:
        frappe.db.set_value("PWA Push Subscription", subscription.name, {
            "enabled": 0,
            "last_seen": now_datetime()
        })

    return {
        "disabled": len(subscriptions)
    }


@frappe.whitelist()
def send_test_push():
    if frappe.session.user == "Guest":
        frappe.throw("Please login to send a test notification.")

    result = send_push_to_user(
        frappe.session.user,
        "World Shading",
        "Test notification from Visitor PWA.",
        "/driver-visits",
        "worldshading-test-push"
    )

    if not result.get("total"):
        frappe.throw("No enabled push subscription found for your user.")

    if not result.get("sent"):
        frappe.throw(result.get("last_error") or "Push notification could not be sent.")

    return {
        "sent": result.get("sent"),
        "total": result.get("total")
    }


@frappe.whitelist()
def get_my_visits(visit_date=None, from_date=None, to_date=None, workflow_state=None, search=None, limit=20, start=0, visitor=None):
    from_date = from_date or visit_date
    to_date = to_date or from_date
    workflow_state = (workflow_state or "").strip()

    if from_date and to_date and getdate(from_date) > getdate(to_date):
        from_date, to_date = to_date, from_date

    limit = _safe_int(limit, 20, 1, 100)
    start = _safe_int(start, 0, 0, 100000)
    user = _get_effective_visitor_user(visitor)
    fields = _get_visit_select_fields()
    time_order = _get_time_order_sql()
    conditions = [
        "sv.docstatus = 1",
        "IFNULL(sv.workflow_state, '') != 'Cancelled'"
    ]
    params = {
        "user": user,
        "from_date": from_date,
        "to_date": to_date,
        "workflow_state": workflow_state,
        "search": "%{0}%".format((search or "").strip()),
        "limit": limit,
        "start": start
    }

    if user:
        conditions.append("ua.user = %(user)s")

    if from_date and to_date:
        conditions.append("DATE(sv.date) BETWEEN %(from_date)s AND %(to_date)s")
    elif from_date:
        conditions.append("DATE(sv.date) >= %(from_date)s")
    elif to_date:
        conditions.append("DATE(sv.date) <= %(to_date)s")

    if (search or "").strip():
        conditions.append("""(
            sv.name LIKE %(search)s
            OR IFNULL(sv.customer_name, '') LIKE %(search)s
            OR IFNULL(sv.mobile_number, '') LIKE %(search)s
            OR IFNULL(sv.whatsapp_no, '') LIKE %(search)s
        )""")

    base_where = " AND ".join(conditions)
    list_where = base_where
    count_expression = "COUNT(*)" if user else "COUNT(DISTINCT sv.name)"
    select_distinct = "" if user else "DISTINCT"

    if workflow_state:
        list_where += " AND IFNULL(sv.workflow_state, '') = %(workflow_state)s"

    visits = frappe.db.sql("""
        SELECT {select_distinct}
            {fields}
        FROM `tabService Visit` sv
        INNER JOIN `tabWS User Assignment` ua
            ON ua.parent = sv.name
            AND ua.parenttype = 'Service Visit'
        WHERE {list_where}
        ORDER BY sv.date ASC, {time_order}, sv.name ASC
        LIMIT %(start)s, %(limit)s
    """.format(select_distinct=select_distinct, fields=fields, list_where=list_where, time_order=time_order), params, as_dict=True)

    total_count = frappe.db.sql("""
        SELECT {count_expression}
        FROM `tabService Visit` sv
        INNER JOIN `tabWS User Assignment` ua
            ON ua.parent = sv.name
            AND ua.parenttype = 'Service Visit'
        WHERE {list_where}
    """.format(count_expression=count_expression, list_where=list_where), params)[0][0]

    state_counts = frappe.db.sql("""
        SELECT IFNULL(sv.workflow_state, '') AS workflow_state, {count_expression} AS count
        FROM `tabService Visit` sv
        INNER JOIN `tabWS User Assignment` ua
            ON ua.parent = sv.name
            AND ua.parenttype = 'Service Visit'
        WHERE {base_where}
        GROUP BY IFNULL(sv.workflow_state, '')
    """.format(count_expression=count_expression, base_where=base_where), params, as_dict=True)

    return {
        "visits": visits,
        "total_count": total_count,
        "state_counts": _rows_to_count_map(state_counts, "workflow_state"),
        "has_more": (start + len(visits)) < total_count,
        "start": start,
        "limit": limit
    }


@frappe.whitelist()
def get_visit_details(name):
    doc = _get_allowed_visit(name, allow_ceo=True)
    data = _visit_to_dict(doc)
    data["can_update"] = _can_update_visit(doc.name)
    data["comments"] = _get_comments("Service Visit", doc.name)
    data["images"] = _get_visit_images(doc)
    data["available_actions"] = _get_driver_actions(doc) if _can_update_visit(doc.name) else []
    data["assigned_users"] = _get_assigned_users(doc)
    return data


@frappe.whitelist()
def add_visit_comment(name, content):
    doc = _get_allowed_visit(name, allow_ceo=True)
    content = (content or "").strip()

    if not content:
        frappe.throw("Comment is required.")

    _add_comment("Service Visit", doc.name, content)
    return _get_comments("Service Visit", doc.name)


@frappe.whitelist()
def add_followup_quotation_comment(name, content):
    doc = _get_allowed_followup_quotation(name, allow_ceo=True)
    content = (content or "").strip()

    if not content:
        frappe.throw("Comment is required.")

    _add_comment("Quotation", doc.name, sanitize_html(content))
    return _get_comments("Quotation", doc.name)


@frappe.whitelist()
def attach_visit_files(name, file_names=None):
    doc = _get_allowed_visit(name, allow_ceo=True)
    _attach_uploaded_files(doc, file_names)
    return get_visit_details(doc.name)


@frappe.whitelist()
def update_visit_location_link(name, google_maps_link=None):
    doc = _get_allowed_visit(name, allow_ceo=True)
    google_maps_link = (google_maps_link or "").strip()

    if not _doctype_has_field("Service Visit", "google_maps_link"):
        frappe.throw("Google Maps link field is not available.")

    if not google_maps_link:
        frappe.throw("Google Maps link is required.")

    if not _is_valid_maps_link(google_maps_link):
        frappe.throw("Please enter a valid Google Maps link.")

    doc.db_set("google_maps_link", google_maps_link, update_modified=True)
    _add_comment(
        "Service Visit",
        doc.name,
        "Location link updated from Driver PWA."
    )

    return get_visit_details(doc.name)


@frappe.whitelist()
def start_service_visit_pbx_call(name, phone=None):
    doc = _get_allowed_visit(name, allow_ceo=True)
    pbx_result = _start_service_visit_pbx_call(doc, phone)
    pbx_result["workflow_applied"] = "No"

    _add_comment(
        "Service Visit",
        doc.name,
        _format_pbx_call_comment(pbx_result)
    )

    return get_visit_details(doc.name)


@frappe.whitelist()
def apply_driver_action(name, action_key, note=None, file_names=None):
    if apply_workflow is None:
        frappe.throw("Workflow API is not available.")

    doc = _get_allowed_visit(name, allow_ceo=True)
    action = _get_workflow_action(doc, action_key)
    config = DRIVER_ACTIONS.get(action_key)

    if not config:
        frappe.throw("Invalid driver action.")

    note = (note or "").strip()

    if config.get("requires_note") and not note:
        frappe.throw("Notes are required for this action.")

    attached_files = _attach_uploaded_files(doc, file_names)

    if action_key == "complete_visit":
        if not attached_files:
            frappe.throw("Please upload at least one file.")

        attached_files = _merge_completion_files(doc, attached_files)

    if note or attached_files:
        content = "<b>{0}</b>".format(config.get("comment_title"))

        if note:
            content += "<br><br>{0}".format(sanitize_html(note))

        if attached_files:
            attachment_title = "Completion Report" if action_key == "complete_visit" else "Attached Images"
            links = []
            for file_doc in attached_files:
                links.append('<a href="{0}" target="_blank">{1}</a>'.format(
                    file_doc.file_url,
                    file_doc.file_name or file_doc.name
                ))
            content += "<br><br><b>{0}:</b><br>{1}".format(
                attachment_title,
                "<br>".join(links)
            )

        _add_comment("Service Visit", doc.name, content)

    doc = apply_workflow(doc, action)

    return get_visit_details(doc.name)


@frappe.whitelist()
def get_filter_options(visit_date=None):
    visits = get_my_visits(visit_date)
    return {
        "workflow_states": sorted(list(set([d.workflow_state for d in visits if d.workflow_state]))),
        "cities": sorted(list(set([d.city for d in visits if d.city]))),
        "visit_types": sorted(list(set([d.type for d in visits if d.type])))
    }


@frappe.whitelist()
def get_driver_monthly_insights(month=None, visitor=None):
    from_date, to_date = _get_month_date_range(month)
    user = _get_effective_visitor_user(visitor)
    filters = {
        "from_date": from_date,
        "to_date": to_date,
        "user": user
    }
    rows = get_visit_rows(filters)

    # get_visit_rows returns one row per (assigned user x visit) because the report it
    # backs is per-employee. Without a user filter that double counts every visit taken
    # by two people, so collapse to distinct visits for the combined view.
    if not user:
        rows = _dedupe_visit_rows(rows)

    summary = get_summary_values(rows, filters)

    # Money figures come from the commission engine, valued on everything invoiced to
    # date (no cutoff) - the same basis the Commission Payout settles on, so the PWA and
    # the payout always tell one story. Commission is per-visitor, so the CEO's combined
    # "All visitors" view keeps the report totals and simply shows no commission.
    today = getdate(nowdate())
    commission = get_commission_result(user, month, cutoff_date=today) if user else None
    # Only populated for a staff row whose role is Coordinator; everyone else gets None
    # and the PWA simply doesn't render the card. The "All visitors" view has no single
    # coordinator, so it gets None too.
    coordinator = get_coordinator_commission_result(
        user, month, cutoff_date=today) if user else None

    if coordinator and not coordinator.get("is_coordinator"):
        coordinator = None

    if user and (commission or coordinator):
        _attach_settlement(user, commission, coordinator, today)

    if commission:
        total_visits = commission.get("total_visits") or 0
        invoiced_visits = commission.get("converted_visits") or 0
        success_percent = commission.get("success_percent") or 0
        invoice_value = commission.get("invoice_value") or 0
        visit_list = commission.get("visit_list") or []
    else:
        invoice_map = get_month_invoice_map(
            [d.get("service_visit") for d in rows], month, cutoff_date=today)
        visit_list = _build_visit_list(rows, invoice_map)
        total_visits = len(rows)
        invoiced_visits = len([d for d in visit_list if d.get("is_invoiced")])
        invoice_value = max(sum([flt(d.get("invoice_net_total")) for d in visit_list]), 0)
        success_percent = round((float(invoiced_visits) / float(total_visits)) * 100, 2) if total_visits else 0

    return {
        "month": month,
        "from_date": from_date,
        "to_date": to_date,
        "total_visits": total_visits,
        "invoiced_visits": invoiced_visits,
        "success_percent": success_percent,
        "invoice_value": invoice_value,
        "avg_visits_per_day": summary.get("avg_visits_per_working_day") or 0,
        "pending_quotation_count": summary.get("pending_quotation_count") or 0,
        "quotation_created_count": summary.get("quotation_created_count") or 0,
        "ordered_count": summary.get("ordered_count") or 0,
        "lost_count": summary.get("lost_count") or 0,
        "expired_count": summary.get("expired_count") or 0,
        "commission": commission,
        "coordinator": coordinator,
        "visit_list": visit_list,
        "currency": frappe.defaults.get_global_default("currency") or "BHD"
    }


@frappe.whitelist()
def get_my_followup_quotations(workflow_state=None, search=None, from_date=None, to_date=None, limit=20, start=0, visitor=None):
    workflow_state = (workflow_state or "").strip()

    if from_date and to_date and getdate(from_date) > getdate(to_date):
        from_date, to_date = to_date, from_date

    limit = _safe_int(limit, 20, 1, 100)
    start = _safe_int(start, 0, 0, 100000)
    user = _get_effective_visitor_user(visitor)
    fields = _get_quotation_list_fields()
    conditions = [
        "follow_up_mode = %(follow_up_mode)s",
        "docstatus != 2",
        "IFNULL(status, '') != 'Cancelled'",
        "IFNULL(workflow_state, '') != 'Cancelled'"
    ]
    params = {
        "follow_up_mode": "Visitor",
        "user": user,
        "workflow_state": workflow_state,
        "from_date": from_date,
        "to_date": to_date,
        "search": "%{0}%".format((search or "").strip()),
        "limit": limit,
        "start": start
    }

    if user:
        conditions.append("visitor = %(user)s")

    if from_date and to_date:
        conditions.append("DATE(transaction_date) BETWEEN %(from_date)s AND %(to_date)s")
    elif from_date:
        conditions.append("DATE(transaction_date) >= %(from_date)s")
    elif to_date:
        conditions.append("DATE(transaction_date) <= %(to_date)s")

    if (search or "").strip():
        search_fields = ["name", "customer_name", "party_name"]

        for optional_field in ["service_visit", "mobile_number", "whatsapp_no", "contact_mobile"]:
            if _doctype_has_field("Quotation", optional_field):
                search_fields.append(optional_field)

        conditions.append("(" + " OR ".join(["IFNULL({0}, '') LIKE %(search)s".format(field) for field in search_fields]) + ")")

    base_where = " AND ".join(conditions)
    list_where = base_where

    if workflow_state:
        list_where += " AND IFNULL(workflow_state, '') = %(workflow_state)s"

    quotations = frappe.db.sql("""
        SELECT {fields}
        FROM `tabQuotation`
        WHERE {list_where}
        ORDER BY transaction_date DESC, modified DESC
        LIMIT %(start)s, %(limit)s
    """.format(fields=", ".join(fields), list_where=list_where), params, as_dict=True)

    total_count = frappe.db.sql("""
        SELECT COUNT(*)
        FROM `tabQuotation`
        WHERE {list_where}
    """.format(list_where=list_where), params)[0][0]

    state_counts = frappe.db.sql("""
        SELECT IFNULL(workflow_state, status) AS workflow_state, COUNT(*) AS count
        FROM `tabQuotation`
        WHERE {base_where}
        GROUP BY IFNULL(workflow_state, status)
    """.format(base_where=base_where), params, as_dict=True)

    return {
        "quotations": [_quotation_to_summary(row, include_actions=True) for row in quotations],
        "total_count": total_count,
        "state_counts": _rows_to_count_map(state_counts, "workflow_state"),
        "has_more": (start + len(quotations)) < total_count,
        "start": start,
        "limit": limit
    }


@frappe.whitelist()
def get_followup_quotation_details(name):
    doc = _get_allowed_followup_quotation(name, allow_ceo=True)
    data = _quotation_doc_to_dict(doc)
    data["items"] = _get_quotation_items(doc)
    data["comments"] = _get_comments("Quotation", doc.name)
    data["available_actions"] = _get_followup_quotation_actions(doc) if _can_update_followup_quotation(doc) else []
    return data


@frappe.whitelist()
def start_followup_quotation_pbx_call(name, phone=None):
    doc = _get_allowed_followup_quotation(name, allow_ceo=True)
    pbx_result = _start_followup_pbx_call(doc)
    pbx_result["workflow_applied"] = "No"

    _add_comment(
        "Quotation",
        doc.name,
        _format_pbx_call_comment(pbx_result)
    )

    return get_followup_quotation_details(doc.name)


@frappe.whitelist()
def get_quotation_lost_reasons():
    return frappe.get_all(
        "Quotation Lost Reason",
        fields=["name", "order_lost_reason"],
        order_by="order_lost_reason asc"
    )


@frappe.whitelist()
def apply_followup_quotation_action(name, action_key, note=None, transition_date=None, lost_reason=None, already_called_customer=None):
    if apply_workflow is None:
        frappe.throw("Workflow API is not available.")

    doc = _get_allowed_followup_quotation(name, allow_ceo=True)
    action = _get_followup_quotation_workflow_action(doc, action_key)
    config = FOLLOWUP_QUOTATION_ACTIONS.get(action_key)
    note = (note or "").strip()
    transition_date = (transition_date or "").strip()
    lost_reason = (lost_reason or "").strip()

    if not config:
        frappe.throw("Invalid quotation action.")

    if action_key == "call_client":
        if str(already_called_customer or "").lower() in ("1", "true", "yes"):
            if not note:
                frappe.throw("Comment is required when customer was already called.")

            _add_comment(
                "Quotation",
                doc.name,
                "<b>{0}</b><br><br>Customer already called manually.{1}".format(
                    config.get("label"),
                    "<br><br>{0}".format(sanitize_html(note)) if note else ""
                )
            )
            apply_workflow(doc, action)
            return get_followup_quotation_details(doc.name)

        pbx_result = _start_followup_pbx_call(doc)

        if note:
            _add_comment(
                "Quotation",
                doc.name,
                "<b>{0}</b><br><br>{1}".format(
                    config.get("label"),
                    sanitize_html(note)
                )
            )

        if _pbx_call_can_apply_workflow(pbx_result):
            apply_workflow(doc, action)
            pbx_result["workflow_applied"] = "Yes"
        else:
            pbx_result["workflow_applied"] = "No"

        _add_comment(
            "Quotation",
            doc.name,
            _format_pbx_call_comment(pbx_result)
        )

        return get_followup_quotation_details(doc.name)

    if action_key == "follow_up":
        if not transition_date:
            frappe.throw("Next follow-up date is required.")

        if not _doctype_has_field("Quotation", "transition_date"):
            frappe.throw("Quotation transition date field is not available.")

        doc.set("transition_date", get_datetime(transition_date.replace("T", " ")))
        doc.save(ignore_permissions=True)

    revisit_visit = None

    if action_key == "book_revisit":
        if not note:
            frappe.throw("Comment is required - explain why a revisit is needed.")

        revisit_visit = _create_revisit_service_visit(doc, note)
        reason_name = frappe.db.get_value(
            "Quotation Lost Reason", {"order_lost_reason": REVISIT_LOST_REASON}) \
            or frappe.db.get_value("Quotation Lost Reason", REVISIT_LOST_REASON)

        # status=Lost (not just the workflow state) makes the quotation invisible to
        # both expiry schedulers forever. status is not editable after submit, so it
        # moves via db_set like every other server-side transition, and the existing
        # sync is invoked directly to walk the original Service Visit to Lost.
        doc.db_set("status", "Lost")

        if reason_name:
            _set_quotation_lost_details(doc, reason_name, note)

        from worldshading.events.service_visit_link import sync_quotation_status_to_visit
        sync_quotation_status_to_visit(doc)

        _add_comment(
            "Quotation",
            doc.name,
            "<b>Book Revisit</b><br><br>New visit <b>{0}</b> created in Pending Schedule."
            "<br><br>{1}".format(revisit_visit, sanitize_html(note))
        )
        note = ""

    if action_key == "lost":
        if not lost_reason:
            frappe.throw("Lost reason is required.")

        reason_label = _set_quotation_lost_details(doc, lost_reason, note)
        _add_comment(
            "Quotation",
            doc.name,
            "<b>{0}</b><br><br>Reason: {1}{2}".format(
                config.get("label"),
                sanitize_html(reason_label),
                "<br><br>{0}".format(sanitize_html(note)) if note else ""
            )
        )
        note = ""

    if note:
        _add_comment(
            "Quotation",
            doc.name,
            "<b>{0}</b><br><br>{1}".format(
                config.get("label"),
                sanitize_html(note)
            )
        )

    apply_workflow(doc, action)

    result = get_followup_quotation_details(doc.name)

    if revisit_visit:
        result["revisit_visit"] = revisit_visit

    return result


def _create_revisit_service_visit(quotation, note):
    """Clone the quotation's original visit into a fresh Pending Schedule draft.

    Mirrors the web-form entry shape (draft, Pending Schedule, no Taken By, no
    coordinator) so it flows through the coordinator's normal scheduling pipeline and
    the actor-based stamping credits whoever schedules it.
    """
    if not quotation.get("service_visit"):
        frappe.throw("This quotation has no linked Service Visit to revisit.")

    existing = frappe.db.get_value("Service Visit", {
        "parent_service_visit": quotation.service_visit,
        "is_follow_up": 1,
        "docstatus": ["<", 2],
        "workflow_state": "Pending Schedule"
    })

    if existing:
        frappe.throw("Revisit {0} is already waiting to be scheduled for this visit.".format(existing))

    original = frappe.get_doc("Service Visit", quotation.service_visit)
    revisit = frappe.new_doc("Service Visit")

    for fieldname in REVISIT_COPY_FIELDS:
        if revisit.meta.has_field(fieldname) and original.get(fieldname):
            revisit.set(fieldname, original.get(fieldname))

    revisit.is_follow_up = 1
    revisit.parent_service_visit = original.name
    revisit.date = nowdate()

    if revisit.meta.has_field("source"):
        revisit.source = "ERP"

    revisit.insert(ignore_permissions=True)
    # The workflow engine refuses Draft -> Pending Schedule as a document edit, so move
    # the state the same way every other server-side transition in this app does.
    revisit.db_set("workflow_state", "Pending Schedule")

    _add_comment(
        "Service Visit",
        revisit.name,
        "<b>Revisit</b> of {0}, booked from Quotation <b>{1}</b>.<br><br>{2}".format(
            original.name, quotation.name, sanitize_html(note))
    )

    return revisit.name


def _set_quotation_lost_details(doc, lost_reason, note):
    reason_label = frappe.db.get_value("Quotation Lost Reason", lost_reason, "order_lost_reason")

    if not reason_label:
        frappe.throw("Please choose a valid lost reason.")

    if _doctype_has_field("Quotation", "order_lost_reason") and note:
        doc.set("order_lost_reason", note)

    if _doctype_has_field("Quotation", "lost_reasons"):
        doc.append("lost_reasons", {"lost_reason": lost_reason})

    doc.save(ignore_permissions=True)
    return reason_label


def _start_followup_pbx_call(doc):
    extension = _get_current_visitor_extension()
    customer_number = _get_followup_customer_call_number(doc)

    try:
        result = _originate_pbx_call(extension, customer_number)
    except Exception:
        frappe.log_error(frappe.get_traceback(), "Driver PWA PBX call failed")
        frappe.throw("Could not start the PBX call.")

    result["extension"] = extension
    result["customer_number"] = customer_number
    return result


def _start_service_visit_pbx_call(doc, phone=None):
    extension = _get_current_visitor_extension()
    customer_number = _get_service_visit_customer_call_number(doc, phone)

    try:
        result = _originate_pbx_call(extension, customer_number)
    except Exception:
        frappe.log_error(frappe.get_traceback(), "Driver PWA Service Visit PBX call failed")
        frappe.throw("Could not start the PBX call.")

    result["extension"] = extension
    result["customer_number"] = customer_number
    return result


def _get_current_visitor_extension():
    visitor_id = _get_visitor_id_for_user(frappe.session.user)

    if visitor_id:
        return visitor_id

    frappe.throw("Visitor extension is not configured in WS Settings.")


def _parse_push_subscription(subscription):
    if isinstance(subscription, dict):
        return subscription

    if not subscription:
        return {}

    return frappe.parse_json(subscription)


def send_push_to_user(user, title, body, url=None, tag=None):
    subscriptions = frappe.get_all(
        "PWA Push Subscription",
        filters={
            "user": user,
            "enabled": 1
        },
        fields=["name", "endpoint", "p256dh_key", "auth_key"],
        limit_page_length=100
    )

    sent = 0
    last_error = ""

    for subscription in subscriptions:
        result = _send_push_subscription(subscription, title, body, url, tag)

        if result.get("ok"):
            sent += 1
        elif result.get("error"):
            last_error = result.get("error")

    return {
        "sent": sent,
        "total": len(subscriptions),
        "last_error": last_error
    }


def _send_push_subscription(subscription, title, body, url=None, tag=None):
    try:
        from pywebpush import WebPushException, webpush
    except Exception:
        frappe.log_error(frappe.get_traceback(), "Web Push library unavailable")
        frappe.throw("Web Push library is not available.")

    private_key_path = _get_vapid_private_key_path()
    subject = (frappe.conf.get("vapid_claims_sub") or "mailto:info@worldshading.com").strip()
    payload = {
        "title": title or "World Shading",
        "body": body or "",
        "url": url or "/driver-visits",
        "tag": tag or "worldshading"
    }
    subscription_info = {
        "endpoint": subscription.endpoint,
        "keys": {
            "p256dh": subscription.p256dh_key,
            "auth": subscription.auth_key
        }
    }

    try:
        webpush(
            subscription_info=subscription_info,
            data=json.dumps(payload),
            vapid_private_key=private_key_path,
            vapid_claims={"sub": subject}
        )
        return {"ok": True}
    except WebPushException as ex:
        status_code = getattr(getattr(ex, "response", None), "status_code", None)
        error = "Push send failed"

        if status_code in [404, 410]:
            frappe.db.set_value("PWA Push Subscription", subscription.name, "enabled", 0)
            error = "Push subscription expired. Please enable notifications again."
        elif status_code:
            error = "Push service rejected the notification. Status: {0}".format(status_code)
        else:
            error = str(ex) or error

        frappe.log_error(
            "Subscription: {0}\nStatus: {1}\nError: {2}".format(
                subscription.name,
                status_code,
                str(ex)
            ),
            "PWA Push Notification Failed"
        )
        return {
            "ok": False,
            "error": error
        }
    except Exception:
        error = frappe.get_traceback()
        frappe.log_error(error, "PWA Push Notification Failed")
        return {
            "ok": False,
            "error": "Push send failed. Please check Error Log."
        }


def _get_vapid_private_key_path():
    private_key_path = (frappe.conf.get("vapid_private_key_path") or "").strip()

    if not private_key_path:
        frappe.throw("Push notification private key is not configured.")

    candidates = []

    if os.path.isabs(private_key_path):
        candidates.append(private_key_path)
    else:
        candidates.append(os.path.join(get_bench_path(), private_key_path))
        candidates.append(frappe.get_site_path(private_key_path))

        site_prefix = "sites/{0}/".format(frappe.local.site)
        if private_key_path.startswith(site_prefix):
            candidates.append(frappe.get_site_path(private_key_path[len(site_prefix):]))

    for path in candidates:
        if path and os.path.isfile(path):
            return path

    frappe.throw("Push notification private key file was not found.")


def _get_driver_admin_role():
    """The role that may view every visitor's visits, from WS Settings.
    Falls back to "CEO" (the previous hardcoded value) if unset."""
    try:
        role = frappe.db.get_single_value("WS Settings", "drivers_visit_admin")
    except Exception:
        role = None
    return (role or "").strip() or "CEO"


def _is_ceo_user(user=None):
    user = user or frappe.session.user
    return _get_driver_admin_role() in frappe.get_roles(user)


def _get_effective_visitor_user(visitor=None):
    visitor = (visitor or "").strip()

    if _is_ceo_user() and visitor == "__all__":
        return None

    if _is_ceo_user() and visitor:
        if not frappe.db.exists("User", visitor):
            frappe.throw("Please choose a valid visitor.")

        return visitor

    return frappe.session.user


def _get_visitor_options():
    users = []
    seen = {}

    settings = frappe.get_single("WS Settings")

    for row in settings.service_visit_staff_capacity:
        user = row.get("user")

        if not user or not row.get("active") or seen.get(user):
            continue

        full_name, user_image = frappe.db.get_value("User", user, ["full_name", "user_image"]) or (None, None)
        users.append({
            "user": user,
            "full_name": full_name or user,
            "visitor_id": str(row.get("visitor_id") or "").strip(),
            "user_image": user_image
        })
        seen[user] = 1

    current_user = frappe.session.user

    if not seen.get(current_user):
        full_name, user_image = frappe.db.get_value("User", current_user, ["full_name", "user_image"]) or (None, None)
        users.append({
            "user": current_user,
            "full_name": full_name or current_user,
            "visitor_id": _get_visitor_id_for_user(current_user),
            "user_image": user_image
        })

    return sorted(users, key=lambda row: (row.get("full_name") or row.get("user") or "").lower())


def _get_visitor_id_for_user(user):
    settings = frappe.get_single("WS Settings")

    for row in settings.service_visit_staff_capacity:
        if row.get("user") == user and row.get("active") and row.get("visitor_id"):
            return str(row.get("visitor_id")).strip()

    return ""


def _get_followup_customer_call_number(doc):
    number = _get_quotation_phone(doc) or _get_quotation_whatsapp(doc)
    number = _normalize_pbx_phone_number(number)

    if not number:
        frappe.throw("Customer phone number is not available for this quotation.")

    return number


def _get_service_visit_customer_call_number(doc, phone=None):
    allowed_numbers = [
        _normalize_pbx_phone_number(doc.get("mobile_number")),
        _normalize_pbx_phone_number(doc.get("whatsapp_no"))
    ]
    allowed_numbers = [number for number in allowed_numbers if number]
    number = _normalize_pbx_phone_number(phone) if phone else ""

    if not number:
        number = allowed_numbers[0] if allowed_numbers else ""

    if not number:
        frappe.throw("Customer phone number is not available for this service visit.")

    if number not in allowed_numbers:
        frappe.throw("Selected phone number is not available for this service visit.")

    return number


def _normalize_pbx_phone_number(number):
    digits = "".join([ch for ch in str(number or "") if ch.isdigit()])

    if digits.startswith("00"):
        digits = digits[2:]

    if digits.startswith("973") and len(digits) == 11:
        digits = digits[-8:]

    return digits


def _originate_pbx_call(extension, customer_number):
    tn = None
    action_id = "WS-{0}-{1}".format(extension, int(time.time()))
    started_at = time.time()

    try:
        tn = telnetlib.Telnet(PBX_AMI_HOST, PBX_AMI_PORT, timeout=10)
        tn.read_until(b"\n", timeout=5)

        login = """Action: Login
Username: {0}
Secret: {1}
Events: on

""".format(PBX_AMI_USERNAME, PBX_AMI_PASSWORD)
        tn.write(login.encode())
        login_raw, login_response = _read_ami_message(tn, timeout=5)

        if login_response.get("Response") != "Success":
            frappe.throw("PBX login failed.")

        originate = """Action: Originate
ActionID: {2}
Channel: PJSIP/{0}
Context: from-internal
Exten: {1}
Priority: 1
CallerID: World Shading <{0}>
Async: true

""".format(extension, customer_number, action_id)
        tn.write(originate.encode())

        return _track_pbx_call(tn, action_id, extension, customer_number, started_at)
    finally:
        if tn:
            try:
                tn.write(b"Action: Logoff\r\n\r\n")
                tn.close()
            except Exception:
                pass


def _read_ami_message(tn, timeout=2):
    try:
        raw = tn.read_until(b"\r\n\r\n", timeout=timeout).decode(errors="ignore")
    except EOFError:
        return "", {"_eof": 1}

    return raw, _parse_ami_message(raw)


def _parse_ami_message(raw):
    data = {}

    for line in (raw or "").splitlines():
        if ":" not in line:
            continue

        key, value = line.split(":", 1)
        data[key.strip()] = value.strip()

    return data


def _track_pbx_call(tn, action_id, extension, customer_number, started_at):
    result = {
        "action_id": action_id,
        "extension": extension,
        "customer_number": customer_number,
        "originate_response": "Not captured",
        "visitor_answered": "No",
        "customer_answered": "No",
        "final_status": "No Answer / Unknown",
        "duration_seconds": 0,
        "billable_seconds": 0,
        "cdr_disposition": None,
        "cdr_captured": "No",
        "hangup_cause": None,
        "customer_answer_source": None,
        "events": []
    }
    customer_answered_at = None
    ended_at = None
    listen_until = time.time() + PBX_AMI_EVENT_CAPTURE_SECONDS

    while time.time() < listen_until:
        raw, event = _read_ami_message(tn, timeout=2)

        if event.get("_eof"):
            result["hangup_cause"] = result.get("hangup_cause") or "AMI connection closed"
            break

        if not event:
            continue

        event_name = event.get("Event") or event.get("Response") or "Unknown"

        if _is_pbx_important_event(event_name, event):
            _append_pbx_event(result["events"], event_name, event)

        if event.get("Response") in ("Success", "Error") and event.get("ActionID") == action_id:
            result["originate_response"] = event.get("Response")

            if event.get("Response") == "Error":
                result["final_status"] = event.get("Message") or "Originate Failed"
                break

        if event_name == "OriginateResponse" and event.get("ActionID") == action_id:
            if event.get("Response") == "Failure":
                result["final_status"] = event.get("Reason") or "Originate Failed"
                break

        if event_name in ("Dial", "DialEnd"):
            dial_status = event.get("DialStatus")

            if dial_status and _event_mentions_extension(event, extension):
                if str(dial_status).upper() in ("ANSWER", "ANSWERED"):
                    result["visitor_answered"] = "Yes"

            if dial_status and _event_mentions_customer_leg(event, customer_number):
                result["final_status"] = dial_status

                if _is_customer_answer_event(event, customer_number, extension):
                    result["customer_answered"] = "Yes"
                    result["final_status"] = "Answered"
                    result["customer_answer_source"] = "DialEnd"

                    if not customer_answered_at:
                        customer_answered_at = time.time()

        if event_name == "Cdr" and _is_customer_cdr(event, customer_number):
            _apply_customer_cdr_result(result, event)
            break

        if event_name == "Hangup":
            if _event_mentions_customer_leg(event, customer_number) or result["customer_answered"] == "Yes":
                result["hangup_cause"] = event.get("Cause-txt") or event.get("Cause")
                ended_at = time.time()
                _drain_pbx_events(tn, result, customer_number)
                break

    if not ended_at:
        ended_at = time.time()

    if not result["duration_seconds"]:
        result["duration_seconds"] = int(ended_at - started_at)

    if result.get("cdr_captured") != "Yes" and not result["billable_seconds"] and customer_answered_at:
        result["billable_seconds"] = int(ended_at - customer_answered_at)

    if result.get("cdr_captured") != "Yes" and result["customer_answered"] == "Yes":
        result["final_status"] = "Awaiting final CDR"

    return result


def _drain_pbx_events(tn, result, customer_number):
    listen_until = time.time() + 8

    while time.time() < listen_until:
        raw, event = _read_ami_message(tn, timeout=1)

        if event.get("_eof"):
            break

        if not event:
            break

        event_name = event.get("Event") or event.get("Response") or "Unknown"

        if _is_pbx_important_event(event_name, event):
            _append_pbx_event(result["events"], event_name, event)

        if event_name == "Cdr" and _is_customer_cdr(event, customer_number):
            _apply_customer_cdr_result(result, event)
            return


def _is_pbx_important_event(event_name, event):
    if event_name in ("OriginateResponse", "Dial", "DialEnd", "BridgeEnter", "BridgeCreate", "Hangup", "Cdr"):
        return True

    if event.get("Response") in ("Success", "Error"):
        return True

    return False


def _append_pbx_event(events, event_name, event):
    if len(events) >= 12:
        return

    compact = {
        "event": event_name,
        "status": event.get("DialStatus") or event.get("Response") or event.get("Disposition"),
        "channel": event.get("Channel"),
        "dest_channel": event.get("DestChannel"),
        "exten": event.get("Exten"),
        "dial_string": event.get("DialString"),
        "caller": event.get("CallerIDNum"),
        "connected": event.get("ConnectedLineNum"),
        "cause": event.get("Cause-txt") or event.get("Cause")
    }
    events.append(compact)


def _event_mentions_extension(event, extension):
    return _event_mentions_digits(event, extension)


def _event_mentions_customer(event, customer_number):
    return _event_mentions_digits(event, customer_number)


def _event_mentions_customer_leg(event, customer_number):
    return _event_mentions_digits_in_fields(event, customer_number, [
        "Channel",
        "DestChannel",
        "CallerIDNum",
        "ConnectedLineNum",
        "DestCallerIDNum",
        "DialString",
        "Destination",
        "DestinationChannel",
        "Source"
    ])


def _is_customer_cdr(event, customer_number):
    if (event.get("Event") or "").lower() != "cdr":
        return False

    if _normalize_pbx_phone_number(event.get("Destination")) != _normalize_pbx_phone_number(customer_number):
        return False

    destination_channel = event.get("DestinationChannel") or ""

    if "PJSIP/trunk" not in destination_channel:
        return False

    return True


def _apply_customer_cdr_result(result, event):
    disposition = event.get("Disposition") or "Unknown"
    billable_seconds = _to_int(event.get("BillableSeconds") or event.get("Billsec"))

    result["cdr_captured"] = "Yes"
    result["cdr_disposition"] = disposition
    result["final_status"] = disposition
    result["duration_seconds"] = _to_int(event.get("Duration"))
    result["billable_seconds"] = billable_seconds
    result["customer_answer_source"] = "CDR"

    if disposition.upper() == "ANSWERED" and billable_seconds >= PBX_MIN_CUSTOMER_BILLABLE_SECONDS:
        result["customer_answered"] = "Yes"
    else:
        result["customer_answered"] = "No"


def _is_customer_answer_event(event, customer_number, extension):
    dial_status = str(event.get("DialStatus") or "").upper()

    if dial_status not in ("ANSWER", "ANSWERED"):
        return False

    if not _event_mentions_customer_leg(event, customer_number):
        return False

    if _event_mentions_extension_only(event, extension, customer_number):
        return False

    return True


def _event_mentions_extension_only(event, extension, customer_number):
    return (
        _event_mentions_extension(event, extension)
        and not _event_mentions_customer_leg(event, customer_number)
    )


def _event_mentions_digits(event, digits):
    return _event_mentions_digits_in_fields(event, digits, [
        "Channel",
        "DestChannel",
        "CallerIDNum",
        "ConnectedLineNum",
        "DestCallerIDNum",
        "Exten",
        "DialString",
        "Destination",
        "DestinationChannel",
        "Source",
        "DestinationContext"
    ])


def _event_mentions_digits_in_fields(event, digits, fields):
    digits = _normalize_pbx_phone_number(digits)

    if not digits:
        return False

    for field in fields:
        value_digits = _normalize_pbx_phone_number(event.get(field))

        if value_digits and digits in value_digits:
            return True

    return False


def _to_int(value):
    try:
        return int(float(value or 0))
    except Exception:
        return 0


def _pbx_call_can_apply_workflow(result):
    return (
        result.get("cdr_captured") == "Yes"
        and (result.get("cdr_disposition") or "").upper() == "ANSWERED"
        and result.get("customer_answered") == "Yes"
        and _to_int(result.get("billable_seconds")) >= PBX_MIN_CUSTOMER_BILLABLE_SECONDS
    )


def _format_pbx_call_comment(result):
    lines = [
        "<b>PBX call summary</b>",
        "",
        "Extension: {0}".format(result.get("extension") or ""),
        "Customer Number: {0}".format(result.get("customer_number") or ""),
        "Customer Answered: {0}".format(result.get("customer_answered") or "No"),
        "Status: {0}".format(result.get("final_status") or "Unknown"),
        "Duration: {0}s".format(_to_int(result.get("duration_seconds"))),
        "Billable Seconds: {0}s".format(_to_int(result.get("billable_seconds"))),
        "Workflow Updated: {0}".format(result.get("workflow_applied") or "No"),
        "Hangup Cause: {0}".format(result.get("hangup_cause") or "Not captured"),
        "Result Source: CDR"
    ]

    return "<br>".join(lines)


def _attach_settlement(user, commission, coordinator, today):
    """Add paid/pending against the payout ledger to the commission blocks.

    The running month is still accruing, so it carries no settlement state - only
    finished months show paid or pending in the PWA.
    """
    reference = commission or coordinator
    from_date = getdate(reference.get("from_date"))
    is_current = (from_date.year, from_date.month) == (today.year, today.month)
    paid = get_paid_amounts(user, from_date.year, from_date.month)

    if commission is not None:
        earned = flt(commission.get("visitor_amount"))
        commission["is_current_month"] = 1 if is_current else 0
        commission["paid_amount"] = paid["Visitor"]
        commission["pending_amount"] = round(max(earned - paid["Visitor"], 0), 3)

    if coordinator is not None:
        earned = flt(coordinator.get("total_amount"))
        coordinator["is_current_month"] = 1 if is_current else 0
        coordinator["paid_amount"] = paid["Coordinator"]
        coordinator["pending_amount"] = round(max(earned - paid["Coordinator"], 0), 3)


def _dedupe_visit_rows(rows):
    seen = {}
    unique_rows = []

    for row in rows:
        name = row.get("service_visit")

        if name and seen.get(name):
            continue

        seen[name] = True
        unique_rows.append(row)

    return unique_rows


def _build_visit_list(rows, invoice_map):
    """Every visit for the combined view, carrying per-invoice detail where it exists."""
    visit_rows = []

    for row in rows:
        invoice = invoice_map.get(row.get("service_visit")) or {}
        normal_count = cint(invoice.get("normal_count"))

        visit_rows.append({
            "service_visit": row.get("service_visit"),
            "visit_date": row.get("visit_date"),
            "customer_name": row.get("customer_name"),
            "visit_type": row.get("visit_type"),
            "workflow_state": row.get("workflow_state"),
            "sales_invoice": ", ".join([
                d.get("sales_invoice") for d in invoice.get("invoices") or []]),
            "invoices": invoice.get("invoices") or [],
            "normal_count": normal_count,
            "is_invoiced": 1 if normal_count else 0,
            "invoice_date": invoice.get("invoice_date"),
            "invoice_net_total": flt(invoice.get("net_value"))
        })

    return sorted(
        visit_rows,
        key=lambda row: (
            str(row.get("visit_date") or ""),
            row.get("service_visit") or ""
        ),
        reverse=True
    )


def _safe_int(value, default, minimum, maximum):
    try:
        value = int(value)
    except Exception:
        value = default

    if value < minimum:
        return minimum

    if value > maximum:
        return maximum

    return value


def _rows_to_count_map(rows, key_field):
    counts = {}

    for row in rows:
        key = row.get(key_field) or ""
        counts[key] = row.get("count") or 0

    return counts


def _get_quotation_list_fields():
    base_fields = [
        "name",
        "customer_name",
        "party_name",
        "creation",
        "modified",
        "transaction_date",
        "grand_total",
        "rounded_total",
        "currency",
        "status",
        "docstatus"
    ]
    optional_fields = [
        "workflow_state",
        "service_visit",
        "visitor",
        "contact_person",
        "contact_mobile",
        "mobile_number",
        "whatsapp_no"
    ]
    fields = []

    standard_fields = ["name", "creation", "modified"]

    for fieldname in base_fields + optional_fields:
        if fieldname in standard_fields or _doctype_has_field("Quotation", fieldname):
            fields.append(fieldname)

    return fields


def _quotation_to_summary(row, include_actions=False):
    transaction_date = row.get("transaction_date")

    data = {
        "name": row.get("name"),
        "customer_name": row.get("customer_name") or row.get("party_name"),
        "grand_total": row.get("rounded_total") or row.get("grand_total") or 0,
        "currency": row.get("currency") or frappe.defaults.get_global_default("currency") or "BHD",
        "creation": row.get("creation"),
        "modified": row.get("modified"),
        "transaction_date": transaction_date,
        "status": row.get("workflow_state") or row.get("status"),
        "workflow_state": row.get("workflow_state"),
        "days_since": _days_since(transaction_date),
        "service_visit": row.get("service_visit"),
        "contact_person": row.get("contact_person"),
        "mobile_number": _get_quotation_phone(row),
        "whatsapp_no": _get_quotation_whatsapp(row)
    }

    if include_actions:
        doc = frappe.get_doc("Quotation", row.get("name"))
        data["can_update"] = _can_update_followup_quotation(doc)
        data["available_actions"] = _get_followup_quotation_actions(doc) if _can_update_followup_quotation(doc) else []

    return data


def _get_allowed_followup_quotation(name, allow_ceo=False):
    doc = frappe.get_doc("Quotation", name)

    if doc.docstatus == 2 or doc.get("status") == "Cancelled" or doc.get("workflow_state") == "Cancelled":
        frappe.throw("This quotation is cancelled.")

    if doc.get("follow_up_mode") != "Visitor":
        frappe.throw("You are not allowed to access this quotation.")

    if doc.get("visitor") != frappe.session.user and not (allow_ceo and _is_ceo_user()):
        frappe.throw("You are not allowed to access this quotation.")

    return doc


def _can_act_on_followup_quotation(doc):
    return doc.get("follow_up_mode") == "Visitor" and doc.get("visitor") == frappe.session.user


def _can_update_followup_quotation(doc):
    return doc.get("follow_up_mode") == "Visitor" and (
        doc.get("visitor") == frappe.session.user or _is_ceo_user()
    )


def _quotation_doc_to_dict(doc):
    data = {
        "name": doc.name,
        "customer_name": doc.get("customer_name") or doc.get("party_name"),
        "party_name": doc.get("party_name"),
        "creation": doc.get("creation"),
        "modified": doc.get("modified"),
        "transaction_date": doc.get("transaction_date"),
        "valid_till": doc.get("valid_till"),
        "grand_total": doc.get("rounded_total") or doc.get("grand_total") or 0,
        "net_total": doc.get("net_total") or 0,
        "total_taxes_and_charges": doc.get("total_taxes_and_charges") or 0,
        "currency": doc.get("currency") or frappe.defaults.get_global_default("currency") or "BHD",
        "status": doc.get("workflow_state") or doc.get("status"),
        "workflow_state": doc.get("workflow_state"),
        "days_since": _days_since(doc.get("transaction_date")),
        "service_visit": doc.get("service_visit"),
        "contact_person": doc.get("contact_person"),
        "mobile_number": _get_quotation_phone(doc),
        "whatsapp_no": _get_quotation_whatsapp(doc),
        "terms": doc.get("terms"),
        "docstatus": doc.docstatus,
        "can_update": _can_update_followup_quotation(doc)
    }

    return data


def _get_quotation_items(doc):
    items = []

    for row in doc.get("items") or []:
        items.append({
            "item_code": row.get("item_code"),
            "item_name": row.get("item_name"),
            "description": row.get("description"),
            "qty": row.get("qty") or 0,
            "uom": row.get("uom"),
            "rate": row.get("rate") or 0,
            "amount": row.get("amount") or 0
        })

    return items


def _get_quotation_phone(doc):
    for fieldname in ["contact_mobile", "mobile_number"]:
        if doc.get(fieldname):
            return doc.get(fieldname)

    return _get_customer_phone(doc.get("party_name"), "mobile_no")


def _get_quotation_whatsapp(doc):
    if doc.get("whatsapp_no"):
        return doc.get("whatsapp_no")

    return _get_customer_phone(doc.get("party_name"), "whatsapp_no") or _get_quotation_phone(doc)


def _get_customer_phone(customer, fieldname):
    if not customer or not _doctype_has_field("Customer", fieldname):
        return None

    return frappe.db.get_value("Customer", customer, fieldname)


def _days_since(value):
    if not value:
        return 0

    return date_diff(nowdate(), getdate(value))


def _doctype_has_field(doctype, fieldname):
    if fieldname == "name":
        return True

    return bool(frappe.get_meta(doctype).get_field(fieldname))


def _get_month_date_range(month):
    month = (month or "")[:7]

    if not month:
        month = nowdate()[:7]

    parts = month.split("-")

    if len(parts) != 2:
        frappe.throw("Invalid month.")

    year = int(parts[0])
    month_number = int(parts[1])

    if month_number < 1 or month_number > 12:
        frappe.throw("Invalid month.")

    from_date = date(year, month_number, 1)

    if month_number == 12:
        next_month = date(year + 1, 1, 1)
    else:
        next_month = date(year, month_number + 1, 1)

    to_date = date.fromordinal(next_month.toordinal() - 1)

    return from_date.isoformat(), to_date.isoformat()


def _get_visit_select_fields():
    meta = frappe.get_meta("Service Visit")
    fieldnames = [df.fieldname for df in meta.fields]
    fields = []

    for fieldname in VISIT_FIELDS + OPTIONAL_VISIT_FIELDS:
        if fieldname in ["name", "workflow_state"] or fieldname in fieldnames:
            fields.append("sv.`{0}`".format(fieldname))

    return ",\n            ".join(fields)


def _get_time_order_sql():
    meta = frappe.get_meta("Service Visit")
    time_field = meta.get_field("time")
    options = []

    if time_field and time_field.options:
        options = [
            option.strip()
            for option in time_field.options.split("\n")
            if option.strip()
        ]

    if not options:
        return "sv.`time` ASC"

    case_parts = []

    for index, option in enumerate(options, 1):
        case_parts.append(
            "WHEN {0} THEN {1}".format(
                frappe.db.escape(option),
                index
            )
        )

    return "CASE sv.`time` {0} ELSE 999 END ASC".format(
        " ".join(case_parts)
    )


def _get_allowed_visit(name, allow_ceo=False):
    user = frappe.session.user

    allowed = _can_act_on_visit(name)

    if not allowed and not (allow_ceo and _is_ceo_user() and _visit_has_user_assignment(name)):
        frappe.throw("You are not allowed to access this visit.")

    doc = frappe.get_doc("Service Visit", name)

    if doc.docstatus != 1 or doc.workflow_state == "Cancelled":
        frappe.throw("This visit is not available in the driver app.")

    return doc


def _can_act_on_visit(name):
    return frappe.db.exists(
        "WS User Assignment",
        {
            "parent": name,
            "parenttype": "Service Visit",
            "user": frappe.session.user
        }
    )


def _can_update_visit(name):
    return _can_act_on_visit(name) or (_is_ceo_user() and _visit_has_user_assignment(name))


def _visit_has_user_assignment(name):
    return frappe.db.exists(
        "WS User Assignment",
        {
            "parent": name,
            "parenttype": "Service Visit"
        }
    )


def _is_valid_maps_link(link):
    link = (link or "").strip().lower()

    if not (link.startswith("http://") or link.startswith("https://")):
        return False

    allowed_hosts = [
        "google.com/maps",
        "www.google.com/maps",
        "maps.google.com",
        "maps.app.goo.gl",
        "goo.gl/maps"
    ]

    return any(host in link for host in allowed_hosts)


def _visit_to_dict(doc):
    data = {}

    for fieldname in VISIT_FIELDS + OPTIONAL_VISIT_FIELDS:
        data[fieldname] = doc.get(fieldname)

    return data


def _get_comments(doctype, name):
    comments = frappe.get_all(
        "Comment",
        filters={
            "reference_doctype": doctype,
            "reference_name": name,
            "comment_type": "Comment"
        },
        fields=["name", "owner", "creation", "content"],
        order_by="creation desc",
        limit_page_length=100
    )

    owners = list(set([comment.owner for comment in comments if comment.owner]))

    if not owners:
        return comments

    users = frappe.get_all(
        "User",
        filters={
            "name": ["in", owners]
        },
        fields=["name", "full_name"]
    )

    full_name_map = {}
    for user in users:
        full_name_map[user.name] = user.full_name or user.name

    for comment in comments:
        comment.owner_full_name = full_name_map.get(comment.owner) or comment.owner

    return comments


def _get_assigned_users(doc):
    users = []

    for row in doc.get("assigned_users") or []:
        if row.get("user"):
            users.append(row.get("user"))

    if not users:
        return []

    user_names = frappe.get_all(
        "User",
        filters={
            "name": ["in", users]
        },
        fields=["name", "full_name"]
    )

    full_name_map = {}
    for user in user_names:
        full_name_map[user.name] = user.full_name or user.name

    return [
        {
            "user": user,
            "full_name": full_name_map.get(user) or user
        }
        for user in users
    ]


def _get_visit_images(doc):
    images = []
    seen = set()

    attached = frappe.get_all(
        "File",
        filters={
            "attached_to_doctype": "Service Visit",
            "attached_to_name": doc.name
        },
        fields=["name", "file_name", "file_url"],
        order_by="creation desc",
        limit_page_length=100
    )

    for file_doc in attached:
        if file_doc.file_url and file_doc.file_url not in seen:
            seen.add(file_doc.file_url)
            images.append(file_doc)

    for file_url in [doc.get("visit_attachment"), doc.get("reference_image")]:
        if file_url and file_url not in seen:
            seen.add(file_url)
            images.append({
                "file_url": file_url,
                "file_name": file_url.split("/")[-1]
            })

    for file_name in _parse_reference_images_json(doc.get("reference_images_json")):
        file_doc = _get_file_for_display(file_name)
        if file_doc and file_doc.file_url not in seen:
            seen.add(file_doc.file_url)
            images.append(file_doc)

    return images


def _get_file_for_display(file_name):
    if not file_name or not frappe.db.exists("File", file_name):
        return None

    return frappe.db.get_value(
        "File",
        file_name,
        ["name", "file_name", "file_url"],
        as_dict=True
    )


def _parse_reference_images_json(raw):
    if not raw:
        return []

    parsed = frappe.parse_json(raw)

    if isinstance(parsed, str):
        return [parsed] if parsed else []

    if isinstance(parsed, (list, tuple)):
        return [d for d in parsed if d]

    return []


def _get_driver_actions(doc):
    actions = []
    transitions = _get_transition_actions(doc)

    for key in ["start_visit", "complete_visit", "request_reschedule", "mark_lost"]:
        config = DRIVER_ACTIONS.get(key)

        action = _match_action(config.get("actions"), transitions)

        if action:
            actions.append({
                "key": key,
                "label": config.get("label"),
                "workflow_action": action,
                "requires_note": config.get("requires_note") or 0
            })

    return actions


def _get_followup_quotation_actions(doc):
    actions = []
    transitions = _get_transition_actions(doc)

    for key in ["request_payment", "lost", "book_revisit", "follow_up", "call_client",
                "send_quotation"]:
        config = FOLLOWUP_QUOTATION_ACTIONS.get(key)
        action = _match_action(config.get("actions"), transitions)

        if action:
            actions.append({
                "key": key,
                "label": config.get("label"),
                "workflow_action": action,
                "requires_note": 0
            })

    return actions


def _get_transition_actions(doc):
    if get_transitions is None:
        return []

    transitions = get_transitions(doc)
    actions = []

    for transition in transitions:
        action = transition.get("action")
        if action:
            actions.append(action)

    return actions


def _get_workflow_action(doc, action_key):
    config = DRIVER_ACTIONS.get(action_key)

    if not config:
        frappe.throw("Invalid driver action.")

    action = _match_action(config.get("actions"), _get_transition_actions(doc))

    if not action:
        frappe.throw("This workflow action is not available for the current visit state.")

    return action


def _get_followup_quotation_workflow_action(doc, action_key):
    config = FOLLOWUP_QUOTATION_ACTIONS.get(action_key)

    if not config:
        frappe.throw("Invalid quotation action.")

    action = _match_action(config.get("actions"), _get_transition_actions(doc))

    if not action:
        frappe.throw("This workflow action is not available for the current quotation state.")

    return action


def _match_action(options, transitions):
    for option in options or []:
        if option in transitions:
            return option

    return None


def _attach_uploaded_files(doc, file_names):
    if not file_names:
        return []

    if isinstance(file_names, str):
        file_names = frappe.parse_json(file_names)

    attached_files = []

    for file_name in file_names:
        if not file_name or not frappe.db.exists("File", file_name):
            continue

        file_doc = frappe.get_doc("File", file_name)

        if file_doc.owner not in [frappe.session.user, "Guest"]:
            frappe.throw("You are not allowed to attach file {0}.".format(file_name))

        file_doc.attached_to_doctype = "Service Visit"
        file_doc.attached_to_name = doc.name
        file_doc.folder = file_doc.folder or "Home/Attachments"
        file_doc.save(ignore_permissions=True)
        attached_files.append(file_doc)

    return attached_files


def _merge_completion_files(doc, files):
    file_names = [file_doc.name for file_doc in files if file_doc and file_doc.name]

    if not file_names:
        return []

    result = merge_documents(
        file_names=file_names,
        output_filename="Service Visit - {0}".format(doc.name),
        attach_to_doctype="Service Visit",
        attach_to_name=doc.name,
        cleanup_originals=1,
        is_private=0
    )

    file_doc_name = result.get("file_doc") if result else None

    if not file_doc_name:
        frappe.throw("Failed to generate visit completion report.")

    file_doc = frappe.get_doc("File", file_doc_name)

    if file_doc.file_url:
        doc.visit_attachment = file_doc.file_url
        doc.db_set("visit_attachment", file_doc.file_url, update_modified=False)

    return [file_doc]


def _add_comment(doctype, name, content):
    frappe.get_doc({
        "doctype": "Comment",
        "comment_type": "Comment",
        "reference_doctype": doctype,
        "reference_name": name,
        "content": content
    }).insert(ignore_permissions=True)
