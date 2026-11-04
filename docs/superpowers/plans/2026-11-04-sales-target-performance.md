# Sales Target and Performance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a submittable Sales Target master with employee target rows, then a fast Sales Target Performance report based on submitted Sales Invoice `base_net_total` attributed through `pb_sales_employee`.

**Architecture:** A Sales Target parent owns one period and a Sales Target Detail child table. Server validation protects the submitted target snapshot and overlap rules; the report loads one submitted plan and performs one grouped Sales Invoice query, then calculates pacing and ranking in memory. The master and report are deployed in separate, explicitly approved `reload-doc` stages.

**Tech Stack:** ERPNext 12, Frappe 12, Python 3.6, MariaDB, Frappe DocType JSON/controllers/client scripts, Script Report, Python `unittest` with mocks.

**Spec:** `docs/superpowers/specs/2026-11-04-sales-target-performance-design.md`

## Global Constraints

- Production is live; preserve unrelated worktree changes and touch only files listed in this plan.
- Keep all product code compatible with ERPNext/Frappe v12 and Python 3.6: no type hints, dataclasses, `frappe.qb`, f-string-only modern assumptions beyond Python 3.6, or unavailable APIs.
- Do not modify ERPNext core or the existing Sales Target and Incentive, Incentive Progress, Incentive Plan, or Sales Person Commission Summary features.
- Do not run `bench migrate`, `bench test`, restart, backup, restore, or any cache-clearing command.
- Do not run a `reload-doc` until the immediately preceding review gate is complete and the user explicitly approves that exact production reload.
- Use submitted Sales Invoice `base_net_total`, company currency, and `pb_sales_employee`; keep credit notes negative.
- Do not store achieved sales on Sales Target and do not issue one query per employee.
- Use parameterized SQL only where the single grouped aggregate cannot be expressed efficiently with Frappe document APIs.
- Do not add workflow, notifications, scheduled jobs, dashboards, item-group scope, points, incentives, commissions, payouts, or row-level Sales User access.
- Every commit must include only the task's scoped files; never stage unrelated customer-retention changes.

## Review Focus

- An amended target whose predecessor is cancelled must submit without treating that predecessor as an active overlap; Task 2 tests this exclusion.
- Multiple employees must be validated with one bulk Employee read, including inactive and wrong-company records; Task 2 tests both failure classes and query count.
- An as-of date before, on, and after the target boundaries must not produce off-by-one pacing or run-rate results; Task 4 tests all three.
- Negative return totals and zero-sales employees must remain visible and calculate safe percentages/statuses; Task 4 tests both cases.
- Filtering one employee must preserve the plan-wide rank rather than making that employee rank 1; Task 4 tests rank-before-filter behavior.

---

### Task 1: Sales Target Metadata Foundation

**Files:**
- Create: `worldshading/worldshading/doctype/sales_target_detail/__init__.py`
- Create: `worldshading/worldshading/doctype/sales_target_detail/sales_target_detail.py`
- Create: `worldshading/worldshading/doctype/sales_target_detail/sales_target_detail.json`
- Create: `worldshading/worldshading/doctype/sales_target/__init__.py`
- Create: `worldshading/worldshading/doctype/sales_target/sales_target.json`
- Create: `worldshading/worldshading/doctype/sales_target/test_sales_target.py`

**Interfaces:**
- Consumes: ERPNext `Company`, `Currency`, and `Employee` links; no runtime interface from earlier tasks.
- Produces: DocTypes `Sales Target` and `Sales Target Detail` with exact fieldnames `company`, `currency`, `target_name`, `period_type`, `from_date`, `to_date`, `total_target_amount`, `notes`, `targets`, `amended_from`, and child fields `sales_employee`, `employee_name`, `currency`, `target_amount`, `remarks`. Child `currency` is hidden/read-only and mirrors the parent solely so v12 formats each child amount in the explicit company currency.

- [ ] **Step 1: Create failing metadata tests**

Add `TestSalesTargetMetadata` tests that load both JSON files and assert:

- `Sales Target Detail.istable == 1` and has no permissions.
- Parent `is_submittable == 1`, `track_changes == 1`, title field is `target_name`, and autoname is `ST-WS-.YYYY.-.#####`.
- `period_type` options are exactly `Daily\nWeekly\nMonthly\nQuarterly\nAnnual\nCustom`.
- `targets` is a required Table with options `Sales Target Detail`.
- `currency` is required/read-only and `total_target_amount` is read-only with Currency options `currency`.
- Child Employee is required with options `Employee`; employee name fetches `sales_employee.employee_name`; hidden child `currency` is read-only; target amount is required with Currency options `currency`.
- Permissions match the approved Sales Manager, General Manager, System Manager, and Accounts Manager matrix.

- [ ] **Step 2: Run the metadata test to verify it fails**

Run: `./env/bin/python -m unittest worldshading.worldshading.doctype.sales_target.test_sales_target.TestSalesTargetMetadata -v`

Expected: FAIL because the new DocType JSON files do not exist.

- [ ] **Step 3: Create the child DocType metadata and empty controller**

Create ERPNext v12-style `sales_target_detail.json`, `__init__.py`, and a Python 3.6 controller class `SalesTargetDetail(Document)` with no business logic. Use editable-grid columns for Employee, Employee Name, Target Amount, and Remarks.

- [ ] **Step 4: Create the parent DocType metadata and controller scaffold**

Create `sales_target.json` with the exact fields and permissions in the spec. Keep Quick Entry disabled because the child targets are required. Create `sales_target.py` with `SalesTarget(Document)` but defer validation bodies to Task 2.

- [ ] **Step 5: Run metadata tests and parse both JSON files**

Run: `./env/bin/python -m unittest worldshading.worldshading.doctype.sales_target.test_sales_target.TestSalesTargetMetadata -v`

Expected: PASS.

Run: `./env/bin/python -m json.tool worldshading/worldshading/doctype/sales_target_detail/sales_target_detail.json >/dev/null`

Run: `./env/bin/python -m json.tool worldshading/worldshading/doctype/sales_target/sales_target.json >/dev/null`

Expected: both exit 0.

- [ ] **Step 6: Commit the metadata foundation**

```bash
git add worldshading/worldshading/doctype/sales_target_detail worldshading/worldshading/doctype/sales_target
git commit -m "feat: add sales target metadata"
```

### Task 2: Sales Target Server Validation

**Files:**
- Modify: `worldshading/worldshading/doctype/sales_target/sales_target.py`
- Modify: `worldshading/worldshading/doctype/sales_target/test_sales_target.py`

**Interfaces:**
- Consumes: Task 1 fieldnames and child rows.
- Produces: `SalesTarget.validate()`, `SalesTarget.before_submit()`, `_validate_dates(doc)`, `_validate_employee_rows(doc)`, `_set_company_currency(doc)`, `_set_total_target(doc)`, and `_validate_no_overlap(doc)`; helper functions accept a document-like object so unit tests do not require database writes.

- [ ] **Step 1: Write failing date, currency, row, and total tests**

Add tests asserting:

- `_validate_dates` accepts equal dates and rejects `to_date < from_date`.
- `_set_company_currency` reads `Company.default_currency`, sets `doc.currency` and every child row's hidden `currency`, and rejects a company without a default currency.
- `_validate_employee_rows` rejects an empty child table, duplicate employees, zero/negative amounts, missing Employees, inactive Employees, and Employees belonging to another Company.
- Employee validation performs one bulk `frappe.get_all("Employee", ...)` call for all unique employees, not one call per row.
- `_set_total_target` uses `flt` semantics and rounds/sums child amounts into `total_target_amount` without accepting blank/negative rows as valid.

- [ ] **Step 2: Run focused tests to verify they fail**

Run: `./env/bin/python -m unittest worldshading.worldshading.doctype.sales_target.test_sales_target.TestSalesTargetValidation -v`

Expected: FAIL because the helper functions are absent.

- [ ] **Step 3: Implement validate-time helpers and orchestration**

Implement the exact helper signatures above using `frappe.throw`, `frappe.get_all`, `frappe.db.get_value`, `getdate`, and `flt`. `SalesTarget.validate()` calls currency, date, employee-row, and total helpers in that order.

