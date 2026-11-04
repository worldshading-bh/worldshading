# Recurring Sales Target Plan Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert Sales Target into one recurring company plan with per-employee frequency amounts and update Sales Target Performance to calculate the applicable day, week, month, quarter, or plan year automatically.

**Architecture:** Evolve the existing DocTypes additively, retaining hidden legacy fields and marking only new documents as `Recurring Plan`. Keep recurrence virtual: a shared v12/Python 3.6 utility derives occurrence dates, while the report performs one grouped Sales Invoice query and calculates employee and team performance without saved occurrence records.

**Tech Stack:** ERPNext/Frappe v12, Python 3.6, MariaDB, ES5 JavaScript, Python `unittest`, Node.js `assert`/`vm`

**Spec:** `docs/superpowers/specs/2026-11-04-recurring-sales-target-plan-design.md`

## Global Constraints

- This is a live production ERPNext v12/Frappe v12 system; keep all product code Python 3.6 and ES5 compatible.
- Modify only the World Shading custom app; do not modify Frappe or ERPNext core.
- Keep existing Sales Target permissions and submitted-document lifecycle behavior.
- Do not add scheduler hooks, workflows, generated occurrence documents, snapshots, points, commissions, or payouts.
- Preserve `period_type`, `total_target_amount`, and child `target_amount` as hidden/read-only legacy fields; never backfill or rewrite the three submitted legacy records.
- Continue using submitted Sales Invoice `base_net_total` grouped by `pb_sales_employee`; returns remain negative.
- Use one bulk Employee validation read and one grouped Sales Invoice query; keep every SQL value parameterized.
- Do not write to Sales Invoice, Employee, or existing incentive records.
- Do not run `bench migrate`, `bench test`, restart, cache-clear, scheduler, or automatic production record mutation commands.
- Production deployment may use only separately approved `reload-doc` commands in dependency order.
- Every task uses TDD: observe the focused test fail before implementation, then pass afterward.

## Review Focus

- A plan valid for 366 days is accepted while 367 days is rejected; Task 2 tests both boundaries.
- A Saturday–Friday week clipped by the plan start or end must never include invoices outside validity; Task 4 tests both clipped edges.
- A direct report request for a submitted legacy target must fail before the invoice query; Task 4 tests the permission/model gate order.
- Overlap exists only when effective dates, Employee, and at least one positive frequency intersect; Task 2 tests shared and disjoint frequencies plus legacy exclusion.
- Employee filtering must preserve team-wide rank, contribution denominator, and report summary rather than recalculating a one-person team; Task 4 tests all three.

---

### Task 1: Additive Recurring Plan Metadata

**Files:**
- Modify: `worldshading/worldshading/doctype/sales_target/sales_target.json`
- Modify: `worldshading/worldshading/doctype/sales_target_detail/sales_target_detail.json`
- Modify: `worldshading/worldshading/doctype/sales_target/test_sales_target.py`

**Interfaces:**
- Produces parent fields: `target_model`, `total_daily_target`, `total_weekly_target`, `total_monthly_target`, `total_quarterly_target`, `total_annual_target`.
- Produces child fields: `daily_target`, `weekly_target`, `monthly_target`, `quarterly_target`, `annual_target`.
- Preserves legacy parent `period_type`, `total_target_amount` and child `target_amount` as hidden/read-only, non-required fields.

- [ ] **Step 1: Extend metadata tests first**

Assert the exact new fieldnames, Currency types, `options: currency`, read-only parent totals, hidden/read-only `target_model`, and five frequency fields. Assert legacy fields remain but are hidden, read-only, and not required. Assert editable-grid columns total at most ten and show Employee, Employee Name, Daily, Weekly, and Monthly inline.

- [ ] **Step 2: Run metadata tests and verify RED**

Run:

```bash
env PYTHONPATH="$PWD" /home/erpadmin/frappe-bench/env/bin/python -m unittest worldshading.worldshading.doctype.sales_target.test_sales_target.TestSalesTargetMetadata -v
```

