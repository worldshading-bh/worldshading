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
- User-approved extension: `workflow.json`, `workflow_state.json`, `workflow_action_master.json`, and the existing PE security-validation entry in `server_script.json` for a Finance-only draft void/reissue path.
- New `worldshading/tests/test_cheque_payments.py` and `test_cheque_payment_form.js`: database-free checks; no bench runner.

## Tasks

- [x] 1. Tests first: outgoing-only context, exact signing transitions, owner conflicts (including a JE-linked leaf), wrong bank/company/currency, signed edit locks, confirmation forgery/staleness, historical/customer/scheduled exclusions.
- [x] 2. Implement payment hooks and internal leaf updates. Keep permission checks at source; approvers need not gain manual leaf-write permission. Confirmation requires the native workflow transition role and self-approval policy.
- [x] 3. Test and implement the popup: no request on cancel, checkbox required, server details escaped, successful frm.save before resolve, errors reject; use separate per-DocType handlers so existing forms are preserved.
- [x] 4. Add metadata, append hooks and repair customs link. Run database-free suites, syntax checks and independent review.
- [x] 5. Snapshot targeted live metadata/scripts/workflows/register data, check source/worker readiness, merge and apply only reviewed metadata. Do not advance real payment workflows or create financial test records. Record deployment and limitations.

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
- Initial activation was deferred because signed payments remain draft and needed a correction path. The user subsequently approved Finance-only void/reissue; the extension and activation below supersede that hold.

## Approved Finance-only void/reissue extension

- User explicitly chose to include the Finance-only path before activation. `Void Cheque` is a native workflow action, gated to outgoing Cheque payments in draft with a signed, Reserved/Issued linked leaf. Native document permissions, Finance role, current transition and the existing self-action policy are checked again on the server.
- Ordinary PE: Pending Reconciliation -> Pending Payment - Maker. GL: Pending Reconciliation -> Draft. Security PE: Handover Security Cheque / Security Cheque Issued -> new Prepare Security Cheque (Maker-editable, docstatus 0). Submit Security Cheque then returns to the existing security checker stage; all ordinary checking/signature approvals remain.
- The maker can submit their own replacement to the checker, matching existing maker submission policy. Finance self-void follows the existing Finance cancellation policy. No new signature self-approval policy is introduced.
- Void uses the same hidden acknowledgement, bound to `operation=void`, actor and cheque details, with a reason and physical cancellation/stop confirmation. It preserves the old leaf's signature, payee, amount, date, owner and audit; sets that leaf Cancelled; clears only the payment's current leaf; and records a comment/reason. Payment remains draft, so no ledger entries are posted or reversed. The old reference number is retained until replacement selection supplies its new number, satisfying native bank-reference validation during the return transition.
- Security PE retains is_security_cheque=1 throughout replacement preparation. Its safe-exec validation includes the new unique security state. Handover requires an attachment created after the replacement's signing confirmation, so the previous cheque's attachment cannot authorize the new handover.
- Independent review of this extension found that maker submission initially disallowed the owner. Corrected to match the existing Security Cheque action, with a failing/passing test using native has_approval_access. Finance save on workflow-readonly states is supported by native v12 when the actor has underlying write access; preflight confirms all six Finance users have PE and GL write access.
- Additional form regression prevents duplicate popup registration when both PE and GL forms load the shared script. RestrictedPython compilation/execution checks exercise the security preparation and fresh-attachment rules. Current total: 103 database-free Python tests, plus signing/register/Fixed Expense Node form checks.

## Production activation: 2026-11-18

- Fast-forwarded production main from `86cadd3` through `fb25d1f` and `0028480`. This work has not been pushed.
- Current private rollback snapshot: `sites/erp.worldshading.com/private/cheque-register-rollbacks/20261118T071931Z-signing-void/before.json`; successful verification/activation receipt beside it in `receipt.json` (restricted permissions).
- Applied only the five scoped payment field definitions, leaf Signed protection/two audit fields, new workflow state/actions, the two reviewed workflow extensions and the existing security-cheque validation update. No migrate, bench tests, service restart or payment workflow actions were run. No financial test records were created.
- The initial post-apply verifier compared complete leaf dictionaries and stopped because newly added empty audit fields changed their shape. Independent verification compared every original field/value, names and counts, and separately verified the new audit values are empty. All original register data is preserved: one book and 50 Available, unsigned leaves.
- Verified all original PE/GL transitions and state document statuses remain; Journal Entry workflow is unchanged. Verified scoped live fields and security script match the reviewed fixtures.
- Administrator-only maintenance requests loaded the new hooks in all six existing web workers without a restart. Live metadata requests confirmed both payment forms include the shared script and hidden confirmation fields; leaf metadata shows protected signature/audit fields. Invalidated only affected users' cached boot information for refreshed workflow metadata.
- Fresh verification on production source: 103 database-free Python checks; signing/register and both Fixed Expense Node checks; JavaScript syntax and diff checks pass. These do not exercise actual financial transactions or production workflow actions.
- Next manual validation: refresh the ERP form; use a supervised outgoing draft to check reservation and cheque-number fill, cancellation of the signing popup, then confirm signing only after the physical cheque is signed. Finance may use Void Cheque only after the old physical cheque is unusable/stopped; verify its Cancelled leaf retains audit and replacement selection returns through existing approvals. Security replacements require a new attachment after signing.
- Remaining scope: Journal Entry integration and ordinary cheque handover/bank-clearance synchronization. Signing alone does not mark an ordinary cheque Issued or Cleared.
