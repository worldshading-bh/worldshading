# Bank Loan: production scope and deployment

## Final design

Company bank borrowings use Bank Loan, independently of employee Loan. New loans start with original principal; existing loans start with reconciled principal at the tracking date. The repayment schedule records future principal, interest and charges. Generated schedules are estimates for bank review; Equal Installments is the default. Apply fills the Draft table; Save persists it.

Approved loans use Maker / Checker / Approver workflow. Saving changed approved terms opens a revision-reason dialog; the revision date is recorded automatically when the reason is entered. Reapproval preserves previous approved snapshots. Moving an unlinked future installment beyond maturity extends maturity to the latest scheduled date; dates must still be ordered and not before tracking start. Referenced installment identities and posted portions are protected.

Journal Entry has exactly one feature Custom Field: `custom_bank_loan`, a Bank Loan link allowing initial historical linking after submission. Normal JV Accounts rows hold the accounting. Server-managed Bank Loan Payment records hold installment allocations, paying bank, reason, unique request and account snapshot. They are not an additional posting document or an editable user list. Continue creates a native Draft JV and its payment record atomically; normal JV workflow controls submission. Draft amounts must still match their recorded breakdown; prepare corrections from the loan, deleting an unwanted Draft before preparing its replacement. Native cancelled-JV amendments get fresh payment references. Closing is an administrative action that blocks new payment preparation/linking; it does not write off balances or cancel existing Drafts. Previously saved Draft repayments can complete native approval using their stored accounting snapshot.

A Button field loads tracking on demand. One combined table derives actual payment status from linked JVs. Drafts do not count as paid; cancellations are excluded; historical payments before tracking do not reduce the opening principal again. Duplicate request and concurrent pending-installment protection are enforced server-side. A different payment date alone needs no reason when principal, interest and charges match the remaining scheduled amounts; amount differences and historical linking still require a reason. Booked interest/charges can settle the liability without duplicating expense. Payment linking currently supports company-currency loans, not FX/tax calculation.

## File audit

The production application footprint is **24 new files + 3 existing files**, separate from 12 regression-test files and this one optional guide. Empty package initializers and simple child controllers are Frappe/Python structure, not additional features. Frappe v12 imports a named controller for every standard DocType, even a child with no custom methods.

| Path under `worldshading/` | Files | Required purpose |
| --- | ---: | --- |
| `worldshading/doctype/bank_loan/__init__.py` | 1 | Python package discovery/imports |
| `worldshading/doctype/bank_loan/bank_loan.json` | 1 | Loan fields, schedule/revision tables and role permissions |
| `worldshading/doctype/bank_loan/bank_loan.py` | 1 | Save validation, ledger checks and agreement identity |
| `worldshading/doctype/bank_loan/bank_loan.js` | 1 | Form controls, schedule preview/apply |
| `worldshading/doctype/bank_loan/bank_loan_list.js` | 1 | Native loan list fields/status indicators |
| `worldshading/doctype/bank_loan/rules.py` | 1 | Decimal schedule validation/calculation shared by controller and generator |
| `worldshading/doctype/bank_loan/generator.py` | 1 | Flat/Diminishing schedule estimates and future-rate updates |
| `worldshading/doctype/bank_loan/payment_rules.py` | 1 | Allocation arithmetic, accounting comparison, paid/remaining balances and revision limits |
| `worldshading/doctype/bank_loan_installment/` | 3 | `__init__.py`, JSON and named controller for schedule child rows |
| `worldshading/doctype/bank_loan_revision/` | 3 | Same native structure for approved revision history |
| `worldshading/doctype/bank_loan_payment/` | 3 | Same native structure for server-owned JV allocation records |
| `api/bank_loan_workflow.py` | 1 | Native workflow setup and edit/transition guards |
| `api/bank_loan_schedule.py` | 1 | Permission-checked, read-only preview endpoint |
| `api/bank_loan_payments.py` | 1 | Native JV creation/linking, lifecycle guards and tracking |
| `api/bank_loan_revisions.py` | 1 | Approved snapshots, identity protection and revision audit |
| `api/bank_loan_setup.py` | 1 | One JV field, required indexes and legacy payment migration |
| `public/js/bank_loan_payments.js` | 1 | On-demand tracking and native payment dialog |
| `public/js/bank_loan_journal.js` | 1 | Loan-link company/status filter and saved-link locking |
| **New application files** | **24** | Includes four empty `__init__.py` files |
| `hooks.py` (existing) | 1 | Registers setup, client scripts and JE lifecycle validation, preserving other handlers |
| `fixtures/custom_field.json` (existing) | 1 | Adds only Journal Entry's Bank Loan link |
| `config/worldshading.py` (existing) | 1 | Adds native Bank Loans navigation |

All retained modules have active imports, hook registrations, client endpoint calls or native DocType discovery. No generator, workflow, payment or revision helper is an optional unused feature. The former JE allocation child DocType is removed from source. Historical database columns/rows are retained during upgrades; removing DocField metadata is not a destructive SQL-column purge.

