import frappe
import json

@frappe.whitelist()
def create_incentive_plan_from_report(filters=None, rows=None):
    if not filters:
        frappe.throw("Missing filters")

    if isinstance(filters, str):
        filters = json.loads(filters)

    if isinstance(rows, str):
        rows = json.loads(rows)

    company = filters.get("company")
    reference_year = filters.get("reference_year")

    if not company or not reference_year:
        frappe.throw("Company and Reference Year are required")

    # --------------------------------------------------
    # 🔒 Duplicate protection
    # --------------------------------------------------
    # existing = frappe.get_all(
    #     "Incentive Plan",
    #     filters={
    #         "company": company,
    #         "reference_year": reference_year,
    #         "status": ["!=", "Cancelled"]
    #     },
    #     limit=1
    # )
    # if existing:
    #     frappe.throw(
    #         f"Incentive Plan already exists for {company} - {reference_year}"
    #     )

    # --------------------------------------------------
    # 🧾 Item Group snapshot
    # --------------------------------------------------
    selected_groups = filters.get("exclude_item_groups") or []
    selected_groups_text = ", ".join(selected_groups)
    # --------------------------------------------------
    # 📌 Extract global values from report rows
    # --------------------------------------------------
    profit_pct = 0
    manager_rate = 0
    team_rate = 0

    for row in rows or []:
        if row.get("quarter") in {"Q1", "Q2", "Q3", "Q4"}:
            profit_pct = row.get("profit_pct") or 0
            manager_rate = row.get("manager_rate") or 0
            team_rate = row.get("team_rate") or 0
            break

    # --------------------------------------------------
    # 📄 Create Incentive Plan (PARENT)
    # --------------------------------------------------
    doc = frappe.get_doc({
        "doctype": "Incentive Plan",
        "company": company,
        "reference_year": reference_year,

        "item_group_filter_mode": filters.get("item_group_filter_mode"),
        "selected_item_groups": selected_groups_text,

        "manager_headcount": filters.get("sales_manager_headcount"),
        "team_members_headcount": filters.get("salesman_headcount"),

        "base_target_percentage": filters.get("target_increase_pct"),

        # ✅ FIXED VALUES
        "profit_percentage_used": profit_pct,
        "manager_incentive_percentage": manager_rate,
        "team_incentive_percentage": team_rate,

        "status": "Generated"
    })

    # --------------------------------------------------
    # 📊 Populate Incentive Plan Quarter (CHILD)
    # --------------------------------------------------
    valid_quarters = {"Q1", "Q2", "Q3", "Q4"}
    valid_classes = {"A", "B", "C"}

    for row in rows or []:
        quarter = row.get("quarter")
        incentive_class = row.get("class")  # ✅ FIXED

        # Skip TOTAL rows
        if quarter not in valid_quarters:
            continue

        if incentive_class not in valid_classes:
            continue

        doc.append("quarterly_incentive", {
            "incentive_class": incentive_class,
            "quarter": quarter,

            "reference_year_sales": row.get("last_year_sales") or 0,
            "effective_target_percentage": row.get("effective_target_pct") or 0,
            "incentive_rate": row.get("incentive_rate") or 0,

            "target_amount": row.get("new_target") or 0,
            "total_incentive_pool": row.get("incentive_amount") or 0,

            "manager_incentive": row.get("manager_incentive") or 0,
            "team_incentive": row.get("team_incentive") or 0,

            "per_manager": row.get("per_manager") or 0,
            "per_team_member": row.get("per_salesman") or 0,
        })
        # --------------------------------------------------
    # 📊 Build Annual Totals from Quarterly Incentives
    # --------------------------------------------------
    annual_map = {}

    for q in doc.quarterly_incentive:
        cls = q.incentive_class

        if cls not in annual_map:
            annual_map[cls] = {
                "annual_target": 0,
                "annual_incentive": 0,
                "annual_manager_incentive": 0,
                "annual_team_member_incentive": 0,
            }

        annual_map[cls]["annual_target"] += q.target_amount or 0
        annual_map[cls]["annual_incentive"] += q.total_incentive_pool or 0
        annual_map[cls]["annual_manager_incentive"] += q.manager_incentive or 0
        annual_map[cls]["annual_team_member_incentive"] += q.team_incentive or 0

    # --------------------------------------------------
    # 🧾 Append Annual Total Child Table
    # --------------------------------------------------
    for cls, values in annual_map.items():
        doc.append("annual_total", {
            "incentive_class": cls,
            "annual_target": values["annual_target"],
            "annual_incentive": values["annual_incentive"],
            "annual_manager_incentive": values["annual_manager_incentive"],
            "annual_team_member_incentive": values["annual_team_member_incentive"],
        })

    # --------------------------------------------------
    # 💾 Save
    # --------------------------------------------------
    doc.insert(ignore_permissions=True)
    doc.submit()

    return {"name": doc.name}
