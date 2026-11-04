# Customer Retention Analysis User Sticky Columns Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add report-local Pin / Unpin Column behavior that moves analytical columns into a contiguous sticky section.

**Architecture:** Store pinned analytical field names on the DataTable instance, align them after the three permanent identity columns through native DataTable switches, and generate sticky rules from the current contiguous block. Replace the report's header dropdown with the four Frappe v12 native actions plus the pin toggle so existing menu behavior is preserved.

**Tech Stack:** ERPNext/Frappe v12, ES5 JavaScript, Frappe DataTable/SortableJS, Node.js `assert`/`vm` client tests

**Spec:** `docs/superpowers/specs/2026-11-03-customer-retention-user-sticky-columns-design.md`

## Global Constraints

- Keep ERPNext/Frappe v12 and ES5 compatibility.
- Keep row number, Customer and Customer Name permanently sticky.
- Preserve native sorting, column removal and permitted analytical dragging.
- Store pin choices only on the current DataTable instance; do not write to the database or `localStorage`.
- Do not modify backend calculations, prepared-report data, permissions, Frappe core or ERPNext core.

## Review Focus

- Pinning several dynamic year columns must preserve their field identities across a report refresh.
- Unpinning the first or middle extra column must compact the remaining sticky block without gaps.
- Analytical dragging must not cross the current dynamic sticky boundary.
- Removing a pinned column must remove its stale field name and keep remaining pins usable.
- Missing or changed dynamic fields after rebuild must be discarded safely without an alignment loop.

---

### Task 1: Dynamic user-controlled sticky block

**Files:**
- Modify: `worldshading/worldshading/report/customer_retention_analysis/customer_retention_analysis.js`
- Test: `worldshading/worldshading/report/customer_retention_analysis/test_customer_retention_analysis_client.js`

**Interfaces:**
- Consumes: existing `apply_sticky_columns(datatable)`, guarded SortableJS reordering, DataTable `columnmanager.switchColumn(oldIndex, newIndex)`, and report `get_datatable_options(options)`.
- Produces: `get_extra_sticky_fieldnames(datatable) -> Array`, `get_sticky_column_count(datatable) -> Number`, `align_extra_sticky_columns(datatable) -> Boolean`, and `toggle_sticky_column(datatable, column) -> void`.

- [ ] **Step 1: Add failing client behavior tests**

Extend the test seam and assert the four native dropdown actions plus Pin / Unpin Column remain available; identity columns cannot toggle; one and multiple analytical fields align at indexes 3 onward; unpinning compacts the block; missing fields are discarded; and the drag guard rejects source/destination indexes below the dynamic sticky count.

- [ ] **Step 2: Run the client test and verify RED**

Run: `node worldshading/worldshading/report/customer_retention_analysis/test_customer_retention_analysis_client.js`

Expected: FAIL because dynamic sticky helpers and the menu action do not exist.

- [ ] **Step 3: Implement session pin state and alignment**

Add the exact helper interfaces above. Keep field names, remove missing/permanent fields, perform at most one native switch per alignment call, and let `onSwitchColumn` clear the pending flag and continue alignment through `apply_sticky_columns(datatable)`.

- [ ] **Step 4: Implement the report column menu**

Add `get_datatable_options(options)` with Frappe v12's Sort Ascending, Sort Descending, Reset sorting and Remove column actions plus Pin / Unpin Column. The pin action calls `toggle_sticky_column(this, column)`.

- [ ] **Step 5: Generate the complete sticky layout dynamically**

Update `apply_sticky_columns(datatable)` to align pins before styling, build sticky indexes from row number plus current identity/pinned columns, calculate cumulative pixel offsets from rendered widths, place the shadow on the final sticky column, and use the dynamic sticky count in the drag guard. On pinned-column removal, clean state and fully reapply.

- [ ] **Step 6: Run focused verification**

Run:

```bash
node worldshading/worldshading/report/customer_retention_analysis/test_customer_retention_analysis_client.js
node --check worldshading/worldshading/report/customer_retention_analysis/customer_retention_analysis.js
node --check worldshading/worldshading/report/customer_retention_analysis/test_customer_retention_analysis_client.js
git diff --check
```

Expected: the client test reports success and all remaining commands exit `0`.

- [ ] **Step 7: Review without deploying**

Compare the incremental diff with this spec and the previous column-reordering design. Do not commit, restart, clear caches, migrate or deploy without separate authorization.
