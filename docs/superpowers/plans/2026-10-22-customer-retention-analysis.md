# Customer Retention Analysis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a read-only prepared ERPNext v12 report that ranks Customers by importance, compares one to five complete calendar years, classifies retention status, and presents sales, activity, inactivity, preferred Item Groups, and permitted Campaign Customer context visually.

**Architecture:** A standard prepared Script Report in the `worldshading` app performs a fixed number of aggregate MariaDB queries, then applies pure Python classification, filtering, ranking, and summary functions. A v12-compatible report client supplies filters, visual indicators, sticky identity columns, prepared-filter restoration, and a safe partial-year notice without introducing a custom Page or stored analytics DocType.

**Tech Stack:** ERPNext 12, Frappe 12, Python 3.6, MariaDB, Frappe Script Report JSON/Python/JavaScript, Python `unittest` with mocks.

**Spec:** `docs/superpowers/specs/2026-10-22-customer-retention-analysis-design.md`

## Global Constraints

- Production environment: do not run `bench migrate`, `bench test`, `reload-doc`, report execution against the production site, restarts, backups, restores, or cache-clearing commands.
- Keep all product changes inside the five new Customer Retention Analysis report files in the `worldshading` custom app.
- Do not modify ERPNext or Frappe core files.
- Support ERPNext/Frappe v12 and Python 3.6; do not use type annotations, dataclasses, `frappe.qb`, or post-v12 APIs.
- The report is read-only and must never update Customer, Sales Invoice, Campaign Customer, Opportunity, workflow, stock, or accounting data.
- Calendar periods are always 1 January through 31 December; current-year results are not annualized or prorated.
- Use submitted Sales Invoice `base_net_total`; returns reduce sales, and return documents never increase purchase invoice counts or establish Last Invoice Date.
- Compare one to five previous years, use a fixed 20 percent status threshold, and default to the top 100 Customers by immediately previous-year sales.
- Use current `tabItem.item_group` for preferred Item Groups and show at most three positive-net groups.
- Preserve all unrelated working-tree changes and commit only task-scoped files.

## Review Focus

- A return-only Customer must retain negative sales value but have zero purchase invoice count and no Last Invoice Date; Task 3 tests all three outcomes.
- A Customer with no current or immediately previous-year sales but positive older selected-year sales must be Lost, not unclassified; Task 2 pins this rule.
- A current unfinished Analysis Year must compare with the previous complete year and show the partial-year notice rather than annualizing values; Tasks 1 and 5 test the server period and client notice.
- A zero Previous Sales denominator must never raise or emit an infinite percentage; New and Reactivated rows must have blank Change %, tested in Task 2.
- A user without Campaign Customer read permission must trigger no Campaign Customer query and receive blank campaign context, tested in Task 4.

---

## File Structure

- `worldshading/worldshading/report/customer_retention_analysis/__init__.py` — report package marker only.
- `worldshading/worldshading/report/customer_retention_analysis/customer_retention_analysis.json` — Report metadata, prepared-report setting, and allowed roles.
- `worldshading/worldshading/report/customer_retention_analysis/customer_retention_analysis.py` — filter validation, columns, aggregate data access, pure calculations, enrichment, summary/chart generation, and `execute()` orchestration.
- `worldshading/worldshading/report/customer_retention_analysis/customer_retention_analysis.js` — v12 filters, formatting, prepared-filter restoration, filter summary, partial-year warning, and sticky identity columns.
- `worldshading/worldshading/report/customer_retention_analysis/test_customer_retention_analysis.py` — isolated metadata, pure-function, mocked-query, orchestration, and JavaScript-contract tests; it must not connect to a site database.

### Task 1: Define Report Metadata, Filters, Periods, and Columns

**Files:**

- Create: `worldshading/worldshading/report/customer_retention_analysis/__init__.py`
- Create: `worldshading/worldshading/report/customer_retention_analysis/customer_retention_analysis.json`
- Create: `worldshading/worldshading/report/customer_retention_analysis/customer_retention_analysis.py`
- Create: `worldshading/worldshading/report/customer_retention_analysis/test_customer_retention_analysis.py`

