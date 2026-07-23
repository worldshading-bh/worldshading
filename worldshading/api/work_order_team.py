from __future__ import unicode_literals

import json
from datetime import datetime, time, timedelta

import frappe
from frappe import _
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.utils import add_days, cint, flt, get_datetime, getdate, now_datetime


WORK_ORDER_SCHEDULING_FIELDS = {
	"Work Order": [
		{
			"fieldname": "production_scheduling_section",
			"label": "Production Scheduling",
			"fieldtype": "Section Break",
			"insert_after": "production_progress_percent",
			"allow_on_submit": 1
		},
		{
			"fieldname": "production_priority",
			"label": "Production Priority",
			"fieldtype": "Select",
			"options": "\nLow\nMedium\nHigh\nUrgent",
			"default": "Medium",
			"insert_after": "production_scheduling_section",
			"allow_on_submit": 1,
			"in_standard_filter": 1
		},
		{
			"fieldname": "estimated_hours",
			"label": "Estimated Hours",
			"fieldtype": "Float",
			"insert_after": "production_priority",
			"allow_on_submit": 1
		},
		{
			"fieldname": "production_scheduling_column_break",
			"fieldtype": "Column Break",
			"insert_after": "estimated_hours",
			"allow_on_submit": 1
		},
		{
			"fieldname": "production_planned_end_datetime",
			"label": "Planned Completion Datetime",
			"fieldtype": "Datetime",
			"insert_after": "production_scheduling_column_break",
			"allow_on_submit": 1
		},
		{
			"fieldname": "team_booking_status",
			"label": "Team Booking Status",
			"fieldtype": "Select",
			"options": "\nNot Scheduled\nAvailable\nOverbooked",
			"default": "Not Scheduled",
			"insert_after": "production_planned_end_datetime",
			"read_only": 1,
			"allow_on_submit": 1,
			"in_standard_filter": 1
		},
		{
			"fieldname": "team_booking_message",
			"label": "Team Booking Message",
			"fieldtype": "Small Text",
			"insert_after": "team_booking_status",
			"read_only": 1,
			"allow_on_submit": 1
		}
	]
}

NON_CAPACITY_WORKFLOW_STATES = (
	"Pending Schedule",
	"Completed",
	"Cancelled",
	"Stopped",
	"Paused"
)

SCHEDULE_SEARCH_DAYS = 365
DEFAULT_WORK_START_TIME = time(8, 0, 0)
DEFAULT_WORK_END_TIME = time(17, 0, 0)


@frappe.whitelist()
def setup_work_order_scheduling_fields():
	create_custom_fields(WORK_ORDER_SCHEDULING_FIELDS, update=True)
	frappe.clear_cache(doctype="Work Order")
	return True


@frappe.whitelist()
def get_production_team_users(production_team, include_unavailable=0):
	if not production_team:
		return []

	team = frappe.get_doc("Work Team", production_team)
	if team.disabled:
		frappe.throw(_("Work Team {0} is disabled.").format(production_team))

	users = []
	for row in team.get("users") or []:
		if not row.available and not cint(include_unavailable):
			continue

		users.append({
			"user": row.user,
			"full_name": row.full_name,
			"role": row.role,
			"available": row.available
		})

	return users


def validate_work_order_team(doc, method=None):
	update_team_booking_status(doc)


def update_work_order_state(doc, method=None):
	if not doc.get("work_order"):
		return

	if doc.get("purpose") == "Material Transfer for Manufacture":
		update_work_order_ready_to_start(doc)
	elif doc.get("purpose") == "Manufacture":
		update_work_order_completed(doc)


def update_work_order_ready_to_start(doc):
	work_order = frappe.get_doc("Work Order", doc.work_order)

	if work_order.docstatus != 1:
		return

	if work_order.get("workflow_state") != "Pending Material Transfer":
		return

	work_order.db_set("workflow_state", "Ready to Start", update_modified=True)
	work_order.notify_update()


def update_work_order_completed(doc):
	work_order = frappe.get_doc("Work Order", doc.work_order)

	if work_order.docstatus != 1:
		return

	if work_order.get("workflow_state") != "In Progress":
		return

	work_order.db_set("workflow_state", "Completed", update_modified=True)
	work_order.notify_update()


@frappe.whitelist()
def check_team_booking(doc):
	if isinstance(doc, str):
		doc = frappe._dict(json.loads(doc))
	else:
		doc = frappe._dict(doc)

	return get_team_booking_status(doc)


