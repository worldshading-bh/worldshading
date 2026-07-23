from __future__ import unicode_literals

import json
import frappe
from frappe import _
from frappe.utils import cint, flt, get_datetime, now_datetime, nowdate


@frappe.whitelist()
def get_default_bom_items(item_code, qty=1):
	if not item_code:
		return {}

	bom_no = _get_default_bom(item_code)
	if not bom_no:
		return {}

	bom = frappe.get_doc("BOM", bom_no)
	if not bom.is_active or bom.docstatus == 2:
		return {}

	multiplier = flt(qty) / (flt(bom.quantity) or 1)
	items = []

	for row in bom.get("items") or []:
		row_qty = flt(row.qty) * multiplier
		rate = get_price_list_rate_for_item(
			row.item_code,
			row.uom,
			qty=row_qty,
			company=bom.company,
			currency=bom.currency
		)

		items.append({
			"item_code": row.item_code,
			"item_name": row.item_name,
			"description": row.description,
			"qty": row_qty,
			"uom": row.uom,
			"rate": rate,
			"amount": row_qty * rate,
			"source_warehouse": row.source_warehouse,
			"include_item_in_manufacturing": row.include_item_in_manufacturing
		})

	return {
		"bom": bom.name,
		"items": items
	}


@frappe.whitelist()
def get_raw_material_details(item_code):
	if not item_code:
		return {}

	item = frappe.db.get_value(
		"Item",
		item_code,
		["item_name", "description", "stock_uom", "valuation_rate"],
		as_dict=True
	)

	if not item:
		return {}

	return {
		"item_name": item.item_name,
		"description": item.description,
		"uom": item.stock_uom,
		"rate": get_price_list_rate_for_item(item_code, item.stock_uom)
	}


@frappe.whitelist()
def get_order_specific_work_order_items(sales_order):
	if not sales_order:
		return []

	doc = frappe.get_doc("Sales Order", sales_order)
	out = []

	for item in doc.get("items") or []:
		bom = _get_bom_for_sales_order_item(doc, item)
		if not bom:
			continue

		pending_qty = _get_pending_work_order_qty(doc, item)
		if not pending_qty:
			continue

		out.append({
			"name": item.name,
			"item_code": item.item_code,
			"item_name": item.item_name,
			"description": item.description,
			"bom": bom,
			"warehouse": item.warehouse,
			"pending_qty": pending_qty,
			"sales_order_item": item.name,
			"production_attachment": item.get("production_attachment")
		})

	return out


@frappe.whitelist()
def get_sales_order_production_estimate_items(sales_order):
	if not sales_order:
		return []

	doc = frappe.get_doc("Sales Order", sales_order)
	out = []

	for item in doc.get("items") or []:
		bom = _get_bom_for_sales_order_item(doc, item)
		if not bom:
			continue

		out.append({
			"name": item.name,
			"item_code": item.item_code,
			"item_name": item.item_name,
			"description": item.description,
			"qty": item.qty,
			"stock_qty": item.stock_qty,
			"bom": bom,
			"sales_order_item": item.name,
			"production_estimated_hours": item.get("production_estimated_hours") or 0
		})

	return out


@frappe.whitelist()
def get_work_estimate_setup(sales_order):
	"""Everything the Work Estimate page needs on load: the SO items + the available
	Work Types (only those that have at least one enabled team)."""
	return {
		"items": get_sales_order_production_estimate_items(sales_order),
		"work_types": get_available_work_types()
	}


@frappe.whitelist()
def get_available_work_types():
	"""Work Types that are enabled AND have at least one enabled team, with their teams.
	Sorted by the Work Type's default sequence (pipeline order)."""
	teams = frappe.get_all(
		"Work Team",
		filters={"disabled": 0},
		fields=["name", "team_name", "work_type", "team_size"],
		order_by="team_name asc"
	)

	teams_by_type = {}
	for team in teams:
		work_type = team.get("work_type")
		if not work_type:
			continue
		teams_by_type.setdefault(work_type, []).append({
			"name": team.name,
			"team_name": team.team_name or team.name,
			"team_size": team.get("team_size") or ""
		})

	out = []
	if teams_by_type:
		work_type_rows = frappe.get_all(
			"Work Type",
			filters={"name": ["in", list(teams_by_type.keys())], "disabled": 0},
			fields=["name", "sequence"]
		)
		for row in work_type_rows:
			out.append({
				"work_type": row.name,
				"sequence": cint(row.sequence),
				"teams": teams_by_type.get(row.name, [])
			})

	out.sort(key=lambda entry: (entry["sequence"], entry["work_type"]))
	return out


