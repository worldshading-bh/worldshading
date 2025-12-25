import frappe
from frappe.utils import nowdate
from frappe.model.mapper import get_mapped_doc
from datetime import datetime, timedelta

# Predefined account maps
ACCOUNT_MAP_RETURN = {"Cheque Sales - WS": "Cheque Return - WS"}
ACCOUNT_MAP_DEPOSIT = {"Cheque Return - WS": "Cheque Return - WS"}

@frappe.whitelist()
def create_reverse_journal_entry(
    source_name,
    action=None,
    posting_date=None,
    deposit_posting_date=None,
    return_posting_date=None
):
    """
    Handles all cheque-related actions (1st / 2nd / 3rd):
      • Record Cheque Return (1st)
      • Record Cheque Return - 2nd / - 3rd
      • Approved Reconciliation (2nd / 3rd)
    Creates 1 or 2 Journal Entries accordingly.
    """

    try:
        source = frappe.get_doc("Journal Entry", source_name)
        if not source:
            frappe.throw("Source Journal Entry not found.")
        if source.docstatus == 2:
            frappe.throw("Cannot process a cancelled Journal Entry.")

        # --- Detect stage ---
        stage = "1st"
        state = (source.workflow_state or "").lower()
        if "2nd" in state:
            stage = "2nd"
        elif "3rd" in state:
            stage = "3rd"

        # --- Detect action ---
        action = (action or "").strip() or frappe.form_dict.get("action") or ""
        action_lower = action.lower()

        # --- Helper: create reversed JV (Sales→Return or Return→Sales) ---
        def make_reverse_jv(base_doc, is_return=True):
            """is_return=True -> Cheque Sales→Return; False -> Cheque Return→Sales"""
            try:
                new_jv = get_mapped_doc(
                    "Journal Entry",
                    base_doc.name,
                    {
                        "Journal Entry": {"doctype": "Journal Entry"},
                        "Journal Entry Account": {
                            "doctype": "Journal Entry Account",
                            "field_map": {
                                "debit": "credit",
                                "credit": "debit",
                                "debit_in_account_currency": "credit_in_account_currency",
                                "credit_in_account_currency": "debit_in_account_currency",
                                "account_currency": "account_currency",
                                "exchange_rate": "exchange_rate"
                            }
                        },
                    },
                )
            except frappe.ValidationError:
                # Fallback for Draft JVs
                new_jv = frappe.new_doc("Journal Entry")
                for f in [
                    "company", "transaction_type", "cheque_no", "cheque_date",
                    "letter_head", "customer", "customer_name",
                    "depositor", "depositor_name", "transition_date"
                ]:
                    new_jv.set(f, base_doc.get(f))

                for row in base_doc.accounts:
                    new_jv.append("accounts", {
                        "account": row.account,
                        "party_type": row.party_type,
                        "party": row.party,
                        "debit": float(row.credit or 0),
                        "credit": float(row.debit or 0),
                        "cost_center": row.cost_center,
                        "account_currency": row.account_currency,
                        "exchange_rate": row.exchange_rate or 1,
                        "is_advance": row.is_advance,
                        "project": row.project
                    })

            # --- Select correct posting date ---
            selected_date = (
                posting_date
                or (return_posting_date if is_return else deposit_posting_date)
                or base_doc.posting_date
                or nowdate()
            )
            new_jv.posting_date = selected_date
            new_jv.company = base_doc.company

            # --- Clean references ---
            for row in new_jv.accounts:
                row.reference_type = None
                row.reference_name = None

            # --- Account remap ---
            account_map = ACCOUNT_MAP_RETURN if is_return else ACCOUNT_MAP_DEPOSIT
            for row in new_jv.accounts:
                if row.account in account_map:
                    row.account = account_map[row.account]

            # --- Remarks ---
            kind = "Return" if is_return else "Deposit"
            new_jv.user_remark = f"{kind} JV auto-created from {base_doc.name} ({stage})"
            new_jv.remark = f"Auto {kind.lower()} JV from {base_doc.name} ({stage})"

            # =========================================================
            # ✅ Insert → Set workflow_state → Submit (correct order)
            # =========================================================
            new_jv.insert(ignore_permissions=True)  # create as Draft

            # Determine and set correct workflow state BEFORE submit
            new_state = f"Returned Cheque - {stage}" if is_return else "Completed"
            new_jv.db_set("workflow_state", new_state, update_modified=False)

            # Now safely submit so server scripts read correct state
            new_jv.submit()

            # --- Dynamic Title for each new JV ---
            kind_label = "Cheque Return" if is_return else "Cheque Deposit"
            title_text = f"{kind_label} JV - {stage} - {base_doc.name}"
            new_jv.db_set("title", title_text, update_modified=False)

            # --- Comments for both documents (compact & efficient) ---
            msg_new = f"🧾 {kind} JV <b>{new_jv.name}</b> auto-created from {base_doc.name} ({stage})"
            msg_src = f"🔁 {kind} JV Created : <b>{new_jv.name}</b> ({stage})"
            new_jv.add_comment("Workflow", msg_new)
            base_doc.add_comment("Workflow", msg_src)

            frappe.logger().info(f"{kind} JV created: {new_jv.name}, stage={stage}, from={base_doc.name}")
            return new_jv


        # =============================================================
        # 🔹 LOGIC MATRIX
        # =============================================================

        result_jv_name = None

        # -------------------------------------------------------------
        # 🔸 SECURITY CHEQUE → FINAL STAGE HANDLING
        # -------------------------------------------------------------
        if (source.transaction_type or "").lower() == "security cheque" and (source.workflow_state or "").lower() == "cheque reconciliation":
            # ① Approved Reconciliation → only PE (no JV)
            if action_lower == "approved reconciliation":
                pe_name = create_security_cheque_payment_entry(source, action)
                if pe_name:
                    frappe.msgprint(f"✅ Payment Entry <b>{pe_name}</b> created automatically for this Security Cheque.")
                    return pe_name
                else:
                    frappe.msgprint("⚠️ Failed to create Payment Entry for this Security Cheque. Check logs.")
                return

            # ② Record Cheque Return → normal JV + silent PE
            elif action_lower == "record cheque return":
                pe_name = create_security_cheque_payment_entry(source, action)
                frappe.logger().info(f"Silent PE created ({pe_name}) for Security Cheque Return {source.name}")
                # continue into JV logic below



        if "record cheque return" in action_lower and "2nd" not in action_lower and "3rd" not in action_lower:
            # 1st Return → only one Return JV
            main_title = "Cheque Deposit JV - Main"
            source.db_set("title", main_title, update_modified=False)
            return_jv = make_reverse_jv(source, is_return=True)
            result_jv_name = return_jv.name

            # Ensure Return JV appears above main JV
            future_time = (datetime.now() + timedelta(seconds=5)).strftime("%Y-%m-%d %H:%M:%S")
            frappe.db.set_value("Journal Entry", return_jv.name, "modified", future_time)

        #  SAFETY CHECK: Skip if this is first approval from main jv (no extra JV needed)
        elif action_lower == "approved reconciliation" and (source.workflow_state or "").lower() == "cheque reconciliation":
            return

        elif "approved reconciliation" in action_lower:
            # Approved Reconciliation (2nd/3rd) → only Deposit JV
            deposit_jv = make_reverse_jv(source, is_return=False)
            future_time = (datetime.now() + timedelta(seconds=5)).strftime("%Y-%m-%d %H:%M:%S")
            frappe.db.set_value("Journal Entry", deposit_jv.name, "modified", future_time)
            result_jv_name = deposit_jv.name


        elif "record cheque return - 2nd" in action_lower or "record cheque return - 3rd" in action_lower:
            # 2nd / 3rd Return → create Deposit JV first, then reverse that Deposit JV to make the Return
            deposit_jv = make_reverse_jv(source, is_return=False)
            return_jv = make_reverse_jv(deposit_jv, is_return=True)
            result_jv_name = return_jv.name
            # 💡 Adjust modified timestamps for correct order in list view
            deposit_time = (datetime.now() + timedelta(seconds=4)).strftime("%Y-%m-%d %H:%M:%S")
            return_time = (datetime.now() + timedelta(seconds=6)).strftime("%Y-%m-%d %H:%M:%S")

            frappe.db.set_value("Journal Entry", deposit_jv.name, "modified", deposit_time)
            frappe.db.set_value("Journal Entry", return_jv.name, "modified", return_time)

        else:
            frappe.throw(f"Unrecognized action: {action}")

        # ✅ Single commit for entire operation
        frappe.db.commit()
        return result_jv_name

    except Exception as e:
        frappe.log_error(
            f"Error processing cheque action for {source_name}\n{str(e)}",
            "Reverse/Deposit JV Creation Error"
        )
        frappe.throw(f"❌ Failed to create Journal Entry(s): {str(e)}")



