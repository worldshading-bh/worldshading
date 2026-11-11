"""Cashflow Forecast Script Report for ERPNext/Frappe v12."""
import json
from datetime import timedelta
from decimal import Decimal
from html import escape

import frappe
from frappe import _
from frappe.utils import nowdate

from .engine import money, as_date, days, today_sales, build_forecast, summarize, monthly_rows, PAYMENTS
from .sources import Sources
from .scenarios import purchase_events
from .rules import group_overdue_review


def authorize(company):
    if frappe.session.user == 'Guest' or not set(frappe.get_roles()).intersection({'System Manager', 'Accounts Manager'}):
        frappe.throw(_('Cashflow Forecast requires Accounts Manager or System Manager access.'), frappe.PermissionError)
    if not company:
        frappe.throw(_('Select a Company.'))
    frappe.get_doc('Company', company).check_permission('read')
    if not frappe.has_permission('GL Entry', 'read'):
        frappe.throw(_('Read access to General Ledger is required.'), frappe.PermissionError)


def parse_list(value, label):
    if isinstance(value, str):
        try:
            value = json.loads(value or '[]')
        except (ValueError, TypeError):
            frappe.throw(_('{0} must be a valid list.').format(label))
    if value is None:
        return []
    if not isinstance(value, list):
        frappe.throw(_('{0} must be a list.').format(label))
    return value


ACCOUNT_SCOPE = 'parent-groups-v1'
ACCOUNT_PARENTS = ('Bank Accounts', 'Cash In Hand')


def resolve_accounts(company):
    """All descendant ledgers, including untyped/disabled balances; never a partial permission-filtered sum."""
    parents = frappe.get_all('Account', filters={'company': company, 'is_group': 1,
        'account_name': ['in', list(ACCOUNT_PARENTS)]}, fields=['name', 'account_name', 'lft', 'rgt'])
    names = set()
    for title in ACCOUNT_PARENTS:
        matches = [p for p in parents if p.account_name == title]
        if len(matches) != 1:
            frappe.throw(_('Expected exactly one {0} account group in {1}.').format(title, company))
        parent = matches[0]
        frappe.get_doc('Account', parent.name).check_permission('read')
        ledgers = frappe.get_all('Account', filters={'company': company, 'is_group': 0,
            'lft': ['>', parent.lft], 'rgt': ['<', parent.rgt]}, fields=['name'])
        for ledger in ledgers:
            account = frappe.get_doc('Account', ledger.name)
            account.check_permission('read')
            if account.company != company or account.is_group:
                frappe.throw(_('Account tree/company mismatch.'), frappe.PermissionError)
            names.add(ledger.name)
    if not names:
        frappe.throw(_('No ledger accounts were found under Bank Accounts and Cash In Hand.'))
    return sorted(names)


