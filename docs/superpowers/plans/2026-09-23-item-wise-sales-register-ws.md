# Item-wise Sales Register WS Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a prepared ERPNext v12 item-wise sales report that combines direct and packed sales while exactly preserving submitted Sales Invoice net revenue.

**Architecture:** A database-independent allocation engine converts direct and packed inputs into reconciled transaction rows. A bulk SQL reader supplies those inputs and aggregates them for the new invoice/item report and Pricing Strategy Analysis. Report-specific Python assembles columns and enrichment, while JavaScript adapts Purchase Plan UI behavior.

**Tech Stack:** Python 3.6, Frappe/ERPNext v12, MariaDB, ES5-compatible JavaScript, Frappe DataTable, `unittest`, and `Decimal`.

**Spec:** `docs/superpowers/specs/2026-09-23-item-wise-sales-register-ws-design.md`

## Global Constraints

- Keep all code compatible with ERPNext/Frappe v12 and Python 3.6.
- Do not modify ERPNext core or `pos_bahrain`.
- Do not create DocTypes or alter database schema.
- Do not alter Prepared Report cleanup settings.
- Do not write production data or run forbidden bench/service operations.
- Preserve unrelated working-tree changes.

## Review Focus

- Inconsistent packed signs on returns must normalize to the parent sign and reconcile exactly.
- Duplicate parent rows must allocate at invoice/parent-item pool level and show ambiguity.
- A packed-child Item filter must still fetch its complete parent pool before filtering output.
- Warehouse filtering must not corrupt bundle allocation weights.
- Multi-component currency rounding must assign the remainder deterministically.

---

### Task 1: Pure packed-revenue allocation engine

**Files:**
- Create: `worldshading/reporting/__init__.py`
- Create: `worldshading/reporting/item_wise_sales.py`
- Create: `worldshading/reporting/test_item_wise_sales.py`

**Interfaces:**
- Consumes: dictionaries representing Sales Invoice Item and Packed Item rows.
- Produces: `allocate_parent_pool(parent_rows, packed_rows, currency_precision=3)` and `normalize_transaction_rows(direct_rows, packed_rows, currency_precision=3)`.

- [ ] **Step 1: Write failing allocation tests**

Add `unittest.TestCase` cases for direct-only, packed residual, discounted scaling, multiple components, negative returns, duplicate parents, missing monetary weights, zero quantity with value, mixed direct/packed Items, and deterministic rounding. Assert the invariant:

```python
self.assertEqual(sum(row["net_amount"] for row in result), Decimal("80.000"))
```

Also assert warning codes, quantities, Sales Basis, and stable ordering.

- [ ] **Step 2: Run tests and verify failure**

```bash
./env/bin/python -m unittest worldshading.reporting.test_item_wise_sales -v
```

Expected: failure because the module/functions do not exist.

- [ ] **Step 3: Implement Decimal allocation**

Implement the two documented interfaces using `Decimal(str(value or 0))`, absolute weights, parent sign, and final-row rounding correction. Never generate revenue for an unmatched packed group. Merge by invoice and Item Code and deduplicate warnings stably.

- [ ] **Step 4: Run focused tests**

Run Step 2 again. Expected: all Task 1 tests pass.

- [ ] **Step 5: Commit**

```bash
git add worldshading/reporting
git commit -m "feat: add packed sales allocation engine"
```

### Task 2: Bulk sales reader and aggregate interface

**Files:**
- Modify: `worldshading/reporting/item_wise_sales.py`
- Modify: `worldshading/reporting/test_item_wise_sales.py`

**Interfaces:**
- Consumes: company/date and optional item/customer/warehouse/project/source filters.
- Produces: `get_transaction_rows(filters)` and `get_item_sales_aggregates(filters, item_codes=None)`.

- [ ] **Step 1: Write failing query and aggregate tests**

Mock `frappe.db.sql`; assert direct and packed SQL use `si.posting_date`, company, docstatus, and each optional filter, and never use `pi.creation`. Test a filtered packed child with an unfiltered parent pool, warehouse/source output filtering, Direct + Packed distinct invoice counting, last date, weighted rate, and returns-exceed-sales warning.

- [ ] **Step 2: Run tests and verify failure**

```bash
./env/bin/python -m unittest worldshading.reporting.test_item_wise_sales -v
```

Expected: failures for missing reader functions.

- [ ] **Step 3: Implement bounded bulk reads**

Implement filter validation, one direct query, one packed query joined to Sales Invoice, and bulk Item metadata. Fetch complete allocation pools for selected packed children. Apply output filters after allocation where early filtering would corrupt reconciliation. Return aggregate keys for quantity, value, weighted/last/low/high rates, invoice count, last date, and warnings.

- [ ] **Step 4: Run focused tests**

Run Step 2 again. Expected: all allocation and reader tests pass.

- [ ] **Step 5: Commit**

```bash
git add worldshading/reporting/item_wise_sales.py worldshading/reporting/test_item_wise_sales.py
git commit -m "feat: add bulk item sales reader"
```

### Task 3: Script Report backend, metadata, and UI

**Files:**
- Create: `worldshading/worldshading/report/item_wise_sales_register_ws/__init__.py`
- Create: `worldshading/worldshading/report/item_wise_sales_register_ws/item_wise_sales_register_ws.py`
- Create: `worldshading/worldshading/report/item_wise_sales_register_ws/item_wise_sales_register_ws.js`
- Create: `worldshading/worldshading/report/item_wise_sales_register_ws/item_wise_sales_register_ws.json`
- Create: `worldshading/worldshading/report/item_wise_sales_register_ws/test_item_wise_sales_register_ws.py`

