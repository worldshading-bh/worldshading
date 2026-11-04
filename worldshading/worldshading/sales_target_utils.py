# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from calendar import monthrange
from datetime import timedelta

import frappe
from frappe import _
from frappe.utils import getdate


FREQUENCY_CONFIG = (
	("Daily", "daily_target", "total_daily_target"),
	("Weekly", "weekly_target", "total_weekly_target"),
	("Monthly", "monthly_target", "total_monthly_target"),
	("Quarterly", "quarterly_target", "total_quarterly_target"),
	("Annual", "annual_target", "total_annual_target")
)


def get_frequency_config(frequency):
	for config in FREQUENCY_CONFIG:
		if config[0] == frequency:
			return config

	return None


def get_occurrence(frequency, as_of_date, plan_from_date, plan_to_date):
	config = get_frequency_config(frequency)
	if not config:
		frappe.throw(_("Select a valid Frequency."))

	plan_start = getdate(plan_from_date)
	plan_end = getdate(plan_to_date)
	as_of = getdate(as_of_date)
	not_started = as_of < plan_start
	reference_date = min(max(as_of, plan_start), plan_end)

	if frequency == "Daily":
		occurrence_start = reference_date
		occurrence_end = reference_date
	elif frequency == "Weekly":
		days_since_saturday = (reference_date.weekday() - 5) % 7
		occurrence_start = reference_date - timedelta(days=days_since_saturday)
		occurrence_end = occurrence_start + timedelta(days=6)
	elif frequency == "Monthly":
		occurrence_start = reference_date.replace(day=1)
		occurrence_end = reference_date.replace(
			day=monthrange(reference_date.year, reference_date.month)[1])
	elif frequency == "Quarterly":
		start_month = ((reference_date.month - 1) // 3) * 3 + 1
		end_month = start_month + 2
		occurrence_start = reference_date.replace(month=start_month, day=1)
		occurrence_end = reference_date.replace(
			month=end_month,
			day=monthrange(reference_date.year, end_month)[1])
	else:
		occurrence_start = plan_start
		occurrence_end = plan_end

	occurrence_start = max(occurrence_start, plan_start)
	occurrence_end = min(occurrence_end, plan_end)
	effective_to_date = (
		occurrence_start if not_started else min(as_of, occurrence_end))

	return {
		"from_date": occurrence_start,
		"to_date": occurrence_end,
		"effective_to_date": effective_to_date,
		"not_started": not_started
	}
