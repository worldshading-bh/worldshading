"""Loan-side payment instructions; the linked native JV owns accounting and status."""
import frappe
from frappe import _
from frappe.model.document import Document


class BankLoanPayment(Document):
    def validate(self):
        if not self.flags.get('from_bank_loan_service'):
            frappe.throw(_('Manage payment breakdowns from the Bank Loan.'))

    def on_trash(self):
        if not self.flags.get('from_bank_loan_service'):
            frappe.throw(_('Keep loan payment records with their linked Journal Entry.'))
