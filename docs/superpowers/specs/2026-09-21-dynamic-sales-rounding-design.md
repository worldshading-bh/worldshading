# Dynamic Sales Rounding Design

## Objective

Provide configurable amount-based rounding rules for Quotation, Sales Order,
and Sales Invoice in ERPNext v12. Rules will be maintained from WS Settings and
will use ERPNext's standard rounded-total and rounding-adjustment accounting
fields when transaction integration is implemented.

## Configuration model

Create the child DocType `Dynamic Rounding Rule` in the `worldshading` app with
these required fields:

- `minimum_amount` — Currency; inclusive lower boundary.
- `maximum_amount` — Currency; inclusive upper boundary.
- `rounding_method` — Select; one of `Nearest`, `Lowest`, or `Highest`.
- `rounding_value` — Currency; the increment to which the amount is rounded.

The child table will use an editable grid. Rule ordering will follow child-row
order. Range validation and transaction calculation are deliberately outside
the initial child-DocType-only change.

## WS Settings integration

WS Settings is currently a UI-created singleton and has no tracked DocType JSON
in the app. A later implementation unit will add a Table custom field pointing
to `Dynamic Rounding Rule`, using the project's established custom-field setup
pattern. This avoids modifying ERPNext core.

## Transaction behavior

When implemented, the rule will be selected using the document grand total
before rounding. The same calculation will apply to Quotation, Sales Order, and
Sales Invoice. Sales Invoice will preserve the standard rounding adjustment so
General Ledger entries remain balanced. Server-side calculation will be
authoritative; client-side calculation may provide the immediate preview.

## Compatibility and safety

- Compatible with ERPNext/Frappe v12 and Python 3.6.
- No core modifications.
- No migration, restart, cache clear, or automated test is part of the initial
  child-DocType-only change.
- Reloading the new DocType creates its database metadata/table; it does not
  activate dynamic rounding on sales transactions.

## Rollback

Before the DocType is reloaded, rollback is removal of the three new DocType
files. After it is reloaded, code files can be reverted, but database metadata
should be removed only through a separately reviewed database change.
