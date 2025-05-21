from __future__ import unicode_literals
import frappe
import erpnext
import json
from frappe.utils import flt, nowdate, add_days, cint
from frappe import _

def reorder_item():
	print("custom  reorder_item() by ws is running.")
	""" Reorder item if stock reaches reorder level"""
	# if initial setup not completed, return
	if not (frappe.db.a_row_exists("Company") and frappe.db.a_row_exists("Fiscal Year")):
		return

	if cint(frappe.db.get_value('Stock Settings', None, 'auto_indent')):
		return _reorder_item()

def _reorder_item():
	material_requests = {"Repack": {}, "Production": {}}
	warehouse_company = frappe._dict(frappe.db.sql("""select name, company from `tabWarehouse`
		where disabled=0"""))
	default_company = (erpnext.get_default_company() or
		frappe.db.sql("""select name from tabCompany limit 1""")[0][0])

	items_to_consider = frappe.db.sql_list("""select name from `tabItem` item
		where is_stock_item=1 and has_variants=0
			and disabled=0
			and (end_of_life is null or end_of_life='0000-00-00' or end_of_life > %(today)s)
			and (exists (select name from `tabItem Reorder` ir where ir.parent=item.name)
				or (variant_of is not null and variant_of != ''
				and exists (select name from `tabItem Reorder` ir where ir.parent=item.variant_of))
			)""",
		{"today": nowdate()})

	if not items_to_consider:
		return

	item_warehouse_projected_qty = get_item_warehouse_projected_qty(items_to_consider)



	def add_to_material_request(item_code, warehouse, reorder_level, reorder_qty, material_request_type, warehouse_group=None):
		if material_request_type not in material_requests:
			print(f"⛔ Skipping unsupported type: {material_request_type}")
			return
		
		if warehouse not in warehouse_company:
			# a disabled warehouse
			return

		reorder_level = flt(reorder_level)
		reorder_qty = flt(reorder_qty)

		# projected_qty will be 0 if Bin does not exist
		if warehouse_group:
			projected_qty = flt(item_warehouse_projected_qty.get(item_code, {}).get(warehouse_group))
		else:
			projected_qty = flt(item_warehouse_projected_qty.get(item_code, {}).get(warehouse))

		if (reorder_level or reorder_qty) and projected_qty < reorder_level:
			deficiency = reorder_level - projected_qty
			if deficiency > reorder_qty:
				reorder_qty = deficiency

			company = warehouse_company.get(warehouse) or default_company

			material_requests[material_request_type].setdefault(company, []).append({
				"item_code": item_code,
				"warehouse": warehouse,
				"reorder_qty": reorder_qty
			})

	for item_code in items_to_consider:
		item = frappe.get_doc("Item", item_code)

		if item.variant_of and not item.get("reorder_levels"):
			item.update_template_tables()

		if item.get("reorder_levels"):
			for d in item.get("reorder_levels"):
				if d.material_request_type not in ["Repack", "Production"]:
					continue;
				add_to_material_request(item_code, d.warehouse, d.warehouse_reorder_level,
					d.warehouse_reorder_qty, d.material_request_type, warehouse_group=d.warehouse_group)

	if material_requests:
		create_material_request(material_requests)


def get_item_warehouse_projected_qty(items_to_consider):
	item_warehouse_projected_qty = {}

	for item_code, warehouse, projected_qty in frappe.db.sql("""select item_code, warehouse, projected_qty
		from tabBin where item_code in ({0})
			and (warehouse != "" and warehouse is not null)"""\
		.format(", ".join(["%s"] * len(items_to_consider))), items_to_consider):

		if item_code not in item_warehouse_projected_qty:
			item_warehouse_projected_qty.setdefault(item_code, {})

		if warehouse not in item_warehouse_projected_qty.get(item_code):
			item_warehouse_projected_qty[item_code][warehouse] = flt(projected_qty)

		warehouse_doc = frappe.get_doc("Warehouse", warehouse)

		while warehouse_doc.parent_warehouse:
			if not item_warehouse_projected_qty.get(item_code, {}).get(warehouse_doc.parent_warehouse):
				item_warehouse_projected_qty.setdefault(item_code, {})[warehouse_doc.parent_warehouse] = flt(projected_qty)
			else:
				item_warehouse_projected_qty[item_code][warehouse_doc.parent_warehouse] += flt(projected_qty)
			warehouse_doc = frappe.get_doc("Warehouse", warehouse_doc.parent_warehouse)

	return item_warehouse_projected_qty




from erpnext.stock.get_item_details import get_item_details

