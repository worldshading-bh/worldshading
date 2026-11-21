# -*- coding: utf-8 -*-
"""Company borrowings, approved schedules and native-JV payment tracking."""
import hashlib
import json
import frappe
from frappe import _
from frappe.model.document import Document
from worldshading.api.bank_loan_workflow import validate_loan_workflow
from .rules import calculate_schedule


def agreement_identity(company, bank, agreement):
    agreement = ' '.join((agreement or '').split()).upper()
    if not company or not bank or not agreement:
        frappe.throw(_('Company, Bank and Agreement Number are required.'))
    value = json.dumps([company, bank, agreement], ensure_ascii=False)
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


class BankLoan(Document):
    def validate(self):
        old = self.get_doc_before_save()
        tracking = self.get('doctype') == 'Bank Loan' and self.meta.has_field('approved_plan')
        if tracking and old:
            from worldshading.api.bank_loan_payments import _source
            old = _source(self.name)
            if self.get('_original_modified') and str(self.get('_original_modified')) != str(old.modified):
                frappe.throw(_('This Bank Loan changed. Reload it before saving.'),frappe.TimestampMismatchError)
        validate_loan_workflow(self, old)
        # Fail closed if setup has not installed the native transition/role gate.
        if self.get('workflow_state') not in (None, '', 'Draft'):
            if not frappe.db.exists('Workflow', {'document_type': 'Bank Loan', 'is_active': 1}):
                frappe.throw(_('Install Bank Loan Approval before requesting approval.'))
        self.agreement_number = ' '.join((self.agreement_number or '').split())
        self.loan_identity = agreement_identity(self.company, self.bank, self.agreement_number)
        duplicate = frappe.db.get_value('Bank Loan', {'loan_identity': self.loan_identity,
                                                    'name': ['!=', self.name or '']}, 'name')
        if duplicate:
            frappe.throw(_('This company and bank already have Agreement Number {0}: {1}').format(
                self.agreement_number, duplicate))
        self.validate_accounts()
        # Frappe's field precision respects the site's currency precision settings.
        precision = self.precision('original_principal')
        try:
            result = calculate_schedule(self.as_dict(), precision,
                                        complete=self.workflow_state in ('Pending Loan - Chkr', 'Pending Loan - App', 'Approved'))
        except ValueError as error:
            frappe.throw(_(str(error)))
        for row, values in zip(self.schedule, result.pop('rows')):
            row.currency = self.currency
            for field, value in values.items():
                row.set(field, float(value) if field != 'installment_number' else value)
        for field, value in result.items():
            self.set(field, float(value) if value is not None and not isinstance(value, str) else value)
        if tracking:
            from worldshading.api.bank_loan_payments import payment_documents
            from worldshading.api.bank_loan_revisions import validate_revision
            history=payment_documents(self.name,for_update=True) if old else []
            validate_revision(self,old,history)

    def on_trash(self):
        from worldshading.api.bank_loan_payments import payment_documents, _source
        _source(self.name)
        if payment_documents(self.name,for_update=True):
            frappe.throw(_('This Bank Loan has linked JV history and cannot be deleted.'))

    def validate_accounts(self):
        for field, root in [('loan_account', 'Liability'), ('interest_account', 'Expense'),
                            ('charges_account', 'Expense'), ('payment_account', 'Asset')]:
            name = self.get(field)
            if not name and field == 'charges_account':
                if any(row.get('charges_amount') for row in self.get('schedule') or []):
                    frappe.throw(_('Select a Charges Account when the schedule includes charges.'))
                continue
            account = frappe.db.get_value('Account', name,
                ['company', 'root_type', 'account_currency', 'account_type', 'disabled', 'is_group'], as_dict=True) if name else None
            if (not account or account.company != self.company or account.root_type != root
                    or account.account_currency != self.currency or account.disabled or account.is_group
                    or (field == 'payment_account' and account.account_type != 'Bank')):
                frappe.throw(_('Select an enabled, non-group {0} account in the loan company and currency for {1}.').format(root, field.replace('_', ' ').title()))
        center = frappe.db.get_value('Cost Center', self.cost_center, ['company', 'is_group'], as_dict=True)
        if not center or center.company != self.company or center.is_group:
            frappe.throw(_('Select a non-group Cost Center belonging to the loan Company.'))
