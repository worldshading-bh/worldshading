# Recurring Sales Target Plan and Performance Report Design

## Intent

Replace the fixed-period interpretation of Sales Target with one stable recurring
plan per company and effective range. Managers enter each salesperson once and set
the applicable daily, weekly, monthly, quarterly, and annual goals. The performance
report derives the relevant occurrence from an As of Date, so nobody edits target
dates every day, week, or month.

The immediate business purpose is to give the sales team clear goals, show each
person's contribution and position, and help managers identify who is achieved, on
track, or behind. Saved period snapshots, points, commissions, and payouts remain a
later phase.

This design supersedes the fixed-period behavior in
`2026-11-04-sales-target-performance-design.md` while preserving its production
safety, permissions, invoice source, and read-only reporting principles.

## Goals

- Configure all recurring target frequencies in one submitted Sales Target plan.
- Keep one child row per salesperson rather than one document per frequency.
- Treat parent From Date and To Date as the plan's effective validity.
- Derive the applicable occurrence automatically for a selected frequency and As of
  Date.
- Show target, achievement, pace, contribution, rank, and team-level performance.
- Continue using submitted Sales Invoice `base_net_total` grouped by
  `pb_sales_employee`, with returns reducing achievement.
- Remain compatible with ERPNext/Frappe v12, Python 3.6, and MariaDB.
- Evolve the existing production DocTypes additively and preserve the three submitted
  test records as legacy audit data until they are cancelled by an approved action.

## Non-goals

- Do not save a generated document for every day, week, month, quarter, or year.
- Do not calculate points, commissions, payout eligibility, or payroll entries.
- Do not freeze or approve period results in this phase.
- Do not add background jobs, scheduler hooks, workflows, or changes to Sales Invoice.
- Do not modify ERPNext or Frappe core.
- Do not provide salesperson self-service or change the management-only permissions.

## Approaches Considered

### 1. One employee row with frequency columns — selected

One parent plan contains one child row per employee and separate Daily, Weekly,
Monthly, Quarterly, and Annual Target columns. This is the clearest entry experience
for managers and makes the complete goal structure visible in one place.

### 2. One child row per employee and frequency

This is more normalized, but repeats every employee up to five times and makes manual
maintenance and review unnecessarily long.

### 3. Generate and save every period occurrence

Saved occurrences provide stronger historical snapshots, but require scheduled jobs,
more documents, exception handling, and a closing policy. That complexity belongs in
the later incentives/commissions phase if immutable results become necessary.

## Data Model

### Sales Target parent

The existing `Sales Target` DocType remains the master. The following fields stay
visible and authoritative:

| Field | Purpose |
| --- | --- |
| Target Name | Human-readable plan name, for example “World Shading 2026 Sales Plan” |
| Company | Company whose invoices and employees are included |
| Currency | Read-only Company default currency |
| From Date | First effective date of the recurring plan |
| To Date | Last effective date of the recurring plan |
| Targets | Employee recurring-target table |
| Notes | Management context |
| Amended From | Standard submitted-document amendment link |

Add read-only parent totals for Daily, Weekly, Monthly, Quarterly, and Annual
targets. Totals are kept separate because amounts from different frequencies are not
mathematically comparable and must never be added into one grand total.

Add a hidden, read-only `target_model` field. The controller sets it to
`Recurring Plan` only in `before_insert` for newly created plans. Existing records
remain blank and are therefore unambiguously legacy records; deployment must not
backfill or rewrite them.

The existing parent `period_type` and `total_target_amount` fields become hidden,
read-only legacy fields. They remain in metadata so the existing submitted records
retain their audit values without destructive schema removal.

The effective range must contain at least one day and may contain at most 366 days.
This keeps one document aligned with one management plan year while allowing a leap
year or a non-calendar fiscal year.

### Sales Target Detail child

Keep one row per Employee with these visible fields:

| Field | Rules |
| --- | --- |
| Sales Employee | Required active Employee from the parent Company; unique in the plan |
| Employee Name | Read-only fetch from Employee |
| Daily Target | Optional positive currency amount per day |
| Weekly Target | Optional positive currency amount per week |
| Monthly Target | Optional positive currency amount per calendar month |
| Quarterly Target | Optional positive currency amount per calendar quarter |
| Annual Target | Optional positive currency amount for the full plan validity |
| Remarks | Optional employee-specific context |