Expected: FAIL because recurring fields do not exist and legacy fields are visible/required.

- [ ] **Step 3: Update child metadata additively**

Add the five Currency fields after `currency`. Set inline columns to Employee `2`, Employee Name `2`, Daily `2`, Weekly `2`, Monthly `2`; omit `in_list_view`/`columns` from Quarterly, Annual, and Remarks. Keep `target_amount` hidden/read-only without `reqd`.

- [ ] **Step 4: Update parent metadata additively**

Add hidden/read-only `target_model` and five read-only Currency totals in a Frequency Totals section. Keep `period_type` and `total_target_amount` hidden/read-only without `reqd`; remove them from list/search presentation but retain their definitions. Keep permissions and submission settings unchanged.

- [ ] **Step 5: Run metadata tests and parse JSON**

Run the Step 2 command, then parse both changed JSON files with `/home/erpadmin/frappe-bench/env/bin/python -m json.tool`.

Expected: tests PASS and both JSON parses exit `0`.

- [ ] **Step 6: Commit**

```bash
git add worldshading/worldshading/doctype/sales_target/sales_target.json \
  worldshading/worldshading/doctype/sales_target_detail/sales_target_detail.json \
  worldshading/worldshading/doctype/sales_target/test_sales_target.py
git commit -m "feat: add recurring sales target metadata"
```

---

### Task 2: Recurring Validation, Totals, and Overlap Safety

**Files:**
- Create: `worldshading/worldshading/sales_target_utils.py`
- Modify: `worldshading/worldshading/doctype/sales_target/sales_target.py`
- Modify: `worldshading/worldshading/doctype/sales_target/test_sales_target.py`

**Interfaces:**
- Produces `FREQUENCY_CONFIG`, ordered tuples `(label, child_field, parent_total_field)` for Daily through Annual.
- Produces `get_frequency_config(frequency)` returning the matching tuple or `None`.
- Produces controller helpers `_set_target_model(doc)`, `_validate_dates(doc)`, `_validate_employee_rows(doc)`, `_set_frequency_totals(doc)`, `_validate_no_overlap(doc)`.
- Consumes Task 1 recurring and legacy fieldnames.

- [ ] **Step 1: Write failing controller tests**

Extend factories with recurring fields. Assert `before_insert` marks new documents exactly `Recurring Plan`; one day and 366 days pass while reversed/367 days fail; every row has at least one positive frequency; negatives fail while blank/zero non-applicable values pass; Employee validation remains one bulk read; all five totals are independent and rounded to three decimals; amendment and Company-lock order remains; legacy plans are excluded; and overlap is rejected only for shared Employee/shared positive frequency.

- [ ] **Step 2: Run controller tests and verify RED**

```bash
env PYTHONPATH="$PWD" /home/erpadmin/frappe-bench/env/bin/python -m unittest worldshading.worldshading.doctype.sales_target.test_sales_target.TestSalesTargetValidation worldshading.worldshading.doctype.sales_target.test_sales_target.TestSalesTargetOverlap -v
```

Expected: FAIL because recurring validation does not exist.

- [ ] **Step 3: Add shared frequency configuration**

Create `FREQUENCY_CONFIG` in Daily, Weekly, Monthly, Quarterly, Annual order with Task 1 fieldnames. Implement `get_frequency_config` without type hints or modern Python features.

- [ ] **Step 4: Implement marker, dates, rows, and totals**

Add `before_insert` calling `_set_target_model`. Update `validate` to run currency, inclusive maximum-366-day validity, recurring row validation, and five totals. Continue one bulk `frappe.get_all("Employee", ...)` and existing Company currency behavior.

- [ ] **Step 5: Implement recurring overlap comparison**

Retain the Company `FOR UPDATE` serialization. In one parameterized locking query, load submitted `Recurring Plan` rows sharing Company, inclusive dates, and Employee IDs, including all five frequency values. Compare candidates in Python and reject the first shared positive frequency. Never inspect legacy `period_type` or `target_amount`.

- [ ] **Step 6: Run all Sales Target tests**