def validate(filters):
    filters = frappe._dict(filters or {})
    authorize(filters.company)
    start = as_date(nowdate())
    if filters.forecast_date and str(filters.forecast_date) != str(start):
        frappe.throw(_('This forecast date is no longer today. Open a new forecast to use current balances.'))
    try:
        end = as_date(filters.end_date)
        if end < start or (end-start).days > 730:
            raise ValueError('End date must be today or later, at most 730 days ahead.')
        for key in ('support_amount', 'minimum_reserve'):
            if money(filters.get(key)) < 0:
                raise ValueError('Support and reserve cannot be negative.')
        if money(filters.sales_adjustment) < -100:
            raise ValueError('Sales adjustment cannot be below -100%.')
        filters.manual_sales = int(filters.get("manual_sales") or 0)
        if filters.manual_sales not in (0, 1) or money(filters.get("average_daily_sales")) < 0:
            raise ValueError("Average Daily Sales must be nonnegative.")
        filters.pop('today_receipts',None)
        filters.include_overdue = int(filters.get('include_overdue') or 0)
        if filters.include_overdue not in (0, 1):
            raise ValueError('Include Overdue Commitments must be checked or unchecked.')
    except (ValueError, TypeError) as exc:
        frappe.throw(str(exc))
    accounts = resolve_accounts(filters.company)
    expenses = parse_list(filters.extra_expenses, 'Extra Expenses')
    if len(expenses) > 500:
        frappe.throw(_('Maximum 500 scenario expense rows.'))
    events = []
    for row in expenses:
        try:
            if not isinstance(row, dict):
                raise ValueError('Each extra expense must be a row.')
            due, amount = as_date(row.get('date')), money(row.get('amount'))
            description = str(row.get('description') or '').strip()
            if not start <= due <= end or amount < 0 or not description or len(description) > 500:
                raise ValueError('Each expense needs an in-range date, nonnegative amount and description (maximum 500 characters).')
            events.append(dict(date=due, category='extra_expenses', amount=amount, description=description))
        except (ValueError, TypeError) as exc:
            frappe.throw(str(exc))
    purchase = frappe.parse_json(filters.get('purchase_scenario')) if isinstance(filters.get('purchase_scenario'), str) else filters.get('purchase_scenario')
    try:
        template = None
        if isinstance(purchase, dict):
            if purchase.get('schema') == 4:
                items=purchase.get('purchases')
                if not isinstance(items,list):
                    raise ValueError('Invalid purchases.')
                if any(isinstance(item,dict) and int(item.get('international') or 0) for item in items):
                    template=get_company_import_rows(filters.company)
            elif purchase.get('schema') in (2, 3) and int((purchase.get('include_customs_vat') if purchase.get('schema') == 2 else purchase.get('international')) or 0):
                template = get_company_import_rows(filters.company)
            elif purchase.get('schema') not in (2, 3, 4) and int(purchase.get('international') or 0):
                template = get_purchase_template(filters.company, purchase.get('tax_template'))['rows']
        events.extend(purchase_events(purchase, start, end, template))
    except (ValueError, TypeError, ArithmeticError) as exc:
        frappe.throw(str(exc))
    return filters, start, end, accounts, events


@frappe.whitelist()
def get_purchase_template(company, template):
    authorize(company)
    if not template:
        frappe.throw(_('Select a purchase tax template.'))
    doc = frappe.get_doc('Purchase Taxes and Charges Template', template)
    doc.check_permission('read')
    if doc.company != company or doc.get('disabled'):
        frappe.throw(_('Select an enabled tax template for this company.'))
    keys = ('account_head', 'charge_type', 'rate', 'row_id', 'category', 'add_deduct_tax',
            'tax_amount', 'included_in_print_rate')
    rows = []
    for row in doc.taxes:
        account = frappe.get_doc('Account', row.account_head)
        account.check_permission('read')
        if account.company != company:
            frappe.throw(_('Tax template account company mismatch.'))
        rows.append({key: row.get(key) for key in keys})
    return dict(rows=rows)


def get_company_import_rows(company):
    # Company default is often local VAT; select the company's import rules instead.
    candidates = []
    for row in frappe.get_list('Purchase Taxes and Charges Template',
            filters={'company': company, 'disabled': 0}, fields=['name', 'is_default'], limit_page_length=0):
        doc = frappe.get_doc('Purchase Taxes and Charges Template', row.name)
        doc.check_permission('read')
        accounts = {tax.account_head for tax in doc.taxes}
        if {'Custom Duty - WS', 'Input VAT – Import - WS'}.issubset(accounts):
            candidates.append(row)
    defaults = [row for row in candidates if row.is_default]
    selected = defaults or candidates
    if len(selected) != 1:
        frappe.throw(_('Accounts must configure one enabled import purchase tax template for this company, or mark the intended import template as default.'))
    return get_purchase_template(company, selected[0].name)['rows']


@frappe.whitelist()
def preview_purchase(company, end_date, purchase):
    values = frappe.parse_json(purchase) if isinstance(purchase, str) else purchase
    filters, start, end, accounts, events = validate(dict(company=company, end_date=end_date, purchase_scenario=values))
    return dict(events=[dict(event, date=str(event['date']), amount=str(event['amount'])) for event in events])


@frappe.whitelist()
def get_accounts(company):
    authorize(company)
    names = [frappe._dict(name=name) for name in resolve_accounts(company)]
    result = []
    for item in names:
        amount = money(frappe.db.sql('''select coalesce(sum(debit-credit),0) from `tabGL Entry`
            where company=%s and account=%s and posting_date<=%s''', (company, item.name, nowdate()))[0][0])
        result.append(dict(value=item.name, label=item.name, description='{0:,.3f} company currency'.format(amount)))
    return result