# -----------------------------------------------------------------
# 🔹 Helper: Create Payment Entry for Security Cheques
# -----------------------------------------------------------------
def create_security_cheque_payment_entry(source, action):
    try:
        total_amount = sum([row.credit or 0 for row in source.accounts])
        if not total_amount:
            frappe.throw("Unable to determine cheque amount (no Credit found).")

        pe = frappe.new_doc("Payment Entry")
        pe.naming_series = "PE.YY.-"
        pe.payment_type = "Receive"
        pe.company = source.company
        pe.party_type = "Customer"
        pe.party = source.customer
        pe.party_name = source.customer_name
        pe.mode_of_payment = "Cheque"
        pe.pb_branch = "Hamad Town Showroom"
        pe.posting_date = source.posting_date or nowdate()
        pe.pb_posting_time = frappe.utils.nowtime()

        pe.paid_from = "Debtors - WS"
        pe.paid_to = "Cheque Sales - WS"
        pe.paid_from_account_currency = pe.paid_to_account_currency = "BHD"
        pe.paid_amount = pe.base_paid_amount = pe.received_amount = pe.base_received_amount = total_amount
        pe.source_exchange_rate = pe.target_exchange_rate = 1
        pe.unallocated_amount = total_amount

        pe.reference_no = source.cheque_no or f"Ref from {source.name}"
        pe.reference_date = source.cheque_date or nowdate()
        pe.remarks = f"Auto Payment Entry for Security Cheque {source.name} ({action})"
        pe.title = source.customer
        pe.letter_head = source.letter_head or "WS"

        pe.insert(ignore_permissions=True)
        pe.submit()

        pe.add_comment("Workflow", f"Auto Payment Entry <b>{pe.name}</b> from Security Cheque JV <b>{source.name}</b> ({action}).")
        source.add_comment("Workflow", f"💰 Payment Entry <b>{pe.name}</b> created and submitted for Security Cheque ({action}).")

        frappe.logger().info(f"Security Cheque PE created: {pe.name} ({action}) from {source.name}, stage={getattr(source, 'workflow_state', 'N/A')}")
        frappe.db.commit()
        return pe.name

    except Exception as e:
        frappe.log_error(f"Security Cheque PE creation failed for {source.name}\n{str(e)}",
                         "Security Cheque PE Error")
        return None