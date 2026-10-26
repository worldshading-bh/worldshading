# Customer Retention Item Group and Comparison Year Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add exact Item Group-scoped retention analysis and an independent prior-five-year Comparison Year to the existing prepared Customer Retention Analysis report.

**Architecture:** Extend the pure filter/year/calculation layer first, add a controlled SQL aggregation path for Item Group scope, then wire dynamic v12 client filters and prepared-filter restoration. Blank Item Group keeps the current Sales Invoice path; selected Item Group uses Sales Invoice Item values and distinct parent invoices without schema or stored analytics data.

**Tech Stack:** ERPNext/Frappe 12, Python 3.6, MariaDB, Script Report Python/JavaScript, Python `unittest`, Node client harness.

**Spec:** `docs/superpowers/specs/2026-10-26-customer-retention-item-group-comparison-design.md`

## Global Constraints

- Do not run `bench migrate`, `bench test`, `reload-doc`, report execution against production, restarts, backups, restores, or cache-clearing commands.
- Product changes stay inside the existing Customer Retention Analysis Python, JavaScript, and test files; documentation stays under `docs/superpowers`.
- Do not modify ERPNext or Frappe core files.
- Support ERPNext/Frappe v12 and Python 3.6; no type annotations, dataclasses, `frappe.qb`, f-strings, or post-v12 APIs.
- The report remains read-only and never updates Customer, Item, Sales Invoice, Campaign Customer, accounting, stock, or workflow data.
- Calendar periods remain full years; do not annualize or prorate.
- Preserve current 45/45/10 Importance weighting and ±20 percent status thresholds.
- Preserve unrelated working-tree changes, especially `campaign_customer.json` and `campaign_interaction_log.json`; never stage them.
- Do not push. Commit only explicitly scoped report/documentation paths after task verification succeeds.

## Review Focus

- Several matching lines on one invoice contribute each item amount while invoice count remains one; Task 2 tests the aggregate SQL contract.
- A return-only Item Group customer retains negative sales, zero purchase invoice count, and no Last Invoice Date; Task 2 covers all three.
- Analysis 2026 versus Comparison 2021 with Previous Years 3 excludes 2022 while retaining 2025/2024/2023 columns; Tasks 1 and 2 test the non-contiguous year set.
- Positive current sales with zero Comparison Year sales but positive other relevant history is Reactivated, not New; Task 1 pins classification.
- Historical Prepared Report restoration updates choices from saved Analysis Year before applying saved Comparison Year; Task 3 tests the order.

---

## File Structure

- `customer_retention_analysis.py` — validation, year sets, calculations, aggregate SQL, enrichment, and execution.
- `customer_retention_analysis.js` — Item Group and dynamic Comparison Year filters, terminology, summary, and prepared restoration.
- `test_customer_retention_analysis.py` — calculation, SQL-contract, orchestration, and source-contract tests.
- `test_customer_retention_analysis_client.js` — executable dynamic-filter and prepared-restoration tests.

All four files are under `worldshading/worldshading/report/customer_retention_analysis/`.

### Task 0: Preserve the Approved Current Report Baseline

**Files:**

- Existing modified report Python, JavaScript, and their two test files.
- Exclude: both Campaign DocType JSON files and the new design/plan documents.

**Interfaces:**

- Consumes: the already approved Importance, tooltip, Rank removal, and visual changes currently in the working tree.
- Produces: a clean scoped baseline commit so new Comparison Year and Item Group changes have reviewable diffs.

- [ ] **Step 1: Verify the current report baseline**

Run the existing full Python test file, Node client harness, both Node syntax checks, and `git diff --check`. Expected: all exit 0.

- [ ] **Step 2: Review and stage only the four report files**

Confirm `git diff --cached --name-only` contains only `customer_retention_analysis.py`, `.js`, and their two test files. The Campaign DocType JSON files and new docs remain unstaged.

- [ ] **Step 3: Commit the approved baseline**

```bash
git commit -m "feat: improve customer retention prioritization"
```

### Task 1: Comparison Year Contracts and Calculations

**Files:**

