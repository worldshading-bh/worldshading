"""Connector-only recovery timer; leaves existing ERP scheduling unchanged."""
import argparse
import json
import frappe


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--site',required=True)
    parser.add_argument('--sites-path',default='.')
    args=parser.parse_args()
    frappe.init(site=args.site,sites_path=args.sites_path)
    frappe.connect()
    try:
        from .common import settings
        config=settings(False)
        if not config.enabled:
            print('WooCommerce connector disabled');return
        if not config.automatic_sync:
            print('WooCommerce connector in manual mode; automatic sync skipped');return
        frappe.set_user(config.integration_user)
        frappe.flags.mute_emails=True
        from .sync import run_cycle
        result=run_cycle(changes_only=True)
        # Catalog matching is recovery-only, never in the immediate stock queue.
        # Failure here must not undo the order/stock cycle already completed.
        from .bulk_linking import recover
        try:result['item_linking']=recover(config)
        except Exception as exc:
            frappe.db.rollback()
            from .common import log
            log('Item linking','catalog','Failed',str(exc))
            frappe.db.commit()
            result['item_linking']=dict(error=str(exc))
        print(json.dumps(result,default=str))
    finally:
        frappe.destroy()


if __name__=='__main__':main()
