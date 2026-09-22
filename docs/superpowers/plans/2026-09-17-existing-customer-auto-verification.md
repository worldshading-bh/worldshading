# Existing Customer Automatic CR Verification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Automatically and gradually verify eligible historical Bahrain company Customers through Sijilat, including safe renaming, rate limiting and three-attempt handling for temporary failures.

**Architecture:** A five-minute cron dispatcher selects at most one eligible historical Customer and enqueues an isolated short job. The worker revalidates eligibility, records its attempt before the external request, reuses the existing Sijilat and name-matching functions, and classifies the result as verified, permanently not verified, or temporarily retryable.

**Tech Stack:** Python 3.6, Frappe 12 scheduler/background jobs, ERPNext 12 Customer, `unittest` with mocked Frappe/Sijilat boundaries.

**Spec:** `docs/superpowers/specs/2026-09-17-existing-customer-auto-verification-design.md`

## Global Constraints

- This is a live production ERPNext 12 / Frappe 12 server.
- Keep all implementation in the `worldshading` custom app; do not modify ERPNext or Frappe core.
- Do not use type hints, dataclasses, `frappe.qb` or APIs introduced after Frappe 12.
- Process at most one Customer every five minutes.
- The existing name approval rule remains strictly greater than 50 percent.
- Automatic CR verification must never grant, remove or change Secret Price List authorization.
- Do not create a manual-review queue or migration audit DocType.
- Tests must mock Sijilat and must never call the public API.
- Do not run restart, migrate, cache-clear, scheduler execution or bench tests without separate explicit authorization.

---

## File Structure

- Modify `worldshading/api/sijilat.py`: eligibility, local CR validation, dispatcher, worker, attempt handling and temporary/permanent error classification.
- Create `worldshading/api/test/test_sijilat_auto_verification.py`: isolated unit tests for selection, outcomes, retries and field safety.
- Modify `worldshading/hooks.py`: add the five-minute dispatcher to the existing cron group.
- Modify `worldshading/Documentation/customer_verification_and_secret_pricing.md`: document the historical migration and operational controls.

No Custom Field, patch, fixture or database schema change is required. The implementation reuses `business_verification_status`, `last_sijilat_check` and `sijilat_recheck_attempts`.

---

### Task 1: Add eligibility and CR-format boundaries

**Files:**
- Modify: `worldshading/api/sijilat.py:15-52, 266-271`
- Create: `worldshading/api/test/test_sijilat_auto_verification.py`

**Interfaces:**
- Produces: `_is_valid_customer_cr(value) -> bool`
- Produces: `_is_existing_customer_auto_verification_eligible(customer_doc, checked_at=None) -> bool`
- Consumes: existing Customer fields `disabled`, `customer_type`, `territory`, `cr_no`, `business_verification_status`, `last_sijilat_check`, and `sijilat_recheck_attempts`.

- [ ] **Step 1: Create failing unit tests for local CR validation**

Add a Python 3.6-compatible `unittest.TestCase` that imports `sijilat` and verifies:

```python
def test_auto_verification_cr_format_accepts_supported_value(self):
	self.assertTrue(sijilat._is_valid_customer_cr("90666-1"))

def test_auto_verification_cr_format_rejects_missing_branch(self):
	self.assertFalse(sijilat._is_valid_customer_cr("90666"))

def test_auto_verification_cr_format_rejects_letters(self):
	self.assertFalse(sijilat._is_valid_customer_cr("90A66-1"))
```

- [ ] **Step 2: Add failing unit tests for Customer eligibility**

Use `types.SimpleNamespace` and a fixed `datetime.datetime(2026, 9, 17, 12, 0)` to cover:

```python
def _customer(self, **overrides):
	values = {
		"disabled": 0,
		"customer_type": "Company",
		"territory": "Bahrain",
		"cr_no": "90666-1",
		"business_verification_status": "",
		"last_sijilat_check": None,
		"sijilat_recheck_attempts": 0,
	}
	values.update(overrides)
	return SimpleNamespace(**values)
```

Assert that the baseline is eligible, while disabled, Individual, non-Bahrain,
missing-CR, non-empty-status and three-attempt Customers are ineligible. Assert that a
check 23 hours ago is ineligible and a check 25 hours ago is eligible.

- [ ] **Step 3: Run only the new unit-test module and confirm the expected failure**

Planned command, to be run only after separate authorization:

```bash
./env/bin/python -m unittest worldshading.api.test.test_sijilat_auto_verification
```

Expected result: failure because the two helper functions do not exist.

