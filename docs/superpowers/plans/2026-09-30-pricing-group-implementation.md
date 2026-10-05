# Pricing Group Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Pricing Groups to Items and Pricing Strategy Analysis so related variants receive one protected shared price and are updated together in Item Price and Pricing Rule.

**Architecture:** A normal `Pricing Group` master owns only group metadata; Item's custom `pricing_group` Link is the sole membership source. The report calculates each Item normally, then a focused group layer derives the highest recommendation per price level and group-integrity status. Both bulk-update APIs consume only the saved Prepared Report snapshot and reject partial or changed groups.

**Tech Stack:** ERPNext/Frappe v12, Python 3.6, MariaDB, Frappe Query Report JavaScript, Python `unittest`, Node.js client assertions.

**Spec:** `docs/superpowers/specs/2026-09-29-pricing-group-design.md`

## Global Constraints

- Production server: preserve unrelated working-tree changes and avoid ERPNext core modifications.
- Use only ERPNext/Frappe v12 APIs and Python 3.6-compatible syntax.
- Do not run `bench test`, `bench migrate`, restart, backup, restore, or cache-clear commands.
- Do not introduce a patch for the Item custom field; the user will create it manually.
- Do not use subagents; execute natively in the existing workspace.
- Keep the existing 50-Item limit, Prepared Report links, audit comments, permissions, and concurrency checks.
- Ungrouped Items must retain their current calculations and update behavior.
- Use `apply_patch` for file edits and do not commit without explicit user authorization.

## Review Focus

- A selected group exceeding or crossing the 50-Item boundary must be blocked, never split.
- A member removed, disabled, reassigned, or added after preview must invalidate execution.
- Missing cost or a missing B2B/tier recommendation must block only the affected group.
- Disabling a Pricing Group after report generation must prevent an update from the stale snapshot.
- Two groups with the same recommended numeric prices must remain distinct rule sets.

---

### Task 1: Pricing Group master and Item-field contract

**Files:**
- Create: `worldshading/worldshading/doctype/pricing_group/__init__.py`
- Create: `worldshading/worldshading/doctype/pricing_group/pricing_group.py`
- Create: `worldshading/worldshading/doctype/pricing_group/pricing_group.json`
- Create: `worldshading/worldshading/doctype/pricing_group/test_pricing_group.py`

**Interfaces:**
- Produces: standard DocType `Pricing Group` with `pricing_group_name`, `description`, and `disabled`.
- Requires at deployment: Item custom Link field `pricing_group` with Options `Pricing Group`.
- Produces: `validate_pricing_group_setup()` in the report module during Task 2; no DB setup patch is created here.

- [ ] **Step 1: Write the failing metadata tests**

Add tests that load `pricing_group.json` and assert:

- `autoname == "field:pricing_group_name"`;
- the DocType is not a tree;
- `pricing_group_name` is required, unique, title/list/filter enabled;
- `disabled` defaults to `0` and is visible in list/filter;
- permissions match the approved System Manager, Accounts Manager, Sales Manager, and Stock Manager policy.

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```bash
cd /home/erpadmin/frappe-bench/apps/worldshading/worldshading
/home/erpadmin/frappe-bench/env/bin/python -m unittest worldshading.doctype.pricing_group.test_pricing_group
```

Expected: FAIL because the Pricing Group definition does not exist.

- [ ] **Step 3: Create the minimal DocType files**

Follow the existing standard DocType JSON style. `PricingGroup(Document)` has no custom behavior. Do not add an Items child table or tree fields.

- [ ] **Step 4: Re-run the focused test**

Expected: one test module passes with no warnings.

- [ ] **Step 5: Record the manual Item custom-field setup**

Add this exact deployment instruction to the existing report guide:

| Property | Value |
|---|---|
| DocType | Item |
| Label | Pricing Group |
| Fieldname | `pricing_group` |
| Field Type | Link |
| Options | Pricing Group |
| Insert After | Item Group |
| In Standard Filter | Yes |
| No Copy | Yes |

No database command is run during implementation.

---

### Task 2: Report filter, membership loading, and group calculations

**Files:**
- Modify: `worldshading/worldshading/report/pricing_strategy_analysis/pricing_strategy_analysis.py`
- Modify: `worldshading/worldshading/report/pricing_strategy_analysis/test_pricing_strategy_analysis.py`

