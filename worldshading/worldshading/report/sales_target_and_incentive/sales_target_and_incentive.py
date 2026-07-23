import frappe
_ITEM_GROUP_CACHE = {}


# --------------------------------------------------
# Incentive Rate from Profit % (Excel-based)
# --------------------------------------------------
def get_incentive_rate_from_profit(profit_pct, incentive_class):
    if not profit_pct:
        return 0

    profit = profit_pct / 100
    base = 0.10

    divisor_map = {"A": 3, "B": 2.5, "C": 2}
    divisor = divisor_map.get(incentive_class, 3)

    return round((profit * base) / divisor, 6)


# --------------------------------------------------
# Expand Item Groups (include children)
# --------------------------------------------------
def get_all_item_groups(group_list):
    if not group_list:
        return []

    key = tuple(sorted(group_list))
    if key in _ITEM_GROUP_CACHE:
        return _ITEM_GROUP_CACHE[key]

    all_groups = set(group_list)
    queue = list(group_list)

    while queue:
        parent = queue.pop(0)
        children = frappe.get_all(
            "Item Group",
            filters={"parent_item_group": parent},
            fields=["name"]
        )
        for c in children:
            if c.name not in all_groups:
                all_groups.add(c.name)
                queue.append(c.name)

    result = list(all_groups)
    _ITEM_GROUP_CACHE[key] = result
    return result


# --------------------------------------------------
# Resolve Item Group Filter Mode
# --------------------------------------------------
def resolve_item_group_filter(selected_groups, filter_mode):
    expanded = get_all_item_groups(selected_groups)

    if not expanded:
        return None, None

    if filter_mode == "Include Only Selected Item Groups":
        return expanded, None

    return None, expanded


# --------------------------------------------------
# Effective Target %
# --------------------------------------------------
def get_effective_target_pct(base_target_pct, incentive_class):
    increment_map = {"A": 0, "B": 5, "C": 10}
    return base_target_pct + increment_map.get(incentive_class, 0)


# --------------------------------------------------
# Quarter-wise Sales
# --------------------------------------------------
def get_quarter_sales(year, selected_item_groups=None, filter_mode=None):
    result = {"Q1": 0, "Q2": 0, "Q3": 0, "Q4": 0}

    include_groups, exclude_groups = resolve_item_group_filter(
        selected_item_groups,
        filter_mode
    )

    conditions = []
    values = {"year": year}

    if include_groups:
        conditions.append("i.item_group IN %(include_groups)s")
        values["include_groups"] = tuple(include_groups)

    if exclude_groups:
        conditions.append("i.item_group NOT IN %(exclude_groups)s")
        values["exclude_groups"] = tuple(exclude_groups)

    where_clause = " AND ".join(conditions)
    if where_clause:
        where_clause = " AND " + where_clause

    rows = frappe.db.sql(
        f"""
        SELECT
            QUARTER(si.posting_date) AS qtr,
            SUM(sii.base_net_amount) AS amount
        FROM `tabSales Invoice Item` sii
        INNER JOIN `tabSales Invoice` si ON si.name = sii.parent
        INNER JOIN `tabItem` i ON i.name = sii.item_code
        WHERE
            si.docstatus = 1
            AND YEAR(si.posting_date) = %(year)s
            {where_clause}
        GROUP BY QUARTER(si.posting_date)
        """,
        values,
        as_dict=True
    )

    for r in rows:
        result[f"Q{r.qtr}"] = r.amount or 0

    return result


