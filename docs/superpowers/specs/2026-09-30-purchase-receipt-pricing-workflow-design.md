# Purchase Receipt Pricing Workflow Design

## Objective

Let staff open Pricing Strategy Analysis directly from a submitted Purchase Receipt and review pricing for every received Item plus every active member of those Items' Pricing Groups.

The workflow prepares analysis only. It never updates Item Price or Pricing Rule records automatically.

## User workflow

1. Open a submitted, non-return Purchase Receipt.
2. Click **Update Pricing**.
3. Select an enabled Pricing Strategy Template for the Purchase Receipt company in a small dialog.
4. Continue to Pricing Strategy Analysis.
5. The report opens with Company, Pricing Strategy and Purchase Receipt prefilled.
6. Generate or rebuild the report, review the recommendations, then use the existing update actions when appropriate.

The button is not shown for draft, cancelled or return Purchase Receipts.

## Report filter

Add an optional **Purchase Receipt** Link filter to Pricing Strategy Analysis.

- It permits only submitted, non-return Purchase Receipts.
- Its query follows the selected Company.
- It is stored and restored with Prepared Report filters.
- It does not automatically apply the Purchase Receipt warehouse. Warehouse remains blank unless the user deliberately selects one, avoiding missing warehouse-specific valuation rates.

When Purchase Receipt is selected, it becomes the authoritative Item scope. Item, Item Group, Pricing Group, Brand and Stock UOM filters are cleared in the client and ignored by the server for scope construction. Company, date, strategy, warehouse and expense settings continue to apply.

## Item expansion

The server validates that the selected Purchase Receipt:

- exists;
- is submitted;
- is not a return; and
- belongs to the selected Company.

It loads distinct stock Item codes from Purchase Receipt Item and expands them as follows:

- an ungrouped received Item is included directly;
- for a received Item with `pricing_group`, every active stock Item in that Pricing Group is included;
- duplicate Items are removed;
- disabled and non-stock group members are excluded consistently with existing Pricing Group membership rules.

The expanded set then passes through the existing cost, sales, expense, shared-price and Pricing Rule calculations. The 50-Item bulk-update limit remains unchanged. A Pricing Group crossing that limit is blocked rather than split.

## Pricing Group behavior

The existing reference selection remains unchanged:

- highest Sales Qty among members with complete valid pricing;
- next-highest valid seller if a higher seller lacks pricing inputs;
- highest valid Recommended Regular price when all group members have zero sales;
- block only when no member has a complete valid price structure.

All active group members are displayed even when only one member appeared on the Purchase Receipt.

## Purchase Receipt client integration

Add a custom Purchase Receipt client script through the worldshading app's `doctype_js` hook.

The dialog contains one mandatory Link field:

- **Pricing Strategy** → Pricing Strategy Template, filtered by Purchase Receipt company and enabled status.

On continue, set Frappe route options for:

- Company;
- Pricing Strategy; and
- Purchase Receipt;

Then route to `query-report/Pricing Strategy Analysis`.

## Permissions and errors

- Respect normal Purchase Receipt and report permissions.
- Do not bypass DocType permissions or workflow state.
- Show a clear validation message when the receipt is invalid, has no stock Items, or its company conflicts with the report Company.
- Do not silently fall back to unrelated Items.

## Files

- `worldshading/hooks.py`
- `worldshading/public/js/purchase_receipt.js` (new)
- `worldshading/worldshading/report/pricing_strategy_analysis/pricing_strategy_analysis.js`
- `worldshading/worldshading/report/pricing_strategy_analysis/pricing_strategy_analysis.py`
- focused Python and JavaScript test files
- `worldshading/Documentation/pricing_strategy_analysis.md`

## Compatibility and deployment

- ERPNext/Frappe v12 compatible JavaScript and Python only.
- No core ERPNext modifications.
- No schema changes and no migration.
- Implementation work must not run `bench test`, `bench migrate`, restart or cache-clear commands.
- The new `doctype_js` hook becomes active through the site's normal approved deployment/reload process; this task will not perform that production operation.

## Rollback

Remove the Purchase Receipt `doctype_js` hook and client file, then remove the Purchase Receipt report filter and server-side scope expansion. Existing Prepared Reports and pricing business records remain untouched.