@frappe.whitelist()
def get_team_booking_dialog_data(work_order, production_team=None, planned_start_date=None,
		estimated_hours=None, production_planned_end_datetime=None, production_priority=None):
	doc = frappe.get_doc("Work Order", work_order)
	test_doc = frappe._dict(doc.as_dict())

	if production_team is not None:
		test_doc.production_team = production_team
	if planned_start_date is not None:
		test_doc.planned_start_date = planned_start_date
	if estimated_hours is not None:
		test_doc.estimated_hours = estimated_hours
	if production_priority is not None:
		test_doc.production_priority = production_priority

	selected_team_plan = get_team_schedule_plan(
		test_doc.get("production_team"),
		test_doc.get("planned_start_date"),
		test_doc.get("estimated_hours"),
		test_doc.get("name"),
		test_doc.get("company")
	) if test_doc.get("production_team") else {}

	current_status = get_status_from_plan(selected_team_plan)
	schedule_date = selected_team_plan.get("suggested_start") or test_doc.get("planned_start_date")

	return {
		"current_status": current_status,
		"selected_team_plan": selected_team_plan,
		"blocking_work_orders": selected_team_plan.get("blocking_work_orders") or [],
		"schedule_rows": get_team_day_schedule(
			test_doc.get("production_team"),
			schedule_date,
			test_doc.get("name")
		),
		"same_sales_order_work_orders": get_same_sales_order_work_orders(doc),
		"team_calendar": selected_team_plan.get("team_calendar") or {}
	}


@frappe.whitelist()
def assign_team_schedule(work_order, production_team, selected_start_datetime=None,
		estimated_hours=None, production_priority=None):
	if not production_team:
		frappe.throw(_("Please select a Work Team."))

	if not selected_start_datetime:
		frappe.throw(_("Please calculate and select a production schedule first."))

	doc = frappe.get_doc("Work Order", work_order)
	validate_work_order_is_schedulable(doc)

	plan = get_team_schedule_plan(
		production_team,
		selected_start_datetime,
		estimated_hours,
		doc.name,
		doc.get("company")
	)

	if not plan.get("suggested_start") or plan.get("status") != "Available":
		frappe.throw(plan.get("message") or _("Selected production slot is not available. Please check schedule again."))

	selected_start = to_datetime_string(selected_start_datetime)
	suggested_start = to_datetime_string(plan.get("suggested_start"))
	if selected_start != suggested_start:
		frappe.throw(_("Selected slot is no longer available. Please check schedule again. Suggested start is {0}.")
			.format(suggested_start))

	doc.production_team = production_team
	set_doc_date_or_datetime(doc, "planned_start_date", plan.get("suggested_start"))
	doc.estimated_hours = flt(estimated_hours)
	doc.production_priority = production_priority or doc.get("production_priority") or "Medium"
	set_work_order_schedule_end(doc, plan.get("suggested_end"))
	load_team_users_to_work_order(doc, production_team)
	update_team_booking_status(doc)

	# Only update WIP Warehouse while the WO is a draft; never change it after submit.
	team_warehouse = get_team_warehouse(production_team)
	if team_warehouse and doc.meta.has_field("wip_warehouse") and doc.docstatus == 0:
		doc.wip_warehouse = team_warehouse

	doc.flags.ignore_permissions = True
	doc.save(ignore_permissions=True)

	return {
		"work_orders": [doc.name],
		"wip_warehouse": doc.get("wip_warehouse")
	}


def get_team_warehouse(production_team):
	if not production_team or not frappe.db.has_column("Work Team", "warehouse"):
		return None

	return frappe.db.get_value("Work Team", production_team, "warehouse")


def update_team_booking_status(doc):
	if not doc.meta.has_field("team_booking_status"):
		return

	status = get_team_booking_status(doc)
	doc.team_booking_status = status.get("status")
	doc.team_booking_message = status.get("message")


def load_team_users_to_work_order(doc, production_team):
	doc.set("production_team_users", [])

	for row in get_production_team_users(production_team):
		doc.append("production_team_users", row)


def get_team_booking_status(doc):
	if not doc.get("production_team"):
		return {
			"status": "Not Scheduled",
			"message": "Select a Work Team.",
			"end_datetime": get_effective_schedule_end(doc)
		}

	start_datetime = doc.get("planned_start_date")
	estimated_hours = flt(doc.get("estimated_hours"))

	if not start_datetime or not estimated_hours:
		return {
			"status": "Not Scheduled",
			"message": "Set Estimated Hours and Planned Start.",
			"end_datetime": get_effective_schedule_end(doc)
		}

	plan = get_team_schedule_plan(
		doc.get("production_team"),
		start_datetime,
		estimated_hours,
		doc.get("name"),
		doc.get("company"),
		allow_past_start=True
	)

	if not plan.get("suggested_start"):
		return {
			"status": "Overbooked",
			"message": plan.get("message") or "Team capacity is not available.",
			"end_datetime": plan.get("suggested_end")
		}

	if to_datetime_string(plan.get("suggested_start")) != to_datetime_string(start_datetime):
		return {
			"status": "Overbooked",
			"message": plan.get("requested_conflict_message") or "Team capacity is not available for the stored schedule.",
			"end_datetime": plan.get("suggested_end")
		}

	return {
		"status": "Available",
		"message": "Team capacity is available for the confirmed working intervals.",
		"end_datetime": plan.get("suggested_end")
	}


