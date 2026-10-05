from __future__ import unicode_literals

from decimal import Decimal
from uuid import uuid4

import frappe
from frappe.utils import add_days, cint, escape_html, now, nowdate


def render_item_price_changes(changes):
	"""Show changed price lists side by side without mixing different UOMs."""
	groups = {}
	price_lists = {}
	for change in changes:
		price_list = change["price_list"]
		price_lists[price_list] = change.get("price_kind") or price_list
		key = (change["item_code"], change.get("uom") or "")
		group = groups.setdefault(key, {"name": change.get("item_name") or key[0], "prices": {}})
		group["prices"][price_list] = change["new_rate"]
	columns = sorted(price_lists, key=lambda name: (
		{"Regular": 0, "B2B": 1}.get(price_lists[name], 2), name))
	if not columns:
		return ""
	price_width = 32.0 / len(columns)
	headings = [("Item", 14), ("Item Name", 44), ("UOM", 10)] + [
		(name + " Price" if name in ("Regular", "B2B") else name, price_width) for name in columns]
	headers = []
	for index, (label, width) in enumerate(headings):
		headers.append(
			'<th style="width: {0}%; padding: 8px 6px; text-align: {1}; '
			'border-bottom: 1px solid #d1d5db; overflow-wrap: break-word;">{2}</th>'.format(
				width, "right" if index >= 3 else "left", escape_html(str(label))))
	rows = []
	for (item_code, uom), group in sorted(groups.items()):
		values = [item_code, group["name"], uom or "All"] + [
			"{0:.3f}".format(Decimal(str(group["prices"][name])))
			if name in group["prices"] else "Not changed" for name in columns]
		cells = []
		for index, value in enumerate(values):
			style = "padding: 8px 6px; vertical-align: top; border-bottom: 1px solid #e5e7eb; "
			style += "text-align: right; white-space: nowrap;" if index >= 3 else "word-wrap: break-word; overflow-wrap: break-word; word-break: normal;"
			cells.append('<td style="{0}">{1}</td>'.format(style, escape_html(str(value))))
		rows.append("<tr>{0}</tr>".format("".join(cells)))
	return (
		'<div style="overflow-x: auto;"><div style="min-width: 560px;"><table style="width: 100%; '
		'table-layout: fixed; border-collapse: collapse; font-size: 12px; line-height: 1.5;">'
		'<thead><tr>{0}</tr></thead><tbody>{1}</tbody></table></div></div>'
	).format("".join(headers), "".join(rows))


def create_pricing_update_note(update_kind, prepared_report_name, changes):
	"""Save one public announcement in the caller's pricing transaction."""
	if not changes:
		return None
	if update_kind not in ("item_price", "pricing_rule"):
		raise ValueError("Unsupported pricing update kind")

	def text(value):
		return escape_html(str(value if value is not None else ""))

	def number(value):
		return "{0:.3f}".format(Decimal(str(value)))

	rows = []
	if update_kind == "item_price":
		title = "Prices Updated"
	else:
		title = "Pricing Rules Updated"
		headers = ["Pricing Rule", "Items", "Minimum Qty", "Maximum Qty", "Discount",
			"Status", "Mixed Conditions"]
		for change in changes:
			rows.append([
				change["rule_name"], ", ".join(change["item_codes"]),
				number(change["minimum_qty"]),
				"No maximum" if not change.get("maximum_qty") else number(change["maximum_qty"]),
				number(change["discount_percentage"]) + "%",
				"Disabled" if cint(change.get("disabled")) else "Enabled",
				"Yes" if cint(change.get("mixed_conditions")) else "No"
			])

	updated_on = now()
	note = frappe.new_doc("Note")
	note.title = "{0} - {1} - {2}".format(title, updated_on, uuid4().hex[:12])
	note.public = 1
	note.notify_on_login = 1
	note.notify_on_every_login = 1
	note.expire_notification_on = add_days(nowdate(), 3)
	note.content = render_item_price_changes(changes) if update_kind == "item_price" else (
		'<p>Updated by {0} on {1}. Prepared Report: {2}.</p>'
		'<p>Amounts are net of VAT. Pending or inactive prices remain subject to approval.</p>'
		'<div style="max-height: 360px; overflow: auto;">'
		'<table class="table table-bordered" style="font-size: 12px;">'
		'<thead><tr>{3}</tr></thead><tbody>{4}</tbody></table></div>'
	).format(
		text(frappe.session.user), text(updated_on), text(prepared_report_name),
		"".join("<th>{0}</th>".format(text(header)) for header in headers),
		"".join("<tr>{0}</tr>".format("".join(
			'<td style="overflow-wrap: anywhere;">{0}</td>'.format(text(value)) for value in row
		)) for row in rows)
	)
	note.insert()
	return note.name
