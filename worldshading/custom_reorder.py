# import frappe
# from frappe.utils import nowdate, add_days, cint, flt

# def daily_reorder_job():
#     print("✅ Running custom daily reorder job")
#     reorder_items_for_repack()

# def reorder_items_for_repack():
#     print("🔍 Fetching items with Repack reorder settings...")
#     items = frappe.db.sql("""
#         SELECT DISTINCT i.name
#         FROM `tabItem` i
#         JOIN `tabItem Reorder` ir ON ir.parent = i.name
#         WHERE i.is_stock_item = 1
#           AND i.disabled = 0
#           AND ir.material_request_type = 'Repack'
#     """, as_dict=True)

#     if not items:
#         print("🚫 No items found with Repack reorder settings.")
#         return

#     for item in items:
#         item_code = item.name
#         reorder_levels = frappe.get_all("Item Reorder",
#             filters={"parent": item_code, "material_request_type": "Repack"},
#             fields=["warehouse", "warehouse_reorder_level", "warehouse_reorder_qty"])

#         for rl in reorder_levels:
#             warehouse = rl.warehouse
#             reorder_level = flt(rl.warehouse_reorder_level)
#             reorder_qty = flt(rl.warehouse_reorder_qty)

#             projected_qty = frappe.db.get_value("Bin",
#                 {"item_code": item_code, "warehouse": warehouse}, "projected_qty") or 0

#             print(f"📦 Item: {item_code}, Warehouse: {warehouse}, "
#                   f"Projected Qty: {projected_qty}, Reorder Level: {reorder_level}")

#             if projected_qty < reorder_level:
#                 print(f"⚠️ Reorder triggered for Item: {item_code} in Warehouse: {warehouse}")
#                 create_material_request(item_code, warehouse, reorder_qty)

# def create_material_request(item_code, warehouse, qty):
#     print(f"📝 Creating Material Request for Item: {item_code}, Qty: {qty}, Warehouse: {warehouse}")

#     mr = frappe.new_doc("Material Request")
#     mr.material_request_type = "Repack"
#     mr.transaction_date = nowdate()
#     mr.schedule_date = add_days(nowdate(), 7)
#     mr.company = frappe.db.get_value("Warehouse", warehouse, "company")

#     # ✅ Fetch repack rule

#     repack_rules = frappe.get_all("Repack Production Rule", filters={"type": "Repack"})

#     found = False
#     for rule in repack_rules:
#         rule_doc = frappe.get_doc("Repack Production Rule", rule.name)
#         # Look for item_code in To Items
#         for to_item in rule_doc.to_item:
#             if to_item.item_code == item_code:
#                 found = True
#                 print(f"🔁 Found Repack Rule: {rule.name} for Item: {item_code}")

#                 # 🔄 Add From Items
#                 for from_item in rule_doc.from_item:
#                     mr.append("items", {
#                         "item_code": from_item.item_code,
#                         "warehouse": warehouse,
#                         "qty": from_item.qty,
#                         "uom": from_item.uom,
#                         "schedule_date": add_days(nowdate(), 7)
#                     })

#                 # ➕ Add the To Item from the rule (even if qty from reorder logic)
#                 for to_item_row in rule_doc.to_item:
#                     mr.append("items", {
#                         "item_code": to_item_row.item_code,
#                         "warehouse": warehouse,
#                         "qty": to_item_row.qty,
#                         "uom": to_item_row.uom,
#                         "schedule_date": add_days(nowdate(), 7)
#                     })

#                 break

#     if not found:
#         print("⚠️ No Repack Rule found, falling back to default item only.")
#         mr.append("items", {
#             "item_code": item_code,
#             "warehouse": warehouse,
#             "qty": qty,
#             "uom": frappe.db.get_value("Item", item_code, "stock_uom"),
#             "schedule_date": add_days(nowdate(), 7)
#         })

#     mr.flags.ignore_mandatory = True
#     mr.insert()
#     mr.submit()

