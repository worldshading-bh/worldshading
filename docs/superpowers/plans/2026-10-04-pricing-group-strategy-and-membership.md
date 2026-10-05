# Pricing Group Strategy and Membership Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Pricing Group the enforced source for Company, Item Group and Pricing Strategy while showing its Item membership automatically and simplifying report selection.

**Architecture:** Extend the existing Pricing Group master with configuration fields, keep Item `pricing_group` as the only persisted membership source, and enforce compatibility through server validation. Expose one permission-checked configuration/read endpoint to the Pricing Group form and report client; the report backend independently validates and applies the same configuration before loading strategy settings.

**Tech Stack:** ERPNext/Frappe v12, Python 3.6-compatible server code, Frappe v12 client JavaScript, JSON DocType definition, direct `unittest` and Node test harnesses.

**Spec:** `docs/superpowers/specs/2026-10-04-pricing-group-strategy-and-membership-design.md`

## Global Constraints

- Production custom app only; do not modify ERPNext core.
- Preserve ERPNext/Frappe v12 and Python 3.6 compatibility.
- Do not run `bench migrate`, `bench test`, restart, cache-clear or database mutation commands.
- Do not create a second persisted Item-membership table.
- Do not change pricing formulas or automatically update Item Price or Pricing Rule.
- Do not commit the dirty production worktree unless the user separately requests it.

## Review Focus

- An existing Pricing Group with blank new fields must fail with a clear configuration message rather than a key error or silent default.
- Saving an Item already assigned to an incomplete or disabled group must explain which group must be corrected.
- Changing Company after choosing a strategy must not retain a strategy from another company.
- Prepared Report restoration must not trigger Pricing Group auto-fill and overwrite historical saved filters.
- A crafted report request mixing a Pricing Group with another Company, Item Group or Pricing Strategy must be rejected server-side.

---

### Task 1: Pricing Group configuration schema and validation

**Files:**
- Modify: `worldshading/worldshading/doctype/pricing_group/pricing_group.json`
- Modify: `worldshading/worldshading/doctype/pricing_group/pricing_group.py`
- Modify: `worldshading/worldshading/doctype/pricing_group/test_pricing_group.py`

**Interfaces:**
- Produces: required fields `company`, `item_group`, `pricing_strategy`, and HTML field `included_items_html`.
- Produces: `validate_pricing_group_configuration(doc)` and `get_pricing_group_configuration(pricing_group, check_permissions=True)` returning `name`, `company`, `item_group`, `pricing_strategy`, and `disabled`.
- Consumes: existing Pricing Strategy Template fields `company` and `enabled`; existing Item `pricing_group` and `item_group` fields.

- [ ] **Step 1: Add failing schema and controller tests**

Assert exact Link options/required flags, HTML read-only field, valid matching strategy, disabled strategy rejection, wrong-company strategy rejection, and Item Group change rejection with mismatched existing Items.

- [ ] **Step 2: Run the focused Pricing Group tests and verify the new tests fail**

Run: `../../env/bin/python -m unittest worldshading.worldshading.doctype.pricing_group.test_pricing_group`

Expected: failures for missing fields and configuration helpers.

- [ ] **Step 3: Add the fields and minimal server validation**

Implement the four fields in the established DocType order. In `PricingGroup.validate`, call `validate_pricing_group_configuration(self)`. Validate the linked strategy using `frappe.db.get_value`; query assigned mismatched Items with `frappe.get_all`, ordered by name, and report the first five plus total count.

- [ ] **Step 4: Add the permission-aware configuration reader**

Expose `get_pricing_group_configuration(pricing_group, check_permissions=True)` with `@frappe.whitelist()`. When permission checking is enabled, require read permission on Pricing Group; reject missing, disabled, incomplete, disabled-strategy and company-mismatch configurations with clear messages.

- [ ] **Step 5: Run focused tests**

Expected: all Pricing Group tests pass.

### Task 2: Enforced Item membership

**Files:**
- Modify: `worldshading/worldshading/doctype/pricing_group/pricing_group.py`
- Modify: `worldshading/worldshading/doctype/pricing_group/test_pricing_group.py`
- Modify: `worldshading/hooks.py`

**Interfaces:**
- Consumes: Task 1 `get_pricing_group_configuration` result.
- Produces: `validate_item_pricing_group(doc, method=None)` registered alongside the existing Item validation hook.

- [ ] **Step 1: Add failing Item validation tests**

Cover no group, matching group, mismatched Item Group, disabled group, incomplete legacy group, and missing group. Verify messages name the Item and Pricing Group where relevant.

- [ ] **Step 2: Run the focused tests and verify expected failures**

- [ ] **Step 3: Implement `validate_item_pricing_group(doc, method=None)`**

Return immediately when `pricing_group` is empty. Otherwise fetch the group configuration without bypassing validation and require `doc.item_group == configuration["item_group"]`.

- [ ] **Step 4: Append the new validator to the existing Item `validate` hook**

Convert the current Item hook value into a list containing both `worldshading.api.legacy_groups.validate_active_group_assignment` and `worldshading.worldshading.doctype.pricing_group.pricing_group.validate_item_pricing_group`. Preserve the existing validator and its order.

- [ ] **Step 5: Add and run a hook-contract test with the focused Pricing Group tests**

Read `hooks.py` in the test and assert both Item validators remain registered in order. Run: `../../env/bin/python -m unittest worldshading.worldshading.doctype.pricing_group.test_pricing_group`. Expected: all direct tests pass and the pre-existing Item-group validation remains registered.

### Task 3: Automatic Included Items display