```bash
env PYTHONPATH="$PWD" /home/erpadmin/frappe-bench/env/bin/python -m unittest worldshading.worldshading.doctype.sales_target.test_sales_target -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add worldshading/worldshading/sales_target_utils.py \
  worldshading/worldshading/doctype/sales_target/sales_target.py \
  worldshading/worldshading/doctype/sales_target/test_sales_target.py
git commit -m "feat: validate recurring sales target plans"
```

---

### Task 3: Consolidated Plan Form Behavior

**Files:**
- Modify: `worldshading/worldshading/doctype/sales_target/sales_target.js`
- Modify: `worldshading/worldshading/doctype/sales_target/test_sales_target.py`
- Modify: `worldshading/worldshading/doctype/sales_target/test_sales_target_client.js`

**Interfaces:**
- Consumes Task 1 frequency fields and parent totals.
- Produces `set_employee_query(frm)`, `update_frequency_totals(frm)`, and existing Company currency synchronization.
- Removes fixed-period date suggestions and parent `period_type` handler.

- [ ] **Step 1: Rewrite executable client tests first**

Assert refresh installs the Employee query and calculates five totals; every frequency change and row add/remove recalculates; blanks are zero and totals round to three decimals; Company change warns, synchronizes currency, and preserves rows; and no `period_type` handler/date mutation remains.

- [ ] **Step 2: Run client contract and verify RED**

```bash
env PYTHONPATH="$PWD" /home/erpadmin/frappe-bench/env/bin/python -m unittest worldshading.worldshading.doctype.sales_target.test_sales_target.TestSalesTargetClientContract -v
```

Expected: FAIL because the form still uses fixed-period behavior.

- [ ] **Step 3: Implement recurring form handlers**

Replace `update_target_total` with `update_frequency_totals`; register all five amount handlers and table add/remove events. Retain Employee query and Company currency behavior. Remove `set_period_defaults`, `pad_date_part`, and `period_type` handler.

- [ ] **Step 4: Verify**

Run all Sales Target tests plus `node --check` for the product and client-test JavaScript.

Expected: tests PASS and syntax checks exit `0`.

- [ ] **Step 5: Commit**

```bash
git add worldshading/worldshading/doctype/sales_target/sales_target.js \
  worldshading/worldshading/doctype/sales_target/test_sales_target.py \
  worldshading/worldshading/doctype/sales_target/test_sales_target_client.js
git commit -m "feat: support consolidated target entry"
```

---

### Task 4: Recurring Occurrence and Performance Engine

**Files:**
- Modify: `worldshading/worldshading/sales_target_utils.py`
- Modify: `worldshading/worldshading/report/sales_target_performance/sales_target_performance.py`
- Modify: `worldshading/worldshading/report/sales_target_performance/test_sales_target_performance.py`

**Interfaces:**
- Produces `get_occurrence(frequency, as_of_date, plan_from_date, plan_to_date)` returning date values `from_date`, `to_date`, `effective_to_date` and Boolean `not_started`.
- Produces `get_sales_aggregates(company, from_date, effective_to_date, employee_ids)` returning `{employee: {achieved_amount, invoice_count}}`.
- Produces `build_rows(target, frequency, occurrence, aggregates, as_of_date, current_date)` returning full-team ranked rows.
- Produces `get_report_summary(rows, currency)` returning v12 report-summary dictionaries.

- [ ] **Step 1: Write failing occurrence tests**

For a 2026 plan assert Daily `2026-11-04`; Saturday–Friday Weekly `2026-10-31` to `2026-11-06`; exact Monthly, Quarterly, and Annual boundaries; clipped weeks at plan edges; first occurrence with `not_started=True` before plan; final occurrence after plan; and rejection of unknown frequency.

- [ ] **Step 2: Run occurrence tests and verify RED**

Run the new occurrence test class directly.

Expected: FAIL because `get_occurrence` does not exist.

- [ ] **Step 3: Implement occurrence derivation**

