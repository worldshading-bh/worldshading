import frappe
from frappe.utils import add_days, nowdate

def execute():
    print("🧹 Running Draft Cleanup Schedule...")

    rules = frappe.get_all("Draft Cleanup Schedule", filters={"disabled": 0}, fields="*")

    for rule in rules:
        try:
            doctype = rule.target_doctype
            date_field = rule.filter_field
            days_old = rule.days_older_than or 10
            limit = rule.limit or 5

            target_date = add_days(nowdate(), -days_old)

            filters = {
                "docstatus": 0,
                date_field: ("<=", f"{target_date} 23:59:59")
            }

            docs = frappe.get_all(doctype, filters=filters, fields=["name"], limit=limit)

            print(f"🔍 {doctype}: Found {len(docs)} draft docs older than {days_old} days (via {date_field})")

            for d in docs:
                try:
                    doc = frappe.get_doc(doctype, d.name)
                    doc.delete()
                    print(f"🗑️ Deleted {doctype}: {doc.name}")
                except Exception as e:
                    print(f"❌ Failed to delete {doctype} {d.name}: {e}")

        except Exception as e:
            frappe.log_error(frappe.get_traceback(), "Draft Cleanup Scheduler Error")
            print(f"⚠️ Error processing rule {rule.name}: {e}")
