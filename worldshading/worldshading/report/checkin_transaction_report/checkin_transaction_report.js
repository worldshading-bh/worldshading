frappe.query_reports["Checkin Transaction Report"] = {
    "filters": [
      {
        "fieldname": "from_date",
        "label": "From Date",
        "fieldtype": "Date"
      },
      {
        "fieldname": "to_date",
        "label": "To Date",
        "fieldtype": "Date"
      },
      {
        "fieldname": "department",
        "label": "Department",
        "fieldtype": "Link",
        "options": "Department"
      },
      {
        "fieldname": "device_name",
        "label": "Device Name",
        "fieldtype": "Data"
      },
      {
        "fieldname": "employee",
        "label": "Employee",
        "fieldtype": "Link",
        "options": "Employee"
      }
    ]
  };
  