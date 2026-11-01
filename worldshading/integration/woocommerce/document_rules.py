"""Preserve Woo's charged total on connector-owned v12 Sales Orders."""
import frappe
from .common import ORDER


def preserve_woo_total(doc, method=None):
    source=doc.get('ws_woo_order_id')
    if not source:
        return
    importing=getattr(doc.flags,'ws_woo_import',False)
    if importing or frappe.db.get_value(ORDER,str(source),'sales_order')==doc.name:
        # v12 Sales Order has no disable_rounded_total field. Its native tax
        # calculator calls this method; scope the policy to this document only.
        doc.is_rounded_total_disabled=lambda: True
