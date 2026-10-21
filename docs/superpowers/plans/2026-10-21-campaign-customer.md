# Campaign Customer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a channel-neutral Campaign Customer record that schedules existing-customer outreach, preserves interaction notes, and links qualified customers to Opportunities.

**Architecture:** A standard parent DocType owns campaign/customer scheduling and derived summary fields; an editable child DocType stores immutable interaction history. A small v12 controller enforces cross-record rules, a form script handles contact convenience, and a custom-app CRM configuration contribution exposes the record without modifying ERPNext core.

**Tech Stack:** ERPNext 12, Frappe 12, Python 3.6, MariaDB, Frappe DocType JSON, Frappe form JavaScript.

**Spec:** `docs/superpowers/specs/2026-10-21-campaign-customer-design.md`

## Global Constraints

- Production environment: do not run `bench migrate`, `bench test`, restart, backup, restore, or cache-clearing commands.
- Do not execute `reload-doc`; only provide the exact child-first commands for manual review and execution.
- Keep all product changes in the `worldshading` custom app; do not modify ERPNext core.
- Code must support ERPNext/Frappe v12, Python 3.6, and the existing project style.
- Do not use type hints, dataclasses, `frappe.qb`, or APIs introduced after v12.
- Do not add Assignment, ToDo, workflow bypasses, automatic messaging, or automatic Opportunity creation.
- Preserve all unrelated uncommitted repository changes.

## Review Focus

- A new unsaved document has no `name`; duplicate validation must exclude the current record only when a name exists and must never construct an invalid filter.
- Interaction rows may contain blank or malformed dates during editing; summary calculation must ignore blank dates and reject invalid nonblank dates through normal Frappe validation rather than sorting strings incorrectly.
- An Opportunity must exist and have `opportunity_from = Customer` and `party_name` equal to the Campaign Customer's Customer.
- Customer or Contact records may lack phone, WhatsApp, or email values; client population must leave fields editable and must not overwrite values already entered by staff.
- Cashier permissions must permit campaign work but must not grant delete, export, share, submit, cancel, or permission-management rights.

---

## File Structure

- `worldshading/worldshading/doctype/campaign_interaction_log/`: child schema and empty v12 controller.
- `worldshading/worldshading/doctype/campaign_customer/`: parent schema, validation controller, form behavior, and isolated unit tests.
- `worldshading/config/crm.py`: CRM module-view contribution only.

### Task 1: Define the Parent and Child DocType Schemas

**Files:**

- Create: `worldshading/worldshading/doctype/campaign_interaction_log/__init__.py`
- Create: `worldshading/worldshading/doctype/campaign_interaction_log/campaign_interaction_log.json`
- Create: `worldshading/worldshading/doctype/campaign_interaction_log/campaign_interaction_log.py`
- Create: `worldshading/worldshading/doctype/campaign_customer/__init__.py`
- Create: `worldshading/worldshading/doctype/campaign_customer/campaign_customer.json`
- Create: `worldshading/worldshading/doctype/campaign_customer/campaign_customer.py`
- Create: `worldshading/worldshading/doctype/campaign_customer/test_campaign_customer.py`

**Interfaces:**

- Consumes: standard DocTypes `Campaign`, `Customer`, `Contact`, `User`, `Opportunity`, and `Call Log`.
- Produces: DocTypes `Campaign Customer` and `Campaign Interaction Log`; parent child-table field `interactions` targets `Campaign Interaction Log`.

- [ ] **Step 1: Write failing schema tests**

Add tests that load both JSON definitions and assert:

- Parent autoname is `naming_series:` and its series is `CC-.YYYY.-.#####`.
- Campaign, Customer, Caller, Planned Contact Date, Status, and Priority are required.
- Status, priority, Next Action, channel, and outcome options exactly match the approved spec.
- The field order contains the approved Section Break and Column Break layout.
- Summary fields are read-only and Interactions is a Table targeting Campaign Interaction Log.
- Campaign, Customer, Caller, Planned Contact Date, Status, and Priority are standard filters; the operational list columns are present.
- Campaign Interaction Log has `istable = 1`, required Interaction On, Channel, Handled By, Outcome, and Notes fields, and no independent permissions.
- Cashier has only create/read/write/report; Sales Manager and System Manager have the approved management rights.

- [ ] **Step 2: Run the isolated schema test and verify failure**

Run from `apps/worldshading`:

```bash
../../env/bin/python -m unittest worldshading.worldshading.doctype.campaign_customer.test_campaign_customer
```

Expected: FAIL because the DocType definitions do not exist yet. This is a direct mocked/unit invocation, not `bench test`, and it must not connect to a site database.

