"""Read-only stock holds derived from unresolved orders; no Item writes."""
import json
import frappe
from .common import ORDER
from .domain import affected_stock_items
from .item_links import LINK, TABLE


def stock_holds():
    rows = frappe.get_all(ORDER, filters={'status': ['in', ['Pending', 'Failed', 'Needs Review']]},
                          fields=['name', 'payload', 'sales_order'])
    result = {'items': {}, 'all': [], 'review_required': len(rows)}
    if not rows:
        return result
    # Disabled mappings still identify stock exposure. Do not normalize UOMs here:
    # a broken conversion on one Item must not prevent reviewing other targets.
    links = frappe.get_all(LINK, filters={'parenttype': 'Item', 'parentfield': TABLE},
                           fields=['parent', 'product_id', 'variation_id'])
    mappings = [dict(item_code=row.parent, product_id=row.product_id, variation_id=row.variation_id) for row in links]
    for row in rows:
        try:
            items = affected_stock_items(json.loads(row.payload), mappings)
            if row.sales_order:
                old = frappe.get_all('Sales Order Item', filters={'parent': row.sales_order, 'parenttype': 'Sales Order'},
                                     fields=['item_code'])
                if not old or any(not entry.item_code for entry in old):
                    raise ValueError('Previous Sales Order Items cannot be identified')
                items.update(entry.item_code for entry in old)
            for item_code in items:
                result['items'].setdefault(item_code, []).append(row.name)
        except (ValueError, TypeError, KeyError):
            result['all'].append(row.name)
    return result


def stock_orders(item_code, holds):
    return sorted(set(holds['all'] + holds['items'].get(item_code, [])))
