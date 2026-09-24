# Pricing Strategy Price Update Actions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add production-safe bulk Item Price create/update from the first 50 rows of a completed Pricing Strategy Analysis Prepared Report, plus a non-writing Update Pricing Rule placeholder.

**Architecture:** The report client extracts the first 50 displayed item codes and requests a server-generated preview. The server validates the Prepared Report, reads its saved compressed result, resolves current Item Price documents, and stores a short-lived user-bound preview token; execution revalidates concurrent state before saving through normal ERPNext documents. JavaScript presents the preview and explicit confirmation, while the Pricing Rule button remains informational.

**Tech Stack:** ERPNext 12, Frappe 12, Python 3.6, MariaDB, JavaScript ES5-compatible report UI, Python `unittest`.

**Spec:** `docs/superpowers/specs/2026-09-24-pricing-strategy-price-update-actions-design.md`

## Global Constraints

- Production server: preserve unrelated working-tree changes and never modify ERPNext core.
- Remain compatible with ERPNext/Frappe v12 and Python 3.6; no type annotations, dataclasses, `frappe.qb`, optional chaining, or modern-only APIs.
- No new DocType, migration, restart, cache clear, `bench test`, or database update command.
- Process at most 50 unique item rows in displayed order; if more exist, only the first 50 are considered.
- Use recommended net prices, not VAT-inclusive gross prices.
- Regular is required; B2B is processed only when the saved Prepared Report has a B2B Price List.
- Never use `ignore_permissions` for Item Price creation or update.
- Require explicit confirmation before any write and preserve the Prepared Report as the immutable reference.
- The Update Pricing Rule action must make no write call in this phase.

## Review Focus

- A displayed total row or duplicate Item Code must not consume an extra update slot; the first 50 unique real items remain in display order.
- A tampered client price or price-list name must not override values saved in the Prepared Report; the server cross-checks the saved attachment and filters.
- A price changed after preview must abort the full write rather than overwrite the newer value.
- A Regular-only report must never invent a B2B update, while a B2B report must apply both price lists.
- Multiple currently applicable Item Prices must update only the same latest record selected by the report and must appear as a preview warning.

---

### Task 1: Prepared Report and request normalization helpers

**Files:**
- Modify: `worldshading/worldshading/report/pricing_strategy_analysis/pricing_strategy_analysis.py`
- Test: `worldshading/worldshading/report/pricing_strategy_analysis/test_pricing_strategy_analysis.py`

**Interfaces:**
- Produces: `_normalize_update_item_codes(item_codes) -> list[str]`, maximum 50 unique codes in input order.
- Produces: `_get_prepared_pricing_report(name) -> frappe._dict` with validated metadata and parsed filters.
- Produces: `_get_prepared_pricing_rows(prepared_report_name) -> list[dict]` loaded from the attached JSON gzip file.
- Consumes: Frappe v12 `Prepared Report`, `File`, `get_attachments`, and `gzip_decompress` APIs.

- [ ] **Step 1: Write failing normalization and Prepared Report tests**

Add tests that independently assert literal outcomes:

```python
def test_update_item_codes_keep_first_50_unique_real_items(self):
	values = ["ITEM-{0:03d}".format(index) for index in range(55)]
	values.insert(2, "ITEM-001")
	values.insert(4, "")
	result = report._normalize_update_item_codes(values)
	self.assertEqual(len(result), 50)
	self.assertEqual(result[:3], ["ITEM-000", "ITEM-001", "ITEM-002"])
	self.assertEqual(result[-1], "ITEM-049")

def test_prepared_report_must_be_completed_pricing_report(self):
	with patch.object(report.frappe.db, "get_value", return_value={
		"name": "PREP-1", "report_name": "Other Report",
		"status": "Completed", "owner": "test@example.com", "filters": "{}"
	}):
		with patch.object(report.frappe, "throw", side_effect=frappe.ValidationError):
			with self.assertRaises(frappe.ValidationError):
				report._get_prepared_pricing_report("PREP-1")
```

