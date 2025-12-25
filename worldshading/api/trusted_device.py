import frappe
import hashlib
import uuid
from frappe.utils import now_datetime

@frappe.whitelist(allow_guest=True)
def register_trusted_device(customer, device_info, device_id=None, device_token=None):
    if not device_id:
        device_id = str(uuid.uuid4())

    if not device_token:
        device_token = frappe.generate_hash(length=64)

    token_hash = hashlib.sha256(device_token.encode()).hexdigest()

    existing = frappe.get_all(
        "Loyalty Trusted Device",
        filters={"device_id": device_id, "customer": customer},
        limit=1
    )

    if existing:
        doc = frappe.get_doc("Loyalty Trusted Device", existing[0].name)
        doc.db_set("last_seen", now_datetime())
        return {
            "device_id": device_id,
            "device_token": device_token
        }

    doc = frappe.get_doc({
        "doctype": "Loyalty Trusted Device",
        "customer": customer,
        "device_id": device_id,
        "token_hash": token_hash,
        "device_info": device_info,
        "last_seen": now_datetime(),
        "is_active": 1
    })
    doc.insert(ignore_permissions=True)

    return {
        "device_id": device_id,
        "device_token": device_token
    }
