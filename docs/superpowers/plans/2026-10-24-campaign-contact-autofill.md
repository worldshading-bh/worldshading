# Campaign Contact Autofill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fill missing Campaign Customer contact person, mobile, WhatsApp and email values from the Customer and its primary Contact.

**Architecture:** Keep immediate form autofill in the v12 client script and add equivalent blank-only server validation for bulk/import paths. Both paths use Contact values first and Customer values as fallback.

**Tech Stack:** ERPNext 12, Frappe 12, Python 3.6, Frappe form JavaScript, Python `unittest` mocks, Node behavior tests.

**Spec:** `docs/superpowers/specs/2026-10-24-campaign-contact-autofill-design.md`

## Global Constraints

- Work only in the `worldshading` custom app and preserve ERPNext/Frappe v12 compatibility.
- Fill blank fields only and never overwrite manual values.
- Do not run migrations, Bench tests, restarts, or cache-clearing commands.
- Do not update existing production records as part of implementation.

## Review Focus

- Customer without a primary Contact uses Customer mobile/email fallbacks.
- Primary Contact without mobile/phone leaves numbers blank unless Customer mobile exists.
- Server validation preserves existing manual values; changing Customer on the
  form resets Contact Person to the new Customer's primary Contact.
- Bulk creation gets the same autofill through normal document validation.
- Changing Customer clears only values previously supplied automatically.

---

### Task 1: Add Contact Autofill

**Files:**

- Modify: `worldshading/worldshading/doctype/campaign_customer/campaign_customer.py`
- Modify: `worldshading/worldshading/doctype/campaign_customer/campaign_customer.js`
- Modify: `worldshading/worldshading/doctype/campaign_customer/test_campaign_customer.py`
- Modify: `worldshading/worldshading/doctype/campaign_customer/test_campaign_customer.js`

**Interfaces:**

- Produces: `set_missing_contact_details(doc)` for server validation.
- Consumes: `Customer.customer_primary_contact`, `Customer.mobile_no`, `Customer.email_id`, and Contact `mobile_no`, `phone`, `email_id`.

- [x] **Step 1: Add failing Python tests**

Assert blank-only Contact-first values, Customer fallback values, preservation
of manual values, and invocation through Campaign Customer validation.

- [x] **Step 2: Run the Python tests and verify the expected failure**

Run `/home/erpadmin/frappe-bench/env/bin/python -m unittest worldshading.worldshading.doctype.campaign_customer.test_campaign_customer`.

- [x] **Step 3: Implement the server helper**

Use `frappe.db.get_value` only; call the helper from `validate` before existing
Campaign Customer validation and summary behavior.

- [x] **Step 4: Run the Python tests and verify they pass**

- [x] **Step 5: Add failing JavaScript behavior tests**

Assert Customer selection sets primary Contact plus available values, Contact
selection prefers Contact details, and manual fields remain unchanged.

- [x] **Step 6: Run the Node test and verify the expected failure**

Run `node worldshading/worldshading/doctype/campaign_customer/test_campaign_customer.js`.

- [x] **Step 7: Implement immediate form autofill**

Extend the existing `frappe.db.get_value` calls without changing the Record
Contact dialog or unrelated form behavior.

- [x] **Step 8: Verify focused and adjacent isolated tests**

Run Campaign Customer Python/form/list tests, report client tests, Python
compilation, JavaScript syntax checks, and `git diff --check`.

- [x] **Step 9: Commit the task-scoped change**

Commit only the spec, plan, controller, form script, and their focused tests.