At least one frequency amount must be greater than zero in every employee row. Blank
or zero means that frequency does not apply to that employee. Negative values are
rejected.

The existing child `target_amount` field remains hidden and read-only as a legacy
field. Child `currency` remains hidden/read-only for correct v12 grid formatting.

## Recurring Occurrence Rules

The report requires Sales Target, Frequency, and As of Date. The selected target must
be submitted. The As of Date chooses the occurrence; it never changes the master.

| Frequency | Applicable occurrence |
| --- | --- |
| Daily | The selected date |
| Weekly | Saturday through Friday containing the selected date |
| Monthly | First through last calendar day of the selected month |
| Quarterly | Calendar quarter containing the selected date |
| Annual | The complete parent From Date through To Date validity |

Every occurrence is clipped to the parent validity range. For an As of Date before
the plan starts, the report uses the first occurrence and reports Not Started with no
sales query. For an As of Date after the plan ends, it uses the final occurrence and
includes that completed occurrence's invoices.

For example, a plan valid `2026-01-01` through `2026-12-31` with As of Date
`2026-11-04` produces:

- Daily: `2026-11-04` through `2026-11-04`
- Weekly: `2026-10-31` through `2026-11-06`
- Monthly: `2026-11-01` through `2026-11-30`
- Quarterly: `2026-10-01` through `2026-12-31`
- Annual: `2026-01-01` through `2026-12-31`

## Validation and Submission Safety

Server validation must:

1. Copy the Company currency to the parent and every child row.
2. Validate From Date, To Date, and the maximum 366-day validity.
3. Require at least one employee row.
4. Validate all employees with one bulk read.
5. Reject missing, inactive, wrong-company, or duplicate employees.
6. Require at least one positive frequency value per row and reject negatives.
7. Recalculate all five frequency totals server-side.
8. Require an amendment source to be cancelled.

Before submit, acquire the same transaction-held Company row lock used by the current
implementation. Reject an overlapping submitted plan when the two plans share an
employee and both configure a positive amount for at least one of the same
frequencies. Different employees, or non-overlapping effective ranges, may coexist.
The current document is excluded; a cancelled amendment predecessor is naturally
excluded by `docstatus = 1`.

Only submitted records with `target_model = "Recurring Plan"` participate in this
new overlap rule. Legacy fixed-period records are audit-only and do not block creation
of the consolidated plan. This is required so the consolidated replacement can be
created and verified before the three legacy test records are cancelled.

## Form Behavior

- Employee Link rows are filtered to active employees in the selected Company.
- Changing Company refreshes currency and warns when employee rows already exist; it
  never silently deletes rows.
- Changing any frequency amount recalculates that frequency's displayed parent total.
- Existing dates are never automatically changed.
- Submitted plans remain immutable through normal Frappe submission behavior; changes
  use Cancel and Amend.
- The grid should fit the most-used Daily, Weekly, and Monthly amounts inline in v12;
  Quarterly, Annual, and Remarks may remain available in the expanded row editor if
  the ten-column grid limit prevents showing every field at once.

## Performance Report

Keep the existing `Sales Target Performance` Script Report and add a required
Frequency filter with Daily, Weekly, Monthly, Quarterly, and Annual options. Keep the
required Sales Target, optional Sales Employee, and As of Date filters.

The report loads the submitted target, explicitly checks document read permission,
derives the applicable occurrence, and includes only employees with a positive target
for the selected frequency.

The target Link query should show only submitted records with
`target_model = "Recurring Plan"`. A direct request naming a legacy record must stop
with a clear “select a recurring Sales Target plan” message before any invoice query;
it must never silently return zero rows or reinterpret legacy `target_amount` values.

Use one parameterized parent Sales Invoice aggregate query:

- `docstatus = 1`
- selected Company
- posting date from occurrence start through the effective As of Date
- non-empty `pb_sales_employee`
- grouped by `pb_sales_employee`
- `SUM(base_net_total)` for achieved amount
- `COUNT(name)` for invoice count

If the As of Date precedes the plan validity, skip the invoice query. Returns and
credit notes naturally reduce achieved amount through negative `base_net_total`.

### Employee rows

Each row contains:

- Rank
- Sales Employee and Employee Name
- Frequency
- Occurrence From Date and To Date
- Target Amount
- Achieved Amount
- Achievement Percentage
- Expected Amount as of the effective date
- Progress Variance
- Remaining Amount
- Over Target Amount
- Required Daily Run Rate
- Contribution Percentage to team achieved sales
- Invoice Count
- Status

