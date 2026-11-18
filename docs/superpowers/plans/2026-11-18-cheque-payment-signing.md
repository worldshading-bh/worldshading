# Cheque Payment Signing Implementation Plan

**Goal:** Reserve own-company cheque leaves from outgoing PE/GL payments and confirm physical signing at the existing approver action, without a second workflow.

**Architecture:** Extend the current register with a shared payment service and one small PE/GL form script. Use the existing connection-scoped account mutex and current leaf reads. Synchronize the leaf only inside a successful payment transaction. A single hidden confirmation value per payment records a server-owned, user-and-details-bound acknowledgement before the existing workflow action.

**Tech Stack:** Frappe/ERPNext v12, Python 3.6, MariaDB, existing worldshading app.

**Spec:** User approved the six-point signing approach in chat on 2026-11-18 and confirmed that PE Approve / GL Paid occurs after physical signing. No separate handover/collector process or new DocType. Journal Entry integration is separate; incoming/customer cheque workflows stay untouched.

## Constraints and scope

- No bench test, migrate, restart, service restart, or broad cache-clear commands. No ERPNext/accounts_addon core changes.
- Preserve existing workflows, roles, ledger posting, scheduled/fixed-expense drafts, customer cheques and historical unlinked submitted payments.
- PE `Pending Cheque Payment - App` + Approve -> `Pending Reconciliation`; GL same source state + Paid -> same target. Outgoing security PE `Pending Security Cheque - App` + Approve -> `Handover Security Cheque` also confirms signing, preserving docstatus 0.
- A selected leaf reserves on save; no leaf is required in Draft/Scheduled/Pending Payment - Maker. Before leaving preparation for cheque processing a leaf is required. No automatic signature, issuance or clearance from mere insertion, submission, attachment or Completed status.
- Existing explicit security-PE handover can mark Issued, provided the bound leaf is signed. Ordinary PE/GL issuance and bank-clearance mapping remain separate because the user has not defined their physical handover event.
- Signed stays a checkbox on a Reserved/Issued leaf. Add only `signature_confirmed_by` and `signature_confirmed_on` to the leaf. The confirmed user is not represented as the physical signatory.
- A linked signed leaf freezes account, company, currency, payee, amount, date, mode and selection. Unsigned selection changes release the prior reservation atomically. Cancellation makes the leaf Cancelled and preserves the link/audit; it never automatically releases a signed leaf. Require removal of an unsigned leaf before deleting its draft payment.
- Unlinked historical submitted payments are grandfathered; no retroactive assignment/signature. Existing manual leaf signatures require preflight review. Signed/audit fields become server-owned.
- GL with no party needs one visible Cheque Payee field; otherwise derive payee from party. Its total must be in the bank currency; foreign-account GLs require explicit currency support rather than guessing.

## Files

- New `worldshading/api/cheque_payments.py`: PE/GL normalization, ownership checks, reservation, acknowledgement, approval access, signed-detail protection, synchronization, cancellation/deletion guards and maintenance activation.
- Modify `worldshading/api/cheque_register.py`: permit narrowly scoped internal tracking updates; protect manual Signed/audit changes.
- New `worldshading/public/js/cheque_payment.js`: native available-leaf filtering, cheque-number fetch and signing dialog using validated=false -> Promise -> Dialog -> save values -> frm.save -> resolve.
- Modify `worldshading/hooks.py`: append handlers/scripts without replacing existing payment logic.
- Modify `worldshading/api/purchase_order.py`: retain the selected customs cheque on the GL Payment.
- Modify `worldshading/fixtures/doctype.json`, `custom_field.json`: two leaf audit fields, GL leaf/payee fields, and hidden payment acknowledgement fields. Existing PE leaf field remains.
- New `worldshading/tests/test_cheque_payments.py` and `test_cheque_payment_form.js`: database-free checks; no bench runner.

## Tasks

- [x] 1. Tests first: outgoing-only context, exact signing transitions, owner conflicts (including a JE-linked leaf), wrong bank/company/currency, signed edit locks, confirmation forgery/staleness, historical/customer/scheduled exclusions.
- [x] 2. Implement payment hooks and internal leaf updates. Keep permission checks at source; approvers need not gain manual leaf-write permission. Confirmation requires the native workflow transition role and self-approval policy.
- [x] 3. Test and implement the popup: no request on cancel, checkbox required, server details escaped, successful frm.save before resolve, errors reject; use separate per-DocType handlers so existing forms are preserved.
- [x] 4. Add metadata, append hooks and repair customs link. Run database-free suites, syntax checks and independent review.
- [ ] 5. Snapshot targeted live metadata/scripts/workflows/register data, check source/worker readiness, merge and apply only reviewed metadata. Do not advance real payment workflows or create financial test records. Record deployment and limitations.

## Review focus

- The same Approve/Paid labels also appear on non-cheque paths: gate exact outgoing mode and state pair.
- Client hidden fields and document flags are untrusted. Confirmation must be minted by a permitted approver for the current details/user and consumed after transition.
- Never leave a signed leaf behind when a later payment validation fails: all synchronization must share the transaction, with no commits in hooks.
- Leaf reassignment, removal, bank change and two source document types competing for one leaf must use the same concurrency guard.
- Respect incoming customer/security JEs and outgoing security PEs that intentionally remain draft after issue.

## Rollback

Save private before/after snapshots and deployment receipts. Revert only added payment hooks/form code and targeted metadata; preserve all payment/register records and audit data. New columns may remain rather than dropping data. Reconcile active reservations before disabling controls. Keep the existing register controls operational. No migration or restart is part of deployment.

## Execution record

- Base: main `86cadd3`. Worktree: `/tmp/worldshading-cheque-signing-20261118`.
- Ruling: use one server-owned hidden acknowledgement field rather than adding another approval state or DocType. It is tied to the actor and normalized cheque details; changing either invalidates it.
- Ruling: ordinary Issued/Cleared mapping is deferred; existing security handover is explicit and can be synchronized without changing its workflow.
- Independent review found three important issues: native transition lookup reloads its Document argument, v12 frm.save resolves some failures, and GL party_name is not server-authoritative. Fixed with a detached transition lookup, explicit save-response/error callbacks plus acknowledgement/detail checks, and linked-party title lookup. Each issue has a failing/passing regression check. Added the missing GL update-after-submit synchronization hook.
- Additional compatibility checks cover a missing initial workflow state (native v12 fills Draft later), closed/expired books retaining their already-signed cheques, source reference/party normalization, and client document flags not authorizing tracking updates.
- Verification before deployment: 93 database-free Python checks; cheque signing, cheque register and both Fixed Expense Node form checks; JavaScript syntax and diff checks pass. No bench runner or real payment workflow was executed.
- Private preflight snapshot: `sites/erp.worldshading.com/private/cheque-register-rollbacks/20261118T064101Z-payment-signing/before.json`. One book, 50 Available leaves, no manual signatures, no linked leaves/PEs, and no active outgoing cheque drafts were found. Existing active PE/GL/JE workflow definitions are included for unchanged-state verification.
- Further database-free checks bring the total to 93. A two-connection live MariaDB probe using an artificial lock key (no Account record or business writes) confirmed immediate refusal of a competing mutex request and automatic release on connection close. This is not an end-to-end payment/workflow test.
- Activation decision pending: existing workflows have no ordinary cancellation/reissue path while the newly signed payment is still docstatus 0. A signed-detail lock would require a controlled exception path for corrections. User was asked whether to include a Finance-only void/reissue path before activation or keep this code prepared until that path is agreed. No production workflow, metadata or payment has been changed for this phase.
