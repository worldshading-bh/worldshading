from __future__ import unicode_literals

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
    create_custom_fields({
        "WhatsApp Notification": [
            {
                "fieldname": "button_section",
                "label": "Dynamic URL Button",
                "fieldtype": "Section Break",
                "insert_after": "message_fields"
            },
            {
                "fieldname": "button_index",
                "label": "Button Index",
                "fieldtype": "Int",
                "read_only": 1,
                "insert_after": "button_section"
            },
            {
                "fieldname": "button_text",
                "label": "Button Text",
                "fieldtype": "Data",
                "read_only": 1,
                "insert_after": "button_index"
            },
            {
                "fieldname": "button_url",
                "label": "Button URL Template",
                "fieldtype": "Data",
                "read_only": 1,
                "insert_after": "button_text"
            },
            {
                "fieldname": "button_parameter_field",
                "label": "Button Parameter Document Field",
                "fieldtype": "Data",
                "description": "Field containing only the dynamic URL suffix, not the complete URL.",
                "insert_after": "button_url"
            }
        ]
    })

    # The previous database-only script registers the same button handlers. The
    # maintained asset replaces it after this patch installs its guard fields.
    for custom_script in frappe.get_all("Custom Script",
        filters={"dt": "WhatsApp Notification"}, fields=["name"]):
        frappe.db.set_value("Custom Script", custom_script.name, "script", "")