def execute(filters=None):
    filters, start, end, accounts, extra = validate(filters)
    source = Sources(filters.company, accounts, start, end, int(filters.get('include_overdue', 0)))
    source.manual_daily_sales = money(filters.average_daily_sales) if filters.manual_sales else None
    source.collect()
    if not filters.include_overdue and getattr(source, 'overdue', []):
        frappe.throw(_('Unpaid overdue commitments require review. Update their source payment dates or complete the payments, then generate again; alternatively check Include Overdue Commitments to include them today.'))
    if source.actual_sales_today is None:
        frappe.throw(_('Sales Invoice read access is required to calculate today’s remaining sales.'))
    multiplier = 1 + money(filters.sales_adjustment)/100
    if filters.manual_sales:
        for day in days(start, end):
            gross = money(0) if str(day) in source.holidays else money(filters.average_daily_sales)
            if day==start:gross=today_sales(source.actual_sales_today,gross)['remaining']
            tax = money(gross * source.manual_vat_rate / (100 + source.manual_vat_rate))
            source.event(day, 'vat_accrual', tax, description='Sales VAT from manual daily sales')
    else:
        for day, tax in source.sales_tax.items():
            if as_date(day) == start:
                historical = source.historical.get(day, money(0))
                remaining=today_sales(source.actual_sales_today,money(historical*multiplier))['remaining']
                projected = money(remaining*tax/historical) if historical else money(0)
            else:
                projected = money(tax*multiplier)
            source.event(day, 'vat_accrual', projected, description='Output VAT projected from same-date historical invoice tax rows')
    return render_forecast(source, filters, start, end, accounts, extra)


