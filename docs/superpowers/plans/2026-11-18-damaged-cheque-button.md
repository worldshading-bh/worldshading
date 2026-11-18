# Damaged Cheque Button Implementation Plan

**Goal:** Record unused cheque damage through the existing cancellation popup, with reason and evidence; make the direct Damaged checkbox read-only.

**Architecture:** Extend Cancel Unused Leaf with an optional damage checkbox and native private FileUploader. The upload area remains visible with a clear note that evidence is required only for damage. Damage requires a real readable File attached to that exact leaf. Reuse the existing account lock/current leaf read and trusted tracking context; direct/API damage toggles are rejected. No new fields or workflows, no automatic changes to payment-owned or signed leaves.

**Scope approved:** User requested read-only field and button popup for reason/damage attachment. Ordinary unused cancellation keeps its reason-only path. Evidence remains under the leaf's existing Attachments, with no duplicate files. Uploading then dismissing leaves the uploaded file attached but does not cancel the leaf.

**Files:** register Python, leaf JS, doctype/custom-script fixtures, register Python/form tests, this plan and private guide.

**Constraints:** ERPNext/Frappe v12 and Python 3.6. No bench test/migrate/restart or real leaf/payment actions. Preserve unrelated main changes. No schema additions; only existing field read_only metadata changes.

**Risk/rollback:** Low/medium. Snapshot leaf definition/script/guide/record values; revert scoped code/settings after reviewing any real damage reports. Retain uploaded evidence and existing cancelled/damaged history.

## Tasks

- [x] Add failing regressions: direct flag toggle/clearing rejected, legitimate button requires reason and exact-leaf attachment, linked/signed/permission denial, private upload, reason-only cancellation unchanged.
- [x] Extract existing available-leaf locking check for reuse; implement guarded damage update and evidence upload with native File insertion.
- [x] Add failing form checks for read-only checkbox, required reason/damage evidence, popup cancel/dirty state and valid submission. Extend existing button and synchronize only leaf fixtures.
- [x] Run database-free suites/syntax/diff checks and independent review; fix important findings.
- [x] Snapshot, commit/merge, activate scoped metadata/script and all six workers; verify unchanged leaf data and update plain-language private guide. No real upload/cancellation tests or push.

## Verification and review

- Direct damage toggles and signed-leaf cancellation regressions failed against prior behaviour, then passed. Button tests initially failed on readonly Damaged and upload handling; private upload entry-point checks ran RED -> GREEN.
- Independent review identified a native v12 Vue/HTML-control lifecycle issue with mounting the uploader directly onto a conditional HTML control. Corrected by using a child mount and an always-visible upload area with explicit required-only-for-damage help. Avoided extra lifecycle/visibility machinery. Regression boundary checks failed before the correction, then passed. No other Important/Critical findings.
- Final pre-activation: 129 database-free Python tests, five Node form suites, JS syntax and git diff checks pass. Includes exact-leaf evidence, permission/wrong-target/empty-content rejection, private uploads, direct flag clearing protection, existing cancellation and dirty/dismissed/duplicate popup controls.

## Production activation

- Main fast-forwarded to `4245c04`; unrelated fixed-expense plan changes preserved. No push.
- Restricted snapshot/receipt: `sites/erp.worldshading.com/private/cheque-register-rollbacks/20261118T113105Z-damaged-cheque-button/`.
- Updated only the existing Damaged field read_only setting and Cheque Leaf-Client script through normal document APIs. Refreshed the leaf form cache/browser metadata token and activated all six existing web workers through the administrator helper. No new columns, workflow changes or service restart.
- Live leaf metadata confirms Damaged readonly and the child-mounted evidence uploader. All book/leaf values match the snapshot; all other leaf field behaviour/settings are unchanged. No leaf was cancelled/marked damaged and no upload was performed during deployment.
- Plain-language private guide now explains the button, reason, required damage evidence, normal reason-only cancellation, uploaded-file-on-dismiss behaviour, and reserved/signed/cleared cases. Existing owner, privacy, notification and sharing settings preserved.
- 129 database-free Python checks and five form suites passed before activation. Full real upload/cancellation remains a supervised manual check; no bench tests/migrate/restart or financial workflow actions were run.
