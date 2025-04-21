# # worldshading/worldshading/hooks/material_request_hooks.py

# from erpnext.stock.get_item_details import get_item_details

# def process_to_items(doc, method):
#     if doc.material_request_type != "Repack":
#         return

#     for item in doc.to_item:
#         if not item.conversion_factor:
#             item.conversion_factor = 1

#         item.stock_qty = item.qty * item.conversion_factor

#         args = {
#             "item_code": item.item_code,
#             "warehouse": item.warehouse,
#             "company": doc.company,
#             "qty": item.qty,
#             "conversion_factor": item.conversion_factor,
#             "doctype": doc.doctype,
#         }

#         item_data = get_item_details(args)

#         for field, value in item_data.items():
#             if hasattr(item, field) and not getattr(item, field):
#                 setattr(item, field, value)