def get_status_from_plan(plan):
	if not plan:
		return {
			"status": "Not Scheduled",
			"message": "Set Estimated Hours and Planned Start."
		}

	if not plan.get("suggested_start"):
		return {
			"status": "Overbooked" if plan.get("status") == "Overbooked" else "Not Scheduled",
			"message": plan.get("message") or "No available slot found.",
			"end_datetime": plan.get("suggested_end")
		}

	return {
		"status": plan.get("status") or "Available",
		"message": plan.get("message"),
		"end_datetime": plan.get("suggested_end")
	}


def get_team_availability_rows(doc):
	teams = frappe.get_all(
		"Work Team",
		filters={"disabled": 0},
		fields=[
			"name",
			"team_name",
			"warehouse",
			"team_size",
			"operation_type",
			"max_concurrent_work_orders"
		],
		order_by="team_name asc"
	)

	rows = []

	for team in teams:
		test_doc = frappe._dict(doc.as_dict() if hasattr(doc, "as_dict") else dict(doc))
		test_doc.production_team = team.name
		plan = get_team_schedule_plan(
			team.name,
			test_doc.get("planned_start_date"),
			test_doc.get("estimated_hours"),
			test_doc.get("name"),
			test_doc.get("company")
		)

		if plan.get("suggested_start"):
			test_doc.planned_start_date = plan.get("suggested_start")
			test_doc.production_planned_end_datetime = plan.get("suggested_end")

		status = get_team_booking_status(test_doc)
		overlaps = get_overlapping_work_orders(
			team.name,
			plan.get("suggested_start") or test_doc.get("planned_start_date"),
			plan.get("suggested_end") or status.get("end_datetime"),
			test_doc.get("name")
		)

		rows.append({
			"name": team.name,
			"team_name": team.team_name or team.name,
			"warehouse": team.warehouse,
			"team_size": team.team_size,
			"operation_type": team.operation_type,
			"capacity": int(team.max_concurrent_work_orders or 1),
			"used_capacity": len(overlaps) + 1 if status.get("status") in ("Available", "Overbooked") else len(overlaps),
			"status": status.get("status"),
			"message": status.get("message"),
			"end_datetime": plan.get("suggested_end") or status.get("end_datetime"),
			"suggested_start": plan.get("suggested_start"),
			"suggested_end": plan.get("suggested_end"),
			"requested_start": plan.get("requested_start"),
			"wait_hours": plan.get("wait_hours"),
			"schedule_note": plan.get("message"),
			"overlaps": overlaps
		})

	return rows


def get_recommended_team(teams):
	available_teams = [team for team in teams if team.get("suggested_start") and team.get("suggested_end")]
	if not available_teams:
		return None

	available_teams = sorted(
		available_teams,
		key=lambda team: (
			get_datetime(team.get("suggested_end")),
			get_datetime(team.get("suggested_start")),
			len(team.get("overlaps") or []),
			team.get("used_capacity") or 0,
			team.get("team_name") or team.get("name")
		)
	)

	return available_teams[0]


