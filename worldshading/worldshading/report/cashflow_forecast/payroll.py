"""Payroll ledger control and forward salary estimates; no accounting writes."""
from collections import defaultdict, deque
from calendar import monthrange
from datetime import date, timedelta
from decimal import Decimal
import frappe
from .engine import money, as_date, occurrences
from .rules import salary_estimate


def salary_period(slip):
    return as_date(slip.get('end_date') or slip.get('start_date')).strftime('%Y-%m')


def cycle_start_day(slips):
    full=[]
    for slip in slips:
        if not slip.get('payroll_entry') or not slip.get('end_date'):continue
        first,last=as_date(slip['start_date']),as_date(slip['end_date'])
        if 24<=(last-first).days+1<=32 and first.day<=28 and (last+timedelta(days=1)).day==first.day:
            full.append((last,first.day))
    return max(full)[1] if full else 1


def period_bounds(month,start_day=1):
    end_month=as_date(month+'-01')
    if start_day==1:return end_month,end_month.replace(day=monthrange(end_month.year,end_month.month)[1])
    previous=end_month-timedelta(days=1)
    return previous.replace(day=start_day),end_month.replace(day=start_day-1)


def payable_lots(rows):
    """FIFO pooled liabilities; debit balances carry as prepayments, never new debt."""
    lots=deque();advance=money(0)
    for row in sorted(rows,key=lambda r:(as_date(r['date']),r.get('name') or '')):
        change=money(row.get('credit'))-money(row.get('debit'))
        if change>0:
            used=min(advance,change);advance-=used;change-=used
            if change:lots.append(dict(row,amount=change))
        elif change<0:
            remaining=-change
            while remaining and lots:
                used=min(remaining,lots[0]['amount']);lots[0]['amount']-=used;remaining-=used
                if not lots[0]['amount']:lots.popleft()
            advance+=remaining
    return list(lots),money(advance)