- [ ] **Step 4: Run validation tests to verify they pass**

Run: `./env/bin/python -m unittest worldshading.worldshading.doctype.sales_target.test_sales_target.TestSalesTargetValidation -v`

Expected: PASS.

- [ ] **Step 5: Write failing overlap tests**

Add tests asserting `_validate_no_overlap(doc)`:

- Detects inclusive intersection (`other.from_date <= doc.to_date` and `other.to_date >= doc.from_date`) for the same company, period type, employee, and submitted parent.
- Ignores drafts, cancelled documents, the current document name, different period types, different companies, and employees not shared by both plans.
- Allows an amended document when its `amended_from` predecessor is cancelled.
- Uses parameterized values and never interpolates company, period type, dates, document name, or employee IDs into SQL text.

- [ ] **Step 6: Run overlap tests to verify they fail**

Run: `./env/bin/python -m unittest worldshading.worldshading.doctype.sales_target.test_sales_target.TestSalesTargetOverlap -v`

Expected: FAIL because overlap validation is absent.

- [ ] **Step 7: Implement submit-time overlap validation**

Implement `_validate_no_overlap(doc)` with one parameterized SQL query joining `tabSales Target` and `tabSales Target Detail`. Return conflicting parent names and throw one actionable message naming the employee and conflicting target. Call it from `SalesTarget.before_submit()` so drafts may coexist but submitted targets cannot conflict.

- [ ] **Step 8: Run all Sales Target Python tests and compile controllers**

Run: `./env/bin/python -m unittest worldshading.worldshading.doctype.sales_target.test_sales_target -v`

Expected: PASS.

Run: `./env/bin/python -m py_compile worldshading/worldshading/doctype/sales_target/sales_target.py worldshading/worldshading/doctype/sales_target_detail/sales_target_detail.py`

Expected: exit 0.

- [ ] **Step 9: Commit server validation**

```bash
git add worldshading/worldshading/doctype/sales_target/sales_target.py worldshading/worldshading/doctype/sales_target/test_sales_target.py
git commit -m "feat: validate sales targets"
```

### Task 3: Sales Target Form Behavior

**Files:**
- Create: `worldshading/worldshading/doctype/sales_target/sales_target.js`
- Modify: `worldshading/worldshading/doctype/sales_target/test_sales_target.py`

**Interfaces:**
- Consumes: Task 1 parent/child fieldnames; server validation from Task 2 remains authoritative.
- Produces: browser helpers `set_period_defaults(frm)`, `set_employee_query(frm)`, and `update_target_total(frm)` registered through v12 `frappe.ui.form.on` handlers for Sales Target and Sales Target Detail.

- [ ] **Step 1: Write failing static client-contract tests**

Add tests that read `sales_target.js` and assert it:

- Registers parent handlers for `refresh`, `company`, and `period_type`.
- Registers child handlers for `target_amount`, row add, and row remove events.
- Uses only v12-compatible `frappe.ui.form.on`, `frm.set_query`, `frm.set_value`, and `frappe.datetime` calls.
- Filters Employee by `status: "Active"` and the selected Company.
- Does not submit, save, reload, call workflow APIs, or write any database value.

- [ ] **Step 2: Run client-contract tests to verify they fail**

Run: `./env/bin/python -m unittest worldshading.worldshading.doctype.sales_target.test_sales_target.TestSalesTargetClientContract -v`

Expected: FAIL because `sales_target.js` does not exist.

- [ ] **Step 3: Implement minimal v12 client behavior**

Implement the three helpers. Period defaults populate only blank dates and never override a manually entered date: Daily suggests today/today; Weekly suggests today through six days later; Monthly suggests the current calendar month's first/last date; Quarterly suggests the current calendar quarter boundaries; Annual suggests January 1 through December 31 of the current year; Custom leaves dates unchanged. On Company change, fetch its default currency for display, copy it to child rows, and warn before clearing incompatible existing rows; do not silently discard rows. Child changes recalculate the displayed total while the server recalculates it on validate.