**Interfaces:**
- Produces: `validate_pricing_group_setup(filters)`.
- Produces: `get_pricing_group_membership(group_names)` returning enabled group metadata and all active stock Item codes per group.
- Produces: `apply_pricing_group_recommendations(rows, membership, filters)` returning rows with group recommendation/status fields.
- Adds row fields: `pricing_group`, `pricing_group_status`, `pricing_group_member_count`, `group_recommended_regular_net`, `group_recommended_b2b_net`, and `group_tier_{n}_net`.
- Consumes: individual recommendations already produced by `calculate_item_row()`.

- [ ] **Step 1: Add failing calculation tests**

Test these exact cases with in-memory rows:

- maximum Regular, B2B, and every tier price is selected independently;
- the shared values are copied to every member row;
- an ungrouped row retains individual values and receives no group status;
- differing current Item Prices yield `Different Current Prices` without invalidating the group;
- a missing expected member yields `Incomplete Group`;
- a present member without a valid required recommendation yields `Missing Cost`;
- a disabled master yields `Disabled Group`;
- two groups with equal numeric recommendations remain separate.

- [ ] **Step 2: Run the individual test cases and verify RED**

Run the exact new unittest test names with:

```bash
cd /home/erpadmin/frappe-bench/apps/worldshading/worldshading
/home/erpadmin/frappe-bench/env/bin/python -m unittest worldshading.report.pricing_strategy_analysis.test_pricing_strategy_analysis.TestPricingStrategyCalculation
```

Expected: FAIL because group functions/fields do not exist.

- [ ] **Step 3: Add setup validation and Item filtering**

`validate_pricing_group_setup(filters)` checks `frappe.get_meta("Item").has_field("pricing_group")` only when the filter or returned Items require group behavior. If missing, throw: `Create the Item custom field pricing_group (Link to Pricing Group) before using Pricing Groups.`

Extend `get_items(filters)` to:

- apply `pricing_group` when provided;
- include `pricing_group` in selected fields when the custom field exists; and
- leave existing behavior unchanged when it does not exist and no group filter is requested.

- [ ] **Step 4: Implement group membership and pure aggregation**

Load all non-disabled stock Items for represented groups and the `disabled` state of each group. Keep price selection in a pure helper so it can be tested without database access.

Required policy:

```text
group price for each level = max(valid member recommendation for that level)
```

Calculate status in this priority: Disabled Group, Incomplete Group, Missing Cost, Different Current Prices, Ready.

- [ ] **Step 5: Integrate group calculation after individual rows**

In `execute()`, calculate/serialize individual rows first, apply the group layer to the complete row list, and then return columns/data. The group layer must not change Base Cost, expense allocation, sales values, or historical-rate fields.

- [ ] **Step 6: Add the 50-Item boundary test**

Assert that a helper such as `classify_updateable_pricing_groups(rows, requested_codes, limit)` marks a group invalid when not all active members are inside the requested first-50 scope. It must not append members beyond the limit or silently split a group.

- [ ] **Step 7: Run the report unit-test module directly**

Run:

```bash
/home/erpadmin/frappe-bench/env/bin/python -m unittest worldshading.report.pricing_strategy_analysis.test_pricing_strategy_analysis
```

Expected: all tests pass. This is direct `unittest`, not `bench test`.

---

### Task 3: Report filters, columns, Simple View, and tooltips

**Files:**
- Modify: `worldshading/worldshading/report/pricing_strategy_analysis/pricing_strategy_analysis.py`
- Modify: `worldshading/worldshading/report/pricing_strategy_analysis/pricing_strategy_analysis.js`
- Modify: `worldshading/worldshading/report/pricing_strategy_analysis/test_pricing_strategy_analysis_client.js`

**Interfaces:**
- Consumes: Task 2 group fields.
- Produces: visible `pricing_group` filter and Full/Simple View group columns.
- Produces: helper `get_pricing_group_status_tooltip(data)`.

- [ ] **Step 1: Add failing client assertions**

Assert that:

- the filter order contains Pricing Group after Item Group and before Item;
- Simple View retains Pricing Group and all group recommended net columns;
- tooltip text explains Ready, Different Current Prices, Incomplete Group, Missing Cost, and Disabled Group;
- group price columns use a distinct but restrained shared-price color;
- obvious identity columns do not receive calculation tooltips.

