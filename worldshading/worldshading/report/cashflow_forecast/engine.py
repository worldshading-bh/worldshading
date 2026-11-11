"""Pure forecast arithmetic. No Frappe imports, database access or writes."""
from calendar import monthrange
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

PAYMENTS = ('fixed_expenses', 'payroll', 'supplier_payments', 'customs', 'import_vat',
            'quarterly_vat', 'extra_expenses', 'other_payments', 'budget_expenses', 'proposed_purchase')
FREQUENCIES = {'Monthly': 1, 'Quarterly': 3, 'Half-yearly': 6, 'Yearly': 12,
               'Every 2 Years': 24, 'Every 3 Years': 36, 'Every 4 Years': 48, 'Every 5 Years': 60}


def money(value, precision=3):
    try:
        result = Decimal(str(value or 0))
        if not result.is_finite():
            raise ValueError('Amounts must be finite numbers.')
        return result.quantize(Decimal(1).scaleb(-precision), rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError):
        raise ValueError('Invalid monetary amount.')


def as_date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return datetime.strptime(str(value), '%Y-%m-%d').date()


def days(start, end):
    current, end = as_date(start), as_date(end)
    while current <= end:
        yield current
        current += timedelta(days=1)


def occurrences(anchor, start, end, months):
    anchor, start, end = as_date(anchor), as_date(start), as_date(end)
    if months <= 0:
        raise ValueError('Frequency must be positive.')
    offset = max(0, ((start.year-anchor.year)*12 + start.month-anchor.month)//months)
    while True:
        absolute = anchor.year*12 + anchor.month-1 + offset*months
        year, month = absolute//12, absolute % 12+1
        due = date(year, month, min(anchor.day, monthrange(year, month)[1]))
        if due > end:
            return
        if due >= start:
            yield due
        offset += 1


def template_taxes(net, rows, rate=1):
    """ERPNext row-total chaining: Valuation rows do not increase row totals."""
    net, rate = money(net), Decimal(str(rate))
    amounts, totals, original_amounts = [], [], []
    for idx, row in enumerate(rows):
        kind = row.get('charge_type')
        percent = Decimal(str(row.get('rate') or 0)) / 100
        ref = int(row.get('row_id') or 0)-1
        if kind == 'Actual':
            amount = money(row.get('tax_amount', 0))
        elif kind == 'On Net Total':
            amount = money(net*percent)
        elif kind in ('On Previous Row Total', 'On Previous Row Amount'):
            if ref < 0 or ref >= idx:
                raise ValueError('Invalid preceding tax-row reference.')
            basis = totals[ref] if kind == 'On Previous Row Total' else original_amounts[ref]
            amount = money(basis*percent)
        else:
            raise ValueError('Unsupported tax charge type: {0}'.format(kind))
        signed = -amount if row.get('add_deduct_tax') == 'Deduct' else amount
        original_amounts.append(amount)
        totals.append((totals[-1] if totals else net) + (0 if row.get('category') == 'Valuation' else signed))
        amounts.append(money(signed*rate))
    return amounts


def import_cash_taxes(rows, amounts):
    """Include valuation-only customs omitted from the import VAT row-total base.

    Amounts may be calculated estimates or stored PO amounts in company currency.
    Customs already included in row totals must not be added a second time.
    """
    result = [money(value) for value in amounts]
    for index, row in enumerate(rows):
        if (row.get('account_head') != 'Input VAT – Import - WS'
                or row.get('charge_type') != 'On Previous Row Total'):
            continue
        reference = int(row.get('row_id') or 0)
        customs = sum((result[i] for i, previous in enumerate(rows[:reference])
                       if previous.get('account_head') == 'Custom Duty - WS'
                       and previous.get('category') == 'Valuation'), money(0))
        result[index] += money(customs * Decimal(str(row.get('rate') or 0)) / 100)
    return result


def reconcile_installments(schedule, paid=0, invoice_outstanding=0):
    """Consume paid cash then invoice-replaced debt, oldest installments first."""
    consumed = max(money(paid), 0) + max(money(invoice_outstanding), 0)
    result = []
    for row in sorted(schedule, key=lambda r: as_date(r['date'])):
        amount = max(money(row['amount']), 0)
        used = min(amount, consumed)
        consumed -= used
        amount -= used
        if amount:
            result.append(dict(row, amount=amount))
    return result


def today_sales(actual,target):
    actual,target=money(actual),money(target)
    remaining=max(money(target-actual),money(0))
    return dict(actual=actual,target=target,remaining=remaining,total=money(actual+remaining))


def build_forecast(start, end, opening, events, historical, adjustment=0, support=0,
                   reserve=0, today_receipts=0, vat_opening=0, manual_daily_sales=None, holidays=None, actual_sales_today=None):
    start, end = as_date(start), as_date(end)
    adjustment = money(adjustment)
    holiday_dates = {as_date(value) for value in (holidays or [])}
    if manual_daily_sales is not None and money(manual_daily_sales) < 0:
        raise ValueError("Average Daily Sales cannot be negative.")
    if end < start or (end-start).days > 730:
        raise ValueError('End date must be within 730 days of today.')
    if adjustment < -100:
        raise ValueError('Sales adjustment cannot be below -100%.')
    if money(support) < 0 or money(reserve) < 0:
        raise ValueError('Support and reserve cannot be negative.')
    try:
        from .vat import VatBook, plan_reservations, quarter, due_date, label
    except ImportError:  # direct standalone arithmetic fixtures
        from vat import VatBook, plan_reservations, quarter, due_date, label
    from collections import defaultdict
    events = list(events)
    vat = VatBook(start, vat_opening)
    allocations = plan_reservations(vat, events)
    reserved = defaultdict(lambda: money(0))
    for portions in allocations.values():
        for period, amount in portions.items(): reserved[period] += amount
    indexed = {}
    for index, event in enumerate(events):
        due = as_date(event['date'])
        if start <= due <= end:
            indexed.setdefault(due, []).append((index, event))
    balance = money(opening) + money(support)
    result = []
    for day in days(start, end):
        last_year = money(historical.get(str(day), 0))
        adjusted = money(last_year*(1 + adjustment/100))
        if manual_daily_sales is not None:
            adjusted = money(0) if day in holiday_dates else money(manual_daily_sales)
        receipts = money(today_receipts) if day == start else adjusted
        cash_receipts=receipts;already_recorded=money(0);remaining_today=money(0)
        if day==start and actual_sales_today is not None:
            calculation=today_sales(actual_sales_today,adjusted)
            receipts=calculation['total'];cash_receipts=calculation['remaining']
            already_recorded=calculation['actual'];remaining_today=calculation['remaining']
        row = dict(date=day, opening_cash=balance, previous_year_sales=last_year,
                   adjusted_sales=adjusted, expected_receipts=receipts, sales_cash_inflow=cash_receipts,
                   sales_already_recorded=already_recorded,remaining_sales_today=remaining_today,other_receipts=money(0),
                   sources=[], warnings=[])
        row.update({key: money(0) for key in PAYMENTS})
        for index, event in indexed.get(day, []):
            category, amount = event['category'], money(event['amount'])
            if category == 'vat_settlement':
                row['quarterly_vat'] += amount
                for period, portion in allocations.get(index, {}).items():
                    vat.allocate(day, portion, period)
                    reserved[period] -= portion
            elif category == 'vat_accrual':
                vat.add(event.get('vat_date') or day, amount)
            elif category in PAYMENTS or category == 'other_receipts':
                row[category] += amount
            else:
                raise ValueError('Unknown event category: {0}'.format(category))
            row['sources'].append(dict(event, amount=amount))
        if day.month in (1, 4, 7, 10) and day.day == 25:
            period = quarter(date(day.year, day.month, 1)-timedelta(days=1))
            settlement = max(vat.balances().get(period, money(0))-reserved[period], money(0))
            row['quarterly_vat'] += settlement
            if settlement:
                row['sources'].append(dict(date=day, category='quarterly_vat', amount=settlement,
                    vat_quarter=str(period), description='VAT payment for '+label(period)))
                vat.allocate(day, settlement, period)
        row['vat_position'] = vat.total()
        row['total_receipts'] = money(row['sales_cash_inflow']+row['other_receipts'])
        row['total_payments'] = money(sum(row[k] for k in PAYMENTS))
        balance = money(balance+row['total_receipts']-row['total_payments'])
        row['closing_cash'] = balance
        row['below_reserve'] = int(balance < money(reserve))
        result.append(row)
    return result


def summarize(rows, reserve=0):
    lowest = min(rows, key=lambda r: r['closing_cash'])
    return dict(lowest_balance=lowest['closing_cash'], lowest_date=lowest['date'],
        first_shortfall_date=next((r['date'] for r in rows if r['closing_cash'] < 0), None),
        first_reserve_date=next((r['date'] for r in rows if r['closing_cash'] < money(reserve)), None),
        ending_balance=rows[-1]['closing_cash'])


def monthly_rows(rows):
    result = []
    for row in rows:
        key = row['date'].strftime('%Y-%m')
        if not result or result[-1]['month'] != key:
            result.append(dict(row, month=key, sources=list(row['sources'])))
        else:
            target = result[-1]
            for field in PAYMENTS + ('previous_year_sales', 'adjusted_sales', 'expected_receipts',
                                     'sales_cash_inflow','sales_already_recorded','remaining_sales_today',
                                     'other_receipts', 'total_receipts', 'total_payments'):
                target[field] += row[field]
            target['closing_cash'] = row['closing_cash']
            for field in ('baseline_closing_cash', 'purchase_impact'):
                if field in row:
                    target[field] = row[field]
            target['sources'].extend(row['sources'])
            target['below_reserve'] = max(target['below_reserve'], row['below_reserve'])
    return result
