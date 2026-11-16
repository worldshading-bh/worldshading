"""Approval of the expense master, independent of GL Payment approval."""
import frappe
from frappe import _
from frappe.model import display_fieldtypes, table_fields, numeric_fieldtypes
from frappe.utils import flt, getdate, get_datetime


MAKER = 'Maker - ACC (Workflow)'
CHECKER = 'Checker - ACC (Workflow)'
APPROVER = 'Approver - ACC (Workflow)'
STATUS_BY_STATE = {'Draft': 'Inactive', 'Pending Expense - Chkr': 'Inactive',
                   'Pending Expense - App': 'Inactive', 'Approved': 'Active', 'Closed': 'Closed'}


def workflow_definition():
    states = [('Draft', MAKER), ('Pending Expense - Chkr', CHECKER),
              ('Pending Expense - App', APPROVER), ('Approved', APPROVER), ('Closed', APPROVER)]
    transitions = [('Draft', 'Request Verification', 'Pending Expense - Chkr', MAKER),
                   ('Pending Expense - Chkr', 'Expense Verified', 'Pending Expense - App', CHECKER),
                   ('Pending Expense - Chkr', 'Request Correction', 'Draft', CHECKER),
                   ('Pending Expense - App', 'Approve', 'Approved', APPROVER),
                   ('Pending Expense - App', 'Request Correction', 'Draft', APPROVER),
                   ('Approved', 'Request Editing', 'Draft', APPROVER),
                   ('Approved', 'Close Expense', 'Closed', APPROVER)]
    return dict(doctype='Workflow', workflow_name='Fixed Expense Approval',
                document_type='Fixed Expense', is_active=1, workflow_state_field='workflow_state',
                send_email_alert=0,
                states=[dict(state=state, doc_status='0', allow_edit=role,
                             update_field='status', update_value=STATUS_BY_STATE[state]) for state, role in states],
                transitions=[dict(state=state, action=action, next_state=target,
                                  allowed=role, allow_self_approval=1)
                             for state, action, target, role in transitions])


def setup_workflow():
    """Install once; never overwrite subsequent administrator workflow changes."""
    if frappe.db.exists('Workflow', 'Fixed Expense Approval'):
        return
    if frappe.db.exists('Workflow', {'document_type': 'Fixed Expense', 'is_active': 1}):
        frappe.throw(_('Review the existing Fixed Expense workflow before installing Fixed Expense Approval.'))
    definition = workflow_definition()
    for role in (MAKER, CHECKER, APPROVER):
        if not frappe.db.exists('Role', role):
            frappe.get_doc(dict(doctype='Role', role_name=role, desk_access=1)).insert()
    for row in definition['states']:
        if not frappe.db.exists('Workflow State', row['state']):
            frappe.get_doc(dict(doctype='Workflow State', workflow_state_name=row['state'],
                                style='Success' if row['state'] == 'Approved' else 'Warning')).insert()
    for row in definition['transitions']:
        if not frappe.db.exists('Workflow Action Master', row['action']):
            frappe.get_doc(dict(doctype='Workflow Action Master', workflow_action_name=row['action'])).insert()
    # Native Workflow setup initializes existing blank states to Draft.
    frappe.get_doc(definition).insert()


def require_approved_expense(source):
    if source.get('workflow_state') != 'Approved' or source.get('status') != 'Active':
        frappe.throw(_('Only Approved, Active Fixed Expenses can create GL Payments.'))


def set_workflow_status(doc):
    state = doc.get('workflow_state') or 'Draft'
    if state not in STATUS_BY_STATE:
        frappe.throw(_('Invalid Fixed Expense workflow state.'))
    doc.status = STATUS_BY_STATE[state]


def _editable_details(doc):
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


def validate_expense_workflow(doc, old=None):
    previous = old.get('workflow_state') if old else 'Draft'
    previous = previous or 'Draft'
    if not old and doc.get('workflow_state') not in (None, '', 'Draft'):
        frappe.throw(_('New Fixed Expenses must start in Draft.'))
    if previous == 'Draft':
        if frappe.session.user != 'Administrator' and MAKER not in frappe.get_roles():
            frappe.throw(_('Only the Accounts Maker can edit a Draft Fixed Expense.'))
    elif _editable_details(doc) != _editable_details(old):
        frappe.throw(_('Return the Fixed Expense to Draft before changing its details.'))
    # Frappe's native workflow validates the action and the user's transition role.
