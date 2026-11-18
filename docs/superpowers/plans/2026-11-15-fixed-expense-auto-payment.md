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
- Follow normal ERPNext deletion permissions and checks; no custom Fixed Expense deletion block. Remaining GLs retain their snapshots. If all GLs for a due date are deleted, that occurrence can be generated again from the master. This also applies to permitted deletions by existing cleanup jobs.
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
- [ ] Add compact GL JS without replacing the existing urgency script. Keep standard ERPNext deletion behavior; do not add a custom deletion block.

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

### Adjustment dialog

For Fixed expenses, saving an adjusted payment collects the mandatory reason and optional underpayment closure in a popup. Cancel aborts saving. Unchanged adjustments reuse the stored values; changed amounts prompt again with the previous reason prefilled. Stored values are displayed readonly, with Edit Adjustment available to reopen the popup. Workflow actions wait for accepted values to be saved before proceeding. Variable expenses do not prompt. Server-side validations remain authoritative.

### Locked expense account mapping

On GLs linked to Fixed Expense, expense account and purchase VAT template/type are readonly and must match the server-owned original schedule snapshot. Row additions/removals or substituted mappings are rejected on save; reordering and amount adjustments remain allowed. Payment method, bank/cash account and references remain editable under existing validation. Selecting an expense and date on a new manual GL fills the expected rows automatically. Existing drafts with altered mappings should be recreated; ordinary GLs remain editable.

### Telephone Bill and ChatGPT identity

Telephone Bill requires Mobile Number, accepting a mobile number or billing account number without a length restriction or automatic country-code changes. ChatGPT requires one normalized Account Email. A hidden nullable unique key enforces company + category + identifier for Active records; Closed records release the key. Existing categories/records are not automatically reclassified. Required reference fields expand their section. No bench tests or migrate were used.

### AI Subscription category

AI Subscription replaces the standalone ChatGPT category. AI Service is mandatory and limited to ChatGPT, Claude and Gemini; Account Email is mandatory and normalized. Active uniqueness is company + AI service + email, allowing the same email on different services. Existing ChatGPT-category records are converted to AI Subscription / ChatGPT without changing payment links. No Other or Service Name field. Telephone uniqueness is unchanged.

### Per-expense currency exchange tolerance

Fixed Expense now has Currency Exchange Tolerance in company currency, visible only for foreign-currency Fixed amounts. Default zero; accounts can set e.g. BHD 1.000. The allowance is captured in the original payment snapshot. Positive payments within the inclusive allowance need no reason popup and settle on completion; a smaller payment closes the exchange remainder, and a note is recorded automatically. Differences above the allowance retain reason/close/carryover rules. Local-currency and Variable payments are unchanged. Existing saved snapshots without tolerance retain zero allowance; edits to the master apply to new renewal payments.


## Fixed Expense approval workflow — 16 November 2026

Approved design: keep the master non-submittable. Draft → Pending Expense - Chkr → Pending Expense - App → Approved, using existing Maker/Checker/Approver - ACC (Workflow) roles. Return to Draft for corrections; Approved records require an Approver to return them for editing. Status is workflow-controlled: Draft/pending = Inactive, Approved = Active, Closed = Closed. Follow existing role-based approval permissions (including self-approval settings); no additional personal approval-tracking fields.

Implementation (review after completion as requested):
- [x] Add standard hidden workflow_state and existing Accounts workflow roles to Fixed Expense permissions. Install the scoped Workflow and any missing states/actions using an idempotent setup helper in worldshading/api/fixed_expense_workflow.py; register for future app setup. Initialize existing records to Draft, never auto-approve.
- [x] Enforce server-side Draft editing by Maker; lock business fields outside Draft, including changes bundled with a return/approval action. Native Frappe validates role transitions. Update fixed_expense.js to lock fields and show Create GL Payment only when Approved + Active.
- [x] Guard new GLs, manual balance payments, payment-date lookup and automatic candidates. Existing saved GLs continue under their own workflow even when the master is returned/closed. Preserve payment history and duplicate checks.
- [x] Run database-free tests for roles, edit/transition tampering, approval gating, saved GL continuation and carried-balance candidates. Apply targeted DocType/workflow setup on this site and inspect it read-only; do not run migrate or bench tests or create payments.