Add cases for missing name, non-completed status, non-owner without System Manager, malformed filters, and more than 50 unique codes. Test the gzip reader with a fake attachment containing a literal two-row JSON result.

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```bash
../../env/bin/python -m unittest \
  worldshading.worldshading.report.pricing_strategy_analysis.test_pricing_strategy_analysis.TestPricingStrategyItemPriceUpdateHelpers
```

Expected: failures because the three helper functions do not exist.

- [ ] **Step 3: Implement normalization and Prepared Report readers**

Add imports compatible with Python 3.6:

```python
import json

from frappe.core.doctype.prepared_report.prepared_report import gzip_decompress
from frappe.desk.form.load import get_attachments
```

Implement normalization without sorting:

```python
ITEM_PRICE_UPDATE_LIMIT = 50

def _normalize_update_item_codes(item_codes):
	item_codes = frappe.parse_json(item_codes) if isinstance(item_codes, str) else item_codes
	result = []
	seen = set()
	for value in item_codes or []:
		item_code = value.get("item_code") if isinstance(value, dict) else value
		item_code = str(item_code or "").strip()
		if not item_code or item_code in seen:
			continue
		seen.add(item_code)
		result.append(item_code)
		if len(result) == ITEM_PRICE_UPDATE_LIMIT:
			break
	return result
```

`_get_prepared_pricing_report` must query `name`, `report_name`, `status`, `owner`, and `filters`; require report name `Pricing Strategy Analysis`, status `Completed`, and owner equal to `frappe.session.user` unless the user has `System Manager`. Parse filters into a dictionary and run `validate_and_normalize_filters` for server-side master/filter validation.

`_get_prepared_pricing_rows` must read the first attachment from the validated Prepared Report, require a private `.json.gz` attachment, decompress its content, parse a JSON list, and keep dictionary rows only. Throw a clear validation error when the attachment is missing or malformed.

- [ ] **Step 4: Run focused and existing calculation tests**

Run:

```bash
../../env/bin/python -m unittest \
  worldshading.worldshading.report.pricing_strategy_analysis.test_pricing_strategy_analysis.TestPricingStrategyItemPriceUpdateHelpers \
  worldshading.worldshading.report.pricing_strategy_analysis.test_pricing_strategy_analysis.TestPricingStrategyCalculation
```

Expected: all selected tests pass.

- [ ] **Step 5: Commit Task 1**

```bash
git add worldshading/worldshading/report/pricing_strategy_analysis/pricing_strategy_analysis.py \
  worldshading/worldshading/report/pricing_strategy_analysis/test_pricing_strategy_analysis.py
git commit -m "feat: validate pricing update report inputs"
```

---

### Task 2: Server-side Item Price preview

**Files:**
- Modify: `worldshading/worldshading/report/pricing_strategy_analysis/pricing_strategy_analysis.py`
- Test: `worldshading/worldshading/report/pricing_strategy_analysis/test_pricing_strategy_analysis.py`

**Interfaces:**
- Consumes: Task 1 helpers and saved result fields `recommended_regular_net`, `recommended_b2b_net`, `current_normal_price`, `current_b2b_price`, `stock_uom`, `item_name`.
- Produces: `_resolve_item_price_target(item, price_list, report_to_date) -> dict` describing existing/latest target, duplicate count, and UOM.
- Produces: `preview_item_price_update(prepared_report_name=None, item_codes=None) -> dict` as a whitelisted method.
- Preview shape: `{token, prepared_report, requested_item_count, source_row_count, limited_to_first_50, entries, counts}`.

- [ ] **Step 1: Write failing preview tests**

Cover these literal behaviors:

```python
def test_preview_regular_only_classifies_update_create_and_unchanged(self):
	# Saved rows: A 12.000, B 20.000, C 30.000.
	# Existing Regular prices: A 10.000, B absent, C 30.000.
	preview = report.preview_item_price_update("PREP-1", ["A", "B", "C"])
	self.assertEqual([row["action"] for row in preview["entries"]],
		["Update", "Create", "Unchanged"])
	self.assertEqual(preview["counts"], {"create": 1, "update": 1, "unchanged": 1})
	self.assertFalse(any(row["price_list"] == "B2B" for row in preview["entries"]))
```