def get_team_schedule_plan(production_team, requested_start, estimated_hours, current_work_order=None,
		company=None, allow_past_start=False):
	if not production_team:
		return {
			"status": "Not Scheduled",
			"message": "Select a Work Team."
		}

	if not requested_start:
		return {
			"status": "Not Scheduled",
			"message": "Set Planned Start to calculate team schedule."
		}

	if flt(estimated_hours) <= 0:
		return {
			"status": "Not Scheduled",
			"requested_start": requested_start,
			"message": "Estimated Hours must be greater than zero."
		}

	try:
		calendar = get_team_calendar(production_team, company)
	except Exception as exc:
		return {
			"status": "Not Scheduled",
			"requested_start": requested_start,
			"message": str(exc)
		}

	requested_datetime = normalize_datetime(requested_start)
	now_value = normalize_datetime(now_datetime(), round_up=True)
	effective_start = requested_datetime
	reasons = []
	if not allow_past_start and requested_datetime < now_value:
		effective_start = now_value
		reasons.append("Requested start has passed. Scheduling started from the current valid working time.")

	start_datetime = move_into_working_time(effective_start, calendar, reasons)
	candidate_start = start_datetime
	search_until = requested_datetime + timedelta(days=SCHEDULE_SEARCH_DAYS)
	requested_slot_available = None
	requested_blocking = []
	requested_conflict_message = ""

	for _idx in range(SCHEDULE_SEARCH_DAYS * 4):
		if candidate_start > search_until:
			break

		interval_data = get_working_intervals(candidate_start, estimated_hours, calendar, search_until)
		candidate_end = interval_data.get("end")
		working_intervals = interval_data.get("intervals") or []
		if not candidate_end or not working_intervals or candidate_end > search_until:
			break

		capacity_result = validate_capacity_for_intervals(
			production_team,
			working_intervals,
			calendar,
			current_work_order
		)

		if requested_slot_available is None:
			requested_slot_available = capacity_result.get("available")
			requested_blocking = capacity_result.get("blocking_work_orders") or []
			if not requested_slot_available and capacity_result.get("conflict_start") and capacity_result.get("conflict_end"):
				requested_conflict_message = "Team capacity is full during {0}-{1}.".format(
					format_datetime_for_message(capacity_result.get("conflict_start")),
					format_datetime_for_message(capacity_result.get("conflict_end"))
				)

		if capacity_result.get("available"):
			wait_hours = (candidate_start - requested_datetime).total_seconds() / 3600.0
			message = "Earliest available slot."
			if requested_slot_available is False:
				message = "Team is busy at requested time. Suggested earliest available slot."
			elif reasons:
				message = reasons[-1]

			return {
				"status": "Available",
				"requested_start": to_datetime_string(requested_datetime),
				"effective_start": to_datetime_string(start_datetime),
				"suggested_start": to_datetime_string(candidate_start),
				"suggested_end": to_datetime_string(candidate_end),
				"estimated_hours": flt(estimated_hours),
				"team": production_team,
				"capacity": calendar.get("capacity"),
				"working_start_time": format_time_value(calendar.get("work_start_time")),
				"working_end_time": format_time_value(calendar.get("work_end_time")),
				"holiday_list": calendar.get("holiday_list"),
				"requested_slot_available": requested_slot_available,
				"wait_hours": flt(wait_hours, 2),
				"reasons": reasons,
				"blocking_work_orders": requested_blocking,
				"requested_conflict_message": requested_conflict_message,
				"working_intervals": serialize_intervals(working_intervals),
				"team_calendar": get_team_calendar_summary(calendar),
				"message": message
			}

		conflict_end = capacity_result.get("conflict_end")
		next_start = move_into_working_time(conflict_end or (candidate_start + timedelta(minutes=1)), calendar, reasons)
		if next_start <= candidate_start:
			next_start = move_into_working_time(candidate_start + timedelta(minutes=1), calendar, reasons)
		candidate_start = next_start

	return {
		"status": "Overbooked",
		"requested_start": to_datetime_string(requested_datetime),
		"effective_start": to_datetime_string(start_datetime),
		"estimated_hours": flt(estimated_hours),
		"team": production_team,
		"capacity": calendar.get("capacity"),
		"working_start_time": format_time_value(calendar.get("work_start_time")),
		"working_end_time": format_time_value(calendar.get("work_end_time")),
		"holiday_list": calendar.get("holiday_list"),
		"requested_slot_available": False,
		"reasons": reasons,
		"blocking_work_orders": requested_blocking,
		"team_calendar": get_team_calendar_summary(calendar),
		"message": "No available slot found in the next schedule window."
	}


def strip_microseconds(value):
	if not value:
		return value

	return get_datetime(value).replace(microsecond=0)


def normalize_datetime(value, round_up=False):
	current = strip_microseconds(value)
	if round_up and (get_datetime(value).second or get_datetime(value).microsecond):
		current = current + timedelta(minutes=1)
	return current.replace(second=0, microsecond=0)


def to_datetime_string(value):
	if not value:
		return ""

	return normalize_datetime(value).strftime("%Y-%m-%d %H:%M:%S")


def format_datetime_for_message(value):
	if not value:
		return ""

	return normalize_datetime(value).strftime("%d %b %Y, %I:%M %p")


def serialize_intervals(intervals):
	return [{
		"start": to_datetime_string(row.get("start")),
		"end": to_datetime_string(row.get("end"))
	} for row in intervals or []]


def add_working_hours(start_datetime, hours, work_start_time, work_end_time, holiday_list=None):
	calendar = frappe._dict({
		"slots": [(work_start_time, work_end_time)],
		"holiday_dates": get_holiday_dates(holiday_list, getdate(start_datetime),
			getdate(start_datetime) + timedelta(days=SCHEDULE_SEARCH_DAYS))
	})
	result = get_working_intervals(start_datetime, hours, calendar,
		get_datetime(start_datetime) + timedelta(days=SCHEDULE_SEARCH_DAYS))
	return result.get("end")


