"""Calendar-period schedule estimates. Pure calculations; no posting or saving."""
import calendar
import copy
from decimal import Decimal, InvalidOperation, Overflow, ROUND_HALF_UP
from .rules import as_date, number, calculate_schedule

MONTHS = {'Monthly': 1, 'Quarterly': 3, 'Half-yearly': 6, 'Yearly': 12}
METHODS = ('Equal Principal', 'Equal Installments', 'Interest Only / Balloon')


def anchored_date(anchor, months):
    year, month = divmod(anchor.year * 12 + anchor.month - 1 + months, 12)
    month += 1
    return as_date('{0:04d}-{1:02d}-{2:02d}'.format(year, month,
        min(anchor.day, calendar.monthrange(year, month)[1]))).isoformat()


def generate_schedule(loan, options, precision, today):
    loan, options = copy.deepcopy(loan), dict(options)
    method = options.get('method')
    if method not in METHODS:
        raise ValueError('Select a repayment method.')
    basis = loan.get('interest_calculation_basis')
    if basis not in ('Diminishing', 'Flat Rate'):
        raise ValueError('Choose Diminishing or Flat Rate to generate; otherwise enter the bank schedule manually.')
    months = MONTHS.get(loan.get('repayment_frequency'))
    if not months:
        raise ValueError('Automatic estimates require Monthly, Quarterly, Half-yearly or Yearly frequency.')
    today = as_date(today)
    # Validate dates, principal and any current rows before generating replacements.
    initial = calculate_schedule(loan, precision)
    original, opening = initial['original_principal'], initial['opening_principal']
    unit = Decimal(10) ** -precision
    def money(value):
        try:
            return Decimal(value).quantize(unit, rounding=ROUND_HALF_UP)
        except (InvalidOperation, Overflow):
            raise ValueError('The calculated amounts exceed the supported currency precision.')
    rate_change = bool(options.get('rate_change'))
    prefix = []
    if rate_change:
        if loan.get('interest_rate_type') != 'Variable':
            raise ValueError('Future rate changes require a Variable loan.')
        calculate_schedule(loan, precision, complete=True)
        effective = as_date(options.get('effective_date'))
        if effective < today:
            raise ValueError('The rate-change date cannot be before today.')
        previous = loan.get('schedule') or []
        anchor = as_date(previous[0].get('due_date'))
        if any(as_date(row.get('due_date')).isoformat() != anchored_date(anchor, months * i)
               for i, row in enumerate(previous)):
            raise ValueError('This bank schedule has irregular periods. Enter bank-provided amounts for rate changes.')
        prefix = [r for r in previous if as_date(r.get('due_date')) < effective]
        future_rows = [r for r in previous if as_date(r.get('due_date')) >= effective]
        dates = [as_date(r.get('due_date')).isoformat() for r in future_rows]
        if effective.isoformat() not in dates:
            raise ValueError('Choose an installment due date for the rate change. Mid-period changes require the bank schedule.')
        if not dates:
            raise ValueError('No scheduled installments fall on or after this rate-change date.')
        annual = number(options.get('new_rate'), 'New Annual Interest Rate')
    else:
        if any(as_date(r.get('due_date')) < today for r in loan.get('schedule') or []):
            raise ValueError('Past installments cannot be replaced. Use a future rate change or edit the bank schedule manually.')
        periods = number(options.get('periods'), 'Number of Installments')
        if not 1 <= periods <= 600 or periods != int(periods):
            raise ValueError('Enter a whole number of installments from 1 to 600.')
        anchor = as_date(options.get('first_due_date'))
        try:
            dates = [anchored_date(anchor, months * i) for i in range(int(periods))]
        except (ValueError, OverflowError):
            raise ValueError('Generated installment dates are outside the supported calendar.')
        annual = number(loan.get('annual_interest_rate'), 'Annual Interest Rate')
    balance = opening - sum((number(r.get('principal_amount'), 'Principal') for r in prefix), Decimal(0))
    if balance <= 0:
        raise ValueError('There is no remaining principal to schedule.')
    money(annual)  # Reject numeric magnitudes that cannot fit currency calculations.
    n = len(dates)
    period_rate = annual / 100 * Decimal(months) / 12
    principal_share = money(balance / n)
    try:
        if method == 'Equal Installments' and basis == 'Diminishing' and period_rate:
            payment = money(balance * period_rate / (1 - (1 + period_rate) ** -n))
        else:
            payment = money(balance / n)
    except (InvalidOperation, Overflow, ZeroDivisionError):
        raise ValueError('The rate and term cannot produce a valid schedule.')
    if method != 'Interest Only / Balloon' and payment <= 0:
        raise ValueError('The principal is too small for this number of installments at currency precision.')
    rows = list(prefix)
    for index, due in enumerate(dates):
        interest = money((original if basis == 'Flat Rate' else balance) * period_rate)
        if index == n - 1:
            principal = balance
        elif method == 'Interest Only / Balloon':
            principal = Decimal(0)
        elif method == 'Equal Installments' and basis == 'Diminishing':
            principal = money(payment - interest)
        else:
            principal = principal_share
        if method != 'Interest Only / Balloon' and principal <= 0:
            raise ValueError('The installment does not repay principal at currency precision. Reduce the term or review the rate.')
        if principal > balance:
            raise ValueError('The term is too long for this balance at currency precision.')
        balance = money(balance - principal)
        previous_note = (future_rows[index].get('remarks') or '') if rate_change else ''
        note = 'Estimate: {0}; {1}; annual rate {2}%; {3}.'.format(basis, method, annual, loan.get('repayment_frequency'))
        charge = number(future_rows[index].get('charges_amount'), 'Charges') if rate_change else Decimal(0)
        rows.append(dict(due_date=due, principal_amount=principal, interest_amount=interest,
            charges_amount=charge, remarks=(previous_note + '\n' if previous_note else '') + note))
    candidate = dict(loan, schedule=rows)
    result = calculate_schedule(candidate, precision, complete=True)
    result['rows'] = [dict(row, **values) for row, values in zip(rows, result['rows'])]
    result['retained_rows'] = len(prefix)
    result['precision'] = precision
    return result
