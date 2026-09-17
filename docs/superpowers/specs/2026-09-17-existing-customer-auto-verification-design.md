# Existing Customer Automatic CR Verification Design

Date: 17 September 2026  
Application: `worldshading`  
Platform: ERPNext 12 / Frappe 12

## Objective

Automatically verify historical Bahrain company Customers whose Business Verification
Status is empty, without creating a large burst of traffic to the public Sijilat service.
The migration must reuse the existing CR validation, company-name matching and Sijilat
verification rules.

This migration is independent of Secret Price List authorization. Automatic CR
verification must not grant, remove or change a Customer's Price List.

## Scope

The automatic migration considers a Customer only when all of these conditions are true:

- the Customer is enabled;
- Customer Type is `Company`;
- Territory is `Bahrain`;
- CR No is present;
- Business Verification Status is empty; and
- fewer than three temporary-error attempts have been recorded.

Customers already marked `Verified`, `Not Verified`, `Pending`, `Rejected` or `Expired`
are outside this migration. Existing monthly rechecks for expired, previously verified
Customers remain unchanged.

## Scheduling and rate limit

A cron dispatcher runs once every five minutes and selects at most one eligible Customer.
This limits the migration to a theoretical maximum of 288 Customers per day and avoids a
burst of simultaneous token and CR-detail requests.

The dispatcher enqueues an individual background job instead of contacting Sijilat
inside the scheduler process. The worker rechecks eligibility before making an API call,
protecting against duplicate or stale queued jobs.

Customers waiting after a temporary failure are not eligible again for at least 24
hours. This prevents one failing record from immediately consuming all three attempts.

## Verification flow

For one eligible Customer, the worker performs the following steps:

1. Recheck the migration eligibility conditions.
2. Validate the saved CR format locally.
3. Validate that the normalized CR is not assigned to a different Customer.
4. Fetch the Sijilat record using the existing integration.
5. Confirm that the returned CR equals the Customer's normalized CR.
6. Confirm that the Sijilat record is active and its expiry date is not in the past.
7. Compare the saved Customer Name against the official English and Arabic commercial
   names using the existing normalization and similarity function.

The existing approval rule is retained: the highest calculated name score must be
strictly greater than 50 percent.

## Outcomes

### Successful verification

When the CR is verified and name similarity is above 50 percent, the worker:

- replaces Customer Name with the official Sijilat English commercial name;
- stores the formatted verified business details;
- stores the CR expiry date;
- sets Business Verification Status to `Verified`;
- stores the Sijilat check time;
- resets attempts to zero; and
- saves through the Customer document API with the existing Sijilat-verification flag.

Saving through the document API preserves normal Customer validation and the ERPNext
version/activity history of the name change.

### Permanent non-verification

The worker sets Business Verification Status to `Not Verified` and stops automatic
processing when any of the following is true:

- CR format is invalid;
- the normalized CR is already assigned to another Customer;
- returned CR does not match;
- Sijilat cannot provide an official commercial name;
- the record is inactive, cancelled, deleted or otherwise rejected;
- the CR is expired; or
- name similarity is 50 percent or lower.

For these outcomes, the worker does not rename the Customer and does not save the hidden
Sijilat identity or business details.

### Temporary integration failure

Network failures, request timeouts, token failures, server errors, response parsing
errors and decryption errors are temporary failures.

For attempts one and two, the worker:

- leaves Business Verification Status empty;
- increments the attempt counter;
- stores the attempt/check time; and
- preserves all Customer identity and business-detail fields.

The Customer becomes eligible again after the 24-hour cooldown. On the third temporary
failure, the worker sets Business Verification Status to `Not Verified`, stores the final
attempt/check time and stops automatic processing.

No separate manual-review queue or migration audit DocType is introduced. Staff can use
the existing **Verify CR** button later for any Customer marked `Not Verified`.

## Concurrency and duplicate protection

Both dispatcher and worker apply eligibility checks. Before calling Sijilat, the worker
records the attempt/check time so another scheduler execution cannot immediately select
the same Customer. The worker must not hold a database transaction open during the
external HTTP request.

Only one Customer is dispatched per cron execution. No sleep loop or long-running bulk
job is used.

## Components and files

### `worldshading/api/sijilat.py`

Add focused functions for:

- selecting and enqueueing one eligible historical Customer;
- processing one Customer in a background job;
- classifying permanent validation outcomes versus temporary integration failures; and
- recording attempts without changing established expired-CR recheck behaviour.

Existing parsing, formatting, status calculation, name similarity and Customer reset
logic should be reused rather than duplicated.

### `worldshading/hooks.py`

Register the five-minute cron dispatcher. Existing daily expiry and monthly expired-CR
hooks remain unchanged.

### Documentation

Extend `worldshading/Documentation/customer_verification_and_secret_pricing.md` with the
historical migration behaviour, eligibility criteria, pacing, retry policy and operating
notes.

## Error handling

Expected permanent validation failures are handled without an exception loop and result
in `Not Verified`. Temporary integration failures use the three-attempt retry policy.
Unexpected exceptions are logged with the Customer identifier and treated as temporary
failures, without exposing a Sijilat commercial name in the log message.

One Customer failure must never prevent later scheduler executions from processing other
Customers.

## Testing strategy

Automated tests should cover:

- dispatcher selection and the one-Customer limit;
- exclusion of non-company, non-Bahrain, disabled, missing-CR and non-empty-status
  Customers;
- successful verification, official rename and field population;
- the strict greater-than-50-percent boundary;
- invalid and duplicate CR permanent outcomes;
- expired and rejected Sijilat records;
- temporary attempts one, two and three;
- 24-hour retry cooldown;
- worker rechecking eligibility before the API call;
- no change to Secret Price List fields; and
- no regression in the existing monthly expired-CR recheck functions.

Tests must mock Sijilat calls. They must not contact the public service.

No restart, migration, cache-clear, scheduler execution or bench test is part of the
production editing step. Any later deployment action requires separate explicit
authorization.

## Risk and rollback

Risk is medium because successful jobs rename and verify production Customer records.
Rate limiting, duplicate checks, strict eligibility and the existing similarity rule
reduce the risk.

Code rollback consists of removing the cron entry and the new dispatcher/worker
functions. Removing the cron entry stops further automatic processing. Customer changes
already made by successful jobs are not automatically reversed; their previous names can
be recovered from ERPNext version/activity history and corrected individually.