**Interfaces:**

- Consumes: Frappe v12 `frappe._dict`, `frappe.throw`, `frappe.utils.cint`, `frappe.utils.flt`, `frappe.utils.getdate`, and `frappe.utils.today`.
- Produces: `normalize_filters(filters, current_year=None)`, `get_years(filters)`, `get_period_bounds(filters)`, `get_columns(filters, currency)`, and `_column(label, fieldname, fieldtype="Data", width=110, options=None)`.

- [ ] **Step 1: Write failing metadata and filter tests**

Add tests asserting:

- Report JSON is named `Customer Retention Analysis`, is a standard Worldshading Script Report for Sales Invoice, has `prepared_report = 1`, `disable_prepared_report = 0`, and `add_total_row = 0`.
- Roles are exactly Cashier, Sales Manager, General Manager, Accounts Manager, and System Manager.
- `normalize_filters()` applies defaults: current Analysis Year, one Previous Year, Top Results 100, Importance descending, and Minimum Historical Sales zero.
- It rejects missing Company, years below 2000 or above the supplied current year, Previous Years outside 1–5, negative Minimum Historical Sales, and unknown status/sort/direction/limit values through `frappe.throw`.
- Analysis Year 2026 with three previous years yields `[2026, 2025, 2024, 2023]` and bounds `2023-01-01` through `2026-12-31`; no logic truncates 2026 to today.
- Columns include actual year labels and dynamic `sales_2025`, `sales_2024`, and `sales_2023` Currency fields in newest-first order.

- [ ] **Step 2: Run the isolated test and verify failure**

Run from `apps/worldshading`:

```bash
../../env/bin/python -m unittest worldshading.worldshading.report.customer_retention_analysis.test_customer_retention_analysis
```

Expected: FAIL because the report package and interfaces do not exist. This direct unit command must not load a site or database.

- [ ] **Step 3: Create Report metadata and the package marker**

Create the approved JSON fields and roles. Use the existing Worldshading prepared Script Report JSON shape; do not add a custom DocType, scheduler, letterhead, or total row.

- [ ] **Step 4: Implement filter normalization and period helpers**

Implement the Task interfaces with controlled option maps:

- statuses: blank, Lost, Decreased, Stable, Increased, New, Reactivated;
- sorts: Importance, Decrease Amount, Current Sales, Previous Sales, Inactive Days, Current Invoice Count;
- directions: Descending, Ascending;
- limits: 20, 50, 100, 250, All.

Use calendar dates only and keep the selected Analysis Year end at 31 December even when that date is in the future.

- [ ] **Step 5: Implement static and dynamic columns**

Create the exact column order from the spec. Use a dynamic Company-currency `options` field on all Currency columns and year-specific labels such as `2026 Sales` and `2025 Sales`.

- [ ] **Step 6: Run the isolated test**

Run the Task 1 command.

Expected: PASS for metadata, defaults, validation, calendar bounds, and dynamic columns; no database calls occur.

- [ ] **Step 7: Commit metadata and filter contracts**

```bash
git add worldshading/worldshading/report/customer_retention_analysis
git commit -m "feat: define customer retention report"
```

### Task 2: Implement Pure Retention Calculations, Filtering, and Ranking

**Files:**

- Modify: `worldshading/worldshading/report/customer_retention_analysis/customer_retention_analysis.py`
- Modify: `worldshading/worldshading/report/customer_retention_analysis/test_customer_retention_analysis.py`

**Interfaces:**

- Consumes: normalized filters and aggregate dictionaries shaped as `{customer: {year: {"sales": number, "invoice_count": int}}}`.
- Produces: `classify_customer(year_values, analysis_year, previous_years)`, `build_customer_row(customer, customer_context, year_values, last_invoice_date, filters, as_of_date)`, `filter_sort_and_limit(rows, filters)`, and `get_sort_value(row, sort_by)`.