@frappe.whitelist()
def get_work_estimate_schedule(sales_order, requested_start=None, delivery_type=None, requirements=None):
	"""Schedule the Work Estimate requirements using the existing team engine.

	Stages run by their Order: a strictly-higher Order waits for the previous Order group
	to finish; stages sharing an Order run in parallel on their own teams. Within one
	estimate, a team's stages queue after each other (team-wise availability), and the
	engine also respects existing Work Order bookings, working hours and holidays.
	"""
	if isinstance(requirements, str):
		requirements = json.loads(requirements)
	if not sales_order:
		return {}

	doc = frappe.get_doc("Sales Order", sales_order)
	requested_start = requested_start or now_datetime()
	partial = (delivery_type == "Partial Delivery")

	from worldshading.api.work_order_team import get_team_schedule_plan

	warnings = []

	def add_warning(message):
		if message and message not in warnings:
			warnings.append(message)

	team_name_cache = {}

	def team_name(team):
		if not team:
			return ""
		if team not in team_name_cache:
			team_name_cache[team] = frappe.db.get_value("Work Team", team, "team_name") or team
		return team_name_cache[team]

	def label(item_code, soi):
		return item_code or soi or ""

	# Group requirements by their integer Order.
	by_level = {}
	for row in (requirements or []):
		level = cint(row.get("priority")) or 1
		by_level.setdefault(level, []).append(row)

	next_start_by_team = {}   # in-estimate team queue: team -> next free datetime string
	item_prev_end = {}        # Partial: sales_order_item -> end of its previous Order group
	global_prev_end = {"v": None}  # One Time: end of the previous Order group across all items
	item_completion = {}      # sales_order_item -> latest stage end
	stages = []

	for level in sorted(by_level.keys()):
		level_item_end = {}
		for row in by_level[level]:
			soi = row.get("sales_order_item")
			item_code = row.get("item_code")
			item_name = row.get("item_name") or (frappe.db.get_value("Item", item_code, "item_name") if item_code else "")
			hours = flt(row.get("estimated_hours"))
			team = row.get("team")
			work_type = row.get("work_type")

			base_start = (item_prev_end.get(soi) if partial else global_prev_end["v"]) or requested_start
			team_ready = next_start_by_team.get(team)
			start = base_start
			if team_ready and get_datetime(team_ready) > get_datetime(start):
				start = team_ready

			plan = {}
			if team and hours > 0:
				plan = get_team_schedule_plan(team, start, hours, company=doc.company)
				if plan.get("suggested_end"):
					next_start_by_team[team] = plan.get("suggested_end")
				for reason in (plan.get("reasons") or []):
					add_warning(reason)
				if not plan.get("suggested_end"):
					add_warning(_("Could not find a slot for {0} on {1}.").format(work_type, label(item_code, soi)))
			elif not team:
				add_warning(_("No team available for {0} on {1}.").format(work_type, label(item_code, soi)))
			else:
				add_warning(_("Enter hours for {0} on {1}.").format(work_type, label(item_code, soi)))

			end = plan.get("suggested_end")
			stages.append({
				"work_type": work_type,
				"priority": level,
				"sales_order_item": soi,
				"item_code": item_code,
				"item_name": item_name,
				"qty": row.get("qty"),
				"hours": hours,
				"team": team,
				"team_name": team_name(team),
				"team_size": row.get("team_size") or "",
				"start": plan.get("suggested_start"),
				"end": end
			})

			if end:
				if not level_item_end.get(soi) or get_datetime(end) > get_datetime(level_item_end[soi]):
					level_item_end[soi] = end
				if not item_completion.get(soi) or get_datetime(end) > get_datetime(item_completion[soi]):
					item_completion[soi] = end

		# Advance readiness after the whole Order group so the next group waits for it.
		if partial:
			for soi, end in level_item_end.items():
				item_prev_end[soi] = end
		else:
			for end in level_item_end.values():
				if not global_prev_end["v"] or get_datetime(end) > get_datetime(global_prev_end["v"]):
					global_prev_end["v"] = end

	completions = [get_datetime(end) for end in item_completion.values()]
	final_completion = max(completions) if completions else None
	first_completion = (min(completions) if completions else None) if partial else final_completion

	return {
		"stages": stages,
		"summary": {
			"delivery_type": delivery_type or ("Partial Delivery" if partial else "One Time Delivery"),
			"final_completion": str(final_completion) if final_completion else None,
			"first_completion": str(first_completion) if first_completion else None
		},
		"warnings": warnings
	}