def render_forecast(source, filters, start, end, accounts, extra):
    engine_options = dict(manual_daily_sales=money(filters.average_daily_sales) if filters.manual_sales else None,
                          holidays=getattr(source, 'holidays', []),actual_sales_today=source.actual_sales_today)
    rows = build_forecast(start, end, source.opening_balance, source.events+extra,
        source.historical, filters.sales_adjustment or 0, filters.support_amount or 0,
        filters.minimum_reserve or 0, filters.today_receipts or 0, source.vat_opening, **engine_options)
    proposed = [e for e in extra if e.get('scenario')]
    baseline = build_forecast(start, end, source.opening_balance,
        source.events+[e for e in extra if not e.get('scenario')], source.historical,
        filters.sales_adjustment or 0, filters.support_amount or 0, filters.minimum_reserve or 0,
        filters.today_receipts or 0, source.vat_opening, **engine_options) if proposed else rows
    for row, base in zip(rows, baseline):
        row['baseline_closing_cash'] = base['closing_cash']
        row['purchase_impact'] = row['closing_cash']-base['closing_cash']
    summary = summarize(rows, filters.minimum_reserve or 0)
    displayed = monthly_rows(rows) if filters.get('view') == 'Monthly' else rows
    for row in displayed:
        # Informational invoice total only: never feed this back into cash receipts.
        row['actual_sales_today'] = source.actual_sales_today if row['date'] == start else None
        row['scenario_supplier'] = any(e.get('scenario_kind') == 'supplier' for e in row['sources'])
        row['scenario_arrival'] = any(e.get('scenario_kind') == 'arrival' for e in row['sources'])
        row['available_above_reserve'] = row['closing_cash'] - money(filters.minimum_reserve or 0)
        row['currency'] = source.currency
        row['source_details'] = '\n'.join('{0}: {1:,.3f} | {2}{3}'.format(
            e['category'], money(e['amount']), e.get('description') or '',
            ' | {0} {1}'.format(e['doctype'], e['name']) if e.get('doctype') and e.get('name') else '')
            for e in row['sources'])
        if row['date']==start:
            row['source_details']='Sales today: actual {0:,.3f}; remaining forecast {1:,.3f}. Only remaining sales are added to cash.\n'.format(
                money(source.actual_sales_today),row['remaining_sales_today'])+row['source_details']
        # JSON-compatible values; retain plain-text source details for standard exports.
        row['sources'] = [{k: str(v) if isinstance(v, Decimal) else v for k, v in e.items()} for e in row['sources']]
    chart = {'data': {'labels': [r['date'].strftime('%d %b %Y') for r in rows],
        'datasets': [{'name': _('Closing Cash'), 'values': [float(r['closing_cash']) for r in rows]}],
        'yMarkers': [{'label': _('Zero Cash'), 'value': 0}]},
        'type': 'line', 'height': 200, 'colors': ['#2563eb'],
        'axisOptions': {'xIsSeries': True, 'xAxisMode': 'tick'}, 'lineOptions': {'hideDots': 1}}
    cards = [dict(label=_('Opening Available Cash'), value=float(rows[0]['opening_cash']), datatype='Currency', currency=source.currency),
             dict(label=_('Lowest Balance'), value=float(summary['lowest_balance']),
                  indicator='Red' if summary['lowest_balance'] < 0 else 'Blue', datatype='Currency', currency=source.currency),
             dict(label=_('Lowest Balance Date'), value=str(summary['lowest_date']), datatype='Date'),
             dict(label=_('First Shortfall'), value=str(summary['first_shortfall_date'] or _('None'))),
             dict(label=_('Ending Balance'), value=float(summary['ending_balance']), datatype='Currency', currency=source.currency),
             dict(label=_('Coverage'), value=_('Review warnings') if source.warnings else _('Available sources'))]
    cards.append(dict(label=_('Actual Sales Today (Reference)'), value=float(source.actual_sales_today) if source.actual_sales_today is not None else _('Unavailable'),
                      datatype='Currency' if source.actual_sales_today is not None else 'Data', currency=source.currency))
    if proposed:
        first_purchase = min(e['date'] for e in proposed)
        after = [r for r in rows if r['date'] >= first_purchase]
        base_after = [r for r in baseline if r['date'] >= first_purchase]
        check = summarize(after, filters.minimum_reserve or 0)
        status = _('Cash shortfall') if check['first_shortfall_date'] else (_('Below minimum reserve') if check['first_reserve_date'] else _('Within reserve through forecast end'))
        cards.extend([dict(label=_('Purchase Check'), value=status, indicator='Red' if check['first_shortfall_date'] or check['first_reserve_date'] else 'Blue'),
                      dict(label=_('Lowest Cash Without Purchase'), value=float(min(r['closing_cash'] for r in base_after)), datatype='Currency', currency=source.currency),
                      dict(label=_('Lowest Cash With Purchase'), value=float(check['lowest_balance']), datatype='Currency', currency=source.currency)])
    if money(filters.minimum_reserve):
        cards.append(dict(label=_('First Below Reserve'), value=str(summary['first_reserve_date'] or _('None'))))
    message = report_message(source, filters, extra)
    message += '<br>Budget Expenses are future-only cash estimates; no prior-day catch-up or actual-spend adjustment. Review overlap with scheduled payments. Purchase scenarios use company currency; international ETA taxes follow the selected template and recoverability requires review.'
    # V12's Prepared Report attachment keeps rows only, losing message/chart/cards.
    # Store immutable presentation context once, outside the exported columns.
    displayed[0]['_cashflow_context'] = dict(message=message, chart=chart,
        report_summary=cards, forecast_date=str(start), accounts=accounts, account_scope=ACCOUNT_SCOPE,
        opening_accounts=[dict(account=r['account'],amount=str(r['amount'])) for r in source.accounts_breakdown],
        support_amount=str(money(filters.support_amount)), sales_adjustment=str(money(filters.sales_adjustment)), minimum_reserve=str(money(filters.minimum_reserve)),
        today_policy='auto-v1', warnings=source.warnings, vat_policy='quarter-v4',
        manual_sales=bool(filters.manual_sales), average_daily_sales=str(money(filters.average_daily_sales)), holiday_list=getattr(source,'holiday_list',None),
        calculation_inputs=calculation_inputs(source), base_filters={k:v for k,v in filters.items() if k not in ('purchase_scenario','prepared_report_name')},
        vat_reconciliation=getattr(source,'vat_reconciliation',[]),
        vat_ledger_balance=str(getattr(source,'vat_ledger_balance',0)),
        payroll_policy='ledger-v1', payroll_reconciliation=getattr(source,'payroll_reconciliation',None),
        overdue_count=len(getattr(source, 'overdue', [])), journal_stats=getattr(source, 'journal_stats', {}), journal_policy='pending-v1')
    return columns(filters.get('view'), has_purchase=bool(proposed), minimum_reserve=filters.minimum_reserve), displayed, message, chart, cards, True