- Modify: `worldshading/worldshading/report/customer_retention_analysis/customer_retention_analysis.py`
- Test: `worldshading/worldshading/report/customer_retention_analysis/test_customer_retention_analysis.py`

**Interfaces:**

- Consumes: existing normalized filters and year-indexed activity.
- Produces: `comparison_year`, `item_group`, `get_reporting_years(filters)`, Comparison-labelled columns/sorting, and comparison-aware status/row calculations.

- [ ] **Step 1: Write failing filter and year-set tests**

Assert Comparison Year defaults to Analysis Year minus one; Item Group defaults blank; only Analysis Year minus 1 through minus 5 are accepted; and 2026/2021/Previous Years 3 yields history `[2026, 2025, 2024, 2023]`, reporting years `[2026, 2025, 2024, 2023, 2021]`, and bounds 2021 through 2026 without selecting 2022.

- [ ] **Step 2: Run focused filter tests and verify RED**

Run the new methods with `/home/erpadmin/frappe-bench/env/bin/python -m unittest ...` from `apps/worldshading`.

Expected: FAIL because Comparison Year, Item Group normalization, and `get_reporting_years()` do not exist.

- [ ] **Step 3: Implement normalization and year helpers**

Keep `get_years(filters)` as ordinary history. Add `get_reporting_years(filters)` as an ordered de-duplicated union with Comparison Year; use the earliest relevant year for bounds.

- [ ] **Step 4: Write failing comparison calculation tests**

Use literal fixtures proving 2026 sales 80 versus 2024 sales 100 yields -20, -20 percent, Decreased, and the 2024 comparison invoice count; 2021 can be the baseline while Average Historical Sales/Total Invoice Count still use 2025/2024/2023; arbitrary-baseline New/Reactivated/Lost rules work; and Importance keeps 45/45/10 using comparison-based decrease.

- [ ] **Step 5: Run focused calculation tests and verify RED**

Expected: FAIL because calculations still use Analysis Year minus one.

- [ ] **Step 6: Implement comparison-aware calculations and columns**

Use Comparison Year for `previous_sales`, `previous_invoice_count`, change, decrease, percentage, direct status baseline, and visible labels. Preserve internal row names for prepared compatibility. Rename visible Previous Sales terminology to Comparison Sales; accept the legacy server sort value only as a compatibility alias.

- [ ] **Step 7: Run all Python report tests**

Run:

```bash
/home/erpadmin/frappe-bench/env/bin/python -m unittest worldshading.worldshading.report.customer_retention_analysis.test_customer_retention_analysis
```

Expected: all tests PASS without site/database access.

- [ ] **Step 8: Commit Task 1 scoped paths only**

Stage only the report Python/test files and approved design/plan docs. Exclude Campaign DocType JSON and client files.

```bash
git commit -m "feat: add retention comparison year"
```

### Task 2: Item Group-Scoped Aggregate Data

**Files:**

- Modify: `worldshading/worldshading/report/customer_retention_analysis/customer_retention_analysis.py`
- Test: `worldshading/worldshading/report/customer_retention_analysis/test_customer_retention_analysis.py`

**Interfaces:**

- Consumes: `filters.item_group`, `get_reporting_years(filters)`, comparison-aware rows.
- Produces: blank-filter customer-wide aggregation, selected-group item aggregation, group-aware last purchase/inactivity, and selected-year Item Group context.

- [ ] **Step 1: Write failing unfiltered SQL tests**

Assert blank Item Group retains `sum(si.base_net_total)`, contains no item join, and binds reporting years 2026/2025/2024/2023/2021 without 2022.

- [ ] **Step 2: Write failing Item Group aggregate tests**

For `PVC 680 GSM`, assert joins from Sales Invoice Item through Sales Invoice, Item, and Customer; bound exact Item Group and reporting years; `sum(sii.base_net_amount)`; distinct non-return invoice count; and existing Company/customer scope conditions.

- [ ] **Step 3: Run focused aggregate tests and verify RED**

Expected: FAIL because Item Group and explicit year membership do not affect aggregation.

- [ ] **Step 4: Implement controlled aggregate paths**

Use only server-selected SQL fragments and bound user values. Keep the current Sales Invoice query when blank; use item aggregation only when selected so joins cannot multiply overall totals.

