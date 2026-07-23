# -*- coding: utf-8 -*-
# Copyright (c) 2026, Hilal Habeeb and contributors
# For license information, please see license.txt

from __future__ import unicode_literals

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import get_time


def format_time_12h(value):
	"""Format a datetime.time as a readable 12-hour string, e.g. 09:00 -> '9:00 AM'.

	Kept in sync with the client-side formatter in work_team.js so the live preview
	and the saved value are identical.
	"""
	hour_12 = value.hour % 12 or 12
	meridiem = "AM" if value.hour < 12 else "PM"
	return "{0}:{1:02d} {2}".format(hour_12, value.minute, meridiem)


class WorkTeam(Document):
	def validate(self):
		self.validate_working_hours()
		self.validate_duplicate_users()

	def validate_working_hours(self):
		# Keep rows in the order the user entered them (row 1, row 2, ...) for the summary.
		slots = []

		for row in self.get("working_hours") or []:
			if not row.start_time or not row.end_time:
				frappe.throw(_("Working Hours row #{0}: Start Time and End Time are required.").format(row.idx))

			start_time = get_time(row.start_time)
			end_time = get_time(row.end_time)

			if end_time <= start_time:
				frappe.throw(_("Working Hours row #{0}: End Time ({1}) must be later than Start Time ({2}).").format(
					row.idx, end_time.strftime("%H:%M"), start_time.strftime("%H:%M")))

			slots.append((start_time, end_time))

		# Overlap is checked on a time-sorted copy, but the summary keeps entry order.
		ordered = sorted(slots, key=lambda slot: slot[0])
		for i in range(1, len(ordered)):
			if ordered[i][0] < ordered[i - 1][1]:
				frappe.throw(_("Working Hours slots overlap: {0}-{1} and {2}-{3}. Please adjust the times so they do not overlap.").format(
					ordered[i - 1][0].strftime("%H:%M"), ordered[i - 1][1].strftime("%H:%M"),
					ordered[i][0].strftime("%H:%M"), ordered[i][1].strftime("%H:%M")))

		self.working_hours_summary = ", ".join(
			"{0} - {1}".format(format_time_12h(start), format_time_12h(end))
			for start, end in slots
		)

	def validate_duplicate_users(self):
		seen_users = set()

		for row in self.get("users") or []:
			if not row.user:
				continue

			if row.user in seen_users:
				frappe.throw(_("User {0} is added more than once.").format(row.user))

			seen_users.add(row.user)
