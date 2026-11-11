"""Protect Cashflow's saved financial snapshots on v12's cached API paths.

Other reports are delegated unchanged. V12 skips the report execute method for
cached results, so its normal authorization must also run on retrieval/export.
"""
import frappe
from frappe import _

from .cashflow_forecast import authorize, get_prepared_filters, resolve_accounts, get_overdue_commitments

REPORT = 'Cashflow Forecast'


def guard_request(report_name, filters=None, user=None):
    values = frappe.parse_json(filters) if isinstance(filters, str) else (filters or {})
    if not isinstance(values, dict):
        if report_name != REPORT:
            return False
        frappe.throw(_('Invalid report filters.'))
    name = values.get('prepared_report_name')
    saved_report = frappe.db.get_value('Prepared Report', name, 'report_name') if name else None
    if saved_report == REPORT and report_name != REPORT:
        frappe.throw(_('This snapshot belongs to Cashflow Forecast.'), frappe.PermissionError)
    if report_name != REPORT:
        return False
    if user and user != frappe.session.user:
        frappe.throw(_('Cashflow snapshots must use the current user.'), frappe.PermissionError)
    if name:
        get_prepared_filters(name)
    else:
        authorize(values.get('company'))
        resolve_accounts(values.get('company'))
    return True


def check_payroll_access(result):
    rows = result.get('result') or []
    context = rows[0].get('_cashflow_context', {}) if rows else {}
    if context.get('vat_policy') in ('quarter-v2', 'quarter-v4'):
        from .sources import TAX_ACCOUNTS
        for key in ('output', 'local', 'import'):
            frappe.get_doc('Account', TAX_ACCOUNTS[key]).check_permission('read')
    budget_names = {source.get('name') for row in result.get('result', []) for source in row.get('sources', [])
                    if source.get('doctype') == 'Budget' and source.get('name')}
    if budget_names:
        if not frappe.has_permission('Budget', 'read'):
            frappe.throw(_('Budget access has changed. Generate a new forecast with your current permissions.'), frappe.PermissionError)
        for name in budget_names:
            frappe.get_doc('Budget', name).check_permission('read')
    payroll_control=context.get('payroll_reconciliation') or {}
    sensitive = bool(payroll_control) or any(source.get('doctype') in ('Salary Structure Assignment', 'Salary Slip', 'Payroll Entry')
        for row in result.get('result', []) for source in row.get('sources', []))
    if sensitive and not (frappe.has_permission('Salary Structure Assignment', 'read')
                          and frappe.has_permission('Salary Slip', 'read')):
        frappe.throw(_('Payroll access has changed. Generate a new forecast with your current permissions.'), frappe.PermissionError)
    if payroll_control.get('account'):
        account=frappe.get_doc('Account',payroll_control['account'])
        account.check_permission('read')
        company=(context.get('calculation_inputs') or {}).get('company')
        if company and account.company!=company:
            frappe.throw(_('Payroll account/company mismatch.'),frappe.PermissionError)


@frappe.whitelist()
def run(report_name, filters=None, user=None, ignore_prepared_report=False, custom_columns=None):
    from frappe.desk.query_report import run as original
    cashflow = guard_request(report_name, filters, user)
    result = original(report_name, filters, user, ignore_prepared_report, custom_columns)
    if cashflow:
        if result.get('doc'):
            saved_filters = get_prepared_filters(result['doc'].name)
            # A ledger can move outside today's groups after the snapshot was generated.
            # Recheck actual snapshot accounts, not just the current tree membership.
            rows = result.get('result') or []
            context = rows[0].get('_cashflow_context', {}) if rows else {}
            for name in context.get('accounts', []):
                account = frappe.get_doc('Account', name)
                account.check_permission('read')
                if account.company != saved_filters.get('company'):
                    frappe.throw(_('Prepared forecast account/company mismatch.'), frappe.PermissionError)
        check_payroll_access(result)
    return result


@frappe.whitelist()
def export_query():
    from frappe.desk.query_report import export_query as original
    args = frappe.local.form_dict
    if guard_request(args.get('report_name'), args.get('filters')):
        # Enforce cached-result permissions before the v12 exporter calls its
        # internal run function (which does not go through whitelist hooks).
        run(args.get('report_name'), args.get('filters'))
    return original()


@frappe.whitelist()
def download_attachment(dn):
    from frappe.core.doctype.prepared_report.prepared_report import download_attachment as original
    if frappe.db.get_value('Prepared Report', dn, 'report_name') == REPORT:
        run(REPORT, {'prepared_report_name': dn})
    return original(dn)


@frappe.whitelist()
def background_enqueue_run(report_name, filters=None, user=None):
    from frappe.desk.query_report import background_enqueue_run as original
    if guard_request(report_name, filters, user):
        review = get_overdue_commitments(filters)
        if review['items']:
            return dict(blocked=True, overdue_review=review)
    return original(report_name, filters, user)
