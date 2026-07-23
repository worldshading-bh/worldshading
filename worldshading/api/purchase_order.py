import frappe
from frappe.utils import nowdate, getdate
from erpnext.buying.doctype.purchase_order.purchase_order import make_purchase_receipt
from erpnext.buying.doctype.purchase_order.purchase_order import make_purchase_invoice
from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry


@frappe.whitelist()
def create_payment_from_schedule(
    po_name,
    paid_from,
    bank_request_reference=None,
    cheque_leaf=None,
    posting_date=None
):

    if not po_name:
        frappe.throw("Purchase Order not provided.")

    if not paid_from:
        frappe.throw("Paid From account is required.")

    po = frappe.get_doc("Purchase Order", po_name)

    if not po.payment_schedule:
        frappe.throw("No payment schedule found in this Purchase Order.")

    today = getdate(nowdate())
    posting_date = posting_date or nowdate()

    # --------------------------------------------------
    # Collect unpaid schedule rows
    # --------------------------------------------------

    valid_rows = [
        row for row in po.payment_schedule
        if row.payment_amount and row.payment_amount > 0 and not row.payment_entry
    ]

    if not valid_rows:
        frappe.throw("No unpaid payment schedule rows found.")

    # Sort by due date
    valid_rows.sort(
        key=lambda r: getdate(r.due_date) if r.due_date else today
    )

    created_pes = []

    mop_to_state = {
        "Cheque": "Pending Cheque Payment - Chkr",
        "Bank Transfer": "Pending Bank Payment - Chkr",
        "Cash": "Pending Cash Payment - Chkr",
        "Credit": "Pending Local Credit Payment - Chkr"
    }

    # --------------------------------------------------
    # Helper → Create PE (Dashboard Logic Preserved)
    # --------------------------------------------------

    def create_pe_from_row(row, is_main=False):

        # 1️⃣ Let ERP initialize like dashboard
        pe = get_payment_entry("Purchase Order", po.name)
        default_reference = pe.references[0] if pe.references else None

        # 2️⃣ Remove default full allocation
        pe.references = []

        # 3️⃣ Calculate BASE amount proportionally (using stored base totals)
        if po.grand_total:
            base_amount = (float(row.payment_amount) / float(po.grand_total)) * float(po.base_grand_total)
        else:
            base_amount = 0

        # Round properly using ERP precision
        base_amount = frappe.utils.flt(
            base_amount,
            frappe.get_precision("Payment Entry", "paid_amount")
        )

        # Preserve ERPNext's rounded PO reference values from get_payment_entry.
        total_amount = base_amount
        outstanding_amount = base_amount

        if default_reference:
            total_amount = default_reference.total_amount
            outstanding_amount = default_reference.outstanding_amount

        # 4️⃣ Override payment fields
        pe.posting_date = row.due_date or posting_date
        pe.mode_of_payment = row.mode_of_payment
        pe.paid_from = paid_from
        pe.reference_no = po.name
        pe.reference_date = row.due_date or posting_date

        pe.paid_amount = base_amount
        pe.received_amount = base_amount

        # 5️⃣ Allocate in BASE (since supplier ledger is BHD)
        pe.append("references", {
            "reference_doctype": "Purchase Order",
            "reference_name": po.name,
            "total_amount": total_amount,
            "outstanding_amount": outstanding_amount,
            "allocated_amount": base_amount
        })

        # 6️⃣ Let ERP finalize calculations
        pe.setup_party_account_field()
        pe.set_missing_values()
        pe.set_exchange_rate()
        pe.set_amounts()

        due_date = getdate(row.due_date) if row.due_date else today

        if is_main and due_date <= today:

            if row.mode_of_payment == "Bank Transfer":
                if not bank_request_reference:
                    frappe.throw("Bank Request Reference required.")
                pe.bank_request_reference = bank_request_reference

            if row.mode_of_payment == "Cheque":
                if not cheque_leaf:
                    frappe.throw("Cheque Leaf required.")
                pe.cheque_leaf = cheque_leaf

        # 8️⃣ Insert
        pe.insert(ignore_permissions=True)

        # 9️⃣ Link schedule row
        row.db_set("payment_entry", pe.name)

        # 🔟 Workflow state
        due_date = getdate(row.due_date) if row.due_date else today

        if due_date > today:
            pe.db_set("workflow_state", "Scheduled")
        else:
            state = mop_to_state.get(row.mode_of_payment)
            if state:
                pe.db_set("workflow_state", state)

        return pe.name

    # --------------------------------------------------
    # STEP 1 → Main PE
    # --------------------------------------------------

    main_pe_name = create_pe_from_row(valid_rows[0], is_main=True)
    created_pes.append(main_pe_name)

    # --------------------------------------------------
    # STEP 2 → Remaining PEs
    # --------------------------------------------------

    for row in valid_rows[1:]:
        pe_name = create_pe_from_row(row, is_main=False)
        created_pes.append(pe_name)

    # --------------------------------------------------
    # STEP 3 → Auto Move PO if all Payments are Scheduled
    # --------------------------------------------------

    skip_workflow = False
    all_scheduled = True

    for pe_name in created_pes:

        pe_state = frappe.get_value(
            "Payment Entry",
            pe_name,
            "workflow_state"
        )

        if pe_state != "Scheduled":
            all_scheduled = False
            break


    if all_scheduled:

        # Decide next workflow state
        if po.supplier_country == "Bahrain":
            next_state = "Pending Local Delivery"
        else:
            next_state = "In Production"

        po.workflow_state = next_state
        po.flags.ignore_validate = True
        po.save(ignore_permissions=True)

        skip_workflow = True

        frappe.msgprint(
            "All payments are future scheduled. PO moved to <b>{}</b>.".format(next_state)
        )

    frappe.msgprint(
        "Payment Entries Created:<br><br>" + "<br>".join(created_pes)
    )

    return {
        "main_pe": main_pe_name,
        "skip_workflow": skip_workflow
    }
    
