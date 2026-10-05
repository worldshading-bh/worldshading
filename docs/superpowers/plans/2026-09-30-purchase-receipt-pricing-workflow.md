# Purchase Receipt Pricing Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Open Pricing Strategy Analysis from a submitted Purchase Receipt and analyze the receipt Items plus every active member of their Pricing Groups.

**Architecture:** The report backend owns receipt validation and deterministic Item-scope expansion. Report JavaScript owns the reusable Purchase Receipt filter, while a focused Purchase Receipt client script owns the strategy-selection dialog and route handoff. Existing pricing calculations and bulk-update safety rules consume the expanded Item set unchanged.

**Tech Stack:** ERPNext/Frappe v12, Python 3.6-compatible server code, Frappe v12 client JavaScript, existing direct `unittest` and Node test harnesses.

**Spec:** `docs/superpowers/specs/2026-09-30-purchase-receipt-pricing-workflow-design.md`

## Global Constraints

- Production custom app only; do not modify ERPNext core.
- Preserve ERPNext/Frappe v12 and Python 3.6 compatibility.
- Do not run `bench test`, `bench migrate`, restart, cache-clear or database mutation commands.
- Do not automatically create or update Item Price or Pricing Rule records.
- Do not automatically apply the Purchase Receipt warehouse.
- Do not commit existing or new work unless the user explicitly requests a commit.

## Review Focus

- Draft, cancelled, returned or wrong-company receipts must be rejected server-side, not merely hidden in the client.
- Duplicate receipt rows and several received members of one Pricing Group must produce a unique Item set.
- A receipt Item's active group siblings must be included even when ordinary Item-scope filters contain conflicting values.
- Ungrouped receipt Items must remain included alongside expanded grouped Items.
- Prepared Report restoration must preserve the Purchase Receipt and must not trigger filter-clearing recursion.

---

### Task 1: Purchase Receipt Item-scope expansion

**Files:**
- Modify: `worldshading/worldshading/report/pricing_strategy_analysis/pricing_strategy_analysis.py`
- Test: `worldshading/worldshading/report/pricing_strategy_analysis/test_pricing_strategy_analysis.py`

**Interfaces:**
- Produces: `get_purchase_receipt_item_scope(filters)` returning a unique ordered set/list of direct received Items plus active stock Pricing Group siblings.
- Consumes: existing Item `pricing_group` field, Pricing Group membership conventions and report `get_items(filters)`.

- [ ] **Step 1: Write failing validation and expansion tests**

Cover submitted receipt validation, return/wrong-company rejection, duplicate direct rows, grouped sibling expansion, ungrouped Items and no-stock-Item rejection.

- [ ] **Step 2: Run the focused Python tests and verify expected failures**

Run direct `python -m unittest` for the new test methods; expect missing helper/filter behavior failures.

- [ ] **Step 3: Implement receipt validation and expansion**

Add a small helper using Frappe v12 APIs. Apply its Item codes as the authoritative `name in (...)` scope in `get_items`; ignore Item, Item Group, Pricing Group, Brand and Stock UOM scope filters when `purchase_receipt` is present. Continue applying Company/report calculations and optional Warehouse behavior.

- [ ] **Step 4: Run focused and complete report Python tests**

Expected: all direct pricing report unit tests pass.

### Task 2: Reusable Purchase Receipt report filter

**Files:**
- Modify: `worldshading/worldshading/report/pricing_strategy_analysis/pricing_strategy_analysis.js`
- Modify: `worldshading/worldshading/report/pricing_strategy_analysis/test_pricing_strategy_analysis_client.js`
- Modify: `worldshading/worldshading/report/pricing_strategy_analysis/test_pricing_strategy_analysis.py`

**Interfaces:**
- Produces: optional `purchase_receipt` Link filter restored through existing Prepared Report filter handling.
- Consumes: Task 1's backend `purchase_receipt` filter contract.

- [ ] **Step 1: Write failing client and filter-contract tests**

Assert filter placement/query restrictions, clearing of Item-scope filters when a receipt is selected, inclusion in the server filter allowlist and Prepared Report restoration.

- [ ] **Step 2: Run Node and focused Python tests and verify expected failures**

Expected: missing `purchase_receipt` filter/contract failures.

- [ ] **Step 3: Implement the report filter behavior**

Add the Link filter after Pricing Strategy, filter it by selected Company, `docstatus = 1` and `is_return = 0`, and clear Item, Item Group, Pricing Group, Brand and Stock UOM values on a user-triggered receipt change without disrupting Prepared Report restoration.

- [ ] **Step 4: Run client and report Python tests**

Expected: Node client tests and all direct report Python tests pass.

### Task 3: Submitted Purchase Receipt Update Pricing button

**Files:**
- Create: `worldshading/public/js/purchase_receipt.js`
- Create: `worldshading/public/js/test_purchase_receipt_pricing.js`
- Modify: `worldshading/hooks.py`

**Interfaces:**
- Produces: `Update Pricing` button for submitted, non-return Purchase Receipts and route options `{company, pricing_strategy, purchase_receipt}`.
- Consumes: Pricing Strategy Template Link filtered by receipt company and enabled status; Task 2's report filters.

- [ ] **Step 1: Write a failing Node test for button eligibility and route options**

Exercise pure helpers for submitted/non-return eligibility and exact route-option construction, including no warehouse key.

- [ ] **Step 2: Run the Node test and verify expected missing-helper failure**

- [ ] **Step 3: Implement the client script and hook**

Add the mandatory Pricing Strategy dialog, filtered by `company` and `enabled = 1`; on continue set route options and navigate to Pricing Strategy Analysis. Register the file under the existing `doctype_js` dictionary without altering other hooks.

- [ ] **Step 4: Run both Node client test files**

Expected: Purchase Receipt and Pricing Strategy Analysis client tests pass.

### Task 4: Documentation and final verification

**Files:**
- Modify: `worldshading/Documentation/pricing_strategy_analysis.md`

**Interfaces:**
- Consumes: completed behavior from Tasks 1–3.
- Produces: operator guidance and deployment note for the new hook.

- [ ] **Step 1: Document the receipt filter, expansion, button workflow and exclusions**

State that warehouse is not copied, Pricing Groups expand fully, review remains mandatory, and hook activation waits for the user's normal approved deployment process.

- [ ] **Step 2: Run final safe verification**

Run direct Python unit tests, both Node test files, Python compilation and scoped `git diff --check`. Do not run any prohibited bench command.

- [ ] **Step 3: Review the scoped diff against the approved specification**

Confirm no core files, schema, database state or unrelated hooks changed.
