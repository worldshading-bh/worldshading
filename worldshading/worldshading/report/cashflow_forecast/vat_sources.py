"""Read-only VAT ledger reconciliation and unpaid-quarter commitments."""
from collections import defaultdict
from datetime import date, timedelta
import frappe
from .engine import money, as_date
from .vat import VatBook, quarter, due_date, label, referenced_quarter, settlement_amount, plan_reservations
from .sources import TAX_ACCOUNTS


class VatSources(object):
    def __init__(self,source):
        self.source=source
        self.settlements={}
        self.paid=[]
        self.activity=defaultdict(lambda:money(0))
        self.summary=[]

    def load(self):
        s=self.source
        accounts=tuple(TAX_ACCOUNTS[k] for k in ('output','local','import'))
        for name in accounts:
            if not frappe.db.exists('Account',{'name':name,'company':s.company}):
                frappe.throw('VAT account mapping missing: '+name)
            frappe.get_doc('Account',name).check_permission('read')
        # Use existing account indexes rather than a broad company-wide ledger scan.
        candidate_branch="""select voucher_type,voucher_no,posting_date,account,debit,credit
            from `tabGL Entry` where company=%s and account=%s and posting_date<=%s
            and voucher_type='Journal Entry'"""
        candidate_sql=' union all '.join([candidate_branch]*len(accounts))
        parameters=tuple(value for account in accounts for value in (s.company,account,s.end))
        candidates=frappe.db.sql("""select voucher_type,voucher_no,posting_date,
            sum(credit-debit) change_amount from ("""+candidate_sql+""") tax
            group by voucher_type,voucher_no,posting_date
            having sum(case when account=%s then debit-credit else 0 end)>0 and sum(credit-debit)<0""",
            parameters+(TAX_ACCOUNTS['output'],),as_dict=1)
        latest=quarter(quarter(s.start)-timedelta(days=1))
        unreadable=[]
        for row in candidates:
            if not frappe.has_permission(row.voucher_type,'read'):
                if as_date(row.posting_date)>=latest:
                    unreadable.append(row.voucher_no)
                continue
            doc=s.read_document(row.voucher_type,row.voucher_no)
            if doc.docstatus!=1:continue
            amount=settlement_amount([r.as_dict() for r in doc.accounts],set(s.accounts),set(accounts),TAX_ACCOUNTS['output'])
            if not amount or amount!=-money(row.change_amount):
                # Ordinary VAT adjustments remain in ledger activity, not settlement proof.
                continue
            text=' '.join(str(doc.get(k) or '') for k in ('user_remark','remark','remarks'))
            info=dict(doctype=row.voucher_type,name=row.voucher_no,date=as_date(row.posting_date),
                      amount=amount,vat_quarter=referenced_quarter(text))
            self.settlements[(row.voucher_type,row.voucher_no)]=info
        activity_branch="""select posting_date,debit,credit from `tabGL Entry`
            where company=%s and account=%s and posting_date<=%s"""
        activity_sql=' union all '.join([activity_branch]*len(accounts))
        parameters=tuple(value for account in accounts for value in (s.company,account,s.start))
        rows=frappe.db.sql("""select year(posting_date) year,quarter(posting_date) period,
            sum(credit-debit) amount from ("""+activity_sql+""") tax
            group by year(posting_date),quarter(posting_date)""",parameters,as_dict=1)
        for row in rows:self.activity[date(int(row.year),(int(row.period)-1)*3+1,1)]+=money(row.amount)
        ledger_total=money(sum(self.activity.values(),money(0)))
        for info in self.settlements.values():
            if info['date']<=s.start:
                self.activity[quarter(info['date'])]+=info['amount']
                self.paid.append(info)
        book=VatBook(s.start,{'balances':{str(k):v for k,v in self.activity.items()}})
        allocated=defaultdict(lambda:money(0));links=defaultdict(list)
        for info in sorted(self.paid,key=lambda r:(r['date'],r['name'])):
            portions=book.allocate(info['date'],info['amount'],info['vat_quarter'])
            for period,amount in portions.items():
                allocated[period]+=amount;links[period].append(dict(doctype=info['doctype'],name=info['name']))
        if book.total()!=ledger_total:frappe.throw('VAT reconciliation failed: ledger and quarter balances differ.')
        # Keep historical balances for matching real payments; only suppress
        # automatic missing-payment estimates for older completed quarters.
        s.vat_opening={'balances':{str(k):str(v) for k,v in book.raw.items()}}
        s.vat_ledger_balance=ledger_total
        balances=book.balances()
        if balances.get(latest,money(0))>0 and unreadable:
            s.warn('Cannot verify the latest quarter VAT payment: Journal Entry access is missing for '+', '.join(unreadable)+'.')
        for period in sorted(set(self.activity)|set(allocated)):
            if period<latest:continue
            balance=balances.get(period,money(0))
            self.summary.append(dict(period=str(period),quarter=label(period),due_date=str(due_date(period)),
                net_vat=str(self.activity[period]),paid=str(allocated[period]),balance=str(balance),
                status='Credit' if balance<0 else ('Credit carried' if self.activity[period]-allocated[period]<0 else ('Paid' if not balance and allocated[period] else ('Open' if due_date(period)>s.start else ('Unpaid' if balance else 'Cleared')))),
                documents=links[period],credit_used=str(max(max(self.activity[period]-allocated[period],money(0))-max(balance,money(0)),money(0)))))

    def future_events(self):
        s=self.source
        rows=frappe.db.sql('''select posting_date,voucher_type,voucher_no,sum(credit-debit) amount
            from `tabGL Entry` where company=%s and account in %s and posting_date>%s and posting_date<=%s
            and voucher_type!='Sales Invoice' group by posting_date,voucher_type,voucher_no''',
            (s.company,tuple(TAX_ACCOUNTS[k] for k in ('output','local','import')),s.start,s.end),as_dict=1)
        for row in rows:
            if (row.voucher_type,row.voucher_no) in self.settlements:continue
            s.event(row.posting_date,'vat_accrual',row.amount,description='Posted VAT: {0} {1}'.format(row.voucher_type,row.voucher_no))

    def finalize(self):
        s=self.source
        events=s.events+([] if s.include_overdue else s.overdue)
        book=VatBook(s.start,s.vat_opening)
        reservations=plan_reservations(book,events)
        reserved=defaultdict(lambda:money(0))
        for portions in reservations.values():
            for period,amount in portions.items():reserved[period]+=amount
        for row in self.summary:
            period=quarter(row['period'])
            row['scheduled']=str(reserved[period])
            if money(row['balance'])>0 and reserved[period]>=money(row['balance']):row['status']='Scheduled'
        for period,balance in book.balances().items():
            due=due_date(period)
            if period!=quarter(quarter(s.start)-timedelta(days=1)) or due>s.start:continue
            remaining=max(balance-reserved[period],money(0))
            if remaining:
                s.event(due,'vat_settlement',remaining,name=label(period),description='Unpaid VAT for '+label(period),
                        vat_quarter=str(period),estimated_vat=True)
        s.vat_reconciliation=self.summary
