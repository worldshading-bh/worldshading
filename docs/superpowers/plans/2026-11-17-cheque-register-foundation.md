# Cheque Register Foundation Implementation Plan

**Goal:** Finish the existing Cheque Book and Cheque Leaf register for World Shading's own outgoing cheques.

**Deployment status (2026-11-17):** User explicitly authorized merge to `main` and targeted live activation. Code is merged; the two DocTypes, their native Custom Scripts, permissions and bank-scoped unique index are active. All six current web workers loaded the validators without a restart. Live form metadata and dashboard HTTP checks passed. The existing book and two Available leaves are preserved; no leaves were generated or cancelled. No bench test, migrate, restart or broad cache-clear command was run.

**Approved scope:** The six-step chat plan was accepted on 2026-11-17, with Journal Entry added alongside Payment Entry and GL Payment. This implementation covers the two register DocTypes only. Payment-side reservation, workflow actions, ledger posting and bank-clearance synchronization are a later phase. No collector or handover fields.

**Constraints:** Production ERPNext/Frappe v12, Python 3.6. No bench test, migrate, restart, bulk cache clearing, payment changes or automatic production deployment. Preserve existing cheque records and names. Current baseline: one book, two leaves; 43 database-free fixed-expense tests pass.

**Approach:** Keep both custom DocTypes. Use custom-app event hooks for validation, a permission-checked API for safe generation, and small form scripts for the book dashboard and leaf actions. Preserve legacy Payment Entry link and add GL Payment/Journal Entry links, all readonly until payment integration. New leaves use independent document IDs; account + normalized cheque number defines uniqueness.

## Files

- `worldshading/api/cheque_register.py`: range validation, account-scoped serialization, record protection, generation, unused-leaf cancellation and dashboard.
- `worldshading/public/js/cheque_book.js`, `cheque_leaf.js`: form controls and clickable inventory totals.
- `worldshading/fixtures/doctype.json`: append the two current custom definitions with minimal field changes; preserve other definitions.
- `worldshading/hooks.py`: add only cheque events/scripts and fixture names.
- `worldshading/fixtures/custom_script.json`, `server_script.json`, `custom_docperm.json`: native custom-form scripts, disabled legacy validation, and scoped permissions. Frappe v12 skips `doctype_js` for custom DocTypes, so form scripts are installed through Custom Script instead.
- `worldshading/tests/test_cheque_register.py`: database-free logic tests with an in-memory storage boundary.
- `docs/superpowers/plans/2026-11-17-cheque-register-foundation.md`: implementation and activation record.

## Tasks

- [x] 1. Test and implement numeric ranges (1–50 leaves), leading zeros, inclusive overlaps and status summaries.
- [x] 2. Test and implement book/leaf validation and identity protection, including the three payment links.
- [x] 3. Test and implement permission-checked, serialized generation that fills missing inventory without renaming existing leaves.
- [x] 4. Add dashboard, unused-leaf cancellation and metadata/permission changes.
- [x] 5. Run database-free Python checks, JavaScript syntax checks and isolated form tests. Review the complete diff.

## Review focus

- Padded numbers must not lose zeros or bypass account-scoped duplicate detection.
- Existing leaves retain names and history; concurrent production additions require a new activation preflight.
- Direct form/API writes cannot set financial links, amount, clearance or operational statuses.
- Count/list access and generation/cancellation must respect permissions.
- A closed book cannot generate inventory; a populated book cannot change its account/range or be deleted.

## Activation and rollback

This branch is preparation, not a deployment. Activating it requires a reviewed targeted metadata update of the two custom DocTypes and replacement of the old leaf-numbering Custom Script/book-validation Server Script. Do not run migrate. Saving these definitions changes their tables through Frappe's normal DocType save, so activation must be explicit and must preserve a private metadata/script/permission snapshot first. Backfill account/company/currency/normalized number on existing leaves without changing names, status, payment links or business values; preflight duplicates before adding an account/normalized-number unique index. Existing linked leaves require review before activation.