### Retained regression tests

All 12 `worldshading/tests/test_bank_loan*` files are development/verification support; none loads on a loan form or makes requests during normal usage.

| Files | Coverage |
| --- | --- |
| `test_bank_loan_form.js` | Form conditions, defaults and list |
| `test_bank_loan_schedule_form.js` | Preview/apply, dialog closure, defaults, stale inputs |
| `test_bank_loan_payment_form.js` | On-demand tracking, combined table, escaping, independent dialog-row deletion |
| `test_bank_loan_rules.py`, `test_bank_loan_generator.py` | Loan inputs, precision, Flat/Diminishing generation, variable-rate bounds |
| `test_bank_loan_register.py` | Register/controller/workflow and account validation |
| `test_bank_loan_schedule_api.py` | Preview permissions and protected installment rows |
| `test_bank_loan_payment_rules.py` | Principal/interest/charges, partials, booked amounts, cancellations and schedule limits |
| `test_bank_loan_payment_api.py` | Financial validation, historical payments and immutable history |
| `test_bank_loan_payment_binding.py` | One-field schema, loan-side storage, native binding, retry, deletion, migration and edit guards |
| `test_bank_loan_revisions.py` | Revision snapshots, reasons and payment-history restrictions |
| `test_bank_loan_hooks.py` | Actual app hook loading and preservation of existing handlers |

The ten historical design/planning documents were consolidated into this guide. Superseded guidance and the unused installment-search endpoint and retired acknowledgment compatibility flag were removed. Prior decisions remain available in Git history.

## Production preparation

Production rollout is not performed by this audit. Review the final feature diff against the actual live branch before integrating; the local comparison baseline used for this audit is `origin/main`. A count of files is not permission to overwrite live configuration.

1. Complete demo user acceptance: generation/save, approval, partial and interest-only payments, extra charges, pending duplicate rejection, cancellation/amendment and approved future revision.
2. Back up the target source, affected metadata and any existing Bank Loan/JV link data. Compare live `hooks.py`, fixtures and module navigation; merge only the feature entries, preserving live changes. No report or core ERPNext file belongs to this feature.
3. Deploy the 24 application files and three scoped configuration edits onto the reviewed live baseline. Keep regression tests in version control; planning/test files are not runtime dependencies. Do not copy demo loan records, illustrative interest rates, JVs or local scripts in `/tmp`.
4. In an initialized target-site context, synchronize scoped DocTypes in order: `bank_loan_installment`, `bank_loan_revision`, `bank_loan`, then `bank_loan_payment`. Verify required existing Maker/Checker/Approver accounts roles. Invoke `worldshading.api.bank_loan_workflow.setup_workflow()` and `worldshading.api.bank_loan_setup.setup_payment_fields()` after all four schemas exist. Review an existing active loan workflow rather than replacing it blindly. No broad bench update/migration is needed for the scoped procedure.
5. Setup first copies any former JV allocation details into Bank Loan Payment records, preserving JV links/references and accounting. Incomplete legacy records stop setup for review. It then removes only the seven obsolete feature Custom Fields, retains Bank Loan, and installs the required lookup indexes. Verify unique indexes on loan identity, payment request and payment journal link. Setup must be repeatable without duplicate payment records.
6. Refresh scoped Bank Loan/Journal Entry metadata caches, including DocType modified timestamps so v12 browser caches refresh. Reload only web/queue processes that cache changed Python code. Verify native form bundles and one feature JV field.
7. Read-only validation: loan/master and accounting records/counts unchanged; migrated payment details reconcile; normal pages/API respond. Run new-transaction acceptance only in the authorized demo or a disposable test site. Do not approve loans, submit JVs or alter actual historical records as part of installation.
8. Rollback requires the matching source/metadata backup and reconciliation of any payments created after deployment. Do not delete loan/payment/revision tables or business documents as a shortcut.

Do not run `bench run-tests` on business-data sites: this v12 installation's global hooks delete unrelated business records. Use offline unittest/Node checks, and controlled demo verification with rollback. No production-wide cache, scheduler, Redis or database restart is required by this feature.

## Verification and remaining scope

Release validation against main `77940acb51a866849b3b1b8f39017d5d39307b5d`: **454 offline Python tests** (198 application + 256 Cashflow Forecast) and **22 Node scripts** (8 application + 14 cashflow) passed. An independent review found no important release defects.

Native demo accounting acceptance used the three approved test loans and real ERPNext/Frappe validation, workflows and GL posting. Each scenario was rolled back; commit was blocked and outbound mail, asynchronous jobs and realtime notifications were suppressed. Ten scenarios passed:

- Normal full payment on each of the new fixed, existing BDB and variable/charges loans; native GL debits/credits, installment balances and outstanding principal reconciled.
- Idempotent retry, pending-duplicate rejection, accounting-tamper rejection and Draft deletion/cleanup.
- Multiple partial payments settling one installment.
- Additional charges and already-booked interest, without expensing that interest again.
- Native cancellation and amendment with a fresh reference, restoring balances and counting the amended payment once.
- Historical BDB JV26-01128 linking, with BHD 3,735 historical cash and no second deduction from opening principal or extra GL posting.
- Two interest-only months, shifting their principal into two additional installments, automatic maturity extension and revision date, and normal reapproval with a preserved audit snapshot.
- Multiple installments in one JV.

A separate native rollback check used enabled non-Administrator users: a Maker created/requested the JV, a distinct Checker submitted it, direct payment-record editing was denied, and Maker/Checker/Approver users completed a future-date loan revision. No roles or user profiles were modified.

The user's existing **submitted** test JV26-01186, all three saved loan records, existing payment records, business record counts and relevant ledger balances matched the baseline after rollback. No test posting remains. Physical demo-only evidence: `/home/erpadmin/bank-loan-final-accounting-verification.json`. These tests establish the exercised paths; they do not replace review of actual bank terms or production permission/configuration differences. Production rollout has not been performed.

Demo examples are illustrative; actual BDB opening/terms need reconciliation against bank documents before operational use. Cashflow report integration, automatic monthly posting, multi-currency repayment and tax calculation are outside this release. Employee Loan remains unchanged.

## Generate from an exact bank installment

For Fixed loans, Generate Schedule now offers **Calculate Using: Interest Rate / Installment Amount**. Interest Rate retains the previous behaviour. Installment Amount uses Equal Installments and the existing balance, frequency, first payment date and count. Enter principal plus interest only; enter identified charges separately in the schedule. Balloon and variable future-rate cases still use the bank schedule/current rate tools.

The calculator derives a non-negative **estimated nominal annual rate**, using Diminishing annuity inversion or Flat interest on original principal. Its bounded Decimal calculation does not change the master Annual Interest Rate. Regular cash installments equal the entered amount; the final principal is reconciled to zero, with any final interest split/cash rounding adjustment shown in the preview. The preview and remarks explain that bank-confirmed splits remain authoritative, especially for irregular first periods, fees and rate changes. Material rounding distortions and infeasible amounts/counts are rejected.

Example: opening principal BHD 29,540.500, 60 monthly installments of BHD 601.950 implies an estimated nominal annual Diminishing rate of approximately 8.210132%, assuming regular end-period payments without separate fees or a balloon. Total cash is BHD 36,117.000, with estimated total interest BHD 6,576.500. This estimate is not confirmation of the bank's actual contract rate or November allocation.

Preview is read-only; Apply fills the unsaved Draft table and Save is still required. Existing permissions and historical/linked-row protections remain. No schema, JV, cashflow calculation or additional persistent fields are introduced. Deployment updates only generator.py and the loan form JS, refreshes the Bank Loan metadata timestamp/cache and reloads the Python web processes serving the preview; no migration or saved-data update is needed.

Installment-mode verification: 208 application Python tests and 275 current Cashflow Forecast Python tests passed, alongside the application/cashflow Node scripts. Native demo preview verified the 60 × 601.950 example above, existing-loan Flat estimation, zero-interest final rounding, unchanged recorded rate and unchanged saved loan/payment/JV records and business counts. Independent review found no important issues. Demo source backup: `/home/erpadmin/bank-loan-installment-amount-backup-20261122-053010`. Production has not been updated by this feature.

## Use the recorded rate and a final settlement

For a Fixed loan, choose **Generate Schedule → Installment Amount → Rate to Use: Use Recorded Rate** when the bank rate is known. This keeps the recorded annual rate, including **0%**, and uses Equal Installments. A recorded zero rate defaults to this option; **Estimate Rate** remains available when the rate is unknown. Enter principal plus interest only; add identified charges separately.

Enter the regular installment, first payment date and number of regular installments. If the principal clears sooner, generation stops and the final payment is reduced. Otherwise choose **Remaining Balance**:

| Option | Result |
| --- | --- |
| Add Final Settlement | Adds one payment on the next frequency date for the remaining principal plus that extra period's interest. The preview shows any maturity extension. |
| Add to Last Installment | Adds the remaining principal to the last selected payment, without adding another period. |

Small currency rounding residue goes into the last payment. Example: opening principal **272,347.595**, recorded rate **0%**, monthly amount **1,786.000**, count **153** produces **152 × 1,786.000 + 875.595**. All interest is zero and scheduled principal exactly matches the opening principal.

These are regular-period estimates: confirm the final amount/date, early-settlement terms, charges and any additional-period interest with the bank. Payments below the period interest require a bank-confirmed manual schedule; negative amortisation is not generated. The limit remains 600 rows including any settlement. Existing linked and historical rows remain protected.

Preview changes nothing. **Apply to Draft** fills the unsaved schedule and extends maturity if necessary; **Save** and the existing approval workflow are still required. The recorded annual rate is unchanged. No new schema, JV fields, accounting entries or automatic payments are introduced.
