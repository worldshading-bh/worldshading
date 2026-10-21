# Campaign Customer Design

## Objective

Add a multi-channel campaign follow-up record to the `worldshading` app for existing ERPNext Customers. The record will let cashiers and sales managers plan contacts, preserve interaction notes, schedule follow-ups, and link a qualified customer to an Opportunity without treating every campaign target as a Lead or Opportunity.

The first intended campaign is **2026 Sales Sprint**, but the design must support later Campaign records and contact channels without code changes.

## Scope

The change adds:

- A parent DocType named **Campaign Customer**.
- A child DocType named **Campaign Interaction Log**.
- A Campaign Management section in the ERPNext CRM module view.
- Server-side validation and summary calculation compatible with ERPNext/Frappe v12 and Python 3.6.

The change does not add a workflow, modify ERPNext core files, send messages, create Opportunities automatically, change the existing Call Assistant, or restrict cashiers to row-level ownership in the first version.

## Why the Name Is Channel-Neutral

The parent is named **Campaign Customer**, not Call Campaign. It represents an existing Customer selected for a Campaign. Calls, WhatsApp messages, SMS messages, emails, and visits are interaction channels recorded beneath that customer. This avoids renaming the DocType when campaigns expand beyond telephone calls.

## Data Model

### Campaign Customer

One record represents one Customer in one Campaign. The same Campaign and Customer combination must not be entered twice.

Naming series: `CC-.YYYY.-.#####`

The DocType is a non-submittable document with change tracking, import enabled, and standard list/report support.

### Campaign Interaction Log

This is an editable child table. Each row preserves one attempted or completed interaction. Historical rows remain visible instead of overwriting the previous call note.

## Form Layout

### Campaign and Schedule

Left column:

- **Campaign** — required Link to Campaign; shown in list and standard filters.
- **Status** — required Select; default `Planned`; shown in list and standard filters.
- **Priority** — required Select; default `Standard`; shown in list and standard filters.

Right column:

- **Caller** — required Link to User; default current user; shown in list and standard filters. This is a business owner field and does not use Frappe Assignment or ToDo.
- **Planned Contact Date** — required Date; shown in list and standard filters.
- **Planned Contact Time** — optional Time.

Status options:

- Planned
- Follow Up
- Interested
- Not Interested
- Converted
- Closed

Priority options:

- Standard
- Top 20

### Customer Details

Left column:

- **Customer** — required Link to Customer; shown in list and standard filters.
- **Customer Name** — read-only Data fetched from Customer.
- **Customer Group** — read-only Link fetched from Customer.
- **Territory** — read-only Link fetched from Customer.

Right column:

- **Contact Person** — optional Link to Contact.
- **Mobile Number** — optional Data.
- **WhatsApp Number** — optional Data.
- **Email Address** — optional Data with Email validation.

Customer contact values may be entered or corrected on the campaign record without changing the Customer master. Selecting a Customer populates missing values from that Customer. Selecting a Contact populates missing values from that Contact.

### Follow-up and Conversion

Left column:

- **Next Action** — Select: blank, Call, WhatsApp, SMS, Email, Visit, None.
- **Next Follow-up** — optional Datetime.
- **Visit Required** — Check.

Right column:

- **Opportunity** — optional Link to Opportunity.
- **Last Contact On** — read-only Datetime calculated from the interaction table.
- **Last Outcome** — read-only Data calculated from the interaction table.
- **Number of Interactions** — read-only Int calculated from the interaction table.

Linking an Opportunity is permitted only when its party is the same Customer. The link does not bypass Opportunity permissions, workflow, or normal creation rules.

### Interaction History

The **Interactions** table uses Campaign Interaction Log rows with:

- **Interaction On** — required Datetime.
- **Channel** — required Select: Call, WhatsApp, SMS, Email, Visit.
- **Handled By** — required Link to User; default current user.
- **Outcome** — required Select.
- **Notes** — required Small Text.
- **Next Follow-up** — optional Datetime.
- **Call Log** — optional Link to Call Log, primarily for PBX calls.

Outcome options:

- No Answer
- Busy
- Call Back Later
- Message Sent
- Replied
- Interested
- Not Interested
- Wrong Number
- Visit Scheduled
- Order Confirmed
- Other