# --------------------------------------------------
# PROFIT POOL CALCULATION (HYBRID – VERSION 2)
# --------------------------------------------------
def get_profit_pool_profit_pct(company, year, selected_item_groups=None, filter_mode=None):
    from erpnext.accounts.report.gross_profit.gross_profit import GrossProfitGenerator
    from erpnext.accounts.report.financial_statements import get_period_list, get_data

    # --------------------------------------------------
    # 1️⃣ Gross Profit Engine (USED ONLY FOR GROUP BUYING)
    # --------------------------------------------------
    gp = GrossProfitGenerator(frappe._dict({
        "company": company,
        "from_date": f"{year}-01-01",
        "to_date": f"{year}-12-31",
        "group_by": "Item Group"
    }))

    include_groups, exclude_groups = resolve_item_group_filter(
        selected_item_groups,
        filter_mode
    )

    total_sales = 0
    excluded_sales = 0
    gp_excluded_buying = 0
    gp_included_buying = 0

    for row in gp.grouped_data:
        if not row.get("item_group"):
            continue

        # 🔹 Selling always from GP (unchanged)
        total_sales += row.base_amount or 0

        # 🔹 INCLUDE MODE
        if include_groups:
            if row.item_group in include_groups:
                gp_included_buying += row.buying_amount or 0
            else:
                excluded_sales += row.base_amount or 0
            continue

        # 🔹 EXCLUDE MODE
        if exclude_groups and row.item_group in exclude_groups:
            gp_excluded_buying += row.buying_amount or 0
            excluded_sales += row.base_amount or 0

    included_sales = total_sales - excluded_sales

    # --------------------------------------------------
    # 2️⃣ STOCK EXPENSES (AUTHORITATIVE BUYING COST)
    # --------------------------------------------------
    filters = frappe._dict({
        "company": company,
        "from_fiscal_year": year,
        "to_fiscal_year": year,
        "periodicity": "Yearly",
        "accumulated_values": False
    })

    period_list = get_period_list(year, year, "Yearly", False, company)

    expense = get_data(
        company,
        "Expense",
        "Debit",
        period_list,
        filters=filters,
        ignore_closing_entries=True,
        ignore_accumulated_values_for_fy=True
    )

    total_stock_expense = 0
    total_indirect_expense = 0

    for row in expense:
        if row.get("account") == "Stock Expenses - WS":
            total_stock_expense = row.get("total") or 0

        if row.get("account") == "Indirect Expenses - WS":
            total_indirect_expense = row.get("total") or 0

    # --------------------------------------------------
    # 3️⃣ FINAL BUYING COST (KEY FIX)
    # --------------------------------------------------
    if include_groups:
        final_buying_cost = gp_included_buying
    elif exclude_groups:
        final_buying_cost = total_stock_expense - gp_excluded_buying
    else:
        final_buying_cost = total_stock_expense

    if final_buying_cost < 0:
        frappe.throw(
            "Final buying cost became negative. "
            "Please verify item group selection and stock expenses."
        )

    # --------------------------------------------------
    # 4️⃣ INDIRECT EXPENSE ALLOCATION (UNCHANGED)
    # --------------------------------------------------
    indirect_per_bhd = total_indirect_expense / total_sales if total_sales else 0
    included_indirect_expense = included_sales * indirect_per_bhd

    # --------------------------------------------------
    # 5️⃣ FINAL PROFIT %
    # --------------------------------------------------
    net_profit = (
        included_sales
        - final_buying_cost
        - included_indirect_expense
    )

    profit_pct = (net_profit / included_sales) * 100 if included_sales else 0

    # --------------------------------------------------
    # 🔍 DEBUG POPUP (VERY IMPORTANT)
    # --------------------------------------------------
    frappe.msgprint(f"""
    <b>📊 Profit Pool Debug – {year}</b><br><br>

    <b>Total Sales</b><br>
    BHD {round(total_sales,3)}<br><br>

    <b>Included Sales</b><br>
    BHD {round(included_sales,3)}<br><br>

    <b>Total Stock Expenses</b><br>
    BHD {round(total_stock_expense,3)}<br><br>

    <b>GP Excluded Buying</b><br>
    BHD {round(gp_excluded_buying,3)}<br><br>

    <b>GP Included Buying</b><br>
    BHD {round(gp_included_buying,3)}<br><br>

    <b>Final Buying Cost Used</b><br>
    BHD {round(final_buying_cost,3)}<br><br>

    <b>Indirect Expense Allocated</b><br>
    BHD {round(included_indirect_expense,3)}<br><br>

    <b>Net Profit</b><br>
    BHD {round(net_profit,3)}<br><br>

    <b>Final Profit %</b><br>
    <b>{round(profit_pct,2)}%</b>
    """, title="Profit Pool Calculation")

    return round(profit_pct, 2)

