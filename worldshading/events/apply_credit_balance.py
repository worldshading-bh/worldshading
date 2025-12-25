import frappe
from frappe.utils import flt

MOP = "Credit Note Balance"          # your Mode of Payment
CLEARING_ACCOUNT_NAME = "Credit Note - WS"  # the exact account you used
BRANCH_FIELD = "pb_branch"           # your custom branch field on PE (optional)

def _get_account(acc_name, company):
    acc = frappe.db.get_value("Account", {"name": acc_name, "company": company, "is_group": 0}, "name")
    if not acc:
        frappe.throw(f"Account '{acc_name}' not found for company {company}. Please create/select it.")
    return acc

def _make_pe(payload):
    pe = frappe.get_doc(payload)
    pe.insert(ignore_permissions=True)
    pe.submit()
    return pe

def apply_credit_simple(doc, method=None):
    # Run only for submitted, non-return SIs when explicitly requested
    if doc.doctype != "Sales Invoice" or doc.docstatus != 1 or doc.is_return:
        return
    if not doc.get("use_credit_balance") or not doc.get("credit_note_to_apply"):
        return

    # prevent re-entry while this function updates related docs
    if getattr(doc, "_in_credit_apply", False):
        return
    doc._in_credit_apply = True

    # Load the selected credit note (minimal checks as requested)
    try:
        cn = frappe.get_doc("Sales Invoice", doc.get("credit_note_to_apply"))
    except Exception:
        frappe.msgprint("Could not load the selected credit note.")
        doc._in_credit_apply = False
        return

    # Amount to carry: min( credit available on CN, this invoice outstanding )
    credit_available = abs(flt(cn.get("outstanding_amount") or 0))  # CN outstanding is negative -> credit
    invoice_outstanding = flt(doc.get("outstanding_amount") or 0)
    if credit_available <= 0 or invoice_outstanding <= 0:
        doc._in_credit_apply = False
        return

    amount_to_use = min(credit_available, invoice_outstanding)

    # Accounts exactly like your manual PEs
    debtors = doc.get("debit_to") or frappe.db.get_value("Company", doc.company, "default_receivable_account")
    clearing = _get_account(CLEARING_ACCOUNT_NAME, doc.company)

    # Optional: copy branch if your PE has pb_branch
    pb_branch = None
    try:
        if BRANCH_FIELD in [f.fieldname for f in frappe.get_meta("Payment Entry").fields]:
            pb_branch = doc.get(BRANCH_FIELD)
    except Exception:
        pass

    # --- PE #1: PAY (from Credit Note -> to Debtors), allocate NEGATIVE to the credit note
    pe1_payload = {
        "doctype": "Payment Entry",
        "payment_type": "Pay",
        "company": doc.company,
        "party_type": "Customer",
        "party": doc.customer,
        "posting_date": doc.posting_date,
        "mode_of_payment": MOP,
        "paid_from": clearing,   # Credit Note - WS
        "paid_to": debtors,      # Debtors - WS
        "paid_amount": amount_to_use,
        "received_amount": amount_to_use,
        "references": [{
            "reference_doctype": "Sales Invoice",
            "reference_name": cn.name,
            # match your JSON: negative allocation on the CN PE
            "allocated_amount": -amount_to_use
        }]
    }
    if pb_branch:
        pe1_payload[BRANCH_FIELD] = pb_branch
    pe1 = _make_pe(pe1_payload)

    # --- PE #2: RECEIVE (from Debtors -> to Credit Note), allocate POSITIVE to THIS invoice
    pe2_payload = {
        "doctype": "Payment Entry",
        "payment_type": "Receive",
        "company": doc.company,
        "party_type": "Customer",
        "party": doc.customer,
        "posting_date": doc.posting_date,
        "mode_of_payment": MOP,
        "paid_from": debtors,    # Debtors - WS
        "paid_to": clearing,     # Credit Note - WS
        "paid_amount": amount_to_use,
        "received_amount": amount_to_use,
        "references": [{
            "reference_doctype": "Sales Invoice",
            "reference_name": doc.name,
            "allocated_amount": amount_to_use
        }]
    }
    if pb_branch:
        pe2_payload[BRANCH_FIELD] = pb_branch
    pe2 = _make_pe(pe2_payload)

    # Reset the switch and log
    try:
        doc.db_set("use_credit_balance", 0, update_modified=False)
    except Exception:
        pass

    log = f"Applied {frappe.format_value(amount_to_use, {'fieldtype':'Currency','options': doc.currency})} " \
          f"from credit note {cn.name} via {pe1.name} and allocated to this invoice via {pe2.name}."
    doc.add_comment("Comment", log)
    frappe.msgprint(log)

    doc._in_credit_apply = False