Use `getdate`, `datetime.timedelta`, and v12 date helpers. Weekly starts Saturday; Monthly and Quarterly use calendar boundaries; Annual is full plan validity. Clip all boundaries to validity and return dates.

- [ ] **Step 4: Write failing recurring report tests**

Assert required target/frequency, submitted recurring model, permission/model checks before invoice access, targeted employees only, one parameterized Employee-filtered invoice aggregate, before/after-plan behavior, current versus historical final-day status, negative/zero sales, contribution denominator, team-wide rank/summary before Employee filtering, and six-item v12 return with `skip_total_row=1`.

- [ ] **Step 5: Run report tests and verify RED**

```bash
env PYTHONPATH="$PWD" /home/erpadmin/frappe-bench/env/bin/python -m unittest worldshading.worldshading.report.sales_target_performance.test_sales_target_performance -v
```

Expected: FAIL because the report is fixed-period.

- [ ] **Step 6: Implement recurring report execution**

Require `frequency`; reject legacy targets with `Select a recurring Sales Target plan.`; select the configured child field; derive occurrence; skip untargeted employees; and query targeted Employee IDs only. Keep permission checking before invoice access.

Update `calculate_metrics` with optional `current_date` defaulting to `nowdate`: a final day is active when it is today, but an unachieved historical completed final day is `Not Achieved`. Reject future As of Dates.

- [ ] **Step 7: Implement team contribution and summary**

Calculate contribution, rank, and summary from all frequency-targeted rows. Summary: Team Target, Team Achieved, Team Achievement %, Achieved count, On Track count, Behind count including Not Achieved. Apply Employee filter afterward.

- [ ] **Step 8: Run complete focused suite**

```bash
env PYTHONPATH="$PWD" /home/erpadmin/frappe-bench/env/bin/python -m unittest worldshading.worldshading.doctype.sales_target.test_sales_target worldshading.worldshading.report.sales_target_performance.test_sales_target_performance -v
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add worldshading/worldshading/sales_target_utils.py \
  worldshading/worldshading/report/sales_target_performance/sales_target_performance.py \
  worldshading/worldshading/report/sales_target_performance/test_sales_target_performance.py
git commit -m "feat: calculate recurring target performance"
```

---

### Task 5: Frequency Filter and Safe Report Drill-Down

**Files:**
- Modify: `worldshading/worldshading/report/sales_target_performance/sales_target_performance.js`
- Modify: `worldshading/worldshading/report/sales_target_performance/test_sales_target_performance.py`
- Modify: `worldshading/worldshading/report/sales_target_performance/test_sales_target_performance_client.js`

**Interfaces:**
- Consumes Task 4 row keys `company`, `sales_employee`, `from_date`, `effective_to_date`, `invoice_count`, `status`, `frequency`, rank, and contribution.
- Produces required Frequency filter and safe delegated Sales Invoice routing from Employee and Invoice Count cells.

- [ ] **Step 1: Extend executable client tests first**

Assert target Link filters submitted `Recurring Plan`; Frequency is required with Daily through Annual; As of Date and optional Employee remain; status uses v12 `indicator`; Employee and positive Invoice Count both create safe delegated links; and both route with Company, Employee, occurrence dates, and submitted status.

- [ ] **Step 2: Run report-client tests and verify RED**

Run the report metadata/client test class directly.

Expected: FAIL because recurring controls and Employee drill-down are absent.

- [ ] **Step 3: Implement filters and formatter**

Add Frequency after Sales Target. Extend target Link query with `target_model`. Share safe route attributes/delegated click handling for Employee and Invoice Count. Replace `indicator-pill` with v12 `indicator`.

- [ ] **Step 4: Run full verification**