def report_message(source, filters, extra):
    amounts = '; '.join('{0}: {1:,.3f}'.format(r['account'], r['amount']) for r in source.accounts_breakdown)
    text = ['<b>Cashflow planning assumptions</b>',
        escape('Opening balances include posted ledger entries through {0}; support {1:,.3f}.'.format(source.start, money(filters.support_amount))),
        escape(amounts),
        escape('Today shows actual submitted sales plus the remaining forecast. Only remaining sales enter cash; actual posted cash and VAT are already in the opening balances.'),
        'Opening liquidity includes every ledger under Bank Accounts and Cash In Hand, including nested groups; all company commitments consume this pool.',
        'Payroll forecast: 28th monthly. Customs/import VAT: PO ETA. Quarterly net VAT: 25th of the following month; credits carry forward.',
        'Journal Entries use their net effect on the included account groups. Unlinked salary or expense matches require Accounts review.',
        'Temporary scenario inputs create no accounting transactions. A positive balance is subject to source coverage and assumptions.']
    if extra:
        text.append('<b>Scenario expenses</b><br>'+ '<br>'.join(escape('{0}: {1:,.3f} — {2}'.format(
            e['date'], e['amount'], e['description'])) for e in extra))
    if source.warnings:
        text.append('<div class="alert alert-warning"><b>Coverage / matching review</b><ul>'+''.join(
            '<li>{0}</li>'.format(escape(w)) for w in source.warnings)+'</ul></div>')
    return '<br>'.join(text)


def columns(view=None, detailed_view=False, has_purchase=False, minimum_reserve=0):
    result = [dict(fieldname='month' if view == 'Monthly' else 'date', label=_('Month') if view == 'Monthly' else _('Date'),
                   fieldtype='Data' if view == 'Monthly' else 'Date', width=110)]
    labels = [('opening_cash', 'Opening Cash'),
              ('expected_receipts', 'Expected Sales Receipts'),
              ('other_receipts', 'Other Incoming'), ('fixed_expenses', 'Fixed Expenses'), ('payroll', 'Payroll'),
              ('supplier_payments', 'Supplier Payments'), ('customs', 'Customs'), ('import_vat', 'Import VAT'),
              ('quarterly_vat', 'Quarterly VAT Settlement'), ('extra_expenses', 'Extra Expenses'),
              ('budget_expenses', 'Budget Expenses'), ('proposed_purchase', 'Proposed Purchase'),
              ('baseline_closing_cash', 'Closing Without Purchase'), ('purchase_impact', 'Purchase Impact'),
              ('other_payments', 'Other Scheduled Payments'),
              ('total_payments', 'Total Payments'), ('closing_cash', 'Closing Cash')]
    labels.append(('available_above_reserve', 'Cash Above Minimum Reserve'))
    result.extend(dict(fieldname=name, label=_(label), fieldtype='Currency', options='currency', precision=3, width=145,
                       hidden=(not has_purchase and name in ('proposed_purchase', 'baseline_closing_cash', 'purchase_impact'))
                              or (name == 'available_above_reserve' and not money(minimum_reserve))) for name, label in labels)
    result.extend([dict(fieldname='source_details', label=_('Source Details'), fieldtype='Data', width=200, hidden=0),
                   dict(fieldname='currency', label=_('Currency'), fieldtype='Link', options='Currency', hidden=1)])
    return result


@frappe.whitelist()
def get_prepared_filters(prepared_report_name):
    saved = frappe.get_doc('Prepared Report', prepared_report_name)
    if saved.report_name != 'Cashflow Forecast' or saved.status != 'Completed':
        frappe.throw(_('Select a completed Cashflow Forecast snapshot.'))
    if saved.owner != frappe.session.user and 'System Manager' not in frappe.get_roles():
        frappe.throw(_('You cannot open another user\'s cashflow scenario.'), frappe.PermissionError)
    saved.check_permission('read')
    filters = frappe.parse_json(saved.filters) if isinstance(saved.filters, str) else saved.filters
    if not isinstance(filters, dict):
        frappe.throw(_('Invalid prepared forecast filters.'))
    authorize(filters.get('company'))
    if filters.get('account_scope') == ACCOUNT_SCOPE:
        resolve_accounts(filters.get('company'))
    # Preserve access checks for historical snapshots created with manual selection.
    for account in parse_list(filters.get('accounts'), 'Accounts'):
        doc = frappe.get_doc('Account', account)
        doc.check_permission('read')
        if doc.company != filters.get('company'):
            frappe.throw(_('Prepared forecast account/company mismatch.'), frappe.PermissionError)
    return filters


