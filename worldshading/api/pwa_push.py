import json
import frappe
from frappe.utils import now_datetime


@frappe.whitelist()
def get_vapid_public_key():
    return frappe.conf.get("vapid_public_key")


@frappe.whitelist()
def save_push_subscription(subscription):
    if not frappe.session.user or frappe.session.user == "Guest":
        frappe.throw("Login required.")

    if isinstance(subscription, str):
        subscription = json.loads(subscription)

    endpoint = subscription.get("endpoint")
    keys = subscription.get("keys") or {}

    if not endpoint:
        frappe.throw("Push endpoint missing.")

    if not keys.get("p256dh") or not keys.get("auth"):
        frappe.throw("Push keys missing.")

    existing = frappe.db.get_value(
        "PWA Push Subscription",
        {"endpoint": endpoint},
        "name"
    )

    data = {
        "user": frappe.session.user,
        "endpoint": endpoint,
        "p256dh_key": keys.get("p256dh"),
        "auth_key": keys.get("auth"),
        "enabled": 1,
        "last_seen": now_datetime()
    }

    if existing:
        doc = frappe.get_doc("PWA Push Subscription", existing)
        doc.update(data)
        doc.save(ignore_permissions=True)
    else:
        doc = frappe.get_doc({
            "doctype": "PWA Push Subscription",
            **data
        })
        doc.insert(ignore_permissions=True)

    frappe.db.commit()

    return {
        "success": True,
        "name": doc.name
    }