- [ ] **Step 4: Run client-contract and syntax checks**

Run: `./env/bin/python -m unittest worldshading.worldshading.doctype.sales_target.test_sales_target.TestSalesTargetClientContract -v`

Expected: PASS.

Run: `node --check worldshading/worldshading/doctype/sales_target/sales_target.js`

Expected: exit 0.

- [ ] **Step 5: Review Phase 1 diff and commit**

Run: `git diff --check HEAD~2 -- worldshading/worldshading/doctype/sales_target worldshading/worldshading/doctype/sales_target_detail`

Expected: no output.

```bash
git add worldshading/worldshading/doctype/sales_target/sales_target.js worldshading/worldshading/doctype/sales_target/test_sales_target.py
git commit -m "feat: add sales target form behavior"
```

### Task 4: Performance Report Calculation Engine

**Files:**
- Create: `worldshading/worldshading/report/sales_target_performance/__init__.py`
- Create: `worldshading/worldshading/report/sales_target_performance/sales_target_performance.py`
- Create: `worldshading/worldshading/report/sales_target_performance/test_sales_target_performance.py`

**Interfaces:**
- Consumes: submitted Sales Target documents and child rows from Tasks 1–2; submitted Sales Invoice fields `company`, `posting_date`, `pb_sales_employee`, `base_net_total`, and `name`.
- Produces: `execute(filters=None)`, `get_columns()`, `get_sales_aggregates(company, from_date, effective_to_date)`, `calculate_metrics(target_amount, achieved_amount, from_date, to_date, as_of_date)`, and `build_rows(target, aggregates, as_of_date, sales_employee=None)`.
- `get_sales_aggregates` returns `{employee_id: {"achieved_amount": number, "invoice_count": int}}`.
- `calculate_metrics` returns keys `achieved_amount`, `achievement_percent`, `expected_amount`, `progress_variance`, `remaining_amount`, `over_target_amount`, `required_daily_run_rate`, and `status`.
- `build_rows` returns report row dictionaries and calculates full-plan rank before the optional employee display filter.

- [ ] **Step 1: Write failing metric-boundary tests**

Add `TestPerformanceMetrics` tests for:

- Before From Date: zero expected/achieved display basis, zero run rate, Not Started.
- First day: one inclusive elapsed day; remaining run-rate days exclude that day.
- On To Date below target: Not Achieved and zero run rate.
- After To Date: metrics clipped to To Date.
- Exact target: Achieved; above target: positive over-target and zero remaining.
- Negative achieved amount from returns: safe negative achievement/variance, positive remaining, no division error.
- Zero target input is guarded even though master validation prohibits it.

- [ ] **Step 2: Run metric tests to verify they fail**

Run: `./env/bin/python -m unittest worldshading.worldshading.report.sales_target_performance.test_sales_target_performance.TestPerformanceMetrics -v`

Expected: FAIL because the report module does not exist.

- [ ] **Step 3: Implement columns and pure metric calculation**

Implement `get_columns()` with the exact spec columns and `calculate_metrics(...)` using `getdate`, `date_diff`, `flt`, and inclusive calendar-day arithmetic. Keep all rounding for display at the report boundary; do not round values before comparisons.

- [ ] **Step 4: Run metric tests to verify they pass**

Run: `./env/bin/python -m unittest worldshading.worldshading.report.sales_target_performance.test_sales_target_performance.TestPerformanceMetrics -v`

Expected: PASS.

- [ ] **Step 5: Write failing aggregation and row-building tests**

Add tests asserting:

- `get_sales_aggregates` issues exactly one SQL query, filters `docstatus = 1`, Company, inclusive posting dates, groups by `pb_sales_employee`, sums `base_net_total`, counts invoices, and uses parameterized values.
- A negative aggregate remains negative; an employee absent from aggregates gets zero achievement and zero invoice count.
- Rows include target identity, employee, employee name, currency, dates, target amount, all metrics, invoice count, and status.
- Ranking is Achievement % descending, then Achieved Amount descending, then Employee Name.
- Applying `sales_employee` after ranking preserves plan-wide rank.
- `execute` rejects a missing target filter, a draft/cancelled target, and an As of Date outside the plan only by clipping—not by changing stored target dates.

