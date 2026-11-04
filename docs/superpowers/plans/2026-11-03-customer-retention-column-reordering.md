# Customer Retention Analysis Column Reordering Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow Customer Retention Analysis users to drag analytical columns while keeping row number, Customer, and Customer Name anchored and sticky.

**Architecture:** Keep Frappe DataTable's existing SortableJS instance and native column-switch operation. Add report-local guards that reject moves involving the first three anchored columns, enable the remaining moves, and rebuild field-based sticky/decorative state after a successful switch.

**Tech Stack:** ERPNext/Frappe v12, ES5-compatible JavaScript, Frappe DataTable/SortableJS, Node.js `assert`/`vm` standalone tests

**Spec:** `docs/superpowers/specs/2026-11-03-customer-retention-column-reordering-design.md`

## Global Constraints

- Target ERPNext/Frappe v12; do not use modern APIs unavailable in v12.
- Keep row number, Customer, and Customer Name anchored at the start and sticky.
- Do not persist column order or change calculations, filters, permissions, backend code, or data.
- Do not modify Frappe or ERPNext core files.
- Keep the change inside the World Shading custom app and use ES5-compatible product JavaScript.

## Review Focus

- A drag whose source is row number, Customer, or Customer Name must be rejected.
- A drag of an analytical column onto an anchored destination must be rejected.
- A drag between two analytical columns must remain enabled through native DataTable switching.
- Missing DataTable/SortableJS internals must fail safely without a browser error.
- After a permitted switch, sticky offsets, field-based colors, Item Group tooltips, empty layout, and selected-row state must be rebuilt from current column indexes.

---

### Task 1: Guarded native column reordering

**Files:**
- Modify: `worldshading/worldshading/report/customer_retention_analysis/customer_retention_analysis.js`
- Test: `worldshading/worldshading/report/customer_retention_analysis/test_customer_retention_analysis_client.js`
- Modify: `docs/superpowers/specs/2026-11-03-customer-retention-column-reordering-design.md` only if implementation evidence requires a correction

**Interfaces:**
- Consumes: Frappe DataTable's existing `datatable.columnmanager.sortable.option(name, value)` API and SortableJS `onMove(event)` callback.
- Produces: report-local `get_column_index(element) -> Number|null`, `can_move_column(dragged_index, related_index) -> Boolean`, and `enable_guarded_column_reordering(datatable) -> void` helpers; `apply_sticky_columns(datatable)` remains the render entry point.

- [ ] **Step 1: Read the client-test rules**

Read `superpowers/test-driven-development/writing-good-tests.md` completely before editing the test.

- [ ] **Step 2: Write failing client regression tests**

Expose the three report-local helpers through the existing `global.__cra_test` test seam. Assert that:

- column indexes are read from the actual DataTable header-cell class/attribute shape;
- source indexes `0`, `1`, and `2` are rejected;
- an analytical source targeting indexes `0`, `1`, or `2` is rejected;
- analytical moves such as `4 -> 7` and `7 -> 3` are allowed;
- configuring a missing sortable instance returns without error;
- configuring an available sortable instance installs the guard and enables it;
- the installed `onMove` callback returns the guard result for anchored and analytical event elements.

- [ ] **Step 3: Run the client test to verify RED**

Run: `node worldshading/worldshading/report/customer_retention_analysis/test_customer_retention_analysis_client.js`

Expected: FAIL because the guarded-reordering helpers do not exist.

- [ ] **Step 4: Implement the minimal guarded reordering helpers**

In `customer_retention_analysis.js`, add ES5-compatible helpers with the exact interfaces above. Treat indexes `0` through `2` as anchored, return `false` for missing/unparseable event elements, set SortableJS `onMove` to the guard, and set `disabled` to `false` only after the guard is installed.

- [ ] **Step 5: Rebuild report decoration after permitted switches**

Replace the current `onSwitchColumn` refresh path with a requestAnimationFrame callback that reruns `apply_sticky_columns(datatable)`. Keep resize and ordinary refresh behavior intact. Remove the line that unconditionally disables the sortable instance and call `enable_guarded_column_reordering(datatable)` instead.

- [ ] **Step 6: Run focused verification**

Run:

```bash
node worldshading/worldshading/report/customer_retention_analysis/test_customer_retention_analysis_client.js
node --check worldshading/worldshading/report/customer_retention_analysis/customer_retention_analysis.js
node --check worldshading/worldshading/report/customer_retention_analysis/test_customer_retention_analysis_client.js
```

Expected: client output reports success and both syntax checks exit `0`.

- [ ] **Step 7: Review the diff against the approved design**

Confirm only analytical columns can move; the three identity columns remain anchored; no backend, database, workflow, core, prepared-report, or permission behavior changed.

- [ ] **Step 8: Commit the isolated change when authorized**

```bash
git add worldshading/worldshading/report/customer_retention_analysis/customer_retention_analysis.js \
  worldshading/worldshading/report/customer_retention_analysis/test_customer_retention_analysis_client.js \
  docs/superpowers/specs/2026-11-03-customer-retention-column-reordering-design.md \
  docs/superpowers/plans/2026-11-03-customer-retention-column-reordering.md
git commit -m "fix: allow retention report column reordering"
```
