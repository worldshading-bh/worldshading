import contextlib
import json
import frappe
from .environment import require_site,validate_store

SETTINGS = 'WS WooCommerce Settings'
MAP = 'WS WooCommerce Item Link'
ORDER = 'WS WooCommerce Order'
LOG = 'WS WooCommerce Sync Log'


class LockBusy(ValueError):
    """Another connection owns this source record; retry later."""


def settings(require_enabled=True):
    require_site()
    doc = frappe.get_single(SETTINGS)
    validate_store(doc.store_url)
    if require_enabled and not doc.enabled:
        raise ValueError('World Shading WooCommerce connector is disabled')
    if frappe.db.get_single_value('Woocommerce Settings', 'enable_sync'):
        raise ValueError('Disable the legacy WooCommerce connector before using this connector')
    return doc


def manager_only(write=False):
    if 'System Manager' not in frappe.get_roles():
        frappe.throw('System Manager access is required', frappe.PermissionError)
    request=getattr(frappe.local,'request',None)
    if write and request is not None and request.method!='POST':
        frappe.throw('POST is required for connector changes',frappe.PermissionError)
    if write:start_operation()


def start_operation():
    """Entry-only boundary, before business writes; never call inside a lock.

    Frappe12 defaults to REPEATABLE READ. A settings read before GET_LOCK
    otherwise leaves the order lookup on an old snapshot after a lock wait.
    Connector operations already commit per order/product; do not wrap these
    entry points in a transaction containing unrelated uncommitted work.
    """
    frappe.db.commit()
    frappe.db.sql('SET SESSION TRANSACTION ISOLATION LEVEL READ COMMITTED')


@contextlib.contextmanager
def lock(key):
    name = 'ws_woo:' + str(key)
    acquired = frappe.db.sql('SELECT GET_LOCK(%s, 0)', (name,))[0][0]
    if not acquired:
        raise LockBusy('Another connector operation is already handling this record')
    try:
        yield
    finally:
        frappe.db.sql('SELECT RELEASE_LOCK(%s)', (name,))


def log(operation, reference, status, message, details=None, item_link=None):
    frappe.get_doc(dict(doctype=LOG, operation=operation, reference=str(reference), status=status,
                        message=str(message)[:1000], details=json.dumps(details or {}, default=str),item_link=item_link)).insert(ignore_permissions=True)


def mappings():
    from .item_links import all_mappings
    return all_mappings()
