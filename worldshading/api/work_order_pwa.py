# -*- coding: utf-8 -*-
# Whitelisted API for the Work Order Production PWA (/work-orders).
#
# Phase 1 scope:
#   - get_work_order_context      -> logged in user profile for the app header
#   - get_my_work_orders          -> active production work orders assigned to the user
#   - get_work_order_details      -> full detail for a single assigned work order
#   - update_work_order_progress  -> update production_progress_percent field only
#
# Security rules honoured here:
#   - user must be logged in (Guest is rejected everywhere)
#   - user only sees / touches Work Orders they are assigned to, either via the
#     Work Order `production_team_users` child rows or via the Work Order's
#     Work Team members. There is no "list all work orders" path.
#   - no workflow state change, no Stock Entry, no submit is performed from here.
#
# ERPNext v12 / Frappe v12 compatible. No frappe.qb, no type hints, no dataclasses.

import frappe
from frappe.utils import cint, flt, getdate
from frappe.utils.html_utils import sanitize_html

# Workflow engine helpers. Imported defensively so the module still loads if a
# future Frappe version moves them (Phase 1 endpoints keep working regardless).
#
# NOTE: we intentionally do NOT use frappe.model.workflow.get_transitions /
# apply_workflow directly, because both enforce standard Work Order read/write
# desk permission — which assigned workshop staff deliberately do not have (they
# only hold the "Workshop (workflow)" role). Instead we read the Workflow doc and
# apply the transition ourselves, gating on (a) the user's assignment to the Work
# Order (already checked in _get_allowed_work_order) and (b) the transition's
# allowed role, then save with ignore_permissions — the same trust model Phase 1
# uses for its raw-SQL reads. This keeps the workflow's role/condition/next-state
# rules intact while not exposing Work Orders through the desk.
try:
    from frappe.model.workflow import (
        get_workflow,
        is_transition_condition_satisfied,
        has_approval_access,
    )
except Exception:
    get_workflow = None
    is_transition_condition_satisfied = None
    has_approval_access = None


# Workshop-owned workflow actions surfaced as PWA buttons (Phase 2). Each maps a
# stable UI key to the underlying Frappe Workflow transition action name(s).
# Availability is still decided by get_transitions() (role + current state), so a
# button only appears / applies when the workflow genuinely allows it. The
# workflow_state is never written directly.
WORK_ORDER_ACTIONS = {
    "start": {
        "label": "Start Production",
        "actions": ["Start Production"],
        "tone": "primary",
        "comment": "Started production",
    },
    "resume": {
        "label": "Resume Production",
        "actions": ["Resume Production"],
        "tone": "primary",
        "comment": "Resumed production",
    },
    "pause": {
        "label": "Pause Production",
        "actions": ["Pause Production"],
        "tone": "neutral",
        "comment": "Paused production",
    },
    "complete": {
        "label": "Complete Production",
        "actions": ["Complete Production"],
        "tone": "success",
        "comment": "Completed production",
    },
    "stop": {
        "label": "Stop Production",
        "actions": ["Stop Production"],
        "tone": "danger",
        "comment": "Stopped production",
    },
}

# The order buttons are shown in the app.
WORK_ORDER_ACTION_ORDER = ["start", "resume", "pause", "complete", "stop"]


# Production states that the workshop app is allowed to show. These are the
# "active" production states. Everything else (Pending Schedule / Draft,
# Scheduled, Pending Material Transfer, Completed, Cancelled, ...) is hidden.
ACTIVE_WORKFLOW_STATES = [
    "Ready to Start",
    "In Progress",
    "Paused",
    "Stopped",
]


# Columns returned for each Work Order card in the list view.
WORK_ORDER_LIST_FIELDS = [
    "wo.name",
    "wo.production_item",
    "wo.item_name",
    "wo.qty",
    "wo.produced_qty",
    "wo.stock_uom",
    "wo.sales_order",
    "wo.production_team",
    "wo.planned_start_date",
    "wo.planned_end_date",
    "wo.status",
    "wo.workflow_state",
    "wo.production_progress_percent",
    "wo.production_priority",
]


