"""Read-only Journal Entry cash commitments and explicit-reference reservations."""
from collections import defaultdict
from datetime import timedelta

import frappe

from .engine import money, as_date
from .rules import journal_effect, journal_reference_allocations
from .vat import settlement_amount, referenced_quarter


class Journals(object):
    def __init__(self, source):
        self.source = source
        self.loaded = False
        self.entries = []
        self.references = defaultdict(list)
        self.reserved = defaultdict(lambda: money(0))
        self.used_references = defaultdict(lambda: money(0))
        self.stats = dict(pending_outgoing=0, internal_or_noncash=0, pending_incoming=0,
                          excluded_draft=0, security_review=0, posted_future=0)
        self._accounts = {}
        self._payable_used = defaultdict(lambda:money(0))

    def workflow_states(self):
        workflows = frappe.get_all('Workflow', filters={'document_type': 'Journal Entry', 'is_active': 1}, fields=['name'])
        if len(workflows) != 1:
            self.source.warn('Journal Entry has no single active workflow; pending JEs need manual review.')
            return set()
        workflow = frappe.get_doc('Workflow', workflows[0].name)
        return {row.state for row in workflow.states if str(row.doc_status) == '0'
                and (row.state.startswith('Pending ') or row.state == 'Cheque Signed')
                and 'Security' not in row.state and 'Replace' not in row.state}

    def account_info(self, account):
        if account not in self._accounts:
            self._accounts[account] = frappe.db.get_value('Account', account,
                ['account_name', 'account_type', 'root_type'], as_dict=1) or frappe._dict()
        return self._accounts[account]

    def load(self):
        if self.loaded:
            return
        self.loaded = True
        s = self.source
        pending = list(s.documents('Journal Entry', {'docstatus': 0}))
        posted = list(s.documents('Journal Entry', {'docstatus': 1,
            'posting_date': ['between', [s.start+timedelta(days=1), s.end]]}))
        states = self.workflow_states() if pending else set()
        pool = set(getattr(s, 'accounts', []))
        fields = ('account', 'debit', 'credit', 'party_type', 'party', 'reference_type', 'reference_name')
        for doc in sorted(pending+posted, key=lambda d: (as_date(d.posting_date), d.name)):
            is_pending = doc.docstatus == 0
            if not is_pending and not (s.start < as_date(doc.posting_date) <= s.end):
                continue
            rows = [{key: r.get(key) for key in fields} for r in doc.accounts]
            cash = journal_effect(rows, pool)
            if is_pending:
                if doc.get('transaction_type') == 'Security Cheque' or 'Security' in (doc.get('workflow_state') or ''):
                    self.stats['security_review'] += 1
                    if cash:
                        s.warn('{0}: security cheque is not assumed to be an authorized payment; verify separately.'.format(doc.name))
                    continue
                if doc.get('workflow_state') not in states:
                    self.stats['excluded_draft'] += 1
                    continue
                if not cash:
                    self.stats['internal_or_noncash'] += 1
                    continue
                if cash < 0:
                    self.stats['pending_incoming'] += 1
                    s.warn('{0}: pending incoming JE is not added to invoice-based receipts; verify collection separately.'.format(doc.name))
                    continue
                self.stats['pending_outgoing'] += 1
            else:
                if not cash:
                    self.stats['internal_or_noncash'] += 1
                    continue
                self.stats['posted_future'] += 1
            refs, ambiguous = journal_reference_allocations(rows, pool) if is_pending else ({}, False)
            counterparts = [r for r in rows if r['account'] not in pool and money(r.get('debit')) > money(r.get('credit'))]
            names = [self.account_info(r['account']).get('account_name') or r['account'] for r in counterparts]
            payroll = any(r.get('reference_type') == 'Payroll Entry' for r in counterparts) or any(
                r['account'] == getattr(s, 'payroll_account', None) or any(w in (self.account_info(r['account']).get('account_name') or r['account']).lower()
                for w in ('salary', 'payroll')) for r in counterparts)
            supplier = any(r.get('party_type') == 'Supplier' or r.get('reference_type') in ('Purchase Invoice', 'Purchase Order')
                           for r in counterparts)
            tax = bool(settlement_amount(rows, pool, {'Output VAT – Sales - WS', 'Input VAT – Local - WS', 'Input VAT – Import - WS'}, 'Output VAT – Sales - WS'))
            if tax: refs = {}
            kind = 'vat_settlement' if tax else ('payroll' if payroll else ('supplier_payments' if supplier else 'other_payments'))
            notes = []
            if tax and not referenced_quarter(' '.join(str(doc.get(k) or '') for k in ('user_remark','remark','remarks'))):
                notes.append('VAT quarter missing; payment is allocated to the oldest unpaid quarter. Verify the allocation.')
            if ambiguous:
                notes.append('Offsetting journal lines prevent safe obligation matching; verify allocations.')
            if is_pending and money(sum(money(r.get('debit'))-money(r.get('credit')) for r in rows)):
                notes.append('Journal is unbalanced; verify the accounting lines before payment.')
            if payroll and not any(r.get('reference_type') == 'Payroll Entry' and r.get('reference_name') for r in counterparts):
                notes.append('Payroll Entry / salary-period link missing; verify against salary estimates and final settlements. No period inferred from remarks.')
            if supplier and not refs:
                notes.append('Supplier invoice/PO reference missing or ambiguous; verify overlap with outstanding supplier obligations.')
            if is_pending and doc.get('transaction_type') == 'Cheque':
                notes.append('Cheque payment uses posting date provisionally; verify expected clearance/payment date.')
            related = [dict(doctype=r['reference_type'], name=r['reference_name']) for r in counterparts
                       if r.get('reference_type') and r.get('reference_name')]
            info = dict(related=related, doc=doc, rows=rows, cash=cash, pending=is_pending, refs=refs, category=kind,
                        counterparts=[r['account'] for r in counterparts], notes=notes,
                        description='Net cash movement; {0}; counterpart: {1}'.format(doc.get('workflow_state') or '', ', '.join(names)))
            self.entries.append(info)
            s.register_source('Journal Entry', doc.name, workflow_state=doc.get('workflow_state') or '',
                review_note=' '.join(notes), related_documents=related, basis='Prepared Journal Entry; net effect on bank/cash pool')
            for reference, amount in refs.items():
                self.references[reference].append((info, amount))

    def reserve(self, doctype, name, amount):
        """Replace an explicit unpaid obligation, independently of event display mode."""
        remaining = max(money(amount), money(0))
        if not remaining:
            return money(0)
        self.load()
        total = money(0)
        for info, allocation in self.references.get((doctype, name), []):
            doc = info['doc']
            key = (doc.name, doctype, name)
            available = min(max(allocation-self.used_references[key], money(0)), max(info['cash']-self.reserved[doc.name], money(0)))
            used = min(available, remaining)
            if used:
                self.reserved[doc.name] += used
                if doctype=='Payroll Entry':self._payable_used[doc.name]+=used
                self.used_references[key] += used
                remaining -= used
                total += used
                self.source.event(self.source.due(doc.posting_date, doc.name),
                    'payroll' if doctype == 'Payroll Entry' else 'supplier_payments', used,
                    'Journal Entry', doc.name, 'Explicit {0} payment replaces source forecast: {1}'.format(doctype, name),
                    related_doctype=doctype, related_name=name)
            if available > used:
                note = '{0} is already covered or only partly outstanding; verify competing prepared payments.'.format(name)
                if note not in info['notes']:
                    info['notes'].append(note)
        return total

    def reserve_payable(self,account,amount,not_before=None,not_after=None,description=None):
        """A scheduled payable debit replaces pooled recorded liability, capped by cash."""
        self.load();remaining=max(money(amount),money(0));total=money(0)
        if not hasattr(self,'_payable_used'):self._payable_used=defaultdict(lambda:money(0))
        for info in self.entries:
            if info['cash']<=0:continue
            doc=info['doc']
            if not_before and as_date(doc.posting_date)<as_date(not_before):continue
            if not_after and as_date(doc.posting_date)>as_date(not_after):continue
            if not_before and any(row.get('reference_type')=='Payroll Entry' and row.get('reference_name') for row in info['rows']):continue
            debit=max(sum((money(row.get('debit'))-money(row.get('credit')) for row in info['rows'] if row['account']==account),money(0)),money(0))
            available=min(max(debit-self._payable_used[doc.name],money(0)),max(info['cash']-self.reserved[doc.name],money(0)))
            used=min(available,remaining)
            if not used:continue
            self._payable_used[doc.name]+=used;self.reserved[doc.name]+=used;total+=used;remaining-=used
            self.source.event(self.source.due(doc.posting_date,doc.name),'payroll',used,'Journal Entry',doc.name,
                description or 'Scheduled payment replaces recorded Payroll Payable balance',related_doctype='Account',related_name=account)
            if not remaining:break
        return total

    def reserve_future_payroll(self,batch,amount):
        self.load();remaining=max(money(amount),money(0));total=money(0)
        for info in self.entries:
            if info['pending'] or info['cash']<=0:continue
            doc=info['doc']
            linked=max(sum((money(row.get('debit'))-money(row.get('credit')) for row in info['rows']
                if row.get('reference_type')=='Payroll Entry' and row.get('reference_name')==batch),money(0)),money(0))
            reference_key=(doc.name,'Payroll Entry',batch)
            used=min(remaining,max(linked-self.used_references[reference_key],money(0)),max(info['cash']-self.reserved[doc.name],money(0)))
            if not used:continue
            self.reserved[doc.name]+=used;self.used_references[reference_key]+=used;self._payable_used[doc.name]+=used;remaining-=used;total+=used
            self.source.event(self.source.due(doc.posting_date,doc.name),'payroll',used,'Journal Entry',doc.name,
                'Submitted future payment replaces Salary Slip forecast',related_doctype='Payroll Entry',related_name=batch)
            if not remaining:break
        return total

    def emit(self):
        self.load()
        s = self.source
        for info in self.entries:
            doc = info['doc']
            fixed = getattr(s, '_fixed_expense_accounts', {})
            if info['pending'] and any(account in fixed for account in info['counterparts']):
                info['notes'].append('Possible fixed-expense schedule overlap; JE has no explicit Fixed Expense link. Verify existing payment matching.')
                for account in info['counterparts']:
                    for name in fixed.get(account, []):
                        info['related'].append(dict(doctype='Fixed Expense', name=name))
            if info['pending'] and sum(info['refs'].values(), money(0)) > self.reserved[doc.name]:
                info['notes'].append('Some referenced amounts were not matched to an outstanding obligation; verify already-paid items, competing prepared payments or missing source access.')
            note = ' '.join(dict.fromkeys(info['notes']))
            if note and (as_date(doc.posting_date) <= s.end):
                s.warn('{0}: {1}'.format(doc.name, note))
            s.register_source('Journal Entry', doc.name, workflow_state=doc.get('workflow_state') or '', review_note=note, related_documents=info['related'],
                              basis='Prepared Journal Entry; net effect on bank/cash pool' if info['pending'] else 'Submitted future Journal Entry')
            # Reservations were emitted before every matching obligation was known.
            # Refresh their review notes after processing all sources.
            for row in s.events + getattr(s, 'overdue', []):
                if row.get('doctype') == 'Journal Entry' and row.get('name') == doc.name:
                    row['review_note'] = note
                    row['related_documents'] = info['related']
            cash = info['cash']
            remaining = cash-self.reserved[doc.name] if cash > 0 else cash
            s.event(s.due(doc.posting_date, doc.name), info['category'] if remaining >= 0 else 'other_receipts',
                abs(remaining), 'Journal Entry', doc.name, info['description'] + ('; '+note if note else ''),
                vat_quarter=str(referenced_quarter(' '.join(str(doc.get(k) or '') for k in ('user_remark','remark','remarks'))))
                    if info['category']=='vat_settlement' and referenced_quarter(' '.join(str(doc.get(k) or '') for k in ('user_remark','remark','remarks'))) else None)
            if info['pending'] and info['category'] != 'vat_settlement':
                credit = sum((money(r.get('debit'))-money(r.get('credit')) for r in info['rows']
                    if r['account'] in ('Input VAT – Local - WS', 'Input VAT – Import - WS')), money(0))
                s.event(s.due(doc.posting_date, doc.name), 'vat_accrual', -credit,
                        'Journal Entry', doc.name, 'Projected input VAT from pending journal tax lines')
        s.journal_stats = dict(self.stats)
