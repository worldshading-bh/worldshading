# Simple Campaign Customer Workflow Design

## Intent

Make Campaign Customer a practical daily follow-up tool. A manager should be
able to turn ranked Customer Retention Analysis results into assigned campaign
work in batches, while a cashier should be able to record a contact outcome,
note, status, and next follow-up without editing the interaction child table.

Success means the normal cashier action takes one dialog and one save. The
interaction table remains the audit history, not the main data-entry surface.

## Goals

- Bulk-create Campaign Customer records from the currently displayed retention
  report rows, preserving the report's displayed customer order.
- Let the manager choose Campaign, Caller, Planned Contact Date, Priority, and
  the number of new customers to add in the batch.
- Skip customers already present in the selected Campaign so repeated batches
  can assign the next customers without duplicates.
- Provide a prominent Record Contact action on both the Campaign Customer form
  and each active row in its list.
- Collect Channel, Outcome, Notes, Status, Next Follow-up, and Next Action in a
  small dialog; set interaction time and handled-by user automatically.
- Keep current outcome, latest note, contact time, next follow-up, and status
  visible without opening the interaction table.
- Preserve all existing Campaign Customer and interaction records.

## Non-goals

- No standard Frappe Workflow document or approval states.
- No ToDo or Assignment records.
- No automatic calls, WhatsApp, SMS, email, or notifications.
- No row-level permission redesign.
- No accounting, stock, Customer, Opportunity, or historical interaction
  changes.
- No custom Desk Page or new frontend framework.

## Constraints

- ERPNext/Frappe v12 and Python 3.6 only.
- Changes remain in the `worldshading` custom app.
- Do not use `frappe.qb`, type annotations, dataclasses, or newer Frappe APIs.
- Do not run migrate, bench tests, reload-doc, restart, backup, restore, or
  cache-clearing commands during implementation.
- Use isolated mocked/unit and JavaScript behavior tests only.

## Approaches Considered

### 1. Standard DocType form/list with action dialogs — chosen

Use the existing Campaign Customer list as the cashier queue. Add Record Contact
dialogs to the form and list, and add a bulk-create dialog to the existing
retention report. Server methods own validation and persistence.

This is the smallest implementation, stays familiar to ERPNext v12 users, and
keeps interaction history in one place.

### 2. Dedicated cashier Desk Page

A custom page could combine queue navigation and editing in one screen, but it
would duplicate list filters, permissions, routing, and refresh behavior. It is
too much custom UI for the initial workflow.

### 3. Standard Frappe Workflow

A formal Workflow would provide controlled transitions, but every contact would
become an approval-style action. That adds clicks and does not solve quick notes
or interaction creation. The business need is an operational flow, not an
approval workflow.

## Daily User Flow

### Manager

1. Open Customer Retention Analysis and choose filters/ranking.
2. Click **Create Campaign Customers**.
3. Choose Campaign, Caller, Planned Contact Date, Priority, and Batch Size.
4. Confirm the displayed source count.
5. The server walks displayed customers in order, skips customers already in
   that Campaign, and creates up to Batch Size new records.
6. Repeat with another Caller to allocate the next batch.

The request accepts at most 250 displayed customers, matching the report's
maximum finite result size. The response states how many were created and how
many were already present.

### Cashier

1. Open Campaign Customer list and use its normal Caller, Status, Campaign,
   Planned Contact Date, and Next Follow-up filters.
2. Click **Record Contact** on an active row, or open the document and use the
   same action.
3. Enter Channel, Outcome, a required short Note, Status, optional Next
   Follow-up, and optional Next Action.
4. Save once.
5. The server appends the interaction with the current timestamp/user, updates
   current status/action fields, saves, and returns the updated summary.

Converted and Closed rows do not show the list quick-action button. They can
still be reopened and reviewed normally.

## Form and List Presentation

The form puts the actionable summary before history:

- Customer and phone/WhatsApp/contact details.
- Campaign, Caller, Status, Priority, and planned date.
- Last Contact On, Last Outcome, Latest Note, Next Follow-up, Next Action, and
  Opportunity.
- Collapsible customer background details and interaction history.

`latest_note` is a read-only parent field maintained from the latest dated
interaction. The list loads Status, Caller, Planned Contact Date, Next Follow-up,
Last Outcome, and Latest Note, with colored status indicators and a Record
Contact row button.

The child interaction table remains available for audit/review. Normal contact
entry no longer requires opening or editing it.

## Server Behavior

### `record_contact`

The whitelisted method accepts a Campaign Customer name and dialog values. It:

- loads the document and checks write permission;
- validates Channel, Outcome, Status, and Next Action against fixed approved
  options;
- requires Notes;
- requires Next Follow-up when Status is Follow Up or Interested;
- appends one Campaign Interaction Log row with `frappe.session.user` and
  `now()`;
- updates Status and Next Action;
- saves through the normal document API so existing duplicate and Opportunity
  validation still runs.

The latest dated interaction always owns the current Next Follow-up value,
including clearing an old follow-up when the new interaction has none. With no
interactions, a manually planned follow-up remains unchanged.

### `bulk_create_campaign_customers`

The whitelisted method checks Campaign Customer create permission, validates
inputs, removes duplicate customer codes while preserving order, and limits the
source to 250. It queries existing records for the Campaign once, then creates
up to Batch Size records through `frappe.get_doc(...).insert()`.

Each new record receives Campaign, Customer, Caller, Planned Contact Date,
Priority, and Planned status. Existing Campaign/Customer pairs are reported as
skipped. An unexpected insert failure is not swallowed, allowing the request
transaction to roll back instead of silently producing a partial batch.

## Error Handling and Security

- UI validation improves speed, but all important validation is repeated on the
  server.
- Record Contact respects document write permission.
- Bulk creation respects Campaign Customer create permission and standard insert
  validation.
- Empty or oversized customer lists, invalid option values, missing required
  notes/follow-ups, and invalid batch sizes are rejected with clear messages.
- Existing uniqueness enforcement remains the final concurrency safeguard.

## Testing

- Python unit tests mock database/document calls and cover quick interaction
  persistence, permissions, required values, summary clearing, bulk ordering,
  duplicate skipping, limits, and insert failures.
- JavaScript behavior tests cover dialog fields, outcome-to-status suggestions,
  form/list refresh, active-row buttons, and the retention report payload.
- JSON parsing, Python compilation, JavaScript syntax checks, and `git diff
  --check` complete verification.

## Rollback

Revert the task-scoped commits and reload Campaign Interaction Log, then Campaign
Customer, followed by the report assets as normally deployed. Existing parent
and child records remain valid; the only added stored field is the nullable,
read-only `latest_note`, so reverting code does not delete business history.
