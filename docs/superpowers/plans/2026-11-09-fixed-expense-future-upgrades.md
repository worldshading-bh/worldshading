# Fixed Expense — future upgrades

Status: backlog notes, not approval to implement. Updated 9 November 2026.

## Already completed

- Renamed the master to Fixed Expense, with FEX numbering.
- Organized the form around general business expenses and GL-style account/tax rows.
- Amounts are entered in the expense currency; foreign expenses have a company-currency estimate.
- Manual Create GL Payment button opens an unsaved payment with accounting defaults and converted amounts for review.
- GL Payment has an optional Fixed Expense custom Link, filled by the button.
- Frequencies include Monthly, Quarterly, Half-yearly, Yearly, and Every 2, 3, 4, or 5 Years.

## Future work

### 1. Automatic GL Payment drafts

- Check active expense schedules daily and prepare draft GL Payments when due.
- Respect first due date, frequency, end date, and closed status. The new multi-year dropdown options still need to be supported by the future scheduling logic.
- Use the latest valid stored buying exchange rate for foreign-currency estimates. Accounts adjusts the payment to the actual bank charge before approval/submission.
- Keep the existing approval workflow; creation does not mean paid or submitted.
- Decide when to create drafts (on the due date or a configurable number of days earlier), how to handle overdue schedules at rollout, and how variable-budget expenses should be reviewed.
- GL Payment currently requires bank references before saving. Design a narrowly scoped way to save generated drafts without references, while requiring the real references before the appropriate workflow transition. Do not invent reference values.

### 2. Scheduled due date and duplicate restriction — deferred

- User explicitly deferred implementation of duplicate restriction.
- Proposed field on GL Payment: Scheduled Due Date, alongside the existing Fixed Expense link.
- Identify a scheduled payment by Fixed Expense + Scheduled Due Date, not by GL posting month.
- Manual creation selects a valid due date from the expense schedule; automatic creation selects the due occurrence.
- Block another payment for the same occurrence when a draft or submitted payment exists. A cancelled payment permits replacement.
- Enforce this server-side, including simultaneous saves, and cover linked payments created directly through GL Payment as well as the button and scheduler.
- Finalize this protection before enabling unattended automatic creation, so repeated scheduler runs cannot generate duplicate drafts.

Why a due date: monthly can mean a cycle such as 15 October–14 November. Its payment might be due on 15 October in advance or 15 November in arrears. Store the agreed scheduled due date; the actual GL posting date can differ. A service coverage From/To range is not required just for duplicate protection.

Historical example: the user identified GLP-2601985 as October rent paid in November. Assign historical payments to their expense and scheduled due date only after confirming the agreement; do not infer the period from the posting date. Reconcile the expense's tracking start/first due date if earlier occurrences need tracking.

### 3. Payment monitoring and reminders

- Show scheduled, draft/in-progress, paid, and overdue occurrences, with links to GL Payments.
- Define paid status using the actual GL Payment workflow and cancellation behavior; draft existence alone must not mean paid.
- Add a monthly monitoring report and reminders once reliable occurrence tracking is available.
- Recheck missing rates, invalid accounting defaults, and failed draft creation without silently dropping expected expenses.

### 4. Cashflow forecast — main business goal

- Combine opening available cash, expected customer collections/sales assumptions, recurring expense schedules, submitted purchase commitments, and outstanding supplier/credit payments.
- Show projected cash available by date to support purchasing and payment decisions.
- Place recurring outflows on their scheduled payment dates, including multi-year renewals; do not forecast an annual payment for a four-year contract.
- Use company-currency estimates consistently and distinguish estimates from actual payments.
- Avoid counting the same obligation twice across expense schedules, GL Payments, purchase orders, and invoices.
- Agree the forecast horizon, collection timing assumptions, and any minimum cash reserve before presenting an amount available to spend.

## Working constraints

- Keep the form and implementation simple; no extra preview files.
- ERPNext/Frappe v12 and Python 3.6 compatibility.
- No bench migrate or bench tests unless explicitly authorized.
- These notes do not enable automation, add fields, change workflows, or apply duplicate restrictions.