def get_working_intervals(start_datetime, hours, calendar, search_until=None):
	remaining_minutes = int(round(flt(hours) * 60))
	current = move_into_working_time(start_datetime, calendar)
	intervals = []
	guard = 0
	search_until = search_until or current + timedelta(days=SCHEDULE_SEARCH_DAYS)

	while remaining_minutes > 0 and guard < SCHEDULE_SEARCH_DAYS * 6:
		guard += 1
		if current > search_until:
			break

		segment_end = get_current_segment_end(current, calendar)
		available_minutes = int((segment_end - current).total_seconds() / 60)

		if available_minutes <= 0:
			current = move_into_working_time(current + timedelta(minutes=1), calendar)
			continue

		interval_start = current
		if remaining_minutes <= available_minutes:
			interval_end = current + timedelta(minutes=remaining_minutes)
			intervals.append({"start": interval_start, "end": interval_end})
			return {
				"start": normalize_datetime(start_datetime),
				"end": interval_end,
				"intervals": intervals
			}

		intervals.append({"start": interval_start, "end": segment_end})
		remaining_minutes -= available_minutes
		current = move_into_working_time(segment_end + timedelta(minutes=1), calendar)

	return {
		"start": normalize_datetime(start_datetime),
		"end": current if remaining_minutes <= 0 else None,
		"intervals": intervals
	}


def append_reason(reasons, message):
	if not reasons or reasons[-1] != message:
		reasons.append(message)


def move_into_working_time(value, calendar, reasons=None):
	current = normalize_datetime(value)
	reasons = reasons if reasons is not None else []
	guard = 0

	while guard < SCHEDULE_SEARCH_DAYS + 5:
		guard += 1

		if is_holiday(calendar, current.date()):
			append_reason(reasons, "Requested start was moved because {0} is a holiday or weekly off.".format(current.date()))
			current = datetime.combine(current.date() + timedelta(days=1), time(0, 0, 0))
			continue

		segments = get_day_segments(current.date(), calendar)
		if not segments:
			append_reason(reasons, "Requested start was moved because {0} is a non-working day for the team.".format(current.date()))
			current = datetime.combine(current.date() + timedelta(days=1), time(0, 0, 0))
			continue

		for segment in segments:
			if current < segment["start"]:
				append_reason(reasons, "Requested start was outside working hours and was moved to the next working slot.")
				return segment["start"]
			if current < segment["end"]:
				return current

		# Past the last slot of the day; continue from the start of the next day.
		current = datetime.combine(current.date() + timedelta(days=1), time(0, 0, 0))

	return current


def get_team_calendar(production_team, company=None):
	if not frappe.db.exists("Work Team", production_team):
		frappe.throw(_("Work Team {0} not found.").format(production_team))

	fields = [
		"name",
		"team_name",
		"disabled",
		"max_concurrent_work_orders"
	]
	if frappe.db.has_column("Work Team", "holiday_list"):
		fields.append("holiday_list")
	if frappe.db.has_column("Work Team", "warehouse"):
		fields.append("warehouse")
	if frappe.db.has_column("Work Team", "team_size"):
		fields.append("team_size")
	if frappe.db.has_column("Work Team", "operation_type"):
		fields.append("operation_type")

	team = frappe.db.get_value("Work Team", production_team, fields, as_dict=True)
	if not team:
		frappe.throw(_("Work Team {0} not found.").format(production_team))
	if cint(team.get("disabled")):
		frappe.throw(_("Work Team {0} is disabled.").format(production_team))

	slots = get_team_working_slots(production_team)
	if not slots:
		frappe.throw(_("Work Team {0} has no working hours defined. Add rows in the Working Hours table.").format(production_team))

	work_start_time = min(slot[0] for slot in slots)
	work_end_time = max(slot[1] for slot in slots)

	capacity = cint(team.get("max_concurrent_work_orders")) or 1
	if capacity < 1:
		capacity = 1

	holiday_list = get_production_team_holiday_list(team, company)

	return frappe._dict({
		"team": production_team,
		"team_name": team.get("team_name") or production_team,
		"capacity": capacity,
		"slots": slots,
		"work_start_time": work_start_time,
		"work_end_time": work_end_time,
		"holiday_list": holiday_list,
		"warehouse": team.get("warehouse"),
		"team_size": team.get("team_size"),
		"operation_type": team.get("operation_type")
	})