### Internal Notes

- **General Notes** — optional Text Editor for campaign-level context that does not belong to a single interaction.

## Behavior and Validation

On validation, the server will:

1. Reject a duplicate Campaign and Customer combination.
2. Recalculate Number of Interactions from the child rows.
3. Set Last Contact On and Last Outcome from the most recent interaction by Interaction On.
4. Copy the latest non-empty child Next Follow-up into the parent Next Follow-up.
5. Reject an Opportunity linked to a different Customer.

The server will not automatically mark a record Interested, Not Interested, Converted, or Closed. Staff retain explicit control of the parent status so an individual outcome does not unexpectedly close the campaign relationship.

Client-side behavior will:

- Populate missing customer contact details when Customer changes.
- Populate missing phone/email details when Contact Person changes.
- Apply a Contact query restricted to Contacts linked to the selected Customer where supported by the v12 contact query.
- Make the interaction table convenient to edit without introducing dialogs or workflow actions.

## CRM Placement

The DocTypes remain in the **Worldshading** module so they are owned by the custom app. A new `worldshading/config/crm.py` module configuration contribution will add a **Campaign Management** section to ERPNext's CRM module containing:

- Campaign Customer
- Campaign

ERPNext v12 combines same-module configuration contributed by installed apps, so no ERPNext core configuration file is changed.

## Permissions

### Cashier

- Create
- Read
- Write
- Report

Cashier does not receive delete, export, share, or permission-management rights from this DocType definition.

### Sales Manager

- Create
- Read
- Write
- Delete
- Report
- Export
- Print
- Email
- Share

### System Manager

- Full document management rights appropriate to a non-submittable DocType.

The first version does not add row-level permission query hooks. Cashiers with read permission can see all Campaign Customer records and use Caller filters for their own work.

## Existing Call Assistant

The repository already contains a `call-assistant` Page with PBX Call Log context and an unfinished Add Note action. This first version will not modify that Page. A later, separately approved change may connect Add Note to Campaign Customer when a live caller belongs to an active campaign.

## Files

New files:

- `worldshading/worldshading/doctype/campaign_customer/__init__.py`
- `worldshading/worldshading/doctype/campaign_customer/campaign_customer.json`
- `worldshading/worldshading/doctype/campaign_customer/campaign_customer.py`
- `worldshading/worldshading/doctype/campaign_customer/campaign_customer.js`
- `worldshading/worldshading/doctype/campaign_interaction_log/__init__.py`
- `worldshading/worldshading/doctype/campaign_interaction_log/campaign_interaction_log.json`
- `worldshading/worldshading/doctype/campaign_interaction_log/campaign_interaction_log.py`
- `worldshading/config/crm.py`

No ERPNext core file will be modified.

## Production Application

Implementation will not run `bench migrate`, `bench test`, any restart, backup, restore, or cache-clearing command.

After code review, the two DocTypes can be applied individually with site-specific `reload-doc` commands supplied for manual execution. Campaign Interaction Log must be reloaded before Campaign Customer because the parent references the child table.

## Verification

Before any database reload:

- Parse both JSON files.
- Compile only the new Python files for Python 3 syntax compatibility while avoiding modern syntax unsupported by Python 3.6.
- Review the diff and confirm that no existing application files except the new CRM configuration contribution are touched.

After an approved manual reload:

1. Confirm Cashier, Sales Manager, and System Manager permissions.
2. Create a Campaign Customer for a test Campaign and Customer.
3. Confirm duplicate Campaign and Customer validation.
4. Add interactions for more than one channel.
5. Confirm last-contact summaries and follow-up values.
6. Confirm an Opportunity for another Customer is rejected.
7. Filter records by Campaign, Caller, Planned Contact Date, Status, and Priority.
8. Confirm Campaign Customer appears in CRM under Campaign Management.

## Risk and Rollback

Risk is low to moderate. Reloading creates two new tables and DocType metadata but does not alter stock, accounting, workflow, Customer, Campaign, Opportunity, or Service Visit schemas.

Before reload, rollback is deletion of the new files. After reload, data should first be exported if records exist; then the new DocTypes can be removed through a separately approved controlled operation. Removing the CRM configuration contribution removes the module shortcut without affecting existing ERPNext CRM records.