```bash
env PYTHONPATH="$PWD" /home/erpadmin/frappe-bench/env/bin/python -m unittest worldshading.worldshading.doctype.sales_target.test_sales_target worldshading.worldshading.report.sales_target_performance.test_sales_target_performance -v
node --check worldshading/worldshading/doctype/sales_target/sales_target.js
node --check worldshading/worldshading/report/sales_target_performance/sales_target_performance.js
/home/erpadmin/frappe-bench/env/bin/python -m json.tool worldshading/worldshading/doctype/sales_target/sales_target.json >/dev/null
/home/erpadmin/frappe-bench/env/bin/python -m json.tool worldshading/worldshading/doctype/sales_target_detail/sales_target_detail.json >/dev/null
/home/erpadmin/frappe-bench/env/bin/python -m json.tool worldshading/worldshading/report/sales_target_performance/sales_target_performance.json >/dev/null
git diff --check
```

Expected: all tests pass and all syntax/JSON/diff checks exit `0`.

- [ ] **Step 5: Commit**

```bash
git add worldshading/worldshading/report/sales_target_performance/sales_target_performance.js \
  worldshading/worldshading/report/sales_target_performance/test_sales_target_performance.py \
  worldshading/worldshading/report/sales_target_performance/test_sales_target_performance_client.js
git commit -m "feat: add recurring target report controls"
```

---

### Task 6: Production Review and Controlled Transition Gates

**Files:**
- Verify only: all files modified in Tasks 1–5
- No source changes expected

**Interfaces:**
- Consumes reviewed commits from Tasks 1–5.
- Produces explicit approvals/evidence for metadata reload, report reload, consolidated plan creation, reconciliation, and legacy cancellation.

- [ ] **Step 1: Verify scope and safety**

Confirm only Sales Target, Sales Target Detail, Sales Target Performance, the shared utility, tests, and approved docs changed. Confirm no core, hooks, scheduler, workflow, invoice/employee writes, incentive files, unparameterized SQL, or hidden deploy commands.

- [ ] **Step 2: Run final isolated verification and whole-branch review**

Run Task 5 verification without Bench tests. Generate the standard review package, obtain one fresh-context review, and resolve Critical/Important findings in one TDD fix pass.

- [ ] **Step 3: Present Phase 1 metadata/controller approval**

Present objective, impacted DocTypes, medium additive-schema/validation risk, and non-destructive rollback. Request explicit approval for only:

```bash
bench --site erp.worldshading.com reload-doc worldshading doctype sales_target_detail
bench --site erp.worldshading.com reload-doc worldshading doctype sales_target
```

- [ ] **Step 4: After approval, reload and verify read-only**

Run only those commands in order. Verify fields, hidden legacy values, permissions, and the three unchanged legacy records. Do not create, submit, amend, cancel, or rewrite targets.

- [ ] **Step 5: Present Phase 2 report approval**

Present objective, existing report impact, low-medium read-only semantic risk, and report-only rollback. Request explicit approval for only:

```bash
bench --site erp.worldshading.com reload-doc worldshading report sales_target_performance
```

- [ ] **Step 6: After approval, reload and reconcile**

Verify browser filters. Before creating the consolidated plan, present its exact rows copied from legacy values and request separate approval. Reconcile all five frequency boundaries, two employee totals, any naturally present return, contribution, rank, status, summary, drill-down, and representative query duration without modifying invoices.

- [ ] **Step 7: Request separate legacy cancellation approval**

Only after the recurring plan is submitted and reconciled, present the three legacy names and request explicit cancellation approval. Never cancel or rewrite automatically.

- [ ] **Step 8: Final handoff**

Document commits, reload evidence, consolidated plan, reconciliations, timing, legacy disposition, deferred snapshots/points/commissions, and rollback posture.

## Self-Review Record

- Spec coverage: Tasks 1–5 cover metadata, validation, recurrence, report, permissions, performance, legacy handling, and UI; Task 6 owns production gates.
- Step scan: every step is one test, implementation, verification, commit, review, or approval action.
- Type/name consistency: Task 1 defines fieldnames, Task 2 centralizes them, and Tasks 3–5 consume them unchanged.
- Review Focus: validity limits, clipped weeks, legacy direct access, frequency-aware overlap, and filtered team context each have an owning test.
- Proportion: exact interfaces and assertions are specified without transcribing implementation bodies.
