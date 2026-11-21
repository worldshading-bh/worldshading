"""Read-only approved bank-loan schedules, reconciled to native JV allocations."""
import json
import frappe

from .engine import money, as_date
from .rules import journal_effect
from worldshading.worldshading.doctype.bank_loan.payment_rules import COMPONENTS, allocation_totals, payment_status


class BankLoans(object):
    def __init__(self, source):
        self.source = source
        self.installments = {}

    def collect(self):
        s = self.source
        if getattr(s, '_bank_loans_loaded', False):
            return
        s._bank_loans_loaded = True
        s.bank_loan_names, s.bank_loan_payment_names, s.bank_loan_journal_names = [], [], []
        if not frappe.db.exists('DocType', 'Bank Loan'):
            s.warn('Bank Loan source is not installed; loan forecast coverage is incomplete.')
            return
        if not frappe.db.exists('DocType', 'Bank Loan Payment') or any(
                not frappe.has_permission(kind, 'read') for kind in ('Bank Loan', 'Bank Loan Payment', 'Journal Entry')):
            s.warn('Bank Loan/payment/JV read access or source is missing; loan forecast coverage is incomplete.')
            return
        loans = {doc.name: doc for doc in s.documents('Bank Loan')}
        if not loans:
            return
        s.bank_loan_names = sorted(loans)
        # One permission-filtered batch, not a query for every installment/day.
        records = frappe.get_list('Bank Loan Payment', filters={'bank_loan': ['in', list(loans)]},
            fields=['name', 'bank_loan', 'journal_entry', 'before_tracking', 'allocations'], limit_page_length=0)
        journals = s.journals()
        eligible = None
        payments = {name: [] for name in loans}
        seen = set()
        for record in records:
            if record.bank_loan not in loans or record.journal_entry in seen:
                s.warn('Duplicate or invalid Bank Loan Payment link; review loan repayment matching.')
                continue
            seen.add(record.journal_entry)
            s.bank_loan_payment_names.append(record.name)
            doc = s.read_document('Journal Entry', record.journal_entry)
            s.bank_loan_journal_names.append(doc.name)
            if doc.company != s.company or doc.get('custom_bank_loan') != record.bank_loan:
                s.warn('{0}: bank loan/JV company or link mismatch; payment is not matched.'.format(doc.name))
                continue
            if doc.docstatus == 2:
                continue
            try:
                allocations = json.loads(record.allocations) if isinstance(record.allocations, str) else record.allocations
                totals = allocation_totals(allocations, 3)
            except (ValueError, TypeError, KeyError):
                s.warn('{0}: invalid loan installment allocations; review before forecasting.'.format(doc.name))
                continue
            payments[record.bank_loan].append(dict(doc=doc, allocations=allocations, totals=totals,
                before_tracking=bool(record.before_tracking)))
        for name, doc in loans.items():
            raw = doc.get('approved_plan')
            if not raw and doc.currency != s.currency:
                s.warn('{0}: bank loan currency differs from company currency; schedule conversion is not supported.'.format(name))
                continue
            if raw:
                try:
                    plan = json.loads(raw)
                except (TypeError, ValueError):
                    s.warn('{0}: approved loan plan cannot be read; schedule omitted.'.format(name))
                    continue
            elif doc.get('workflow_state') == 'Approved':
                plan = dict(company=doc.company, currency=doc.currency, opening_principal=doc.get('opening_principal'),
                    schedule=doc.get('schedule') or [])
            else:
                plan = None
            if plan and (plan.get('company') != s.company or plan.get('currency') != s.currency):
                s.warn('{0}: approved loan company/currency mismatch; schedule omitted.'.format(name))
                continue
            schedule = plan.get('schedule', []) if plan else []
            self.installments.update({(name,row['name']):(index,row['due_date']) for index,row in enumerate(schedule,1)})
            posted = [dict(docstatus=1, allocations=p['allocations'], before_tracking=p['before_tracking'])
                for p in payments[name] if p['doc'].docstatus == 1 and as_date(p['doc'].posting_date) <= s.start]
            position = payment_status(schedule, posted, (plan or {}).get('opening_principal') or 0, 3)
            balances = {row['name']: dict(row['balances']) for row in position['installments']}
            if position['needs_reschedule']:
                s.warn('{0}: posted repayment exceeds a scheduled component; review the approved loan schedule.'.format(name))
            for payment in sorted(payments[name], key=lambda p: (as_date(p['doc'].posting_date), p['doc'].name)):
                journal = payment['doc']
                if journal.docstatus == 1 and as_date(journal.posting_date) <= s.start:
                    continue  # Already in opening cash; only its installment allocation reduces debt.
                if eligible is None:
                    journals.load()
                    eligible = {info['doc'].name: info for info in journals.entries}
                info = eligible.get(journal.name)
                # Also honor a submitted future payment beyond this report's end:
                # it moves its allocated obligation out of the window, not to overdue.
                future_posted = journal.docstatus == 1 and as_date(journal.posting_date) > s.end
                if not info and not future_posted:
                    continue
                cash = journal_effect(journal.accounts, getattr(s, 'liquidity_accounts', None) or s.accounts)
                available = info['cash']-journals.reserved[journal.name] if info else cash
                if cash <= 0 or cash != payment['totals']['cash'] or available != cash:
                    s.warn('{0}: loan allocation does not match available JV cash; original JV remains for review.'.format(journal.name))
                    continue
                if info:
                    journals.reserved[journal.name] += cash
                    reference = dict(doctype='Bank Loan', name=name)
                    if reference not in info['related']:
                        info['related'].append(reference)
                for allocation in payment['allocations']:
                    values = {key: money(allocation.get(key)) for key in COMPONENTS}
                    installment = allocation.get('installment')
                    if not payment['before_tracking']:
                        target = balances.get(installment)
                        if target is not None:
                            if any(values[key] > target[key] for key in COMPONENTS):
                                s.warn('{0}: planned repayment exceeds an unpaid component; review loan {1}.'.format(journal.name, name))
                            for key in COMPONENTS:
                                target[key] = max(money(0), target[key]-values[key])
                        elif plan:
                            s.warn('{0}: allocated installment is absent from the approved plan.'.format(journal.name))
                    self.emit(doc, installment, journal.posting_date, values, 'Journal Entry', journal.name,
                        'Linked JV repayment', journal.get('workflow_state'))
            for installment in schedule:
                self.emit(doc, installment['name'], installment['due_date'], balances[installment['name']],
                    'Bank Loan', name, 'Unpaid approved loan installment', doc.get('workflow_state'))
            if doc.get('status') == 'Closed' and any(sum(values.values()) for values in balances.values()):
                s.warn('{0}: closed loan still has unpaid approved installments; closing does not record repayment.'.format(name))

    def emit(self, loan, installment, due, values, doctype, name, description, workflow):
        s = self.source
        total = sum(values.values(), money(0))
        if total <= 0:
            return
        position = self.installments.get((loan.name, installment))
        label = 'installment {0} due {1}'.format(*position) if position else 'historical repayment'
        s.event(s.due(due, name), 'bank_loan_repayments', total, doctype, name,
            '{0}: {1}; {2}'.format(description, loan.get('loan_name') or loan.name, label),
            related_doctype='Bank Loan' if doctype != 'Bank Loan' else None,
            related_name=loan.name if doctype != 'Bank Loan' else None,
            bank_loan=loan.name, installment=installment, workflow_state=workflow or '', **values)