def create_material_request(material_requests):
    print("⚠️ Creating Material Requests for Repack/Production...")
    MAX_MR_LIMIT = 25  # 🔢 Set your desired max limit here
    mr_list = []
    missing_rule_items = []
    exceptions_list = []

    def _log_exception():
        if frappe.local.message_log:
            exceptions_list.extend(frappe.local.message_log)
            frappe.local.message_log = []
        else:
            exceptions_list.append(frappe.get_traceback())
        frappe.log_error(frappe.get_traceback())

    for request_type in ["Repack", "Production"]:
        for company in material_requests.get(request_type, {}):
            items = material_requests[request_type][company]
            if not items:
                continue

            for d in items:
                d = frappe._dict(d)
                print(f"👥 Creating Material Request for {d.item_code} ({request_type})")

                try:
                    rules = frappe.get_all("Repack Production Rule", filters={"type": request_type})
                    found = False

                    for rule in rules:
                        rule_doc = frappe.get_doc("Repack Production Rule", rule.name)
                        for to_item in rule_doc.to_item:
                            if to_item.item_code == d.item_code:
                                found = True
                                print(f"🔁 Rule matched: {rule.name}")

                                rule_qty = to_item.qty
                                reorder_qty = d.reorder_qty
                                multiplier = max(1, round(reorder_qty / rule_qty))

                                print(f"🔢 Reorder Qty: {reorder_qty}, Rule Qty: {rule_qty}, Multiplier: {multiplier}")

                                # ✅ Check stock of all source items before proceeding
                                if request_type == "Production":
                                    if d.warehouse == "Production Salmabad - WS":
                                        from_warehouse = "Salmabad Showroom - WS"
                                    elif d.warehouse == "Production Hamad Town - WS":
                                        from_warehouse = "Hamad Town Showroom - WS"
                                    else:
                                        from_warehouse = d.warehouse
                                else:
                                    from_warehouse = d.warehouse

                                source_missing = []
                                for from_item in rule_doc.from_item:
                                    actual_qty = frappe.db.get_value("Bin", {
                                        "item_code": from_item.item_code,
                                        "warehouse": from_warehouse
                                    }, "actual_qty") or 0
                                    if actual_qty <= 0:
                                        source_missing.append(f"{from_item.item_code} (0 in {from_warehouse})")

                                if source_missing:
                                    print(f"❌ Skipping {d.item_code} ({request_type}) — source stock unavailable: {', '.join(source_missing)}")
                                    continue

                                # ✅ For Production: create one MR per multiplier
                                if request_type == "Production":
                                    for i in range(multiplier):
                                        if len(mr_list) >= MAX_MR_LIMIT:
                                            print("🛑 Max MR limit reached — stopping further MR creation.")
                                            return mr_list
                                        print(f"🔄 Current MR count: {len(mr_list)}")

                                        mr = frappe.new_doc("Material Request")
                                        mr.update({
                                            "company": company,
                                            "transaction_date": nowdate(),
                                            "material_request_type": request_type
                                        })

                                        for from_item in rule_doc.from_item:
                                            args = {
                                                "item_code": from_item.item_code,
                                                "warehouse": from_warehouse,
                                                "company": company,
                                                "qty": from_item.qty,
                                                "conversion_factor": 1,
                                                "doctype": "Material Request"
                                            }
                                            from_item_data = get_item_details(args)

                                            mr.append("from_items", frappe._dict({
                                                "item_code": from_item.item_code,
                                                "warehouse": from_warehouse,
                                                "qty": from_item.qty,
                                                "uom": from_item.uom,
                                                "schedule_date": add_days(nowdate(), 7),
                                                **from_item_data
                                            }))

                                        item_doc = frappe.get_doc("Item", to_item.item_code)
                                        mr.append("items", {
                                            "item_code": to_item.item_code,
                                            "warehouse": d.warehouse,
                                            "qty": to_item.qty,
                                            "uom": to_item.uom,
                                            "item_name": item_doc.item_name,
                                            "description": item_doc.description,
                                            "item_group": item_doc.item_group,
                                            "brand": item_doc.brand,
                                            "schedule_date": add_days(nowdate(), 7)
                                        })

                                        mr.flags.ignore_mandatory = True
                                        mr.insert()
                                        mr.submit()
                                        print(f"✅ MR Created: {mr.name}")
                                        mr_list.append(mr)

                                # ✅ For Repack: combine all into one MR with multiplier * qty
                                else:
                                    if len(mr_list) >= MAX_MR_LIMIT:
                                        print("🛑 Max MR limit reached — stopping further MR creation.")
                                        return mr_list
                                    print(f"🔄 Current MR count: {len(mr_list)}")

                                    mr = frappe.new_doc("Material Request")
                                    mr.update({
                                        "company": company,
                                        "transaction_date": nowdate(),
                                        "material_request_type": request_type
                                    })

                                    for from_item in rule_doc.from_item:
                                        args = {
                                            "item_code": from_item.item_code,
                                            "warehouse": from_warehouse,
                                            "company": company,
                                            "qty": from_item.qty * multiplier,
                                            "conversion_factor": 1,
                                            "doctype": "Material Request"
                                        }
                                        from_item_data = get_item_details(args)

                                        mr.append("from_items", frappe._dict({
                                            "item_code": from_item.item_code,
                                            "warehouse": from_warehouse,
                                            "qty": from_item.qty * multiplier,
                                            "uom": from_item.uom,
                                            "schedule_date": add_days(nowdate(), 7),
                                            **from_item_data
                                        }))

                                    item_doc = frappe.get_doc("Item", to_item.item_code)
                                    mr.append("items", {
                                        "item_code": to_item.item_code,
                                        "warehouse": d.warehouse,
                                        "qty": to_item.qty * multiplier,
                                        "uom": to_item.uom,
                                        "item_name": item_doc.item_name,
                                        "description": item_doc.description,
                                        "item_group": item_doc.item_group,
                                        "brand": item_doc.brand,
                                        "schedule_date": add_days(nowdate(), 7)
                                    })

                                    mr.flags.ignore_mandatory = True
                                    mr.insert()
                                    mr.submit()
                                    print(f"✅ MR Created: {mr.name}")
                                    mr_list.append(mr)

                                break  # rule matched — break inner loop
                    if not found:
                        print(f"📝 No rule found for {d.item_code} — will include in summary ToDo")
                        item_link = f"{frappe.utils.get_url()}/desk#Form/Item/{d.item_code}"
                        missing_rule_items.append(f"<li><a href='{item_link}'>{d.item_code}</a> ({request_type})</li>")

                except Exception:
                    _log_exception()

    if mr_list and cint(frappe.db.get_value('Stock Settings', None, 'reorder_email_notify')):
        send_email_notification(mr_list)

    if exceptions_list:
        notify_errors(exceptions_list)

    # ✅ Create one summary ToDo listing all missing rule items
    if missing_rule_items:
        item_list_html = "<ul>" + "\n".join(missing_rule_items) + "</ul>"
        todo_description = (
            f"🚫 The following items were skipped during auto reorder because no "
            f"<b>Repack/Production Rule</b> was found:<br>{item_list_html}"
        )

        stock_managers = frappe.db.sql_list("""
            SELECT parent FROM `tabHas Role`
            WHERE role = 'Stock Manager'
            AND parent IN (
                SELECT name FROM `tabUser`
                WHERE enabled = 1 AND name NOT IN ('Administrator', 'Guest')
            )
        """)

        for user in stock_managers:
            frappe.get_doc({
                "doctype": "ToDo",
                "owner": user,
                "description": todo_description,
                "priority": "Medium",
                "status": "Open",
                "date": nowdate()
            }).insert(ignore_permissions=True)

        print("📝 Summary ToDo created for all missing rule items.")

    return mr_list







