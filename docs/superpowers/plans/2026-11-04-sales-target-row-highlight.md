# Sales Target Performance Row Highlight Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Color complete Sales Target Performance result rows green at 100% achievement or above and red below 100%.

**Architecture:** After each DataTable render, map `frappe.query_report.data` to native `.dt-row[data-row-index]` elements and apply achievement classes to their `.dt-cell` children through scoped CSS. A MutationObserver reapplies the classes when Frappe redraws virtual rows.

**Tech Stack:** ERPNext/Frappe v12 Query Report, frappe-datatable, ES5-compatible JavaScript, Node executable client test.

**Spec:** `docs/superpowers/specs/2026-11-04-sales-target-row-highlight-design.md`

## Global Constraints

- ERPNext/Frappe v12 and Python 3.6 compatibility.
- Custom app only; do not modify Frappe or ERPNext core.
- Presentation-only: do not change targets, invoices, calculations, permissions, or drill-down behavior.
- Deploy with report-only `reload-doc`; do not migrate, restart, clear cache, or run Bench tests.

## Review Focus

- Exactly 100% must receive the green class, not red.
- Negative, zero, and fractional values below 100% must receive the red class.
- Header, filter, footer, and rows without a valid numeric index must remain uncolored.
- Sorting, filtering, and virtual DataTable redraws must restore the class from current report data.
- Repeated renders must disconnect the prior observer and avoid duplicate event or style state.

---

### Task 1: Native DataTable Achievement Row Highlight

**Files:**
- Modify: `worldshading/worldshading/report/sales_target_performance/sales_target_performance.js`
- Modify: `worldshading/worldshading/report/sales_target_performance/test_sales_target_performance_client.js`

**Interfaces:**
- Consumes: `after_datatable_render(datatable)` and `frappe.query_report.data` rows containing `achievement_percent`.
- Produces: `apply_sales_target_row_highlights(datatable)`, scoped row classes, and one managed MutationObserver per DataTable.

- [ ] **Step 1: Write the failing executable client tests**

Assert literal row mappings for 100, 99.99, 0, and -5; assert header/filter rows are excluded; assert a redraw restores classes; and assert a repeated render disconnects the previous observer.

- [ ] **Step 2: Run the client test and verify RED**

Run: `node worldshading/worldshading/report/sales_target_performance/test_sales_target_performance_client.js`

Expected: FAIL because `after_datatable_render` does not apply row achievement classes.

- [ ] **Step 3: Implement the native row-class highlighter**

Add `apply_sales_target_row_highlights(datatable)` and call it after summary rendering. Scope injected CSS to the report wrapper, color every `.dt-cell` in achieved rows light green and below-target rows light red, and use a managed MutationObserver with `requestAnimationFrame` restoration.

- [ ] **Step 4: Run focused and full verification**

Run the executable client test, the combined 67-test Python suite, both client behavior scripts, JavaScript syntax validation, JSON parsing, and `git diff --check`.

Expected: all commands exit 0.

- [ ] **Step 5: Commit and deliver directly**

Commit the JavaScript/test change, fast-forward `main`, rerun merged-tree verification, push, then run only `bench --site erp.worldshading.com reload-doc worldshading report sales_target_performance`.

## Self-Review Record

- Spec coverage: row thresholds, full-row scope, redraw behavior, and exclusions are assigned to Task 1.
- Step scan: one UI behavior has one RED/GREEN/verification cycle.
- Type/name consistency: the plan uses existing v12 DataTable and report data interfaces.
- Review focus: all five identified failure modes are included in the Task 1 client test.
- Proportion: one task and two production/test files match the small presentation-only scope.