- [ ] **Step 3: Create both schemas and minimal v12 controllers**

Create the exact field layout from the spec. Use `from __future__ import unicode_literals`, `frappe.model.document.Document`, no type annotations, `default: "__user"` for Caller and Handled By, `track_changes: 1`, `allow_import: 1`, and `title_field: "customer_name"` on Campaign Customer. The child controller remains an empty `Document` subclass.

- [ ] **Step 4: Run the isolated schema test**

Run the Step 2 command.

Expected: PASS for all schema and permission assertions without database access.

- [ ] **Step 5: Commit the schemas**

```bash
git add worldshading/worldshading/doctype/campaign_customer worldshading/worldshading/doctype/campaign_interaction_log
git commit -m "feat: add campaign customer schemas"
```

### Task 2: Implement Server Validation and Summaries

**Files:**

- Modify: `worldshading/worldshading/doctype/campaign_customer/campaign_customer.py`
- Modify: `worldshading/worldshading/doctype/campaign_customer/test_campaign_customer.py`

**Interfaces:**

- Consumes: `CampaignCustomer.validate()`, `frappe.db.get_value`, child rows from `doc.get("interactions")`, and `frappe.utils.get_datetime`.
- Produces: `validate_unique_campaign_customer(doc)`, `update_interaction_summary(doc)`, and `validate_opportunity_customer(doc)`; these functions raise `frappe.ValidationError` through `frappe.throw` when invalid.

- [ ] **Step 1: Add failing controller tests**

Add database-mocked tests asserting:

- A new record builds duplicate filters without a `name != None` condition and rejects an existing Campaign + Customer pair.
- A saved record excludes its own name and accepts itself when no other record is returned.
- Empty interaction history sets count to zero without corrupting a manually planned follow-up.
- Unordered interaction rows select the newest valid Interaction On for Last Contact On and Last Outcome.
- Blank Interaction On rows are excluded from last-contact selection while still contributing to the row count during form editing.
- The newest non-empty child Next Follow-up is copied to the parent.
- A missing Opportunity, a Lead-based Opportunity, and another Customer's Opportunity are rejected.
- A Customer Opportunity for the same Customer is accepted.

- [ ] **Step 2: Run the controller tests and verify failure**

Run the Task 1 unittest command.

Expected: FAIL because the validation helpers are not implemented.

- [ ] **Step 3: Implement `CampaignCustomer.validate(self)`**

Call the helpers in this order:

1. `validate_unique_campaign_customer(self)`
2. `update_interaction_summary(self)`
3. `validate_opportunity_customer(self)`

This order rejects duplicates before performing optional cross-record conversion checks.

- [ ] **Step 4: Implement `validate_unique_campaign_customer(doc)`**

Use `frappe.db.get_value("Campaign Customer", filters, "name")`. Filters always contain Campaign and Customer; add `name: ["!=", doc.name]` only for a saved named record. Throw a translated message naming the Customer and Campaign when another record exists.

- [ ] **Step 5: Implement `update_interaction_summary(doc)`**

Set Number of Interactions from all rows. Among rows with Interaction On, compare values using `get_datetime`, then set Last Contact On and Last Outcome from the newest row. Copy the Next Follow-up from the newest dated row that has a non-empty Next Follow-up; preserve a manually planned parent value when no interaction has a follow-up.

- [ ] **Step 6: Implement `validate_opportunity_customer(doc)`**

When Opportunity is set, fetch `opportunity_from` and `party_name` as a dictionary. Throw if it does not exist, is not Customer-based, or belongs to a different Customer. Do not mutate the Opportunity.

- [ ] **Step 7: Run the isolated test suite**

Run the Task 1 unittest command.

Expected: PASS with all database calls mocked and no site/database connection.

- [ ] **Step 8: Commit controller behavior**

```bash
git add worldshading/worldshading/doctype/campaign_customer/campaign_customer.py worldshading/worldshading/doctype/campaign_customer/test_campaign_customer.py
git commit -m "feat: validate campaign customer activity"
```

### Task 3: Add Form Convenience and CRM Navigation

**Files:**

- Create: `worldshading/worldshading/doctype/campaign_customer/campaign_customer.js`
- Create: `worldshading/config/crm.py`
- Modify: `worldshading/worldshading/doctype/campaign_customer/test_campaign_customer.py`

**Interfaces:**

- Consumes: Frappe v12 `frm.set_query`, `frappe.contacts.doctype.contact.contact.contact_query`, and `frappe.db.get_value`; CRM module configuration `get_data()`.
- Produces: channel-neutral customer/contact field population and a CRM section labeled `Campaign Management` containing `Campaign Customer` and `Campaign`.

