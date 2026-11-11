# Cashflow Forecast — production handover, 11 November 2026

The scoped release is prepared for controlled deployment. Demo calculations and API/UI fixtures pass; production itself has not been changed or certified against its live data. A browser is not installed in the agent environment, so screen behavior was checked against Frappe v12 source and UI fixtures; perform the brief browser check below on the target.

## Verified

- Python 3.6.9, Frappe 12.16.3, ERPNext 12.26.0; standard Script Report with Prepared Report enabled and Accounts Manager/System Manager roles.
- Today's actual+remaining display, remaining-only cash/VAT, history/average modes, holidays, signed returns, source details and monthly cash totals.
- Running balances, overdue gate, supplier/PO/fixed/budget/payroll/VAT sources, purchase installments and independent ETA, quick purchase replay/Clear, exports, permission checks, sticky offsets and collapsible purchase state have regression coverage.
- New payroll control uses posted liability, net salary and 20th–19th periods; dates remain 28th. Quarterly tax dates 25th of following month; automatic historical missing-payment check limited to latest completed quarter.
- Old prepared snapshots remain immutable. New today_policy/payroll_policy keys require a fresh calculation. Quick checks reuse new snapshots and reject obsolete inputs.
- Read-only demo opening and forecast sales reconciled. Full historical forecast 24.618 s; quick purchase replay 0.189 s. Manual sales run 11.298 s. These are single observations, not load-test guarantees.
- No business-site bench run-tests, accounting-data changes, schema migrations, or production deployment performed.

## Scope to deploy

Copy the production files in `worldshading/worldshading/report/cashflow_forecast/`. Merge only the four Cashflow whitelist overrides listed in the release hook patch into the target app's existing `override_whitelisted_methods` dictionary. Other reports are delegated unchanged. Do not replace hooks.py with this working copy: it contains unrelated changes and after_migrate hooks for other features.

Dependencies already present on demo and expected on live: company cash/bank account trees; custom GL Payment and Fixed Expense doctypes and GL Payment.custom_fixed_expense; existing purchase ETA/customs customizations; native payroll, budgets and tax templates. If any dependency is missing on live, provision/review it separately before enabling this report. This release does not bundle or rewrite those workflows.

## Target preflight and activation

1. Take the normal target backup and preserve the previous report directory, four hook values and Report record/roles for rollback.
2. Confirm target version compatibility and read access; verify Bank Accounts and Cash In Hand groups, company Payroll Payable, Output VAT – Sales - WS, Input VAT – Local - WS, Input VAT – Import - WS, Custom Duty - WS. Confirm one eligible import template and a default sales-tax template. Confirm Holiday Lists for relevant years, budget distribution and active payroll assignments.
3. Copy the scoped files and merge the four overrides, preserving every other hook. Register/update only the Cashflow Forecast Report JSON if needed using Frappe's import_file_by_path with force=True and reset_permissions=True. Review target role settings. Avoid a broad migrate of this dirty workspace: it invokes unrelated app migrations/hooks. Normal release pipelines may migrate their reviewed complete release instead.
4. Clear the target app/site caches and gracefully reload web workers using the target's normal process manager. Ensure background workers can import the new files. No asset build is needed for the report-specific JS, which Frappe reads from its report path.
5. Hard-refresh and generate one new prepared report. First run may show the overdue-review popup. Resolve source documents or consciously include overdue amounts; do not alter accounting data merely to hide warnings.
6. In a browser, check compact filters, average checkbox, automatic today tooltip, native collapsible Purchase 1/2 sections, independently toggled ETA, Add/Remove/Clear, horizontal scroll divider, row selection, graph and Download/Export. Quick purchase checks must not create additional Prepared Report rows; a Rebuild must create a fresh calculation. Compare opening balances and one future payroll/VAT/payment with target ledgers.

## Operational limits to communicate

- Forecast assumes invoice sales are collected the same day. Opening cash is the whole requested account pool, including deposits/clearing balances; it is not bank-reconciled withdrawable funds.
- Historical unbooked/unverified payroll slips need review; absent older payroll is not automatically backfilled. Demo booking-link warnings and pending salary JEs are not proof of live debt. Direct final settlements and variable salary components need review.
- Unlinked forward Payroll Payable JEs are matched only within the salary payment calendar month; explicit Payroll Entry links support cross-month dates. Expense-account-only salary JEs remain review items.
- Recoverability of input VAT and the chosen management settlement dates must match Accounts' intended assumptions. Quarterly credits are carried, not assumed cash refunds.
- Review incomplete schedules, supplier credits, missing FX estimates, budget/fixed-expense overlap and missing permissions. No forecast amount constitutes approval to pay.

## Rollback

Disable the Cashflow Forecast Report, restore the previous scoped report files and hook values, restore its previous Report configuration/roles if changed, clear caches and reload workers. Preserve existing Prepared Report attachments for audit; no accounting transactions or schema rollback are required for this report-only release.

Final verification: 134 standalone Python tests and six Node UI suites passed. Scoped hook patch dry-run passed against the repository base. The release archive includes SHA256 checksums and excludes the unrelated dirty workspace changes.

Final recheck: import VAT estimates include valuation-only customs in the VAT base, without adding customs twice when already included. Stored customs GL amounts remain authoritative. VAT policy quarter-v4 requires a fresh prepared calculation. All 134 standalone Python tests and six Node UI suites passed again. The revised quick guide is included. VM resource-outage cause remains unconfirmed; monitor the initial live run.