- [ ] **Step 5: Write failing inactivity and return tests**

Assert selected-group Last Invoice Date uses a bound `exists` subquery over Sales Invoice Item plus Item and excludes returns. Cover return-only negative sales, zero invoice count, and no Last Invoice Date.

- [ ] **Step 6: Implement group-aware Last Invoice Date**

Preserve the simple query when blank; add the controlled `exists` clause only for selected Item Group.

- [ ] **Step 7: Write failing preferred-group tests**

Assert blank Item Group retains top three. When selected, bind exact group and explicit reporting years; expose only its positive amount as Top Item Group 1 with slots 2/3 blank and an explicit-year tooltip period.

- [ ] **Step 8: Implement selected-year Item Group enrichment**

Update `get_item_group_context()` and its period label without changing Campaign Customer enrichment or row order.

- [ ] **Step 9: Run all Python report tests**

Run Task 1's full Python command. Expected: all PASS with mocked database calls.

- [ ] **Step 10: Commit Task 2 scoped paths only**

```bash
git commit -m "feat: scope retention by item group"
```

### Task 3: Dynamic Filters, Prepared Restoration, and Final Verification

**Files:**

- Modify: `worldshading/worldshading/report/customer_retention_analysis/customer_retention_analysis.js`
- Modify: `worldshading/worldshading/report/customer_retention_analysis/test_customer_retention_analysis.py`
- Test: `worldshading/worldshading/report/customer_retention_analysis/test_customer_retention_analysis_client.js`

**Interfaces:**

- Consumes: server filters `analysis_year`, `comparison_year`, and `item_group`; existing prepared-filter endpoint.
- Produces: dynamic prior-five-year choices, immediate reset on Analysis Year change, ordered prepared restoration, filter summary values, and Comparison terminology/tooltips.

- [ ] **Step 1: Write failing client behavior tests**

Assert `get_comparison_year_options(2026)` returns 2025 through 2021; changing Analysis Year to 2024 changes options to 2023 through 2019 and resets only an invalid comparison; Item Group is a Link; summary includes both filters; and Sort By/help say Comparison Sales.

- [ ] **Step 2: Run Node harness and verify RED**

```bash
node worldshading/worldshading/report/customer_retention_analysis/test_customer_retention_analysis_client.js
```

Expected: FAIL because the helpers and filters do not exist.

- [ ] **Step 3: Implement filters and option synchronization**

Add v12-compatible helpers and bind Analysis Year changes without suppressing normal Query Report refresh behavior. Preserve the single Bootstrap Sort By tooltip.

- [ ] **Step 4: Write failing prepared-restoration test**

Restore saved Analysis Year 2024 plus Comparison Year 2021. Assert options are rebuilt for 2024 before 2021 is applied.

- [ ] **Step 5: Implement ordered prepared restoration**

Restore Analysis Year first, synchronize comparison options without an unwanted report run, then restore remaining filters and update summary/help.

- [ ] **Step 6: Run complete allowed verification**

Run:

```bash
/home/erpadmin/frappe-bench/env/bin/python -m unittest worldshading.worldshading.report.customer_retention_analysis.test_customer_retention_analysis
node worldshading/worldshading/report/customer_retention_analysis/test_customer_retention_analysis_client.js
node --check worldshading/worldshading/report/customer_retention_analysis/customer_retention_analysis.js
node --check worldshading/worldshading/report/customer_retention_analysis/test_customer_retention_analysis_client.js
git diff --check
```

Expected: every command exits 0; no Bench/site command runs.

- [ ] **Step 7: Review the full scoped diff**

Request read-only independent review focused on SQL multiplication, year membership, returns, classification, prepared restoration, v12 compatibility, and unrelated-file preservation. Fix Critical/Important findings test-first and rerun Step 6.

- [ ] **Step 8: Commit Task 3 scoped paths only**

```bash
git commit -m "feat: complete retention scope filters"
```

Do not push. Report commit hashes, verification evidence, untouched unrelated files, and manual browser steps: hard-refresh, choose Item Group and Comparison Year, click Rebuild, and inspect the completed Prepared Report.
