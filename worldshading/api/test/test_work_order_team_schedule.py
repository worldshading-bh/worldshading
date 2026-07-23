from __future__ import unicode_literals

import unittest
from datetime import datetime, time

import frappe

from worldshading.api import work_order_team


def make_calendar(capacity=1, holidays=None, slots=None):
	if slots is None:
		# Default: single 08:00-17:00 window on every working day.
		slots = [(time(8, 0, 0), time(17, 0, 0))]
	return frappe._dict({
		"team": "Test Team",
		"capacity": capacity,
		"slots": slots,
		"work_start_time": min(slot[0] for slot in slots),
		"work_end_time": max(slot[1] for slot in slots),
		"holiday_list": None,
		"holiday_dates": set(holidays or []),
		"holiday_dates_loaded": True
	})


class TestWorkOrderTeamSchedule(unittest.TestCase):
	def setUp(self):
		self._original_get_team_calendar = work_order_team.get_team_calendar
		self._original_get_overlapping_work_orders = work_order_team.get_overlapping_work_orders
		self._original_now_datetime = work_order_team.now_datetime

	def tearDown(self):
		work_order_team.get_team_calendar = self._original_get_team_calendar
		work_order_team.get_overlapping_work_orders = self._original_get_overlapping_work_orders
		work_order_team.now_datetime = self._original_now_datetime

	def test_same_day_working_hours(self):
		calendar = make_calendar()
		result = work_order_team.get_working_intervals(
			datetime(2026, 7, 16, 8, 0),
			2,
			calendar
		)
		self.assertEqual(result.get("end"), datetime(2026, 7, 16, 10, 0))

	def test_start_before_working_hours_moves_to_day_start(self):
		calendar = make_calendar()
		result = work_order_team.get_working_intervals(
			datetime(2026, 7, 16, 6, 30),
			1,
			calendar
		)
		self.assertEqual(result.get("intervals")[0].get("start"), datetime(2026, 7, 16, 8, 0))

	def test_start_after_working_hours_moves_to_next_day(self):
		calendar = make_calendar()
		result = work_order_team.get_working_intervals(
			datetime(2026, 7, 16, 18, 0),
			1,
			calendar
		)
		self.assertEqual(result.get("intervals")[0].get("start"), datetime(2026, 7, 17, 8, 0))

	def test_decimal_hours(self):
		calendar = make_calendar()
		result = work_order_team.get_working_intervals(
			datetime(2026, 7, 16, 8, 0),
			1.5,
			calendar
		)
		self.assertEqual(result.get("end"), datetime(2026, 7, 16, 9, 30))

	def test_crosses_working_day_end(self):
		calendar = make_calendar()
		result = work_order_team.get_working_intervals(
			datetime(2026, 7, 16, 16, 0),
			3,
			calendar
		)
		self.assertEqual(result.get("end"), datetime(2026, 7, 17, 10, 0))
		self.assertEqual(len(result.get("intervals")), 2)

	def test_multi_slot_day_skips_break(self):
		# Team works 09:00-12:00 and 18:00-20:00 every working day (a break from 12:00-18:00).
		slots = [(time(9, 0), time(12, 0)), (time(18, 0), time(20, 0))]
		calendar = make_calendar(slots=slots)
		# 4 hours from 09:00: fill 09:00-12:00 (3h), then jump the break to 18:00 + 1h = 19:00.
		result = work_order_team.get_working_intervals(
			datetime(2026, 7, 16, 9, 0),
			4,
			calendar
		)
		self.assertEqual(result.get("end"), datetime(2026, 7, 16, 19, 0))
		self.assertEqual(len(result.get("intervals")), 2)
		self.assertEqual(result.get("intervals")[0].get("end"), datetime(2026, 7, 16, 12, 0))
		self.assertEqual(result.get("intervals")[1].get("start"), datetime(2026, 7, 16, 18, 0))

	def test_start_inside_break_moves_to_next_slot(self):
		slots = [(time(9, 0), time(12, 0)), (time(18, 0), time(20, 0))]
		calendar = make_calendar(slots=slots)
		result = work_order_team.get_working_intervals(
			datetime(2026, 7, 16, 14, 0),
			1,
			calendar
		)
		self.assertEqual(result.get("intervals")[0].get("start"), datetime(2026, 7, 16, 18, 0))

	def test_break_carries_across_days(self):
		# Two slots/day: 2h from the 18:00-20:00 slot start fills that slot, then next day 09:00-10:00.
		slots = [(time(9, 0), time(12, 0)), (time(18, 0), time(20, 0))]
		calendar = make_calendar(slots=slots)
		result = work_order_team.get_working_intervals(
			datetime(2026, 7, 16, 19, 0),
			2,
			calendar
		)
		self.assertEqual(result.get("end"), datetime(2026, 7, 17, 10, 0))
		self.assertEqual(len(result.get("intervals")), 2)

	def test_holiday_between_start_and_completion(self):
		calendar = make_calendar(holidays=[datetime(2026, 7, 17).date()])
		result = work_order_team.get_working_intervals(
			datetime(2026, 7, 16, 16, 0),
			3,
			calendar
		)
		self.assertEqual(result.get("end"), datetime(2026, 7, 18, 10, 0))

	def test_consecutive_holidays(self):
		calendar = make_calendar(holidays=[
			datetime(2026, 7, 17).date(),
			datetime(2026, 7, 18).date()
		])
		result = work_order_team.get_working_intervals(
			datetime(2026, 7, 16, 16, 0),
			3,
			calendar
		)
		self.assertEqual(result.get("end"), datetime(2026, 7, 19, 10, 0))

	def test_capacity_one_overlap_blocks(self):
		calendar = make_calendar(capacity=1)
		original = work_order_team.get_overlapping_work_orders

		def fake_overlaps(production_team, start_datetime, end_datetime, current_work_order=None):
			return [
				frappe._dict({
					"name": "WO-A",
					"planned_start_date": datetime(2026, 7, 16, 8, 0),
					"production_planned_end_datetime": datetime(2026, 7, 16, 10, 0),
					"estimated_hours": 2
				})
			]

		work_order_team.get_overlapping_work_orders = fake_overlaps
		try:
			result = work_order_team.validate_capacity_for_intervals(
				"Test Team",
				[{
					"start": datetime(2026, 7, 16, 9, 0),
					"end": datetime(2026, 7, 16, 11, 0)
				}],
				calendar
			)
		finally:
			work_order_team.get_overlapping_work_orders = original

		self.assertFalse(result.get("available"))

	def test_capacity_two_separate_bookings_do_not_combine(self):
		calendar = make_calendar(capacity=2)

		def fake_overlaps(production_team, start_datetime, end_datetime, current_work_order=None):
			return [
				frappe._dict({
					"name": "WO-A",
					"planned_start_date": datetime(2026, 7, 16, 8, 0),
					"production_planned_end_datetime": datetime(2026, 7, 16, 10, 0),
					"estimated_hours": 2
				}),
				frappe._dict({
					"name": "WO-B",
					"planned_start_date": datetime(2026, 7, 16, 14, 0),
					"production_planned_end_datetime": datetime(2026, 7, 16, 16, 0),
					"estimated_hours": 2
				})
			]

		work_order_team.get_overlapping_work_orders = fake_overlaps
		result = work_order_team.validate_capacity_for_intervals(
			"Test Team",
			[{
				"start": datetime(2026, 7, 16, 8, 0),
				"end": datetime(2026, 7, 16, 16, 0)
			}],
			calendar
		)

		self.assertTrue(result.get("available"))

	def test_capacity_two_simultaneous_bookings_block(self):
		calendar = make_calendar(capacity=2)

		def fake_overlaps(production_team, start_datetime, end_datetime, current_work_order=None):
			return [
				frappe._dict({
					"name": "WO-A",
					"planned_start_date": datetime(2026, 7, 16, 8, 0),
					"production_planned_end_datetime": datetime(2026, 7, 16, 10, 0),
					"estimated_hours": 2
				}),
				frappe._dict({
					"name": "WO-B",
					"planned_start_date": datetime(2026, 7, 16, 8, 0),
					"production_planned_end_datetime": datetime(2026, 7, 16, 10, 0),
					"estimated_hours": 2
				})
			]

		work_order_team.get_overlapping_work_orders = fake_overlaps
		result = work_order_team.validate_capacity_for_intervals(
			"Test Team",
			[{
				"start": datetime(2026, 7, 16, 8, 0),
				"end": datetime(2026, 7, 16, 10, 0)
			}],
			calendar
		)

		self.assertFalse(result.get("available"))

	def test_overnight_booking_uses_working_intervals_only(self):
		calendar = make_calendar(capacity=1)
		bookings = [
			frappe._dict({
				"name": "WO-A",
				"planned_start_date": datetime(2026, 7, 16, 16, 0),
				"production_planned_end_datetime": datetime(2026, 7, 17, 10, 0),
				"estimated_hours": 3
			})
		]
		intervals = work_order_team.get_booking_working_intervals(
			bookings,
			calendar,
			datetime(2026, 7, 16, 16, 0),
			datetime(2026, 7, 17, 10, 0)
		)
		self.assertEqual(intervals[0].get("start"), datetime(2026, 7, 16, 16, 0))
		self.assertEqual(intervals[0].get("end"), datetime(2026, 7, 16, 17, 0))
		self.assertEqual(intervals[1].get("start"), datetime(2026, 7, 17, 8, 0))
		self.assertEqual(intervals[1].get("end"), datetime(2026, 7, 17, 10, 0))

	def test_schedule_plan_no_bookings(self):
		work_order_team.get_team_calendar = lambda production_team, company=None: make_calendar()
		work_order_team.get_overlapping_work_orders = lambda *args, **kwargs: []
		work_order_team.now_datetime = lambda: datetime(2026, 7, 16, 7, 0)
		plan = work_order_team.get_team_schedule_plan(
			"Test Team",
			datetime(2026, 7, 16, 8, 0),
			2
		)
		self.assertEqual(plan.get("suggested_start"), "2026-07-16 08:00:00")
		self.assertEqual(plan.get("suggested_end"), "2026-07-16 10:00:00")

	def test_schedule_plan_past_requested_start_uses_current_working_time(self):
		work_order_team.get_team_calendar = lambda production_team, company=None: make_calendar()
		work_order_team.get_overlapping_work_orders = lambda *args, **kwargs: []
		work_order_team.now_datetime = lambda: datetime(2026, 7, 16, 9, 15, 45)
		plan = work_order_team.get_team_schedule_plan(
			"Test Team",
			datetime(2026, 7, 16, 8, 0),
			1
		)
		self.assertEqual(plan.get("suggested_start"), "2026-07-16 09:16:00")

	def test_schedule_plan_zero_hours_rejected(self):
		plan = work_order_team.get_team_schedule_plan(
			"Test Team",
			datetime(2026, 7, 16, 8, 0),
			0
		)
		self.assertEqual(plan.get("status"), "Not Scheduled")

	def test_schedule_plan_negative_hours_rejected(self):
		plan = work_order_team.get_team_schedule_plan(
			"Test Team",
			datetime(2026, 7, 16, 8, 0),
			-1
		)
		self.assertEqual(plan.get("status"), "Not Scheduled")

	def test_schedule_plan_team_validation_error(self):
		def invalid_team(production_team, company=None):
			frappe.throw("Work Team is disabled.")

		work_order_team.get_team_calendar = invalid_team
		plan = work_order_team.get_team_schedule_plan(
			"Test Team",
			datetime(2026, 7, 16, 8, 0),
			1
		)
		self.assertEqual(plan.get("status"), "Not Scheduled")

	def test_schedule_plan_moves_to_conflict_end(self):
		work_order_team.get_team_calendar = lambda production_team, company=None: make_calendar(capacity=1)
		work_order_team.now_datetime = lambda: datetime(2026, 7, 16, 7, 0)

		def fake_overlaps(production_team, start_datetime, end_datetime, current_work_order=None):
			if start_datetime < datetime(2026, 7, 16, 10, 0):
				return [
					frappe._dict({
						"name": "WO-A",
						"planned_start_date": datetime(2026, 7, 16, 8, 0),
						"production_planned_end_datetime": datetime(2026, 7, 16, 10, 0),
						"estimated_hours": 2
					})
				]
			return []

		work_order_team.get_overlapping_work_orders = fake_overlaps
		plan = work_order_team.get_team_schedule_plan(
			"Test Team",
			datetime(2026, 7, 16, 8, 0),
			1
		)
		self.assertEqual(plan.get("suggested_start"), "2026-07-16 10:00:00")


if __name__ == "__main__":
	unittest.main()