- [ ] **Step 4: Add constants and minimal helper implementations**

In `sijilat.py`, import `add_days` and `get_datetime`, and add:

```python
AUTO_VERIFICATION_RETRY_HOURS = 24


def _is_valid_customer_cr(value):
	value = str(value or "").strip()
	return bool(re.match(r"^[0-9]{4,6}-[0-9]{1,3}$", value))


def _is_existing_customer_auto_verification_eligible(customer_doc, checked_at=None):
	checked_at = get_datetime(checked_at or now_datetime())
	last_check = get_datetime(customer_doc.last_sijilat_check) if customer_doc.last_sijilat_check else None
	return bool(
		not cint(customer_doc.disabled) and
		customer_doc.customer_type == "Company" and
		customer_doc.territory == "Bahrain" and
		customer_doc.cr_no and
		not customer_doc.business_verification_status and
		cint(customer_doc.sijilat_recheck_attempts) < MAX_AUTOMATIC_RECHECK_ATTEMPTS and
		(not last_check or last_check <= add_days(checked_at, -1))
	)
```

- [ ] **Step 5: Reuse `_is_valid_customer_cr` inside `fetch_cr_details`**

Preserve the current user-facing error text. Split `cr_no` and `branch_no` as today,
rebuild `"{0}-{1}".format(cr_no, branch_no)`, and call the shared helper so manual and
automatic validation cannot diverge.

- [ ] **Step 6: Run the isolated unit tests and confirm they pass**

Planned command only; do not run without authorization:

```bash
./env/bin/python -m unittest worldshading.api.test.test_sijilat_auto_verification
```

Expected result: all Task 1 tests pass without network access.

- [ ] **Step 7: Commit Task 1 files only**

```bash
git add worldshading/api/sijilat.py worldshading/api/test/test_sijilat_auto_verification.py
git commit -m "test: define historical CR verification eligibility"
```

---

### Task 2: Implement one-Customer dispatcher

**Files:**
- Modify: `worldshading/api/sijilat.py:346-398`
- Modify: `worldshading/api/test/test_sijilat_auto_verification.py`

**Interfaces:**
- Consumes: `_is_existing_customer_auto_verification_eligible(customer_doc, checked_at=None)` from Task 1.
- Produces: `enqueue_existing_customer_cr_verification() -> customer name or None`.
- Produces background call to `worldshading.api.sijilat.auto_verify_existing_customer_cr` with keyword `customer`.

- [ ] **Step 1: Write failing dispatcher tests**

Mock `frappe.get_all`, `frappe.enqueue`, and `now_datetime`. Test that the dispatcher:

- requests enabled Bahrain Company Customers with CR numbers and empty status;
- requests only fields needed by the eligibility helper;
- enqueues the first eligible candidate on queue `short` with timeout `60`;
- uses job name `sijilat_existing_customer_auto_verification|<customer>`;
- passes `customer=<name>`;
- stops after one enqueue; and
- does not enqueue when all candidates are in their cooldown.

The key assertion is:

```python
enqueue.assert_called_once_with(
	"worldshading.api.sijilat.auto_verify_existing_customer_cr",
	queue="short",
	timeout=60,
	job_name="sijilat_existing_customer_auto_verification|CM0001",
	customer="CM0001"
)
```

- [ ] **Step 2: Run the dispatcher tests and confirm they fail**

Planned command only:

```bash
./env/bin/python -m unittest worldshading.api.test.test_sijilat_auto_verification.TestExistingCustomerDispatcher
```

Expected result: failure because the dispatcher is not defined.

- [ ] **Step 3: Implement the dispatcher**

Use `frappe.get_all` rather than SQL. Query oldest candidates first with these database
filters:

```python
filters={
	"disabled": 0,
	"customer_type": "Company",
	"territory": "Bahrain",
	"cr_no": ["!=", ""],
	"business_verification_status": ["is", "not set"],
	"sijilat_recheck_attempts": ["<", MAX_AUTOMATIC_RECHECK_ATTEMPTS]
}
```

Fetch `name`, all eligibility fields, `creation`, and order by
`last_sijilat_check asc, creation desc`. Limit the candidate window to 20, skip candidates
inside the cooldown, enqueue only the first eligible Customer, return its name for
observability/tests, and return `None` if no candidate is eligible.

- [ ] **Step 4: Run the dispatcher tests and confirm they pass**

Planned command only; expected result is PASS with no Sijilat call.

- [ ] **Step 5: Commit Task 2 files only**

