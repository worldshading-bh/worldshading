from __future__ import unicode_literals


def get_data(data):
	for group in data.get("transactions", []):
		items = group.get("items", [])
		if "Payment Entry" in items and "Journal Entry" in items:
			if "GL Payment" not in items:
				items.append("GL Payment")
			break

	return data
