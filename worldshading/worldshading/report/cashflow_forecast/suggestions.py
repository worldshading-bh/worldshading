"""Read-only purchase date search against the exact daily forecast engine."""
from collections import defaultdict
from datetime import timedelta
from .engine import as_date, money, PAYMENTS
from .vat import quarter


def suggest_dates(start, end, events, evaluate, tolerance=1000):
    """Suggest each purchase independently, leaving every other purchase fixed.

    Cash schedules move only later, by whole days. VAT effects are recalculated by the
    existing engine once per combination of credit quarters: moving a credit
    within its quarter cannot change the next-quarter settlement. No candidate
    is allowed to drop a payment outside the forecast.
    """
    start, end, tolerance = as_date(start), as_date(end), money(tolerance)
    if tolerance < 0:
        raise ValueError('Max Shortage Tolerance cannot be negative.')
    groups = defaultdict(list)
    for event in events:
        if event.get('scenario') and event.get('purchase_number'):
            groups[event['purchase_number']].append(event)
    results = []
    for number, purchase in sorted(groups.items()):
        fixed = [event for event in events if event not in purchase]
        base = evaluate(fixed)
        cash = [money(row['closing_cash']) for row in base]
        taxes = [money(row['quarterly_vat']) for row in base]
        first = min(as_date(event['date']) for event in purchase)
        last = max(as_date(event['date']) for event in purchase)
        supplier = min(as_date(event['date']) for event in purchase if event['category'] == 'proposed_purchase')
        tax_cache = {}
        answer = dict(purchase_number=number, first_cost_date=None, supplier_date=None, shift_days=None)
        for offset in range(max(0,(first-start).days), (end-start).days-(last-first).days+1):
            candidate = start+timedelta(days=offset)
            shift = (candidate-first).days
            shifted = [dict(event, date=as_date(event['date'])+timedelta(days=shift)) for event in purchase]
            signature = tuple(str(quarter(event['date'])) for event in shifted if event['category'] == 'vat_accrual')
            if signature not in tax_cache:
                if signature:
                    calculated = evaluate(fixed+shifted)
                    running = money(0)
                    tax_cache[signature] = []
                    for i,row in enumerate(calculated):
                        running += money(row['quarterly_vat'])-taxes[i]
                        tax_cache[signature].append(running)
                else:
                    tax_cache[signature] = [money(0)]*len(base)
            costs = defaultdict(lambda: money(0))
            for event in shifted:
                if event['category'] in PAYMENTS:
                    costs[(event['date']-start).days] += money(event['amount'])
            accumulated = money(0)
            lowest = None
            for i in range(offset,len(cash)):
                accumulated += costs.get(i,0)
                closing = cash[i]-accumulated-tax_cache[signature][i]
                lowest = closing if lowest is None else min(lowest,closing)
                if closing < -tolerance:
                    break
            else:
                answer.update(first_cost_date=str(candidate), supplier_date=str(supplier+timedelta(days=shift)),
                              shift_days=shift, lowest_cash=str(lowest),
                              schedule=[dict(date=str(event['date']),category=event['category'],amount=str(money(event['amount'])),
                                             kind=event.get('scenario_kind')) for event in sorted(shifted,key=lambda event:event['date'])
                                        if event['category'] in PAYMENTS])
                break
        results.append(answer)
    return results
