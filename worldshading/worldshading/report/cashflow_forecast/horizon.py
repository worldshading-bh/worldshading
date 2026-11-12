"""Latest reconciled purchase payment date; no writes or forecast-day generation."""
from datetime import date
from .engine import as_date, money


def adjust_end_date(requested, start, minimum):
    requested, start = as_date(requested), as_date(start)
    minimum = as_date(minimum) if minimum else start
    end = max(requested, minimum)
    if end < start or (end-start).days > 730:
        raise ValueError('The last outstanding purchase payment or selected end date is beyond the supported 730-day forecast. Review its payment date before generating the report.')
    return end


def po_related(row, invoice_pos):
    references = [(row.get('doctype'), row.get('name')),
                  (row.get('related_doctype'), row.get('related_name'))]
    references += [(r.get('doctype'), r.get('name')) for r in row.get('related_documents', [])]
    return any(kind == 'Purchase Order' or (kind == 'Purchase Invoice' and invoice_pos.get(name))
               for kind, name in references)


def latest_supplier_payment(rows, invoice_pos, start):
    latest = None
    for row in rows:
        if row.get('category') != 'supplier_payments' or money(row.get('amount')) <= 0:
            continue
        if not po_related(row, invoice_pos) or as_date(row['date']) < as_date(start):
            continue
        if latest is None or as_date(row['date']) > latest['date']:
            latest = dict(date=as_date(row['date']), doctype=row.get('doctype'), name=row.get('name'))
    return latest


def minimum_purchase_end(company, accounts, start):
    import frappe
    from .sources import Sources
    for doctype in ('Purchase Order', 'Purchase Invoice', 'Payment Entry', 'Journal Entry'):
        if not frappe.has_permission(doctype, 'read'):
            frappe.throw('Read access to {0} is required to determine the last purchase payment date.'.format(doctype), frappe.PermissionError)
    # Reuse outstanding/advance/payment matching, but skip taxes, payroll, recurring
    # expenses and sales. Scan all payment dates so the 730-day guard cannot hide one.
    source = Sources(company, accounts, start, date.max, False)
    source._supplier_horizon_only = True
    source.supplier_invoices()
    source.purchase_orders()
    rows = list(source.events)
    invoice_pos = getattr(source, 'invoice_purchase_orders', {})
    # Submitted future payments already reduced PI/PO balances; active unmatched
    # prepared payments still represent cash in the regular forecast.
    for pe in source.pending_documents('Payment Entry'):
        if pe.payment_type != 'Pay' or money(pe.base_paid_amount) <= 0:
            continue
        if pe.docstatus == 0 and pe.get('workflow_state') in (None, '', 'Draft'):
            continue
        related = [dict(doctype=r.reference_doctype, name=r.reference_name)
                   for r in pe.references if money(r.allocated_amount) > 0]
        rows.append(dict(date=pe.posting_date, category='supplier_payments', amount=pe.base_paid_amount,
                         doctype='Payment Entry', name=pe.name, related_documents=related))
    journals = source.journals()
    journals.load()
    for info in journals.entries:
        if info['category'] == 'supplier_payments' and info['cash'] > 0:
            rows.append(dict(date=info['doc'].posting_date, category='supplier_payments', amount=info['cash'],
                             doctype='Journal Entry', name=info['doc'].name, related_documents=info['related']))
    return latest_supplier_payment(rows, invoice_pos, start)