# Before rounded total fix
# @frappe.whitelist()
# def create_payment_from_schedule(
#     po_name,
#     paid_from,
#     bank_request_reference=None,
#     cheque_leaf=None,
#     posting_date=None
# ):

#     if not po_name:
#         frappe.throw("Purchase Order not provided.")

#     if not paid_from:
#         frappe.throw("Paid From account is required.")

#     po = frappe.get_doc("Purchase Order", po_name)

#     if not po.payment_schedule:
#         frappe.throw("No payment schedule found in this Purchase Order.")

#     today = getdate(nowdate())
#     posting_date = posting_date or nowdate()

#     # --------------------------------------------------
#     # Collect unpaid schedule rows
#     # --------------------------------------------------

#     valid_rows = [
#         row for row in po.payment_schedule
#         if row.payment_amount and row.payment_amount > 0 and not row.payment_entry
#     ]

#     if not valid_rows:
#         frappe.throw("No unpaid payment schedule rows found.")

#     # Sort by due date
#     valid_rows.sort(
#         key=lambda r: getdate(r.due_date) if r.due_date else today
#     )

#     created_pes = []

#     mop_to_state = {
#         "Cheque": "Pending Cheque Payment - Chkr",
#         "Bank Transfer": "Pending Bank Payment - Chkr",
#         "Cash": "Pending Cash Payment - Chkr",
#         "Credit": "Pending Local Credit Payment - Chkr"
#     }

#     # --------------------------------------------------
#     # Helper → Create PE (Dashboard Logic Preserved)
#     # --------------------------------------------------

#     def create_pe_from_row(row, is_main=False):

#         # 1️⃣ Let ERP initialize like dashboard
#         pe = get_payment_entry("Purchase Order", po.name)

#         # 2️⃣ Remove default full allocation
#         pe.references = []

#         # 3️⃣ Calculate BASE amount proportionally (using stored base totals)
#         if po.grand_total:
#             base_amount = (float(row.payment_amount) / float(po.grand_total)) * float(po.base_grand_total)
#         else:
#             base_amount = 0

#         # Round properly using ERP precision
#         base_amount = frappe.utils.flt(
#             base_amount,
#             frappe.get_precision("Payment Entry", "paid_amount")
#         )

#         # 4️⃣ Override payment fields
#         pe.posting_date = row.due_date or posting_date
#         pe.mode_of_payment = row.mode_of_payment
#         pe.paid_from = paid_from
#         pe.reference_no = po.name
#         pe.reference_date = row.due_date or posting_date

