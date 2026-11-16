# Fixed Expense Automatic Payment Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task after approval. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Automatically prepare GL Payments two days before renewal, prevent duplicate active payments, and carry unpaid balances forward until paid or explicitly closed.

**Architecture:** Use the existing Fixed Expense master and GL Payment documents only. Identify each renewal by Fixed Expense + Scheduled Due Date, and calculate its balance from linked GL Payments. No new DocType, automation checkbox, extra tracking cutoff, or separate instalment screen.

**Tech Stack:** ERPNext/Frappe v12, Python 3.6, MariaDB; worldshading and accounts_addon apps.

**Spec:** Requirements and rules below incorporate the user's simplification of the previous plan. This document supersedes the earlier proposal for a Fixed Expense Renewal DocType. The older [future upgrades backlog](2026-11-09-fixed-expense-future-upgrades.md) is historical context.

**Status:** Implementation completed for review. Four GL fields and metadata are synchronized; the daily job is intentionally not registered because the user will replace the existing test expenses. No bench tests or migrate were run.

## 1. Existing master controls the schedule

- Tracking Start Date determines when tracking begins.
- First Due Date anchors renewal dates; frequency determines subsequent dates.
- Process all Active expenses; respect End Date for new renewals.
- Monthly/Quarterly/Half-yearly/Yearly/Every 2–5 Years mean offsets of 1/3/6/12/24/36/48/60 months from the original First Due Date.
- Clamp the original day in shorter months without drifting: Jan 31 -> Feb month end -> Mar 31. Use Asia/Bahrain business dates.
- Daily job prepares drafts when a due date is within two calendar days, including eligible overdue dates missed during an outage. Document creation date is irrelevant.
- Closing a master stops new renewals. Existing unpaid renewals remain visible and can still be paid; proposed behavior is to continue their balance retries until paid or explicitly closed.
- Do not rewrite existing GL renewal identity or original amount when the master changes. Disallow changing the schedule anchor/frequency while it has an unsettled tracked renewal; settle it first. Already-created future drafts must be reviewed before changing a settled schedule.

## 2. Small GL Payment addition

Keep the existing `custom_fixed_expense` link. Add one compact section, shown only for linked payments:

| Field | Purpose |
|---|---|
| Expense Due Date | Identifies the original renewal being paid; stays the same on carryovers. |
| Expense Amount | Readonly amount payable for this GL: the full amount initially, or remaining balance on a separate carryover GL. |
| Close Remaining Balance | Optional when paying less; settles the unpaid remainder when this payment completes. |
| Adjustment Reason | Required when paying more or less than the remaining amount, including explicit closure. |

Technical field names: `custom_expense_due_date`, `custom_expense_amount`, `custom_close_remaining_balance`, `custom_adjustment_reason`.

Only two hidden supporting values are needed on GL Payment: `custom_expense_snapshot` (immutable JSON of original currency/amount/rate and validated account/tax allocation) and `custom_next_balance_due_date` (date fixed when a partial payment completes). These are not extra user inputs or a new schedule register.

Manual Create GL Payment selects the due occurrence or existing open balance. Direct manual GL entry with a Fixed Expense also requires the scheduled date. The server verifies this date, fills the original amount, and checks the balance. New linked payments must not bypass this by omitting the date. Existing unclassified historical GLs need review rather than guessing from posting dates.

## 3. Amount, closure and carryover rules

- The original scheduled amount is stored in the hidden snapshot, includes tax and is captured on the first saved GL for that renewal, under the expense lock. Later GLs inherit the same server-owned snapshot; editable payment totals never change it.
- Completed non-cancelled payments reduce the balance. Drafts and payments awaiting reconciliation reserve the renewal but do not count as paid.
- Pay the exact remainder: settle the renewal. Pay more: require a reason, settle this renewal and record the excess through the GL amount; do not automatically settle another renewal.
- Pay less without Close Remaining Balance: require a reason and carry the remainder forward.
- Pay less with Close Remaining Balance: require a reason; closure only takes effect on completion. This closes tracking, not an accounting write-off entry.
- Proposed retry timing: on completion of a partial payment, store the first monthly anniversary of the original due date strictly after both the payment posting date and today's business date. Generate its balance draft two days beforehand. Store this date once; do not recalculate it forward every day.
- Carryovers retry monthly even if the normal expense renews yearly. Normal new renewals continue separately. Do not generate another balance draft while an earlier attempt is in progress.
- Foreign renewals use the latest valid stored rate for their first payment estimate. Proposed simple balance policy: retain that original company-currency estimate for subsequent partial payments. New renewals use fresh rates. A bank-rate difference uses Adjustment Reason and, for a smaller final charge, Close Remaining Balance. This is not foreign-currency liability accounting.
- Positive payments only. Closing an entirely unpaid renewal with no payment is outside this version; do not create zero-value GLs.

