# -*- coding: utf-8 -*-
# Copyright (c) 2026, Hilal Habeeb and contributors
# For license information, please see license.txt

from __future__ import unicode_literals

import frappe
from frappe.model.document import Document
from frappe.utils import cint, flt, getdate

from worldshading.api.service_visit_commission import (
    MONTH_NAMES,
    _resolve_year,
    build_settlement_rows
)


class CommissionPayout(Document):

    def validate(self):
        self.total_amount = round(
            sum(flt(d.amount) for d in self.details), 3)

    def before_submit(self):
        if not self.details:
            frappe.throw("Nothing to pay - fetch the details first.")

        self._validate_duplicate_run()

    def before_cancel(self):
        # The payout is the commission ledger; its accounting entry must go first so the
        # books and the ledger can never disagree.
        if self.journal_entry and frappe.db.get_value(
                "Journal Entry", self.journal_entry, "docstatus") != 2:
            frappe.throw(
                "Journal Entry {0} is linked to this payout. "
                "Cancel or delete it first.".format(self.journal_entry))

    def _validate_duplicate_run(self):
        """Only one SUBMITTED payout per commission type per payout month (year-aware -
        payout_month is a month name, so the year comes from each doc's posting date)."""
        my_year = _payout_year(self)

        others = frappe.get_all(
            "Commission Payout",
            filters={
                "docstatus": 1,
                "commission_type": self.commission_type,
                "payout_month": self.payout_month,
                "name": ["!=", self.name]
            },
            fields=["name", "payout_month", "posting_date"]
        )

        for other in others:
            if _payout_year(other) == my_year:
                frappe.throw(
                    "{0} is already submitted for {1} {2} ({3}). "
                    "Cancel it first if this run should replace it.".format(
                        other.name, self.payout_month, my_year, self.commission_type))


def _payout_year(doc):
    posting = getdate(doc.get("posting_date"))
    payout_number = MONTH_NAMES.index(doc.get("payout_month")) + 1

    return _resolve_year(payout_number, posting.month, posting.year)


def unlink_journal_entry(doc, method=None):
    """Journal Entry on_trash / before_cancel hook.

    The payout's journal_entry link would otherwise block deleting or cancelling the
    entry (Frappe's generic link check fires right after these hooks). Releasing the
    link here means killing a wrong entry immediately frees the payout to create a
    corrected one - the Create Journal Entry button reappears.
    """
    for name in [d.name for d in frappe.get_all(
            "Commission Payout", filters={"journal_entry": doc.name})]:
        frappe.db.set_value("Commission Payout", name, "journal_entry", None,
                            update_modified=False)


@frappe.whitelist()
def get_payout_details(payout_month, posting_date, commission_type):
    """Rows for the Fetch Details button - computed by the settlement engine."""
    frappe.only_for(("System Manager", "Accounts Manager"))

    return build_settlement_rows(payout_month, posting_date, commission_type)


@frappe.whitelist()
def create_journal_entry(name, expense_account, payment_account,
                         entry_type="Journal Entry", submit_entry=0,
                         reference_no=None, reference_date=None):
    """Build the accounting entry for a submitted payout.

    Debit the commission expense with the run total; credit the payment account. When
    the credit account is a Payable (payroll-style accrual), one credit row is written
    per employee with the Employee as party so the liability clears per person;
    otherwise (bank/cash) a single credit row carries the total and the per-person
    detail stays on the payout document.
    """
    frappe.only_for(("System Manager", "Accounts Manager"))

    payout = frappe.get_doc("Commission Payout", name)

    if payout.docstatus != 1:
        frappe.throw("Submit the Commission Payout first.")

    if payout.journal_entry and frappe.db.get_value(
            "Journal Entry", payout.journal_entry, "docstatus") != 2:
        frappe.throw("Journal Entry {0} already exists for this payout.".format(
            payout.journal_entry))

    total = flt(payout.total_amount)

    if total <= 0:
        frappe.throw("Nothing to post - the payout total is zero.")

    entry = frappe.new_doc("Journal Entry")
    entry.voucher_type = entry_type
    entry.company = payout.company
    entry.posting_date = payout.posting_date

    if reference_no:
        entry.cheque_no = reference_no
        entry.cheque_date = reference_date or payout.posting_date

    remark_lines = ["Service Visit Commission - {0} ({1})".format(
        payout.payout_month, payout.name)]
    for row in payout.details:
        remark_lines.append("{0} / {1} / {2}: {3}".format(
            row.employee_name or row.employee, row.component or "",
            row.earned_month, flt(row.amount, 3)))
    entry.user_remark = "\n".join(remark_lines)

    entry.append("accounts", {
        "account": expense_account,
        "debit_in_account_currency": total
    })

    if frappe.db.get_value("Account", payment_account, "account_type") == "Payable":
        per_employee = {}
        for row in payout.details:
            per_employee[row.employee] = flt(per_employee.get(row.employee)) + flt(row.amount)

        for employee, amount in per_employee.items():
            entry.append("accounts", {
                "account": payment_account,
                "party_type": "Employee",
                "party": employee,
                "credit_in_account_currency": round(amount, 3)
            })
    else:
        entry.append("accounts", {
            "account": payment_account,
            "credit_in_account_currency": total
        })

    entry.insert(ignore_permissions=True)

    if cint(submit_entry):
        entry.submit()

    payout.db_set("journal_entry", entry.name, update_modified=False)

    return entry.name