Add tests for Regular plus B2B, disabled item, missing/zero recommendation, invalid/same price lists, price-list currency, UOM-independent price list, duplicate active prices warning, item code absent from saved result, 51 client items becoming exactly 50, and a client-supplied row value being ignored in favor of the saved Prepared Report value.

- [ ] **Step 2: Run preview tests and verify RED**

Run:

```bash
../../env/bin/python -m unittest \
  worldshading.worldshading.report.pricing_strategy_analysis.test_pricing_strategy_analysis.TestPricingStrategyItemPricePreview
```

Expected: failure because `preview_item_price_update` and target resolution do not exist.

- [ ] **Step 3: Implement price-list, item, and target resolution**

Use `frappe.get_list`/`frappe.db.get_value` for validation. Resolve applicable Item Prices with the same constraints and ordering as `get_item_prices`: selling flag, Item Code, selected Price List, validity at the saved report `to_date`, and Stock UOM unless `price_not_uom_dependent` is enabled. Return the latest applicable target plus `duplicate_count`; never update all duplicates.

Represent every preview entry explicitly:

```python
{
	"item_code": "A",
	"item_name": "Item A",
	"stock_uom": "Nos",
	"price_list": "Regular Price",
	"price_kind": "Regular",
	"currency": "BHD",
	"current_rate": 10.0,
	"new_rate": 12.0,
	"action": "Update",
	"item_price_name": "IP-0001",
	"target_modified": "2026-09-24 10:00:00",
	"warning": ""
}
```

Rates must be normalized with `quantize_money`; reject non-positive values. Use the saved result, not client prices, as the recommendation source.

- [ ] **Step 4: Implement short-lived preview tokens**

Generate a 32-character token with `frappe.generate_hash(length=32)`. Store a payload under:

```python
"pricing-strategy-item-price-preview:{0}:{1}".format(frappe.session.user, token)
```

The cached payload includes the Prepared Report name, user, normalized entries, current target name/rate/modified fingerprint, and creation timestamp. Save for 600 seconds using:

```python
frappe.cache().set_value(cache_key, payload, expires_in_sec=600)
```

Return the token and display-safe preview. Do not expose internal cache keys.

- [ ] **Step 5: Run preview tests and full report tests**

Run:

```bash
../../env/bin/python -m unittest \
  worldshading.worldshading.report.pricing_strategy_analysis.test_pricing_strategy_analysis
```

Expected: all report tests pass.

- [ ] **Step 6: Commit Task 2**

```bash
git add worldshading/worldshading/report/pricing_strategy_analysis/pricing_strategy_analysis.py \
  worldshading/worldshading/report/pricing_strategy_analysis/test_pricing_strategy_analysis.py
git commit -m "feat: preview pricing report Item Price updates"
```

---

### Task 3: Atomic Item Price execution

**Files:**
- Modify: `worldshading/worldshading/report/pricing_strategy_analysis/pricing_strategy_analysis.py`
- Test: `worldshading/worldshading/report/pricing_strategy_analysis/test_pricing_strategy_analysis.py`

**Interfaces:**
- Consumes: the Task 2 user-bound cached preview payload.
- Produces: `execute_item_price_update(preview_token=None) -> dict` as a whitelisted method.
- Result shape: `{prepared_report, created, updated, unchanged, item_prices}`.

- [ ] **Step 1: Write failing execution tests**

Add tests with real document-like fakes whose `insert`, `save`, and `check_permission` side effects are observable:

```python
def test_execute_creates_updates_and_skips_unchanged_prices(self):
	result = report.execute_item_price_update("TOKEN-1")
	self.assertEqual(result["created"], 1)
	self.assertEqual(result["updated"], 1)
	self.assertEqual(result["unchanged"], 1)
	self.assertEqual(result["item_prices"], ["IP-NEW", "IP-OLD"])
```

Add cases for missing/expired token, token belonging to another user, second use of a consumed token, missing create permission, missing write permission, changed rate, changed `modified`, deleted target, a new competing applicable Item Price after preview, and a save failure that raises rather than returning partial success.

- [ ] **Step 2: Run execution tests and verify RED**

Run:

```bash
../../env/bin/python -m unittest \
  worldshading.worldshading.report.pricing_strategy_analysis.test_pricing_strategy_analysis.TestPricingStrategyItemPriceExecution
```

Expected: failure because `execute_item_price_update` does not exist.

- [ ] **Step 3: Implement token consumption and full preflight**

Load the cache key for the current user. Reject missing or malformed payloads. Before the first write:

- revalidate the completed Prepared Report and its saved filters;
- require `frappe.has_permission("Item Price", "create")` if any entry is Create;
- load every Update target and call `doc.check_permission("write")`;
- re-resolve every applicable target and compare name, rate, and `modified` to the preview fingerprint;
- ensure every recommendation remains positive and every item/price list remains valid.

Any mismatch calls `frappe.throw` before writes begin.

- [ ] **Step 4: Implement normal document writes**

For Update:

```python
item_price = frappe.get_doc("Item Price", entry["item_price_name"])
item_price.check_permission("write")
item_price.price_list_rate = entry["new_rate"]
item_price.save()
```

For Create:

```python
item_price = frappe.new_doc("Item Price")
item_price.item_code = entry["item_code"]
item_price.price_list = entry["price_list"]
item_price.price_list_rate = entry["new_rate"]
item_price.selling = 1
item_price.currency = entry["currency"]
item_price.uom = entry["uom"]
item_price.insert()
```

Do not set `valid_from` or use `ignore_permissions`. Delete the cache token only after all saves succeed. Return created, updated, unchanged counts and affected Item Price names. Let exceptions propagate so Frappe rolls back the request transaction.

- [ ] **Step 5: Run execution and full report tests**

Run:

```bash
../../env/bin/python -m unittest \
  worldshading.worldshading.report.pricing_strategy_analysis.test_pricing_strategy_analysis
```

Expected: all report tests pass.

- [ ] **Step 6: Commit Task 3**

```bash
git add worldshading/worldshading/report/pricing_strategy_analysis/pricing_strategy_analysis.py \
  worldshading/worldshading/report/pricing_strategy_analysis/test_pricing_strategy_analysis.py
git commit -m "feat: apply confirmed Item Price updates"
```

---

### Task 4: Report buttons, preview dialog, and confirmation

**Files:**
- Modify: `worldshading/worldshading/report/pricing_strategy_analysis/pricing_strategy_analysis.js`
- Test: `worldshading/worldshading/report/pricing_strategy_analysis/test_pricing_strategy_analysis.py`

**Interfaces:**
- Consumes: `preview_item_price_update(prepared_report_name, item_codes)` and `execute_item_price_update(preview_token)`.
- Produces: `get_pricing_update_item_codes(report)`, `show_item_price_update_dialog(report)`, and `show_pricing_rule_update_notice()`.

- [ ] **Step 1: Write failing UI contract tests**

Add assertions that the script registers both exact button names and both server methods, takes at most 50 unique item rows, uses `report.raw_data.doc.name`, renders a read-only preview table, warns when source rows exceed 50, calls `frappe.confirm`, freezes execution, and makes no Pricing Rule write call.

```python
self.assertIn('report.page.add_inner_button(__("Update Item Price")', javascript)
self.assertIn('report.page.add_inner_button(__("Update Pricing Rule")', javascript)
self.assertIn('preview_item_price_update', javascript)
self.assertIn('execute_item_price_update', javascript)
self.assertIn('frappe.confirm', javascript)
self.assertIn('slice(0, 50)', javascript)
self.assertIn('Pricing Rule update configuration is pending', javascript)
```

- [ ] **Step 2: Run the UI contract test and verify RED**

Run:

```bash
../../env/bin/python -m unittest \
  worldshading.worldshading.report.pricing_strategy_analysis.test_pricing_strategy_analysis.TestPricingStrategyReportFiles.test_report_metadata_and_filter_contract
```

Expected: failure because the buttons and dialog do not exist.

- [ ] **Step 3: Implement displayed-row selection and button registration**

In `onload`, add both inner buttons. `get_pricing_update_item_codes` must iterate `report.data`, ignore rows without `item_code`, de-duplicate in order, record the total unique count, and use `.slice(0, 50)` for the request. Require `report.raw_data.doc.name`; otherwise show a message instructing the user to open a completed Prepared Report.