Hook loading must be verified in the web process; no restart or broad cache-clear is authorized. Do not claim live behavior until this is verified. On rollback, restore the previous app files, two definitions and scripts/permissions. Preserve all business records; do not delete generated leaves. If new records use repeated numbers at different banks, do not restore the old globally unique cheque-number constraint until those records are reconciled.

## Execution record

- Preparation in `/tmp/worldshading-cheque-register-20261117`, branch `feature/cheque-register-foundation`; production checkout remains unchanged.
- Ruling: independent IDs apply only to new leaves. Existing leaf names are preserved to avoid breaking links.
- Ruling: this phase does not offer manual Reserved/Issued/Cleared/Bounced transitions or payment-link editing; those require the next phase's payment-side checks.
- Ruling: book validity dates remain optional as in the current live definition; if both supplied, they must be ordered.
- Ruling: a single-leaf range is allowed; the maximum remains 50.
- Ruling: use a non-waiting MariaDB advisory lock per database/account, then current locking reads. A competing operation receives a retry message. The lock lasts until the connection closes; Frappe v12 closes web/job connections in `frappe.destroy()` after commit/rollback. Standalone callers must likewise close their connection. Ordinary document saves already hold a row lock before validation, so waiting on an Account row would create lock-order cycles.
- Ruling: dashboard totals use permission-filtered leaves and show book capacity separately. A hidden leaf must not be reported as missing inventory.
- Final review: independent reviewer identified the lock-order and dashboard-access issues above; both reproduced with failing checks and corrected. Also corrected readonly form-state reuse, with a failing/passing Node check.
- Verification: 66 database-free Python unittest checks pass (23 cheque-register checks plus 43 existing checks). Existing two Fixed Expense Node checks and new cheque form checks pass; both new form scripts pass `node --check`. Python syntax parsed using Python 3.6. Unrelated DocType fixtures compare exactly to the base revision; diff whitespace checks pass.
- Verification limit: no bench test, migrate, database writes, browser test or live MariaDB concurrency test. Lock helpers/storage are substituted in unit tests. Before activation, exercise generation versus ordinary saves, cancellation versus leaf edits, duplicate generation and restricted-user dashboards on a separate v12/MariaDB site.

## Authorized deployment record

- Pre-deployment private snapshot: `sites/erp.worldshading.com/private/cheque-register-rollbacks/20261117T072019Z/before.json` (restricted filesystem permissions). The adjacent `apply.py` records the exact targeted changes; `receipt.json` records successful activation and live checks. No authentication credentials are stored in these files.
- Main fast-forwarded through `9d7a93b`; deployment additionally synchronizes actual Custom DocPerm record identities in the fixture.
- Both metadata definitions were saved through normal Frappe DocType APIs, without running migrate. The old book Server Script is disabled; both native Custom Scripts are installed from the versioned JavaScript sources.
- Existing documents were saved through the new validators to populate bank account, company, currency and normalized cheque number. Names and business values were compared with the snapshot and preserved. The unique index `ws_bank_cheque_unique` covers account plus normalized number; the old globally unique cheque-number index is removed.
- Administrator-only `activate_worker` loads the updated app hooks in each preloaded web worker. All six worker PIDs were observed with active validators. The server has developer mode enabled; no broad hook-cache flush was performed.
- Live authenticated GET checks confirmed the native scripts and readonly payment-link fields in form responses. The dashboard returned 2 visible leaves, all Available, against book capacity 50. The database index was checked directly. No business records were created for testing.
- Refreshed only cached boot permission snapshots for the 23 users holding affected roles, so their next desk load reflects the new permissions.
- Current verification: 67 database-free Python tests, new cheque form checks, existing Fixed Expense form checks and JavaScript syntax checks. Browser interaction, actual generation/cancellation and concurrent edit testing remain unperformed.
- Rollback: retain all business records. Restore the two prior metadata definitions, native scripts and custom permission rules from the private snapshot, and revert the cheque code commits. Reload the restored app hooks in the web workers through an authorized targeted maintenance operation. Do not restore global cheque-number uniqueness if later records contain the same printed number at different banks. Added database columns may remain to preserve data; do not drop them automatically.