#         pe.paid_amount = base_amount
#         pe.received_amount = base_amount

#         # 5️⃣ Allocate in BASE (since supplier ledger is BHD)
#         pe.append("references", {
#             "reference_doctype": "Purchase Order",
#             "reference_name": po.name,
#             "allocated_amount": base_amount
#         })

#         # 6️⃣ Let ERP finalize calculations
#         pe.setup_party_account_field()
#         pe.set_missing_values()
#         pe.set_exchange_rate()
#         pe.set_amounts()

#         due_date = getdate(row.due_date) if row.due_date else today

#         if is_main and due_date <= today:

#             if row.mode_of_payment == "Bank Transfer":
#                 if not bank_request_reference:
#                     frappe.throw("Bank Request Reference required.")
#                 pe.bank_request_reference = bank_request_reference

#             if row.mode_of_payment == "Cheque":
#                 if not cheque_leaf:
#                     frappe.throw("Cheque Leaf required.")
#                 pe.cheque_leaf = cheque_leaf

#         # 8️⃣ Insert
#         pe.insert(ignore_permissions=True)

#         # 9️⃣ Link schedule row
#         row.db_set("payment_entry", pe.name)

#         # 🔟 Workflow state
#         due_date = getdate(row.due_date) if row.due_date else today

#         if due_date > today:
#             pe.db_set("workflow_state", "Scheduled")
#         else:
#             state = mop_to_state.get(row.mode_of_payment)
#             if state:
#                 pe.db_set("workflow_state", state)

#         return pe.name

#     # --------------------------------------------------
#     # STEP 1 → Main PE
#     # --------------------------------------------------

#     main_pe_name = create_pe_from_row(valid_rows[0], is_main=True)
#     created_pes.append(main_pe_name)

#     # --------------------------------------------------
#     # STEP 2 → Remaining PEs
#     # --------------------------------------------------

#     for row in valid_rows[1:]:
#         pe_name = create_pe_from_row(row, is_main=False)
#         created_pes.append(pe_name)

#     # --------------------------------------------------
#     # STEP 3 → Auto Move PO if all Payments are Scheduled
#     # --------------------------------------------------

#     skip_workflow = False
#     all_scheduled = True

#     for pe_name in created_pes:

#         pe_state = frappe.get_value(
#             "Payment Entry",
#             pe_name,
#             "workflow_state"
#         )

#         if pe_state != "Scheduled":
#             all_scheduled = False
#             break


#     if all_scheduled:

#         # Decide next workflow state
#         if po.supplier_country == "Bahrain":
#             next_state = "Pending Local Delivery"
#         else:
#             next_state = "In Production"

#         po.workflow_state = next_state
#         po.flags.ignore_validate = True
#         po.save(ignore_permissions=True)

#         skip_workflow = True

#         frappe.msgprint(
#             "All payments are future scheduled. PO moved to <b>{}</b>.".format(next_state)
#         )

#     frappe.msgprint(
#         "Payment Entries Created:<br><br>" + "<br>".join(created_pes)
#     )

#     return {
#         "main_pe": main_pe_name,
#         "skip_workflow": skip_workflow
#     }