- [ ] **Step 4: Implement the server preview and read-only dialog**

Call the preview endpoint with the Prepared Report name and first 50 codes. Render entries in a Frappe Dialog Table with `cannot_add_rows`, `cannot_delete_rows`, and read-only fields for Item, Item Name, Price List, Currency, Current Price, New Price, Action, and Warning. Show a highlighted first-50 notice when the client unique count exceeds 50.

The primary action label is **Continue**. It must not write directly; it opens `frappe.confirm` with counts and the Prepared Report name.

- [ ] **Step 5: Implement confirmed execution and Pricing Rule notice**

Inside the confirmation callback, call `execute_item_price_update` with `freeze: true` and a pricing-update freeze message. Disable the dialog primary button until the call completes. On success, hide the dialog and show created, updated, and unchanged counts. Do not refresh or rebuild the old Prepared Report automatically.

The Pricing Rule button calls only:

```javascript
frappe.msgprint(__("Pricing Rule update configuration is pending. No Pricing Rules were changed."));
```

- [ ] **Step 6: Run report tests and JavaScript syntax validation**

Run:

```bash
../../env/bin/python -m unittest \
  worldshading.worldshading.report.pricing_strategy_analysis.test_pricing_strategy_analysis
node --check worldshading/worldshading/report/pricing_strategy_analysis/pricing_strategy_analysis.js
git diff --check
```

Expected: all tests pass, JavaScript parses, and no whitespace errors are reported.

- [ ] **Step 7: Commit Task 4**

```bash
git add worldshading/worldshading/report/pricing_strategy_analysis/pricing_strategy_analysis.js \
  worldshading/worldshading/report/pricing_strategy_analysis/test_pricing_strategy_analysis.py
git commit -m "feat: add pricing report update actions"
```

---

### Task 5: Final production-safety verification

**Files:**
- Verify: `worldshading/worldshading/report/pricing_strategy_analysis/pricing_strategy_analysis.py`
- Verify: `worldshading/worldshading/report/pricing_strategy_analysis/pricing_strategy_analysis.js`
- Verify: `worldshading/worldshading/report/pricing_strategy_analysis/test_pricing_strategy_analysis.py`

**Interfaces:**
- Consumes: completed Tasks 1-4.
- Produces: evidence that the approved design is implemented without touching unrelated production changes.

- [ ] **Step 1: Run the complete focused report suite**

```bash
../../env/bin/python -m unittest \
  worldshading.worldshading.report.pricing_strategy_analysis.test_pricing_strategy_analysis
```

Expected: all Pricing Strategy Analysis tests pass with zero failures and errors.

- [ ] **Step 2: Run static validation**

```bash
../../env/bin/python -m py_compile \
  worldshading/worldshading/report/pricing_strategy_analysis/pricing_strategy_analysis.py
node --check \
  worldshading/worldshading/report/pricing_strategy_analysis/pricing_strategy_analysis.js
git diff --check
```

Expected: all commands exit zero.

- [ ] **Step 3: Audit the final diff against the specification**

Confirm explicitly:

- no ERPNext core file changed;
- no DocType or migration was added;
- both exact button labels exist;
- only the first 50 unique displayed items are previewed;
- server-side maximum, permissions, Prepared Report, saved-value, and concurrency validations exist;
- Item Price writes use normal `insert`/`save` without `ignore_permissions`;
- the Pricing Rule button contains no mutation call;
- unrelated dirty files remain unstaged.

- [ ] **Step 4: Commit any test-only corrections**

If final verification required corrections, stage only the three Pricing Strategy report files and commit:

```bash
git add worldshading/worldshading/report/pricing_strategy_analysis/pricing_strategy_analysis.py \
  worldshading/worldshading/report/pricing_strategy_analysis/pricing_strategy_analysis.js \
  worldshading/worldshading/report/pricing_strategy_analysis/test_pricing_strategy_analysis.py
git commit -m "test: verify pricing report update safety"
```

If no corrections were required, do not create an empty commit.
