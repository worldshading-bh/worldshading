# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from frappe import _


def get_data():
	return [
		{
			"label": _("Campaign Management"),
			"items": [
				{
					"type": "doctype",
					"name": "Campaign Customer",
					"description": _("Plan and record customer campaign interactions.")
				},
				{
					"type": "doctype",
					"name": "Campaign",
					"description": _("Sales campaigns.")
				}
			]
		}
	]