# create arrival payment through PI and PE
@frappe.whitelist()
def create_arrival_payment_from_po(
    po_name,
    supplier,
    item_code,
    amount,
    mode_of_payment,
    paid_from,
    bank_request_reference=None,
    cheque_leaf=None,
    posting_date=None
):

    # --------------------------------------------------
    # Basic Validations
    # --------------------------------------------------

    if not po_name:
        frappe.throw("Purchase Order not provided.")

    if not supplier:
        frappe.throw("Supplier is required.")

    if not item_code:
        frappe.throw("Arrival Item is required.")

    if not amount or float(amount) <= 0:
        frappe.throw("Amount must be greater than zero.")

    if not paid_from:
        frappe.throw("Paid From account is required.")

    if mode_of_payment == "Bank Transfer":
        if not bank_request_reference:
            frappe.throw("Bank Request Reference is required for Bank Transfer.")

    if mode_of_payment == "Cheque":
        if not cheque_leaf:
            frappe.throw("Cheque Leaf is required for Cheque payment.")

        leaf = frappe.get_doc("Cheque Leaf", cheque_leaf)

        if leaf.status != "Available":
            frappe.throw("Selected cheque leaf is not available.")
    # --------------------------------------------------
    # Fetch PO
    # --------------------------------------------------

    po = frappe.get_doc("Purchase Order", po_name)

    
    # --------------------------------------------------
    # Prevent duplicate Arrival PI for same Arrival Note Agent
    # --------------------------------------------------

    existing_pi = frappe.get_all(
        "Purchase Invoice",
        filters={
            "reference_purchase_order": po.name,
            "supplier": supplier,
            "docstatus": ["!=", 2]
        },
        fields=["name"]
    )

    if existing_pi:
        frappe.throw(
            f"Arrival Invoice already exists for this PO under supplier {supplier}."
        )

    # --------------------------------------------------
    # Create Purchase Invoice
    # --------------------------------------------------

    pi = frappe.new_doc("Purchase Invoice")
    pi.supplier = supplier
    pi.company = po.company
    pi.posting_date = posting_date if posting_date else nowdate()
    pi.set_posting_time = 1
    pi.reference_purchase_order = po.name
    pi.update_stock = 0
    pi.set_warehouse = po.set_warehouse
    pi.disable_rounded_total = 1
    pi.against_expense_account = "Arrival Note - WS"
    pi.remarks = "Auto-created Arrival Note Invoice from PO " + po.name

    pi.append("items", {
        "item_code": item_code,
        "qty": 1,
        "rate": amount,
        "expense_account": "Arrival Note - WS"
    })

    pi.insert(ignore_permissions=True)
    pi.submit()
    pi.workflow_state = "Completed"
    pi.save(ignore_permissions=True)

    # --------------------------------------------------
    # Get Default Payable Account
    # --------------------------------------------------

    creditors_account = frappe.get_value(
        "Company",
        po.company,
        "default_payable_account"
    )

    if not creditors_account:
        frappe.throw("No default payable account found.")

    # --------------------------------------------------
    # Create Payment Entry (Draft)
    # --------------------------------------------------

    pe = frappe.new_doc("Payment Entry")
    pe.payment_type = "Pay"
    pe.company = po.company
    pe.party_type = "Supplier"
    pe.party = supplier
    pe.posting_date = pi.posting_date
    pe.mode_of_payment = mode_of_payment
    if mode_of_payment == "Bank Transfer":
        pe.bank_request_reference = bank_request_reference

    if mode_of_payment == "Cheque":
        pe.cheque_leaf = cheque_leaf    

    pe.reference_no = pi.name
    pe.reference_date = pi.posting_date

    pe.paid_from = paid_from
    pe.paid_to = creditors_account

    pe.paid_amount = pi.grand_total
    pe.received_amount = pi.grand_total
    pe.is_arrival_payment = 1

    pe.append("references", {
        "reference_doctype": "Purchase Invoice",
        "reference_name": pi.name,
        "allocated_amount": pi.grand_total
    })

    pe.insert(ignore_permissions=True)  # Draft only
    mop_to_state = {
        "Cheque": "Pending Cheque Payment - Chkr",
        "Bank Transfer": "Pending Bank Payment - Chkr",
        "Cash": "Pending Cash Payment - Chkr"
    }

    if mode_of_payment in mop_to_state:
        pe.db_set("workflow_state", mop_to_state[mode_of_payment])

    frappe.msgprint(
        f"Arrival Purchase Invoice {pi.name} created. Redirecting to Payment Entry {pe.name}."
    )

    return {
        "purchase_invoice": pi.name,
        "payment_entry": pe.name
    }