Files: Fixed Expense JSON/JS/Python, fixed_expense_payments.py, hooks.py, new fixed_expense_workflow.py, focused tests, this plan. Risk: existing masters cannot generate new payments until approved. Rollback: restore source/configuration backups; remove the new workflow and restore prior master workflow-state values and DocType permissions. No existing GL changes.

Verification: 41 database-free Python checks, workflow-form Node checks and existing adjustment-dialog checks passed. Independent review identified browser/database Date representation differences; normalized dates and added a regression test. Live metadata verified non-submittable workflow, six transitions, all eight existing masters in Draft, and idempotent setup. Read-only checks across the eight masters verified initial actions and unchanged serialized detail comparisons. No GL creation, approvals, bench tests or migrate performed.

Workflow labels: Draft → Request Verification → Pending Expense - Chkr → Expense Verified → Pending Expense - App → Approve → Approved. Request Correction returns either pending state to Draft; Request Editing returns Approved to Draft. Roles and permissions are unchanged.

Workflow-controlled Status: the native Workflow Update Field/Value sets status on each transition, with a server-side consistency check. Status is read-only and new masters default to Inactive. Approvers can Close Expense from Approved; Closed is terminal. Returning to Draft sets Inactive. Existing GLs continue, but no new GL may be generated from an Inactive/Closed master. Close Expense does not require or invent an End Date: state/status stops further payments; any entered End Date retains its existing date validation. Unique expense identifiers remain reserved only for Active masters and are checked again on approval.

Status update verification: 43 database-free Python checks passed. Live Workflow state update_field/update_value mappings and read-only Status metadata verified. All eight existing Draft masters are now Inactive; no records were approved or closed and no GLs were changed.


## Bank Loan repayments — review and proposed implementation (18 November 2026)

Planning only. No loan functionality or accounting records changed during this review.

### Findings from the current system

- Fixed Expense account selection and server validation currently accept only Expense ledgers. Each row requires a Purchase Tax Template. Payment creation, snapshots, duplicate checks, balances and scheduled generation currently query GL Payment only.
- Journal Entry has no Fixed Expense linkage yet. Keep its existing validations, submission logic, urgency/commission hooks, server scripts and workflow intact.
- `JV26-01617`: debit AUB loan- Six wheeler 256.334 and Interest for Loan 53.666; credit bank 310.000 BHD.
- `JV26-01759`: debit BDB Loan 3,364.071 and Interest for Loan 370.929; credit bank 3,735.000 BHD. The September entry `JV26-01496` uses a different principal/interest split for the same total, so a fixed instalment does not imply a fixed split.
- `JV26-01017` debits only the AUB car loan ledger and credits bank. Interest is also recorded in a separate entry in the samples: do not automatically add interest again to every repayment.
- These examples use `transaction_type = Other Expenses`. Its existing route is Draft → Pending Other Expenses Transfer → Completed, with Checker approval. Journal Entry's Bank Transfer route separately supports Checker → Approver → Reconciliation. Do not silently switch routes.

### Recommended scope

Reuse Fixed Expense as the repayment schedule; no new loan DocType or amortization engine. It does not become an authoritative outstanding-principal register. Actual loan balances remain in the ledger.

| Area | Proposed behavior |
| --- | --- |
| Category | Add Bank Loan. Preserve all other categories. |
| Accounts | Bank Loan allows same-company, enabled, non-group Liability and Expense ledgers in company currency. Require at least one loan liability row. Other categories remain Expense-only. Apply the rules in the form and on the server. |
| Amounts | Store the expected instalment breakdown. Principal debits liability; interest/charges debit expense; bank is the balancing credit. The cash-flow amount is the complete bank outflow. |
| Taxes | Retain the familiar Tax Template column. Principal rows require an explicit zero-tax template selected by accounts. Do not infer VAT treatment from account names. If expense rows include tax, map the calculated tax to its ledger in the JE. |
| Dates and approval | Reuse tracking start, first due date, frequency, optional end date and Approved + Active gating. Use the final instalment due date as End Date where known. |
| Manual action | Show Create Journal Entry for Bank Loan; other categories retain Create GL Payment. Block loan creation through the GL endpoint as well as hiding its button. |
| Journal draft | Prepare an unsaved balanced JE using the selected bank account and expense cost center. Default voucher_type to Journal Entry and transaction_type to Other Expenses to match current split-loan entries. Check JE create permission and start in the native Draft workflow state. Do not submit automatically or fill invented bank references. |
| Review | Accounts reviews the principal/interest split against the bank statement before submission. Permit amount redistribution between the approved ledgers, even when the total instalment is unchanged. Keep source liability/expense/tax ledgers protected; allow a valid bank-account correction. |
| Payment difference | Reuse the existing reason, Close Remaining Balance and applicable currency tolerance behavior based on total bank payment. A change of split with the same total does not itself create a balance or require the total-adjustment reason. |

