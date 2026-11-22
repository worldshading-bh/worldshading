"""Calendar-period schedule estimates. Pure calculations; no posting or saving."""
import calendar
import copy
from decimal import Decimal, InvalidOperation, Overflow, ROUND_HALF_UP, localcontext
from .rules import as_date, number, calculate_schedule

MONTHS = {'Monthly': 1, 'Quarterly': 3, 'Half-yearly': 6, 'Yearly': 12}
METHODS = ('Equal Principal', 'Equal Installments', 'Interest Only / Balloon')


def anchored_date(anchor, months):
    year, month = divmod(anchor.year * 12 + anchor.month - 1 + months, 12)
    month += 1
    return as_date('{0:04d}-{1:02d}-{2:02d}'.format(year, month,
        min(anchor.day, calendar.monthrange(year, month)[1]))).isoformat()


def installment_rate(balance, original, payment, periods, basis, unit):
    """Non-negative periodic estimate for regular end-period payments; no fees/balloon."""
    with localcontext() as context:
        context.prec = 50
        total_interest = payment * periods - balance
        if total_interest < -(unit * periods / 2):
            raise ValueError('The installment amount and count do not cover Opening Principal. Increase the amount or count.')
        if total_interest <= 0:
            return Decimal(0)  # A small zero-interest final rounding difference is shown separately.
        if basis == 'Flat Rate':
            return total_interest / (original * periods)
        low, high = Decimal(0), payment / balance
        for unused in range(200):
            rate = (low + high) / 2
            present_value = payment * (1 - (1 + rate) ** -periods) / rate
            if present_value > balance:
                low = rate
            else:
                high = rate
        return (low + high) / 2


def recorded_rate_schedule(loan, options, dates, precision, payment, money):
    """Apply the known rate to fixed cash payments, disclosing any final settlement."""
    handling = options.get('remaining_balance') or 'Add Final Settlement'
    if handling not in ('Add Final Settlement', 'Add to Last Installment'):
        raise ValueError('Choose Add Final Settlement or Add to Last Installment.')
    original = money(number(loan.get('original_principal'), 'Original Principal'))
    balance = money(number(loan.get('opening_principal'), 'Opening Principal'))
    annual = number(loan.get('annual_interest_rate'), 'Annual Interest Rate')
    months = MONTHS[loan['repayment_frequency']]
    rate = annual * Decimal(months) / 1200
    unit = Decimal(10) ** -precision
    rows = []
    note = 'Estimate: recorded annual rate {0}%; {1}; installment {2}; confirm bank settlement and charges.'.format(
        annual, loan['repayment_frequency'], payment)

    def interest_due():
        return money((original if loan.get('interest_calculation_basis') == 'Flat Rate' else balance) * rate)

    for due in dates:
        interest = interest_due()
        if payment < interest:
            raise ValueError('The installment is below the period interest. Use the bank schedule for unpaid interest or capitalisation.')
        principal = min(balance, money(payment - interest))
        rows.append(dict(due_date=due, principal_amount=principal, interest_amount=interest,
                         charges_amount=Decimal(0), remarks=note))
        balance = money(balance - principal)
        if balance == 0:
            rows[-1]['final_payment'] = True
            rows[-1]['remarks'] += ' Final payment; principal fully settled.'
            break
    regular_count = len(rows)
    settlement_added = False
    if balance:
        if balance <= unit * len(dates) or handling == 'Add to Last Installment':
            rows[-1]['principal_amount'] += balance
            rows[-1]['final_payment'] = True
            rows[-1]['remarks'] += ' Remaining principal {0} included in final installment.'.format(balance)
        else:
            if len(rows) >= 600:
                raise ValueError('A settlement would exceed 600 rows. Choose Add to Last Installment or reduce the regular installment count.')
            try:
                due = anchored_date(as_date(dates[0]), months * len(dates))
            except (ValueError, OverflowError):
                raise ValueError('The final settlement date is outside the supported calendar.')
            rows.append(dict(due_date=due, principal_amount=balance, interest_amount=interest_due(),
                charges_amount=Decimal(0), remarks=note + ' Additional final settlement, including the extra period interest.',
                settlement_row=True))
            settlement_added = True
    previous_maturity = as_date(loan['maturity_date']).isoformat()
    maturity = max(previous_maturity, rows[-1]['due_date'])
    result = calculate_schedule(dict(loan, schedule=rows, maturity_date=maturity), precision, complete=True)
    result['rows'] = [dict(row, **values) for row, values in zip(rows, result['rows'])]
    result.update(retained_rows=0, precision=precision, calculation_mode='Installment Amount',
        rate_source='Use Recorded Rate', recorded_annual_rate=annual, installment_amount=payment,
        requested_installments=len(dates), regular_installments=regular_count, settlement_added=settlement_added,
        final_payment_amount=result['rows'][-1]['total_amount'],
        final_payment_adjustment=Decimal(0) if settlement_added else result['rows'][-1]['total_amount'] - payment)
    if maturity > previous_maturity:
        result.update(maturity_date=maturity, previous_maturity_date=previous_maturity)
    return result