# create gl payment directly from PO for customs clearance payment - new method using GL Payment doctype
import json
@frappe.whitelist()
def create_customs_payment_from_po(
    po_name,
    gl_items,
    total_amount,
    mode_of_payment,
    paid_from,
    bank_request_reference=None,
    cheque_leaf=None,
    posting_date=None
):

    # --------------------------------------------------
    # Basic Validations
    # --------------------------------------------------

    if not po_name:
        frappe.throw("Purchase Order not provided.")

    if not total_amount or float(total_amount) <= 0:
        frappe.throw("Total amount must be greater than zero.")

    if not gl_items:
        frappe.throw("GL items are required.")

    if not paid_from:
        frappe.throw("Paid From account is required.")

    if mode_of_payment == "Bank Transfer":
        if not bank_request_reference:
            frappe.throw("Bank Request Reference is required for Bank Transfer.")

    if mode_of_payment == "Cheque":
        if not cheque_leaf:
            frappe.throw("Cheque Leaf is required for Cheque payment.")

        leaf = frappe.get_doc("Cheque Leaf", cheque_leaf)

        if leaf.status != "Available":
            frappe.throw("Selected cheque leaf is not available.")

    # --------------------------------------------------
    # Normalize gl_items (🔥 FIX)
    # --------------------------------------------------

    if isinstance(gl_items, str):
        gl_items = json.loads(gl_items)

    # --------------------------------------------------
    # Fetch PO
    # --------------------------------------------------

    po = frappe.get_doc("Purchase Order", po_name)

    if po.workflow_state != "Pending Payment - Customs":
        frappe.throw("Purchase Order is not in Pending Payment - Customs state.")

    # --------------------------------------------------
    # Prevent Duplicate GL Payment
    # --------------------------------------------------
    existing = frappe.get_all(
        "GL Payment",
        filters={
            "purchase_order": po.name,
            "is_customs_payment": 1,
            "docstatus": ["!=", 2]
        },
        fields=["name"]
    )

    if existing:
        frappe.throw("Customs GL Payment already exists for this Purchase Order.")

    # --------------------------------------------------
    # Create GL Payment
    # --------------------------------------------------

    glp = frappe.get_doc({
        "doctype": "GL Payment",
        "payment_type": "Outgoing",
        "posting_date": posting_date or frappe.utils.nowdate(),
        "company": po.company,
        "mode_of_payment": mode_of_payment,
        "cost_center": po.get("cost_center") or "Main - WS",
        "party_type": "Supplier",
        "party": po.supplier,
        "payment_account": paid_from,
        "net_amount": total_amount,
        "total_amount": total_amount,
        "reference_no": bank_request_reference or po.name,
        "reference_date": posting_date or frappe.utils.nowdate(),
        "remarks": "Being customs paid for PO# {}".format(po.name),
        "purchase_order": po.name,
        "is_customs_payment": 1
    })

    # --------------------------------------------------
    # Add GL Items (🔥 CORE CHANGE)
    # --------------------------------------------------

    for row in gl_items:

        account = row.get("account")
        amount = float(row.get("net_amount") or 0)

        if not account or amount <= 0:
            frappe.throw("Invalid GL item row detected.")

        glp.append("items", {
            "account": account,
            "net_amount": amount,
            "tax_amount": 0
        })

    # --------------------------------------------------
    # Insert (Draft Only)
    # --------------------------------------------------

    glp.insert(ignore_permissions=True)

    # --------------------------------------------------
    # Set Workflow State Based on Mode of Payment
    # --------------------------------------------------

    target_state = None

    if mode_of_payment == "Bank Transfer":
        target_state = "Pending Bank Payment - Chkr"

    elif mode_of_payment == "Cheque":
        target_state = "Pending Cheque Payment - Chkr"

    elif mode_of_payment == "Cash":
        target_state = "Pending Cash Payment - Chkr"

    if target_state:
        glp.db_set("workflow_state", target_state)


    frappe.msgprint(
        "Customs GL Payment " + glp.name + " created successfully."
    )

    return {
        "gl_payment": glp.name
    }

# # create customs clearance payment directly from PO  using PE -old method
# @frappe.whitelist()
# def create_customs_payment_from_po(
#     po_name,
#     total_amount,
#     custom_other_charges,
#     mode_of_payment,
#     paid_from,
#     bank_request_reference=None,
#     cheque_leaf=None,
#     posting_date=None
# ):

#     # --------------------------------------------------
#     # Basic Validations
#     # --------------------------------------------------

#     if not po_name:
#         frappe.throw("Purchase Order not provided.")

#     if not total_amount or float(total_amount) <= 0:
#         frappe.throw("Total Bayan Amount must be greater than zero.")