# Fields copied into the detail payload (read with doc.get so a missing custom
# field never raises).
WORK_ORDER_DETAIL_FIELDS = [
    "name",
    "production_item",
    "item_name",
    "qty",
    "produced_qty",
    "material_transferred_for_manufacturing",
    "stock_uom",
    "sales_order",
    "production_team",
    "planned_start_date",
    "planned_end_date",
    "actual_start_date",
    "actual_end_date",
    "status",
    "workflow_state",
    "production_progress_percent",
    "production_priority",
    "estimated_hours",
    "bom_no",
    "company",
    "wip_warehouse",
    "fg_warehouse",
]


@frappe.whitelist()
def get_work_order_context():
    """Return the current user profile for the app header/greeting."""
    user = _require_login()

    full_name, user_image = frappe.db.get_value(
        "User", user, ["full_name", "user_image"]
    ) or (None, None)

    is_admin = _is_work_order_admin(user)

    return {
        "user": user,
        "full_name": full_name or user,
        "user_image": user_image,
        "is_admin": is_admin,
        "user_options": _get_work_order_member_options() if is_admin else [],
    }


@frappe.whitelist()
def get_my_work_orders(workflow_state=None, search=None, from_date=None,
        to_date=None, limit=20, start=0, member=None):
    """List active production Work Orders.

    By default only Work Orders the logged-in user is assigned to are returned.
    A work-order admin (the role configured in WS Settings `work_order_admin`)
    may pass `member`: "__all__" for every active Work Order (no duplication),
    or a specific user to see that team member's assigned Work Orders.
    Optional `from_date` / `to_date` filter on the planned start date.
    """
    user = _require_login()

    workflow_state = (workflow_state or "").strip()
    search_value = (search or "").strip()
    from_date = (from_date or "").strip()
    to_date = (to_date or "").strip()
    limit = _safe_int(limit, 20, 1, 100)
    start = _safe_int(start, 0, 0, 100000)
    target_user = _get_effective_member(member)

    if from_date and to_date and getdate(from_date) > getdate(to_date):
        from_date, to_date = to_date, from_date

    params = {
        "user": target_user or user,
        "search": "%{0}%".format(search_value),
        "from_date": from_date,
        "to_date": to_date,
        "limit": limit,
        "start": start,
    }

    conditions = ["wo.docstatus = 1"]
    if target_user is not None:
        conditions.append(_membership_condition())
    _append_active_state_condition(conditions, params)

    if from_date:
        conditions.append("DATE(wo.planned_start_date) >= %(from_date)s")

    if to_date:
        conditions.append("DATE(wo.planned_start_date) <= %(to_date)s")

    if search_value:
        conditions.append("""(
            wo.name LIKE %(search)s
            OR IFNULL(wo.production_item, '') LIKE %(search)s
            OR IFNULL(wo.item_name, '') LIKE %(search)s
            OR IFNULL(wo.sales_order, '') LIKE %(search)s
        )""")

    base_where = " AND ".join(conditions)

    list_where = base_where
    if workflow_state:
        params["workflow_state"] = workflow_state
        list_where += " AND IFNULL(wo.workflow_state, '') = %(workflow_state)s"

    fields = ", ".join(WORK_ORDER_LIST_FIELDS)

    work_orders = frappe.db.sql("""
        SELECT DISTINCT {fields}
        FROM `tabWork Order` wo
        WHERE {list_where}
        ORDER BY wo.planned_start_date IS NULL ASC, wo.planned_start_date ASC, wo.name ASC
        LIMIT %(start)s, %(limit)s
    """.format(fields=fields, list_where=list_where), params, as_dict=True)

    total_count = frappe.db.sql("""
        SELECT COUNT(DISTINCT wo.name)
        FROM `tabWork Order` wo
        WHERE {list_where}
    """.format(list_where=list_where), params)[0][0]

    state_rows = frappe.db.sql("""
        SELECT IFNULL(wo.workflow_state, '') AS workflow_state,
            COUNT(DISTINCT wo.name) AS count
        FROM `tabWork Order` wo
        WHERE {base_where}
        GROUP BY IFNULL(wo.workflow_state, '')
    """.format(base_where=base_where), params, as_dict=True)

    return {
        "work_orders": work_orders,
        "total_count": total_count,
        "state_counts": _rows_to_count_map(state_rows),
        "has_more": (start + len(work_orders)) < total_count,
        "start": start,
        "limit": limit,
    }


