# Simple Campaign Customer Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn Campaign Customer into a one-dialog cashier follow-up queue and bulk-create ordered campaign work from Customer Retention Analysis.

**Architecture:** Keep the existing DocType, list, and prepared report. Permission-aware whitelisted methods in the Campaign Customer controller own interaction recording and ordered bulk creation; v12 form/list/report scripts only collect input and refresh their views.

**Tech Stack:** ERPNext 12, Frappe 12, Python 3.6, MariaDB, Frappe DocType/List/Script Report JavaScript, Python `unittest` mocks, Node behavior tests.

**Spec:** `docs/superpowers/specs/2026-10-24-simple-campaign-customer-workflow-design.md`

## Global Constraints

- Production environment: do not run `bench migrate`, `bench test`, `reload-doc`, report execution against the production site, restarts, backups, restores, or cache-clearing commands.
- Keep product changes inside the `worldshading` custom app; do not modify ERPNext or Frappe core.
- Support ERPNext/Frappe v12 and Python 3.6; do not use type annotations, dataclasses, `frappe.qb`, or post-v12 APIs.
- Preserve existing Campaign Customer, interaction, Opportunity, permission, accounting, and stock behavior.
- Do not create ToDo/Assignment records or a standard Frappe Workflow.
- Implement in the isolated `feature/simplify-campaign-customer` branch and do not touch dirty files in the main checkout.

## Review Focus

- A terminal contact with no next date must clear an older current follow-up; Task 1 pins this summary behavior.
- A forged quick-action request must still enforce write permission and fixed option values; Task 1 pins both.
- Repeated bulk batches must skip existing Campaign/Customer pairs and continue in displayed order; Task 2 pins this allocation behavior.
- Duplicate customer codes in one browser payload must never consume multiple batch positions; Task 2 pins stable de-duplication.
- A prepared report with no loaded rows must not expose a usable bulk action or send an empty mutation request; Task 3 pins the client guard.

---

## File Structure

- `worldshading/worldshading/doctype/campaign_customer/campaign_customer.json` — simplified field order and latest-note summary metadata.
- `worldshading/worldshading/doctype/campaign_customer/campaign_customer.py` — validation, summary calculation, quick contact method, and bulk creation method.
- `worldshading/worldshading/doctype/campaign_customer/campaign_customer.js` — form quick-contact dialog plus existing contact autofill.
- `worldshading/worldshading/doctype/campaign_customer/campaign_customer_list.js` — cashier list indicators and row quick action.
- `worldshading/worldshading/doctype/campaign_customer/test_campaign_customer.py` — isolated schema/controller/API tests.
- `worldshading/worldshading/doctype/campaign_customer/test_campaign_customer.js` — form dialog behavior test.
- `worldshading/worldshading/doctype/campaign_customer/test_campaign_customer_list.js` — list quick-action behavior test.
- `worldshading/worldshading/report/customer_retention_analysis/customer_retention_analysis.js` — bulk-create dialog using displayed ordered rows.
- `worldshading/worldshading/report/customer_retention_analysis/test_customer_retention_analysis_client.js` — report bulk-action behavior test.

### Task 1: Simplify the Form and Add One-Step Contact Recording

**Files:**

- Modify: `worldshading/worldshading/doctype/campaign_customer/campaign_customer.json`
- Modify: `worldshading/worldshading/doctype/campaign_customer/campaign_customer.py`
- Modify: `worldshading/worldshading/doctype/campaign_customer/campaign_customer.js`
- Modify: `worldshading/worldshading/doctype/campaign_customer/test_campaign_customer.py`
- Modify: `worldshading/worldshading/doctype/campaign_customer/test_campaign_customer.js`

**Interfaces:**

- Consumes: existing Campaign Customer validation and Campaign Interaction Log rows.
- Produces: `record_contact(name, channel, outcome, notes, status, next_follow_up=None, next_action=None)` and read-only `latest_note` summary.