- [ ] **Step 1: Add failing status-classification tests**

Test exact cases for:

- Lost when current sales are zero and any selected prior year is positive, including the Review Focus case where only an older year is positive.
- Decreased at exactly -20 percent and Stable just above -20 percent.
- Increased at exactly +20 percent and Stable just below +20 percent.
- New when current sales are positive and all selected prior values are zero or negative.
- Reactivated when current is positive, immediately previous is zero, and an older selected year is positive.
- Change % is `None` for New and Reactivated zero-baseline rows.
- Negative current sales with historical positive sales is Lost.

- [ ] **Step 2: Add failing metric and ranking tests**

Assert that `build_customer_row()` calculates:

- current, previous, dynamic annual, change, decrease, average historical, and invoice-count values;
- Average Historical Sales across every selected previous year, including zero years;
- Inactive Days from `min(today, Analysis Year end)` and the full-history Last Invoice Date;
- blank inactivity when Last Invoice Date is absent.

Assert that `filter_sort_and_limit()`:

- excludes a Customer whose sales values net to exactly zero in every selected year;
- uses the highest selected prior-year value for Minimum Historical Sales;
- filters by Retention Status;
- defaults Importance to Previous Sales descending with Customer name as a deterministic tie-breaker;
- ranks largest positive Decrease Amount first;
- applies Top Results only after filtering and sorting;
- assigns final 1-based ranks.

- [ ] **Step 3: Run the isolated test and verify failure**

Run the Task 1 command.

Expected: FAIL because the calculation interfaces do not exist.

- [ ] **Step 4: Implement `classify_customer()` and `build_customer_row()`**

Use `flt`-compatible numeric output and a fixed `20.0` threshold. Apply classification in the spec's exact New, Reactivated, Lost, Decreased, Increased, Stable order. Do not divide when Previous Sales is zero or negative.

- [ ] **Step 5: Implement deterministic filtering, sorting, limiting, and ranking**

Map each approved Sort By label to one numeric row field. For Ascending/Descending, keep the Customer code tie-breaker deterministic rather than relying on database row order.

- [ ] **Step 6: Run the isolated test**

Run the Task 1 command.

Expected: PASS for all pure calculations, Review Focus edge cases, filtering, sorting, limiting, and ranking.

- [ ] **Step 7: Commit calculation behavior**

```bash
git add worldshading/worldshading/report/customer_retention_analysis/customer_retention_analysis.py worldshading/worldshading/report/customer_retention_analysis/test_customer_retention_analysis.py
git commit -m "feat: calculate customer retention status"
```

### Task 3: Aggregate Sales Activity and Orchestrate the Report

**Files:**

- Modify: `worldshading/worldshading/report/customer_retention_analysis/customer_retention_analysis.py`
- Modify: `worldshading/worldshading/report/customer_retention_analysis/test_customer_retention_analysis.py`

**Interfaces:**

- Consumes: Task 1 period helpers and Task 2 row pipeline; submitted Sales Invoice and Customer records.
- Produces: `get_company_context(company)`, `get_sales_activity(filters)`, `get_last_invoice_dates(filters, customers)`, `index_sales_activity(rows)`, `enrich_rows(rows, filters)`, `get_report_summary(rows, currency)`, `get_chart(rows)`, `get_message(filters, current_date=None)`, and `execute(filters=None)` returning the v12 six-value Script Report tuple. Task 3's `enrich_rows()` is an explicit no-op seam that Task 4 replaces with Item Group and Campaign enrichment.

- [ ] **Step 1: Add failing aggregate-query tests**

Mock `frappe.db.sql` and assert:

- The sales query binds Company, start date, and 31 December Analysis Year end.
- It restricts `docstatus = 1`, groups by Customer and `YEAR(posting_date)`, sums `base_net_total`, and counts only `is_return = 0` invoices.
- It does not filter out a disabled Customer master when that Customer has historical activity.
- Customer, Customer Group, and Territory filters are bound parameters, never interpolated user values.
- The last-invoice query is restricted to the already identified Customers, selected Company, `docstatus = 1`, `is_return = 0`, and dates through Analysis Year end, but has no selected-history start bound.
- Empty Customer input returns immediately without producing an invalid `IN ()` query.

- [ ] **Step 2: Add failing orchestration tests**

With all data access mocked, assert that `execute()`:

- loads and permission-checks the Company document and uses its `default_currency`;
- converts aggregate rows into year indexes, builds rows, filters/sorts/limits them, and only then calls `enrich_rows()` with the displayed rows;
- returns columns, enriched rows, partial-year message, chart, summary, and `skip_total_row = 1`;
- returns valid columns, empty data, a clear no-results message, an empty chart, and zero summary indicators when nothing qualifies.

Add the Review Focus return-only fixture and assert negative sales remains, purchase count is zero, and Last Invoice Date is absent.

- [ ] **Step 3: Run the isolated test and verify failure**

Run the Task 1 command.

Expected: FAIL because the data-access and orchestration interfaces do not exist.

- [ ] **Step 4: Implement Company validation and aggregate queries**

Use `frappe.get_doc("Company", company).check_permission("read")` and read `default_currency`. Use one grouped sales query and one last-invoice query with bound values. Explain in code comments that SQL is required for multi-year aggregation and avoids per-Customer queries.

- [ ] **Step 5: Implement sales indexing and `execute()` orchestration**

Keep orchestration in this order: normalize → Company check → columns → sales aggregate → pure row build → filters/rank/limit → `enrich_rows()` → summary/chart/message → return. Define Task 3's `enrich_rows()` to return the rows unchanged, and do not call it for empty rows. This preserves a testable interface without implementing Task 4 early.

- [ ] **Step 6: Implement summary, chart, and messages**

Summary indicators count only final displayed rows and include at-risk Previous Sales for Lost plus Decreased Customers. Chart at most ten displayed rows with positive Decrease Amount. When the Analysis Year is the unfinished current year, return the approved year-to-date-versus-full-prior-year notice without changing calculations.

- [ ] **Step 7: Run the isolated test**

Run the Task 1 command.

Expected: PASS with every database and permission call mocked; no site/database connection occurs.

- [ ] **Step 8: Commit sales aggregation and report execution**

```bash
git add worldshading/worldshading/report/customer_retention_analysis/customer_retention_analysis.py worldshading/worldshading/report/customer_retention_analysis/test_customer_retention_analysis.py
git commit -m "feat: aggregate customer retention sales"
```

### Task 4: Add Preferred Item Groups and Campaign Customer Context

**Files:**

- Modify: `worldshading/worldshading/report/customer_retention_analysis/customer_retention_analysis.py`
- Modify: `worldshading/worldshading/report/customer_retention_analysis/test_customer_retention_analysis.py`

**Interfaces:**

- Consumes: final displayed rows and the `enrich_rows(rows, filters)` seam from Task 3.
- Produces: `get_item_group_context(filters, customers)`, `get_campaign_context(customers)`, `apply_customer_context(rows, item_group_context, campaign_context)`, and the completed permission-safe `enrich_rows(rows, filters)` implementation called by `execute()`.

- [ ] **Step 1: Add failing Item Group tests**

Mock the Item Group query and assert:

- It runs only for final displayed Customer codes and selected calendar bounds.
- It joins Sales Invoice Item → submitted Sales Invoice → current Item, restricts Company, and groups by Customer plus `item.item_group`.
- It sums `Sales Invoice Item.base_net_amount`, allowing returns to reduce the group value.
- Context keeps at most the first three positive-net groups per Customer, ordered by amount descending and Item Group ascending for ties.
- Zero/negative groups and blank groups are excluded, and empty Customer input performs no query.

- [ ] **Step 2: Add failing Campaign Customer permission and selection tests**