@frappe.whitelist()
def get_overdue_commitments(filters):
    values = frappe.parse_json(filters) if isinstance(filters, str) else filters
    filters, start, end, accounts, extra = validate(values)
    if filters.include_overdue:
        return dict(items=[], include_overdue=True)
    source = Sources(filters.company, accounts, start, end, False).collect_commitments()
    grouped = {}
    for row in source.overdue:
        key = (str(row['date']), row.get('doctype') or '', row.get('name') or '', row['category'])
        if key not in grouped:
            grouped[key] = dict(row, date=str(row['date']), amount=money(0), related_documents=[], descriptions=[], review_notes=[])
        target = grouped[key]
        target['amount'] += money(row['amount'])
        description = row.get('description') or ''
        if description and description not in target['descriptions']:
            target['descriptions'].append(description)
        note = row.get('review_note') or ''
        if note and note not in target['review_notes']:
            target['review_notes'].append(note)
        related = list(row.get('related_documents') or [])
        if row.get('related_doctype') and row.get('related_name'):
            related.append(dict(doctype=row['related_doctype'], name=row['related_name']))
        for link in related:
            if link not in target['related_documents']:
                target['related_documents'].append(link)
    items = sorted(grouped.values(), key=lambda r: (r['date'], r.get('doctype') or '', r.get('name') or ''))
    for item in items:
        item['description'] = ' | '.join(item.pop('descriptions'))
        item['review_note'] = ' '.join(item.pop('review_notes'))
    return dict(items=items, groups=group_overdue_review(items), currency=source.currency,
                journal_stats=getattr(source, 'journal_stats', {}), include_overdue=False)


def calculation_inputs(source):
    """Immutable inputs for quick purchase checks; stored only inside protected snapshots."""
    keys = ('company','currency','opening_balance','events','historical','vat_opening','accounts_breakdown',
            'warnings','actual_sales_today','vat_reconciliation','vat_ledger_balance','overdue','journal_stats',
            'holidays','holiday_list','payroll_reconciliation')
    return {key:getattr(source,key,None) for key in keys}


@frappe.whitelist()
def recalculate_purchase(prepared_report_name, filters):
    """Reprice one purchase against authorized, unchanged prepared accounting inputs."""
    from .prepared_access import run
    saved = run('Cashflow Forecast', {'prepared_report_name':prepared_report_name})
    rows = saved.get('result') or []
    context = rows[0].get('_cashflow_context',{}) if rows else {}
    if context.get('vat_policy') != 'quarter-v4' or context.get('today_policy') != 'auto-v1' or not context.get('calculation_inputs'):
        frappe.throw('Rebuild this forecast once to enable quick purchase checks.')
    values = frappe.parse_json(filters) if isinstance(filters,str) else filters
    filters,start,end,accounts,extra = validate(values)
    base = context.get('base_filters') or {}
    ignored = {'purchase_scenario','prepared_report_name'}
    if {k:v for k,v in filters.items() if k not in ignored} != {k:v for k,v in base.items() if k not in ignored}:
        frappe.throw('Forecast filters have changed. Rebuild before checking a purchase.')
    if str(start)!=context.get('forecast_date'):
        frappe.throw('Open a new forecast for today before checking a purchase.')
    source = frappe._dict(context['calculation_inputs'])
    source.start = start
    source.opening_balance = money(source.opening_balance)
    source.actual_sales_today = money(source.actual_sales_today) if source.actual_sales_today is not None else None
    for row in source.accounts_breakdown:row['amount']=money(row['amount'])
    result = render_forecast(source,filters,start,end,accounts,extra)
    return dict(columns=result[0],result=result[1],message=result[2],chart=result[3],report_summary=result[4],
                skip_total_row=True,purchase_preview=True,prepared_report_name=prepared_report_name)
