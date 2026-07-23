from __future__ import unicode_literals

from worldshading.dashboards.service_visit import add_service_visit


def get_data(data):
	return add_service_visit(data, merge_into_reference=True)