- [ ] **Step 6: Run aggregation tests to verify they fail**

Run: `./env/bin/python -m unittest worldshading.worldshading.report.sales_target_performance.test_sales_target_performance.TestPerformanceReport -v`

Expected: FAIL because aggregation, row building, and execute orchestration are absent.

- [ ] **Step 7: Implement aggregate query, row builder, and execute orchestration**

Use one parameterized parent-level Sales Invoice aggregate query. `execute` loads the selected Sales Target once with `frappe.get_doc`, requires `docstatus == 1`, clips the effective query date, skips the invoice query before the plan begins, builds all rows, ranks them, and only then applies the optional employee filter.

- [ ] **Step 8: Run report engine tests and compile**

Run: `./env/bin/python -m unittest worldshading.worldshading.report.sales_target_performance.test_sales_target_performance -v`

Expected: PASS.

Run: `./env/bin/python -m py_compile worldshading/worldshading/report/sales_target_performance/sales_target_performance.py`

Expected: exit 0.

- [ ] **Step 9: Commit the report engine**

```bash
git add worldshading/worldshading/report/sales_target_performance
git commit -m "feat: calculate sales target performance"
```

### Task 5: Report Metadata, Filters, and Invoice Drill-Down

**Files:**
- Create: `worldshading/worldshading/report/sales_target_performance/sales_target_performance.json`
- Create: `worldshading/worldshading/report/sales_target_performance/sales_target_performance.js`
- Modify: `worldshading/worldshading/report/sales_target_performance/test_sales_target_performance.py`

**Interfaces:**
- Consumes: Task 4 report columns/rows, including `sales_target`, `sales_employee`, `company`, `from_date`, `effective_to_date`, `invoice_count`, `status`, and `currency`.
- Produces: Script Report registration `frappe.query_reports["Sales Target Performance"]`, filters `sales_target`, `sales_employee`, `as_of_date`, status formatting, and `open_sales_target_invoices(data)` routing to filtered Sales Invoice List.

- [ ] **Step 1: Write failing report metadata/client tests**

Add tests asserting:

- Report JSON is standard Script Report, module Worldshading, `ref_doctype` Sales Target, `prepared_report` disabled, and roles are System Manager, General Manager, Sales Manager, and Accounts Manager.
- Sales Target filter is required and queries `docstatus: 1`.
- As of Date defaults to today; Sales Employee is optional.
- Status formatter has distinct indicators for Not Started, Behind, On Track, Achieved, and Not Achieved.
- Invoice-count drill-down calls `frappe.set_route("List", "Sales Invoice", filters)` with Company, `pb_sales_employee`, posting-date range, and `docstatus: 1` from row data; values are not concatenated into executable JavaScript.

- [ ] **Step 2: Run metadata/client tests to verify they fail**

Run: `./env/bin/python -m unittest worldshading.worldshading.report.sales_target_performance.test_sales_target_performance.TestPerformanceReportMetadata -v`

Expected: FAIL because report JSON/JS do not exist.

- [ ] **Step 3: Create report JSON and v12 client script**

Implement the exact report registration and filters. Use formatter-produced DOM-safe link data or a delegated click handler rather than embedding unescaped Employee values into an inline handler. The drill-down is read-only and uses Frappe List routing only.

- [ ] **Step 4: Run report tests, JSON parsing, and JavaScript syntax check**

Run: `./env/bin/python -m unittest worldshading.worldshading.report.sales_target_performance.test_sales_target_performance -v`

Expected: PASS.

Run: `./env/bin/python -m json.tool worldshading/worldshading/report/sales_target_performance/sales_target_performance.json >/dev/null`

Run: `node --check worldshading/worldshading/report/sales_target_performance/sales_target_performance.js`

Expected: both exit 0.

- [ ] **Step 5: Run the complete isolated feature checks**

Run: `./env/bin/python -m unittest worldshading.worldshading.doctype.sales_target.test_sales_target worldshading.worldshading.report.sales_target_performance.test_sales_target_performance -v`

