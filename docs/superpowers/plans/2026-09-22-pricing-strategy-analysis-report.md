# Pricing Strategy Analysis Report Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a read-only ERPNext v12 Script Report that analyzes item costs and historical sales and calculates regular, B2B, and four configurable quantity-tier prices.

**Architecture:** Keep the report in one standard report directory. Put pure validation, rounding, and pricing helpers at the top of the Python module; keep batched database readers separate; let `execute(filters)` orchestrate validation, reads, calculations, messages, and output. The JavaScript file defines runtime assumptions as filters and does not save configuration.

**Tech Stack:** ERPNext 12, Frappe 12 Script Reports, Python 3.6, JavaScript ES5-compatible syntax, MariaDB, `decimal.Decimal`, `unittest`.

**Spec:** `docs/superpowers/specs/2026-09-22-pricing-strategy-analysis-report-design.md`

## Global Constraints

- Production environment: do not run `bench test`, `bench migrate`, `bench restart`, backups, cache-clearing commands, or database writes.
- Create no DocTypes, custom fields, scheduled tasks, or mutation endpoints.
- Modify no ERPNext core files and no existing World Shading pricing implementation.
- Keep all Python compatible with Python 3.6: no dataclasses, type hints, f-string-only interfaces, or modern Frappe APIs.
- Use parameterized SQL only for grouped/batched reads that Frappe v12 cannot express efficiently.
- Preserve the workbook's markup-on-cost model while separately reporting true gross margin.

## Review Focus

- Empty filters or filters serialized as strings must normalize predictably and must never cause an unhandled arithmetic exception.
- Returns that make purchase or sales net quantity zero or negative must leave average rates blank and add a warning.
- Multiple warehouses with negative stock must not distort the positive-stock weighted valuation; use the latest Stock Ledger valuation fallback when no positive stock remains.
- Duplicate valid Item Price rows must be selected deterministically and flagged rather than silently producing unstable results.
- Tier gaps are allowed and reported, while overlaps, unordered tiers, and a non-final open-ended tier are rejected.

---

### Task 1: Pure calculation and validation helpers

**Files:**
- Create: `worldshading/worldshading/report/pricing_strategy_analysis/__init__.py`
- Create: `worldshading/worldshading/report/pricing_strategy_analysis/pricing_strategy_analysis.py`
- Create: `worldshading/worldshading/report/pricing_strategy_analysis/test_pricing_strategy_analysis.py`

**Interfaces:**
- Consumes: Frappe filter dictionaries and values convertible to strings.
- Produces: `to_decimal(value)`, `round_to_increment(value, increment, method)`, `validate_and_normalize_filters(filters)`, `calculate_price(loaded_cost, markup_percent, vat_percent, increment, method)`, `calculate_item_row(item, context)`, and `compose_warnings(values)`.

- [ ] **Step 1: Write failing pure-helper tests**

Add `unittest.TestCase` cases that assert:

```python
def test_workbook_regular_example(self):
    result = report.calculate_price("46", "43", "10", "1", "Nearest")
    self.assertEqual(result["gross_price"], Decimal("72"))
    self.assertEqual(result["net_price"], Decimal("65.455"))

def test_rounding_methods(self):
    self.assertEqual(report.round_to_increment("72.11", "0.5", "Nearest"), Decimal("72.0"))
    self.assertEqual(report.round_to_increment("72.11", "0.5", "Up"), Decimal("72.5"))
    self.assertEqual(report.round_to_increment("72.89", "0.5", "Down"), Decimal("72.5"))

def test_markup_and_margin_are_distinct(self):
    result = report.calculate_price("46", "43", "10", "1", "Nearest")
    self.assertEqual(result["actual_markup_percent"], Decimal("42.293"))
    self.assertEqual(result["gross_margin_percent"], Decimal("29.722"))
```

Also test negative numeric inputs, zero increment, reversed dates, tier overlap, tier gaps, an open-ended non-final tier, missing cost, expense burden, price-action thresholds, warning order, empty/string filter normalization, and zero denominators.

- [ ] **Step 2: Run the helper test module and confirm RED**

Run:

```bash
/home/erpadmin/frappe-bench/env/bin/python -m unittest worldshading.worldshading.report.pricing_strategy_analysis.test_pricing_strategy_analysis
```

Expected: import or missing-function failure. This uses the bench Python 3.6
interpreter directly and is not `bench test`.

- [ ] **Step 3: Implement the pure helpers**

Use `Decimal(str(value or 0))`, `ROUND_HALF_UP`, `ROUND_CEILING`, and `ROUND_FLOOR`. Return monetary values quantized to three decimals and percentages quantized to three decimals. Validate tiers as four dictionaries containing `minimum`, `maximum`, and `markup`; return normalized filters plus a list of gap messages.

`calculate_price` must return:

```python
{
    "net_price": Decimal("65.455"),
    "gross_price": Decimal("72.000"),
    "profit": Decimal("19.455"),
    "actual_markup_percent": Decimal("42.293"),
    "gross_margin_percent": Decimal("29.722")
}
```

