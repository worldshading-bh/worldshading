"""Quarter VAT arithmetic and payment identification; no database access."""
from collections import defaultdict
from datetime import date, timedelta
import re
try:
    from .engine import as_date, money
except ImportError:
    from engine import as_date, money


def quarter(value):
    value=as_date(value)
    return date(value.year,((value.month-1)//3)*3+1,1)


def due_date(value):
    value=quarter(value)
    return date(value.year+1,1,25) if value.month==10 else date(value.year,value.month+3,25)


def label(value):
    value=quarter(value)
    return 'Q{0} {1}'.format((value.month-1)//3+1,value.year)


def referenced_quarter(text):
    matches=set(re.findall(r'\bQ([1-4])\s*(?:[-/,]|of)?\s*(20\d{2})\b',str(text or ''),re.I))
    if len(matches)!=1:return None
    number,year=next(iter(matches))
    return date(int(year),(int(number)-1)*3+1,1)


def settlement_amount(rows, accounts, tax_accounts, output_account=None):
    """Only balanced VAT-to-liquidity journals qualify, not expense/transfer JEs."""
    if output_account and not any(r.get('account')==output_account and money(r.get('debit'))>money(r.get('credit')) for r in rows):return money(0)
    cash=money(0);tax=money(0);balance=money(0)
    for row in rows:
        amount=money(row.get('debit'))-money(row.get('credit'))
        balance+=amount
        if row.get('account') in accounts:cash-=amount
        elif row.get('account') in tax_accounts:tax+=amount
        elif amount:return money(0)
    return cash if not balance and cash>0 and cash==tax else money(0)


class VatBook(object):
    def __init__(self,start,opening=0):
        self.start=as_date(start)
        self.raw=defaultdict(lambda:money(0))
        if isinstance(opening,dict):
            for period,amount in opening.get('balances',{}).items():self.raw[quarter(period)]+=money(amount)
        else:self.raw[quarter(start)]=money(opening)
        self.raw[quarter(start)]+=money(0)

    def copy(self):
        return VatBook(self.start,{'balances':{str(k):v for k,v in self.raw.items()}})

    def balances(self):
        result={};carry=money(0)
        for period in sorted(self.raw):
            amount=money(self.raw[period]+carry)
            result[period]=max(amount,money(0))
            carry=min(amount,money(0))
        if carry:result[max(self.raw)]=carry
        return result

    def add(self,day,amount):self.raw[quarter(day)]+=money(amount)

    def allocate(self,day,amount,target=None):
        remaining=max(money(amount),money(0));allocations={}
        if target:
            target=quarter(target);self.raw[target]-=remaining
            return {target:remaining}
        for period,balance in sorted(self.balances().items()):
            if period>=quarter(day) or balance<=0:continue
            used=min(remaining,balance)
            if used:self.raw[period]-=used;allocations[period]=used;remaining-=used
            if not remaining:break
        if remaining:
            period=quarter(day);self.raw[period]-=remaining
            allocations[period]=allocations.get(period,money(0))+remaining
        return allocations

    def total(self):return money(sum(self.raw.values(),money(0)))


def plan_reservations(book,events):
    """Identify known settlements before generating automatic residual payments."""
    projected=book.copy()
    for event in events:
        if event['category']=='vat_accrual':projected.add(event.get('vat_date') or event['date'],event['amount'])
    allocations={}
    for index,event in sorted(enumerate(events),key=lambda pair:(as_date(pair[1]['date']),pair[0])):
        if event['category']=='vat_settlement':
            allocations[index]=projected.allocate(event['date'],event['amount'],event.get('vat_quarter'))
    return allocations