Example: original amount 100; pay 60 -> remaining 40. Next month normal rent 100 and old balance 40 produce separate drafts. Pay 25 toward the old balance -> remaining 15. Later pay 10 and close -> total paid 95, remainder closed 5. The master stays 100.

## 4. Duplicate protection without another DocType

Group GL Payments by `custom_fixed_expense` + `custom_scheduled_due_date`.

- Only one docstatus-0 payment per group at a time, including Rejected and Pending Reconciliation. Several completed partial payments are allowed.
- Fully paid or explicitly closed groups cannot create another payment. On rejection, accounts must revise the existing attempt through the normal workflow; the scheduler must not silently create a replacement.
- Manual button, direct GL save, automation and submission all use the same server checks.
- Lock the existing Fixed Expense row before inspecting/creating/submitting a payment, and hold it to transaction end. Narrow `SELECT ... FOR UPDATE` is justified for concurrency because no supported equivalent was found in this Frappe v12 installation. No SQL is needed for routine reads/updates.
- Re-read linked GLs after obtaining the lock. On a first payment derive the snapshot from the master; on later attempts use the first saved snapshot, including a cancelled original. Never trust client-supplied readonly amounts or JSON.
- Cancelled payments do not count as paid or close a balance. If cancellation exists after the most recent valid payment, skip automatic replacement and let accounts explicitly create the replacement using the existing button. Do not add a hold field or retry screen.
- Cancel payments in reverse order within a renewal when later non-cancelled payments depend on them. This prevents an old cancellation from silently changing the basis of a later closed balance.
- Protect managed GLs from deletion, including the existing generic draft cleanup job, so the original snapshot/history survives. A rejected attempt must be corrected through the normal workflow. Confirm that return path during implementation; do not bypass a workflow if it lacks one or silently release rejected reservations.
- Prevent changing expense/due date/snapshot on a saved managed payment or altering submitted amounts through update-after-submit.

## 5. Existing draft validation needs one narrow change

GL Payment currently requires a valid bank/cash account and bank references even at draft save; live Reference Date metadata is also mandatory.

- Keep payment-account checks; incomplete master defaults produce a clear logged error and retry next run.
- Permit missing references only for a valid managed Fixed Expense GL in workflow Draft.
- Require the references before leaving Draft and again before submission. Preserve existing requirements for every ordinary GL Payment.
- Adjust the reference-date metadata condition and server validation together. Do not bypass validation, insert fake references or use unsupported `override_doctype_class` APIs.
- Use the existing approval workflow and existing account/tax calculations. Pending Reconciliation is not treated as completed settlement.

## 6. Affected files

Paths are relative to `apps/`.

| File | Work |
|---|---|
| `worldshading/worldshading/worldshading/doctype/fixed_expense/fixed_expense.py` and `.js` | Extend existing builder/button with scheduled date and shared balance checks. No master JSON fields added. |
| New `worldshading/worldshading/api/fixed_expense_payments.py` | Shared date, snapshot, balance, duplicate, validation and daily-job functions. Keep the daily coordinator here rather than adding a separate scheduler file. |
| New `worldshading/worldshading/public/js/fixed_expense_payment.js` | Compact GL fields, date selection and reason/close behavior. |
| `worldshading/worldshading/hooks.py` | Append GL events/script and daily job; preserve existing urgency handlers. |
| `worldshading/worldshading/fixtures/custom_field.json` | Additional GL fields, including hidden server-owned values. |
| `worldshading/worldshading/fixtures/property_setter.json` (create if absent) | Scoped reference-date metadata, registered in fixtures. |
| `accounts_addon/accounts_addon/accounts_addon/doctype/gl_payment/gl_payment.py` | Narrow bank-reference exception for valid managed Drafts. No ERPNext/Frappe core modification. |
| New `worldshading/worldshading/tests/test_fixed_expense_payments.py` | Focused calculation, concurrency and workflow test source. |

## 7. Implementation tasks

### Task 1 — GL identity and balance calculations

Interfaces in the shared service: `get_due_date(first_due_date, frequency, occurrence_index)` and `get_balance(expense_name, scheduled_due_date, exclude_payment=None)` returning scheduled, paid, closed_remainder, excess, remaining, active_payment and closed.

- [ ] Add GL fields/fixtures, including readonly and server-enforced snapshot behavior.
- [ ] Implement anchored schedule dates and server snapshot creation/inheritance using existing currency/tax validation.
- [ ] Implement balances from GLs only. Tests: 100 -> 60 -> 25 -> 10/close; 125 with excess; draft has no paid effect; cancellation; a changed master/rate does not change the original amount.
- [ ] Cover month-end, leap-year and every-2/3/4/5-years dates, tracking start and inclusive end boundaries.

### Task 2 — Manual payments, reasons and concurrency

Interfaces: extend `make_gl_payment(source_name, scheduled_due_date=None)`; service `validate_payment(doc, method=None)`, `on_payment_completed(doc, method=None)`, and `before_payment_cancel(doc, method=None)`.