```bash
git add worldshading/api/sijilat.py worldshading/api/test/test_sijilat_auto_verification.py
git commit -m "feat: enqueue historical CR checks gradually"
```

---

### Task 3: Implement worker outcomes and retry handling

**Files:**
- Modify: `worldshading/api/sijilat.py:95-111, 222-264, 398-448`
- Modify: `worldshading/api/test/test_sijilat_auto_verification.py`

**Interfaces:**
- Consumes: `_fetch_customer_cr_verification(customer_doc) -> dict`.
- Consumes: `_get_business_name_match(customer_name, official_name_en, official_name_ar=None) -> dict`.
- Consumes: `_validate_unique_customer_cr(customer_doc)`.
- Produces: `SijilatTemporaryError`, a `frappe.ValidationError` subclass.
- Produces: `SijilatPermanentError`, a `frappe.ValidationError` subclass.
- Produces: `auto_verify_existing_customer_cr(customer) -> status string or None`.

- [ ] **Step 1: Write failing tests for temporary/permanent exception classification**

Mock HTTP/token boundaries and verify:

- network, token, timeout, server and invalid-response failures become
  `SijilatTemporaryError`;
- a missing official English name becomes `SijilatPermanentError`; and
- a mismatched returned CR becomes `SijilatPermanentError`.

Both exception classes must remain subclasses of `frappe.ValidationError` so the existing
manual Verify CR UI continues to receive normal Frappe validation messages.

- [ ] **Step 2: Write failing worker tests**

With `frappe.get_doc`, `frappe.db.set_value`, `frappe.db.commit`, Sijilat fetch and name
matching mocked, cover these exact outcomes:

1. Eligible verified record with score `50.01`: official rename, details/expiry/status
   saved, verification flag set, attempts reset, no Price List field changed.
2. Score `50.00`: status becomes `Not Verified`, no rename/details stored.
3. Invalid local CR: no Sijilat call, status becomes `Not Verified`.
4. Duplicate CR: no Sijilat call after duplicate validation fails; status becomes
   `Not Verified`.
5. Returned `Expired` or `Rejected`: status becomes `Not Verified`, no rename/details.
6. First and second `SijilatTemporaryError`: status remains empty, attempts increment,
   check time is stored.
7. Third `SijilatTemporaryError`: status becomes `Not Verified` and attempts remain `3`.
8. Customer made ineligible after enqueue: worker returns without API call or write.

The successful Customer mock must assert that no assignment is made to
`default_price_list`, `customer_price_list` or any Secret Price List field.

- [ ] **Step 3: Run the worker tests and confirm the expected failures**

Planned command only:

```bash
./env/bin/python -m unittest worldshading.api.test.test_sijilat_auto_verification.TestExistingCustomerWorker
```

Expected result: failures because worker and exception classes are absent.

- [ ] **Step 4: Add exception classes and tighten external-error conversion**

Define the two `frappe.ValidationError` subclasses near the constants. Wrap both token
and CR-detail HTTP/JSON operations in `fetch_cr_details`; raise
`SijilatTemporaryError` with the existing safe user message for integration failures.
Raise `SijilatPermanentError` from `_fetch_customer_cr_verification` for missing official
English name or returned-CR mismatch.

Do not include the hidden Sijilat commercial name in exceptions or error-log titles.

- [ ] **Step 5: Implement permanent failure helper**

Add a focused helper that updates only:

```python
{
	"business_verification_status": "Not Verified",
	"last_sijilat_check": checked_at,
	"sijilat_recheck_attempts": attempt_count
}
```

It must not write `customer_name`, `verified_business_details`, `cr_expiry_date` or any
pricing field.

- [ ] **Step 6: Implement `auto_verify_existing_customer_cr`**

The worker must:

1. Load the Customer and return if eligibility changed.
2. Increment and store attempt/check fields before the external request.
3. Commit that attempt before calling Sijilat so no external call occurs inside an open
   write transaction.
4. Permanently reject invalid format and duplicate CR without calling Sijilat.
5. Catch `SijilatPermanentError` as permanent non-verification.
6. Catch `SijilatTemporaryError` and unexpected exceptions as temporary; log only the
   unexpected/temporary technical traceback with the Customer ID.
7. On the third temporary failure, set `Not Verified`; otherwise preserve empty status.
8. Convert returned `Expired` or `Rejected` to `Not Verified` without storing returned
   identity/details.
9. Apply the existing name matcher and permanently reject scores at or below 50.
10. For success, set official English name, details, expiry, `Verified`, check time and
    zero attempts; set `customer_doc.flags.sijilat_verification = True`; call
    `customer_doc.save()`.

