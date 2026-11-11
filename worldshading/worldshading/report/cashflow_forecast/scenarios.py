"""Purchase affordability scenario arithmetic; no accounting writes."""
from calendar import monthrange
from datetime import date, timedelta
from decimal import Decimal
from .engine import as_date, money, template_taxes, import_cash_taxes


def arrival_date(order, mode, eta=None, lead=0, unit='Days'):
    order = as_date(order)
    if mode == 'Date':
        result = as_date(eta)
    elif mode == 'Lead Time':
        numeric = Decimal(str(lead or 0))
        if not numeric.is_finite() or numeric < 0 or numeric != int(numeric) or numeric > 730:
            raise ValueError('Lead time must be a whole nonnegative number, maximum 730.')
        if unit == 'Days':
            result = order+timedelta(days=int(numeric))
        elif unit == 'Months':
            absolute = order.year*12+order.month-1+int(numeric)
            year, month = absolute//12, absolute % 12+1
            result = date(year,month,min(order.day,monthrange(year,month)[1]))
        else:
            raise ValueError('Lead-time unit must be Days or Months.')
    else:
        raise ValueError('Choose an ETA date or Lead Time.')
    if result < order:
        raise ValueError('ETA cannot precede the order date.')
    return result


def purchase_events(values, start, end, template_rows=None):
    if not values:
        return []
    if not isinstance(values, dict):
        raise ValueError('Purchase scenario must be an object.')
    if values.get('schema') == 4:
        purchases=values.get('purchases')
        if not isinstance(purchases,list) or len(purchases)>20:
            raise ValueError('Enter up to 20 purchases.')
        events=[]
        for index,purchase in enumerate(purchases,1):
            if not isinstance(purchase,dict):
                raise ValueError('Invalid purchase row.')
            payments=purchase.get('payments')
            if not isinstance(payments,list) or not payments or len(payments)>100 or any(not isinstance(row,dict) for row in payments):
                raise ValueError('Purchase {0}: enter between 1 and 100 supplier payments.'.format(index))
            total=sum((money(row.get('amount')) for row in payments),money(0))
            normalized=dict(description='Purchase {0}'.format(index),purchase_value=total,order_date=str(start),
                international=purchase.get('international'),eta_mode='Date',eta_date=purchase.get('eta_date'),payments=payments,charges=[])
            try:
                for event in purchase_events(normalized,start,end,template_rows):
                    event['purchase_number']=index
                    events.append(event)
            except (ValueError,TypeError,ArithmeticError) as exc:
                raise ValueError('Purchase {0}: {1}'.format(index,exc))
        return events
    if values.get('schema') == 3:
        split = int(values.get('split_payments') or 0)
        if split not in (0, 1):
            raise ValueError('Split Payments must be checked or unchecked.')
        values = dict(description='Proposed purchase', purchase_value=values.get('amount'),
                      order_date=str(start), international=values.get('international'),
                      eta_mode='Date', eta_date=values.get('eta_date'),
                      payments=values.get('payments') if split else [dict(date=values.get('date'), amount=values.get('amount'))], charges=[])
    if values.get('schema') == 2:
        include = int(values.get('include_customs_vat') or 0)
        if include not in (0, 1):
            raise ValueError('Include Customs and VAT must be checked or unchecked.')
        values = dict(description='Proposed purchase', purchase_value=values.get('amount'),
                      order_date=values.get('date'), international=include,
                      eta_mode='Lead Time', lead_time=values.get('interval'), lead_unit=values.get('interval_unit') or 'Days',
                      payments=[dict(date=values.get('date'), amount=values.get('amount'))], charges=[])
    start,end=as_date(start),as_date(end)
    description=str(values.get('description') or '').strip()
    value=money(values.get('purchase_value'))
    if not description or len(description)>500 or value<=0:
        raise ValueError('Purchase needs a description and a positive purchase value.')
    order=as_date(values.get('order_date'))
    if not start<=order<=end:
        raise ValueError('Purchase order date must be within the forecast period.')
    international=int(values.get('international') or 0)
    if international not in (0,1):
        raise ValueError('International must be checked or unchecked.')
    payments=values.get('payments') or []
    if not isinstance(payments,list) or not payments or len(payments)>100:
        raise ValueError('Enter between 1 and 100 supplier installments.')
    events=[]
    for row in payments:
        if not isinstance(row,dict):
            raise ValueError('Invalid supplier installment.')
        due,amount=as_date(row.get('date')),money(row.get('amount'))
        if not order<=due<=end or amount<=0:
            raise ValueError('Each supplier installment needs a positive amount and a date from order date through forecast end.')
        events.append(dict(date=due,category='proposed_purchase',amount=amount,
                           scenario=True,scenario_kind='supplier',description='Proposed purchase: '+description))
    if sum((r['amount'] for r in events),money(0))!=value:
        raise ValueError('Supplier installments must total the purchase value. Enter all installments and extend Forecast Until if necessary.')
    if not international:
        return events
    eta=arrival_date(order,values.get('eta_mode') or 'Date',values.get('eta_date'),values.get('lead_time'),values.get('lead_unit') or 'Days')
    if not start<=eta<=end:
        raise ValueError('ETA must be inside the forecast period; extend Forecast Until to include all import costs.')
    if not template_rows:
        raise ValueError('Select an import purchase tax template.')
    rows=[dict(r) for r in template_rows]
    charges=values.get('charges') or []
    if not isinstance(charges,list) or len(charges)>100:
        raise ValueError('Invalid estimated import charges.')
    actual={r['account_head'] for r in rows if r.get('charge_type')=='Actual'}
    amounts={}
    for row in charges:
        account=row.get('account')
        amount=money(row.get('amount'))
        if account not in actual or account in amounts or amount<0:
            raise ValueError('Import charges must use unique Actual-charge accounts from the selected template and nonnegative amounts.')
        amounts[account]=amount
    for row in rows:
        if row.get('included_in_print_rate') or row.get('add_deduct_tax')=='Deduct' or Decimal(str(row.get('rate') or 0))<0:
            raise ValueError('Purchase scenario requires an additive, tax-exclusive template.')
        if row.get('charge_type')=='Actual':
            row['tax_amount']=amounts.get(row['account_head'],money(0))
    taxes=import_cash_taxes(rows,template_taxes(value,rows))
    customs='Custom Duty - WS'
    import_vat='Input VAT – Import - WS'
    if not any(r.get('account_head')==import_vat for r in rows):
        raise ValueError('Selected international template must contain the mapped import VAT account.')
    for row,amount in zip(rows,taxes):
        if not amount:
            continue
        account=row.get('account_head')
        category='customs' if account==customs else ('import_vat' if account==import_vat else 'proposed_purchase')
        events.append(dict(date=eta,category=category,amount=amount,scenario=True,scenario_kind='arrival',
                           description='Proposed purchase ETA cost: {0}; {1}'.format(description,account),account=account))
        if account==import_vat:
            events.append(dict(date=eta,category='vat_accrual',amount=-amount,scenario=True,scenario_kind='arrival',
                               description='Proposed purchase recoverable import VAT estimate: '+description))
    return events
