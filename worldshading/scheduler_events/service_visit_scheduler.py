import frappe
from datetime import datetime
from frappe.utils import now_datetime, nowdate, getdate, add_days, add_to_date, get_datetime
from worldshading.api.driver_visit import send_push_to_user

SERVICE_VISIT_REMINDER_TYPE = "30 Minute Reminder"
SERVICE_VISIT_REMINDER_WORKFLOW_STATE = "Ready To Visit"

def auto_update_service_visits():

    # today = getdate(nowdate())
    # tomorrow = add_days(today, 1)
    today = getdate(nowdate())

    # Default: move visits one day before
    confirmation_cutoff = add_days(today, 1)

    # Thursday: also move Saturday visits because Friday is a holiday
    # Monday=0, Tuesday=1, Wednesday=2, Thursday=3, Friday=4, Saturday=5, Sunday=6
    if today.weekday() == 3:
        confirmation_cutoff = add_days(today, 2)

    processed = 0
    max_process = 50  # Safety limit

    visits = frappe.get_all(
        "Service Visit",
        filters={
            "workflow_state": "Scheduled",
            "docstatus": 1
        },
        fields=["name", "date"],
        limit_page_length=200
    )

    for sv in visits:

        if processed >= max_process:
            break

        try:

            doc = frappe.get_doc("Service Visit", sv.name)

            if not doc.date:
                continue

            visit_date = getdate(doc.date)

            # Move if appointment is today, tomorrow,
            # or missed by scheduler previously
            if visit_date <= confirmation_cutoff:

                doc.workflow_state = "Pending Confirmation"

                doc.save(ignore_permissions=True)

                doc.add_comment(
                    "Workflow",
                    f"📞 Auto-moved from 'Scheduled' → 'Pending Confirmation' "
                    f"(Visit date: {doc.date})"
                )

                frappe.db.commit()

                processed += 1

        except Exception as ex:

            frappe.log_error(
                f"Service Visit: {sv.name}\nError: {str(ex)}",
                "Service Visit Auto Update"
            )

    frappe.logger().info(
        f"[Service Visit Automation] Total transitions processed: {processed}"
    )


def send_service_visit_reminders():
    now_dt = get_datetime(now_datetime())
    window_end = add_to_date(now_dt, minutes=30)
    today = getdate(now_dt)
    window_end_date = getdate(window_end)
    processed = 0
    max_process = 100

    visits = frappe.get_all(
        "Service Visit",
        filters={
            "docstatus": 1,
            "date": ["between", [today, window_end_date]],
            "workflow_state": SERVICE_VISIT_REMINDER_WORKFLOW_STATE
        },
        fields=["name", "customer_name", "date", "time", "city", "workflow_state"],
        limit_page_length=300
    )

    due_visits = []

    for visit in visits:
        reminder_on = _get_service_visit_start_datetime(visit)

        if not reminder_on:
            continue

        if reminder_on < now_dt or reminder_on > window_end:
            continue

        visit.reminder_on = reminder_on
        due_visits.append(visit)

        if len(due_visits) >= max_process:
            break

    if not due_visits:
        return

    assignments = _get_service_visit_assignments([visit.name for visit in due_visits])

    for visit in due_visits:
        for user in assignments.get(visit.name, []):
            if _has_service_visit_reminder_log(visit.name, user, visit.reminder_on):
                continue

            if not _has_enabled_push_subscription(user):
                continue

            result = send_push_to_user(
                user,
                "Service Visit in 30 minutes",
                _get_service_visit_reminder_message(visit),
                "/driver-visits",
                "service-visit-{0}-{1}".format(visit.name, SERVICE_VISIT_REMINDER_TYPE)
            )

            status = "Sent" if result.get("sent") else "Failed"
            _create_service_visit_reminder_log(visit, user, status)
            processed += 1

    frappe.logger().info(
        "[Service Visit Reminder] Total reminders processed: {0}".format(processed)
    )


def _get_service_visit_start_datetime(visit):
    if not visit.get("date") or not visit.get("time"):
        return None

    time_text = (visit.get("time") or "").strip()
    start_time = time_text.split(" to ")[0].strip()

    for fmt in ["%I:%M %p", "%H:%M:%S", "%H:%M"]:
        try:
            parsed_time = datetime.strptime(start_time, fmt).time()
            break
        except ValueError:
            parsed_time = None

    if not parsed_time:
        return None

    return datetime.combine(getdate(visit.get("date")), parsed_time)


def _get_service_visit_assignments(service_visits):
    rows = frappe.get_all(
        "WS User Assignment",
        filters={
            "parent": ["in", service_visits],
            "parenttype": "Service Visit"
        },
        fields=["parent", "user"],
        limit_page_length=500
    )
    assignments = {}

    for row in rows:
        if not row.get("user"):
            continue

        assignments.setdefault(row.parent, [])

        if row.user not in assignments[row.parent]:
            assignments[row.parent].append(row.user)

    return assignments


def _has_service_visit_reminder_log(service_visit, user, reminder_on):
    return frappe.db.exists(
        "PWA Notification Log",
        {
            "reference_doctype": "Service Visit",
            "reference_name": service_visit,
            "user": user,
            "reminder_type": SERVICE_VISIT_REMINDER_TYPE,
            "reminder_on": reminder_on
        }
    )


def _has_enabled_push_subscription(user):
    return frappe.db.exists(
        "PWA Push Subscription",
        {
            "user": user,
            "enabled": 1
        }
    )


def _create_service_visit_reminder_log(visit, user, status):
    doc = frappe.new_doc("PWA Notification Log")
    doc.reference_doctype = "Service Visit"
    doc.reference_name = visit.name
    doc.user = user
    doc.reminder_type = SERVICE_VISIT_REMINDER_TYPE
    doc.reminder_on = visit.reminder_on
    doc.sent_on = now_datetime()
    doc.status = status
    doc.insert(ignore_permissions=True)


def _get_service_visit_reminder_message(visit):
    parts = [
        visit.get("customer_name") or visit.name,
        visit.get("city"),
        visit.get("time")
    ]
    return " - ".join([part for part in parts if part])
