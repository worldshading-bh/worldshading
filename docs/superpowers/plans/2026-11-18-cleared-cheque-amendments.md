# Cleared Cheque Amendments Implementation Plan

**Goal:** Complete outgoing PE/GL cheque tracking on submission and preserve a cleared physical cheque through accounting cancellation/amendment.

**Architecture:** Extend the existing transaction-bound payment synchronizer. Use native `amended_from`, existing leaf ownership and account mutex; introduce no fields, states, general reuse action or new ledger behaviour. Native v12 Amend already copies the leaf even with no_copy, whereas Duplicate does not. Preserve signature, physical details and first clearance date. Keep existing payment approvals; the signing-stage check recognizes a verified cleared amendment and skips only the physical signing acknowledgement.

**Spec:** User approved Cancel -> Amend with intact linking and requested implementation, simplicity review and production activation, 2026-11-18. Accounting corrections can change posting date, expense rows, cost centres and remarks. Bank/company/currency, payee identity, cheque amount and printed date remain unchanged. Correcting the physical cheque details is outside this scope.

**Constraints:** ERPNext/Frappe v12, Python 3.6. No bench test/migrate/restart, core edits or real financial workflow actions. Preserve the user's unrelated fixed-expense plan edits. Keep security-cheque draft issuance unchanged. Do not backfill existing leaves silently.

**Impacted files:** `api/cheque_payments.py`, `api/cheque_register.py` (one scoped worker-reload line), `public/js/cheque_payment.js`, their existing tests, this plan and the private Administrator Note. No metadata changes.

**Risk / rollback:** Medium: ownership transfers during amendment save. Revert code only after reconciling newly transferred reservations; preserve existing payment links, cancelled original documents and leaf audit. Reload these cheque modules in existing workers using the scoped administrator helper; no service restart.

## Review focus

- Two competing amendments, duplicate documents, cross-DocType references and forged/changed amendment ancestry cannot claim a cleared leaf.
- Invalid/failed saves never transfer a leaf; saved amendment history cannot detach or change its physical cheque.
- First submission clears a signed leaf with clearance date (payment clearance_date if set, otherwise confirmation day). Later saves/cancellation/amendment preserve it.
- Cleared corrections retain original signatures and bypass only repeated physical signing; native action permissions and state progression still apply.
- Draft void, security issuance, historical unlinked/incoming payments, fixed expenses and source deletion protection keep their current behaviour.

## Task 1: clearance and amendment ownership

- [x] Add database-free regression checks for PE/GL submission, cancellation, amendment transfer/repeated chain, accounting edits, forbidden physical edits, no permission, duplicate/wrong parent, contention, empty selection restoration and failure-before-sync.
- [x] Run new tests against current code and confirm expected missing-behaviour failures.
- [x] Implement the minimal shared checks/ownership transfer, original/current payment audit comment, unchanged cleared date and exact signed-detail restrictions. Keep the current source's original leaf selection in cancelled history.
- [x] Run Python database-free suite.

## Task 2: workflow form and review

- [x] Add a form regression: server-verified cleared correction continues the existing signing action without another popup/save. Normal signing and void still require their confirmations.
- [x] Run failing test, implement recognition, then run all existing Node form checks.
- [x] Independently review correctness, v12 compatibility and unnecessary complexity; fix important findings with regression tests.

## Task 3: activation and documentation

- [ ] Verify clean scoped diff; commit and merge only these changes, preserving unrelated main edits.
- [ ] Snapshot affected live register/payment state and prior guide, reload the cheque module in all web workers, verify live scripts/read-only APIs and unchanged business values. No real workflow actions.
- [ ] Update the private Administrator guide and record receipts, limitations and commits. No push unless requested.

## Execution evidence

- Baseline: 103 database-free Python tests pass. New regressions initially failed because submission did not clear and another payment owned the leaf; the form regression failed because a cleared amendment opened a signing popup.
- Implemented native amendment retention and same-transaction ownership transfer; no general reuse path, new field or new workflow. All 115 Python checks and all four Node form suites pass.
- Existing administrator worker activation now reloads the payment module as well as register/hooks, so subsequent code can be loaded without restarting services. This adds no business document writes or broader maintenance permissions.

- Independent review found one important permissions issue: native v12 validate_workflow does not itself enforce self-approval policy on direct saves. Corrected the cleared-amendment signing-stage branch to always call the native action/self-approval check, while skipping only the physical acknowledgement. Regression failed before the correction and passed afterward. Reviewer found no other Critical/Important findings or necessary complexity changes.
- Final pre-activation verification: 116 database-free Python tests, four Node form suites, JavaScript syntax and git diff checks pass. This includes repeat amendments, two contenders, wrong/cross-source ownership, original amendment permission, physical detail locks, cleared-date preservation and transactional transfer timing. No real financial workflow actions were executed.
