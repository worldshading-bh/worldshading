"""Source reconciliation rules kept independent of Frappe for fixture testing."""
from decimal import Decimal
try:
    from .engine import money, as_date
except ImportError:  # standalone tests
    from engine import money, as_date


def paid_before(payment, cutoff):
    if int(payment.get('docstatus') or 0) != 1 or as_date(payment['posting_date']) > as_date(cutoff):
        return money(0)
    return money(payment.get('paid_amount'))


def supplier_amount(total, import_vat_in_total):
    return max(money(total)-money(import_vat_in_total), money(0))


def po_remaining(total, invoiced, advances, applied_advances):
    unbilled = max(money(total)-money(invoiced), money(0))
    unused_advance = max(money(advances)-money(applied_advances), money(0))
    return max(unbilled-unused_advance, money(0))


def base_outstanding(amount, party_currency, company_currency, conversion_rate):
    if party_currency == company_currency:
        return money(amount)
    if not conversion_rate or Decimal(str(conversion_rate)) <= 0:
        raise ValueError('Missing positive exchange rate.')
    return money(Decimal(str(amount))*Decimal(str(conversion_rate)))


def salary_estimate(rows, context, evaluate, fraction=Decimal(1)):
    context = dict(context)
    total = money(0)
    for row in rows:
        if row.get('condition') and not evaluate(row['condition'], context):
            continue
        amount = evaluate(row['formula'], context) if row.get('amount_based_on_formula') else row.get('amount', 0)
        amount = money(amount)
        if row.get('depends_on_payment_days'):
            amount = money(amount*fraction)
        if row.get('abbr'):
            context[row['abbr']] = float(amount)
        if row.get('statistical_component') or row.get('do_not_include_in_total'):
            continue
        total += -amount if row.get('parentfield') == 'deductions' else amount
    return money(total)


def supplier_outstanding(gross, outstanding, import_tax):
    # Document payments settle supplier cash first, not a proportional share of third-party VAT.
    paid = max(money(gross)-money(outstanding), money(0))
    return max(supplier_amount(gross, import_tax)-paid, money(0))


def arrival_residual(estimate, paid, planned):
    return max(money(estimate)-money(paid)-money(planned), money(0))


def advance_shares(amount, references, invoice_pos):
    eligible = [r for r in references if r['reference_name'] in invoice_pos]
    total = sum((money(r['allocated_amount']) for r in eligible), money(0))
    if not total:
        return {}
    result = {}
    for row in eligible:
        name = row['reference_name']
        result[name] = result.get(name, money(0)) + money(money(amount)*money(row['allocated_amount'])/total)
    return result


def journal_effect(rows, accounts):
    """Company-currency net outflow from the exact report liquidity pool."""
    return money(sum((money(r.get('credit'))-money(r.get('debit')) for r in rows
                      if r.get('account') in accounts), money(0)))


def journal_reference_allocations(rows, accounts):
    """Use explicit references only when outside-pool debits explain all cash.

    Complex offsetting credits are not a safe basis for guessing allocations.
    """
    cash = journal_effect(rows, accounts)
    if cash <= 0:
        return {}, False
    outside = [r for r in rows if r.get('account') not in accounts]
    credits = sum((max(money(r.get('credit'))-money(r.get('debit')), money(0)) for r in outside), money(0))
    if credits:
        return {}, True
    result = {}
    for r in outside:
        kind, name = r.get('reference_type'), r.get('reference_name')
        amount = max(money(r.get('debit'))-money(r.get('credit')), money(0))
        if name and kind in ('Purchase Invoice', 'Purchase Order', 'Payroll Entry') and amount:
            key = (kind, name)
            result[key] = result.get(key, money(0)) + amount
    if sum(result.values(), money(0)) > cash:
        return {}, True
    return result, False