def get_team_working_slots(production_team):
	"""Return a sorted list of [(start_time, end_time), ...] from the team's Working Hours table.

	The same slots apply to every working day (non-working days come from the Holiday List).
	Rows are sorted and validated so each slot ends after it starts and slots do not overlap.
	Multiple rows model breaks within a day (e.g. 09:00-12:00 and 18:00-20:00).
	"""
	rows = frappe.get_all(
		"Work Team Timing",
		filters={"parent": production_team, "parenttype": "Work Team", "parentfield": "working_hours"},
		fields=["start_time", "end_time"]
	)

	slots = []
	for row in rows:
		start_time = parse_time_value(row.get("start_time"), None)
		end_time = parse_time_value(row.get("end_time"), None)
		if not start_time or not end_time or end_time <= start_time:
			frappe.throw(_("Work Team {0} has an invalid working-hours row (end time must be later than start time).").format(production_team))
		slots.append((start_time, end_time))

	slots.sort(key=lambda slot: slot[0])
	for i in range(1, len(slots)):
		if slots[i][0] < slots[i - 1][1]:
			frappe.throw(_("Work Team {0} has overlapping working-hours slots.").format(production_team))

	return slots


def get_team_calendar_summary(calendar):
	return {
		"team": calendar.get("team"),
		"team_name": calendar.get("team_name"),
		"capacity": calendar.get("capacity"),
		"working_start_time": format_time_value(calendar.get("work_start_time")),
		"working_end_time": format_time_value(calendar.get("work_end_time")),
		"working_slots": format_working_slots(calendar),
		"holiday_list": calendar.get("holiday_list"),
		"warehouse": calendar.get("warehouse"),
		"team_size": calendar.get("team_size"),
		"operation_type": calendar.get("operation_type")
	}


def format_working_slots(calendar):
	"""Human-readable working slots, e.g. ["09:00-12:00", "18:00-20:00"]."""
	return [
		"{0}-{1}".format(format_time_value(start), format_time_value(end))
		for start, end in (calendar.get("slots") or [])
	]


def get_production_team_holiday_list(team, company=None):
	if team.get("holiday_list"):
		return team.get("holiday_list")

	holiday_list = None

	if company:
		holiday_list = frappe.db.get_value("Company", company, "default_holiday_list")

	if not holiday_list:
		holiday_list = frappe.db.get_value("Holiday List", {"is_default": 1}, "name")

	return holiday_list


def get_holiday_dates(holiday_list, start_date=None, end_date=None):
	if not holiday_list or not start_date or not end_date:
		return set()

	rows = frappe.get_all(
		"Holiday",
		filters={
			"parent": holiday_list,
			"holiday_date": ["between", [getdate(start_date), getdate(end_date)]]
		},
		fields=["holiday_date"]
	)
	return set([getdate(row.holiday_date) for row in rows])


def ensure_calendar_holidays(calendar, start_datetime, end_datetime):
	if calendar.get("holiday_dates_loaded"):
		return

	calendar.holiday_dates = get_holiday_dates(
		calendar.get("holiday_list"),
		getdate(start_datetime),
		getdate(end_datetime)
	)
	calendar.holiday_dates_loaded = True


def is_holiday(calendar, date_value):
	holiday_list = calendar.get("holiday_list")
	if not holiday_list and "holiday_dates" not in calendar:
		return False

	if "holiday_dates" not in calendar:
		calendar.holiday_dates = get_holiday_dates(
			holiday_list,
			getdate(date_value) - timedelta(days=1),
			getdate(date_value) + timedelta(days=SCHEDULE_SEARCH_DAYS)
		)

	return getdate(date_value) in calendar.get("holiday_dates")


def get_day_segments(date_value, calendar):
	"""Concrete datetime segments (sorted) for the team's slots on the given date.

	The same slots apply to every day; holidays are filtered separately via is_holiday.
	"""
	day = getdate(date_value)
	segments = [
		{
			"start": datetime.combine(day, start_time),
			"end": datetime.combine(day, end_time)
		}
		for start_time, end_time in (calendar.get("slots") or [])
	]
	segments.sort(key=lambda segment: segment["start"])
	return segments


def get_current_segment_end(current, calendar):
	"""End datetime of the working slot that `current` falls inside (else `current`)."""
	for segment in get_day_segments(current.date(), calendar):
		if segment["start"] <= current < segment["end"]:
			return segment["end"]
	return current


