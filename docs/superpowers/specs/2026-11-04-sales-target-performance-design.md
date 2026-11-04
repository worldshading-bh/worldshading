# Sales Target and Performance Report Design

## Objective

Add a separate, production-safe sales target foundation to the `worldshading` app. Management will define a target period once, assign an individual amount to each sales employee, and use a performant report to compare submitted Sales Invoice net sales against those targets.

The first version establishes reliable target and achievement data. Points, incentive slabs, commissions, approvals, and payouts are deliberately deferred so they can reference this foundation later without changing the meaning of historical targets.

## Confirmed Business Basis

- World Shading attributes sales through the required custom `pb_sales_employee` Link to Employee on Sales Invoice.
- A read-only production check found that all 13,394 submitted Sales Invoices in the preceding twelve months had `pb_sales_employee`, while none used ERPNext Sales Team rows.
- Achievement is therefore based on `Sales Invoice.pb_sales_employee`, not the ERPNext Sales Person/Sales Team allocation table.
- Achievement uses submitted Sales Invoices only (`docstatus = 1`).
- The amount is company-currency `base_net_total`: after item/document discounts and before taxes.
- Credit notes and return invoices reduce achievement through their negative `base_net_total`, attributed to the employee recorded on the return invoice.
- The old Sales Target and Incentive, Incentive Progress, Incentive Plan, and core Sales Person Commission Summary remain unchanged and are not calculation inputs.

## Goals

- Configure daily, weekly, monthly, quarterly, annual, or custom target periods.
- Maintain one period header with target rows for multiple employees.
- Preserve an auditable submitted target snapshot once management activates it.
- Report each employee's target, achievement, expected progress, remaining amount, and status.
- Use one aggregate Sales Invoice query for all employees in a selected target plan.
- Keep the model compatible with ERPNext/Frappe v12, Python 3.6, and MariaDB.
- Leave clean extension points for later points, incentive, and commission modules.

## Non-Goals for the First Version

- No points, commission, incentive, payroll, Journal Entry, or payout calculation.
- No integration with the unfinished Incentive Plan DocTypes.
- No ERPNext core modification.
- No workflow and no workflow bypass.
- No automatic Sales Invoice, Sales Order, or employee updates.
- No item-group, territory, customer, product, gross-profit, collection, or paid-invoice target scope.
- No scheduled jobs, notifications, dashboards, charts, or salesperson self-service portal.
- No automatic generation of separate daily or weekly target documents from a monthly target.

## Anti-Goals

- Do not store achieved sales on the target document; stored achievement becomes stale when invoices or returns change.
- Do not calculate achievement with one database query per employee.
- Do not infer salesperson credit from owner, creator, Sales Team, customer, or territory.
- Do not let overlapping targets silently combine or double-count for later rewards.
- Do not change or reuse the old quarterly incentive calculation as the target engine.

## Approaches Considered

### 1. Period Header with Employee Target Rows — Selected

One Sales Target document holds the company, target dates, and period type. A Sales Target Detail child row holds each employee and amount.

This supports fast bulk entry, one controlled submission for a whole period, consistent dates across the team, and a single grouped report query. It also gives future reward logic one stable target plan to reference.

The tradeoff is that the standard Sales Target List shows period plans rather than one list row per employee. Individual rows are visible inside the document and in the performance report.

### 2. One Target Document per Employee — Rejected

This makes the standard List view employee-oriented, but duplicates period fields, creates more documents, makes team setup slower, and increases overlap and inconsistency risk.

### 3. Extend ERPNext Sales Person Targets — Rejected

ERPNext v12 targets are fiscal-year based and use monthly distributions. Extending them would couple the feature to core behavior and would not cleanly support the requested independent period types.

## Delivery Sequence

### Phase 1: Sales Target Master

Create and manually verify Sales Target Detail first, then Sales Target. Management can begin entering draft targets after the two DocTypes are reloaded.

### Phase 2: Sales Target Performance Report

Create the report only after the master validates and submits correctly. Reload the report separately and reconcile its figures against Sales Invoice data.