REVIEW_SECTIONS = (
    ('pe_supplier', 'Supplier payments — PE prepared', 'Review the Payment Entry, allocation and payment date.'),
    ('pe_other', 'Other Payment Entries (PE)', 'Review the Payment Entry and its payment date.'),
    ('gl', 'GL Payments', 'Review the GL Payment, source link and payment date.'),
    ('jv', 'Journal Entries (JV)', 'Review the net cash movement, workflow, references and matching notes.'),
    ('supplier_due', 'Supplier / PO obligations — payment needs review', 'Verify outstanding balances and existing payments before preparing or linking a payment.'),
    ('fixed_due', 'Fixed-expense schedules — payment needs review', 'Verify each occurrence and link an existing GL Payment if already paid.'),
    ('payroll_due', 'Payroll — payment or matching needs review', 'Verify salary-period and Payroll Entry payment links; do not repay an already settled salary.'),
    ('vat_due', 'Quarterly VAT', 'Review unpaid VAT and settlement journals.'),
    ('other_due', 'Other obligations', 'Verify the source obligation and payment date.'),
)


def group_overdue_review(rows):
    buckets = {}
    for row in rows:
        kind, category = row.get('doctype'), row.get('category')
        if kind == 'Payment Entry':
            section = 'pe_supplier' if category == 'supplier_payments' or row.get('party_type') == 'Supplier' else 'pe_other'
        elif kind == 'GL Payment':
            section = 'gl'
        elif kind == 'Journal Entry':
            section = 'jv'
        elif kind in ('Purchase Invoice', 'Purchase Order'):
            section = 'supplier_due'
        elif kind == 'Fixed Expense':
            section = 'fixed_due'
        elif category in ('vat_settlement', 'quarterly_vat'):
            section = 'vat_due'
        elif category == 'payroll':
            section = 'payroll_due'
        else:
            section = 'other_due'
        buckets.setdefault(section, []).append(row)
    return [dict(id=key, title=title, action=action, items=buckets[key], count=len(buckets[key]),
                 total_amount=money(sum((money(r['amount']) for r in buckets[key]), money(0))))
            for key, title, action in REVIEW_SECTIONS if key in buckets]


def invoice_installments(schedule, total, outstanding):
    """Honor recorded term payments, then distribute unallocated paid cash FIFO.

    Aggregate outstanding is authoritative; stale term paid fields cannot erase debt.
    Returns dated residual rows and any outstanding not covered by those rows.
    """
    rows = [dict(r, amount=max(money(r['amount']), money(0))) for r in
            sorted(schedule, key=lambda r: as_date(r['date']))]
    # Some schedules are already reduced to the unpaid portion. Do not deduct
    # lifetime payments from that residual a second time.
    paid = min(max(money(total)-money(outstanding), money(0)),
               max(sum((r['amount'] for r in rows), money(0))-money(outstanding), money(0)))
    recorded = money(0)
    for row in rows:
        used = min(max(money(row.get('paid_amount')), money(0)), row['amount'], max(paid-recorded, money(0)))
        row['amount'] -= used
        recorded += used
    remaining_paid = paid-recorded
    for row in rows:
        used = min(row['amount'], remaining_paid)
        row['amount'] -= used
        remaining_paid -= used
    budget = max(money(outstanding), money(0))
    result = []
    for row in rows:
        row['amount'] = min(row['amount'], budget)
        budget -= row['amount']
        if row['amount']:
            result.append(row)
    return result, budget


def reserve_installment(schedule, amount, payment_name=None, payment_term=None):
    """Remove a planned payment from its explicit installment before FIFO fallback.

    Explicit term/link ambiguity leaves the schedule intact for caller review.
    """
    rows = [dict(r) for r in schedule]
    linked = [r for r in rows if payment_name and r.get('payment_entry') == payment_name]
    terms = [r for r in rows if payment_term and r.get('payment_term') == payment_term]
    if linked and payment_term:
        selected = [r for r in linked if r.get('payment_term') == payment_term]
        if len(selected) != 1:
            return rows, money(0), True
    elif linked:
        selected = linked
    elif payment_term:
        if len(terms) != 1:
            return rows, money(0), True
        selected = terms
    else:
        selected = rows
    budget = max(money(amount), money(0))
    for row in selected:
        used = min(row['amount'], budget)
        row['amount'] -= used
        budget -= used
    return [r for r in rows if r['amount']], money(amount)-budget, False
