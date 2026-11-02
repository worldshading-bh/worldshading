"""Native ten-minute recovery plus a compatible optional CLI entry point."""
import argparse
import json
from uuid import uuid4
import frappe
from .common import settings, lock, LockBusy
from .environment import site_is_allowed
from .events import queue_connection

METHOD = 'worldshading.integration.woocommerce.worker.recover'
TIMEOUT = 1500


def _lease_key():
    return 'ws_woo:recovery:' + frappe.local.site


def _release(token):
    if token:
        queue_connection().eval("if redis.call('get',KEYS[1]) == ARGV[1] then return redis.call('del',KEYS[1]) else return 0 end",1,_lease_key(),token)


def scheduled_recovery():
    """Small cron callback; remote work runs separately on the long queue."""
    if not site_is_allowed():return dict(skipped=True)
    config=settings(False)
    if not config.enabled or not config.automatic_sync:return dict(skipped=True)
    token=uuid4().hex
    if not queue_connection().set(_lease_key(),token,nx=True,ex=TIMEOUT+60):return dict(queued=False)
    try:
        frappe.enqueue(METHOD,queue='long',timeout=TIMEOUT,token=token)
    except Exception:
        _release(token)
        raise
    return dict(queued=True)


def recover(token=None):
    """Shared lock covers native jobs and legacy external recovery timers."""
    previous_user=getattr(getattr(frappe,'session',None),'user',None)
    previous_mute=getattr(frappe.flags,'mute_emails',False)
    try:
        if not site_is_allowed():return dict(skipped=True)
        config=settings(False)
        if not config.enabled or not config.automatic_sync:return dict(skipped=True)
        with lock('recovery'):
            frappe.set_user(config.integration_user)
            frappe.flags.mute_emails=True
            from .sync import run_cycle
            result=run_cycle(changes_only=True)
            from .bulk_linking import recover as recover_links
            try:result['item_linking']=recover_links(config)
            except Exception as exc:
                frappe.db.rollback()
                from .common import log
                log('Item linking','catalog','Failed',str(exc));frappe.db.commit()
                result['item_linking']=dict(error=str(exc))
            return result
    except LockBusy:
        return dict(busy=True)
    finally:
        frappe.flags.mute_emails=previous_mute
        if previous_user:frappe.set_user(previous_user)
        _release(token)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--site',required=True)
    parser.add_argument('--sites-path',default='.')
    args=parser.parse_args()
    frappe.init(site=args.site,sites_path=args.sites_path)
    frappe.connect()
    try:print(json.dumps(recover(),default=str))
    finally:frappe.destroy()


if __name__=='__main__':main()