This sequence limits production risk and matches the requested master-first, report-second rollout.

## Data Model

### Sales Target

One submittable document represents one company-wide target plan for one date range.

Proposed naming series: `ST-WS-.YYYY.-.#####`

The document uses standard Frappe `docstatus` as its lifecycle:

- Draft: editable and ignored by the performance report.
- Submitted: active for reporting and locked as an auditable target snapshot.
- Cancelled: excluded from reporting; may be amended through standard Frappe behavior.

Fields:

| Field | Type | Rules |
| --- | --- | --- |
| Naming Series | Select | Required; `ST-WS-.YYYY.-.#####` |
| Company | Link / Company | Required; shown in list/filter |
| Currency | Link / Currency | Required, read-only; fetched from Company default currency |
| Target Name | Data | Required descriptive label; shown in title/list |
| Period Type | Select | Required: Daily, Weekly, Monthly, Quarterly, Annual, Custom |
| From Date | Date | Required; authoritative start date |
| To Date | Date | Required; authoritative end date |
| Total Target Amount | Currency | Read-only; sum of child target amounts |
| Notes | Small Text | Optional management context |
| Targets | Table / Sales Target Detail | Required; at least one row |
| Amended From | Link / Sales Target | Standard amendment field |

The explicit dates are authoritative. Period Type categorizes the business period and controls overlap validation, but the server does not force calendar boundaries. This supports fiscal calendars, Saturday-to-Friday weeks, short launch periods, and other World Shading operating periods without code changes. Client conveniences may suggest dates, but server behavior never depends on the browser suggestion.

All target amounts are denominated in the selected Company's default currency. Currency fields use the parent Currency field as their option, and achievement uses Sales Invoice `base_net_total` in the same company currency. Changing Company in a draft refreshes Currency and revalidates the employee rows.

### Sales Target Detail

Each child row assigns one amount to one Employee for the parent period.

Fields:

| Field | Type | Rules |
| --- | --- | --- |
| Sales Employee | Link / Employee | Required; must be active and belong to the parent company |
| Employee Name | Data | Read-only fetch from Employee |
| Target Amount | Currency | Required; must be greater than zero |
| Remarks | Small Text | Optional row-specific context |

The same Employee may appear only once in one Sales Target document.

The first version intentionally links Employee rather than Sales Person because `pb_sales_employee` is an Employee link and has complete production coverage. This prevents an unreliable Employee-to-Sales-Person translation layer.

## Validation and Server Behavior

Validation must run server-side in the Sales Target controller and remain compatible with Python 3.6.

On validate:

1. Require Company, Target Name, Period Type, From Date, To Date, and at least one target row.
2. Reject To Date earlier than From Date.
3. Reject duplicate Employee rows.
4. Reject zero or negative target amounts.
5. Confirm each Employee is active and belongs to the selected Company.
6. Recalculate Total Target Amount from child rows using Frappe numeric helpers.
7. For a document being submitted, reject an overlap when another submitted, non-cancelled Sales Target has the same Company and Period Type, contains the same Employee, and has intersecting dates.

Different period types may overlap. For example, an independently assigned Weekly plan may exist inside a Monthly plan. They remain separate plans and the report never adds them together. Future points or commissions must explicitly reference one Sales Target so the same invoice is not rewarded twice accidentally.

An amended document ignores its cancelled predecessor during overlap validation. Draft documents do not block each other because only submitted targets are authoritative.

No validation modifies invoices, employees, workflows, permissions, or the old incentive records.

## Client Behavior

Keep client scripting minimal:

- When Period Type changes, offer sensible From Date/To Date defaults if the dates are blank.
- Recalculate the displayed Total Target Amount as child values change for immediate feedback; the server remains authoritative.
- Filter Sales Employee links to active employees belonging to the selected Company where ERPNext v12 link-query support permits.
- Clear or warn about employee rows if Company changes in a draft.

No dialogs, promises, workflow-action interception, or automatic submission are required.

## Permissions

Initial management-only permissions:

### Sales Manager

- Create, Read, Write, Submit, Cancel, Amend, Report, Print, Email, Export

### General Manager

