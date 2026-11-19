"""Payment allocation/accounting rules independent of Frappe and the database."""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from .rules import number, as_date

COMPONENTS = ('principal_amount', 'interest_amount', 'charges_amount')


def money(value, precision):
    try:
        return number(value, 'Payment amount').quantize(Decimal(10) ** -precision, rounding=ROUND_HALF_UP)
    except InvalidOperation:
        raise ValueError('Payment amount exceeds supported currency precision.')


def allocation_totals(rows, precision):
    if not rows:
        raise ValueError('Add at least one payment allocation.')
    totals = {key: Decimal(0) for key in COMPONENTS + ('booked_interest', 'booked_charges')}
    seen = set()
    for row in rows:
        key = row.get('installment') or ''
        if key in seen:
            raise ValueError('Allocate each installment once per JV.')
        seen.add(key)
        values = {field: money(row.get(field), precision) for field in totals}
        if values['booked_interest'] > values['interest_amount'] or values['booked_charges'] > values['charges_amount']:
            raise ValueError('Already-booked amounts cannot exceed interest or charges being paid.')
        if sum(values[k] for k in COMPONENTS) <= 0:
            raise ValueError('Each payment allocation must have a positive amount.')
        for field in totals:
            totals[field] += values[field]
    totals['cash'] = sum(totals[k] for k in COMPONENTS)
    return totals


def expected_postings(mapping, totals):
    result = {}
    def add(account, amount):
        if amount:
            if not account:
                raise ValueError('Configure the loan, interest, charges and bank accounts required for this payment.')
            result[account] = result.get(account, Decimal(0)) + amount
    add(mapping.get('loan_account'), totals['principal_amount'] + totals['booked_interest'] + totals['booked_charges'])
    add(mapping.get('interest_account'), totals['interest_amount'] - totals['booked_interest'])
    add(mapping.get('charges_account'), totals['charges_amount'] - totals['booked_charges'])
    add(mapping.get('payment_account'), -totals['cash'])
    return {key: value for key, value in result.items() if value}


def validate_postings(mapping, totals, accounts, precision):
    actual = {}
    for row in accounts:
        debit, credit = money(row.get('debit'), precision), money(row.get('credit'), precision)
        if debit and credit:
            raise ValueError('A repayment row cannot contain both debit and credit.')
        if debit or credit:
            actual[row.get('account')] = actual.get(row.get('account'), Decimal(0)) + debit - credit
    actual = {key: value for key, value in actual.items() if value}
    if actual != expected_postings(mapping, totals):
        raise ValueError('JV account amounts do not match the loan payment allocation. Review principal, interest, already-booked amounts and charges.')


def payment_status(schedule, payments, opening, precision):
    zero = Decimal(0)
    paid = {r['name']: {k: zero for k in COMPONENTS} for r in schedule}
    totals = {k: zero for k in COMPONENTS}
    all_cash = zero
    for payment in payments:
        if int(payment.get('docstatus') or 0) != 1:
            continue
        values = allocation_totals(payment['allocations'], precision)
        all_cash += values['cash']
        if payment.get('before_tracking'):
            continue
        for field in COMPONENTS:
            totals[field] += values[field]
        for allocation in payment['allocations']:
            target = paid.setdefault(allocation.get('installment'), {k: zero for k in COMPONENTS})
            for field in COMPONENTS:
                target[field] += money(allocation.get(field), precision)
    remaining = []
    discrepancy = False
    for row in schedule:
        values = paid[row['name']]
        balances = {key: max(zero, money(row.get(key), precision) - values[key]) for key in COMPONENTS}
        excess = any(values[key] > money(row.get(key), precision) for key in COMPONENTS)
        discrepancy = discrepancy or excess
        remaining.append(dict(name=row['name'], due_date=row.get('due_date'), paid=values,
                              remaining=sum(balances.values()), balances=balances, excess=excess))
    return dict(principal_paid=totals['principal_amount'], interest_paid=totals['interest_amount'],
                charges_paid=totals['charges_amount'], total_paid=sum(totals.values()),
                outstanding_principal=money(opening, precision)-totals['principal_amount'],
                all_linked_cash_paid=all_cash, installments=remaining, needs_reschedule=discrepancy)


def validate_schedule_edit(old, new, payments, precision, require_reconciled=False):
    old = {r['name']: r for r in old}
    new = {r['name']: r for r in new}
    status = payment_status(list(old.values()), payments, Decimal(0), precision)
    posted = {r['name']: r['paid'] for r in status['installments']}
    for payment in payments:
        if payment.get('before_tracking') or int(payment.get('docstatus') or 0) == 2:
            continue
        for row in payment['allocations']:
            key = row.get('installment')
            if key not in old or key not in new:
                raise ValueError('Keep installments referenced by pending or posted JVs. Revise their unpaid amounts instead of deleting them.')
            if as_date(old[key]['due_date']) != as_date(new[key]['due_date']):
                raise ValueError('Keep the original due date of linked installments; move deferred amounts into new future rows.')
            for field in COMPONENTS:
                if int(payment.get('docstatus') or 0) == 0 and money(old[key].get(field), precision) != money(new[key].get(field), precision):
                    raise ValueError('Finish or cancel the in-progress payment before revising this installment.')
                changed=money(new[key].get(field),precision)!=money(old[key].get(field),precision)
                if money(new[key].get(field), precision) < posted[key][field] and (changed or require_reconciled):
                    raise ValueError('A revised installment cannot be smaller than its posted payments.')
