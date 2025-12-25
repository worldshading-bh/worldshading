import frappe
from datetime import datetime

def execute(filters=None):
    if not filters:
        filters = {}

    from_date = filters.get("from_date")
    to_date = filters.get("to_date")

    # ---- Build SQL conditions dynamically ----
    conditions = []
    if from_date:
        conditions.append("DATE(time) >= %(from_date)s")
    if to_date:
        conditions.append("DATE(time) <= %(to_date)s")
    if filters.get("department"):
        conditions.append("department = %(department)s")
    if filters.get("device_name"):
        conditions.append("device_name = %(device_name)s")
    if filters.get("employee"):
        conditions.append("employee = %(employee)s")

    condition_sql = " AND ".join(conditions) if conditions else "1=1"

    # ---- Fetch and group punches ----
    records = frappe.db.sql(f"""
        SELECT
            employee,
            employee_name,
            department,
            device_name,
            DATE(time) AS punch_date,
            MIN(time) AS first_punch,
            MAX(time) AS last_punch,
            COUNT(*) AS total_punches
        FROM `tabEmployee Checkin`
        WHERE {condition_sql}
        GROUP BY employee, punch_date
        ORDER BY punch_date DESC, employee_name
    """, filters, as_dict=1)

    # ---- Process each day's summary ----
    for row in records:
        if row.first_punch and row.last_punch:
            t1 = datetime.strptime(str(row.first_punch), "%Y-%m-%d %H:%M:%S")
            t2 = datetime.strptime(str(row.last_punch), "%Y-%m-%d %H:%M:%S")
            delta = t2 - t1
            hours = delta.seconds // 3600
            minutes = (delta.seconds % 3600) // 60
            row.work_hours = f"{hours}:{minutes:02d}"

            # Format times to show only HH:MM AM/PM
            row.first_punch = t1.strftime("%I:%M %p").lstrip("0")
            row.last_punch = t2.strftime("%I:%M %p").lstrip("0")
        else:
            row.work_hours = "—"
            row.first_punch = ""
            row.last_punch = ""

        # simple remarks logic
        if row.work_hours != "—":
            h = int(row.work_hours.split(":")[0])
            row.remarks = "✅ Normal" if h >= 8 else "⚠️ Short Shift"
        else:
            row.remarks = "❌ No Punch"

    # ---- Column definitions ----
    columns = [
        {"label": "Date", "fieldname": "punch_date", "fieldtype": "Date", "width": 100},
        {"label": "Employee", "fieldname": "employee", "fieldtype": "Link", "options": "Employee", "width": 110},
        {"label": "Employee Name", "fieldname": "employee_name", "fieldtype": "Data", "width": 160},
        {"label": "Department", "fieldname": "department", "fieldtype": "Data", "width": 120},
        {"label": "Device Name", "fieldname": "device_name", "fieldtype": "Data", "width": 120},
        {"label": "First Punch", "fieldname": "first_punch", "fieldtype": "Data", "width": 100},
        {"label": "Last Punch", "fieldname": "last_punch", "fieldtype": "Data", "width": 100},
        {"label": "Total Punches", "fieldname": "total_punches", "fieldtype": "Int", "width": 110},
        {"label": "Work Hours", "fieldname": "work_hours", "fieldtype": "Data", "width": 100},
        {"label": "Remarks", "fieldname": "remarks", "fieldtype": "Data", "width": 120},
    ]

    return columns, records