class Payroll(object):
    def __init__(self,source):
        self.s=source

    def slips(self):
        return frappe.get_list('Salary Slip',filters={'company':self.s.company,'docstatus':1},
            fields=['name','employee','start_date','end_date','net_pay','payroll_entry','journal_entry'],
            order_by='end_date asc, name asc',limit_page_length=0)

    def booked_rows(self):
        s=self.s
        account=getattr(s,'payroll_account',None)
        if not account:frappe.throw('Set the company Payroll Payable account before forecasting payroll.')
        doc=frappe.get_doc('Account',account);doc.check_permission('read')
        if doc.company!=s.company or doc.is_group:frappe.throw('Payroll Payable account company/group mismatch.')
        return frappe.db.sql('''select posting_date date,voucher_type doctype,voucher_no name,
            sum(debit) debit,sum(credit) credit from `tabGL Entry`
            where company=%s and account=%s and posting_date<=%s
            group by posting_date,voucher_type,voucher_no order by posting_date,voucher_no''',
            (s.company,account,s.start),as_dict=1)

    def collect(self):
        s=self.s
        if not frappe.has_permission('Salary Structure Assignment','read') or not frappe.has_permission('Salary Slip','read'):
            s.warn('Payroll access unavailable: payroll is omitted; forecast is incomplete.');return
        slips=list(self.slips())
        self.cycle_day=cycle_start_day(slips)
        rows=self.booked_rows()
        booked={row['name'] for row in rows if row['doctype']=='Journal Entry' and money(row['credit'])>money(row['debit'])}
        linked_periods=defaultdict(set)
        for slip in slips:
            if slip.get('journal_entry') in booked:linked_periods[slip.journal_entry].add(salary_period(slip))
        lots,advance=payable_lots(rows)
        balance=money(sum((money(row['credit'])-money(row['debit']) for row in rows),money(0)))
        reserved=money(0)
        for lot in lots:
            periods=linked_periods.get(lot['name'],set())
            period=next(iter(periods)) if len(periods)==1 else as_date(lot['date']).strftime('%Y-%m')
            payday=max(as_date(period+'-28'),as_date(lot['date']))
            amount=lot['amount']
            amount_reserved=s.journals().reserve_payable(s.payroll_account,amount)
            reserved+=amount_reserved
            s.event(s.due(payday,'Recorded payroll balance'),'payroll',amount-amount_reserved,
                'Account',s.payroll_account,'Recorded Payroll Payable balance; pooled ledger reconciliation',
                related_doctype=lot['doctype'],related_name=lot['name'])
        s.payroll_reconciliation=dict(account=s.payroll_account,balance=str(balance),prepayment=str(advance),
            scheduled=str(reserved),remaining=str(money(sum((lot['amount'] for lot in lots),money(0))-reserved)),
            cutoff=str(s.start),cycle_start_day=self.cycle_day,basis='Posted Payroll Payable ledger; exact balance, including rounding differences')
        # Historical slips explain recorded liabilities; they are not added again.
        old_unverified=[slip for slip in slips if salary_period(slip)<s.start.strftime('%Y-%m') and slip.get('journal_entry') not in booked]
        if old_unverified:
            s.warn('{0} historical Salary Slips lack a verified Payroll Payable booking link; review their bookings/payments. They are not assumed paid or added on top of the recorded ledger balance: {1}.'.format(
                len(old_unverified),', '.join(slip.name for slip in old_unverified[:8])))
        actual=defaultdict(list)
        for slip in slips:
            period=salary_period(slip)
            if period>=s.start.strftime('%Y-%m') and period<=s.end.strftime('%Y-%m'):
                actual[(slip.employee,period)].append(slip)
        batches=defaultdict(lambda:money(0));batch_links=defaultdict(list)
        for (employee,period),employee_slips in actual.items():
            if len(employee_slips)>1:
                s.warn('{0}: multiple submitted Salary Slips ending in {1}; review payroll before relying on this period. No duplicate slips or estimate added.'.format(employee,period));continue
            slip=employee_slips[0]
            if slip.get('journal_entry') in booked:continue
            batch=slip.get('payroll_entry') or slip.name
            batches[(period,batch)]+=money(slip.net_pay)
            batch_links[(period,batch)].append(slip)
        for (period,batch),total in batches.items():
            if total<=0:
                if total<0:s.warn('{0}: negative net salary needs review; no automatic cash receipt assumed.'.format(batch))
                continue
            linked=batch_links[(period,batch)]
            is_batch=bool(linked[0].get('payroll_entry'))
            pending=s.journals().reserve('Payroll Entry',batch,total) if is_batch else money(0)
            # Submitted future bank JEs are not in the opening ledger; reserve them too.
            pending+=s.journals().reserve_future_payroll(batch,max(total-pending,money(0))) if is_batch else money(0)
            pending+=s.journals().reserve_payable(s.payroll_account,max(total-pending,money(0)),not_before=as_date(period+'-01'),not_after=as_date(period+'-01').replace(day=monthrange(int(period[:4]),int(period[5:]))[1]),
                description='Scheduled Payroll Payable payment replaces forward Salary Slip forecast')
            s.event(s.due(as_date(period+'-28'),batch+' payroll'),'payroll',max(total-pending,money(0)),
                'Payroll Entry' if is_batch else 'Salary Slip',batch,
                'Submitted Salary Slip net pay; salary month '+period,
                related_documents=[dict(doctype='Salary Slip',name=slip.name) for slip in linked])
        self.estimates(actual,advance)

    def estimates(self,actual,advance=0):
        s=self.s
        assignments=defaultdict(list)
        for assignment in s.documents('Salary Structure Assignment',{'docstatus':1,'from_date':['<=',s.end]}):
            assignments[assignment.employee].append(assignment)
        for values in assignments.values():values.sort(key=lambda a:(as_date(a.from_date),a.creation),reverse=True)
        earliest,_=period_bounds(s.start.strftime('%Y-%m'),getattr(self,'cycle_day',1))
        employees={employee.name:employee for employee in s.documents('Employee',{'status':'Active'})}
        for employee in s.documents('Employee',{'status':'Left','relieving_date':['>=',earliest]}):employees[employee.name]=employee
        employees=list(employees.values())
        for payday in occurrences(date(s.start.year,s.start.month,28),date(s.start.year,s.start.month,1),s.end,1):
            period=payday.strftime('%Y-%m');first,last=period_bounds(period,getattr(self,'cycle_day',1))
            period_days=(last-first).days+1
            for employee in employees:
                if (employee.name,period) in actual:continue
                if employee.date_of_joining and as_date(employee.date_of_joining)>last:continue
                if employee.relieving_date and as_date(employee.relieving_date)<first:continue
                active_from=max(first,as_date(employee.date_of_joining)) if employee.date_of_joining else first
                choices=[a for a in assignments.get(employee.name,[]) if as_date(a.from_date)<=active_from]
                if not choices:
                    s.warn('{0}: no assignment effective at employment/period start {1}.'.format(employee.name,active_from));continue
                assignment=choices[0]
                if any(active_from<as_date(a.from_date)<=last for a in assignments[employee.name]):
                    s.warn('{0}: salary assignment changes within {1}; baseline uses the starting assignment.'.format(employee.name,period))
                structure=s.read_document('Salary Structure',assignment.salary_structure)
                if structure.payroll_frequency!='Monthly' or structure.salary_slip_based_on_timesheet:
                    s.warn('{0}: non-monthly/timesheet salary cannot be estimated.'.format(employee.name));continue
                active_to=min(last,as_date(employee.relieving_date)) if employee.relieving_date else last
                fraction=Decimal(max((active_to-active_from).days+1,0))/Decimal(period_days)
                context=dict(employee.as_dict());context.update(base=assignment.base,variable=assignment.variable,start_date=first,end_date=last,
                    total_working_days=period_days,payment_days=(active_to-active_from).days+1)
                components=[dict(row.as_dict(),parentfield=field) for field in ('earnings','deductions') for row in structure.get(field)]
                try:amount=salary_estimate(components,context,lambda expression,values:frappe.safe_eval(expression,eval_locals=values),fraction)
                except Exception as exc:
                    s.warn('{0}: salary formula unavailable ({1}); estimate omitted.'.format(employee.name,type(exc).__name__));continue
                if amount<0:
                    s.warn('{0}: estimated salary is negative; no automatic cash receipt assumed.'.format(employee.name));continue
                scheduled=s.journals().reserve_payable(s.payroll_account,amount,not_before=payday.replace(day=1),not_after=payday.replace(day=monthrange(payday.year,payday.month)[1]),
                    description='Scheduled Payroll Payable payment replaces forward salary estimate')
                s.event(s.due(payday,employee.name+' payroll'),'payroll',max(amount-scheduled,money(0)),'Salary Structure Assignment',assignment.name,
                    'Monthly salary estimate; {0}; payment on 28th'.format(period))
        if advance:
            s.warn('Payroll Payable has a debit balance of {0:,.3f}; review salary prepayments. It is not automatically deducted from unrelated future employees.'.format(advance))
