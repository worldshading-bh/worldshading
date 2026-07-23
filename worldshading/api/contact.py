import frappe

@frappe.whitelist()
def update_contact_whatsapp(contact, country_code, whatsapp_no):

    try:

        if not contact:
            frappe.throw("Contact is required")

        # ==================================================
        # Normalize Country Code
        # ==================================================
        cc = ""

        for ch in (country_code or ""):
            if ch.isdigit():
                cc = cc + ch

        # ==================================================
        # Normalize Phone
        # ==================================================
        phone = ""

        for ch in (whatsapp_no or ""):
            if ch.isdigit():
                phone = phone + ch

        # Remove leading zero
        if phone.startswith("0"):
            phone = phone[1:]

        if not phone:
            frappe.throw("WhatsApp number is required")

        # ==================================================
        # Full WhatsApp Number
        # ==================================================
        full_number = cc + phone

        # ==================================================
        # Load Contact
        # ==================================================
        contact_doc = frappe.get_doc("Contact", contact)

        # ==================================================
        # Remove old WhatsApp flags
        # ==================================================
        for row in contact_doc.phone_nos:
            row.is_whatsapp = 0

        matched_row = None

        # ==================================================
        # Reuse existing row if phone matches
        # ==================================================
        for row in contact_doc.phone_nos:

            existing_phone = ""

            for ch in (row.phone or ""):
                if ch.isdigit():
                    existing_phone = existing_phone + ch

            # Remove leading zero
            if existing_phone.startswith("0"):
                existing_phone = existing_phone[1:]

            if existing_phone == phone:

                matched_row = row

                break

        # ==================================================
        # Create new row if not found
        # ==================================================
        if not matched_row:

            matched_row = contact_doc.append("phone_nos", {})

            matched_row.phone = phone

        # ==================================================
        # Update row details
        # ==================================================
        matched_row.country_code = country_code
        matched_row.is_whatsapp = 1

        # ==================================================
        # Save Contact
        # ==================================================
        contact_doc.save(ignore_permissions=True)

        return {
            "status": "success",
            "whatsapp_no": full_number
        }

    except Exception:

        frappe.log_error(
            frappe.get_traceback(),
            "Update Contact WhatsApp Failed"
        )

        raise




@frappe.whitelist()
def check_customer_phone_duplicates(
    mobile_no=None,
    customer_name=None,
    customer_type=None
):
    # frappe.msgprint("Checking for duplicates ")

    matches = []

    # ==================================================
    # Clean Entered Number
    # ==================================================

    entered_number = ""

    for ch in (mobile_no or ""):

        if ch.isdigit():

            entered_number = entered_number + ch

    entered_number = entered_number[-8:]

    # ==================================================
    # No Number
    # ==================================================

    if not entered_number:

        return {
            "has_duplicate": 0,
            "matches": []
        }

    # ==================================================
    # PERFORMANCE OPTIMIZATION
    # Search only possible matches
    # ==================================================

    last_four = entered_number[-4:]

    contact_phones = frappe.get_all(
        "Contact Phone",
        filters={
            "phone": ["like", "%" + last_four + "%"]
        },
        fields=[
            "parent",
            "phone"
        ]
    )

    # ==================================================
    # Compare Final Last 8 Digits
    # ==================================================

    for row in contact_phones:

        saved_number = ""

        for ch in (row.phone or ""):

            if ch.isdigit():

                saved_number = saved_number + ch

        saved_number = saved_number[-8:]

        # ==================================================
        # Exact Match
        # ==================================================

        if saved_number == entered_number:

            links = frappe.get_all(
                "Dynamic Link",
                filters={
                    "parent": row.parent,
                    "link_doctype": "Customer"
                },
                fields=["link_name"],
                limit=1
            )

            if links:

                customer_id = links[0].link_name

                customer = frappe.db.get_value(
                    "Customer",
                    customer_id,
                    [
                        "customer_name",
                        "customer_type",
                        "whatsapp_no",
                        "disabled"
                    ],
                    as_dict=True
                )

                if customer:

                    matches.append({
                        "name": customer_id,
                        "customer_name": customer.customer_name,
                        "customer_type": customer.customer_type,
                        "whatsapp_no": customer.whatsapp_no,
                        "disabled": customer.disabled
                    })

    # ==================================================
    # Remove Duplicate Customers
    # ==================================================

    unique_matches = []
    added_customers = []

    for row in matches:

        if row["name"] not in added_customers:

            unique_matches.append(row)

            added_customers.append(row["name"])

    # ==================================================
    # Final Response
    # ==================================================

    return {
        "has_duplicate": 1 if unique_matches else 0,
        "matches": unique_matches
    }