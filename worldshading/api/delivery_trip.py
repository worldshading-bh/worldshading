import frappe
from frappe.model.mapper import get_mapped_doc

@frappe.whitelist()
def custom_make_delivery_trip(source_name, target_doc=None, source_doctype=None):

    # fallback to Delivery Note if source_doctype is not passed
    if not source_doctype:
        source_doctype = "Delivery Note"

    # ✅ Case 1: from Delivery Note
    if source_doctype == "Delivery Note":
        delivery_notes = []

        def update_stop_details(source_doc, target_doc, source_parent):
            target_doc.customer = source_parent.customer
            target_doc.address = source_parent.shipping_address_name
            target_doc.customer_address = source_parent.shipping_address
            target_doc.contact = source_parent.contact_person
            target_doc.customer_contact = source_parent.contact_display
            target_doc.grand_total = source_parent.grand_total
            delivery_notes.append(target_doc.delivery_note)

        doclist = get_mapped_doc("Delivery Note", source_name, {
            "Delivery Note": {
                "doctype": "Delivery Trip",
                "validation": {
                    "docstatus": ["in", [0, 1]]
                }
            },
            "Delivery Note Item": {
                "doctype": "Delivery Stop",
                "field_map": {
                    "parent": "delivery_note"
                },
                "condition": lambda item: item.parent not in delivery_notes,
                "postprocess": update_stop_details
            }
        }, target_doc)

        doclist.type = "Delivery Note"

    # ✅ Case 2: from Stock Entry (Material Transfer)
    elif source_doctype == "Stock Entry":
        
        stock_entry = frappe.get_doc("Stock Entry", source_name)

        doclist = frappe.new_doc("Delivery Trip")
        doclist.type = "Material Transfer"
        doclist.reference = stock_entry.name
        doclist.company = stock_entry.company

        # ✅ Fetch from first row
        if stock_entry.items:
            first_item = stock_entry.items[0]
            s_warehouse = first_item.s_warehouse or "?"
            t_warehouse = first_item.t_warehouse or "?"
            doclist.reference = f"Need material transfer from {s_warehouse} to {t_warehouse}."

        #✅ Fixed stop details
        doclist.append("delivery_stops", {
            "customer": "CM0922",
            "address": "CM0385-Billing"
        })

    else:
        frappe.throw("Unsupported source_doctype: " + source_doctype)

    return doclist