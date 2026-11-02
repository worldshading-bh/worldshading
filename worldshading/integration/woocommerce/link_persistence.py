"""Persist connector configuration without invoking unrelated Item save hooks."""
import json
import frappe
from frappe.utils import get_datetime, now_datetime
from .item_links import TABLE, CONFIG_FIELDS, validate_item


def persist(item, row, expected_modified, before=None):
    """Caller owns target lock; SQL Item lock serializes sibling mapping edits.

    Native child validation still enforces manager/parent permissions. A Version
    records only the changed mapping. Images, names, prices and other children
    are never passed through Item.validate or written back to the database.
    The caller commits this together with its state marker/log, or rolls it back.
    """
    item.check_permission('write')
    stored=frappe.db.sql('SELECT modified FROM `tabItem` WHERE name=%s FOR UPDATE',(item.name,),as_dict=True)
    if not stored or not expected_modified or get_datetime(stored[0].modified)!=get_datetime(expected_modified):
        raise ValueError('The Item changed; reload it before saving this link')
    validate_item(item)
    row.set('parent',item.name);row.set('parenttype','Item');row.set('parentfield',TABLE)
    row.set('idx',next(i for i,r in enumerate(item.get(TABLE),1) if r is row))
    if before is None:
        row.insert(ignore_permissions=True)
        data=dict(added=[[TABLE,row.as_dict()]])
    else:
        row.save(ignore_permissions=True)
        changes=[[key,before.get(key),row.get(key)] for key in CONFIG_FIELDS if before.get(key)!=row.get(key)]
        data=dict(row_changed=[[TABLE,row.idx,row.name,changes]])
    changed=now_datetime()
    frappe.db.set_value('Item',item.name,dict(modified=changed,modified_by=frappe.session.user),update_modified=False)
    frappe.get_doc(dict(doctype='Version',ref_doctype='Item',docname=item.name,
                        data=json.dumps(data,default=str))).insert(ignore_permissions=True)
    item.set('modified',changed)
    frappe.clear_document_cache('Item',item.name)
    return str(changed)
