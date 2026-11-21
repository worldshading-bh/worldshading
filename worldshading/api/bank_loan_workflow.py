"""Scoped Bank Loan approval setup. Call setup_workflow explicitly on deployment."""
import frappe
from frappe import _
from frappe.model import display_fieldtypes, table_fields, numeric_fieldtypes
from frappe.utils import flt, getdate, get_datetime

MAKER = 'Maker - ACC (Workflow)'
CHECKER = 'Checker - ACC (Workflow)'
APPROVER = 'Approver - ACC (Workflow)'
STATUS = {'Draft': 'Inactive', 'Pending Loan - Chkr': 'Inactive',
          'Pending Loan - App': 'Inactive', 'Approved': 'Active', 'Closed': 'Closed'}


def workflow_definition():
    states = [('Draft', MAKER), ('Pending Loan - Chkr', CHECKER),
              ('Pending Loan - App', APPROVER), ('Approved', APPROVER), ('Closed', APPROVER)]
    transitions = [('Draft', 'Request Verification', 'Pending Loan - Chkr', MAKER),
                   ('Pending Loan - Chkr', 'Loan Verified', 'Pending Loan - App', CHECKER),
                   ('Pending Loan - Chkr', 'Request Correction', 'Draft', CHECKER),
                   ('Pending Loan - App', 'Approve', 'Approved', APPROVER),
                   ('Pending Loan - App', 'Request Correction', 'Draft', APPROVER),
                   ('Approved', 'Revise Future Schedule', 'Draft', APPROVER),
                   ('Approved', 'Close Loan', 'Closed', APPROVER)]
    return dict(doctype='Workflow', workflow_name='Bank Loan Approval', document_type='Bank Loan',
                is_active=1, workflow_state_field='workflow_state', send_email_alert=0,
                states=[dict(state=state, doc_status='0', allow_edit=role,
                             update_field='status', update_value=STATUS[state]) for state, role in states],
                transitions=[dict(state=state, action=action, next_state=target,
                                  allowed=role, allow_self_approval=1)
                             for state, action, target, role in transitions])


def setup_workflow():
    if frappe.db.exists('Workflow', 'Bank Loan Approval'):
        return
    if frappe.db.exists('Workflow', {'document_type': 'Bank Loan', 'is_active': 1}):
        frappe.throw(_('Review the existing Bank Loan workflow before installing Bank Loan Approval.'))
    for role in (MAKER, CHECKER, APPROVER):
        if not frappe.db.exists('Role', role):
            frappe.throw(_('Required accounts workflow role is missing: {0}').format(role))
    definition = workflow_definition()
    for row in definition['states']:
        if not frappe.db.exists('Workflow State', row['state']):
            frappe.get_doc(dict(doctype='Workflow State', workflow_state_name=row['state'],
                                style='Success' if row['state'] == 'Approved' else 'Warning')).insert()
    for row in definition['transitions']:
        if not frappe.db.exists('Workflow Action Master', row['action']):
            frappe.get_doc(dict(doctype='Workflow Action Master', workflow_action_name=row['action'])).insert()
    frappe.get_doc(definition).insert()


def _editable_details(doc):
    """Compare business fields consistently across browser and database values."""
    result = {}
    for field in doc.meta.fields:
        if field.fieldtype in display_fieldtypes or field.read_only or field.fieldname == 'workflow_state':
            continue
        value = doc.get(field.fieldname)
        if value and field.fieldtype == 'Date':
            value = getdate(value)
        elif value and field.fieldtype == 'Datetime':
            value = get_datetime(value)
        elif field.fieldtype in numeric_fieldtypes:
            value = flt(value)
        result[field.fieldname] = ([_editable_details(row) for row in (value or [])]
                                  if field.fieldtype in table_fields else value or None)
    return result


def validate_loan_workflow(doc, old):
    state = doc.get('workflow_state') or 'Draft'
    if state not in STATUS:
        frappe.throw(_('Invalid Bank Loan workflow state.'))
    if not old and state != 'Draft':
        frappe.throw(_('New Bank Loans must start in Draft.'))
    previous = (old.get('workflow_state') or 'Draft') if old else 'Draft'
    if previous == 'Draft':
        if frappe.session.user != 'Administrator' and MAKER not in frappe.get_roles():
            frappe.throw(_('Only the Accounts Maker can edit a Draft Bank Loan.'))
    elif _editable_details(doc) != _editable_details(old):
        frappe.throw(_('Return the Bank Loan to Draft before changing its details.'))
    doc.workflow_state = state
    doc.status = STATUS[state]