- [ ] **Step 1: Add failing schema and summary tests**

Assert the simplified section/column order, collapsible history, visible current
summary fields, read-only `latest_note`, and that the latest dated interaction
sets Last Contact, Last Outcome, Latest Note, and Next Follow-up even when the
newest follow-up is blank.

- [ ] **Step 2: Add failing `record_contact` server tests**

Mock document loading/saving and assert write permission, allowed options,
required Notes, required follow-up for Follow Up/Interested, automatic current
user/time values, exactly one appended row, current Status/Next Action updates,
and returned summaries.

- [ ] **Step 3: Run the Campaign Customer Python tests and verify failure**

Run from the isolated app worktree:

```bash
/home/erpadmin/frappe-bench/env/bin/python -m unittest worldshading.worldshading.doctype.campaign_customer.test_campaign_customer
```

Expected: FAIL for the new schema, summary, and missing quick-action API.

- [ ] **Step 4: Implement the schema, summary, and `record_contact` method**

Use fixed module-level tuples for allowed Channel, Outcome, Status, and Next
Action values. Use normal `get_doc`, `check_permission`, `append`, and `save`
APIs; do not use SQL.

- [ ] **Step 5: Add failing form-dialog behavior tests**

Extend the Node sandbox to assert a saved document shows Record Contact, the
dialog uses the approved fields/options, outcome changes suggest a status, a
successful call refreshes the document, and new/unsaved documents do not show
the action.

- [ ] **Step 6: Implement the form Record Contact dialog**

Preserve existing Customer/Contact autofill. Use v12 `frappe.ui.Dialog`,
`frm.add_custom_button`, and `frappe.call`; keep status user-editable and require
Next Follow-up in the dialog for Follow Up or Interested.

- [ ] **Step 7: Run Task 1 Python and JavaScript tests**

```bash
/home/erpadmin/frappe-bench/env/bin/python -m unittest worldshading.worldshading.doctype.campaign_customer.test_campaign_customer
node worldshading/worldshading/doctype/campaign_customer/test_campaign_customer.js
```

Expected: PASS without site/database access.

- [ ] **Step 8: Commit the one-step form workflow**

```bash
git add worldshading/worldshading/doctype/campaign_customer
git commit -m "feat: simplify campaign contact recording"
```

### Task 2: Add the Cashier List Queue and Ordered Bulk Creation

**Files:**

- Create: `worldshading/worldshading/doctype/campaign_customer/campaign_customer_list.js`
- Create: `worldshading/worldshading/doctype/campaign_customer/test_campaign_customer_list.js`
- Modify: `worldshading/worldshading/doctype/campaign_customer/campaign_customer.py`
- Modify: `worldshading/worldshading/doctype/campaign_customer/test_campaign_customer.py`

**Interfaces:**

- Consumes: Task 1 `record_contact()` and dialog field contract.
- Produces: `bulk_create_campaign_customers(campaign, customers, caller, planned_contact_date, priority="Standard", batch_size=10)` returning created names, skipped customer codes, and counts.

- [ ] **Step 1: Add failing ordered bulk-creation tests**

Assert create permission, required inputs, maximum 250 source customers, batch
size 1–250, stable de-duplication, one existing-record query, skip-and-continue
ordering, standard inserts with Planned status, and propagation of insert errors.

- [ ] **Step 2: Run the Python test and verify failure**

Run Task 1's Python command.

Expected: FAIL because the bulk interface is absent.

- [ ] **Step 3: Implement `bulk_create_campaign_customers`**

Use `frappe.parse_json`, `frappe.has_permission`, `frappe.get_all`, and
`frappe.get_doc({...}).insert()`. Do not catch unexpected insert exceptions and
do not use SQL.

- [ ] **Step 4: Add failing list behavior tests**

Assert active rows show a Record Contact button, Converted/Closed rows do not,
status indicators use stable colors, the dialog calls Task 1's server method,
and success refreshes the list.