def validate_capacity_for_intervals(production_team, proposed_intervals, calendar, current_work_order=None):
	if not proposed_intervals:
		return {
			"available": False,
			"blocking_work_orders": [],
			"conflict_end": None
		}

	window_start = min([row.get("start") for row in proposed_intervals])
	window_end = max([row.get("end") for row in proposed_intervals])
	bookings = get_overlapping_work_orders(production_team, window_start, window_end, current_work_order)
	booking_intervals = get_booking_working_intervals(bookings, calendar, window_start, window_end)
	capacity = cint(calendar.get("capacity")) or 1

	for proposed in proposed_intervals:
		points = [proposed.get("start"), proposed.get("end")]
		for row in booking_intervals:
			if row.get("start") < proposed.get("end") and row.get("end") > proposed.get("start"):
				points.append(max(row.get("start"), proposed.get("start")))
				points.append(min(row.get("end"), proposed.get("end")))

		points = sorted(set(points))
		for idx in range(len(points) - 1):
			segment_start = points[idx]
			segment_end = points[idx + 1]
			if segment_start >= segment_end:
				continue

			active = []
			for row in booking_intervals:
				if row.get("start") < segment_end and row.get("end") > segment_start:
					active.append(row)

			if len(active) + 1 > capacity:
				# Paused Work Orders continue occupying their existing planned capacity in this version.
				blocking = get_unique_booking_rows(active)
				conflict_end = min([row.get("end") for row in active if row.get("end")] or [segment_end])
				return {
					"available": False,
					"blocking_work_orders": blocking,
					"conflict_start": segment_start,
					"conflict_end": conflict_end
				}

	return {
		"available": True,
		"blocking_work_orders": [],
		"conflict_end": None
	}


def get_booking_working_intervals(bookings, calendar, window_start, window_end):
	out = []
	search_until = get_datetime(window_end) + timedelta(days=1)

	for booking in bookings:
		start = get_datetime(booking.planned_start_date)
		end = get_datetime(booking.production_planned_end_datetime)
		intervals = []

		if flt(booking.get("estimated_hours")) > 0:
			result = get_working_intervals(start, booking.get("estimated_hours"), calendar, search_until)
			intervals = result.get("intervals") or []

		if not intervals:
			intervals = [{"start": start, "end": end}]

		for interval in intervals:
			interval_start = max(interval.get("start"), get_datetime(window_start))
			interval_end = min(interval.get("end"), get_datetime(window_end))
			if interval_start < interval_end:
				out.append({
					"start": interval_start,
					"end": interval_end,
					"booking": booking
				})

	return out


def get_unique_booking_rows(intervals):
	rows = []
	seen = set()
	for interval in intervals:
		booking = interval.get("booking")
		if not booking or booking.name in seen:
			continue
		seen.add(booking.name)
		rows.append(booking)
	return rows


def parse_time_value(value, default_value):
	if not value:
		return default_value

	if isinstance(value, time):
		return value

	if isinstance(value, timedelta):
		total_seconds = int(value.total_seconds())
		hours = total_seconds // 3600
		minutes = (total_seconds % 3600) // 60
		seconds = total_seconds % 60
		return time(hours % 24, minutes, seconds)

	if isinstance(value, str):
		parts = value.split(":")
		try:
			return time(int(parts[0]), int(parts[1]), int(float(parts[2])) if len(parts) > 2 else 0)
		except Exception:
			return default_value

	return default_value


def format_time_value(value):
	parsed = parse_time_value(value, None)
	if not parsed:
		return ""

	return parsed.strftime("%H:%M")


def get_team_day_schedule(production_team, planned_start_date, current_work_order=None):
	if not production_team or not planned_start_date:
		return []

	day_start = datetime.combine(getdate(planned_start_date), time(0, 0, 0))
	day_end = day_start + timedelta(days=1)
	end_expression = get_work_order_end_datetime_expression()
	active_condition = get_active_work_order_condition()

	return frappe.db.sql("""
		select
			name,
			production_item,
			qty,
			produced_qty,
			status,
			workflow_state,
			sales_order,
			estimated_hours,
			planned_start_date,
			{end_expression} as production_planned_end_datetime,
			production_priority,
			team_booking_status
		from `tabWork Order`
		where production_team = %s
			and docstatus = 1
			and {active_condition}
			and ifnull(planned_start_date, '') != ''
			and ifnull({end_expression}, '') != ''
			and planned_start_date < %s
			and {end_expression} > %s
			and name != %s
		order by planned_start_date asc
	""".format(end_expression=end_expression, active_condition=active_condition), (
		production_team,
		day_end,
		day_start,
		current_work_order or ""
	), as_dict=True)


def get_selected_team_schedule_rows(doc, selected_team_plan, current_status):
	if not doc.get("production_team") or not doc.get("planned_start_date"):
		return []

	rows = get_team_day_schedule(
		doc.get("production_team"),
		selected_team_plan.get("suggested_start") or doc.get("planned_start_date"),
		doc.get("name")
	)

	return sorted(
		rows,
		key=lambda row: get_datetime(row.get("planned_start_date")) if row.get("planned_start_date") else datetime.max
	)