@frappe.whitelist()
def get_work_order_details(name):
    """Return the full detail payload for one assigned Work Order."""
    doc = _get_allowed_work_order(name)

    data = {}
    for fieldname in WORK_ORDER_DETAIL_FIELDS:
        data[fieldname] = doc.get(fieldname)

    data["required_items"] = _get_required_items(doc)
    data["team_members"] = _get_team_members(doc)
    data["comments"] = _get_comments("Work Order", doc.name)
    data["available_actions"] = _available_actions(doc)
    data["can_update"] = 1

    return data


@frappe.whitelist()
def get_work_order_insights(member=None):
    """Aggregate figures across active production Work Orders.

    Assigned Work Orders by default; a work-order admin may pass `member`
    ("__all__" for everyone, or a specific user).
    """
    user = _require_login()
    target_user = _get_effective_member(member)

    params = {"user": target_user or user}
    conditions = ["wo.docstatus = 1"]
    if target_user is not None:
        conditions.append(_membership_condition())
    _append_active_state_condition(conditions, params)
    where = " AND ".join(conditions)

    totals = frappe.db.sql("""
        SELECT
            COUNT(*) AS total,
            SUM(wo.qty) AS total_qty,
            SUM(wo.produced_qty) AS produced_qty,
            AVG(wo.production_progress_percent) AS avg_progress
        FROM `tabWork Order` wo
        WHERE {where}
    """.format(where=where), params, as_dict=True)[0]

    state_rows = frappe.db.sql("""
        SELECT IFNULL(wo.workflow_state, '') AS workflow_state, COUNT(*) AS count
        FROM `tabWork Order` wo
        WHERE {where}
        GROUP BY IFNULL(wo.workflow_state, '')
    """.format(where=where), params, as_dict=True)

    return {
        "total": cint(totals.get("total")),
        "total_qty": flt(totals.get("total_qty")),
        "produced_qty": flt(totals.get("produced_qty")),
        "avg_progress": int(round(flt(totals.get("avg_progress")))),
        "state_counts": _rows_to_count_map(state_rows),
    }


@frappe.whitelist()
def add_work_order_comment(name, content):
    """Add a plain comment to an assigned Work Order and return the thread."""
    doc = _get_allowed_work_order(name)

    content = (content or "").strip()
    if not content:
        frappe.throw("Comment is required.")

    _add_comment("Work Order", doc.name, content)

    return _get_comments("Work Order", doc.name)


@frappe.whitelist()
def apply_work_order_action(name, action_key, note=None):
    """Apply a Workshop workflow transition (Start/Pause/Resume/Complete/Stop).

    The transition is applied through frappe.model.workflow.apply_workflow, so
    the workflow engine enforces the transition's allowed role, any condition,
    and the resulting next state. The workflow_state field is never written
    directly, and no Stock Entry / submit is performed here. An optional note is
    recorded as a comment on the Work Order.
    """
    if get_workflow is None:
        frappe.throw("Workflow actions are not available right now.")

    doc = _get_allowed_work_order(name)
    transition, config = _resolve_work_order_action(doc, action_key)

    _apply_transition(doc, transition)

    note = (note or "").strip()
    content = "<b>{0}</b>".format(config["comment"])
    if note:
        content += "<br><br>{0}".format(sanitize_html(note))
    _add_comment("Work Order", doc.name, content)

    return get_work_order_details(doc.name)


@frappe.whitelist()
def update_work_order_progress(name, production_progress_percent):
    """Update only the production_progress_percent field on a Work Order.

    No workflow transition, no submit, no stock movement is triggered. The value
    is clamped to the 0-100 range.
    """
    doc = _get_allowed_work_order(name)

    value = flt(production_progress_percent)
    if value < 0:
        value = 0
    if value > 100:
        value = 100

    # Write the single field directly so the submitted document's workflow and
    # other fields are left untouched.
    frappe.db.set_value(
        "Work Order", doc.name, "production_progress_percent", value
    )

    return {
        "name": doc.name,
        "production_progress_percent": value,
    }