def send_email_notification(mr_list):
	""" Notify user about auto creation of indent"""

	email_list = frappe.db.sql_list("""select distinct r.parent
		from `tabHas Role` r, tabUser p
		where p.name = r.parent and p.enabled = 1 and p.docstatus < 2
		and r.role in ('Purchase Manager','Stock Manager')
		and p.name not in ('Administrator', 'All', 'Guest')""")

	msg = frappe.render_template("templates/emails/reorder_item.html", {
		"mr_list": mr_list
	})

	frappe.sendmail(recipients=email_list,
		subject=_('Auto Material Requests Generated'), message = msg)

import json

def notify_errors(exceptions_list):
    subject = _("[Important] [ERPNext] Auto Reorder Errors")
    content = _("Dear System Manager,") + "<br>" + _(
        "An error occurred for certain Items while creating Material Requests based on Re-order level. \
        Please rectify these issues:"
    ) + "<br>"

    for exception in exceptions_list:
        if not exception:
            continue

        # If already parsed, or simple string
        try:
            if isinstance(exception, dict):
                message = exception.get("message")
            elif isinstance(exception, str) and exception.strip().startswith("{"):
                parsed = json.loads(exception)
                message = parsed.get("message", str(parsed))
            else:
                message = str(exception)
        except Exception:
            message = "❌ Error while parsing exception: " + str(exception)

        error_message = f"""<div class='small text-muted'>{message}</div><br>"""
        content += error_message

    content += _("Regards,") + "<br>" + _("Administrator")

    from frappe.email import sendmail_to_system_managers
    sendmail_to_system_managers(subject, content)





