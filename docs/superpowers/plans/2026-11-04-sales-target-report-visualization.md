# Sales Target Report Visualization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Sales Target Performance compact and visual, while allowing a blank Frequency filter to show every configured frequency for the selected target and optional salesperson.

**Architecture:** Keep Sales Target required as the approved source. For a selected frequency, retain the current grouped invoice aggregate; for blank Frequency, use one employee/date-grouped Sales Invoice query and calculate each occurrence in Python, avoiding five queries. Render a compact table and per-frequency summary indicators, with Achievement % green at 100% or above and red below 100%.

**Tech Stack:** ERPNext/Frappe v12, Python 3.6, MariaDB, ES5-compatible report JavaScript.

**Spec:** User-approved direct report enhancement requested 2026-11-04; this plan is a presentation/optional-frequency delta to `docs/superpowers/specs/2026-11-04-recurring-sales-target-plan-design.md`.

## Global Constraints

- Modify only the custom `worldshading` app; never modify ERPNext/Frappe core.
- Remain compatible with ERPNext/Frappe v12 and Python 3.6; no type hints or `frappe.qb`.
- Keep Sales Target required and submitted recurring-plan validation unchanged.
- Use only submitted parent Sales Invoices, `pb_sales_employee`, and `base_net_total`.
- Keep invoice SQL parameterized and execute one invoice query per report run.
- Do not write Sales Target, Employee, Sales Invoice, incentive, or commission records.
- Push directly to `main` as requested; deploy with report-only `reload-doc` and no migrate, restart, cache clear, or Bench tests.

## Review Focus

- Blank Frequency with one salesperson shows every positive configured frequency for that person.
- Blank Frequency without a salesperson remains valid and does not combine unlike target amounts into one currency total.
- One date-grouped invoice query feeds all occurrence calculations without double-counting outside each occurrence.
- Historical/current occurrence status and Saturday-Friday weekly boundaries remain unchanged.
- Achievement formatting handles numeric zero and colors 100% or more green, otherwise red.

---

### Task 1: Optional Frequency Report Engine

**Files:**
- Modify: `worldshading/worldshading/report/sales_target_performance/sales_target_performance.py`
- Modify: `worldshading/worldshading/report/sales_target_performance/test_sales_target_performance.py`

**Interfaces:**
- Produces `get_sales_aggregates_by_date(company, from_date, to_date, employee_ids)` keyed by employee and posting date.
- Produces `build_frequency_rows(target, frequencies, occurrences, aggregates_by_frequency, as_of_date, current_date)`.
- Blank `filters.frequency` selects Daily through Annual and returns only positive configured targets.

- [ ] **Step 1: Write failing tests**

Assert Frequency is optional; blank Frequency returns all positive configured frequencies; optional Employee filters after frequency-aware ranking; all-frequency execution performs one parameterized date-grouped invoice query; and all-frequency summaries are percentages per frequency rather than a cross-frequency currency sum.

- [ ] **Step 2: Run the report test module and verify RED**

Run the isolated Python unittest module. Expected: failures because Frequency is required and only one occurrence is supported.

- [ ] **Step 3: Implement optional-frequency execution**

Derive each occurrence with existing helpers. Query the union date range once, grouped by employee and posting date, then fold each daily aggregate into every matching occurrence. Preserve the existing single-frequency path and permission/legacy/future-date gates.

- [ ] **Step 4: Implement frequency-aware summaries**

For blank Frequency, return one percentage indicator per displayed frequency. When an Employee filter is present, calculate these indicators from the visible employee rows. Never add Daily, Weekly, Monthly, Quarterly, and Annual target amounts together.

- [ ] **Step 5: Verify and commit**

Run report tests and the combined 64-test suite. Commit the server/tests change.

---

### Task 2: Compact Visual Report

**Files:**
- Modify: `worldshading/worldshading/report/sales_target_performance/sales_target_performance.js`
- Modify: `worldshading/worldshading/report/sales_target_performance/test_sales_target_performance_client.js`
- Modify: `worldshading/worldshading/report/sales_target_performance/sales_target_performance.py`

**Interfaces:**
- Frequency Select begins with a blank All Frequencies option and is not required.
- Compact columns are Sales Employee, Employee Name, Frequency, Period, Target, Achieved, Achievement %, Remaining, Invoice Count, and Status.
- Achievement % formatter uses v12 `indicator green` for values at least 100, otherwise `indicator red`.

- [ ] **Step 1: Write failing client and column tests**

Assert the optional Frequency filter, compact column list, period display, green/red Achievement %, existing status indicators, safe invoice drill-down, and styled summary cards.

- [ ] **Step 2: Run executable client tests and verify RED**

Expected: failures because Frequency is required, columns are wide, and Achievement % has no indicator.

- [ ] **Step 3: Implement compact columns and formatters**

Add a display-only Period value while retaining occurrence dates in row data for drill-down. Remove analytical detail columns from the visible table only; keep their server calculations available.

- [ ] **Step 4: Run final verification**

Run the combined Python suite, both report JavaScript syntax/behavior checks, JSON parsing, and `git diff --check`.

- [ ] **Step 5: Commit, push, and deploy directly**

Push `main`, run only `bench --site erp.worldshading.com reload-doc worldshading report sales_target_performance`, and verify report metadata read-only.

## Self-Review Record

- Spec coverage: optional frequency, all-frequency calculation, salesperson filtering, compact layout, color semantics, one-query performance, and safe deployment are assigned.
- Step scan: each task has RED, implementation, GREEN, and commit stages.
- Type/name consistency: occurrences and existing frequency configuration remain the shared source of truth.
- Review focus: all five listed failure modes have explicit Task 1 or Task 2 tests.
- Proportion: two coupled tasks keep report calculation and presentation independently reviewable.
