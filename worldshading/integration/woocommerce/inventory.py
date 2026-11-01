"""Explicit online stock pool; order routing retains one default warehouse."""
import frappe


def stock_warehouses(config):
    rows = getattr(config, 'stock_warehouses', None) or []
    names = [row.get('warehouse') for row in rows] if rows else [config.warehouse]
    if any(not name for name in names) or len(set(names)) != len(names):
        raise ValueError('Choose each online stock warehouse once; empty rows are not allowed')
    if config.warehouse not in names:
        raise ValueError('Include the Default Order Warehouse in Online Stock Warehouses')
    for name in names:
        row=frappe.db.get_value('Warehouse',name,['company','is_group','disabled'],as_dict=True)
        if not row or row.company!=config.company or row.is_group or row.disabled:
            raise ValueError('Choose an active leaf warehouse in the selected company: '+str(name))
    return names