Assert that:

- When `frappe.has_permission("Campaign Customer", "read")` is false, `get_campaign_context()` returns `{}` without calling SQL.
- When permitted, the query is restricted to final displayed Customers and ordered by Customer, modified descending, name descending.
- The first row per Customer wins and maps Campaign Customer, Campaign, outreach status, priority, planned date, next follow-up, and interaction count.
- `apply_customer_context()` leaves all context fields blank when either enrichment is unavailable.

- [ ] **Step 3: Run the isolated test and verify failure**

Run the Task 1 command.

Expected: FAIL because enrichment interfaces do not exist.

- [ ] **Step 4: Implement preferred Item Group enrichment**

Use one bound aggregate SQL query for the limited Customer tuple. Select the top three qualifying groups in Python so the tie rule and positive-net rule are explicit and testable.

- [ ] **Step 5: Implement permission-safe Campaign Customer enrichment**

Check permission before any query. Query only the final Customer tuple and keep the first deterministically ordered row for each Customer. Do not use `ignore_permissions` and do not expose contact fields.

- [ ] **Step 6: Wire both contexts into `execute()` after ranking and limiting**

Replace Task 3's no-op `enrich_rows()` with orchestration that extracts the final Customer codes, reads both contexts, and calls `apply_customer_context()`. Populate `top_item_group_1` through `top_item_group_3` and the seven approved Campaign Customer fields without changing sort order or ranks.

- [ ] **Step 7: Run the isolated test**

Run the Task 1 command.

Expected: PASS, including the no-permission/no-query Review Focus case.

- [ ] **Step 8: Commit report enrichment**

```bash
git add worldshading/worldshading/report/customer_retention_analysis/customer_retention_analysis.py worldshading/worldshading/report/customer_retention_analysis/test_customer_retention_analysis.py
git commit -m "feat: enrich customer retention context"
```

### Task 5: Build the Visual and Prepared-Report Client

**Files:**

- Create: `worldshading/worldshading/report/customer_retention_analysis/customer_retention_analysis.js`
- Modify: `worldshading/worldshading/report/customer_retention_analysis/customer_retention_analysis.py`
- Modify: `worldshading/worldshading/report/customer_retention_analysis/test_customer_retention_analysis.py`

**Interfaces:**

- Consumes: Frappe v12 Query Report client contract, server row fields, chart/summary/message output, and completed Prepared Report filter JSON.
- Produces: the `frappe.query_reports["Customer Retention Analysis"]` definition and whitelisted `get_prepared_report_filters(prepared_report_name=None)`.

- [ ] **Step 1: Add failing JavaScript contract tests**

Read the JS file as text and assert it defines every approved filter with exact options/defaults, including 1–5 Previous Years and Top Results 20/50/100/250/All. Assert it registers:

- a `formatter` using escaped values and all six status indicator colors;
- negative/positive Change Amount and Change % formatting;
- prepared-report filter restoration using `prepared_report_name` and the report-specific server method;
- a current unfinished-year notice hook without annualization code;
- filter-summary rendering;
- sticky Rank, Customer, and Customer Name behavior scoped to a report-specific CSS class.

Also assert the script does not use `localStorage`, does not create Sales Invoice/Customer/Campaign Customer mutations, and does not register bulk actions.

- [ ] **Step 2: Add failing prepared-filter security tests**

Mock Frappe and assert `get_prepared_report_filters()`:

- rejects a missing name;
- accepts only a completed Prepared Report for `Customer Retention Analysis` owned by the session user, except System Manager may read it;
- rejects a wrong report, incomplete status, or unauthorized owner;
- parses and returns only a JSON object of saved filters.

- [ ] **Step 3: Run the isolated test and verify failure**

Run the Task 1 command.

Expected: FAIL because the JS file and prepared-filter endpoint do not exist.

- [ ] **Step 4: Implement the v12 report filters and formatting**