- Create, Read, Write, Submit, Cancel, Amend, Report, Print, Email, Export, Share

### System Manager

- Full document management rights appropriate to a submittable custom DocType

### Accounts Manager

- Read, Report, Print, Export

The first version does not grant Sales User access or implement row-level visibility. Salesperson self-service can be added later only after agreeing how User maps to Employee and what target information colleagues may see.

## Sales Target Performance Report

Create a Script Report named **Sales Target Performance**, referenced to Sales Target.

### Filters

- Sales Target — required Link; only submitted documents should be selectable.
- Sales Employee — optional Link to Employee, restricted to employees present in the selected target where practical in ERPNext v12.
- As of Date — optional Date, default today; clipped to the target period so historical or mid-period progress can be reproduced.

Requiring one Sales Target makes the figures unambiguous and permits one efficient achievement query. A later portfolio/dashboard report may compare multiple plans without changing this report.

### Columns

- Rank
- Sales Employee
- Employee Name
- Period Type
- From Date
- To Date
- Target Amount
- Achieved Amount
- Achievement %
- Expected Amount as of the selected date
- Progress Variance
- Remaining Amount
- Over Target Amount
- Required Daily Run Rate
- Invoice Count
- Status

### Calculation Rules

- Effective As of Date is the later of From Date and the earlier of As of Date, To Date. Before From Date, achievement and expected progress are zero and status is Not Started.
- Achieved Amount is the sum of submitted Sales Invoice `base_net_total` for the plan Company, row Employee, and Posting Date from From Date through Effective As of Date inclusive.
- Return and credit-note values remain negative and reduce achievement.
- Achievement % is Achieved Amount divided by Target Amount times 100, guarded against division by zero.
- Expected Amount is Target Amount multiplied by elapsed calendar days divided by total inclusive calendar days.
- Progress Variance is Achieved Amount minus Expected Amount.
- Remaining Amount is the greater of Target Amount minus Achieved Amount and zero.
- Over Target Amount is the greater of Achieved Amount minus Target Amount and zero.
- Required Daily Run Rate is Remaining Amount divided by remaining inclusive days, or zero once the period has ended or the target is achieved.
- Rank orders employees by Achievement % descending, then Achieved Amount descending, then Employee Name.

Because achievement includes all postings through the Effective As of Date, Required Daily Run Rate uses only dates after the Effective As of Date through To Date. It is zero on To Date. Ranking is calculated for the complete target plan before applying the optional employee display filter, so filtering one employee preserves that employee's team rank.

Status rules, in order:

1. Not Started — As of Date is before From Date.
2. Achieved — Achieved Amount is at least Target Amount.
3. Not Achieved — the target period has ended below target.
4. On Track — current-period achievement is at least expected progress.
5. Behind — current-period achievement is below expected progress.

Elapsed progress uses calendar days in version one. Working-day calendars and holidays are explicitly deferred because they require an agreed Holiday List assignment policy.

### Drill-Down

Employee and invoice-count cells should provide a v12-compatible route or link to the Sales Invoice list filtered by:

- Company
- `pb_sales_employee`
- Posting Date range
- Submitted status

The report itself remains read-only and does not alter invoices.

## Performance Design

The report will:

1. Load the selected submitted Sales Target and its child rows once.
2. Execute one aggregate Sales Invoice query for the target Company and effective date range, grouping by `pb_sales_employee`.
3. Map the aggregate results to child rows in memory.
4. Avoid loading Sales Invoice documents or invoice items.
5. Avoid one query per employee.

`base_net_total` is available on the Sales Invoice parent, so no Sales Invoice Item join is required for an overall-sales target. This is substantially cheaper than the old incentive report's item-level calculations.

At the current production volume, the company/date/docstatus restriction and single grouped query are appropriate. No database index or existing Custom Field definition will be changed in the first version. Query timing should be measured after reload; an index proposal requires separate approval only if production evidence shows it is necessary.

## Future Extension Boundaries

Later features should be separate DocTypes or reports that reference Sales Target and Employee:

- Point Scheme and Point Ledger
- Achievement slabs
- Incentive Scheme
- Commission Calculation
- Commission Payout integration
- Team/manager rollups
- Item-group or territory targets
- Paid-sales or collection targets
- Working-day pacing
- Salesperson self-service view

Historical target amounts and achievement rules must not be silently reinterpreted when these modules are added. Reward calculations should snapshot their rule and result and reference the exact submitted Sales Target.

## Files

Phase 1 new files:

- `worldshading/worldshading/doctype/sales_target_detail/__init__.py`
- `worldshading/worldshading/doctype/sales_target_detail/sales_target_detail.json`
- `worldshading/worldshading/doctype/sales_target_detail/sales_target_detail.py`
- `worldshading/worldshading/doctype/sales_target/__init__.py`
- `worldshading/worldshading/doctype/sales_target/sales_target.json`
- `worldshading/worldshading/doctype/sales_target/sales_target.py`
- `worldshading/worldshading/doctype/sales_target/sales_target.js`

Phase 2 new files:

- `worldshading/worldshading/report/sales_target_performance/__init__.py`
- `worldshading/worldshading/report/sales_target_performance/sales_target_performance.json`
- `worldshading/worldshading/report/sales_target_performance/sales_target_performance.py`
- `worldshading/worldshading/report/sales_target_performance/sales_target_performance.js`

No ERPNext core files and no existing incentive files will be modified. No module-menu change is required in the first version; the DocType and report remain available through standard search and permissions after reload.

## Production Application

Implementation will not run `bench migrate`, `bench test`, restart, backup, restore, or cache-clearing commands.

After code review and explicit approval, apply only targeted site-specific reloads in dependency order:

1. Reload Sales Target Detail.
2. Reload Sales Target.
3. Manually verify the master.
4. Reload Sales Target Performance.
5. Manually reconcile the report.

The exact commands will be shown before execution. No reload command will be run merely by approving this design.

## Verification

Before any reload:

- Parse each new JSON file.
- Compile only the new Python files using syntax compatible with Python 3.6.
- Review JavaScript for ERPNext/Frappe v12 APIs.
- Review the diff and confirm that only the listed new files are touched.
- Review SQL placeholders and ensure all values are parameterized.

After an approved Phase 1 reload:

1. Confirm permissions for each role.
2. Create a draft target with multiple employees and confirm the total.
3. Confirm duplicate employee, invalid dates, inactive/wrong-company employee, and non-positive amount validation.
4. Submit a target and confirm it becomes immutable.
5. Confirm same-type employee/date overlaps are rejected.
6. Confirm a different period type may overlap.
7. Cancel/amend the test target and confirm the amended document can submit.

After an approved Phase 2 reload:

1. Reconcile at least two employees against submitted Sales Invoices for the same dates.
2. Confirm `base_net_total` excludes tax and includes discounts.
3. Confirm a return invoice reduces the correct employee's achievement.
4. Verify Not Started, Behind, On Track, Achieved, and Not Achieved statuses.
5. Verify zero invoices, overachievement, future periods, ended periods, and As of Date clipping.
6. Confirm the optional employee filter and invoice drill-down.
7. Record query duration for a representative monthly and annual target.

## Risk and Rollback

Overall implementation risk is medium because the change creates production metadata and becomes a management performance source, but it does not modify accounting, stock, invoices, workflows, or existing incentive behavior.

Before reload, rollback is deletion of the new files.

After reload but before real target entry, rollback is a separately approved removal of the new Report and DocTypes in reverse dependency order.

After real target records exist, export those records before any removal. The safer operational rollback is to cancel or stop using the new targets and disable access to the report while retaining the audit data. Existing Sales Invoices and old incentive records remain unaffected in every rollback path.

## Builder Decisions

The implementer may choose field ordering, section/column breaks, list-view widths, translated labels, indicator colors, and small helper-function names as long as the behavior above is preserved and the files follow existing World Shading style.

The design review also settled three minor calls: target and report currencies are explicitly the Company default currency; the as-of day is excluded from remaining run-rate days because its invoices are already included; and plan-wide ranking is preserved when an employee filter is used.
