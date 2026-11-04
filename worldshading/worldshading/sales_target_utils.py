# -*- coding: utf-8 -*-
from __future__ import unicode_literals


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