- [ ] **Step 2: Run Node test and verify RED**

```bash
cd /home/erpadmin/frappe-bench/apps/worldshading/worldshading
node worldshading/report/pricing_strategy_analysis/test_pricing_strategy_analysis_client.js
```

Expected: assertion failure for missing Pricing Group UI.

- [ ] **Step 3: Add backend columns**

Full Analysis View adds Pricing Group, Group Status, and group Regular/B2B/tier recommendations adjacent to their individual recommendation families. Simple View shows identity, current prices, and the group recommendation used for an update; for ungrouped rows it continues to show the individual recommendation.

- [ ] **Step 4: Add filter and presentation behavior**

Add the Pricing Group Link filter with query filter `disabled = 0`. Update filter restoration so saved Prepared Report links restore it automatically through the existing generic mechanism. Add concise group-status tooltips and group column styling without changing sticky Item Code/Item Name or row highlighting.

- [ ] **Step 5: Run client and backend column tests**

Expected: direct Node test and relevant Python unittest cases pass.

---

### Task 4: Group-safe Item Price preview and execution

**Files:**
- Modify: `worldshading/worldshading/report/pricing_strategy_analysis/pricing_strategy_analysis.py`
- Modify: `worldshading/worldshading/report/pricing_strategy_analysis/pricing_strategy_analysis.js`
- Modify: `worldshading/worldshading/report/pricing_strategy_analysis/test_pricing_strategy_analysis.py`
- Modify: `worldshading/worldshading/report/pricing_strategy_analysis/test_pricing_strategy_analysis_client.js`

**Interfaces:**
- Consumes: Task 2 group statuses and shared recommendation fields.
- Produces: `validate_saved_pricing_groups(prepared_rows, requested_item_codes, live_items)` returning allowed groups, blocked groups, and ungrouped items.
- Preview entries add `pricing_group`, `individual_rate`, `group_rate`, and `group_key`.
- Execution validates the cached `group_key` membership against current Item records.

- [ ] **Step 1: Add failing backend tests**

Cover:

- a complete Ready group uses the shared Regular and B2B prices for every member;
- Different Current Prices remains updateable;
- Incomplete Group, Missing Cost, and Disabled Group are blocked with compact reasons;
- one invalid group does not block another valid group or ungrouped Item;
- a group crossing the 50-Item boundary is blocked;
- a member added, removed, disabled, or reassigned after preview causes execution rejection;
- unchanged entries still retain Prepared Report integrity but do not write unnecessarily.

- [ ] **Step 2: Run the new backend cases and verify RED**

Expected: failure because preview currently reads individual recommendation fields.

- [ ] **Step 3: Implement grouped preview creation**

Use shared group fields for grouped entries and individual fields for ungrouped entries. Return compact blocked-group counts and reasons. Preserve the maximum of 50 Items and up to two Item Price rows per Item.

- [ ] **Step 4: Enforce whole-group selection**

In the client preview, selecting/removing any grouped entry operates on the whole `group_key` across both price lists. The server rejects a selected-row payload containing only part of a group even if the browser is manipulated.

- [ ] **Step 5: Revalidate live membership during execution**

Before saving, compare the cached preview membership with all current active Items in each group and confirm the Pricing Group is still enabled. Retain the existing Item Price target, modified timestamp, permission, currency, UOM, comment, and `pricing_prepared_report` checks.

- [ ] **Step 6: Run direct Python and Node tests**

Expected: all focused Item Price tests pass without running `bench test`.

---

### Task 5: Group-aware Pricing Rule creation

**Files:**
- Modify: `worldshading/worldshading/report/pricing_strategy_analysis/pricing_strategy_analysis.py`
- Modify: `worldshading/worldshading/report/pricing_strategy_analysis/pricing_strategy_analysis.js`
- Modify: `worldshading/worldshading/report/pricing_strategy_analysis/test_pricing_strategy_analysis.py`
- Modify: `worldshading/worldshading/report/pricing_strategy_analysis/test_pricing_strategy_analysis_client.js`

**Interfaces:**
- Consumes: Task 2 group recommendation/status fields and Task 4 live-membership validator.
- Produces: pricing-rule mode `pricing_group` internally for grouped selections.
- Produces one rule spec per complete group per tier with exact shared-price discount.
- Rule name: `PSA - {Pricing Group} - Tier {N}`.