#     if custom_other_charges is None or float(custom_other_charges) < 0:
#         frappe.throw("Custom Other Charges must be valid.")

#     if float(custom_other_charges) >= float(total_amount):
#         frappe.throw("Custom Other Charges cannot be equal or greater than total amount.")

#     if not paid_from:
#         frappe.throw("Paid From account is required.")

#     if mode_of_payment == "Bank Transfer":
#         if not bank_request_reference:
#             frappe.throw("Bank Request Reference is required for Bank Transfer.")

#     if mode_of_payment == "Cheque":
#         if not cheque_leaf:
#             frappe.throw("Cheque Leaf is required for Cheque payment.")

#         leaf = frappe.get_doc("Cheque Leaf", cheque_leaf)

#         if leaf.status != "Available":
#             frappe.throw("Selected cheque leaf is not available.")
#     # --------------------------------------------------
#     # Fetch PO FIRST
#     # --------------------------------------------------

#     po = frappe.get_doc("Purchase Order", po_name)

#     if po.workflow_state != "Pending Payment - Customs":
#         frappe.throw("Purchase Order is not in Pending Payment - Customs state.")


#     # --------------------------------------------------
#     # Prevent Duplicate Customs Payment
#     # --------------------------------------------------

#     customs_pes = frappe.get_all(
#         "Payment Entry",
#         filters={
#             "is_customs_payment": 1,
#             "docstatus": ["!=", 2]
#         },
#         fields=["name"]
#     )

#     for pe_row in customs_pes:

#         refs = frappe.get_all(
#             "Payment Entry Reference",
#             filters={
#                 "parent": pe_row.name,
#                 "reference_doctype": "Purchase Order",
#                 "reference_name": po.name
#             },
#             fields=["name"]
#         )
#         if refs:
#             frappe.throw("Customs Payment already exists for this Purchase Order.")

#     # --------------------------------------------------
#     # Get Default Payable Account
#     # --------------------------------------------------

#     creditors_account = frappe.get_value(
#         "Company",
#         po.company,
#         "default_payable_account"
#     )

#     if not creditors_account:
#         frappe.throw("No default payable account found.")

#     # --------------------------------------------------
#     # Calculate Allocation
#     # --------------------------------------------------

#     total_amount = float(total_amount)
#     custom_other_charges = float(custom_other_charges)
#     allocated_amount = total_amount - custom_other_charges

#     # --------------------------------------------------
#     # Create Payment Entry (Draft)
#     # --------------------------------------------------

#     pe = frappe.new_doc("Payment Entry")
#     pe.payment_type = "Pay"
#     pe.company = po.company
#     pe.party_type = "Supplier"
#     pe.party = po.supplier
#     pe.posting_date = posting_date or nowdate()
#     pe.mode_of_payment = mode_of_payment
#     if mode_of_payment == "Bank Transfer":
#         pe.bank_request_reference = bank_request_reference

#     if mode_of_payment == "Cheque":
#         pe.cheque_leaf = cheque_leaf

#     pe.reference_no = po.name
#     pe.reference_date = posting_date or nowdate()

#     pe.paid_from = paid_from
#     pe.paid_to = creditors_account

#     pe.paid_amount = total_amount
#     pe.received_amount = total_amount

#     # Mark as Customs Payment
#     pe.is_customs_payment = 1
#     pe.purchase_order_reference = po.name

#     # Deduction Entry
#     pe.append("deductions", {
#         "account": "Custom Other Charges - WS",
#         "cost_center": "Main - WS",
#         "amount": custom_other_charges
#     })

#     pe.insert(ignore_permissions=True)  # Draft only

#     # --------------------------------------------------
#     # Set Workflow State Based on Mode of Payment
#     # --------------------------------------------------

#     target_state = None

#     if mode_of_payment == "Bank Transfer":
#         target_state = "Pending Bank Payment - Chkr"

#     elif mode_of_payment == "Cheque":
#         target_state = "Pending Cheque Payment - Chkr"

#     elif mode_of_payment == "Cash":
#         target_state = "Pending Cash Payment - Chkr"

#     if target_state:
#         pe.db_set("workflow_state", target_state)