for the workbook regular example.

- [ ] **Step 4: Run helper tests and confirm GREEN**

Run the same direct unittest command. Expected: all helper tests pass without
connecting to a live site.

- [ ] **Step 5: Commit Task 1**

```bash
git add worldshading/worldshading/report/pricing_strategy_analysis
git commit -m "feat: add pricing strategy calculations"
```

### Task 2: Batched ERPNext read layer

**Files:**
- Modify: `worldshading/worldshading/report/pricing_strategy_analysis/pricing_strategy_analysis.py`
- Modify: `worldshading/worldshading/report/pricing_strategy_analysis/test_pricing_strategy_analysis.py`

**Interfaces:**
- Consumes: normalized filters from `validate_and_normalize_filters(filters)` and a list of item codes.
- Produces: `get_items(filters)`, `get_stock_data(filters, item_codes)`, `get_purchase_data(filters, item_codes)`, `get_sales_data(filters, item_codes)`, and `get_item_prices(filters, item_codes)` dictionaries keyed by item code.

- [ ] **Step 1: Write failing database-boundary tests with mocks**

Patch `frappe.get_all`, `frappe.db.sql`, and `frappe.db.get_value` to verify:

```python
def test_sales_zero_net_quantity_has_no_average(self):
    rows = [{"item_code": "A", "sales_qty": 0, "sales_value": 20}]
    normalized = report.normalize_sales_rows(rows)
    self.assertIsNone(normalized["A"]["weighted_average_sold_rate"])
    self.assertIn("Sales returns equal or exceed sales", normalized["A"]["warnings"])

def test_duplicate_item_prices_are_deterministic(self):
    rows = [
        {"item_code": "A", "price_list": "Standard Selling", "price_list_rate": 10, "valid_from": "2026-01-01", "creation": "2026-01-01 10:00:00"},
        {"item_code": "A", "price_list": "Standard Selling", "price_list_rate": 11, "valid_from": "2026-02-01", "creation": "2026-02-01 10:00:00"}
    ]
    prices = report.normalize_item_prices(rows, "Standard Selling", None)
    self.assertEqual(prices["A"]["normal"], Decimal("11"))
    self.assertIn("Multiple valid normal Item Prices", prices["A"]["warnings"])
```

Also assert parameterized SQL arguments, company/warehouse constraints, descendant Item Group expansion, return normalization, Stock UOM rates, latest-purchase lookup without From Date, weighted purchases inside the date window, positive-stock valuation, SLE fallback, and currency mismatch validation.

- [ ] **Step 2: Run tests and confirm RED**

Run the direct unittest command from Task 1. Expected: failures for the missing read/normalization functions.

- [ ] **Step 3: Implement batched readers and normalizers**

Use one bounded query per dataset rather than queries inside the item loop. Use tuple parameters for item codes and named parameters for company, dates, warehouse, and price lists. Normalize query rows in pure functions so mock tests can exercise return imbalance, price duplication, and fallbacks.

For current valuation, aggregate only positive `Bin.actual_qty`. For an item with no positive aggregate, read its latest `Stock Ledger Entry.valuation_rate` on or before To Date. For Item Price, sort valid rows by `valid_from DESC, creation DESC, name DESC` before deterministic selection.

- [ ] **Step 4: Run tests and confirm GREEN**

Run the direct unittest command. Expected: read-layer and pure-helper tests pass.

- [ ] **Step 5: Commit Task 2**

```bash
git add worldshading/worldshading/report/pricing_strategy_analysis
git commit -m "feat: add pricing strategy data sources"
```

### Task 3: Script Report orchestration and columns

**Files:**
- Modify: `worldshading/worldshading/report/pricing_strategy_analysis/pricing_strategy_analysis.py`
- Modify: `worldshading/worldshading/report/pricing_strategy_analysis/test_pricing_strategy_analysis.py`

**Interfaces:**
- Consumes: helpers and data maps from Tasks 1-2.
- Produces: Frappe Script Report `execute(filters=None)` returning `(columns, data, message, chart)` and `get_columns(filters)`.

- [ ] **Step 1: Write failing orchestration tests**

Mock all readers and assert that `execute`:

```python
columns, data, message, chart = report.execute(filters)
self.assertEqual(data[0]["item_code"], "A")
self.assertEqual(data[0]["recommended_regular_gross"], 72.0)
self.assertEqual(data[0]["suggested_action"], "Increase Price")
self.assertIsNone(chart)
```

Test Include Items Without Sales, a missing-cost row with blank recommendations, tier labels built from runtime ranges, gap messages, no-recent-sales warnings, current-price-below-cost warning, and report output consisting only of JSON-serializable values.

- [ ] **Step 2: Run tests and confirm RED**

Run the direct unittest command. Expected: failure for missing `execute`/columns behavior.

- [ ] **Step 3: Implement orchestration and output columns**

Build columns in the exact groups from the spec. Construct four tier column groups dynamically while retaining stable fieldnames `tier_1_*` through `tier_4_*`. Convert Decimal values to floats only at the final report serialization boundary. Return gap information as the standard report message and return `None` for chart.