- [ ] **Step 7: Run all new unit tests and inspect assertions**

Planned command only; expected result: all tests pass with mocked network calls.

- [ ] **Step 8: Commit Task 3 files only**

```bash
git add worldshading/api/sijilat.py worldshading/api/test/test_sijilat_auto_verification.py
git commit -m "feat: auto verify historical Bahrain customers"
```

---

### Task 4: Register the five-minute scheduler safely

**Files:**
- Modify: `worldshading/hooks.py:207-215`
- Modify: `worldshading/api/test/test_sijilat_auto_verification.py`

**Interfaces:**
- Consumes: `worldshading.api.sijilat.enqueue_existing_customer_cr_verification` from Task 2.
- Produces: Frappe cron registration under the existing `*/5 * * * *` group.

- [ ] **Step 1: Add a failing hook-registration test**

Import `worldshading.hooks` and assert:

```python
self.assertIn(
	"worldshading.api.sijilat.enqueue_existing_customer_cr_verification",
	hooks.scheduler_events["cron"]["*/5 * * * *"]
)
```

- [ ] **Step 2: Add the dispatcher to the existing five-minute cron list**

Append exactly:

```python
"worldshading.api.sijilat.enqueue_existing_customer_cr_verification"
```

Preserve all existing reminder and sent-item scheduler entries.

- [ ] **Step 3: Perform static verification only**

Without executing bench tests or schedulers, inspect the hook dictionary and run Python
syntax compilation only if separately authorized. Confirm there is one registration and
no change to daily/monthly Sijilat hooks.

- [ ] **Step 4: Commit Task 4 files only**

```bash
git add worldshading/hooks.py worldshading/api/test/test_sijilat_auto_verification.py
git commit -m "feat: schedule gradual historical CR checks"
```

---

### Task 5: Update operational documentation and complete static review

**Files:**
- Modify: `worldshading/Documentation/customer_verification_and_secret_pricing.md:270-344`

**Interfaces:**
- Documents: dispatcher path, worker path, eligibility, five-minute limit, retry policy,
  outcomes, independence from Secret Price Lists and operational stop procedure.

- [ ] **Step 1: Add a historical auto-verification section**

Document the exact method names:

```text
worldshading.api.sijilat.enqueue_existing_customer_cr_verification
worldshading.api.sijilat.auto_verify_existing_customer_cr
```

State that only blank-status, enabled Bahrain Company Customers with a CR participate;
one Customer is queued every five minutes; scores must be above 50%; valid matches are
renamed; permanent failures become `Not Verified`; temporary errors retry after 24 hours
up to three times; no pricing fields are changed.

- [ ] **Step 2: Document operating and rollback guidance**

Explain that removing/commenting the cron entry stops new automatic checks, queued jobs
must be allowed to finish or be handled through normal worker operations, and already
renamed Customers require individual restoration from ERPNext version/activity history.

- [ ] **Step 3: Conduct static self-review**

Review the diff for:

- ERPNext/Frappe 12 compatibility;
- no core changes;
- no schema/fixture change;
- no pricing-field writes;
- no API calls from tests;
- one Customer per dispatcher execution;
- strict `> 50` boundary;
- 24-hour temporary retry cooldown;
- permanent third-failure outcome;
- preservation of daily expiry and monthly expired-CR behavior; and
- no accidental staging of unrelated working-tree changes.

- [ ] **Step 4: Check formatting without running prohibited operations**

Run only read-only/static commands permitted at execution time, such as:

```bash
git diff --check -- worldshading/api/sijilat.py worldshading/api/test/test_sijilat_auto_verification.py worldshading/hooks.py worldshading/Documentation/customer_verification_and_secret_pricing.md
git diff --stat -- worldshading/api/sijilat.py worldshading/api/test/test_sijilat_auto_verification.py worldshading/hooks.py worldshading/Documentation/customer_verification_and_secret_pricing.md
```

Do not run `bench test`, restart, migrate, cache-clear, or a scheduler command.

- [ ] **Step 5: Commit the documentation only**

```bash
git add worldshading/Documentation/customer_verification_and_secret_pricing.md
git commit -m "docs: explain historical CR auto verification"
```

---

## Deployment Checkpoint

Implementation completion does not activate changed Python hooks in already running
processes. Stop after code, tests and documentation are prepared. Report the changed
files and static verification evidence, and request separate authorization for any
restart, migration, cache clear, scheduler invocation or production test.