- [ ] **Step 1: Add failing navigation and client-contract tests**

Add tests that:

- Import `worldshading.config.crm.get_data()` and assert the Campaign Management section contains Campaign Customer and Campaign doctype items.
- Inspect the client script and assert it registers Campaign Customer handlers for `setup`, `customer`, and `contact_person`.
- Assert the script uses the v12 contact query with `link_doctype: "Customer"` and the current Customer as `link_name`.
- Assert the customer fetch requests `customer_name`, `customer_group`, `territory`, `mobile_no`, and `email_id`.
- Assert the contact fetch requests `mobile_no`, `phone`, and `email_id` and only fills blank values.

- [ ] **Step 2: Run the tests and verify failure**

Run the Task 1 unittest command.

Expected: FAIL because the form script and CRM configuration do not exist.

- [ ] **Step 3: Implement the CRM module contribution**

Create `get_data()` in `worldshading/config/crm.py` returning one `Campaign Management` section with doctype items for Campaign Customer and Campaign. Use `from __future__ import unicode_literals` and `frappe._`; do not modify `erpnext/config/crm.py`.

- [ ] **Step 4: Implement Campaign Customer form setup**

Register the Contact Person query using `frappe.contacts.doctype.contact.contact.contact_query` with `link_doctype: "Customer"` and `link_name: frm.doc.customer`. Return no restrictive query until Customer is selected.

- [ ] **Step 5: Implement customer field population**

On Customer change, fetch `customer_name`, `customer_group`, `territory`, `mobile_no`, and `email_id`. Populate identity fields and fill Mobile Number and Email Address only when their current values are blank. Clear Contact Person when the Customer changes to prevent a stale cross-customer contact.

- [ ] **Step 6: Implement contact field population**

On Contact Person change, fetch `mobile_no`, `phone`, and `email_id`. Fill blank Mobile Number using mobile first and phone second, fill blank WhatsApp Number from mobile, and fill blank Email Address. Do not overwrite staff-entered values.

- [ ] **Step 7: Run all isolated unit tests**

Run the Task 1 unittest command.

Expected: PASS without a site/database connection.

- [ ] **Step 8: Run safe static verification**

Run only:

```bash
../../env/bin/python -m json.tool worldshading/worldshading/doctype/campaign_customer/campaign_customer.json >/dev/null
../../env/bin/python -m json.tool worldshading/worldshading/doctype/campaign_interaction_log/campaign_interaction_log.json >/dev/null
../../env/bin/python -m py_compile worldshading/worldshading/doctype/campaign_customer/campaign_customer.py worldshading/worldshading/doctype/campaign_interaction_log/campaign_interaction_log.py worldshading/config/crm.py
git diff --check
```

Expected: all commands exit 0. Do not invoke bench or load a site.

- [ ] **Step 9: Commit client and CRM integration**

```bash
git add worldshading/worldshading/doctype/campaign_customer/campaign_customer.js worldshading/worldshading/doctype/campaign_customer/test_campaign_customer.py worldshading/config/crm.py
git commit -m "feat: expose campaign customers in CRM"
```

### Task 4: Final Review and Manual Production Handoff

**Files:**

- Review: all files created or modified in Tasks 1–3.
- Do not modify: ERPNext core, `worldshading/hooks.py`, Call Assistant, Service Visit, or unrelated dirty files.

**Interfaces:**

- Consumes: completed DocType files and passing isolated/static checks.
- Produces: an evidence-based handoff containing exact manual reload order and post-reload verification; performs no production reload.

- [ ] **Step 1: Review the scoped diff**

Run:

```bash
git diff HEAD~3 -- worldshading/worldshading/doctype/campaign_customer worldshading/worldshading/doctype/campaign_interaction_log worldshading/config/crm.py
git status --short
```

Confirm no existing production file was changed and unrelated dirty files remain untouched.

- [ ] **Step 2: Re-run isolated and static verification**

Repeat Task 3 Steps 7 and 8. Record the command results in the final handoff.

- [ ] **Step 3: Provide reload commands without executing them**

Supply commands in dependency order, substituting the real production site name only after reading the existing sites directory without changing it:

```bash
bench --site <site> reload-doc worldshading doctype campaign_interaction_log
bench --site <site> reload-doc worldshading doctype campaign_customer
```

State explicitly that these commands were not executed.

- [ ] **Step 4: Provide post-reload checks and rollback**

Give the approved manual checks for permissions, duplicate prevention, multi-channel interactions, Opportunity/customer matching, list filters, and CRM visibility. Before reload, rollback is file/commit reversion; after records exist, export data and use a separately approved DocType removal procedure.
