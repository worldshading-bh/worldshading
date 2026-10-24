# Customer Retention Notice Removal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove every year-to-date explanatory message from Customer Retention Analysis while leaving its calculations and other visual behavior unchanged.

**Architecture:** Delete the backend message producer and the client banner path instead of hiding them. Keep the existing report result tuple and summary components, with the result summary anchored directly after the filter summary.

**Tech Stack:** ERPNext/Frappe v12, Python 3.6, ES5-compatible JavaScript, Python `unittest`, Node.js `assert`.

**Spec:** `docs/superpowers/specs/2026-10-24-customer-retention-notice-removal-design.md`

## Global Constraints

- Preserve calendar-year boundaries, retention status logic, sorting, totals, charts, and prepared-report behavior.
- Remain compatible with ERPNext/Frappe v12 and Python 3.6.
- Do not modify DocTypes, database schema, workflows, ERPNext core, or the unrelated Pricing Group change.
- Do not run migration, reload-doc, cache clear, restart, database update, bench tests, or push.

## Review Focus

- A current in-progress analysis year returns no explanatory message while retaining the same rows, chart, and summary; covered in Task 1.
- A completed analysis year also returns no explanatory message; covered in Task 1.
- An empty result still returns the useful “No customers matched” message; covered by the existing empty-result test rerun in Task 1.
- Normal and prepared client rendering creates no partial-year banner; covered in Task 1.
- The result summary remains directly below the filter summary after the banner anchor is removed; covered in Task 1.

---

### Task 1: Remove all year-to-date notices

**Files:**
- Modify: `worldshading/worldshading/report/customer_retention_analysis/customer_retention_analysis.py:492-541`
- Modify: `worldshading/worldshading/report/customer_retention_analysis/customer_retention_analysis.js:22-166,475-486`
- Test: `worldshading/worldshading/report/customer_retention_analysis/test_customer_retention_analysis.py:300-370,498-535`
- Test: `worldshading/worldshading/report/customer_retention_analysis/test_customer_retention_analysis_client.js`

**Interfaces:**
- Consumes: normalized filters, the existing six-element `execute(filters)` tuple, and the existing filter/result summary elements.
- Produces: `message=None` when rows exist, no client banner, and result summary insertion directly after `.cra-filter-summary`; empty results retain `"No customers matched the selected filters."`.

- [ ] **Step 1: Write failing backend and client tests**

Change the normal-row execution test to assert `message is None`; add `test_execute_returns_no_notice_for_completed_analysis_year` with the same expectation; leave the empty-result message assertion intact. Update the Python client contract to exclude `update_partial_year_notice`, `cra-partial-year-notice`, and `sales are not annualized`. Instrument the real client script in the Node test to expose `update_result_summary`, pass a minimal fake report page, and assert insertion after `.cra-filter-summary`.

- [ ] **Step 2: Run focused tests and verify RED**

Run: `/home/erpadmin/frappe-bench/env/bin/python -m unittest worldshading.worldshading.report.customer_retention_analysis.test_customer_retention_analysis.TestCustomerRetentionAnalysis.test_execute_builds_limits_then_enriches_and_returns_v12_contract worldshading.worldshading.report.customer_retention_analysis.test_customer_retention_analysis.TestCustomerRetentionAnalysis.test_execute_returns_no_notice_for_completed_analysis_year worldshading.worldshading.report.customer_retention_analysis.test_customer_retention_analysis.TestCustomerRetentionAnalysis.test_javascript_defines_filters_visual_contract_and_safe_read_only_behavior`

Expected: FAIL because the backend message and client banner still exist.

Run: `node worldshading/worldshading/report/customer_retention_analysis/test_customer_retention_analysis_client.js`

Expected: FAIL because the result summary still prefers `.cra-partial-year-notice` as its anchor.

- [ ] **Step 3: Implement clean removal**

Delete Python `get_message(filters, current_date=None)` and set `message = None` for non-empty execution. Delete the JavaScript banner CSS, function, and calls. Insert a new result summary directly after `.cra-filter-summary`.

- [ ] **Step 4: Run isolated verification**

Run:

```bash
/home/erpadmin/frappe-bench/env/bin/python -m unittest worldshading.worldshading.report.customer_retention_analysis.test_customer_retention_analysis
node worldshading/worldshading/report/customer_retention_analysis/test_customer_retention_analysis_client.js
node --check worldshading/worldshading/report/customer_retention_analysis/customer_retention_analysis.js
/home/erpadmin/frappe-bench/env/bin/python -m py_compile worldshading/worldshading/report/customer_retention_analysis/customer_retention_analysis.py worldshading/worldshading/report/customer_retention_analysis/test_customer_retention_analysis.py
git diff --check
```

Expected: all commands exit `0`; Python reports at least 30 tests and `OK`; Node reports `Customer Retention Analysis client tests passed`.

- [ ] **Step 5: Commit**

```bash
git add worldshading/worldshading/report/customer_retention_analysis/customer_retention_analysis.py worldshading/worldshading/report/customer_retention_analysis/customer_retention_analysis.js worldshading/worldshading/report/customer_retention_analysis/test_customer_retention_analysis.py worldshading/worldshading/report/customer_retention_analysis/test_customer_retention_analysis_client.js
git commit -m "fix: remove retention year-to-date notices"
```
