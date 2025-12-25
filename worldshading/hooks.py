# -*- coding: utf-8 -*-
from __future__ import unicode_literals
from . import __version__ as app_version

app_name = "worldshading"
app_title = "Worldshading"
app_publisher = "Hilal Habeeb"
app_description = "Custom developments"
app_icon = "octicon octicon-file-directory"
app_color = "grey"
app_email = "it.development@worldshading.com"
app_license = "MIT"

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/worldshading/css/worldshading.css"
# app_include_js = "/assets/worldshading/js/worldshading.js"




# include js, css files in header of web template
# web_include_css = "/assets/worldshading/css/worldshading.css"
# web_include_js = "/assets/worldshading/js/worldshading.js"

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
# doctype_js = {"doctype" : "public/js/doctype.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
#	"Role": "home_page"
# }

# Website user home page (by function)
# get_website_user_home_page = "worldshading.utils.get_home_page"

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# Installation
# ------------

# before_install = "worldshading.install.before_install"
# after_install = "worldshading.install.after_install"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "worldshading.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
# 	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# Document Events
# ---------------
# Hook on document methods and events

# doc_events = {
# 	"*": {
# 		"on_update": "method",
# 		"on_cancel": "method",
# 		"on_trash": "method"
#	}
# }

# Scheduled Tasks
# ---------------

# scheduler_events = {
# 	"all": [
# 		"worldshading.tasks.all"
# 	],
# 	"daily": [
# 		"worldshading.tasks.daily"
# 	],
# 	"hourly": [
# 		"worldshading.tasks.hourly"
# 	],
# 	"weekly": [
# 		"worldshading.tasks.weekly"
# 	]
# 	"monthly": [
# 		"worldshading.tasks.monthly"
# 	]
# }

# Testing
# -------

# before_tests = "worldshading.install.before_tests"

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "worldshading.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "worldshading.task.get_dashboard_data"
# }
app_include_css = "/assets/worldshading/css/custom_theme.css"

app_include_js = [
    "/assets/worldshading/js/customer_quick_entry.js",
    "/assets/worldshading/js/global_list_patch.js",
    "/assets/worldshading/js/notification_sound.js"
]



scheduler_events = {
    "daily": [
        "worldshading.custom_reorder.reorder_item",
        "worldshading.scheduler_events.insurance_reminders.create_insurance_todos",
        "worldshading.scheduler_events.draft_cleanup_schedule.execute",
        #"worldshading.scheduler_events.overdue_assignments.assign_overdue_sales_orders",
        "worldshading.scheduler_events.journal_entry_followups.auto_transition_jv"
    ],

    "cron": {
        "30 6 * * *": [  # every day at 6:30 AM
            "worldshading.scheduler_events.quotation_followups.auto_update_followups"
        ],
        "*/10 7-19 * * *":[
            "worldshading.integration.zkteco.attendance_sync.run"
        ]
    }
}



fixtures = [
    {
        "doctype": "DocType",
        "filters": [
            ["name", "in", [
                # Existing (do NOT remove)
                "Repack Production Rule",
                "Source Item",
                "Target Item",

                # New UI-created DocTypes (to protect)
                "Loyalty Trusted Device",
                "API Settings",
                "OTP Log"
            ]]
        ]
    }
]


doctype_js = {
    "Material Request": "public/js/material_request.js"

}



override_whitelisted_methods = {
    "worldshading.api.public_pdf.download_public_pdf": "worldshading.api.public_pdf.download_public_pdf",
    "worldshading.api.loyalty.get_loyalty_points": "worldshading.api.loyalty.get_loyalty_points",
    "worldshading.api.otp.send_otp": "worldshading.api.otp.send_otp",
    "worldshading.api.otp.verify_otp": "worldshading.api.otp.verify_otp",
    "worldshading.api.trusted_device.register_trusted_device": "worldshading.api.trusted_device.register_trusted_device",
}

doctype_list_js = {
    "Material Request": "public/js/material_request_list.js"
}


doc_events = {
    "*": {
        "on_cancel": "worldshading.events.cancel_assign.assign_to_gm_on_cancel"
    },
    "Material Request": {
        "before_submit": "worldshading.events.material_request_event.make_stock_qty_zero"
    },
    "Sales Order": {
        "validate": "worldshading.overrides.sales_order.validate",
        "after_save": "worldshading.overrides.sales_order.custom_after_save",
    },
    "Sales Invoice": {
        "on_update_after_submit": "worldshading.events.apply_credit_balance.apply_credit_simple"
    }
}



import frappe  

def override_status_updater():
    try:
        from erpnext.controllers import status_updater
        from worldshading.overrides.custom_status_updater import CustomStatusUpdater
        status_updater.StatusUpdater = CustomStatusUpdater
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Failed to override StatusUpdater")

override_status_updater()



#if migration failed bcs of pickling error, use this no-op function to let old pickles load and comment the patch below
# def override_packing_list(*args, **kwargs):
#     # no-op; exists only to let old pickles load once
#     return None



# Monkey patch make_packing_list
def override_packing_list():
    import erpnext.stock.doctype.packed_item.packed_item as original
    from worldshading.overrides.packed_item import make_packing_list
    original.make_packing_list = make_packing_list
    

override_packing_list()  # ✅ Call it directly at load time (not via doc_events)