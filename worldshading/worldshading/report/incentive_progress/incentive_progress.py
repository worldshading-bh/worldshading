import frappe
from frappe.utils import nowdate


# --------------------------------------------------
# Expand Item Groups (include all children)
# --------------------------------------------------
def expand_item_groups(group_list):
    if not group_list:
        return []

    expanded = set(group_list)
    queue = list(group_list)

    while queue:
        parent = queue.pop(0)

        children = frappe.get_all(
            "Item Group",
            filters={"parent_item_group": parent},
            fields=["name"]
        )

        for c in children:
            if c.name not in expanded:
                expanded.add(c.name)
                queue.append(c.name)

    return list(expanded)


# --------------------------------------------------
# Build Item Group SQL condition
# --------------------------------------------------
def get_item_group_condition(filter_mode, selected_groups):
    if not selected_groups:
        return "", []

    placeholders = ", ".join(["%s"] * len(selected_groups))

    if filter_mode == "Exclude Selected Item Groups":
        return f"AND i.item_group NOT IN ({placeholders})", selected_groups

    if filter_mode == "Include Selected Item Groups":
        return f"AND i.item_group IN ({placeholders})", selected_groups

    return "", []


# --------------------------------------------------
# Main Report
# --------------------------------------------------
def execute(filters=None):
    filters = filters or {}

    incentive_plan = filters.get("incentive_plan")
    sales_person = filters.get("sales_person")

    if not incentive_plan or not sales_person:
        return get_columns(), []

    # --------------------------------------------------
    # Sales Person (role detection)
    # --------------------------------------------------
    sp = frappe.get_value(
        "Sales Person",
        sales_person,
        ["employee", "is_group"],
        as_dict=True
    )

    if not sp:
        return get_columns(), []

    is_manager = bool(sp.is_group)
    employee = sp.employee

    # --------------------------------------------------
    # Incentive Plan (incl. item group filters)
    # --------------------------------------------------
    plan = frappe.get_value(
        "Incentive Plan",
        incentive_plan,
        [
            "team_members_headcount",
            "item_group_filter_mode",
            "selected_item_groups"
        ],
        as_dict=True
    )

    team_count = plan.team_members_headcount or 1
    current_year = frappe.utils.nowdate()[:4]

    # --------------------------------------------------
    # Parse & expand item groups
    # --------------------------------------------------
    raw_groups = []
    if plan.selected_item_groups:
        raw_groups = [
            g.strip()
            for g in plan.selected_item_groups.split(",")
            if g.strip()
        ]

    expanded_groups = expand_item_groups(raw_groups)

    condition, group_params = get_item_group_condition(
        plan.item_group_filter_mode,
        expanded_groups
    )

    frappe.msgprint(
        f"[DEBUG] Incentive Plan Item Group Filter<br>"
        f"Mode: {plan.item_group_filter_mode or 'None'}<br>"
        f"Raw Groups: {', '.join(raw_groups) or 'None'}<br>"
        f"Expanded Groups: {', '.join(expanded_groups) or 'None'}"
    )

    # --------------------------------------------------
    # Incentive Plan Quarter rows
    # --------------------------------------------------
    rows = frappe.get_all(
        "Incentive Plan Quarter",
        filters={"parent": incentive_plan},
        fields=[
            "quarter",
            "incentive_class",
            "target_amount",
            "team_incentive",
            "manager_incentive"
        ]
    )

    plan_map = {}
    for r in rows:
        plan_map.setdefault(r.quarter, {})[r.incentive_class] = r

    data = []

    for quarter in ["Q1", "Q2", "Q3", "Q4"]:

        # --------------------------------------------------
        # Quarter dates
        # --------------------------------------------------
        if quarter == "Q1":
            from_date, to_date = f"{current_year}-01-01", f"{current_year}-03-31"
        elif quarter == "Q2":
            from_date, to_date = f"{current_year}-04-01", f"{current_year}-06-30"
        elif quarter == "Q3":
            from_date, to_date = f"{current_year}-07-01", f"{current_year}-09-30"
        else:
            from_date, to_date = f"{current_year}-10-01", f"{current_year}-12-31"

        if to_date > nowdate():
            to_date = nowdate()

        # --------------------------------------------------
        # SALES SOURCE (item-level, filtered)
        # --------------------------------------------------
        if is_manager:
            sales = frappe.db.sql(f"""
                SELECT SUM(sii.net_amount)
                FROM `tabSales Invoice` si
                JOIN `tabSales Invoice Item` sii ON sii.parent = si.name
                JOIN `tabItem` i ON i.name = sii.item_code
                WHERE si.docstatus = 1
                  AND si.posting_date BETWEEN %s AND %s
                  {condition}
            """, [from_date, to_date] + group_params)[0][0] or 0
        else:
            sales = frappe.db.sql(f"""
                SELECT SUM(sii.net_amount)
                FROM `tabSales Invoice` si
                JOIN `tabSales Invoice Item` sii ON sii.parent = si.name
                JOIN `tabItem` i ON i.name = sii.item_code
                WHERE si.docstatus = 1
                  AND si.pb_sales_employee = %s
                  AND si.posting_date BETWEEN %s AND %s
                  {condition}
            """, [employee, from_date, to_date] + group_params)[0][0] or 0

        frappe.msgprint(
            f"[DEBUG] {quarter} | Filtered Sales = {round(sales, 2)}"
        )

        q = plan_map.get(quarter, {})
        A = q.get("A")
        B = q.get("B")
        C = q.get("C")

        if not A:
            continue

        # --------------------------------------------------
        # TARGETS
        # --------------------------------------------------
        if is_manager:
            target_A = A.target_amount
            target_B = B.target_amount if B else target_A
            target_C = C.target_amount if C else target_B
        else:
            target_A = A.target_amount / team_count
            target_B = B.target_amount / team_count if B else target_A
            target_C = C.target_amount / team_count if C else target_B

        # --------------------------------------------------
        # RATE CALCULATION
        # --------------------------------------------------
        def get_rate(row, label):
            if not row:
                return 0

            incentive_pool = (
                row.manager_incentive if is_manager else row.team_incentive
            )

            rate = incentive_pool / row.target_amount if row.target_amount else 0

            frappe.msgprint(
                f"[DEBUG] {quarter} | Class {label} | "
                f"Target={round(row.target_amount,2)} | "
                f"Incentive={round(incentive_pool,2)} | "
                f"Rate={round(rate * 100,3)}%"
            )

            return rate

        rate_A = get_rate(A, "A")
        rate_B = get_rate(B, "B") if B else rate_A
        rate_C = get_rate(C, "C") if C else rate_B

        # --------------------------------------------------
        # SLABS
        # --------------------------------------------------
        if sales >= target_C:
            team_slab = "C"
            individual_class = "C"
        elif sales >= target_B:
            team_slab = "B"
            individual_class = "B"
        elif sales >= target_A:
            team_slab = "A"
            individual_class = "A"
        else:
            team_slab = "-"
            individual_class = "-"

        eligible = sales >= target_A

        # --------------------------------------------------
        # APPLIED RATE
        # --------------------------------------------------
        if team_slab == "C":
            applied_rate = rate_C if individual_class == "C" else rate_B if individual_class == "B" else rate_A
        elif team_slab == "B":
            applied_rate = rate_B if individual_class in ["B", "C"] else rate_A
        else:
            applied_rate = rate_A

        earned = sales * applied_rate

        frappe.msgprint(
            f"[DEBUG] {quarter} | "
            f"Sales={round(sales,2)} | "
            f"Team Slab={team_slab} | "
            f"Class={individual_class} | "
            f"Applied Rate={round(applied_rate*100,3)}% | "
            f"Eligible={'Yes' if eligible else 'No'} | "
            f"Incentive={round(earned,2)}"
        )

        # --------------------------------------------------
        # NEXT TARGET
        # --------------------------------------------------
        if individual_class == "C":
            next_class = "C (Max)"
            next_target = target_C
        elif individual_class == "B":
            next_class = "C"
            next_target = target_C
        elif individual_class == "A":
            next_class = "B"
            next_target = target_B
        else:
            next_class = "A"
            next_target = target_A

        # --------------------------------------------------
        # NEXT TARGET INCENTIVE (Projection)
        # --------------------------------------------------
        if next_class.startswith("C"):
            next_rate = rate_C
        elif next_class == "B":
            next_rate = rate_B
        else:
            next_rate = rate_A

        next_target_incentive = next_target * next_rate

        remaining = max(next_target - sales, 0)

        frappe.msgprint(
            f"[DEBUG] {quarter} | Next Class={next_class} | "
            f"Next Target={round(next_target,2)} | "
            f"Next Incentive={round(next_target_incentive,2)}"
        )


        data.append({
            "quarter": quarter,
            "role": "Manager" if is_manager else "Sales Executive",
            "current_sales": round(sales, 2),
            "individual_class": individual_class,
            "earned_incentive": round(earned, 2),
            "eligible": "Yes" if eligible else "No",
            "next_class": next_class,
            "next_target": round(next_target, 2),
            "next_target_incentive": round(next_target_incentive, 2),
            "remaining": round(remaining, 2)
        })


    return get_columns(), data


# --------------------------------------------------
# Columns
# --------------------------------------------------
def get_columns():
    return [
        {"label": "Quarter", "fieldname": "quarter", "width": 80},
        {"label": "Role", "fieldname": "role", "width": 130},
        {"label": "Current Sales", "fieldname": "current_sales", "fieldtype": "Currency", "width": 150},
        {"label": "My Class", "fieldname": "individual_class", "width": 110},
        {"label": "Next Class", "fieldname": "next_class", "width": 100},
        {"label": "Earned Incentive", "fieldname": "earned_incentive", "fieldtype": "Currency", "width": 150},
        {"label": "Next Target", "fieldname": "next_target", "fieldtype": "Currency", "width": 140},
        {"label": "Next Target Incentive", "fieldname": "next_target_incentive", "fieldtype": "Currency", "width": 160},
        {"label": "Remaining", "fieldname": "remaining", "fieldtype": "Currency", "width": 140},
    ]