# ---------------------------------------------------------------------------
# Push notifications
# ---------------------------------------------------------------------------
#
# The push subscription store and sender live in api/driver_visit.py and are
# fully generic: they key off frappe.session.user and the shared "PWA Push
# Subscription" DocType (there is nothing driver-specific about them), and the
# VAPID keys in site_config are app-wide. So the Workshop app reuses them as-is;
# only the test-push target URL/label is workshop-specific. Imported lazily so
# this module never depends on driver_visit's heavier imports at load time.


@frappe.whitelist()
def get_push_public_key():
    from worldshading.api.driver_visit import get_push_public_key as _fn
    return _fn()


@frappe.whitelist()
def save_push_subscription(subscription=None):
    _require_login()
    from worldshading.api.driver_visit import save_push_subscription as _fn
    return _fn(subscription)


@frappe.whitelist()
def disable_push_subscription(endpoint=None):
    _require_login()
    from worldshading.api.driver_visit import disable_push_subscription as _fn
    return _fn(endpoint)


@frappe.whitelist()
def send_test_push():
    """Send a test push to the current user's enabled devices (Workshop app)."""
    user = _require_login()
    from worldshading.api.driver_visit import send_push_to_user

    result = send_push_to_user(
        user,
        "Workshop",
        "Test notification from the Workshop app.",
        "/workshop",
        "workshop-test-push",
    )

    if not result or not result.get("sent"):
        frappe.throw("No active notification device found. Enable notifications first, then try again.")

    return result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_login():
    user = frappe.session.user

    if not user or user == "Guest":
        frappe.throw("Please login to use the Work Order app.", frappe.PermissionError)

    return user


def _get_work_order_admin_role():
    """The role that may view/act on every Work Order, from WS Settings."""
    try:
        role = frappe.db.get_single_value("WS Settings", "work_order_admin")
    except Exception:
        role = None
    return (role or "").strip()


def _is_work_order_admin(user=None):
    role = _get_work_order_admin_role()
    if not role:
        return False
    return role in frappe.get_roles(user or frappe.session.user)


# The role whose holders are the selectable "members" in the admin picker
# (shop-floor staff who get assigned to production teams / work orders).
WORKSHOP_MEMBER_ROLE = "Workshop (workflow)"


def _get_effective_member(member):
    """Resolve the admin member picker to a user filter.

    Admin + "__all__"        -> None  (all active Work Orders, no membership filter)
    Admin + a specific user  -> that user (their assigned Work Orders)
    Everyone else            -> the logged-in user (their own).
    """
    member = (member or "").strip()

    if _is_work_order_admin():
        if member == "__all__":
            return None
        if member and frappe.db.exists("User", member):
            return member

    return frappe.session.user


def _get_work_order_member_options():
    """Users holding the Workshop role, for the admin's member picker.

    The current user is always included (so an admin can view their own jobs),
    mirroring the driver PWA's visitor list.
    """
    rows = frappe.get_all(
        "Has Role",
        filters={"role": WORKSHOP_MEMBER_ROLE, "parenttype": "User"},
        fields=["parent"],
        limit_page_length=0,
    )

    seen = {}
    options = []

    def _add(user):
        if not user or user in ("Administrator", "Guest") or seen.get(user):
            return
        full_name, user_image, enabled = frappe.db.get_value(
            "User", user, ["full_name", "user_image", "enabled"]
        ) or (None, None, 0)
        if not enabled:
            return
        seen[user] = 1
        options.append({
            "user": user,
            "full_name": full_name or user,
            "user_image": user_image,
        })

    for row in rows:
        _add(row.get("parent"))

    _add(frappe.session.user)

    return sorted(options, key=lambda row: (row.get("full_name") or row.get("user") or "").lower())


