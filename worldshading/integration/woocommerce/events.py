"""Post-commit wakeups; durable SQL revisions remain authoritative."""
import json
from uuid import uuid4
import frappe
from frappe.utils import now_datetime
from .common import SETTINGS,ORDER,settings,LockBusy
from .item_links import LINK,TABLE
from .environment import site_is_allowed

METHOD='worldshading.integration.woocommerce.events.drain'
LEASE_SECONDS=360


def automatic_enabled():
    return (site_is_allowed()
        and frappe.db.get_single_value(SETTINGS,'enabled')
        and frappe.db.get_single_value(SETTINGS,'automatic_sync'))


def warn():
    # Queue errors must never turn a completed business save into an error.
    try:frappe.logger().warning('Woo background notification unavailable; durable work awaits recovery',exc_info=True)
    except Exception:pass


def request_drain():
    """One notification after this transaction commits, with v12-safe failure isolation.

    v12's native enqueue_after_commit propagates Redis errors after SQL commit.
    Adapt only this request's DB instance, restoring its original method first.
    A callback surviving rollback cannot publish: drain checks committed work.
    """
    if getattr(frappe.flags,'ws_woo_draining',False) or getattr(frappe.flags,'ws_woo_commit_pending',False):return
    try:
        if not automatic_enabled():return
        original=frappe.db.commit
        def commit_and_notify(*args,**kwargs):
            frappe.db.commit=original
            frappe.flags.ws_woo_commit_pending=False
            result=original(*args,**kwargs)
            try:notify()
            except Exception:warn()
            return result
        frappe.db.commit=commit_and_notify
        frappe.flags.ws_woo_commit_pending=True
    except Exception:warn()


def pending_links():
    rows=frappe.db.sql('''SELECT s.name FROM `tabWS WooCommerce Sync State` s
        JOIN `tabWS WooCommerce Item Link` l ON l.name=s.item_link
        WHERE l.enabled=1 AND l.parenttype='Item' AND l.parentfield=%s
        AND (l.sync_stock=1 OR l.sync_price=1)
        AND (s.next_retry IS NULL OR s.next_retry<=%s)
        AND (s.requested_version>s.synced_version OR s.attempts>0
             OR (s.last_verified IS NULL AND s.last_payload_hash IS NOT NULL))''',(TABLE,now_datetime()))
    return {row[0] for row in rows}


def has_work():
    if pending_links():return True
    rows=frappe.db.sql('''SELECT name FROM `tabWS WooCommerce Order`
        WHERE status IN ('Pending','Failed','Needs Review') AND attempts<%s
        AND (next_retry IS NULL OR next_retry<=%s) LIMIT 1''',
        (frappe.db.get_single_value(SETTINGS,'max_attempts'),now_datetime()))
    return bool(rows)


def queue_connection():
    from frappe.utils.background_jobs import get_queue
    return get_queue('short').connection


def lease_key():
    return 'ws_woo:notification:'+frappe.local.site


def release(token):
    if token:
        # An expired worker must not delete a newer worker's lease.
        queue_connection().eval("if redis.call('get',KEYS[1]) == ARGV[1] then return redis.call('del',KEYS[1]) else return 0 end",1,lease_key(),token)


def notify():
    if not automatic_enabled() or not has_work():return
    token=uuid4().hex
    if not queue_connection().set(lease_key(),token,nx=True,ex=LEASE_SECONDS):return
    try:frappe.enqueue(METHOD,queue='short',timeout=300,token=token)
    except Exception:
        release(token)
        raise


def drain(token=None):
    successful=False
    previous=getattr(frappe.flags,'ws_woo_draining',False)
    frappe.flags.ws_woo_draining=True
    try:
        config=settings(False)
        if not config.enabled or not config.automatic_sync or not has_work():return
        frappe.set_user(config.integration_user)
        frappe.flags.mute_emails=True
        from .sync import run_cycle
        result=run_cycle(changes_only=True,pending_only=True)
        successful=True
        return result
    except LockBusy:
        return {'busy':True}
    finally:
        frappe.flags.ws_woo_draining=previous
        try:
            release(token)
            # Release before checking: concurrent arrivals either get their own
            # lease or are observed here. Errors/busy cycles await recovery.
            if successful:notify()
        except Exception:warn()


def order_changed(doc,method=None):
    """before_save: invalidate both old and new exposure, including hold release."""
    from .domain import affected_stock_items
    from .changes import mark_items
    if not site_is_allowed():return
    old=frappe.db.get_value(ORDER,doc.get('name'),['payload','sales_order','status'],as_dict=True) if doc.get('name') else None
    if old and all(old.get(key)==doc.get(key) for key in ('payload','sales_order','status')):return
    links=frappe.get_all(LINK,filters={'parenttype':'Item','parentfield':TABLE},fields=['parent','product_id','variation_id'])
    mappings=[dict(item_code=row.parent,product_id=row.product_id,variation_id=row.variation_id) for row in links]
    codes=set()
    for row in [doc]+([old] if old else []):
        try:codes.update(affected_stock_items(json.loads(row.get('payload') or '{}'),mappings))
        except (ValueError,TypeError,KeyError):codes.update(m['item_code'] for m in mappings)
        if row.get('sales_order'):
            codes.update(r.item_code for r in frappe.get_all('Sales Order Item',filters={'parent':row.get('sales_order'),'parenttype':'Sales Order'},fields=['item_code']))
    mark_items(codes,'stock')
    request_drain()