@frappe.whitelist()
def get_sales_order_production_estimate(sales_order, items, requested_start=None, delivery_type=None,
		fixing_needed=0):
	if isinstance(items, str):
		items = json.loads(items)

	if not sales_order:
		return {}

	doc = frappe.get_doc("Sales Order", sales_order)
	requested_start = requested_start or now_datetime()
	fixing_needed = cint(fixing_needed)
	partial = (delivery_type == "Partial Delivery")

	from worldshading.api.work_order_team import get_team_schedule_plan

	warnings = []

	def add_warning(message):
		if message and message not in warnings:
			warnings.append(message)

	def item_label(item_code, sales_order_item):
		return item_code or sales_order_item or ""

	# ---------------- Production ----------------
	next_start_by_team = {}
	production = []
	production_end_by_item = {}

	for row in items or []:
		team = row.get("production_team")
		item_code = row.get("item_code")
		item_name = row.get("item_name") or (frappe.db.get_value("Item", item_code, "item_name") if item_code else "")
		sales_order_item = row.get("sales_order_item") or row.get("name")
		estimated_hours = flt(row.get("production_estimated_hours"))
		team_requested_start = next_start_by_team.get(team) or requested_start
		plan = {}

		if team and estimated_hours > 0:
			plan = get_team_schedule_plan(team, team_requested_start, estimated_hours, company=doc.company)
			if plan.get("suggested_end"):
				next_start_by_team[team] = plan.get("suggested_end")
				production_end_by_item[sales_order_item] = plan.get("suggested_end")
			for reason in (plan.get("reasons") or []):
				add_warning(reason)
		else:
			add_warning("Select Production Team and Production Hours for {0}.".format(item_label(item_code, sales_order_item)))

		production.append({
			"sales_order_item": sales_order_item,
			"item_code": item_code,
			"item_name": item_name,
			"team": team,
			"hours": estimated_hours,
			"start": plan.get("suggested_start"),
			"end": plan.get("suggested_end")
		})

	# ---------------- Fixing ----------------
	# Fixing cannot start before the corresponding production is complete.
	#   Partial Delivery  -> fixing for an item starts after THAT item's production end.
	#   One Time Delivery -> fixing starts only after the LATEST production end across all items.
	fixing = []
	fixing_end_by_item = {}
	latest_production_end = max([get_datetime(v) for v in production_end_by_item.values()]) if production_end_by_item else None

	if fixing_needed:
		next_start_by_team = {}
		for row in items or []:
			team = row.get("fixing_team")
			item_code = row.get("item_code")
			item_name = row.get("item_name") or (frappe.db.get_value("Item", item_code, "item_name") if item_code else "")
			sales_order_item = row.get("sales_order_item") or row.get("name")
			estimated_hours = flt(row.get("fixing_estimated_hours"))
			plan = {}

			if partial:
				base_start = production_end_by_item.get(sales_order_item)
			else:
				base_start = latest_production_end
			base_start = base_start or requested_start

			team_requested_start = base_start
			team_last_end = next_start_by_team.get(team)
			if team_last_end and get_datetime(team_last_end) > get_datetime(team_requested_start):
				team_requested_start = team_last_end

			if team and estimated_hours > 0 and production_end_by_item.get(sales_order_item):
				plan = get_team_schedule_plan(team, team_requested_start, estimated_hours,
					company=doc.company, allow_past_start=True)
				if plan.get("suggested_end"):
					next_start_by_team[team] = plan.get("suggested_end")
					fixing_end_by_item[sales_order_item] = plan.get("suggested_end")
				for reason in (plan.get("reasons") or []):
					add_warning(reason)
			elif not production_end_by_item.get(sales_order_item):
				add_warning("Set the production estimate first for {0} before fixing.".format(item_label(item_code, sales_order_item)))
			else:
				add_warning("Select Fixing Team and Fixing Hours for {0}.".format(item_label(item_code, sales_order_item)))

			fixing.append({
				"sales_order_item": sales_order_item,
				"item_code": item_code,
				"item_name": item_name,
				"team": team,
				"hours": estimated_hours,
				"start": plan.get("suggested_start"),
				"end": plan.get("suggested_end")
			})

	# ---------------- Summary ----------------
	completions = []
	for sales_order_item, prod_end in production_end_by_item.items():
		final_for_item = fixing_end_by_item.get(sales_order_item) if fixing_needed else None
		final_for_item = final_for_item or prod_end
		completions.append(get_datetime(final_for_item))

	final_completion = max(completions) if completions else None
	first_completion = (min(completions) if completions else None) if partial else final_completion

	summary = {
		"delivery_type": delivery_type or ("Partial Delivery" if partial else "One Time Delivery"),
		"fixing_needed": fixing_needed,
		"first_completion": str(first_completion) if first_completion else None,
		"final_completion": str(final_completion) if final_completion else None
	}

	return {
		"production": production,
		"fixing": fixing,
		"summary": summary,
		"warnings": warnings
	}