def _append_active_state_condition(conditions, params):
    """Append the "workflow_state is an active production state" SQL filter."""
    placeholders = []

    for index, state in enumerate(ACTIVE_WORKFLOW_STATES):
        key = "active_{0}".format(index)
        params[key] = state
        placeholders.append("%({0})s".format(key))

    conditions.append(
        "IFNULL(wo.workflow_state, '') IN ({0})".format(", ".join(placeholders))
    )


def _membership_condition():
    """SQL fragment: the current user is assigned to the Work Order.

    Assignment is either a direct row in the Work Order `production_team_users`
    child table, or membership in the Work Order's Work Team. Both share
    the `Work Team User` child doctype, distinguished by `parenttype`.
    """
    return """(
        EXISTS (
            SELECT 1
            FROM `tabWork Team User` wo_ptu
            WHERE wo_ptu.parenttype = 'Work Order'
                AND wo_ptu.parent = wo.name
                AND wo_ptu.user = %(user)s
        )
        OR EXISTS (
            SELECT 1
            FROM `tabWork Team User` team_ptu
            WHERE team_ptu.parenttype = 'Work Team'
                AND team_ptu.parent = wo.production_team
                AND team_ptu.user = %(user)s
        )
    )"""


def _is_assigned_to_work_order(name):
    user = frappe.session.user

    if frappe.db.exists("Work Team User", {
        "parenttype": "Work Order",
        "parent": name,
        "user": user,
    }):
        return True

    production_team = frappe.db.get_value("Work Order", name, "production_team")

    if production_team and frappe.db.exists("Work Team User", {
        "parenttype": "Work Team",
        "parent": production_team,
        "user": user,
    }):
        return True

    return False


def _get_allowed_work_order(name):
    _require_login()

    if not name or not frappe.db.exists("Work Order", name):
        frappe.throw("Work Order not found.")

    if not _is_assigned_to_work_order(name) and not _is_work_order_admin():
        frappe.throw(
            "You are not allowed to access this work order.", frappe.PermissionError
        )

    doc = frappe.get_doc("Work Order", name)

    if doc.docstatus != 1:
        frappe.throw("This work order is not available in the app.")

    return doc


def _available_transitions(doc):
    """Workflow transitions available to the current user for this doc's state.

    Mirrors frappe.model.workflow.get_transitions' role + condition filtering,
    but deliberately skips its Work Order read-permission check (assignment is
    already enforced upstream). Returns a list of transition child docs.
    """
    if get_workflow is None:
        return []

    workflow = get_workflow(doc.doctype)
    if not workflow:
        return []

    current_state = doc.get(workflow.workflow_state_field)
    if not current_state:
        return []

    roles = set(frappe.get_roles())
    transitions = []

    for transition in workflow.transitions:
        if transition.state != current_state:
            continue
        if transition.allowed not in roles:
            continue
        if is_transition_condition_satisfied and not is_transition_condition_satisfied(transition, doc):
            continue
        transitions.append(transition)

    return transitions


def _available_actions(doc):
    """Map the workflow's currently-available transitions to PWA action buttons."""
    action_names = set([t.action for t in _available_transitions(doc)])
    available = []

    for key in WORK_ORDER_ACTION_ORDER:
        config = WORK_ORDER_ACTIONS[key]
        matched = _match_action(config["actions"], action_names)
        if matched:
            available.append({
                "key": key,
                "label": config["label"],
                "tone": config["tone"],
                "workflow_action": matched,
            })

    return available


def _match_action(options, action_names):
    for option in (options or []):
        if option in action_names:
            return option
    return None


def _resolve_work_order_action(doc, action_key):
    """Return the (transition_doc, config) for a UI action key, or throw."""
    config = WORK_ORDER_ACTIONS.get(action_key)
    if not config:
        frappe.throw("Invalid work order action.")

    for transition in _available_transitions(doc):
        if transition.action in config["actions"]:
            return transition, config

    frappe.throw("This action is not available for the current work order state.")