- [ ] **Step 5: Implement `campaign_customer_list.js`**

Use v12 `frappe.listview_settings`, `add_fields`, `get_indicator`, and the
supported row `button` contract. Keep its dialog contract identical to the form.

- [ ] **Step 6: Run Task 2 Python and JavaScript tests**

```bash
/home/erpadmin/frappe-bench/env/bin/python -m unittest worldshading.worldshading.doctype.campaign_customer.test_campaign_customer
node worldshading/worldshading/doctype/campaign_customer/test_campaign_customer_list.js
```

Expected: PASS without site/database access.

- [ ] **Step 7: Commit the queue and bulk server behavior**

```bash
git add worldshading/worldshading/doctype/campaign_customer
git commit -m "feat: add campaign follow-up queue"
```

### Task 3: Create Ordered Campaign Batches from Retention Results

**Files:**

- Modify: `worldshading/worldshading/report/customer_retention_analysis/customer_retention_analysis.js`
- Modify: `worldshading/worldshading/report/customer_retention_analysis/test_customer_retention_analysis_client.js`

**Interfaces:**

- Consumes: Task 2 `bulk_create_campaign_customers(...)` and the report's ordered `report.data` rows.
- Produces: a **Create Campaign Customers** report button and manager dialog.

- [ ] **Step 1: Add failing report-client tests**

Assert onload registers one inner button; no-data use shows a clear message and
makes no server call; the dialog displays source count and Campaign, Caller,
Planned Contact Date, Priority, and Batch Size fields; and submit sends unique
ordered displayed customers to Task 2's exact method.

- [ ] **Step 2: Run the client test and verify failure**

```bash
node worldshading/worldshading/report/customer_retention_analysis/test_customer_retention_analysis_client.js
```

Expected: FAIL because the bulk action does not exist.

- [ ] **Step 3: Implement the report bulk-create dialog**

Use v12 `report.page.add_inner_button`, `frappe.ui.Dialog`, and `frappe.call`.
Limit the payload to 250 unique customer codes, confirm the result count, show
created/skipped totals, and refresh the report after success.

- [ ] **Step 4: Run the report Python and client suites**

```bash
/home/erpadmin/frappe-bench/env/bin/python -m unittest worldshading.worldshading.report.customer_retention_analysis.test_customer_retention_analysis
node worldshading/worldshading/report/customer_retention_analysis/test_customer_retention_analysis_client.js
```

Expected: PASS; the server report stays read-only and unchanged.

- [ ] **Step 5: Commit report integration**

```bash
git add worldshading/worldshading/report/customer_retention_analysis/customer_retention_analysis.js worldshading/worldshading/report/customer_retention_analysis/test_customer_retention_analysis_client.js
git commit -m "feat: create campaign batches from retention report"
```

### Task 4: Complete Isolated Verification

**Files:**

- Modify only if a verification failure identifies a task-scoped defect.

**Interfaces:**

- Consumes: Tasks 1–3.
- Produces: verified ERPNext v12-compatible branch ready for review/integration.

- [ ] **Step 1: Run all isolated behavior tests**

Run both Python unittest modules and all three Node behavior scripts from Tasks
1–3. Expected: all pass without a site/database connection.

- [ ] **Step 2: Run static validation**

Parse both DocType JSON files, compile the modified Python controller, run
`node --check` for each modified/created JavaScript file, and run
`git diff --check`. Expected: zero errors.

- [ ] **Step 3: Review production safety**

Confirm no core file, hook, workflow, permission role, accounting/stock code, or
prohibited command changed; inspect `git status` and task-scoped diff.

- [ ] **Step 4: Commit the design and plan**

```bash
git add docs/superpowers/specs/2026-10-24-simple-campaign-customer-workflow-design.md docs/superpowers/plans/2026-10-24-simple-campaign-customer-workflow.md
git commit -m "docs: design simple campaign workflow"
```