#     frappe.msgprint(
#         "Customs Payment Entry " + pe.name + " created successfully."
#     )

#     return {
#         "payment_entry": pe.name
#     }



# create PR and PI from PO after customs clearance - old method without GL Payment doctype
# @frappe.whitelist()
# def create_pr_from_po(po_name):

#     if not po_name:
#         frappe.throw("Purchase Order not provided.")

#     po = frappe.get_doc("Purchase Order", po_name)

#     # if po.workflow_state != "Pending Customs Clearance":
#     #     frappe.throw("Purchase Order not in Pending Customs Clearance state.")

#     # --------------------------------------------------
#     # Prevent Duplicate PR
#     # --------------------------------------------------

#     existing_pr = frappe.get_all(
#         "Purchase Receipt Item",
#         filters={
#             "purchase_order": po.name,
#             "docstatus": ["!=", 2]
#         },
#         fields=["parent"]
#     )

#     if existing_pr:
#         frappe.throw("Purchase Receipt already exists for this Purchase Order.")

#     # --------------------------------------------------
#     # Prevent Duplicate Main PI
#     # --------------------------------------------------

#     # existing_pi = frappe.get_all(
#     #     "Purchase Invoice",
#     #     filters={
#     #         "reference_purchase_order": po.name,
#     #         "docstatus": ["!=", 2]
#     #     },
#     #     fields=["name"]
#     # )

#     # if existing_pi:
#     #     frappe.throw("Purchase Invoice already exists for this Purchase Order.")

#     # --------------------------------------------------
#     # 1️⃣ CREATE PURCHASE RECEIPT (Draft)
#     # --------------------------------------------------

#     pr = make_purchase_receipt(po_name)
#     pr.posting_date = nowdate()
#     pr.set_posting_time = 1

#     pr.insert(ignore_permissions=True)
#     pr.db_set("workflow_state", "Pending Receipt")

#     # --------------------------------------------------
#     # 2️⃣ CREATE MAIN PURCHASE INVOICE (Draft)
#     # --------------------------------------------------

#     pi = make_purchase_invoice(po_name)

#     pi.posting_date = nowdate()
#     pi.set_posting_time = 1

#     # IMPORTANT
#     pi.update_stock = 0

#     #To reload the payment schedule with the newly created invoice date.
#     pi.set("payment_schedule", [])   # clear old schedule
#     if pi.payment_terms_template:
#         pi.set_payment_schedule()


#     pi.insert(ignore_permissions=True)
#     pi.db_set("workflow_state", "Pending Valuation Approval")
#     pi.save(ignore_permissions=True)


#     frappe.msgprint(
#         "Purchase Receipt " + pr.name +
#         " and Purchase Invoice " + pi.name +
#         " created."
#     )

#     return {
#         "purchase_receipt": pr.name,
#         "purchase_invoice": pi.name
#     }