Expected: all tests PASS without `bench test` and without database writes.

Run: `git diff --check HEAD~4 -- worldshading/worldshading/doctype/sales_target worldshading/worldshading/doctype/sales_target_detail worldshading/worldshading/report/sales_target_performance`

Expected: no output.

- [ ] **Step 6: Commit report presentation**

```bash
git add worldshading/worldshading/report/sales_target_performance
git commit -m "feat: add sales target performance report"
```

### Task 6: Production Review and Controlled Reload Gates

**Files:**
- Verify only: all files created in Tasks 1–5
- No source file changes expected

**Interfaces:**
- Consumes: reviewed commits from Tasks 1–5.
- Produces: explicit evidence for separate Phase 1 and Phase 2 production approvals; no automatic deployment.

- [ ] **Step 1: Verify scoped worktree and commit history**

Run: `git status --short`

Expected: only known pre-existing unrelated changes remain; no uncommitted Sales Target files.

Run: `git log --oneline --max-count=6`

Expected: the Sales Target task commits are present and independently reviewable.

- [ ] **Step 2: Review ERPNext v12 and production safety**

Inspect the full feature diff and confirm: no core files, no hooks, no scheduler, no workflow, no imports unavailable in v12, no non-parameterized values, no writes to Sales Invoice/Employee, no existing incentive files, and no deploy command hidden in code.

- [ ] **Step 3: Present Phase 1 change control and wait for approval**

Present before execution:

- Objective: create Sales Target Detail and Sales Target metadata only.
- Impacted production metadata: two new DocTypes/tables.
- Risk: medium-low; additive metadata, no transaction mutation.
- Rollback: stop use; before data, separately remove DocTypes in reverse order; after data, export and retain/cancel rather than destructive removal.
- Exact proposed commands:

```bash
bench --site erp.worldshading.com reload-doc worldshading doctype sales_target_detail
bench --site erp.worldshading.com reload-doc worldshading doctype sales_target
```

Do not execute until the user explicitly approves these exact reloads.

- [ ] **Step 4: After approval, reload and manually verify Phase 1**

Run only the two approved commands in dependency order. Do not run migrate, test, restart, or cache commands. Confirm metadata and permissions read-only. Before creating, submitting, cancelling, or amending any production test target, present the proposed test records and request separate explicit approval; otherwise provide the checklist for the user to execute. Verification covers draft totals, validation failures, submit locking, same-type overlap rejection, different-type overlap allowance, cancel, and amend behavior.

- [ ] **Step 5: Present Phase 2 change control and wait for approval**

Present before execution:

- Objective: register the read-only Sales Target Performance report.
- Impacted production metadata: one new Script Report.
- Risk: low; read-only grouped Sales Invoice query.
- Rollback: disable/remove only the report metadata in a separately approved action; master targets remain.
- Exact proposed command:

```bash
bench --site erp.worldshading.com reload-doc worldshading report sales_target_performance
```

Do not execute until the user explicitly approves this exact reload.

- [ ] **Step 6: After approval, reload and reconcile Phase 2**

Run only the approved report reload. Reconcile at least two employee totals and one return against submitted Sales Invoices, verify every status and filter, verify drill-down, and measure representative monthly and annual query duration. Report the exact evidence and any discrepancy; do not modify live invoices to manufacture test cases.

- [ ] **Step 7: Final rollback/readiness handoff**

Document the created metadata, manual test target names, reconciled report totals, observed query times, remaining deferred features, and rollback posture. Do not add points or commission work without a separately approved design.

## Self-Review Record

- Spec coverage: every scope, validation, permission, performance, calculation, deployment, verification, and rollback requirement maps to Tasks 1–6.
- Step scan: each step is one test, implementation, verification, commit, or approval gate; production reloads are isolated behind explicit approval.
- Type/name consistency: parent/child/report fieldnames and helper interfaces are defined once and reused unchanged.
- Review Focus: amendment overlap, bulk employee validation, date boundaries, negative/zero sales, and rank-before-filter each have an owning test.
- Proportion: the plan specifies interfaces and assertions without transcribing implementation bodies.
