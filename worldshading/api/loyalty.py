import frappe
from frappe import _
from frappe.utils import nowdate
from erpnext.accounts.doctype.loyalty_program.loyalty_program import (
    get_loyalty_program_details_with_points
)

@frappe.whitelist(allow_guest=True)
def get_loyalty(customer_input, key=None):
    """
    Unified loyalty lookup:
    - Search by Mobile Number
    - Search by Customer ID (CMXXXX)
    """

    # ---------------------------
    # SECURITY CHECK - SECRET KEY
    # ---------------------------
    SECRET_KEY = "859687458WSLP789658745"  # choose your own strong key

    if key != SECRET_KEY:
        return {
            "status": "error",
            "message": "Unauthorized request."
        }


    customer = None
    mobile = None

    # ---------------------------
    # 1. Determine input type
    # ---------------------------
    if customer_input.isdigit():  
        # Search by mobile number (new: Customer.mobile_number field)
        customer = frappe.db.get_value("Customer", {"mobile_number": customer_input}, "name")

        if not customer:
            return {
                "status": "error", 
                "message": "No customer found with this mobile number."
            }

        mobile = customer_input

    else:
        # Search by customer ID
        customer = customer_input
        mobile = frappe.db.get_value(
            "Customer",
            customer,
            "mobile_number"
        )

    # ---------------------------
    # 2. Validate customer
    # ---------------------------
    if not frappe.db.exists("Customer", customer):
        return {"status": "error", "message": "Customer does not exist."}

    customer_name = frappe.db.get_value("Customer", customer, "customer_name")

    # ---------------------------
    # 3. Fetch loyalty details
    # ---------------------------
    loyalty = get_loyalty_program_details_with_points(customer)

    # ---------------------------
    # 4. EXTRA: Expiry information
    # ---------------------------
    today = nowdate()

    # Total expired points
    expired_points = frappe.db.sql("""
        SELECT COALESCE(SUM(loyalty_points), 0)
        FROM `tabLoyalty Point Entry`
        WHERE customer=%s
        AND expiry_date < %s
    """, (customer, today))[0][0]

    # Nearest upcoming expiry amount + date
    next_expiry = frappe.db.sql("""
        SELECT expiry_date, SUM(loyalty_points) AS pts
        FROM `tabLoyalty Point Entry`
        WHERE customer=%s
        AND expiry_date >= %s
        GROUP BY expiry_date
        ORDER BY expiry_date ASC
        LIMIT 1
    """, (customer, today), as_dict=True)

    if next_expiry:
        upcoming_expiry_date = next_expiry[0].expiry_date
        upcoming_expiry_points = next_expiry[0].pts
    else:
        upcoming_expiry_date = None
        upcoming_expiry_points = 0

    # ---------------------------
    # 5. Final API Response
    # ---------------------------
    return {
        "status": "success",
        "customer_id": customer,
        "customer_name": customer_name,
        "mobile": mobile,

        "loyalty_program": loyalty.loyalty_program,
        "points": loyalty.loyalty_points,
        "spent": loyalty.total_spent,

        "tier": loyalty.get("tier_name", "N/A"),
        "collection_factor": loyalty.get("collection_factor", 0),

        # New fields
        "expired_points": expired_points,
        "upcoming_expiry_date": upcoming_expiry_date,
        "upcoming_expiry_points": upcoming_expiry_points
    }