#     print(f"✅ Material Request {mr.name} created and submitted.")






# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

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
		# create_repack_request(material_requests)
		# return create_material_request(material_requests)

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





# Splitting the logic into two functions as per user request
def create_material_request(material_requests):
    print("⚠️ Creating Material Requests for Repack/Production...")
    mr_list = []

    for request_type in ["Repack", "Production"]:
        for company in material_requests.get(request_type, {}):
            items = material_requests[request_type][company]
            if not items:
                continue

            for d in items:
                d = frappe._dict(d)
                print(f"🛠 Creating Material Request for {d.item_code} ({request_type})")

                mr = frappe.new_doc("Material Request")
                mr.update({
                    "company": company,
                    "transaction_date": nowdate(),
                    "material_request_type": request_type
                })

                rules = frappe.get_all("Repack Production Rule", filters={"type": request_type})
                found = False

                for rule in rules:
                    rule_doc = frappe.get_doc("Repack Production Rule", rule.name)
                    for to_item in rule_doc.to_item:
                        if to_item.item_code == d.item_code:
                            found = True
                            print(f"🔁 Rule matched: {rule.name}")

                            # Calculate multiplier
                            rule_qty = to_item.qty
                            reorder_qty = d.reorder_qty
                            multiplier = max(1, round(reorder_qty / rule_qty))

                            print(f"🔢 Reorder Qty: {reorder_qty}, Rule Qty: {rule_qty}, Multiplier: {multiplier}")

                            # Add from_items
                            for from_item in rule_doc.from_item:
                                item_doc = frappe.get_doc("Item", from_item.item_code)
                                mr.append("items", {
                                    "item_code": from_item.item_code,
                                    "warehouse": d.warehouse,
                                    "t_warehouse": None,
                                    "s_warehouse": d.warehouse,
                                    "qty": from_item.qty * multiplier,
                                    "uom": from_item.uom,
                                    "item_name": item_doc.item_name,
                                    "description": item_doc.description,
                                    "item_group": item_doc.item_group,
                                    "brand": item_doc.brand,
                                    "schedule_date": add_days(nowdate(), 7)
                                })

                            # Add to_items
                            for to_item_row in rule_doc.to_item:
                                item_doc = frappe.get_doc("Item", to_item_row.item_code)
                                mr.append("items", {
                                    "item_code": to_item_row.item_code,
                                    "warehouse": d.warehouse,
                                    "s_warehouse": None,
                                    "t_warehouse": d.warehouse,
                                    "qty": to_item_row.qty * multiplier,
                                    "uom": to_item_row.uom,
                                    "item_name": item_doc.item_name,
                                    "description": item_doc.description,
                                    "item_group": item_doc.item_group,
                                    "brand": item_doc.brand,
                                    "schedule_date": add_days(nowdate(), 7)
                                })
                            break

                if not found:
                    print("⚠️ No rule found — fallback to only requested item")
                    item_doc = frappe.get_doc("Item", d.item_code)
                    mr.append("items", {
                        "item_code": d.item_code,
                        "warehouse": d.warehouse,
                        "qty": d.reorder_qty,
                        "uom": item_doc.stock_uom,
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

    return mr_list




def create_repack_request(material_requests):
    print("⚠️ Creating Repack Requests only for Repack Type...")
    for company in material_requests.get("Repack", {}):
        items = material_requests["Repack"][company]
        for d in items:
            d = frappe._dict(d)
            rules = frappe.get_all("Repack Production Rule", filters={"type": "Repack"})
            for rule in rules:
                rule_doc = frappe.get_doc("Repack Production Rule", rule.name)
                for to_item in rule_doc.to_item:
                    if to_item.item_code == d.item_code:
                        print(f"⚙️ Creating Repack Request for {d.item_code}")
                        repack_request = frappe.new_doc("Repack Request")
                        repack_request.update({
                            "type": "Repack",
                            "transaction_date": nowdate(),
                            "required_date": add_days(nowdate(), 7),
                            "schedule_date": add_days(nowdate(), 7),
                            "company": company,
                            "warehouse": d.warehouse,
                            "status": "Draft"
                        })

                        for from_item in rule_doc.from_item:
                            item_details = frappe.get_doc("Item", from_item.item_code)
                            repack_request.append("items", {
                                "item_code": from_item.item_code,
                                "item_name": item_details.item_name,
                                "description": item_details.description,
                                "image": item_details.image,
                                "qty": from_item.qty,
                                "uom": from_item.uom,
                                "stock_uom": item_details.stock_uom,
                                "conversion_factor": 1.0,
                                "stock_qty": from_item.qty,
                                "warehouse": d.warehouse,
                                "schedule_date": add_days(nowdate(), 7),
                                "item_group": item_details.item_group,
                                "brand": item_details.brand,
                                "expense_account": item_details.expense_account
                                
                            })

                        for to_item_row in rule_doc.to_item:
                            item_details = frappe.get_doc("Item", to_item_row.item_code)
                            repack_request.append("to_items", {
                                "item_code": to_item_row.item_code,
                                "item_name": item_details.item_name,
                                "description": item_details.description,
                                "image": item_details.image,
                                "qty": to_item_row.qty,
                                "uom": to_item_row.uom,
                                "stock_uom": item_details.stock_uom,
                                "conversion_factor": 1.0,
                                "stock_qty": to_item_row.qty,
                                "warehouse": d.warehouse,
                                "schedule_date": add_days(nowdate(), 7),
                                "item_group": item_details.item_group,
                                "brand": item_details.brand,
                                "expense_account": item_details.expense_account
                            })

                        repack_request.flags.ignore_mandatory = True
                        repack_request.insert()
                        print(f"✅ Repack Request {repack_request.name} created!")









# def create_material_request(material_requests):
# 	print("⚠️ Custom create_material_request() for Repack/Production is running.")
# 	mr_list = []
# 	exceptions_list = []

# 	def _log_exception():
# 		if frappe.local.message_log:
# 			exceptions_list.extend(frappe.local.message_log)
# 			frappe.local.message_log = []
# 		else:
# 			exceptions_list.append(frappe.get_traceback())
# 		frappe.log_error(frappe.get_traceback())

# 	for request_type in ["Repack", "Production"]:
# 		for company in material_requests.get(request_type, {}):
# 			try:
# 				items = material_requests[request_type][company]
# 				if not items:
# 					continue

# 				for d in items:
# 					d = frappe._dict(d)
# 					print(f"🛠 Creating Material Request for {d.item_code} ({request_type})")

# 					mr = frappe.new_doc("Material Request")
# 					mr.update({
# 						"company": company,
# 						"transaction_date": nowdate(),
# 						"material_request_type": request_type
# 					})

# 					rules = frappe.get_all("Repack Production Rule", filters={"type": request_type})
# 					found = False

# 					for rule in rules:
# 						rule_doc = frappe.get_doc("Repack Production Rule", rule.name)
# 						for to_item in rule_doc.to_item:
# 							if to_item.item_code == d.item_code:
# 								found = True
# 								print(f"🔁 Rule matched: {rule.name}")

# 								# ➕ Source Items
# 								for from_item in rule_doc.from_item:
# 									mr.append("items", {
# 										"item_code": from_item.item_code,
# 										"warehouse": d.warehouse,
# 										"t_warehouse": None,
# 										"s_warehouse": d.warehouse,
# 										"qty": from_item.qty,
# 										"uom": from_item.uom,
# 										"schedule_date": add_days(nowdate(), 7)
# 									})
# 								# ➕ Target Items
# 								for to_item_row in rule_doc.to_item:
# 									mr.append("items", {
# 										"item_code": to_item_row.item_code,
# 										"warehouse": d.warehouse,
# 										"s_warehouse": None,
# 										"t_warehouse": d.warehouse,
# 										"qty": to_item_row.qty,
# 										"uom": to_item_row.uom,
# 										"schedule_date": add_days(nowdate(), 7)
# 									})
# 								break

# 					if not found:
# 						print("⚠️ No rule found — fallback to only requested item")
# 						uom = frappe.db.get_value("Item", d.item_code, "stock_uom")
# 						mr.append("items", {
# 							"item_code": d.item_code,
# 							"warehouse": d.warehouse,
# 							"qty": d.reorder_qty,
# 							"uom": uom,
# 							"schedule_date": add_days(nowdate(), 7)
# 						})

# 					mr.flags.ignore_mandatory = True
# 					mr.insert()
# 					mr.submit()
# 					print(f"✅ MR Created: {mr.name}")
# 					mr_list.append(mr)

# 					# 🧠 Create Repack Request if it's Repack type
# 					if request_type == "Repack" and found:
# 						print(f"⚙️ Creating Repack Request for MR {mr.name}")
# 						repack_request = frappe.new_doc("Repack Request")
# 						repack_request.update({
# 							"type": "Repack",
# 							"transaction_date": nowdate(),
# 							"required_date": add_days(nowdate(), 7),
# 							"schedule_date": add_days(nowdate(), 7),
# 							"company": company,
# 							"warehouse": d.warehouse,
# 							"status": "Draft"
# 						})

# 						# ➕ Add source items to 'items' table
# 						for from_item in rule_doc.from_item:
# 							repack_request.append("items", {
# 								"item_code": from_item.item_code,
# 								"qty": from_item.qty,
# 								"uom": from_item.uom,
# 								"for_warehouse": d.warehouse,
# 								"required_date": add_days(nowdate(), 7)
# 							})

# 						# ➕ Add target items to 'to_items' table
# 						for to_item in rule_doc.to_item:
# 							repack_request.append("to_items", {
# 								"item_code": to_item.item_code,
# 								"qty": to_item.qty,
# 								"uom": to_item.uom,
# 								"for_warehouse": d.warehouse,
# 								"required_date": add_days(nowdate(), 7)
# 							})

# 						repack_request.flags.ignore_mandatory = True
# 						repack_request.insert()
# 						print(f"✅ Repack Request {repack_request.name} created!")

# 			except:
# 				_log_exception()

# 	if mr_list and cint(frappe.db.get_value('Stock Settings', None, 'reorder_email_notify')):
# 		send_email_notification(mr_list)

# 	if exceptions_list:
# 		notify_errors(exceptions_list)

# 	return mr_list


# def send_email_notification(mr_list):
# 	""" Notify user about auto creation of indent"""

# 	email_list = frappe.db.sql_list("""select distinct r.parent
# 		from `tabHas Role` r, tabUser p
# 		where p.name = r.parent and p.enabled = 1 and p.docstatus < 2
# 		and r.role in ('Purchase Manager','Stock Manager')
# 		and p.name not in ('Administrator', 'All', 'Guest')""")

# 	msg = frappe.render_template("templates/emails/reorder_item.html", {
# 		"mr_list": mr_list
# 	})

# 	frappe.sendmail(recipients=email_list,
# 		subject=_('Auto Material Requests Generated'), message = msg)

# def notify_errors(exceptions_list):
# 	subject = _("[Important] [ERPNext] Auto Reorder Errors")
# 	content = _("Dear System Manager,") + "<br>" + _("An error occured for certain Items while creating Material Requests based on Re-order level. \
# 		Please rectify these issues :") + "<br>"

# 	for exception in exceptions_list:
# 		exception = json.loads(exception)
# 		error_message = """<div class='small text-muted'>{0}</div><br>""".format(_(exception.get("message")))
# 		content += error_message

# 	content += _("Regards,") + "<br>" + _("Administrator")

# 	from frappe.email import sendmail_to_system_managers
# 	sendmail_to_system_managers(subject, content)