**Interfaces:**
- Consumes: `get_transaction_rows(filters)` from Task 2.
- Produces: Script Report `execute(filters=None)` returning columns, rows, message, and chart placeholder.

- [ ] **Step 1: Write failing report tests**

Mock the shared reader and enrichment calls. Assert compact column order, detail-only columns/queries, tax/total arithmetic, warning summaries, filter forwarding, company-only Bin stock, Item Default supplier selection, and metadata values `prepared_report=1`, `disable_prepared_report=0`, and `ref_doctype=Sales Invoice`.

- [ ] **Step 2: Run tests and verify failure**

```bash
./env/bin/python -m unittest worldshading.worldshading.report.item_wise_sales_register_ws.test_item_wise_sales_register_ws -v
```

Expected: failure because the package does not exist.

- [ ] **Step 3: Implement backend and metadata**

Build compact/detailed columns separately. Batch-load Item, supplier, company stock, payments, sales-team/employee fields, and taxes. Use ERPNext v12 item-wise tax JSON semantics and reconciled proportions. Produce stable distinct-value strings and a concise warning summary.

- [ ] **Step 4: Implement report JavaScript**

Define required filters using ES5 syntax. Adapt Purchase Plan's labels, summary, prepared-filter restoration/download binding, sticky columns, selected-row persistence, and important colors. Add a toolbar color input stored under a report-specific `localStorage` key.

- [ ] **Step 5: Run tests and parsers**

```bash
./env/bin/python -m unittest worldshading.worldshading.report.item_wise_sales_register_ws.test_item_wise_sales_register_ws -v
./env/bin/python -m json.tool worldshading/worldshading/report/item_wise_sales_register_ws/item_wise_sales_register_ws.json >/dev/null
node --check worldshading/worldshading/report/item_wise_sales_register_ws/item_wise_sales_register_ws.js
```

Expected: all commands pass.

- [ ] **Step 6: Commit**

```bash
git add worldshading/worldshading/report/item_wise_sales_register_ws
git commit -m "feat: add item-wise sales register ws"
```

### Task 4: Pricing Strategy Analysis parity

**Files:**
- Modify: `worldshading/worldshading/report/pricing_strategy_analysis/pricing_strategy_analysis.py`
- Modify: `worldshading/worldshading/report/pricing_strategy_analysis/test_pricing_strategy_analysis.py`

**Interfaces:**
- Consumes: `get_item_sales_aggregates(filters, item_codes=None)` from Task 2.
- Produces: existing `get_sales_data(filters, item_codes)` contract unchanged.

- [ ] **Step 1: Write failing parity tests**

Patch the shared helper and assert Pricing Strategy forwards its filters and returns helper quantities, values, rates, dates, counts, and warnings unchanged. Add a fabricated-row test proving both paths agree.

- [ ] **Step 2: Run tests and verify failure**

```bash
./env/bin/python -m unittest worldshading.worldshading.report.pricing_strategy_analysis.test_pricing_strategy_analysis -v
```

Expected: new parity tests fail against the direct-only query.

- [ ] **Step 3: Delegate the existing reader**

Keep `get_sales_data(filters, item_codes)` and delegate to the shared aggregate helper. Preserve all return keys and warning behavior.

- [ ] **Step 4: Run all focused tests**

```bash
./env/bin/python -m unittest worldshading.reporting.test_item_wise_sales worldshading.worldshading.report.item_wise_sales_register_ws.test_item_wise_sales_register_ws worldshading.worldshading.report.pricing_strategy_analysis.test_pricing_strategy_analysis -v
```

Expected: all focused tests pass.

- [ ] **Step 5: Commit**

```bash
git add worldshading/worldshading/report/pricing_strategy_analysis
git commit -m "refactor: share packed sales with pricing analysis"
```

### Task 5: Compatibility and reconciliation verification

**Files:**
- Modify only if verification exposes a defect in Tasks 1-4 files.

**Interfaces:**
- Consumes: all report components.
- Produces: verified files ready for user-run `reload-doc`.

- [ ] **Step 1: Compile Python with the production interpreter**

```bash
./env/bin/python -m compileall -q apps/worldshading/worldshading/reporting apps/worldshading/worldshading/worldshading/report/item_wise_sales_register_ws apps/worldshading/worldshading/worldshading/report/pricing_strategy_analysis
```

Expected: exit zero.

- [ ] **Step 2: Parse JavaScript and JSON**

```bash
node --check apps/worldshading/worldshading/worldshading/report/item_wise_sales_register_ws/item_wise_sales_register_ws.js
./env/bin/python -m json.tool apps/worldshading/worldshading/worldshading/report/item_wise_sales_register_ws/item_wise_sales_register_ws.json >/dev/null
```

Expected: both commands exit zero.

- [ ] **Step 3: Run the full focused suite**

Run Task 4 Step 4. Expected: all tests pass without database writes.

- [ ] **Step 4: Inspect scope**

```bash
git -C apps/worldshading diff --check
git -C apps/worldshading status --short
git -C apps/erpnext status --short
git -C apps/pos_bahrain status --short
```

Confirm no implementation changes in core or `pos_bahrain`, and preserve unrelated files.

- [ ] **Step 5: Reconcile a read-only production sample**

Invoke the helper for a narrow date range and compare each invoice's report net total to included Sales Invoice Item `base_net_amount`. Do not save documents or update the database. Expected: zero unexplained difference at currency precision, with known ambiguity warnings visible.

- [ ] **Step 6: Commit verification fixes if needed**

Stage and commit only exact report files changed during verification.

- [ ] **Step 7: Hand off reload command**

Provide, but do not run:

```bash
bench --site erp.worldshading.com reload-doc worldshading report item_wise_sales_register_ws
```
