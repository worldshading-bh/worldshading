"""Small operational state; never stored on Item or its child configuration."""
import hashlib
import json
from datetime import timedelta
import frappe
from .domain import retry_delay

STATE='WS WooCommerce Sync State'
TABLE='`tabWS WooCommerce Sync State`'


def invalidate_verification(name):
    """Release state locks before HTTP; a crash/manual PUT cannot leave a valid cache."""
    if frappe.db.table_exists(STATE):
        frappe.db.sql('UPDATE '+TABLE+' SET last_verified=NULL WHERE name=%s',(name,))
        frappe.db.commit()


def payload_hash(mapping,payload):
    identity={key:mapping.get(key) for key in ['product_id','variation_id','sku','sale_uom','sync_stock','sync_price','clear_sale_price']}
    return hashlib.sha256(json.dumps([identity,payload],sort_keys=True,default=str).encode()).hexdigest()


class StateStore:
    def prepare(self,mappings):
        if not mappings:return {}
        names=[m['name'] for m in mappings]
        rows=frappe.get_all(STATE,filters={'name':['in',names]},fields=['*'])
        present={row.name for row in rows}
        missing=[row for row in mappings if row['name'] not in present]
        # Idle runs perform no marker writes. Release bootstrap locks before HTTP.
        for mapping in sorted(missing,key=lambda row:row['name']):
            frappe.db.sql('INSERT IGNORE INTO '+TABLE+''' (name,creation,modified,owner,modified_by,docstatus,idx,item_link,item_code,requested_version,synced_version,attempts)
                VALUES (%s,NOW(6),NOW(6),'Administrator','Administrator',0,0,%s,%s,0,0,0)''',
                (mapping['name'],mapping['name'],mapping['item_code']))
        if missing:
            frappe.db.commit()
            rows=frappe.get_all(STATE,filters={'name':['in',names]},fields=['*'])
        return {row.name:row for row in rows}

    def ack(self,name,version,digest,now,verified=True):
        fields={'synced_version':version,'last_payload_hash':digest,'attempts':0,'next_retry':None,'last_error':None}
        if verified:fields.update(last_verified=now,last_attempt=now)
        frappe.db.set_value(STATE,name,fields,update_modified=False)
        frappe.db.commit()

    def hold(self,name,version):
        frappe.db.sql('UPDATE '+TABLE+''' SET synced_version=%s,last_payload_hash=NULL,
            attempts=0,next_retry=NULL,last_error=NULL
            WHERE name=%s AND (COALESCE(last_payload_hash,'')<>'' OR synced_version<>%s
                OR attempts<>0 OR next_retry IS NOT NULL OR last_error IS NOT NULL)''',(version,name,version))
        frappe.db.commit()

    def fail(self,name,version,error,now):
        # A PUT may have succeeded before readback failed. Even if a newer
        # business event arrived, its target must be verified again.
        frappe.db.set_value(STATE,name,dict(last_attempt=now,last_verified=None),update_modified=False)
        row=frappe.db.get_value(STATE,name,['attempts','requested_version'],as_dict=True)
        if row and int(row.requested_version or 0)==version:
            attempts=int(row.attempts or 0)+1
            frappe.db.sql('UPDATE '+TABLE+''' SET attempts=%s,next_retry=%s,last_error=%s
                WHERE name=%s AND requested_version=%s''',
                (attempts,now+timedelta(seconds=retry_delay(attempts)),str(error)[:1000],name,version))
        frappe.db.commit()