def generate_schedule(loan, options, precision, today):
    loan, options = copy.deepcopy(loan), dict(options)
    mode = options.get('calculation_mode') or 'Interest Rate'
    if mode not in ('Interest Rate', 'Installment Amount'):
        raise ValueError('Select Interest Rate or Installment Amount.')
    by_amount = mode == 'Installment Amount'
    rate_source = options.get('rate_source') or 'Estimate Rate'
    if by_amount and rate_source not in ('Estimate Rate', 'Use Recorded Rate'):
        raise ValueError('Choose Estimate Rate or Use Recorded Rate.')
    recorded = by_amount and rate_source == 'Use Recorded Rate'
    method = options.get('method')
    if method not in METHODS:
        raise ValueError('Select a repayment method.')
    basis = loan.get('interest_calculation_basis')
    zero_recorded = recorded and number(loan.get('annual_interest_rate'), 'Annual Interest Rate') == 0
    if basis not in ('Diminishing', 'Flat Rate') and not zero_recorded:
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
    if by_amount and (method != 'Equal Installments' or rate_change or loan.get('interest_rate_type') != 'Fixed'):
        raise ValueError('Installment Amount requires Fixed rate type and Equal Installments, without a future-rate update.')
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
    requested_payment = None
    if by_amount:
        requested_payment = money(number(options.get('installment_amount'), 'Installment Amount'))
        if requested_payment <= 0:
            raise ValueError('Enter a positive Installment Amount, excluding separate charges and balloon payments.')
        if recorded:
            return recorded_rate_schedule(loan, options, dates, precision, requested_payment, money)
        period_rate = installment_rate(balance, original, requested_payment, n, basis, unit)
        annual = period_rate * 1200 / Decimal(months)
        money(annual)
        try:
            display_rate = annual.quantize(Decimal('0.000001'), rounding=ROUND_HALF_UP)
        except InvalidOperation:
            raise ValueError('The implied rate is too large. Review the amount, principal and installment count.')
    principal_share = money(balance / n)
    try:
        if by_amount:
            payment = requested_payment
        elif method == 'Equal Installments' and basis == 'Diminishing' and period_rate:
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
            final_expected_interest = interest
            if by_amount:
                if balance > payment and balance - payment > unit * n / 2:
                    raise ValueError('This payment cannot reconcile at currency precision. Use the bank schedule or review the amount and term.')
                interest = max(Decimal(0), payment - balance)
                if abs(interest - final_expected_interest) > unit * n:
                    raise ValueError('Currency rounding materially changes final interest. Use the bank schedule or review the amount and term.')
        elif method == 'Interest Only / Balloon':
            principal = Decimal(0)
        elif by_amount or (method == 'Equal Installments' and basis == 'Diminishing'):
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
        if by_amount:
            note = 'Estimate: {0}; installment {1}; estimated nominal annual rate {2}%; {3}; regular periods, no separate fees/balloon. Recorded loan rate unchanged.'.format(basis, payment, display_rate, loan.get('repayment_frequency'))
            if index == n - 1:
                note += ' Final interest split rounding adjustment: {0}.'.format(interest - final_expected_interest)
        charge = number(future_rows[index].get('charges_amount'), 'Charges') if rate_change else Decimal(0)
        rows.append(dict(due_date=due, principal_amount=principal, interest_amount=interest,
            charges_amount=charge, remarks=(previous_note + '\n' if previous_note else '') + note))
    candidate = dict(loan, schedule=rows)
    result = calculate_schedule(candidate, precision, complete=True)
    result['rows'] = [dict(row, **values) for row, values in zip(rows, result['rows'])]
    result['retained_rows'] = len(prefix)
    result['precision'] = precision
    if by_amount:
        result.update(calculation_mode=mode, installment_amount=payment,
            estimated_annual_rate=display_rate,
            final_payment_adjustment=result['rows'][-1]['total_amount']-payment,
            final_interest_adjustment=result['rows'][-1]['interest_amount']-final_expected_interest)
    return result