@frappe.whitelist()
def save_sales_order_production_estimate(sales_order, items, delivery_type=None,
		allow_partial_manufacturing_delivery=None):
	if isinstance(items, str):
		items = json.loads(items)

	if not sales_order:
		frappe.throw("Sales Order is required.")

	doc = frappe.get_doc("Sales Order", sales_order)
	doc.check_permission("write")
	_validate_estimate_fields(doc)

	# Delivery Type select maps onto the existing partial-delivery flag.
	if delivery_type is not None:
		allow_partial = 1 if delivery_type == "Partial Delivery" else 0
	else:
		allow_partial = 1 if flt(allow_partial_manufacturing_delivery) else 0

	frappe.db.set_value(
		"Sales Order",
		doc.name,
		"allow_partial_manufacturing_delivery",
		allow_partial
	)

	valid_item_rows = {}
	for row in doc.get("items") or []:
		valid_item_rows[row.name] = row

	for row in items or []:
		sales_order_item = row.get("sales_order_item") or row.get("name")
		if not sales_order_item or sales_order_item not in valid_item_rows:
			continue

		frappe.db.set_value(
			"Sales Order Item",
			sales_order_item,
			"production_estimated_hours",
			flt(row.get("production_estimated_hours"))
		)

	doc.notify_update()
	return True


def _validate_estimate_fields(doc):
	if not doc.meta.has_field("allow_partial_manufacturing_delivery"):
		frappe.throw("Please add Allow Partial Manufacturing Delivery field in Sales Order.")

	sales_order_item_meta = frappe.get_meta("Sales Order Item")
	if not sales_order_item_meta.has_field("production_estimated_hours"):
		frappe.throw("Please add Production Estimated Hours field in Sales Order Item.")

	if doc.docstatus == 1:
		if not doc.meta.get_field("allow_partial_manufacturing_delivery").allow_on_submit:
			frappe.throw("Allow on Submit must be enabled for Allow Partial Manufacturing Delivery.")

		if not sales_order_item_meta.get_field("production_estimated_hours").allow_on_submit:
			frappe.throw("Allow on Submit must be enabled for Production Estimated Hours.")


@frappe.whitelist()
def make_order_specific_work_orders(items, sales_order, company, project=None, attachments=None):
	from erpnext.selling.doctype.sales_order.sales_order import make_work_orders

	if isinstance(items, str):
		items = json.loads(items)

	if isinstance(attachments, str):
		attachments = json.loads(attachments or "{}")

	work_order_names = make_work_orders(
		json.dumps({"items": items or []}),
		sales_order,
		company,
		project=project
	)

	_apply_production_attachments(sales_order, work_order_names, attachments or {})

	return work_order_names


def _apply_production_attachments(sales_order, work_order_names, attachments):
	"""Copy each drawing onto the created Work Order and back onto the Sales Order Item."""
	if not attachments:
		return

	work_order_has_field = frappe.get_meta("Work Order").has_field("production_attachment")
	sales_order_item_has_field = frappe.get_meta("Sales Order Item").has_field("production_attachment")

	for wo_name in work_order_names:
		sales_order_item = frappe.db.get_value("Work Order", wo_name, "sales_order_item")
		url = _resolve_drawing_url(attachments.get(sales_order_item), sales_order, wo_name)
		if not url:
			continue

		if work_order_has_field:
			frappe.db.set_value("Work Order", wo_name, "production_attachment", url, update_modified=False)
			_attach_file_to_doc(url, "Work Order", wo_name)

		if sales_order_item and sales_order_item_has_field:
			current = frappe.db.get_value("Sales Order Item", sales_order_item, "production_attachment")
			if current != url:
				frappe.db.set_value("Sales Order Item", sales_order_item, "production_attachment", url,
					update_modified=False)
			_attach_file_to_doc(url, "Sales Order", sales_order)