**Files:**
- Create: `worldshading/worldshading/doctype/pricing_group/pricing_group.js`
- Create: `worldshading/worldshading/doctype/pricing_group/test_pricing_group_client.js`
- Modify: `worldshading/worldshading/doctype/pricing_group/pricing_group.py`
- Modify: `worldshading/worldshading/doctype/pricing_group/test_pricing_group.py`

**Interfaces:**
- Produces: `get_pricing_group_items(pricing_group)` returning ordered rows with `item_code`, `item_name`, `item_group`, `brand`, `stock_uom`, and `disabled`.
- Consumes: Task 1 fields and standard Frappe form routing.

- [ ] **Step 1: Add failing server tests for the Item reader**

Assert Pricing Group and Item read permissions, exact fields, deterministic Item Code ordering, empty results, and disabled Item visibility.

- [ ] **Step 2: Add a failing Node test for form behavior**

Assert the strategy query uses Company and `enabled = 1`, Company change clears an incompatible strategy, saved forms load and safely render escaped Item rows/count, new forms show save-first guidance, and **View Items** routes with a Pricing Group filter.

- [ ] **Step 3: Run both focused suites and verify expected failures**

- [ ] **Step 4: Implement the server Item reader**

Use Frappe v12 read APIs and explicit permission checks. Do not write membership or create child rows.

- [ ] **Step 5: Implement the Pricing Group form client**

Render a compact read-only table in `included_items_html`, escape all database text, display the count, and add the filtered **View Items** button. Refresh the display after save and on form refresh.

- [ ] **Step 6: Run Pricing Group Python and Node tests**

Expected: all focused tests pass.

### Task 4: Backend-authoritative report configuration

**Files:**
- Modify: `worldshading/worldshading/report/pricing_strategy_analysis/pricing_strategy_analysis.py`
- Modify: `worldshading/worldshading/report/pricing_strategy_analysis/test_pricing_strategy_analysis.py`

**Interfaces:**
- Consumes: Task 1 `get_pricing_group_configuration`.
- Produces: `apply_pricing_group_filter_configuration(filters)` returning a copied filter dictionary with authoritative `company`, `item_group`, and `pricing_strategy`.
- Consumed by: existing `validate_and_normalize_filters(filters, apply_strategy=True)` before `_get_pricing_strategy_settings`.

- [ ] **Step 1: Add failing backend filter tests**

Cover a configured enabled group, incomplete legacy group, disabled group, mismatched Company, mismatched Item Group, mismatched Pricing Strategy, and report execution without a Pricing Group.

- [ ] **Step 2: Run focused tests and verify expected failures**

- [ ] **Step 3: Implement authoritative configuration application**

Resolve Pricing Group before loading strategy settings. Empty incoming dependent values are populated; conflicting non-empty values are rejected. Preserve the existing no-Pricing-Group path exactly.

- [ ] **Step 4: Run focused and complete report Python tests**

Expected: all direct Pricing Strategy Analysis tests pass.

### Task 5: Pricing Group-first report client behavior

**Files:**
- Modify: `worldshading/worldshading/report/pricing_strategy_analysis/pricing_strategy_analysis.js`
- Modify: `worldshading/worldshading/report/pricing_strategy_analysis/test_pricing_strategy_analysis_client.js`
- Modify: `worldshading/worldshading/report/pricing_strategy_analysis/test_pricing_strategy_analysis.py`

**Interfaces:**
- Consumes: Task 1 whitelisted `get_pricing_group_configuration`.
- Produces: `load_pricing_group_configuration(report)` setting Company, Item Group and Pricing Strategy, then invoking the existing strategy loader.

- [ ] **Step 1: Add failing client and file-contract tests**

Assert Pricing Group appears before Company and Pricing Strategy, only enabled groups are queried, selection applies all three dependent filters, incomplete configuration is surfaced, clearing Pricing Group leaves standalone filters usable, and the prepared-filter restoration guard prevents auto-fill.

- [ ] **Step 2: Run Node and focused Python tests and verify expected failures**

- [ ] **Step 3: Implement the Pricing Group change handler**

Call the Task 1 method, set dependent filters in one operation, and load existing strategy settings only after those values are applied. During `pricing_strategy_restoring_prepared_filters`, return without fetching or changing values.

- [ ] **Step 4: Preserve standalone and Purchase Receipt workflows**

Keep manual Company/Strategy operation when Pricing Group is blank. Do not alter Purchase Receipt authoritative Item expansion or its restoration guard.

- [ ] **Step 5: Run both client suites and the complete report Python suite**

Expected: all direct tests pass.

### Task 6: Documentation and final safe verification

**Files:**
- Modify: `worldshading/Documentation/pricing_strategy_analysis.md`

**Interfaces:**
- Consumes: completed Tasks 1–5.
- Produces: administrator setup, user workflow, deployment and rollback guidance.

- [ ] **Step 1: Document setup and legacy transition**

Explain the three required fields, automatic membership table, Item Group enforcement, report auto-selection, incomplete legacy-group behavior, and manual configuration steps.

- [ ] **Step 2: Document the approved reload command only**

Document `bench --site erp.worldshading.com reload-doc worldshading doctype pricing_group` and its previously established global `--force` variant when necessary. Explicitly state that migration, bench tests, restart and cache clear are not part of this deployment.

- [ ] **Step 3: Run final safe verification**

Run the direct Pricing Group and Pricing Strategy Analysis Python suites, both relevant Node suites, Python compilation for modified Python files, JSON parsing, stale-contract searches, and scoped `git diff --check`.

- [ ] **Step 4: Review the scoped diff against the approved specification**

Confirm no ERPNext core file, pricing formula, database record, workflow, or unrelated hook changed.