- [ ] **Step 1: Add failing Pricing Rule tests**

Assert:

- one complete group with four tiers produces four specs, not one spec per Item;
- every spec contains all active group members;
- tier discount equals `(shared reference net - shared tier net) / shared reference net × 100`;
- B2B is the reference when configured, otherwise Regular;
- Mixed Conditions is copied to each group rule;
- groups with identical discounts remain separate;
- default Rule Set Name is the Pricing Group;
- stale membership and disabled groups are rejected at execution;
- ungrouped Combined, Separate, and Same Discount modes remain unchanged.

- [ ] **Step 2: Run the focused tests and verify RED**

Expected: current average-based Combined logic fails the new group assertions.

- [ ] **Step 3: Build grouped rule specs**

Introduce a group-specific spec builder rather than changing the existing ungrouped builders. Use the shared prices from the Prepared Report; do not average member discounts. Populate the native Pricing Rule Item table with every group member and preserve no-price-list behavior.

- [ ] **Step 4: Update the selection/review dialogs**

Visually group rows, display Pricing Group, and explain that grouped members create one rule set per group. Removing one member removes the complete group. Retain editable Final Discount %, tier Include toggles, and Mixed Conditions.

- [ ] **Step 5: Preserve naming and update matching**

Use the exact title `PSA - {Pricing Group} - Tier {N}`. Re-running the same group/tier updates its matching generated rule. Never merge different Pricing Groups because their percentages happen to match.

- [ ] **Step 6: Run direct Python and Node tests**

Expected: all Pricing Rule and regression tests pass.

---

### Task 6: Documentation and deployment handoff

**Files:**
- Modify: `Documentation/pricing_strategy_analysis.md`
- Modify: `docs/superpowers/specs/2026-09-29-pricing-group-design.md` only if implementation required an approved clarification.

**Interfaces:**
- Documents the UI setup and manual production deployment; produces no runtime behavior.

- [ ] **Step 1: Update functional documentation**

Document:

- Pricing Group master fields;
- Item membership field;
- highest-per-level group pricing policy;
- statuses and partial-group blocking;
- Item Price and Pricing Rule behavior;
- Mixed Conditions behavior inside a group;
- 50-Item limit behavior; and
- Prepared Report audit links.

- [ ] **Step 2: Add exact manual deployment sequence**

1. Create Item Custom Field `pricing_group` in the UI using Task 1 values.
2. Load the new DocType manually:

```bash
bench --site erp.worldshading.com --force reload-doc worldshading doctype pricing_group
```

3. Load the updated report definition only if its JSON changes:

```bash
bench --site erp.worldshading.com --force reload-doc worldshading report pricing_strategy_analysis
```

4. Confirm Pricing Group opens and Item displays the Link field.
5. Create a small group and rebuild a Prepared Report before any bulk update.

Do not include migrate, restart, or cache-clear instructions.

- [ ] **Step 3: Document rollback**

Revert the custom-app code, preserve Pricing Group and Item field records until dependencies are reviewed, and never automatically delete Item Price/Pricing Rule business records already created.

---

### Task 7: Final non-bench verification

**Files:**
- Verify all files modified in Tasks 1–6.

**Interfaces:**
- Produces the evidence used for the final handoff.

- [ ] **Step 1: Validate JSON and Python syntax**

```bash
python3 -m json.tool worldshading/doctype/pricing_group/pricing_group.json >/dev/null
python3 -m py_compile \
  worldshading/doctype/pricing_group/pricing_group.py \
  worldshading/report/pricing_strategy_analysis/pricing_strategy_analysis.py
```

- [ ] **Step 2: Run direct focused tests, not bench tests**

```bash
/home/erpadmin/frappe-bench/env/bin/python -m unittest \
  worldshading.doctype.pricing_group.test_pricing_group \
  worldshading.report.pricing_strategy_analysis.test_pricing_strategy_analysis

node worldshading/report/pricing_strategy_analysis/test_pricing_strategy_analysis_client.js
```

- [ ] **Step 3: Check whitespace and scope**

```bash
git diff --check
git status --short
git diff --stat
```

Inspect the full diff to confirm no core files, migrations, patches, or unrelated user changes were modified.

- [ ] **Step 4: Report what was and was not executed**

State exact test counts and results. Explicitly state that no `bench test`, migrate, restart, cache clear, reload-doc, or production database write was performed.
