from frappe import _


def get_data():
    return [
        {
            "label": _("Service"),
            "items": [
                {
                    "type": "doctype",
                    "name": "Service Visit",
                    "label": _("Service Visit"),
                },
                {
                    "type": "doctype",
                    "name": "Fixing Visit",
                    "label": _("Fixing Visit"),
                },
            ]
        },
        {
            "label": _("Reports"),
            "items": [
                {
                    "type": "report",
                    "name": "Checkin Transaction Report",
                    "label": _("Checkin Transaction Report"),
                    "is_query_report": True,
                },
                {
                    "type": "report",
                    "name": "Employee Service Visit Performance",
                    "label": _("Employee Service Visit Performance"),
                    "is_query_report": True,
                },
                {
                    "type": "report",
                    "name": "Incentive Progress",
                    "label": _("Incentive Progress"),
                    "is_query_report": True,
                },
                {
                    "type": "report",
                    "name": "Sales Target and Incentive",
                    "label": _("Sales Target and Incentive"),
                    "is_query_report": True,
                },
            ]
        },
    ]