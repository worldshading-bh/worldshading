"""Bank-statement schedule validation; no amortization or accounting writes."""
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


def number(value, label):
    try:
        result = Decimal(str(value if value not in (None, '') else 0))
    except (InvalidOperation, ValueError):
        raise ValueError('{0} must be a valid number.'.format(label))
    if not result.is_finite() or result < 0:
        raise ValueError('{0} must be finite and zero or greater.'.format(label))
    return result


def as_date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return datetime.strptime(str(value), '%Y-%m-%d').date()
    except ValueError:
        raise ValueError('Enter valid loan received, tracking, maturity and installment dates.')


def calculate_schedule(loan, precision, complete=False):
    unit = Decimal(10) ** -precision
    def money(value, label):
        try:
            return number(value, label).quantize(unit, rounding=ROUND_HALF_UP)
        except InvalidOperation:
            raise ValueError('{0} is too large.'.format(label))
    original = money(loan.get('original_principal'), 'Original Principal Amount')
    opening = money(loan.get('opening_principal'), 'Opening Principal')
    number(loan.get('annual_interest_rate'), 'Annual Interest Rate')
    if original <= 0 or opening <= 0 or opening > original:
        raise ValueError('Opening Principal must be positive and no greater than Original Principal Amount.')
    disbursed = as_date(loan.get('disbursement_date'))
    start = as_date(loan.get('tracking_start_date'))
    maturity = as_date(loan.get('maturity_date'))
    original_maturity = maturity
    if loan.get('approved_plan') and loan.get('workflow_state') == 'Draft' and loan.get('schedule'):
        maturity = max(maturity, max(as_date(row.get('due_date')) for row in loan['schedule']))
    if not disbursed <= start <= maturity:
        raise ValueError('Tracking Start Date must be between Loan Received Date and Maturity Date.')
    if loan.get('loan_position') == 'New Loan' and (opening != original or start != disbursed):
        raise ValueError('New loans must start tracking on Loan Received Date with Opening Principal equal to Original Principal Amount.')
    result = dict(rows=[], original_principal=original,
                  opening_principal=opening, scheduled_principal=Decimal(0), scheduled_interest=Decimal(0),
                  scheduled_charges=Decimal(0), scheduled_total=Decimal(0))
    if maturity != original_maturity:
        result['maturity_date'] = maturity.isoformat()
    previous = None
    balance = opening
    for index, row in enumerate(loan.get('schedule') or [], 1):
        due = as_date(row.get('due_date'))
        if due < start:
            raise ValueError('Installment {0}: due date cannot be before Tracking Start Date.'.format(index))
        if previous and due <= previous:
            raise ValueError('Installment {0}: choose a date after the previous installment ({1}).'.format(index, previous.isoformat()))
        if due > maturity:
            raise ValueError('Installment {0}: extend Maturity Date to {1} or later.'.format(index, due.isoformat()))
        previous = due
        principal = money(row.get('principal_amount'), 'Principal')
        interest = money(row.get('interest_amount'), 'Interest')
        charges = money(row.get('charges_amount'), 'Charges')
        total = principal + interest + charges
        balance -= principal
        if total <= 0 or balance < 0:
            raise ValueError('Installment {0}: total must be positive and principal cannot exceed the opening balance.'.format(index))
        result['rows'].append(dict(installment_number=index, principal_amount=principal,
                                   interest_amount=interest, charges_amount=charges, total_amount=total,
                                   projected_principal_balance=balance))
        for key, amount in [('principal', principal), ('interest', interest), ('charges', charges), ('total', total)]:
            result['scheduled_' + key] += amount
    result['unscheduled_principal'] = balance
    if complete and (not result['rows'] or balance != 0):
        raise ValueError('Complete the bank schedule: scheduled principal must equal Opening Principal before approval.')
    return result
