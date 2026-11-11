"""Read-only adapters. Every query is company scoped; document reads honor permissions."""
from calendar import monthrange
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

import frappe
from frappe.utils import getdate

from .engine import money, as_date, days, occurrences, FREQUENCIES, reconcile_installments, PAYMENTS, import_cash_taxes
from .rules import supplier_amount, po_remaining, base_outstanding, salary_estimate, supplier_outstanding, arrival_residual, advance_shares, invoice_installments, reserve_installment

TAX_ACCOUNTS = {'output': 'Output VAT – Sales - WS', 'local': 'Input VAT – Local - WS',
                'import': 'Input VAT – Import - WS', 'customs': 'Custom Duty - WS'}


class Sources(object):
    def __init__(self, company, accounts, start, end, include_overdue=False):
        self.company, self.accounts = company, accounts
        self.start, self.end = as_date(start), as_date(end)
        self.currency = frappe.db.get_value('Company', company, 'default_currency')
        self.payroll_account = frappe.db.get_value('Company', company, 'default_payroll_payable_account')
        self.include_overdue = include_overdue
        self.events, self.warnings, self.accounts_breakdown, self.overdue = [], [], [], []
        self.historical, self.sales_tax = {}, {}
        self.handled_glp, self.handled_pe = set(), set()
        self.invoiced, self.applied_advances = defaultdict(Decimal), defaultdict(Decimal)
        self.import_credited = defaultdict(Decimal)
        self._names = {}

    def register_source(self, doctype, name, **values):
        if not hasattr(self, '_source_info'):
            self._source_info = {}
        self._source_info.setdefault((doctype, name), {}).update(values)

    def journals(self):
        if not hasattr(self, '_journals'):
            from .journals import Journals
            self._journals = Journals(self)
        return self._journals

    def warn(self, message):
        if message not in self.warnings:
            self.warnings.append(message)

    def names(self, doctype, filters=None):
        if not frappe.db.exists('DocType', doctype) or not frappe.has_permission(doctype, 'read'):
            self.warn('Missing read access/source: {0}; forecast coverage is incomplete.'.format(doctype))
            return []
        filters = dict(filters or {}, company=self.company)
        if doctype == 'Purchase Order' and filters.get('docstatus') == 1:
            records = frappe.get_list(doctype, filters=filters, fields=['name','base_grand_total','advance_paid',
                'currency','conversion_rate','eta_date','workflow_state'], limit_page_length=0)
            imported = defaultdict(Decimal)
            for row in frappe.db.sql("""select t.parent, t.base_tax_amount_after_discount_amount amount
                from `tabPurchase Taxes and Charges` t inner join `tabPurchase Order` p on p.name=t.parent
                where p.company=%s and p.docstatus=1 and t.parenttype='Purchase Order'
                and t.account_head=%s and t.category in ('Total','Valuation and Total')""",
                (self.company, TAX_ACCOUNTS['import']), as_dict=1):
                # Match invoice_import(): round each stored row before summing.
                imported[row.parent] += money(row.amount)
            return [r.name for r in records if self.purchase_order_relevant(r, imported.get(r.name, money(0)))]
        return [r.name for r in frappe.get_list(doctype, filters=filters, fields=['name'], limit_page_length=0)]

    def purchase_order_relevant(self, record, imported):
        if record.get('workflow_state') != 'Completed':
            return True
        if record.get('eta_date') and as_date(record.eta_date) >= self.start:
            return True
        remaining = po_remaining(supplier_amount(record.base_grand_total, imported),
            self.invoiced[record.name], self.conversion(record, record.advance_paid), self.applied_advances[record.name])
        return bool(remaining)

    def documents(self, doctype, filters=None):
        for name in self.names(doctype, filters):
            yield self.read_document(doctype, name)

    def read_document(self, doctype, name):
        if not hasattr(self, '_documents'):
            self._documents = {}
        key = (doctype, name)
        if key not in self._documents:
            self._documents[key] = frappe.get_doc(doctype, name)
        doc = self._documents[key]
        doc.check_permission('read')
        return doc

    def due(self, value, label):
        if not value:
            self.warn('{0}: no payment date; amount is not scheduled.'.format(label))
            return None
        due = as_date(value)
        # Keep original overdue dates until event reconciliation records the unpaid amount.
        return due if due <= self.end else None

    def event(self, due, category, amount, doctype=None, name=None, description='', **extra):
        if due is None or not amount:
            return
        due = as_date(due)
        amount = money(amount)
        details = dict(getattr(self, '_source_info', {}).get((doctype, name), {}))
        details.update(extra)
        if due < self.start:
            if category in PAYMENTS + ('vat_settlement',) and amount > 0:
                if not hasattr(self, 'overdue'):
                    self.overdue = []
                self.overdue.append(dict(date=due, category=category, amount=amount,
                    doctype=doctype, name=name, description=description, **details))
                details['original_due_date'] = due
                description += '; original due {0}'.format(due)
            if not self.include_overdue:
                return
            due = self.start
        if self.start <= due <= self.end:
            self.events.append(dict(date=due, category=category, amount=amount,
                doctype=doctype, name=name, description=description, **details))

    def collect(self):
        self.opening()
        if getattr(self, "manual_daily_sales", None) is None:
            self.historical_sales()
        else:
            self.manual_sales()
        self.tax_position()
        self.future_tax_events()
        self.collect_commitments()
        from .budgets import Budgets
        Budgets(self).collect()
        return self

    def collect_commitments(self):
        if not getattr(self, '_vat_loaded', False):
            self.tax_position()
            self.future_tax_events()
        self.supplier_invoices()
        self.purchase_orders()
        self.fixed_expenses()
        self.payroll()
        self.other_payments()
        self._vat_data.finalize()
        self.warn('Payroll estimates assume normal structure components and full attendance; variable overtime, unrecorded loans and employer costs need review.')
        return self

    def opening(self):
        # Single-account branches use v12's existing account index reliably. A broad
        # IN/GROUP BY can choose the company index and scan the whole company ledger.
        index = {}
        branch = """select account, coalesce(sum(debit-credit),0) balance from `tabGL Entry`
            where company=%s and account=%s and posting_date<=%s group by account"""
        for offset in range(0, len(self.accounts), 100):
            batch = self.accounts[offset:offset+100]
            parameters = tuple(value for account in batch for value in (self.company, account, self.start))
            balances = frappe.db.sql(' union all '.join([branch]*len(batch)), parameters, as_dict=1)
            index.update({row.account: money(row.balance) for row in balances})
        self.opening_balance = money(0)
        for account in self.accounts:
            balance = index.get(account, money(0))
            self.accounts_breakdown.append(dict(account=account, amount=balance))
            self.opening_balance += balance

    def forecast_holidays(self):
        """Use dated calendars automatically; uncovered dates remain working days."""
        calendars = frappe.get_list('Holiday List', filters={'from_date': ['<=', self.end],
            'to_date': ['>=', self.start]}, fields=['name'], order_by='from_date asc, name asc', limit_page_length=0)
        dates, names = set(), []
        for row in calendars:
            calendar = frappe.get_doc('Holiday List', row.name)
            calendar.check_permission('read')
            names.append(row.name)
            for holiday in calendar.holidays:
                day = as_date(holiday.holiday_date)
                if self.start <= day <= self.end and as_date(calendar.from_date) <= day <= as_date(calendar.to_date):
                    dates.add(str(day))
        self.holidays = sorted(dates)
        self.holiday_list = ', '.join(names)

    def manual_sales(self):
        """Gross daily sales; no previous-year invoice lookup in manual mode."""
        self.actual_sales_today = None
        if frappe.has_permission('Sales Invoice', 'read'):
            rows = frappe.get_list('Sales Invoice', filters={'company': self.company, 'docstatus': 1,
                'posting_date': self.start}, fields=['sum(base_grand_total) as amount'], limit_page_length=1)
            self.actual_sales_today = money(rows[0].amount) if rows else money(0)
        self.forecast_holidays()
        # Standard gross sales include the company's configured output VAT rate.
        templates = frappe.get_list('Sales Taxes and Charges Template', filters={'company': self.company, 'is_default': 1, 'disabled': 0},
            fields=['name'], limit_page_length=0)
        if len(templates)!=1:
            frappe.throw('Set one default Sales Taxes and Charges Template for manual daily sales.')
        template = frappe.get_doc('Sales Taxes and Charges Template', templates[0].name)
        template.check_permission('read')
        tax_rows = [row for row in template.taxes if row.account_head==TAX_ACCOUNTS['output']]
        if len(tax_rows)!=1 or tax_rows[0].charge_type!='On Net Total' or Decimal(str(tax_rows[0].rate or 0))<0:
            frappe.throw('Manual sales requires one On Net Total Output VAT row in the default sales tax template.')
        self.manual_vat_rate = Decimal(str(tax_rows[0].rate or 0))

    def historical_sales(self):
        # Sales are aggregated in base currency, including signed returns and VAT.
        self.actual_sales_today = None
        if not frappe.has_permission('Sales Invoice', 'read'):
            self.warn('Sales Invoice access missing; sales coverage is incomplete.')
            return
        try:
            first = self.start.replace(year=self.start.year-1)
        except ValueError:
            first = date(self.start.year-1, 2, 28)
        try:
            last = self.end.replace(year=self.end.year-1)
        except ValueError:
            last = date(self.end.year-1, 2, 28)
        last = min(last, self.start)
        records = frappe.get_list('Sales Invoice', filters={'company': self.company, 'docstatus': 1,
            'posting_date': ['between', [first, last]]},
            fields=['name', 'posting_date', 'base_grand_total'], limit_page_length=0)
        if last < self.start:
            records += frappe.get_list('Sales Invoice', filters={'company': self.company, 'docstatus': 1,
                'posting_date': self.start}, fields=['name', 'posting_date', 'base_grand_total'], limit_page_length=0)
        # Retain coverage-warning semantics without loading the entire history.
        earliest = frappe.get_list('Sales Invoice', filters={'company': self.company, 'docstatus': 1,
            'posting_date': ['between', [date(self.start.year-1, 1, 1), self.start]]},
            fields=['min(posting_date) as posting_date'], order_by='posting_date asc', limit_page_length=1)
        earliest = [r for r in earliest if r.posting_date]
        invoices = {r.name: r for r in records}
        self.actual_sales_today = money(0)
        if not invoices and not earliest:
            self.warn('No accessible submitted historical invoices; sales coverage is incomplete.')
            return
        totals, taxes, dates = defaultdict(Decimal), defaultdict(Decimal), set()
        for r in invoices.values():
            day = as_date(r.posting_date)
            if day > self.start:
                continue
            dates.add(day)
            totals[day] += money(r.base_grand_total)
        self.actual_sales_today = totals.get(self.start, money(0))
        tax_rows = frappe.db.sql('''select t.parent, t.base_tax_amount_after_discount_amount amount
            from `tabSales Taxes and Charges` t inner join `tabSales Invoice` s on s.name=t.parent
            where t.parenttype='Sales Invoice' and s.company=%s and s.docstatus=1
            and s.posting_date between %s and %s and t.account_head=%s''',
            (self.company, first, last, TAX_ACCOUNTS['output']), as_dict=1)
        for r in tax_rows:
            if r.parent in invoices:
                taxes[as_date(invoices[r.parent].posting_date)] += money(r.amount)
        for day in days(self.start, self.end):
            try:
                prior = day.replace(year=day.year-1)
            except ValueError:
                self.warn('29 February has no exact previous-year comparator; sales are zero for that day.')
                continue
            if prior > self.start:
                self.warn('Forecast extends beyond available prior-year history; unavailable comparator days are zero.')
            self.historical[str(day)] = totals.get(prior, money(0))
            self.sales_tax[str(day)] = taxes.get(prior, money(0))
        if earliest and as_date(earliest[0].posting_date) > date(self.start.year-1, self.start.month, min(self.start.day, monthrange(self.start.year-1, self.start.month)[1])):
            self.warn('Historical invoice coverage starts after the first required comparator date.')

    def tax_position(self):
        from .vat_sources import VatSources
        self._vat_data = VatSources(self)
        self._vat_data.load()
        self._vat_loaded = True

    def future_tax_events(self):
        if not getattr(self, '_vat_loaded', False): self.tax_position()
        if not getattr(self, '_vat_future_loaded', False):
            self._vat_data.future_events()
            self._vat_future_loaded = True

    def conversion(self, doc, value):
        return base_outstanding(value, doc.get('party_account_currency') or doc.get('currency') or self.currency,
                                self.currency, doc.get('conversion_rate') or 1)

    def invoice_import(self, doc):
        return sum((money(t.base_tax_amount_after_discount_amount)
                    for t in doc.get('taxes', []) if t.account_head == TAX_ACCOUNTS['import']
                    and t.category in ('Total', 'Valuation and Total')), money(0))

    def supplier_invoices(self):
        if not frappe.has_permission('Purchase Invoice', 'read'):
            self.warn('Purchase Invoice access missing; supplier and VAT coverage is incomplete.')
            return
        if self.names('Purchase Invoice', {'docstatus': 1, 'is_return': 1, 'outstanding_amount': ['!=', 0]}):
            self.warn('Unallocated supplier credit notes exist; reconcile them against invoices. Cash refunds are not assumed.')
        # Index all billed PO portions in bulk; load full documents only for unpaid invoices.
        records = frappe.get_list('Purchase Invoice', filters={'company': self.company, 'docstatus': 1, 'is_return': 0},
            fields=['name', 'base_grand_total', 'base_net_total', 'outstanding_amount',
                    'posting_date', 'party_account_currency', 'currency', 'conversion_rate'], limit_page_length=0)
        index = {r.name: r for r in records}
        invoice_import = defaultdict(Decimal)
        invoice_pos = defaultdict(set)
        for row in frappe.db.sql("""select t.parent, sum(t.base_tax_amount_after_discount_amount) amount
            from `tabPurchase Taxes and Charges` t inner join `tabPurchase Invoice` p on p.name=t.parent
            where p.company=%s and p.docstatus=1 and t.parenttype='Purchase Invoice'
            and t.account_head=%s and t.category in ('Total','Valuation and Total') group by t.parent""",
            (self.company, TAX_ACCOUNTS['import']), as_dict=1):
            if row.parent in index:
                invoice_import[row.parent] = money(row.amount)
        for row in frappe.db.sql("""select i.parent,i.purchase_order,sum(i.base_net_amount) amount
            from `tabPurchase Invoice Item` i inner join `tabPurchase Invoice` p on p.name=i.parent
            where p.company=%s and p.docstatus=1 and p.is_return=0 and ifnull(i.purchase_order,'')!=''
            group by i.parent,i.purchase_order""", self.company, as_dict=1):
            pi = index.get(row.parent)
            if not pi or not pi.base_net_total:
                continue
            share = money(row.amount)/money(pi.base_net_total)
            invoice_pos[pi.name].add(row.purchase_order)
            self.invoiced[row.purchase_order] += money(supplier_amount(pi.base_grand_total, invoice_import[pi.name])*share)
            # Future posted credits are represented by future_tax_events, not a second PO credit.
            self.import_credited[row.purchase_order] += money(invoice_import[pi.name]*share)
        advances = frappe.db.sql("""select a.parent,a.reference_type,a.reference_name,a.allocated_amount
            from `tabPurchase Invoice Advance` a inner join `tabPurchase Invoice` p on p.name=a.parent
            where p.company=%s and p.docstatus=1 and p.is_return=0 and a.allocated_amount>0""", self.company, as_dict=1)
        pe_refs = defaultdict(list)
        for ref in frappe.db.sql("""select r.parent,r.reference_name,r.allocated_amount
            from `tabPayment Entry Reference` r inner join `tabPayment Entry` p on p.name=r.parent
            where p.company=%s and p.docstatus=1 and r.reference_doctype='Purchase Order'""", self.company, as_dict=1):
            pe_refs[ref.parent].append(ref)
        for advance in advances:
            pi = index.get(advance.parent)
            if not pi:
                continue
            if advance.reference_type != 'Payment Entry':
                self.warn('Supplier Journal Entry advances require review against PO balances.')
                continue
            shares = advance_shares(advance.allocated_amount, pe_refs[advance.reference_name], invoice_pos[pi.name])
            for po, amount in shares.items():
                self.applied_advances[po] += self.conversion(pi, amount)
            if not shares:
                self.warn('Supplier invoice advance lacks a matching PO reference; reconcile advance allocation.')
        for record in records:
            outstanding_base = max(self.conversion(record, record.outstanding_amount), money(0))
            if not outstanding_base:
                continue
            pi = frappe.get_doc('Purchase Invoice', record.name)
            pi.check_permission('read')
            self.register_source('Purchase Invoice', pi.name, party=pi.supplier, party_type='Supplier',
                workflow_state=pi.get('status') or '', basis='Outstanding invoice schedule; no matched prepared payment for this residual')
            gross, import_tax = money(pi.base_grand_total), invoice_import[pi.name]
            supplier_total = supplier_amount(gross, import_tax)
            outstanding = supplier_outstanding(gross, outstanding_base, import_tax)
            if not outstanding:
                continue
            schedule = [dict(date=r.due_date, amount=money(Decimal(str(r.payment_amount))*Decimal(str(pi.conversion_rate or 1))),
                             paid_amount=self.conversion(pi, r.get('paid_amount') or 0),
                             payment_term=r.get('payment_term'), payment_entry=r.get('payment_entry'))
                        for r in pi.payment_schedule if r.due_date and r.payment_amount]
            if not schedule:
                schedule = [dict(date=pi.due_date, amount=gross)] if pi.due_date else []
            if gross and import_tax:
                schedule = [dict(r, amount=money(r['amount']*supplier_total/gross)) for r in schedule]
            schedule, unscheduled = invoice_installments(schedule, supplier_total, outstanding)
            if unscheduled and pi.due_date:
                schedule.append(dict(date=pi.due_date, amount=unscheduled))
                self.warn('{0}: payment schedule does not cover {1}; using invoice Due Date for that residual. Verify the schedule.'.format(pi.name, unscheduled))
                unscheduled = money(0)
            if unscheduled:
                self.warn('{0}: {1} supplier outstanding is not covered by dated installments; complete the payment schedule.'.format(pi.name, unscheduled))
            if not schedule:
                self.warn('{0}: outstanding supplier invoice has no usable dated residual.'.format(pi.name))
            planned = money(0)
            for pe, allocation in self.pending_reference_payments('Purchase Invoice', pi.name):
                allocation = min(allocation, max(outstanding-planned, money(0)))
                self.event(self.due(pe.posting_date, pe.name), 'supplier_payments', allocation,
                    'Payment Entry', pe.name, 'Scheduled payment replaces invoice installment; '+pi.name, related_doctype='Purchase Invoice', related_name=pi.name)
                # Use custom schedule PE links or explicit payment terms before FIFO.
                terms = [r for r in pe.references if r.reference_doctype == 'Purchase Invoice' and r.reference_name == pi.name]
                budget = allocation
                for ref in terms:
                    portion = min(budget, max(money(Decimal(str(ref.allocated_amount))*Decimal(str(pe.target_exchange_rate or 1))), money(0)))
                    if not portion:
                        continue
                    schedule, used, ambiguous = reserve_installment(schedule, portion, pe.name, ref.get('payment_term'))
                    if ambiguous or used < portion:
                        self.warn('{0}: installment link/term does not fully identify the allocation to {1}; residual schedule timing uses oldest-first matching. Verify the source references.'.format(pe.name, pi.name))
                        schedule, fallback, ignored = reserve_installment(schedule, portion-used)
                    budget -= portion
                planned += allocation
                self.handled_pe.add(pe.name)
            journal_planned = self.journals().reserve('Purchase Invoice', pi.name, max(outstanding-planned, money(0)))
            schedule, used, ambiguous = reserve_installment(schedule, journal_planned)
            for row in schedule:
                self.event(self.due(row['date'], pi.name), 'supplier_payments', row['amount'], 'Purchase Invoice', pi.name,
                    'Outstanding invoice; {0}; original due {1}'.format(pi.supplier, row['date']))

    def pending_reference_payments(self, doctype, name):
        if not hasattr(self, '_pending_refs'):
            self._pending_refs = defaultdict(list)
            payments = sorted(self.documents('Payment Entry', {'docstatus': 0, 'payment_type': 'Pay'}),
                              key=lambda pe: (as_date(pe.posting_date), pe.name))
            for pe in payments:
                if pe.get('workflow_state') in (None, '', 'Draft'):
                    continue
                self.register_source('Payment Entry', pe.name, party=pe.get('party') or '', party_type=pe.get('party_type') or '',
                    workflow_state=pe.get('workflow_state') or '', basis='Prepared payment document')
                budget = max(money(pe.base_paid_amount), money(0))
                allocations = defaultdict(Decimal)
                for ref in pe.references:
                    if ref.reference_doctype in ('Purchase Order', 'Purchase Invoice'):
                        requested = max(money(Decimal(str(ref.allocated_amount))*Decimal(str(pe.target_exchange_rate or 1))), money(0))
                        amount = min(requested, budget)
                        budget -= amount
                        if requested > amount:
                            self.warn('{0}: supplier reference allocations exceed the prepared cash amount; capped to base paid amount. Verify allocations.'.format(pe.name))
                        allocations[(ref.reference_doctype, ref.reference_name)] += amount
                for key, amount in allocations.items():
                    if amount:
                        self._pending_refs[key].append((pe, amount))
        return self._pending_refs.get((doctype, name), [])

    def tax_estimate(self, po):
        """Recalculate only an in-memory copy; never save/validate the source document."""
        import copy
        taxes = [t.as_dict() for t in po.taxes]
        if po.taxes_and_charges:
            template = self.read_document('Purchase Taxes and Charges Template', po.taxes_and_charges)
            expected = {t.account_head for t in template.taxes}
            if not expected.issubset({t.account_head for t in po.taxes}):
                clone = frappe.get_doc(copy.deepcopy(po.as_dict()))
                existing = {t.account_head: t for t in po.taxes}
                clone.set('taxes', [])
                for t in template.taxes:
                    values = {key: t.get(key) for key in ('charge_type', 'account_head', 'description', 'rate',
                        'row_id', 'category', 'add_deduct_tax', 'included_in_print_rate', 'cost_center')}
                    if t.charge_type == 'Actual':
                        values['tax_amount'] = existing[t.account_head].tax_amount if t.account_head in existing else t.tax_amount
                    clone.append('taxes', values)
                from erpnext.controllers.taxes_and_totals import calculate_taxes_and_totals
                calculate_taxes_and_totals(clone)
                taxes = [t.as_dict() for t in clone.taxes]
                self.warn('{0}: missing PO tax rows estimated from its selected template in memory.'.format(po.name))
                if not any(t.get('tax_amount') for t in taxes if t.get('charge_type') == 'Actual'):
                    self.warn('{0}: template actual charges are zero; verify shipping/broker estimates.'.format(po.name))
        amounts = import_cash_taxes(taxes, [t.get('base_tax_amount_after_discount_amount') or 0 for t in taxes])
        for row, amount in zip(taxes, amounts):
            row['base_tax_amount_after_discount_amount'] = amount
        return taxes

    def purchase_orders(self):
        for po in self.documents('Purchase Order', {'docstatus': 1}):
            if po.get('workflow_state') == 'Legal Dispute':
                continue
            self.register_source('Purchase Order', po.name, party=po.get('supplier') or '', party_type='Supplier',
                workflow_state=po.get('workflow_state') or '', basis='Remaining PO commitment not covered by a matched prepared payment')
            # Historical completed POs without any residual supplier amount or future ETA need no tax reconstruction.
            base = money(po.base_grand_total)
            advances = self.conversion(po, po.advance_paid)
            prelim = po_remaining(supplier_amount(base, self.invoice_import(po)), self.invoiced[po.name], advances, self.applied_advances[po.name])
            eta = as_date(po.eta_date) if po.eta_date else None
            if not prelim and (not eta or eta < self.start) and po.get('workflow_state') == 'Completed':
                continue
            if po.get('workflow_state') == 'On Hold':
                self.warn('{0}: on-hold obligation is included; review its timing.'.format(po.name))
            try:
                taxes = self.tax_estimate(po)
            except Exception as exc:
                self.warn('{0}: tax estimate unavailable ({1}); customs/VAT coverage incomplete.'.format(po.name, type(exc).__name__))
                taxes = [t.as_dict() for t in po.taxes]
            customs = sum((money(t.get('base_tax_amount_after_discount_amount')) for t in taxes
                           if t.get('account_head') == TAX_ACCOUNTS['customs']), money(0))
            import_vat = sum((money(t.get('base_tax_amount_after_discount_amount')) for t in taxes
                              if t.get('account_head') == TAX_ACCOUNTS['import']), money(0))
            # Remove only import VAT actually included in the stored supplier total, not reconstructed taxes.
            included_import = self.invoice_import(po)
            supplier_total = supplier_amount(base, included_import)
            remaining = po_remaining(supplier_total, self.invoiced[po.name], advances, self.applied_advances[po.name])
            # Ignore sub-dinar PO/PI or FX residuals, not individual installments or actual payments.
            if self.currency == 'BHD' and remaining < money(1):
                remaining = money(0)
            schedule = []
            for r in (po.payment_schedule if remaining else []):
                if not r.payment_amount:
                    continue
                amount = money(Decimal(str(r.payment_amount))*Decimal(str(po.conversion_rate or 1)))
                if base:
                    amount = money(amount*supplier_total/base)
                due = r.due_date
                if r.get('payment_entry'):
                    pe = frappe.db.get_value('Payment Entry', r.payment_entry,
                        ['docstatus', 'posting_date', 'company'], as_dict=1)
                    if pe and pe.company == self.company and pe.docstatus != 2:
                        self.handled_pe.add(r.payment_entry)
                        if pe.docstatus == 0 or as_date(pe.posting_date) > self.start:
                            due = pe.posting_date or due
                if due:
                    schedule.append(dict(date=due, amount=amount))
                else:
                    self.warn('{0}: installment has no date.'.format(po.name))
            # Replacement removes billed installments and unused advance cash from the PO schedule.
            full = sum((r['amount'] for r in schedule), money(0))
            planned = money(0)
            for pe, allocation in (self.pending_reference_payments('Purchase Order', po.name) if remaining else []):
                allocation = min(allocation, max(remaining-planned, money(0)))
                self.event(self.due(pe.posting_date, pe.name), 'supplier_payments', allocation,
                    'Payment Entry', pe.name, 'Scheduled payment replaces PO installment; '+po.name, related_doctype='Purchase Order', related_name=po.name)
                planned += allocation
                self.handled_pe.add(pe.name)
            if remaining:
                planned += self.journals().reserve('Purchase Order', po.name, max(remaining-planned, money(0)))
            consumed = max(full-remaining, money(0)) + planned
            for r in reconcile_installments(schedule, consumed):
                self.event(self.due(r['date'], po.name), 'supplier_payments', r['amount'], 'Purchase Order', po.name,
                    'Unbilled supplier commitment; {0}; original due {1}'.format(po.supplier, r['date']))
            if remaining and not schedule:
                self.warn('{0}: {1} outstanding PO amount has no payment schedule.'.format(po.name, remaining))
            if remaining > full:
                self.warn('{0}: payment schedule does not cover its full outstanding amount.'.format(po.name))
            # Actual linked customs GL payments replace ETA estimates. Draft links are not paid.
            glps = list(self.documents('GL Payment', {'purchase_order': po.name,
                         'is_customs_payment': 1, 'docstatus': ['!=', 2]}))
            paid_customs, paid_import, planned_customs, planned_import = [money(0)]*4
            for glp in glps:
                self.handled_glp.add(glp.name)
                complete = glp.docstatus == 1 and as_date(glp.posting_date) <= self.start
                for item in glp.items:
                    value = money(item.total_amount or item.net_amount)
                    if item.account == TAX_ACCOUNTS['customs']:
                        if complete: paid_customs += value
                        else: planned_customs += value
                    if item.account == TAX_ACCOUNTS['import']:
                        if complete: paid_import += value
                        else: planned_import += value
                if not complete:
                    self.gl_payment(glp, customs=True, project_tax=False)
            residual_customs = arrival_residual(customs, paid_customs, planned_customs)
            residual_import = arrival_residual(import_vat, paid_import, planned_import)
            # Already posted PI/GLP tax credits are present in opening/future tax ledgers.
            recorded_credit = self.import_credited[po.name] + paid_import
            recorded_credit += sum((money(item.total_amount or item.net_amount) for glp in glps
                if glp.docstatus == 1 and as_date(glp.posting_date) > self.start for item in glp.items
                if item.account == TAX_ACCOUNTS['import']), money(0))
            credit_remaining = max(import_vat-recorded_credit, money(0))
            for glp in glps:
                if glp.docstatus == 0:
                    credit = min(credit_remaining, sum((money(item.total_amount or item.net_amount)
                        for item in glp.items if item.account == TAX_ACCOUNTS['import']), money(0)))
                    self.event(self.due(glp.posting_date, glp.name), 'vat_accrual', -credit,
                        'GL Payment', glp.name, 'Projected import VAT credit on scheduled payment')
                    credit_remaining -= credit
            if residual_customs or residual_import:
                if po.eta_date:
                    due = self.due(po.eta_date, po.name+' customs/import VAT')
                    self.event(due, 'customs', residual_customs, 'Purchase Order', po.name, 'Unpaid template customs estimate on ETA')
                    self.event(due, 'import_vat', residual_import, 'Purchase Order', po.name, 'Unpaid template import VAT estimate on ETA')
                    self.event(due, 'vat_accrual', -credit_remaining, 'Purchase Order', po.name,
                               'Projected recoverable import VAT; separate from ETA cash payment')
                else:
                    self.warn('{0}: customs/import VAT has no ETA; payment is unscheduled.'.format(po.name))
            elif not customs and not import_vat and po.supplier_country and po.supplier_country != 'Bahrain' and remaining:
                self.warn('{0}: foreign PO has no customs/import VAT template amounts.'.format(po.name))
            local_vat = sum((money(t.get('base_tax_amount_after_discount_amount')) for t in taxes
                             if t.get('account_head') == TAX_ACCOUNTS['local']), money(0))
            if local_vat and remaining:
                self.warn('{0}: local VAT credit is taken from the posted Purchase Invoice, not the LPO payment schedule.'.format(po.name))

    def fixed_expenses(self):
        self._fixed_expense_accounts = defaultdict(set)
        self._future_fixed_expense_accounts = set()
        for expense in self.documents('Fixed Expense'):
            self.register_source('Fixed Expense', expense.name, party=expense.supplier or expense.provider_name,
                workflow_state=expense.status, basis='Schedule estimate; verify existing payment matching')
            for account in expense.get('accounts', []):
                self._fixed_expense_accounts[account.account].add(expense.name)
            if expense.status == 'Closed' and not expense.end_date:
                continue
            interval = FREQUENCIES.get(expense.billing_frequency)
            if not interval or not expense.first_due_date:
                self.warn('{0}: unsupported/missing recurrence.'.format(expense.name))
                continue
            amount = money(expense.expected_total_amount)
            if expense.currency != self.currency:
                amount = money(expense.estimated_base_total)
                age = (self.start-as_date(expense.estimate_rate_date)).days if expense.estimate_rate_date else 99999
                max_age = int(frappe.db.get_single_value('WS Settings', 'currency_exchange_max_age_days') or 4)
                if age > max_age or not expense.estimate_exchange_rate:
                    self.warn('{0}: missing/stale exchange estimate; occurrence amounts omitted.'.format(expense.name))
                    continue
            end = min(self.end, as_date(expense.end_date)) if expense.end_date else self.end
            first = max(as_date(expense.start_date), as_date(expense.first_due_date))
            history = list(occurrences(expense.first_due_date, first, end, interval))
            if len(history) > 1200:
                self.warn('{0}: excessive recurrence history; review tracking start.'.format(expense.name))
                continue
            paid = money(0)
            pending = []
            for glp in self.documents('GL Payment', {'custom_fixed_expense': expense.name, 'docstatus': ['!=', 2]}):
                self.handled_glp.add(glp.name)
                if glp.payment_type != 'Outgoing':
                    continue
                if glp.docstatus == 1 and as_date(glp.posting_date) <= self.start:
                    paid += money(glp.total_amount)
                else:
                    pending.append(glp)
            schedule = [dict(date=d, amount=amount) for d in history]
            outstanding = reconcile_installments(schedule, paid)
            # Pending payment replaces oldest unpaid occurrences up to its amount.
            planned = sum((money(p.total_amount) for p in pending), money(0))
            for glp in pending:
                if self.start < as_date(glp.posting_date) <= self.end:
                    self._future_fixed_expense_accounts.update(a.account for a in expense.get('accounts', []))
                self.gl_payment(glp, category='fixed_expenses')
            for r in reconcile_installments(outstanding, planned):
                due = self.due(r['date'], expense.name)
                if due and due > self.start:
                    self._future_fixed_expense_accounts.update(a.account for a in expense.get('accounts', []))
                self.event(due, 'fixed_expenses', r['amount'], 'Fixed Expense', expense.name,
                    '{0}; {1}; original due {2}'.format(expense.expense_name, expense.amount_type, r['date']))
                if expense.expected_total_amount:
                    tax = money(expense.expected_tax_amount)*r['amount']/money(expense.expected_total_amount)
                    # Fixed Expense validates a single added purchase tax template for each row.
                    self.event(due, 'vat_accrual', -money(tax), 'Fixed Expense', expense.name,
                               'Projected expense input VAT; recoverability requires review')
            if expense.supplier:
                self.warn('{0}: verify unlinked supplier invoices do not duplicate this expense schedule.'.format(expense.name))

    def payroll(self):
        from .payroll import Payroll
        Payroll(self).collect()

    def gl_payment(self, glp, category=None, customs=False, project_tax=True):
        self.register_source('GL Payment', glp.name, party=glp.get('party') or '', party_type=glp.get('party_type') or '',
            workflow_state=glp.get('workflow_state') or '', basis='Prepared GL Payment')
        due = self.due(glp.posting_date, glp.name)
        if glp.payment_type == 'Incoming':
            self.event(due, 'other_receipts', glp.total_amount, 'GL Payment', glp.name, 'Scheduled incoming payment')
            return
        total = money(glp.total_amount)
        remaining = total
        for item in glp.items:
            kind = category or 'other_payments'
            if customs:
                kind = 'import_vat' if item.account == TAX_ACCOUNTS['import'] else (
                    'customs' if item.account == TAX_ACCOUNTS['customs'] else 'other_payments')
            amount = money(item.total_amount or (money(item.net_amount)+money(item.tax_amount)))
            self.event(due, kind, amount, 'GL Payment', glp.name, 'Scheduled payment; {0}'.format(item.account), account=item.account)
            remaining -= amount
            if project_tax and glp.docstatus == 0:
                tax = money(item.net_amount) if item.account == TAX_ACCOUNTS['import'] else (
                      money(item.tax_amount) if item.account_head == TAX_ACCOUNTS['local'] else money(0))
                self.event(due, 'vat_accrual', -tax, 'GL Payment', glp.name, 'Projected input VAT')
        if remaining:
            self.event(due, category or 'other_payments', remaining, 'GL Payment', glp.name, 'Payment total reconciliation')

    def pending_documents(self, doctype):
        for doc in self.documents(doctype, {'docstatus': 0, 'posting_date': ['<=', self.end]}):
            yield doc
        for doc in self.documents(doctype, {'docstatus': 1, 'posting_date': ['between', [self.start+timedelta(days=1), self.end]]}):
            yield doc

    def other_payments(self):
        for glp in self.pending_documents('GL Payment'):
            self.register_source('GL Payment', glp.name, party=glp.get('party') or '', party_type=glp.get('party_type') or '',
                workflow_state=glp.get('workflow_state') or '', basis='Prepared GL Payment')
            if glp.name in self.handled_glp:
                continue
            if glp.payment_type == 'Internal Transfer':
                if glp.docstatus == 0 and glp.get('workflow_state') in (None, '', 'Draft'):
                    continue
                impact = -money(glp.total_amount) if glp.payment_account in self.accounts else money(0)
                for item in glp.items:
                    if item.account in self.accounts:
                        impact += money(item.net_amount)
                    if item.account_head in self.accounts:
                        impact += money(item.tax_amount)
                self.event(self.due(glp.posting_date, glp.name), 'other_receipts' if impact > 0 else 'other_payments',
                    abs(impact), 'GL Payment', glp.name, 'Transfer across automatic bank/cash account groups')
                continue
            if glp.docstatus == 1 and as_date(glp.posting_date) <= self.start:
                continue
            if glp.docstatus == 0 and glp.get('workflow_state') in (None, '', 'Draft'):
                continue
            self.gl_payment(glp)
        for pe in self.pending_documents('Payment Entry'):
            self.register_source('Payment Entry', pe.name, party=pe.get('party') or '', party_type=pe.get('party_type') or '',
                workflow_state=pe.get('workflow_state') or '', basis='Prepared payment document')
            if pe.payment_type == 'Internal Transfer':
                if pe.docstatus == 0 and pe.get('workflow_state') in (None, '', 'Draft'):
                    continue
                if pe.docstatus == 1 and as_date(pe.posting_date) <= self.start:
                    continue
                impact = (money(pe.base_received_amount) if pe.paid_to in self.accounts else money(0)) - (money(pe.base_paid_amount) if pe.paid_from in self.accounts else money(0))
                self.event(self.due(pe.posting_date, pe.name), 'other_receipts' if impact > 0 else 'other_payments',
                    abs(impact), 'Payment Entry', pe.name, 'Transfer across automatic bank/cash account groups')
                continue
            if pe.docstatus == 1:
                if as_date(pe.posting_date) > self.start and pe.payment_type == 'Pay':
                    self.event(pe.posting_date, 'supplier_payments', pe.base_paid_amount, 'Payment Entry', pe.name,
                               'Submitted future-dated payment; already deducted from source outstanding amounts')
                continue
            if pe.docstatus == 0 and pe.get('workflow_state') in (None, '', 'Draft'):
                continue
            # PO/invoice commitments already represent these payments; do not add their cash twice.
            refs = [r for r in pe.references if r.reference_doctype in ('Purchase Order', 'Purchase Invoice')]
            if refs and pe.payment_type == 'Pay':
                represented_events = self.events + ([] if self.include_overdue else getattr(self, 'overdue', []))
                represented = sum((money(e['amount']) for e in represented_events if e.get('doctype') == 'Payment Entry'
                    and e.get('name') == pe.name and e['category'] == 'supplier_payments'), money(0))
                residual = max(money(pe.base_paid_amount)-represented, money(0))
                if residual:
                    self.event(self.due(pe.posting_date, pe.name), 'other_payments', residual,
                        'Payment Entry', pe.name, 'Unallocated/unmatched portion of scheduled supplier payment')
                    self.warn('{0}: scheduled supplier amount is not fully matched; review overlap with obligations.'.format(pe.name))
                continue
            if pe.payment_type == 'Receive':
                self.warn('{0}: pending customer receipt is not added on top of invoice-based sales forecast.'.format(pe.name))
                continue
            self.event(self.due(pe.posting_date, pe.name), 'other_payments', pe.base_paid_amount,
                       'Payment Entry', pe.name, 'Other scheduled outgoing payment')

        self.journals().emit()