def _apply_transition(doc, transition):
    """Apply one workflow transition to doc.

    The transition's role and condition were already checked in
    _available_transitions, and self-approval is enforced here. The state is then
    written directly with db_set — the same approach as Phase 1's progress update
    and worldshading.api.work_order_team.update_work_order_state — so assigned
    workshop staff who hold only the "Workshop (workflow)" role (and not Work
    Order desk permission) can still drive the shop-floor states. Using doc.save()
    instead would trip Frappe's validate_workflow, which re-checks read
    permission on every save.

    Transitions that would change docstatus (submit/cancel) are refused: those
    are heavier operations deliberately kept out of the PWA for now.
    """
    workflow = get_workflow(doc.doctype)
    user = frappe.session.user

    if has_approval_access and not has_approval_access(user, doc, transition):
        frappe.throw("Self approval is not allowed for this action.")

    next_states = [d for d in workflow.states if d.state == transition.next_state]
    if not next_states:
        frappe.throw("Workflow next state is not configured correctly.")
    next_state = next_states[0]

    if cint(next_state.doc_status) != cint(doc.docstatus):
        frappe.throw("This action cannot be performed from the app.")

    doc.db_set(workflow.workflow_state_field, transition.next_state, update_modified=True)

    if next_state.update_field:
        doc.db_set(next_state.update_field, next_state.update_value, update_modified=True)

    return doc


def _get_required_items(doc):
    rows = doc.get("required_items") or []

    # Work Order Item has no UOM field: its required/transferred/consumed
    # quantities are always in the item's STOCK uom (ERPNext converts BOM lines
    # to stock qty when building the Work Order). So we just label them with the
    # item's stock uom, fetched from the Item master in one query.
    item_codes = list(set([row.get("item_code") for row in rows if row.get("item_code")]))
    uom_map = {}
    if item_codes:
        for item in frappe.get_all(
            "Item",
            filters={"name": ["in", item_codes]},
            fields=["name", "stock_uom"],
        ):
            uom_map[item.name] = item.stock_uom

    items = []
    for row in rows:
        items.append({
            "item_code": row.get("item_code"),
            "item_name": row.get("item_name"),
            "required_qty": flt(row.get("required_qty")),
            "transferred_qty": flt(row.get("transferred_qty")),
            "consumed_qty": flt(row.get("consumed_qty")),
            "source_warehouse": row.get("source_warehouse"),
            "uom": uom_map.get(row.get("item_code")) or "",
        })

    return items


def _get_team_members(doc):
    members = []

    for row in (doc.get("production_team_users") or []):
        members.append({
            "user": row.get("user"),
            "full_name": row.get("full_name") or row.get("user"),
            "role": row.get("role"),
            "available": cint(row.get("available")),
        })

    # Fall back to the Work Team roster when the Work Order table is empty.
    if not members and doc.get("production_team"):
        team_rows = frappe.get_all(
            "Work Team User",
            filters={
                "parenttype": "Work Team",
                "parent": doc.get("production_team"),
            },
            fields=["user", "full_name", "role", "available"],
            order_by="idx asc",
        )

        for row in team_rows:
            members.append({
                "user": row.get("user"),
                "full_name": row.get("full_name") or row.get("user"),
                "role": row.get("role"),
                "available": cint(row.get("available")),
            })

    return members


def _get_comments(doctype, name):
    comments = frappe.get_all(
        "Comment",
        filters={
            "reference_doctype": doctype,
            "reference_name": name,
            "comment_type": "Comment",
        },
        fields=["name", "owner", "creation", "content"],
        order_by="creation desc",
        limit_page_length=100,
    )

    owners = list(set([comment.owner for comment in comments if comment.owner]))

    if not owners:
        return comments

    users = frappe.get_all(
        "User",
        filters={"name": ["in", owners]},
        fields=["name", "full_name"],
    )

    full_name_map = {}
    for user in users:
        full_name_map[user.name] = user.full_name or user.name

    for comment in comments:
        comment.owner_full_name = full_name_map.get(comment.owner) or comment.owner

    return comments


def _add_comment(doctype, name, content):
    frappe.get_doc({
        "doctype": "Comment",
        "comment_type": "Comment",
        "reference_doctype": doctype,
        "reference_name": name,
        "content": content,
    }).insert(ignore_permissions=True)


def _rows_to_count_map(rows):
    counts = {}

    for row in rows:
        key = row.get("workflow_state") or ""
        counts[key] = cint(row.get("count"))

    return counts


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