# --------------------------------------------------
# Main Report
# --------------------------------------------------
def execute(filters=None):
    filters = filters or {}

    company = filters.get("company")
    reference_year = str(filters.get("reference_year"))
    target_pct = float(filters.get("target_increase_pct") or 0)

    manager_count = int(filters.get("sales_manager_headcount") or 1)
    salesman_count = int(filters.get("salesman_headcount") or 1)

    selected_groups = filters.get("exclude_item_groups")
    if isinstance(selected_groups, str):
        selected_groups = [g.strip() for g in selected_groups.split(",") if g.strip()]

    item_group_filter_mode = filters.get("item_group_filter_mode") or "Exclude Selected Item Groups"

    # 🔹 Calculated ONCE
    last_year_profit_pct = get_profit_pool_profit_pct(
        company,
        reference_year,
        selected_groups,
        item_group_filter_mode
    )

    quarter_sales = get_quarter_sales(
        int(reference_year),
        selected_groups,
        item_group_filter_mode
    )

    columns = get_columns()
    data = []

    # 🔥 LOOP ALL CLASSES
    for incentive_class in ["A", "B", "C"]:

        effective_target_pct = get_effective_target_pct(target_pct, incentive_class)

        incentive_rate_policy = filters.get("incentive_rate")

        if incentive_rate_policy:
            rate_doc = frappe.get_doc("Incentive Rate", incentive_rate_policy)
            incentive_rate = (rate_doc.incentive_rate or 0) / 100
        else:
            incentive_rate = get_incentive_rate_from_profit(
                last_year_profit_pct,
                incentive_class
            )


        class_rows = []

        for q in ["Q1", "Q2", "Q3", "Q4"]:
            sales = quarter_sales.get(q, 0)
            target = sales * (1 + effective_target_pct / 100)
            incentive = target * incentive_rate

            total_weight = manager_count * 2 + salesman_count
            manager_amt = incentive * (2 * manager_count / total_weight)
            team_amt = incentive - manager_amt

            row = {
                "class": incentive_class,
                "quarter": q,
                "last_year_sales": sales,
                "profit_pct": round(last_year_profit_pct, 2),
                "effective_target_pct": effective_target_pct,
                "new_target": target,
                "incentive_rate": round(incentive_rate * 100, 2),
                "manager_rate": round(manager_amt / incentive * 100, 2) if incentive else 0,
                "team_rate": round(team_amt / incentive * 100, 2) if incentive else 0,
                "incentive_amount": incentive,
                "manager_incentive": manager_amt,
                "team_incentive": team_amt,
                "per_manager": manager_amt / manager_count,
                "per_salesman": team_amt / salesman_count,
            }

            data.append(row)
            class_rows.append(row)

        # 🔸 TOTAL per class
        data.append({
            "class": incentive_class,
            "quarter": "<b>TOTAL</b>",
            "last_year_sales": sum(r["last_year_sales"] for r in class_rows),
            "profit_pct": round(last_year_profit_pct, 2),
            "effective_target_pct": round(effective_target_pct, 2),
            "new_target": sum(r["new_target"] for r in class_rows),
            "incentive_rate": round(incentive_rate * 100, 2),
            "manager_rate": class_rows[0]["manager_rate"] if class_rows else 0,
            "team_rate": class_rows[0]["team_rate"] if class_rows else 0,
            "incentive_amount": sum(r["incentive_amount"] for r in class_rows),
            "manager_incentive": sum(r["manager_incentive"] for r in class_rows),
            "team_incentive": sum(r["team_incentive"] for r in class_rows),
            "per_manager": sum(r["manager_incentive"] for r in class_rows) / manager_count,
            "per_salesman": sum(r["team_incentive"] for r in class_rows) / salesman_count,
        })

    return columns, data


# --------------------------------------------------
# Columns
# --------------------------------------------------
def get_columns():
    return [
        {"label": "Class", "fieldname": "class", "fieldtype": "Data", "width": 50},
        {"label": "Quarter", "fieldname": "quarter", "fieldtype": "Data", "width": 120},
        {"label": "Reference Year Sales(BHD)", "fieldname": "last_year_sales", "fieldtype": "Currency", "width": 180},
        {"label": "Profit %","fieldname": "profit_pct","fieldtype": "Float","precision": 2,"width": 120},
        {"label": "Effective Target(%)", "fieldname": "effective_target_pct", "fieldtype": "Float", "width": 150},
        {"label": "New Target (BHD)", "fieldname": "new_target", "fieldtype": "Currency", "width": 180},
        {"label": "Incentive Rate(%)", "fieldname": "incentive_rate", "fieldtype": "Float", "precision": 2,"width": 140},
        {"label": "Manager Incentive(%)", "fieldname": "manager_rate", "fieldtype": "Float", "width": 150},
        {"label": "Team Incentive(%)", "fieldname": "team_rate", "fieldtype": "Float", "width": 160},
        {"label": "Total Incentive Pool(BHD)", "fieldname": "incentive_amount", "fieldtype": "Currency", "width": 200},
        {"label": "Manager Incentive(BHD)", "fieldname": "manager_incentive", "fieldtype": "Currency", "width": 190},
        {"label": "Team Incentive(BHD)", "fieldname": "team_incentive", "fieldtype": "Currency", "width": 200},
        {"label": "Per Manager(BHD)", "fieldname": "per_manager", "fieldtype": "Currency", "width": 170},
        {"label": "Per Team Member(BHD)", "fieldname": "per_salesman", "fieldtype": "Currency", "width": 180},
    ]