def _resolve_drawing_url(entry, sales_order, work_order):
	"""Resolve an item's production drawing to a single file URL.

	`entry` may be:
	  * a plain URL string (legacy / already-set drawing), or
	  * a dict {"file_docnames": [File names...], "existing_url": "..."}.

	When more than one drawing was uploaded for the item, they are merged into a
	single PDF (same helper the Service Visit reference image uses). A single
	upload is kept in its original format.
	"""
	if not entry:
		return None

	if isinstance(entry, str):
		return entry

	file_docnames = [name for name in (entry.get("file_docnames") or []) if name]
	existing_url = entry.get("existing_url") or ""

	if not file_docnames:
		return existing_url

	if len(file_docnames) == 1:
		return frappe.db.get_value("File", file_docnames[0], "file_url") or existing_url

	from worldshading.api.utility import merge_documents

	result = merge_documents(
		file_docnames,
		output_filename="Production Drawing - {0}".format(work_order),
		attach_to_doctype="Sales Order",
		attach_to_name=sales_order,
		cleanup_originals=1,
		is_private=0
	)

	return (result or {}).get("file_url") or existing_url


def _attach_file_to_doc(url, doctype, name):
	"""Ensure the uploaded drawing shows up in the target document's attachments."""
	if not url or not name:
		return

	if frappe.db.exists("File", {"file_url": url, "attached_to_doctype": doctype, "attached_to_name": name}):
		return

	file_name = url.rsplit("/", 1)[-1]
	is_private = 1 if url.startswith("/private/") else 0

	frappe.get_doc({
		"doctype": "File",
		"file_url": url,
		"file_name": file_name,
		"attached_to_doctype": doctype,
		"attached_to_name": name,
		"is_private": is_private,
		"folder": "Home/Attachments"
	}).insert(ignore_permissions=True)


def get_global_default_price_list_name():
	price_list = frappe.db.get_value(
		"Price List",
		{"enabled": 1, "global_default": 1},
		"name"
	)

	if price_list:
		return price_list

	return frappe.db.get_value(
		"Price List",
		{"enabled": 1, "name": "Regular Price"},
		"name"
	)


def get_price_list_rate_for_item(item_code, uom=None, qty=1, company=None, currency=None):
	price_list = get_global_default_price_list_name()
	if not price_list or not item_code:
		return 0

	if not uom:
		uom = frappe.db.get_value("Item", item_code, "stock_uom")

	item_price = frappe.db.sql("""
		select price_list_rate
		from `tabItem Price`
		where item_code = %s
			and price_list = %s
			and ifnull(uom, '') in ('', %s)
			and ifnull(customer, '') = ''
			and ifnull(supplier, '') = ''
			and %s between ifnull(valid_from, '2000-01-01') and ifnull(valid_upto, '2500-12-31')
		order by valid_from desc, uom desc
		limit 1
	""", (item_code, price_list, uom, nowdate()), as_dict=True)

	return flt(item_price[0].price_list_rate) if item_price else 0


def _get_default_bom(item_code):
	default_bom = frappe.db.get_value("Item", item_code, "default_bom")
	if default_bom:
		return default_bom

	return frappe.db.get_value(
		"BOM",
		{
			"item": item_code,
			"is_default": 1,
			"is_active": 1,
			"docstatus": ["<", 2]
		},
		"name"
	)


def _get_bom_for_sales_order_item(doc, item):
	transaction_bom = None
	master_bom = None

	for row in doc.get("production_bom_items") or []:
		if row.parent_detail == item.name or (row.parent_item_row == item.idx and row.parent_item == item.item_code):
			if row.transaction_bom:
				transaction_bom = row.transaction_bom
				break
			if row.master_bom:
				master_bom = row.master_bom

	return transaction_bom or master_bom or _get_default_bom(item.item_code)


def _get_pending_work_order_qty(doc, item):
	total_work_order_qty = flt(frappe.db.sql('''select sum(qty) from `tabWork Order`
		where production_item=%s and sales_order=%s and sales_order_item=%s and docstatus<2''',
		(item.item_code, doc.name, item.name))[0][0])

	return flt(item.stock_qty) - total_work_order_qty
