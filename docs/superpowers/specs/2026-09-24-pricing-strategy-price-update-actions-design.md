# Pricing Strategy Price Update Actions Design

## Objective

Add two actions to the existing ERPNext v12 **Pricing Strategy Analysis**
Prepared Report:

1. **Update Item Price** performs a confirmed bulk create/update of Regular and
   optional B2B Item Prices from the report's recommended net prices.
2. **Update Pricing Rule** is visible but informational until the quantity-tier
   Pricing Rule structure is approved in a later phase.

No new DocType and no ERPNext core modification are required.

## Scope

This phase implements the complete Item Price action and only the placeholder
Pricing Rule action. It does not create or update Pricing Rules.

The action uses the report result currently shown to the user. It processes at
most the first 50 item rows in the displayed report order. If more than 50 rows
exist, later rows are not processed and the user is warned before confirmation.

## User Interface

The report receives two inner buttons with these exact labels:

- **Update Item Price**
- **Update Pricing Rule**

### Update Item Price flow

1. Require a completed Pricing Strategy Analysis Prepared Report to be loaded.
2. Take the first 50 item rows from the displayed result, excluding total or
   other non-item rows.
3. Use `recommended_regular_net` for the selected Regular Price List.
4. If a B2B Price List is selected, also use `recommended_b2b_net`. If the B2B
   Price List is blank, process only Regular prices.
5. Request a server-side preview. The server resolves the affected Item Price
   records and returns one preview line per item and price list.
6. Show a confirmation dialog containing:
   - Item Code
   - Item Name
   - Price List
   - Current price
   - Recommended new price
   - Action: Create, Update, or Unchanged
7. If the report contains more than 50 item rows, prominently state that only
   the first 50 are included.
8. Only an explicit confirmation invokes the write operation.
9. Freeze the interface while saving to prevent duplicate clicks.
10. Show created, updated, and unchanged counts when complete. Keep the old
    Prepared Report unchanged as the pricing-decision reference.

The confirmation table is read-only. Users narrow the affected set with the
report's Item, Item Group, Brand, and other filters before rebuilding.

### Update Pricing Rule flow

Clicking **Update Pricing Rule** displays an informational message that the
Pricing Rule update configuration is pending. It performs no server write.

## Item Price Resolution

The server uses ERPNext Item Price documents and normal document permission
checks. For each requested item and selected price list:

- Confirm the item exists and is enabled.
- Confirm the price list exists, is enabled, is a selling price list, and has a
  currency.
- Confirm the recommended net price is greater than zero.
- Match the applicable Item Price using the same item, price-list, validity,
  and stock-UOM rules used by the report.
- If applicable records exist, target the latest applicable record selected by
  the report's current ordering. If multiple applicable records exist, expose
  that fact as a preview warning rather than silently updating every duplicate.
- If no applicable record exists, create a selling Item Price for the item's
  Stock UOM and the selected Price List currency. For a price list configured
  as UOM-independent, leave the UOM blank.
- Save through `frappe.get_doc`/`frappe.new_doc` and normal `save`/`insert`
  methods so ERPNext validation, permissions, and version history remain active.

The operation updates the existing applicable record instead of creating a new
dated price each time. New records are immediately applicable and do not invent
historical validity dates.

## Preview and Write Contract

The client sends no more than 50 unique item rows containing Item Code,
Recommended Regular Net, and, when applicable, Recommended B2B Net. It also
sends the selected price lists and the current Prepared Report identifier.

The server independently enforces the 50-item maximum even if the endpoint is
called outside the report UI. It validates the completed Prepared Report name,
report type, owner/access, and saved filters. The selected Regular and B2B price
lists must match the saved Prepared Report filters.

The preview returns an opaque confirmation token tied to the user and preview
payload. The write request supplies that token. Before saving, the server
resolves the Item Prices again and rejects the operation if the target price
lists or current rates changed after preview. This prevents silently
overwriting another user's intervening price change.

All rows are validated before the first write. Any validation or permission
failure aborts the request. Frappe's request transaction provides all-or-nothing
database behavior for save-time failures. The successful response contains
created, updated, and unchanged counts plus the affected Item Price names.

## Permissions and Safety

- Preview requires read permission on Item, Price List, Item Price, and the
  Prepared Report.
- Execution requires create permission when any Item Price is missing and write
  permission for every Item Price being updated.
- The operation never uses `ignore_permissions`.
- Duplicate item rows are de-duplicated by Item Code while preserving the first
  displayed occurrence.
- Missing, zero, negative, nonnumeric, or non-finite prices abort the operation.
- Regular and B2B Price Lists cannot be the same when both are supplied.
- The client disables repeat submission while a request is active.
- Existing Item Price values are not changed during preview.

## Prepared Report Reference

The completed Prepared Report remains the immutable reference showing the cost,
expense choice, markup, VAT, rounding, and recommended prices used for the
decision. Updating Item Prices does not rebuild or alter that report. The user
can rebuild afterward to compare the new current prices against a new snapshot.

## ERPNext v12 Compatibility

Implementation remains inside the custom `worldshading` app and uses APIs
available in ERPNext/Frappe v12. It avoids `frappe.qb`, type annotations,
dataclasses, and modern framework-only APIs.

## Expected Files

- `worldshading/worldshading/report/pricing_strategy_analysis/pricing_strategy_analysis.js`
- `worldshading/worldshading/report/pricing_strategy_analysis/pricing_strategy_analysis.py`
- `worldshading/worldshading/report/pricing_strategy_analysis/test_pricing_strategy_analysis.py`

No report metadata change, DocType, migration, restart, or core edit is planned.

## Verification

Automated tests will cover:

- first-50 selection and duplicate removal;
- Regular-only and Regular-plus-B2B payloads;
- preview create/update/unchanged classification;
- server-side 50-item enforcement;
- invalid item, price, price list, Prepared Report, and permission rejection;
- correct UOM handling;
- concurrent rate-change rejection between preview and execution;
- create, update, and unchanged outcomes;
- atomic failure behavior;
- button and confirmation-dialog contracts;
- Pricing Rule placeholder making no write call.

Verification will use focused Python unit tests and JavaScript syntax/contract
checks. No `bench test`, migrate, restart, or cache-clearing command will run.

## Rollback

The code change is reverted through its dedicated commit. Any business-data
rollback uses the old/new values shown in the confirmation result and the saved
Prepared Report reference. ERPNext document version history remains available
for updated Item Price documents where tracking is enabled.