@frappe.whitelist()
def create_pr_from_po(po_name):

    if not po_name:
        frappe.throw("Purchase Order not provided.")

    po = frappe.get_doc("Purchase Order", po_name)
    # --------------------------------------------------
    # Prevent Duplicate PR and PI
    # --------------------------------------------------

    existing_pr = frappe.get_all(
        "Purchase Receipt Item",
        filters={
            "purchase_order": po.name,
            "docstatus": ["!=", 2]
        },
        fields=["parent"]
    )

    if existing_pr:
        frappe.throw("Purchase Receipt already exists for this Purchase Order.")

    existing_pi = frappe.get_all(
        "Purchase Invoice Item",
        filters={
            "purchase_order": po.name,
            "docstatus": ["!=", 2]
        },
        fields=["parent"]
    )

    if existing_pi:
        frappe.throw("Purchase Invoice already exists for this Purchase Order.")

    # --------------------------------------------------
    # 1️⃣ CREATE PURCHASE RECEIPT (Draft)
    # --------------------------------------------------

    # --------------------------------------------------
    # 1️⃣ CREATE PURCHASE RECEIPT (Draft)
    # --------------------------------------------------

    pr = make_purchase_receipt(po_name)

    pr.posting_date = nowdate()
    pr.set_posting_time = 1

    # PR will carry only taxes/charges mapped from PO.
    pr.calculate_taxes_and_totals()
    pr.insert(ignore_permissions=True)

    # --------------------------------------------------
    # Add valuation source comment only
    # --------------------------------------------------

    comment_lines = []
    comment_lines.append("<b>Valuation Source Reference</b><br>")

    # Customs GL Payments
    gl_payments = frappe.get_all(
        "GL Payment",
        filters={
            "purchase_order": po.name,
            "is_customs_payment": 1,
            "docstatus": 1
        },
        fields=["name"]
    )

    comment_lines.append("<br><b>Customs GL Payments:</b><br>")

    if gl_payments:
        for gl in gl_payments:
            link = f"/desk#Form/GL%20Payment/{gl.name}"
            comment_lines.append(
                f'- <a href="{link}" target="_blank">{gl.name}</a>'
            )
    else:
        comment_lines.append("- No submitted Customs GL Payment found.")

    # Arrival Payment Entries
    arrival_entries = []

    pe_list = frappe.get_all(
        "Payment Entry",
        filters={
            "is_arrival_payment": 1,
            "docstatus": 1,
            "party_type": "Supplier"
        },
        fields=["name"]
    )

    for pe in pe_list:
        pe_doc = frappe.get_doc("Payment Entry", pe.name)

        for ref in pe_doc.references:
            if ref.reference_doctype == "Purchase Invoice":

                linked_po = frappe.db.get_value(
                    "Purchase Invoice",
                    ref.reference_name,
                    "reference_purchase_order"
                )

                if linked_po == po.name:
                    arrival_entries.append(pe_doc.name)
                    break

    comment_lines.append("<br><b>Arrival Payment Entries:</b><br>")

    if arrival_entries:
        for pe_name in arrival_entries:
            link = f"/desk#Form/Payment%20Entry/{pe_name}"
            comment_lines.append(
                f'- <a href="{link}" target="_blank">{pe_name}</a>'
            )
    else:
        comment_lines.append("- No submitted Arrival Payment Entry found.")

    pr.add_comment("Comment", "<br>".join(comment_lines))

    pr.workflow_state = "Pending Receipt"
    pr.save(ignore_permissions=True)


    # --------------------------------------------------
    # 2️⃣ CREATE MAIN PURCHASE INVOICE (Draft)
    # --------------------------------------------------

    pi = make_purchase_invoice(po_name)

    pi.posting_date = po.transaction_date or nowdate()
    pi.set_posting_time = 1
    pi.update_stock = 0
    # Reload payment schedule using current invoice date (comment below if not needed)
    pi.set("payment_schedule", [])
    if pi.payment_terms_template:
        pi.set_payment_schedule()

    pi.insert(ignore_permissions=True)
    pi.submit()
    pi.db_set({
        "workflow_state": "Completed",
        "workflow": "Completed"
    })

    frappe.msgprint(
        "Purchase Receipt " + pr.name +
        " and Purchase Invoice " + pi.name +
        " created."
    )

    return {
        "purchase_receipt": pr.name,
        "purchase_invoice": pi.name
    }



#To cange the workflow state based on the ETA date entered in the popup
@frappe.whitelist()
def update_eta_and_validate_arrival(po_name, eta_date=None, fields_to_update=None):

    import json
    from frappe.utils import getdate, nowdate

    po = frappe.get_doc("Purchase Order", po_name)

    # -------------------------------------
    # Convert JSON string → dict
    # -------------------------------------
    if fields_to_update and isinstance(fields_to_update, str):
        fields_to_update = json.loads(fields_to_update)

    # -------------------------------------
    # Update popup fields
    # -------------------------------------
    if fields_to_update:
        for field, value in fields_to_update.items():
            po.db_set(field, value)

    # -------------------------------------
    # ETA Logic
    # -------------------------------------
    if eta_date:

        eta_date = getdate(eta_date)
        today = getdate(nowdate())

        days_diff = (eta_date - today).days

        po.db_set("eta_date", eta_date)

        if days_diff > 7:

            po.db_set("workflow_state", "Shipped")

            return {
                "status": "reverted",
                "message": "ETA is more than 7 days away. PO moved back to Shipped state."
            }

    return {"status": "ok"}
