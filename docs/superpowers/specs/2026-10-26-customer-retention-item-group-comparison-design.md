# Customer Retention Item Group and Comparison Year Design

## Intent

Extend the existing read-only prepared **Customer Retention Analysis** report so sales managers can analyze retention for one Item Group and compare the Analysis Year directly with any one of the prior five calendar years.

The report must answer questions such as: “Which customers reduced PVC 680 GSM purchases in 2026 compared with 2024?” without changing the existing multi-year context, prepared-report workflow, or Customer and invoice data.

## Approved Behavior

### Item Group scope

- Add an optional **Item Group** Link filter.
- With no Item Group, preserve the current customer-wide calculations.
- With an Item Group, calculate sales, invoice counts, minimum historical sales, retention status, decrease, importance, chart, summary, last invoice date, and inactivity using only Sales Invoice Items whose current Item master belongs to that exact Item Group.
- Group-specific sales use submitted `Sales Invoice Item.base_net_amount`; return items reduce sales.
- Group-specific invoice counts count distinct submitted non-return Sales Invoices containing the selected group.
- Group-specific Last Invoice Date is the latest submitted non-return invoice containing the selected group, up to the Analysis Year end.
- Preferred Item Group enrichment is scoped to the selected group, so Top Item Group 1 shows the selected group and its tooltip shows that group's net sales across the selected reporting years; Top Item Groups 2 and 3 remain blank. When no Item Group is selected, the existing top-three behavior remains unchanged.
- The first version matches the exact Item Group. It does not implicitly include descendant Item Groups.

### Comparison Year

- Add a required **Comparison Year** Select filter.
- Default to the calendar year immediately before Analysis Year.
- Allow any of the five years immediately before Analysis Year, independently of **Previous Years**.
- Example: Analysis Year 2026, Comparison Year 2021, and Previous Years 3 compares 2026 directly with 2021 while retaining the regular 2025, 2024, and 2023 history columns.
- Changing Analysis Year refreshes the five Comparison Year choices and resets an invalid selection to Analysis Year minus one.
- Completed Prepared Reports restore both Analysis Year and Comparison Year correctly.

## Main Comparison Semantics

The selected Comparison Year replaces the hard-coded immediately previous year for:

- Comparison Sales and Comparison Invoice Count.
- Change Amount, Change %, and Decrease Amount.
- Decreased, Increased, and Stable classification.
- The decrease component of Importance Score.
- **Comparison Sales** sorting.
- At-risk Comparison Sales summary.

Internal row field names such as `previous_sales` may remain for backward compatibility, but all visible labels and help text use “Comparison.”

The existing 45/45/10 Importance formula remains:

- 45% Average Historical Sales percentile rank.
- 45% Decrease Amount percentile rank against the selected Comparison Year.
- 10% Inactive Days percentile rank.

## Historical Context and Status Rules

**Previous Years** continues to control the ordinary annual history columns and Average Historical Sales. The Comparison Year does not replace or reorder those columns.

The relevant year set is the union of:

- Analysis Year.
- The years selected through Previous Years.
- Comparison Year.

Only those years contribute to report-period aggregates; an unselected year lying between Comparison Year and Analysis Year must not silently affect sales, invoice totals, or Item Group tooltip amounts.

Status classification uses the selected Comparison Year as its direct baseline while retaining multi-year context:

1. **New** — current sales are positive and every relevant historical year is zero or negative.
2. **Reactivated** — current sales are positive, Comparison Year sales are zero or negative, and another relevant historical year is positive.
3. **Lost** — current sales are zero or negative and any relevant historical year is positive.
4. **Decreased**, **Increased**, or **Stable** — current and Comparison Year sales are positive, using the existing ±20 percent thresholds.

Total Invoice Count and Minimum Historical Sales continue to use the ordinary Previous Years selection, preserving their existing meaning. The dedicated Comparison Invoice Count is available even when Comparison Year lies outside those history columns.

## Data Retrieval

The report remains a prepared Script Report and uses aggregate SQL because multi-year customer/item aggregation cannot be performed efficiently with one ORM call per customer.

- Without Item Group, retain the current Sales Invoice aggregate path.
- With Item Group, join Sales Invoice Item and current Item master, bind the selected Item Group, sum item `base_net_amount`, and count distinct qualifying invoices.
- Restrict aggregate contribution to the relevant year set with bound parameters.
- Use an Item Group-aware `exists` condition for Last Invoice Date to avoid duplicate invoice rows.
- Apply Customer, Customer Group, Territory, status, minimum sales, ranking, and Top Results in the same order as the current report.
- Do not add a DocType, cache table, migration, scheduler, or database write.

## UI and Prepared Reports

- Place Comparison Year beside Analysis Year and Item Group with the other scope filters.
- Include both values in the compact filter summary.
- Rename the Sort By option **Previous Sales** to **Comparison Sales** and update its tooltip.
- Label columns with actual years, for example `2026 Sales` and `2024 Comparison Sales`.
- Existing sticky columns, row highlighting, Item Group amount tooltips, summary chips, and chart remain intact.
- Previously generated Prepared Report artifacts remain historical snapshots. Users must Rebuild to apply new filters or calculations.

## Approaches Considered

1. **Filter customers by Item Group but retain overall customer sales.** This was the initial idea, but it cannot show whether purchasing of the selected group itself declined.
2. **Scope the full analysis to Item Group when selected — chosen.** This directly answers the manager's question and keeps blank-filter behavior unchanged.
3. **Build a separate Item Group retention report.** This would duplicate most filters, calculations, prepared-report behavior, and maintenance, so it is unnecessary.

For Comparison Year, an independent prior-five-year selector was chosen over limiting the selector to displayed Previous Years. This permits direct comparisons such as 2026 versus 2021 without forcing five extra history columns.

## Constraints and Non-goals

- ERPNext/Frappe v12 and Python 3.6 compatibility.
- Read-only behavior; no Customer, Item, Sales Invoice, Campaign Customer, accounting, stock, or workflow updates.
- Exact Item Group only; descendant expansion and multi-select groups are future enhancements.
- No annualization or prorating.
- No core ERPNext/Frappe changes.
- Preserve unrelated working-tree changes, including current Campaign Customer DocType metadata edits.
- Do not run Bench migrate, Bench tests, reload-doc, restart, backup/restore, or cache-clearing commands.

## Verification and Rollback

Use test-first isolated Python unit tests with mocked database calls, the existing Node client harness, JavaScript syntax checks, Python compilation where safe, JSON parsing, and `git diff --check`. Do not execute the report against the production database during implementation.

Risk is moderate: a wrong SQL join could multiply sales, a wrong year set could include unintended years, and stale labels could mislead exports. Tests must cover distinct invoice counts, returns, non-contiguous year selection, arbitrary comparison classification, prepared-filter restoration, and blank Item Group backward compatibility.

Rollback is a normal Git revert of the report-scoped changes. No data rollback or schema rollback is required.
