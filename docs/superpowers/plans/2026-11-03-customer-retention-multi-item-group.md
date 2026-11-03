# Customer Retention Multi-Item-Group Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add exact multi-Item-Group filtering with combined retention calculations and per-group yearly tooltip breakdowns.

**Architecture:** Preserve the `item_group` filter name but normalize its value to an ordered list. Existing aggregate paths use bound SQL `IN` clauses for combined figures; one bounded enrichment query supplies per-customer/per-year/per-group tooltip detail after Top Results is applied.

**Tech Stack:** ERPNext/Frappe v12, Python 3.6, MariaDB, ES5-compatible report JavaScript, `unittest`, Node assertion harness.

**Spec:** `docs/superpowers/specs/2026-11-03-customer-retention-multi-item-group-design.md`

## Global Constraints

- Exact Item Groups only; do not include descendants.
- Blank selection means all groups.
- Keep legacy scalar and prepared-report compatibility.
- Use parameter-bound SQL and no database writes.
- Do not run migration, Bench tests, reload-doc, restart, cache commands, or push.

## Review Focus

- Empty, scalar, JSON-array, and list filter values normalize consistently.
- Multiple item lines or groups do not multiply invoice counts.
- Selected groups are combined for report calculations but separated in tooltips.
- Missing group/year combinations display zero without extra per-row queries.
- Prepared reports restore arrays and legacy scalar selections in Frappe v12.

---

### Task 1: Server normalization and combined aggregate scope

**Files:**
- Modify: `worldshading/worldshading/report/customer_retention_analysis/customer_retention_analysis.py`
- Test: `worldshading/worldshading/report/customer_retention_analysis/test_customer_retention_analysis.py`

**Interfaces:**
- Consumes: `filters.item_group` as empty, scalar, JSON-array string, tuple, or list.
- Produces: normalized ordered `filters.item_group` list and bound `item.item_group in %(item_groups)s` aggregate paths.

- [x] Write failing tests for empty/scalar/JSON/list normalization, de-duplication, and multiple selected groups.
- [x] Run focused Python tests and confirm failures are caused by scalar-only behavior.
- [x] Implement Python 3.6-compatible normalization and change sales, last-invoice, preferred-group, and overall-sales gates to list semantics.
- [x] Run focused tests and confirm combined sales and distinct invoice contracts pass.

### Task 2: Per-group yearly tooltip enrichment

**Files:**
- Modify: `worldshading/worldshading/report/customer_retention_analysis/customer_retention_analysis.py`
- Test: `worldshading/worldshading/report/customer_retention_analysis/test_customer_retention_analysis.py`

**Interfaces:**
- Consumes: normalized selected groups, displayed customers, explicit reporting years.
- Produces: `selected_item_groups` and `selected_item_group_sales` row metadata with zero-filled group/year combinations.

- [x] Write a failing enrichment test for two groups across current, comparison, and historical years, including a missing zero-sales combination.
- [x] Run the focused test and verify RED.
- [x] Add one bounded grouped enrichment query and populate ordered row metadata without changing row order.
- [x] Run all Python report tests and verify PASS.

### Task 3: ERPNext v12 multiselect and tooltip presentation

**Files:**
- Modify: `worldshading/worldshading/report/customer_retention_analysis/customer_retention_analysis.js`
- Test: `worldshading/worldshading/report/customer_retention_analysis/test_customer_retention_analysis_client.js`

**Interfaces:**
- Consumes: `selected_item_groups`, `selected_item_group_sales`, overall yearly totals, and legacy `selected_item_group` rows.
- Produces: native `MultiSelectList`, readable filter summary, prepared restoration, and per-group yearly tooltips.

- [x] Write failing client tests for `MultiSelectList`, Link options, array summary display, combined tooltip breakdown, zero group sales, and legacy scalar restoration.
- [x] Run the Node harness and verify RED.
- [x] Implement v12-compatible multiselect data loading and tooltip formatting; preserve legacy tooltip metadata fallback.
- [x] Run Python tests, Node tests, both JavaScript syntax checks, and `git diff --check`.
- [x] Review SQL binding, return semantics, prepared restoration, and unrelated-file preservation.
- [x] Commit only scoped report, test, design, and plan files.
