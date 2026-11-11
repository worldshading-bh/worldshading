"""Read-only annual budget to future daily cash allocations."""
from calendar import month_name, monthrange
from datetime import date, timedelta
from decimal import Decimal, ROUND_DOWN
import frappe
from .engine import money, as_date, days


def daily_budget(annual, percentages, start, end):
    """Keep regular days equal; reconcile monthly rounding on the calendar last day."""
    annual = money(annual)
    if annual < 0:
        raise ValueError('Budget amounts cannot be negative.')
    total = sum((Decimal(str(v)) for v in percentages.values()), Decimal(0))
    if not total.is_finite() or total <= 0 or abs(total-100) > Decimal('.01') or any(Decimal(str(v)) < 0 for v in percentages.values()):
        raise ValueError('Budget distribution must total 100%.')
    for day in days(start, end):
        count = monthrange(day.year, day.month)[1]
        prior = sum((Decimal(str(percentages.get(m, 0))) for m in range(1, day.month)), Decimal(0))
        current = prior+Decimal(str(percentages.get(day.month, 0)))
        monthly = money(annual*current/total)-money(annual*prior/total)
        regular = money(monthly/count)
        # Tiny allowances must not produce a negative month-end adjustment.
        if regular*(count-1) > monthly:
            regular = (monthly/count).quantize(Decimal('.001'), rounding=ROUND_DOWN)
        amount = monthly-regular*(count-1) if day.day == count else regular
        if amount:
            yield day, amount


class Budgets(object):
    def __init__(self, source):
        self.source = source

    def collect(self):
        s = self.source
        if not frappe.has_permission('Budget', 'read'):
            s.warn('Budget read access missing; Budget Expenses are omitted.')
            return
        candidates = []
        fixed = getattr(s, '_future_fixed_expense_accounts', set())
        found = False
        covered_years = set()
        for doc in s.documents('Budget', {'docstatus': 1}):
            year = frappe.get_doc('Fiscal Year', doc.fiscal_year)
            year.check_permission('read')
            first, last = as_date(year.year_start_date), as_date(year.year_end_date)
            start, end = max(s.start+timedelta(days=1), first), min(s.end, last)
            if start > end:
                continue
            found = True
            if first.month != 1 or first.day != 1 or last != date(first.year, 12, 31):
                s.warn('{0}: non-calendar/short fiscal-year budget requires review; omitted.'.format(doc.name))
                continue
            percentages = {month: Decimal(100)/12 for month in range(1, 13)}
            if doc.monthly_distribution:
                distribution = frappe.get_doc('Monthly Distribution', doc.monthly_distribution)
                distribution.check_permission('read')
                percentages = {}
                invalid = distribution.fiscal_year != doc.fiscal_year
                for row in distribution.percentages:
                    try:
                        month = list(month_name).index(row.month)
                        percent = Decimal(str(row.percentage_allocation or 0))
                        if month < 1 or month in percentages or not percent.is_finite() or percent < 0:
                            raise ValueError()
                        percentages[month] = percent
                    except (ValueError, ArithmeticError):
                        invalid = True
                if invalid or abs(sum(percentages.values(), Decimal(0))-100) > Decimal('.01'):
                    s.warn('{0}: monthly distribution must total 100% with valid unique months; budget omitted.'.format(doc.name))
                    continue
            else:
                s.warn('{0}: no Monthly Distribution; annual budget spread evenly across 12 months.'.format(doc.name))
            covered_years.add(first.year)
            for row in doc.accounts:
                account = frappe.get_doc('Account', row.account)
                account.check_permission('read')
                if account.company != s.company or account.is_group or account.root_type != 'Expense':
                    s.warn('{0}: budget account {1} is not a company expense ledger; omitted.'.format(doc.name, row.account))
                    continue
                if row.account in fixed:
                    s.warn('{0}: budget account {1} also occurs in Fixed Expense; budget portion omitted to avoid duplication. Separate the budget accounts.'.format(doc.name, row.account))
                    continue
                if money(row.budget_amount) < 0:
                    s.warn('{0}: negative budget account amount omitted.'.format(doc.name))
                    continue
                if any(e.get('account') == row.account and e.get('doctype') == 'GL Payment' and e['date'] >= start for e in s.events):
                    s.warn('{0}: budget account {1} also has scheduled GL Payments; review overlapping cash assumptions. Budget is not automatically reduced by those payments.'.format(doc.name, row.account))
                candidates.append((doc, row, percentages, start, end))
        if not found:
            s.warn('No submitted Budget covers the forecast period; Budget Expenses are zero. Create/submit the company fiscal-year budgets and monthly distributions to include them.')
        if found:
            future = s.start+timedelta(days=1)
            required = set(range(future.year, s.end.year+1)) if future <= s.end else set()
            missing = required-covered_years
            if missing:
                s.warn('No usable submitted calendar-year Budget covers forecast years {0}; those budget allowances are omitted.'.format(', '.join(str(y) for y in sorted(missing))))
        # Cost-center/project budgets can overlap. Do not blindly sum different scopes.
        for doc, row, percentages, start, end in candidates:
            conflicts = [(d, r) for d, r, p, a, b in candidates if r.account == row.account
                         and max(start, a) <= min(end, b) and (d.name != doc.name or r is not row)
                         and (d.budget_against != doc.budget_against or self.overlapping_scope(doc, d))]
            if conflicts:
                s.warn('{0}: overlapping budget scopes for {1}; conflicting budget amounts omitted. Use non-overlapping budget scopes.'.format(doc.name, row.account))
                continue
            for day, amount in daily_budget(row.budget_amount, percentages, start, end):
                s.event(day, 'budget_expenses', amount, 'Budget', doc.name,
                        'Future daily budget; {0}; annual {1}; monthly {2}%; no past catch-up or actual-spend deduction'.format(
                            row.account, money(row.budget_amount), percentages.get(day.month, 0)), account=row.account)

    def overlapping_scope(self, first, second):
        if first.budget_against == 'Project':
            return first.project == second.project
        if first.cost_center == second.cost_center:
            return True
        a = frappe.db.get_value('Cost Center', first.cost_center, ['lft', 'rgt'], as_dict=1)
        b = frappe.db.get_value('Cost Center', second.cost_center, ['lft', 'rgt'], as_dict=1)
        return not a or not b or (a.lft <= b.lft <= a.rgt or b.lft <= a.lft <= b.rgt)