def set_doc_date_or_datetime(doc, fieldname, value):
	if not value or not doc.meta.has_field(fieldname):
		return

	field = doc.meta.get_field(fieldname)
	if field and field.fieldtype == "Date":
		doc.set(fieldname, getdate(value))
	else:
		doc.set(fieldname, to_datetime_string(value))


def get_effective_schedule_end(doc):
	if doc.get("planned_end_date"):
		return doc.get("planned_end_date")
	if doc.get("production_planned_end_datetime"):
		return doc.get("production_planned_end_datetime")
	return None


def set_work_order_schedule_end(doc, value):
	if not value:
		return

	set_doc_date_or_datetime(doc, "planned_end_date", value)
	set_doc_date_or_datetime(doc, "production_planned_end_datetime", value)


def validate_work_order_is_schedulable(doc):
	if doc.docstatus == 2:
		frappe.throw(_("Cancelled Work Orders cannot be scheduled."))

	if doc.get("workflow_state") in ("Completed", "Cancelled", "Stopped"):
		frappe.throw(_("Work Order cannot be scheduled while it is {0}.").format(doc.get("workflow_state")))

	if not doc.get("workflow_state") and doc.get("status") in ("Completed", "Cancelled", "Stopped"):
		frappe.throw(_("Work Order cannot be scheduled while it is {0}.").format(doc.get("status")))


def get_same_sales_order_work_orders(doc):
	if not doc.get("sales_order"):
		return []

	rows = frappe.get_all(
		"Work Order",
		filters={
			"sales_order": doc.sales_order,
			"name": ["!=", doc.name],
			"docstatus": ["<", 2]
		},
		fields=[
			"name",
			"production_item",
			"qty",
			"produced_qty",
			"status",
			"production_team",
			"planned_start_date",
			"production_planned_end_datetime",
			"team_booking_status"
		],
		order_by="creation asc"
	)

	return rows

def get_planned_end_datetime(doc):
	end_datetime = get_effective_schedule_end(doc)
	if end_datetime:
		return end_datetime

	if not doc.get("planned_start_date") or not flt(doc.get("estimated_hours")):
		return end_datetime

	if not doc.get("production_team"):
		return None

	calendar = get_team_calendar(doc.get("production_team"), doc.get("company"))
	result = get_working_intervals(doc.get("planned_start_date"), doc.get("estimated_hours"),
		calendar, get_datetime(doc.get("planned_start_date")) + timedelta(days=SCHEDULE_SEARCH_DAYS))
	return result.get("end")


def get_team_capacity(production_team):
	capacity = frappe.db.get_value("Work Team", production_team, "max_concurrent_work_orders")
	return int(capacity or 1)


def get_overlapping_work_order_count(production_team, start_datetime, end_datetime, current_work_order=None):
	return len(get_overlapping_work_orders(production_team, start_datetime, end_datetime, current_work_order))


def get_overlapping_work_orders(production_team, start_datetime, end_datetime, current_work_order=None):
	if not start_datetime or not end_datetime:
		return []
	end_expression = get_work_order_end_datetime_expression()
	active_condition = get_active_work_order_condition()

	return frappe.db.sql("""
		select
			name,
			production_item,
			qty,
			produced_qty,
			status,
			workflow_state,
			sales_order,
			estimated_hours,
			planned_start_date,
			{end_expression} as production_planned_end_datetime,
			production_priority
		from `tabWork Order`
		where production_team = %s
			and docstatus = 1
			and {active_condition}
			and ifnull(planned_start_date, '') != ''
			and ifnull({end_expression}, '') != ''
			and planned_start_date < %s
			and {end_expression} > %s
			and name != %s
		order by planned_start_date asc
	""".format(end_expression=end_expression, active_condition=active_condition), (
		production_team,
		end_datetime,
		start_datetime,
		current_work_order or ""
	), as_dict=True)


def get_work_order_end_datetime_expression():
	has_planned_end = frappe.db.has_column("Work Order", "planned_end_date")
	has_custom_end = frappe.db.has_column("Work Order", "production_planned_end_datetime")

	if has_planned_end and has_custom_end:
		return "coalesce(planned_end_date, production_planned_end_datetime)"
	if has_planned_end:
		return "planned_end_date"
	if has_custom_end:
		return "production_planned_end_datetime"

	return "null"


def get_active_work_order_condition():
	if frappe.db.has_column("Work Order", "workflow_state"):
		states = ", ".join(["'{0}'".format(state.replace("'", "''")) for state in NON_CAPACITY_WORKFLOW_STATES])
		return """(
			ifnull(workflow_state, '') = ''
			or workflow_state not in ({states})
		)""".format(states=states)

	statuses = ", ".join(["'{0}'".format(status.replace("'", "''")) for status in NON_CAPACITY_WORKFLOW_STATES])
	return "ifnull(status, '') not in ({0})".format(statuses)