Keep `execute` shallow: validate, obtain items, fetch five maps, call `calculate_item_row` for every item, filter no-sales rows when requested, and return output.

- [ ] **Step 4: Run tests and confirm GREEN**

Run the direct unittest command. Expected: all report Python tests pass.

- [ ] **Step 5: Commit Task 3**

```bash
git add worldshading/worldshading/report/pricing_strategy_analysis
git commit -m "feat: assemble pricing strategy report"
```

### Task 4: ERPNext report metadata and filter interface

**Files:**
- Create: `worldshading/worldshading/report/pricing_strategy_analysis/pricing_strategy_analysis.json`
- Create: `worldshading/worldshading/report/pricing_strategy_analysis/pricing_strategy_analysis.js`
- Modify: `worldshading/worldshading/report/pricing_strategy_analysis/test_pricing_strategy_analysis.py`

**Interfaces:**
- Consumes: filter fieldnames and allowed values defined by `validate_and_normalize_filters`.
- Produces: standard report registration named `Pricing Strategy Analysis` and browser filters passed to `execute`.

- [ ] **Step 1: Add failing metadata and static-contract tests**

Read JSON/JS as text and assert:

```python
self.assertEqual(metadata["report_name"], "Pricing Strategy Analysis")
self.assertEqual(metadata["report_type"], "Script Report")
self.assertEqual(metadata["ref_doctype"], "Item")
self.assertEqual(sorted(row["role"] for row in metadata["roles"]), ["Accounts Manager", "System Manager"])
self.assertIn('"fieldname": "cost_source"', javascript)
self.assertIn('"fieldname": "tier_4_markup"', javascript)
```

Also assert the complete required fieldname set, exact Cost Source and Rounding Method options, workbook defaults, and absence of mutation buttons or RPC calls.

- [ ] **Step 2: Run tests and confirm RED**

Run the direct unittest command. Expected: file-not-found failure for metadata/client files.

- [ ] **Step 3: Create JSON metadata and JavaScript filters**

Register the standard report under module `Worldshading`, reference DocType `Item`, no prepared report, no total row, and roles Accounts Manager/System Manager.

Use `frappe.query_reports["Pricing Strategy Analysis"] = {filters: [...]}`. Use functions only for safe defaults and link queries. Supply all spec filters with the exact backend fieldnames. Use ordinary ES5-compatible function syntax and no external library.

- [ ] **Step 4: Run tests and static checks**

Run:

```bash
/home/erpadmin/frappe-bench/env/bin/python -m unittest worldshading.worldshading.report.pricing_strategy_analysis.test_pricing_strategy_analysis
/home/erpadmin/frappe-bench/env/bin/python -m json.tool worldshading/worldshading/report/pricing_strategy_analysis/pricing_strategy_analysis.json >/dev/null
/home/erpadmin/frappe-bench/env/bin/python -m py_compile worldshading/worldshading/report/pricing_strategy_analysis/pricing_strategy_analysis.py worldshading/worldshading/report/pricing_strategy_analysis/test_pricing_strategy_analysis.py
```

Expected: all commands exit zero. None invokes bench or writes production data.

- [ ] **Step 5: Commit Task 4**

```bash
git add worldshading/worldshading/report/pricing_strategy_analysis
git commit -m "feat: register pricing strategy report"
```

### Task 5: Final verification and documentation alignment

**Files:**
- Modify if necessary: `worldshading/worldshading/report/pricing_strategy_analysis/*`
- Modify if necessary: `docs/superpowers/specs/2026-09-22-pricing-strategy-analysis-report-design.md`

**Interfaces:**
- Consumes: completed report files.
- Produces: verified source ready for the user's production deployment process.

- [ ] **Step 1: Run the permitted verification suite**

Run the direct unittest, JSON parser, and Python compile commands from Task 4. Run `git diff --check` and inspect `git status --short`.

- [ ] **Step 2: Compare implementation to every spec section**

Verify filter defaults, roles, all output columns, cost-source behavior, VAT-inclusive rounding, return handling, Item Price selection, warnings, no writes, no N+1 queries, and Python 3.6 syntax. Correct any discrepancy and add a regression test for it.

- [ ] **Step 3: Review interaction with existing protected B2B pricing**

Confirm the report only reads B2B Item Price records and does not reference deprecated `pb_price_list` fields or alter `business_pricing.py`.

- [ ] **Step 4: Review the complete diff for scope and unrelated changes**

Use:

```bash
git diff HEAD~4 -- worldshading/worldshading/report/pricing_strategy_analysis docs/superpowers/specs/2026-09-22-pricing-strategy-analysis-report-design.md
git status --short
```

Ensure the existing dynamic-rounding files and untracked workbook were never staged or modified by this work.

- [ ] **Step 5: Commit verification corrections if any**

If Task 5 required source corrections, commit only the pricing report paths with message `fix: complete pricing strategy report verification`. If no corrections were needed, create no empty commit.