- [ ] Extend manual selection; prefill company-currency amount and original due date. Preserve normal source-read and GL-create permissions.
- [ ] Require reasons above/below the available balance at currency precision; only permit close on an underpayment. Recalculate server totals from items and verified tax data, preserving existing permitted bank adjustments.
- [ ] Allocate balance-draft amounts proportionally across original account rows with their original tax rates, currency rounding and deterministic final-row correction. Test mixed taxable/zero-tax rows; net + tax must equal the intended payment total.
- [ ] Lock the master and validate both on save and submission; reject simultaneous duplicate drafts, tampered snapshot/identity, and further payments after settlement.
- [ ] Store next balance due date on completion of a partial payment. Test cancelled replacement, reverse-order cancellation, rejected reservation and pending reconciliation.
- [ ] Add compact GL JS without replacing the existing urgency script. Protect managed-document history against deletion/cleanup.

### Task 3 — Draft-reference exception and daily creation

Interfaces: `is_fixed_expense_draft(doc)`, `create_due_payments(today=None)`, and `create_payment_draft(expense_name, scheduled_due_date)` in the shared service.

- [ ] Apply the narrow addon reference check and metadata condition. Test ordinary GL behavior and managed Draft -> approval transitions without fake references.
- [ ] Daily job handles all Active masters, deriving occurrences from existing dates through today + 2 days. Also process stored due balance retries; never repeatedly generate skipped monthly retry history.
- [ ] Missing accounts, invalid tax or stale rates log a clear error and leave work retryable. One failure must not block others; use one transaction per payment, rollback failed inserts, and no commits inside document hooks.
- [ ] Test repeated runs, concurrent manual/automatic creation, overdue catch-up, monthly carryover alongside a new renewal, missing defaults and stale rates. Register the job only at controlled activation.

## 8. Activation, verification and rollback

All Active expenses will participate once the daily job is registered. There is no new enable switch or cutoff date.

Before registering it, produce a read-only listing of what would be generated from the existing Tracking Start Date and First Due Date. Existing paid periods must be linked/classified, or their tracking dates intentionally corrected, before activation. Otherwise the historical due dates would create duplicate drafts for payments the new links cannot identify. Do not silently assume old periods were paid or silently ignore them.

Recheck the list: the 14 November review found eight Active records, all Monthly, seven without a payment account, and no GLs using the new expense link. These are historical findings, not assumed current configuration. Confirm hosting renewal frequency and required payment defaults before activation.

Risk: moderate/high because this adds balance tracking and a narrow accounting-draft exception. No implementation or live configuration changes are part of this planning task. No bench migrate or bench tests; static Python 3.6/JSON/JS checks and diff review are permitted. Workflow/concurrency verification must be agreed on an isolated environment before production scheduling; static checks alone do not prove race safety. Do not run service restarts or schema synchronization implicitly.

Rollback: unregister the daily job first; preserve GL history and snapshot fields. Restore code/metadata only after checking generated drafts remain usable. Never drop business records or undo submitted payments outside the normal cancellation workflow.

No new DocType, extra Fixed Expense fields, separate scheduler module, notification system, report, preview, or external dependency. Leave the user's spreadsheet untouched. Cashflow reporting remains future work.


## Implementation record

- Latest user decision: four visible fields only: Expense Due Date, Expense Amount, Adjustment Reason, Close Remaining Balance. Carried balances generate a separate GL retaining the original Expense Due Date; normal renewals remain independent.
- Existing test masters are intentionally unchanged. Scheduler entry is commented in hooks.py until those test records are retired and real masters/dates are reviewed. Do not activate it against the existing test list.
- Added targeted Custom Fields and reference-date Property Setter, plus the expense/due composite index via the native database API. No migrate command was run.
- Original amount and account allocation are server-owned JSON on GL Payment; no new DocType or master automation fields.
- Source/rate values for a first saved payment are revalidated; subsequent partials reuse the stored company-currency balance. Reasons are required for differences, and closure takes effect only on submission.
- Fifteen database-free unittest checks passed. Real metadata/controller checks used unsaved documents and rollback only. Full concurrent saves and end-to-end workflow transitions have not been executed.
- Review fixes include explicit initial workflow state, current locked reads, indexed grouping, non-negative minor-unit allocation, edited payment-account/cost-center validation, and preservation of unrelated submitted metadata edits.
- Backup of original source and live metadata: /tmp/fixed-expense-automation-yp5r_5kc. Preserve GL history if rolling back; do not drop payment fields once used.

### Variable expense rule

Variable expenses settle each due occurrence after one completed payment at the actual amount entered. Differences from the budget do not require an adjustment reason, and Close Remaining Balance is hidden. No balance GL is generated for that occurrence. The next regular renewal still generates normally; cancellation permits a deliberate replacement. Fixed expense partial-payment rules remain unchanged. Amount type is captured in the payment snapshot.