Follow existing Worldshading Query Report conventions. Use `frappe.utils.escape_html` for custom HTML. Keep exported row data plain and make visual behavior additive so the table remains usable if styling fails.

- [ ] **Step 5: Implement prepared-filter restoration and filter summary**

Follow the owned/completed-report checks used by Item-wise Sales Register WS. Restore saved filters only when opening a completed Prepared Report; do not automatically rerun it. Render a compact summary containing Company, Analysis Year, history depth, status, ranking, and limit.

- [ ] **Step 6: Implement scoped sticky columns and partial-year notice**

Use report-specific style IDs/classes and calculate sticky offsets after DataTable render and column resize. Show the notice when Analysis Year equals the current year before 31 December; never rewrite server values.

- [ ] **Step 7: Run isolated and safe static checks**

Run from `apps/worldshading`:

```bash
../../env/bin/python -m unittest worldshading.worldshading.report.customer_retention_analysis.test_customer_retention_analysis
node --check worldshading/worldshading/report/customer_retention_analysis/customer_retention_analysis.js
../../env/bin/python -m json.tool worldshading/worldshading/report/customer_retention_analysis/customer_retention_analysis.json >/dev/null
../../env/bin/python -m py_compile worldshading/worldshading/report/customer_retention_analysis/customer_retention_analysis.py
git diff --check
```

Expected: all commands exit 0 without loading a site or database. If `node` is unavailable, record that the JS syntax check was skipped; the Python client-contract tests still run.

- [ ] **Step 8: Commit the visual prepared report**

```bash
git add worldshading/worldshading/report/customer_retention_analysis
git commit -m "feat: visualize customer retention report"
```

### Task 6: Final Review and Manual Production Handoff

**Files:**

- Review: all files under `worldshading/worldshading/report/customer_retention_analysis/`.
- Do not modify: ERPNext/Frappe core, Campaign Customer, existing reports, hooks, scheduler configuration, or unrelated dirty files.

**Interfaces:**

- Consumes: completed Tasks 1–5 and the approved specification.
- Produces: evidence-backed implementation handoff, exact unexecuted registration command, manual smoke checks, and rollback instructions.

- [ ] **Step 1: Review the complete scoped diff**

Run:

```bash
git diff HEAD~5 -- worldshading/worldshading/report/customer_retention_analysis
git status --short
```

Confirm only the five approved report files changed and all unrelated working-tree changes remain untouched.

- [ ] **Step 2: Re-run allowed verification**

Repeat Task 5 Step 7. Record exact command results. Do not substitute any bench/site test.

- [ ] **Step 3: Verify production prohibitions**

Confirm no migration, reload, restart, cache clear, scheduler change, production report execution, or database update occurred during implementation.

- [ ] **Step 4: Provide the manual registration command without executing it**

After human review, the site operator may register only this Report metadata with:

```bash
bench --site erp.worldshading.com reload-doc worldshading report customer_retention_analysis
```

State explicitly that this command was not executed.

- [ ] **Step 5: Provide manual smoke checks**

After an approved manual registration, verify:

1. Allowed roles can open the report and other roles cannot.
2. A one-year comparison matches Sales Analytics totals for sampled Customers.
3. Returns reduce value without increasing invoice counts.
4. Lost, Decreased, Stable, Increased, New, and Reactivated sample Customers match the documented rules.
5. Top 20/50/100/250 and every Sort By option are deterministic.
6. Five-year output shows five previous-year columns and no query timeout.
7. Preferred Item Groups match the current Item master.
8. Campaign context is visible only to users with Campaign Customer read permission.
9. Completed Prepared Reports reopen with their saved filter summary and visual formatting.
10. Exported data remains plain and usable in Excel.

- [ ] **Step 6: Document rollback**

Before manual registration, rollback is commit/file reversion. After registration, disable or remove the Report metadata only through a separately approved operation; existing Prepared Report attachments follow the current cleanup lifecycle. No transaction rollback is needed because the feature is read-only.