### Small implementation steps

1. **Master and manual JE:** update Fixed Expense JSON/JS/Python for Bank Loan and category-specific accounts. Add a small `worldshading/api/fixed_expense_journal_entries.py` module to prepare and validate loan JEs. Reuse existing schedule/currency helpers rather than introducing a generic accounting framework. Require a valid payment account when preparing the JE; never create an unbalanced placeholder.
2. **JE linkage and tracking:** add scoped Journal Entry custom fields through fixtures: Fixed Expense, Expense Due Date, Expense Amount, Adjustment Reason and Close Remaining Balance; add the same hidden snapshot/retry fields needed by the current balance logic. Add a small scoped client handler for the adjustment dialog and protected ledgers, without changing unrelated JE behavior. Merge hooks with existing Journal Entry hooks rather than replacing them.
3. **Duplicate and remaining balance protection:** use Fixed Expense + original Expense Due Date as the key, including manually linked JEs. Reuse the master lock so concurrent manual/automatic requests cannot create two active attempts. One draft/in-progress attempt blocks another; submitted partial payments leave the balance available; paid/closed schedules block further creation. Cancelled entries do not count as paid. Keep normal deletion permissions and preserve later-payment cancellation protections. Count the designated bank credit once as the amount paid, never debit plus credit. Validate positive balanced repayment rows and reject unrelated/reversed postings in linked repayment JEs.
4. **Share schedule history safely:** extend history lookup only as needed to include GL Payments and linked JEs, with document type + name identifiers, and retain original amount/account snapshots. Prevent switching between Bank Loan and ordinary expense categories after linked payment history exists. Do not count a GL Payment's own generated journal as a second repayment. Preserve existing saved payment workflows when a master is returned/closed.
5. **Automatic dispatch:** the existing due-two-days-before process chooses JE for Bank Loan and GL Payment otherwise, including remaining-balance retries for the original due date. Keep automation disabled until explicitly activated and reviewed. Generating a JE must never mark the loan paid; only submitted, non-cancelled payments count.

### Verification and rollout

- Database-free checks: loan ledger eligibility versus ordinary expenses; BHD 310 sample debit/credit mapping; principal-only repayment; zero-tax principal and taxed-fee handling; changing split with an unchanged total; rejection of unbalanced or unrelated lines; date/approval gates; direct-link and concurrent duplicate protection; partial/closed/cancelled payment accounting; ordinary GL regression checks.
- Review the Other Expenses versus Bank Transfer workflow choice before implementation if three-person JE approval is required. Default plan preserves the actual existing loan process; changing workflow routing is a separate explicit decision.
- Apply targeted metadata/custom-field sync only when implementation is approved. No bench tests or migrate. First review an unsaved draft against a real repayment statement; no automatic submission or backfilling old JEs. Existing loan postings need linking or an appropriate future Tracking Start Date to avoid generating already-paid instalments.
- Files expected: Fixed Expense JSON/JS/Python; fixed_expense_payments.py; new fixed_expense_journal_entries.py and scoped JE client handler; hooks.py; custom_field.json; focused tests; this plan. All changes remain in worldshading, without ERPNext core edits.
- Implementation risk: moderate (financial documents and shared payment tracking). Back up affected metadata/configuration before rollout. Rollback source and scoped metadata from backup; preserve any genuine JEs created during review. No automatic deletion of accounting history.