Ranking is based on achievement percentage, then achieved amount, then employee name.
It is calculated across the complete selected-frequency team before applying the
optional Employee filter.

Contribution Percentage is `employee achieved / team achieved * 100`. Negative
employee contribution remains visible when team achieved is non-zero. When team
achieved is zero, contribution is zero to avoid division by zero.

### Pace and status

Use inclusive calendar-day arithmetic inside the derived occurrence:

- Expected Amount = Target Amount × elapsed occurrence days ÷ total occurrence days.
- Remaining Amount = maximum of Target − Achieved and zero.
- Over Target Amount = maximum of Achieved − Target and zero.
- Required Daily Run Rate = Remaining ÷ remaining occurrence days, excluding the As
  of Date because its invoices are already included.

Statuses remain:

1. Not Started — As of Date is before plan validity.
2. Achieved — achieved amount is at least the target.
3. Not Achieved — occurrence has ended below target.
4. On Track — active occurrence achievement is at least expected progress.
5. Behind — active occurrence achievement is below expected progress.

### Team summary

The report returns v12-compatible summary indicators for:

- Team Target
- Team Achieved
- Team Achievement Percentage
- Achieved salesperson count
- On Track salesperson count
- Behind salesperson count, including ended Not Achieved rows

Invoice-count cells retain the safe Sales Invoice list drill-down using Company,
Employee, occurrence date range, and submitted status. Employee cells should provide
the same filtered invoice-list route rather than the default Employee document link.

## Performance and Permissions

- Keep the existing management roles: Sales Manager, General Manager, System Manager,
  and read/report-only Accounts Manager access.
- Keep one bulk Employee validation query and one grouped Sales Invoice report query.
- Do not query invoice items or execute one invoice query per employee.
- Keep all SQL values parameterized.
- Do not write to Employee, Sales Invoice, or existing incentive records.

## Existing Production Records and Deployment

The current submitted Daily, Weekly, and Monthly test documents are fixed-period
legacy records. They must not be silently converted because that would change the
meaning of submitted audit data.

After deployment they remain readable audit records, do not participate in recurring
overlap validation, and are not valid inputs to the recurring performance report.

Controlled transition:

1. Export or record the three test document names and values.
2. Deploy the additive metadata/controller/report changes with separately approved
   `reload-doc` commands only.
3. Create one new consolidated recurring plan with the same two employees and their
   daily, weekly, and monthly amounts.
4. Reconcile all five frequencies and report calculations without modifying invoices.
5. Cancel the three legacy test documents only through a separately approved user or
   administrator action.

No `bench migrate`, `bench test`, restart, cache clear, scheduler change, or automatic
production record mutation is part of this change.

## Testing

Automated isolated tests must cover:

- additive metadata and hidden legacy fields;
- per-frequency row validation and totals;
- bulk employee validation;
- overlap detection by shared employee and shared configured frequency;
- cancelled amendments and concurrent submission serialization;
- daily, Saturday–Friday weekly, monthly, quarterly, and annual occurrence boundaries;
- validity clipping and before/after-plan As of Dates;
- per-frequency target selection;
- negative returns, zero sales, contribution percentage, stable ranking, and team
  summaries;
- document permission denial before invoice access;
- safe employee and invoice-count drill-down behavior;
- ERPNext/Frappe v12 and ES5 compatibility.

Production acceptance remains read-only until separate approval is given to create or
cancel target records.

## Risk and Rollback

Risk is medium because this changes the meaning and layout of a newly introduced
production master and report, but it remains isolated from accounting, stock,
workflow, invoices, and existing incentive logic.

- Before reload: revert the feature commit; production behavior is unchanged.
- After reload but before a recurring plan is created: reload the prior DocType and
  report JSON/code through a separately approved rollback.
- After recurring plans exist: stop use, export the plans, and retain/cancel them
  rather than deleting audit records. Hidden legacy fields preserve the original
  three test records.
- No rollback path modifies Sales Invoice or Employee.

## Builder Decisions

The implementer may choose helper names, section/column breaks, and v12-compatible
summary-indicator formatting. The implementer must not change frequency semantics,
week boundaries, invoice source, ranking order, permissions, legacy-data posture, or
deployment gates without design approval.
