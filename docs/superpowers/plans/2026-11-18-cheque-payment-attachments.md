# Cheque Payment Attachments Implementation Plan

**Goal:** Require cheque evidence before outgoing PE/GL reconciliation completes and display existing payment attachments on Cheque Leaf.

**Architecture:** Add a server-side submission gate to the current payment service, a native GL upload dialog, and a permission-checked read-only leaf section. Keep files on their payment: no copied File records, new fields, DocTypes or workflows. PE keeps its existing Attach dialog. Leaf lists all files on its linked PE/GL/JE, clearly labelled Payment Attachments; a replacement payment can therefore contain files for both old and replacement cheques.

**Spec:** User approved implementation after the attachment proposal. First completion requires a payment attachment created after the leaf signing confirmation, matching the existing security cheque standard. A cleared amendment requires an inherited/current payment attachment without a new signing-time boundary. A later update/cancellation of a submitted historical payment is not blocked. Native amendment file copying stays unchanged.

**Files:** `api/cheque_payments.py`, `public/js/cheque_payment.js`, `public/js/cheque_leaf.js`, leaf Custom Script fixture, database-free tests, this plan, private Administrator guide.

**Constraints:** Frappe/ERPNext v12, Python 3.6; preserve native workflow permissions and Promise/dialog/save order. No bench tests/migrate/restart, real payment actions or financial test records. Preserve unrelated main edits.

**Risk / rollback:** Medium: attachment gate can block submission. Snapshot live script/guide and register data. Revert only new gate/display/form code and scoped leaf script, reload modules using existing administrator helper. Keep uploaded files and business records.

## Task 1: server behaviour

- [x] Add failing database-free tests for missing/stale/current-file submission, inherited amendment attachments, incoming/historical/cancellation exclusions and API permission/empty/JE/all-file behaviour.
- [x] Implement attachment lookup/submission guard and permission-checked leaf/reconciliation APIs with native File records and safe URLs.
- [x] Run Python suite; failed payment validation must not mutate leaf.

## Task 2: forms and fixtures

- [x] Add failing form checks for GL Reconciled upload/cancel/error/dirty/stale-file cases and leaf attachment rendering, escaping, empty/restricted data, repeated refresh and stale replies.
- [x] Implement GL-only reconciliation dialog with FileUploader; require server evidence, then successful frm.save before continuing. Reuse a qualifying existing attachment without prompting. Preserve PE existing popup and signing/void logic.
- [x] Show a read-only Payment Attachments dashboard section on saved linked leaves; verify source and File permissions. Synchronize only Cheque Leaf-Client fixture.
- [x] Run all form suites, syntax/diff checks and independent review; fix important findings.

## Task 3: activation

- [ ] Snapshot targeted live data/scripts/guide, commit and merge scoped source. Activate six workers, update leaf Custom Script only and refresh PE/GL/leaf form metadata. Do not invoke payment actions or create financial docs/files.
- [ ] Verify business records unchanged, leaf API/live scripts, private guide and commit status; record deployment limitations. No push unless requested.

## Verification and review

- Server regressions failed before implementation (missing gate/APIs), then passed. Form regression initially failed because Reconciled did not wait for attachment handling. Final verification: 125 database-free Python tests and five Node form suites pass, along with syntax/diff checks.
- Independent review identified native v12 escape_html as text-only: it does not encode attribute quotes. The URL injection regression was run with a faithful native escape stub, failed, then passed after explicit href quote encoding; source and fixture match.
- In-flight dialog cancellation regression failed before completed-state guards and passed afterward. Cancelling during readiness checking or save never resumes reconciliation. Failed/silent v12 saves cannot authorize workflow continuation.
- Native FileUploader makes images public by default in this v12 build. The small authorized GL upload callback uses native File insertion with is_private=1 and preserves native file/source permissions, size limits, storage and rollback handling. No duplicate File references or binary copies are created.
- Scope clarification: the leaf section displays all current attachments of its linked payment, subject to permissions. If Finance reuses a payment for a replacement leaf, both old and new payment documents may be listed; only post-signing attachments qualify for that replacement's completion. This is a live view, not an immutable file archive. Payment file deletion still removes a link from this view; no new retention policy is introduced.
