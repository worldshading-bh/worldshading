# Pricing Strategy Analysis — Functional and Technical Guide

Last reviewed against the implementation on 28 September 2026.

This document explains the World Shading pricing workflow from source data to the final Item Price and Pricing Rule records. The application code is authoritative if this guide and the live implementation ever differ.

## 1. Purpose

Pricing Strategy Analysis provides a repeatable way to:

- calculate selling prices from an approved cost basis;
- allocate indirect expenses to each sold item;
- propose Regular, B2B, and quantity-tier prices;
- compare proposed prices with current Item Prices;
- create or update Item Prices in bulk;
- create or update quantity-based Pricing Rules in bulk; and
- retain a link from every generated record to the exact Prepared Report used for the decision.

It is an analysis and controlled-update tool. It does not change prices simply by running the report. A user must open the appropriate update preview, review the selected rows, and confirm the operation.

## 2. Main implementation files

| Purpose | File |
|---|---|
| Report calculations and update APIs | `worldshading/report/pricing_strategy_analysis/pricing_strategy_analysis.py` |
| Report filters, views, tooltips, previews, and buttons | `worldshading/report/pricing_strategy_analysis/pricing_strategy_analysis.js` |
| Report definition and roles | `worldshading/report/pricing_strategy_analysis/pricing_strategy_analysis.json` |
| Pricing strategy master | `worldshading/doctype/pricing_strategy_template/pricing_strategy_template.json` |
| Strategy validation | `worldshading/doctype/pricing_strategy_template/pricing_strategy_template.py` |
| Quantity tier child table | `worldshading/doctype/pricing_strategy_tier/pricing_strategy_tier.json` |
| Packed-item-aware sales source | `worldshading/report/item_wise_sales_register_ws/` |

All customization is in the `worldshading` custom app and is compatible with ERPNext/Frappe v12.

## 3. Pricing Strategy Template

Employees reuse a Pricing Strategy Template instead of entering commercial assumptions each time.

The template controls:

- company and whether the strategy is enabled/default;
- whether indirect expense is included or excluded;
- indirect expense account;
- VAT percentage;
- Regular Price List and markup percentage;
- optional B2B Price List and markup percentage; and
- optional quantity pricing tiers, each with minimum quantity, maximum quantity, and markup percentage.

If the B2B Price List is blank, B2B pricing is treated as disabled. A separate enable checkbox is unnecessary.

The quantity tiers are intended for Pricing Rules. Their ranges must be clear and non-overlapping. The final tier may have no maximum quantity.

### Report cost basis

Cost Basis is selected directly in the report and defaults to **Latest Valuation Rate**. It is not stored in the Pricing Strategy Template, so users can compare the same strategy with either cost basis.

| Cost basis | Meaning | Recommended use |
|---|---|---|
| Current Valuation Rate | The present accounting value per unit of stock. It reflects the system's valuation method and the history of receipts, stock movements, and landed-cost adjustments that remain represented in current stock. | Stable everyday pricing based on the current value of inventory. |
| Latest Valuation Rate | The final valuation rate of the latest incoming purchase transaction, after applicable landed-cost changes. The source can be a submitted Purchase Receipt or a stock-updating Purchase Invoice. | Pricing against the most recently landed batch cost. |

These are intentionally the only two cost options. A raw Purchase Invoice rate is not used as a substitute for landed cost because it may omit freight, duty, and other landed-cost adjustments.

### Pricing Group setup on Item

Pricing Group membership is stored on Item as the single source of truth. Create this Custom Field manually before using grouped pricing:

| Property | Value |
|---|---|
| DocType | Item |
| Label | Pricing Group |
| Fieldname | `pricing_group` |
| Field Type | Link |
| Options | Pricing Group |
| Insert After | Item Group |
| In Standard Filter | Yes |
| No Copy | Yes |

An Item may belong to one Pricing Group. Items without this value continue to use their individual pricing recommendations.

## 4. Report filters and Prepared Report behavior

Visible report filters are arranged as follows:

1. Pricing Group, Company, Pricing Strategy, From Date, To Date
2. Purchase Receipt, Item Group, Item, Stock UOM, Brand
3. Warehouse, Cost Basis, Exclude Items Without Sales

Choosing a configured Pricing Group automatically fills its Company, Item Group and Pricing Strategy. Choosing the Pricing Strategy directly still supports standalone analysis without a Pricing Group. Cost Basis remains independently editable and is stored with the Prepared Report. Other strategy-controlled settings are also stored with the Prepared Report even though they are not shown as separate editable filters.

The report is a Prepared Report. Each result therefore represents a saved snapshot of:

- the filters;
- the selected strategy settings;
- the calculated rows; and
- the report generation time.

Use **Rebuild** when current transactions, stock valuation, strategy settings, or prices have changed. **Refresh** displays the existing saved result and does not recalculate it.

When a link to a saved Prepared Report is opened, the report restores its exact saved filters first, including the Pricing Strategy, before displaying the result. This prevents strategy defaults from replacing the historical settings.

## 5. Data sources

| Result | Primary source |
|---|---|
| Item identity, Item Group, Brand, Stock UOM | Item |
| Available quantity and Current Valuation Rate | Bin/current stock valuation, with Stock Ledger fallback where required |
| Latest Valuation Rate | Latest eligible submitted Purchase Receipt or stock-updating Purchase Invoice, including the final valuation effect of landed cost |
| Current Regular and B2B prices | Item Price for the selected price lists |
| Sales quantity, item sales value, last sold rate, average sold rate | Packed-item-aware Item-wise Sales aggregation |
| Company and item net COGS | Net outgoing stock value from submitted Delivery Notes and stock-updating Sales Invoices, including returns |
| Indirect expense | Submitted GL Entries under the selected expense account and its child accounts |

Period Closing Voucher entries are excluded from the indirect-expense total.

## 6. Packed items and sales quantities

Packed items are essential because project sales often record the physical rolls or components in the Sales Invoice Packed Items table rather than as independent invoice lines.

The sales aggregation therefore examines both:

- Sales Invoice Item; and
- Sales Invoice Packed Item.

This provides the correct per-item quantity and item sales analysis. COGS comes from the corresponding sales Stock Ledger movements, so physical packed Items retain their own stock cost.

In short:

- use sales Stock Ledger movements for company and item net COGS;
- use both normal and packed-item rows to identify which items and quantities were sold; and
- do not add a packed item's value to the invoice total a second time.

## 7. Indirect expense allocation

The report first calculates one company-wide expense ratio for the selected period:

```text
Indirect Expense Ratio = Indirect Expense Total / Company Net COGS
```

For each item with sales in that period:

```text
Allocated Item Expense = Item Net COGS × Indirect Expense Ratio
Expense per Unit       = Allocated Item Expense / Item Sales Quantity
Fully Loaded Cost      = Base Cost + Expense per Unit
```

Example:

```text
Company expense ratio      = 25.856%
Item net COGS              = BHD 10,000.000
Allocated item expense     = 10,000.000 × 25.856%
                           = BHD 2,585.600
Item sales quantity        = 249
Expense per unit           = 2,585.600 / 249
                           = BHD 10.384
```

The expense ratio comes from the selected account's company-wide net indirect-expense total divided by company-wide net Cost of Goods Sold (COGS). Each item's actual-period net COGS is multiplied by that ratio, then divided by its sales quantity to calculate Expense / Unit.

The tooltip on Expense / Unit displays the actual values used for the row.

If an item has no usable period COGS but has a valid selected Base Cost, the fallback is:

```text
Expense per Unit = Base Cost × Indirect Expense Ratio
```

The row identifies this as **Base Cost fallback**. If neither basis exists, the report leaves the expense unavailable and records a warning.

When the strategy excludes expense, the report may still display the expense analysis, but the pricing calculation uses Base Cost rather than Fully Loaded Cost.

## 8. Price calculation and rounding

For each Regular, B2B, or tier level:

```text
Raw Net Price   = Pricing Cost × (1 + Markup % / 100)
Raw Gross Price = Raw Net Price × (1 + VAT % / 100)
Rounded Gross   = Raw Gross Price rounded upward to the applicable increment
Final Net Price = Rounded Gross / (1 + VAT % / 100)
```

The report always rounds the VAT-inclusive gross price upward:

| Raw gross price | Increment |
|---:|---:|
| Below BHD 0.100 | BHD 0.005 |
| BHD 0.100 to below 30.000 | BHD 0.100 |
| BHD 30.000 to below 100.000 | BHD 0.500 |
| BHD 100.000 to below 1,000.000 | BHD 1.000 |
| BHD 1,000.000 and above | BHD 10.000 |

Example with expense excluded:

```text
Base cost                   = BHD 41.270
Regular markup              = 43%
Raw net price               = 41.270 × 1.43 = BHD 59.0161
VAT at 10%                  = BHD 64.91771 gross
Rounded gross price         = BHD 65.000
Strategy Regular Net        = 65.000 / 1.10 = BHD 59.091
```

This explains why the recommended net price can differ slightly from simply multiplying cost by the template markup. Rounding is applied to the VAT-inclusive price and the final net price is then derived from it.

## 9. Markup, margin, discount, and averages

These terms are not interchangeable:

```text
Actual Markup % = (Net Price - Pricing Cost) / Pricing Cost × 100
Gross Margin %  = (Net Price - Pricing Cost) / Net Price × 100
Discount %      = (Reference Price - Lower Price) / Reference Price × 100
```

- Markup measures profit relative to cost.
- Gross margin measures profit relative to the selling price.
- B2B discount compares B2B net price with Regular net price.
- Tier discount compares the tier net price with B2B net price when B2B is configured; otherwise it compares with Regular net price.

Average Actual Markup, Average Gross Margin, and Average Discount are simple arithmetic averages of the configured Regular, B2B, and tier levels that apply to the row. They summarize the proposed price structure; they are not weighted by historical sales.

## 10. Report views and presentation

**Full Analysis View** displays source costs, expenses, historical sales, current prices, every calculated price level, changes, margins, discounts, averages, suggested action, and warnings.

**Simple Price View** hides the calculation detail without rebuilding the report. It shows the key price-decision columns:

- Item Code, Item Name, and Stock UOM;
- Current Regular Price and Strategy Regular Net;
- Current B2B Price and Strategy B2B Net; and
- recommended net price for every quantity tier.

The report also provides:

- related column groups with consistent colors;
- sticky Item Code and Item Name columns;
- the same row-highlight color used in Purchase Plan; and
- tooltips for calculation-heavy columns. Recommended-price tooltips include the VAT-inclusive gross price.

### Pricing Groups

A Pricing Group keeps related variants, such as different colours of the same material, on one shared selling-price structure.

The Pricing Group master is a normal, non-tree document with:

- Pricing Group Name;
- required Company;
- required Item Group;
- required enabled Pricing Strategy belonging to that Company;
- optional Description; and
- Disabled status.

Item's `pricing_group` Link is the single source of membership. Items without a Pricing Group continue to use their individual recommendations.

The Pricing Group form shows an automatic read-only **Included Items** table with Item Code, Item Name, Item Group, Brand, Stock UOM and status. It also provides a **View Items** button. This is a live view of Item records and is not a second membership table.

Item Group membership is enforced. An Item can use a Pricing Group only when its Item Group matches the group configuration, and a Pricing Group cannot be changed to another Item Group while incompatible Items remain assigned. Disabled or incompletely configured Pricing Groups cannot receive new Item assignments.

Existing Pricing Groups are not filled automatically. After deployment, open each group and set Company, Item Group and Pricing Strategy. Until those fields are completed, saving an assigned Item or using that group as the report configuration shows a clear validation message.

For grouped Items, the report calculates every Item normally and calculates its share of the group's Sales Qty:

```text
Sales Contribution % = Item Sales Qty / Total Pricing Group Sales Qty * 100
```

The member with the highest Sales Qty among Items that have a complete valid Regular, B2B and quantity-tier recommendation is the reference Item. Its recommendations become the shared group prices. A member without cost or complete recommendations is skipped as a reference but remains part of the group and receives the shared prices. If the highest-selling member is invalid, the next-highest-selling valid member is used. If every member has zero sales, the valid member with the highest Strategy Regular Net is the fallback reference Item. The group is blocked only when no member can produce a complete valid price structure.

Each member row continues to show its own recommendation. The reference Item row is highlighted light red. A bold **Group Strategy Price** label is rendered in the Item Code column after the group's final Item; the row contains only the reference Item's Base Cost and strategy Regular, B2B and quantity-tier Net prices. Its tooltip identifies the source Item Code and whether it was selected by highest Sales Qty or the zero-sales highest-price fallback. The same compact presentation is used in Simple Price View; separate Group Regular, Group B2B and group-tier columns are not displayed. Simple Price View also retains Base Cost, Expense / Unit and Cost + Expense. Empty summary-row percentage fields are rendered blank instead of `0%`.

The visible report omits the technical Group Status, Expense Basis, VAT-inclusive price, individual Actual Markup, absolute Regular price change, Suggested Action and Warnings columns. The underlying values and update validations remain available internally. VAT-inclusive prices and expense allocation details remain available through tooltips.

The **Fully Loaded Cost** display label is **Cost + Expense**; its calculation is unchanged. The separate Item Name column is omitted because the Item Code Link already displays the descriptive name. Row number and Item Code use the Purchase Plan-style sticky-column behavior, including dynamic resize offsets, synchronized header/footer movement, preserved horizontal scrolling and empty-result layout handling.

Group Status can be:

- **Ready** — every active stock Item in the group is present and valid;
- **Different Current Prices** — the group is valid and its existing prices can be aligned;
- **Incomplete Group** — at least one active member is absent from the Prepared Report or update selection;
- **Missing Cost** — no group member can produce every required recommendation; or
- **Disabled Group** — the Pricing Group master is disabled.

Only Ready and Different Current Prices groups can be updated. The report never silently updates part of a group. A group that crosses the first-50-Items boundary is blocked rather than split.

## 11. Updating Item Prices

The **Update Item Price** button works from the saved Prepared Report result, not from unsaved browser data.

Workflow:

1. The first 50 eligible items from the report result are considered.
2. Rows without a valid recommended price are skipped and summarized by count.
3. A preview displays the proposed Regular and, when configured, B2B changes.
4. The user may remove exact rows from the preview.
5. The user confirms the remaining changes.
6. Existing Item Prices are updated; missing Item Prices are created.

The limit is **50 items**, not 50 Item Price records. With both Regular and B2B enabled, 50 items can produce up to 100 Item Price creates/updates.

Safeguards include:

- permission checks;
- explicit confirmation;
- validation against the saved preview;
- concurrent-change checks;
- skipping items with missing cost or invalid recommendations; and
- compact counts for skipped rows instead of a large warning panel.

Each saved Item Price receives the Prepared Report link and an audit comment.

For a complete Pricing Group, every member uses the shared group price for the applicable Regular or B2B Price List. The preview shows the member recommendation and the shared group price. Keeping or removing grouped rows must be done for the complete group; the server rechecks group membership before saving.

## 12. Updating Pricing Rules

The **Update Pricing Rule** button creates quantity-based percentage-discount rules. It does not create one rule per item unless the user explicitly chooses Separate by Item.

The user first selects up to 50 eligible items and may remove unwanted rows. The review step shows every tier and permits the final percentage to be edited or a tier to be omitted.

### Rule creation modes

| Mode | Result |
|---|---|
| Combined | One Pricing Rule per tier for all selected items. The suggested final discount is the arithmetic average for that tier and remains editable. |
| Separate by Item | One Pricing Rule per selected item per tier, retaining each item's exact discount. |
| Group by Same Discount | One Pricing Rule per tier for each group of items sharing the same calculated discount. |

Pricing Rules intentionally do not specify a Price List. The discount rule can therefore apply to an eligible transaction whether the customer is using the Regular or B2B price list.

### Mixed conditions

**Mixed Conditions** combines quantities from different selected items to reach a tier quantity. For example, quantities 3 and 2 from two eligible items can together satisfy a tier minimum of 5. Mixed Conditions is unavailable for Separate by Item mode because each rule contains only one item.

### Naming

The editable Rule Set Name defaults in this priority:

1. Item Group
2. Brand
3. Item
4. `Selected Items`

Only the middle Rule Set Name is edited. The report adds the standard prefix and tier automatically:

```text
Combined:              PSA - {Rule Set Name} - Tier 1
Separate by Item:      PSA - {Rule Set Name} - {Item Code} - Tier 1
Group by Same Discount: PSA - {Rule Set Name} - Tier 1 - Group 1
```

Using the same Rule Set Name and creation mode again updates matching generated rules rather than creating random duplicate names.

Each Pricing Rule receives the Prepared Report link and an audit comment.

For grouped Items, the report creates one Pricing Rule per Pricing Group per tier. The rule contains every active group member and is named:

```text
PSA - {Pricing Group} - Tier {N}
```

Its discount comes directly from the shared group reference price and shared group tier price; it is not an average of member discounts. Different Pricing Groups remain separate even if their percentages happen to match. Mixed Conditions allows quantities from different members of that group to combine toward the tier minimum.

## 13. Required custom fields

Create the following Custom Field on both **Item Price** and **Pricing Rule**:

| Setting | Value |
|---|---|
| Label | Pricing Prepared Report |
| Fieldname | `pricing_prepared_report` |
| Field Type | Link |
| Options | Prepared Report |
| Read Only | Yes |
| No Copy | Yes |
| In Standard Filter | Yes |

For Pricing Rule, inserting after Rule Description is suitable. The report checks for the field before assigning it, preserving compatibility while the field is being deployed.

The link is important for auditability and retention. It lets a user open the exact Prepared Report that produced the price or rule, including its saved strategy and filters.

## 14. Permissions, audit, and production safety

- Report access follows the roles configured in the report definition.
- Creating or updating Item Price and Pricing Rule records also requires the native DocType permission.
- Native validation, workflow state, and document permissions are not bypassed.
- The update actions save records normally; they do not use direct database writes as a shortcut.
- Comments and Prepared Report links provide the audit trail.
- Running or rebuilding the report alone never changes Item Price or Pricing Rule.

### Three-day pricing announcements

Each successful **Update Item Price** or **Update Pricing Rule** operation that
creates or changes records automatically creates one public **Note**. All changed
records appear together in a scrollable popup when staff next open or reload Desk.
The popup repeats on subsequent Desk loads until its expiry; it is not a realtime
broadcast to sessions that are already open.

### Popup audience roles

Note has a **Popup Audience Roles** Table MultiSelect field, visible when
**Notify users with a popup when they log in** is enabled. Roles appear as
removable tags. It reuses the existing custom **Workflow Assignment Role** child
DocType and its required Role field; existing child rows and selected roles are
preserved when changing from the original Table display.

- Empty table: keep the existing popup audience (everyone).
- One or more roles: show the popup only to users with at least one selected role.
- The filter applies to all login Notes, including manually created Notes and
  automatic pricing announcements. It is independent of the urgent PO popup.
- Public Note access is unchanged: excluded users can still open a public Note.
- Existing expiry and repeat-login settings remain in effect. Role changes are
  evaluated on the next Desk load; already-open popups are not revoked.
- Frappe's normal role resolution applies, including Administrator's built-in
  all-role behavior.

Open the Note, choose Edit, search and select the desired Popup Audience Roles, and
save. No automatic pricing audience has been selected yet; new pricing Notes
start with an empty table and can be configured individually.

Implementation: `api/note_popup_audience.py:filter_note_popups`, registered through
`extend_bootinfo`, filters the native popup list after its expiry/seen checks.
It queries only child rows whose parenttype is Note and parentfield is
`custom_popup_audience_roles`, so role rows on other documents are not included.
`setup_note_popup_audience` installs the compatible Custom Field using normal
Frappe APIs. Deployment created the field and refreshed the single `app_hooks`
cache entry; no restart, migration, bench tests or broad cache clearing was run.

Rollback: remove the custom `extend_bootinfo` registration and hide the Note
Custom Field, retaining its selections. Do not delete the reused child DocType
or alter public Note permissions.

### Announcement content

Item Price announcements show **Item**, **Item Name**, **UOM**, and the changed
price lists as adjacent net-price columns, with Regular before B2B. Each item/UOM
appears once. Batches containing only one price list show only that price column;
when both columns exist but only one price changed for an item, the other shows
**Not changed**. This does not fetch or imply an unchanged current price.
Different UOMs remain separate rows. Currency, old price, approval status and the
updater/report preamble are omitted from this popup. The popup title is simply
**Prices Updated**; the stored Note retains its unique title. An announcement
does not approve a price or change its workflow. Pricing Rule announcements show
the saved rules, item codes, quantity ranges, final discounts, enabled status and
Mixed Conditions. Costs, margins and expense calculations are not published.

The Note is public to Desk users across companies. Native document metadata and
the report's existing audit comments retain update provenance. The Pricing Rule
popup retains its Prepared Report identifier, which does not grant report access.
Public announcements must only be used for selling-price information suitable for
that audience.

Expiry follows the existing production-item announcement: the site update date
plus three days. An update on 4 October appears on 4, 5 and 6 October and expires
at the start of 7 October. This is a calendar-date expiry, not exactly 72 hours.
Each later operation creates a fresh Note with its own expiry; several recent
announcements can coexist.

Unchanged-only updates and previews create no Note. Pricing operators need normal
Note create permission. Note creation is part of the pricing transaction: if it
fails, the request fails and pricing changes roll back; its preview token is not
consumed. No permission bypass or explicit database commit is used.

This automation covers only the two report buttons, not manual edits or imports.
The separate `Auto Note Creation - Notify users about the new item` Server Script
is unchanged and can also announce a newly activated production item.

Implementation: `api/pricing_update_notifications.py`, the report's existing
Item Price and bulk Pricing Rule execution methods, and
`public/js/pricing_update_notifications.js` registered in `hooks.py`. The small
Desk guard prevents this Frappe v12 version from reopening generated repeat-login
Notes immediately on dismissal. It tracks display only in the current browser
load, leaves persisted Seen By records untouched, and does not alter other Notes.
Item Price popups use a 760px desktop dialog capped at the viewport width minus
24px. The table can scroll horizontally on small screens. Later unrelated
messages return to the standard dialog width.
The pricing wrapper also enables native `msgprint` wide mode so Frappe removes
its narrow-message class. After a script update, hard-refresh Desk to load the
current asset; refreshing just the Note form may retain the previous wrapper.
No schema change, new DocType or client bundle build is required. Running web
workers must load the updated Python code and hooks through the site's normal
authorized deployment process; saving the files alone does not verify activation
in already-running workers. Verify the new script is included on a fresh Desk
load before using the update buttons. No restart or cache clearing was performed
as part of this change.

To roll back, remove the report integration, notification helper, and added Desk
asset/hook entry only. Under
separate authorization, generated Notes can have their login-notification flags
disabled. Do not undo saved prices or delete existing production-item Notes as
part of notification rollback.

## 15. Verification checklist

Before a bulk update:

1. Confirm the Pricing Strategy Template, VAT, markups, tiers, and expense account.
2. Confirm the report dates, company, warehouse, Item Group, Item, Stock UOM, and Brand filters.
3. Rebuild the Prepared Report after changing any input.
4. Spot-check Base Cost against Stock Ledger/current valuation or the latest incoming valuation transaction.
5. Spot-check indirect expense against the General Ledger.
6. Spot-check company net COGS against sales Stock Ledger movements.
7. Spot-check item quantity and net COGS, including packed items.
8. Check the gross price shown in the recommended-price tooltip.
9. Review skipped counts and remove unwanted rows from the update preview.
10. After confirmation, verify the created Item Prices or Pricing Rules and open their Pricing Prepared Report links.

### Purchase Receipt workflow

Use **Update Pricing** on a submitted, non-return Purchase Receipt when newly received stock should be reviewed. Select an enabled Pricing Strategy, then the button opens Pricing Strategy Analysis with the Company, Pricing Strategy and Purchase Receipt already selected.

The Purchase Receipt scope includes each active stock Item on the receipt. When one of those Items belongs to a Pricing Group, every active stock Item in that group is included so the group can be reviewed and updated together. Duplicate receipt rows are included only once, and ungrouped receipt Items remain in the report. Item, Item Group, Pricing Group, Brand and Stock UOM filters do not narrow this authoritative receipt scope.

When a selected Purchase Receipt contains no active stock Items, the report shows a friendly warning and clears the filter. This normal business condition does not create a failed Prepared Report or Error Log.

The receipt warehouse is deliberately not copied into the report. Select a Warehouse manually only when warehouse-specific stock values are required. Opening or rebuilding the report does not update prices; review the recommendations and use the existing update previews before confirming any Item Price or Pricing Rule changes.

## 16. Common troubleshooting

| Symptom | Explanation/action |
|---|---|
| Refresh shows an older value | Prepared Reports are snapshots. Use Rebuild to recalculate. |
| Recommended prices are blank | The item normally has no valid Base Cost. Inspect the Warnings column and valuation source. |
| Expense / Unit is unexpectedly high | Check the indirect-expense account scope, GL total, company net COGS, item net COGS, and sales quantity shown in the tooltip. |
| An item is skipped during an update | It has no valid recommendation for that operation, or its saved result no longer passes update validation. |
| B2B Item Price is not offered | The selected strategy has no B2B Price List. |
| A tier discount differs between items | Their costs, rounding effects, or reference prices differ. Use Combined for an editable average, Separate by Item for exact item discounts, or Group by Same Discount. |
| Prepared Report link opens with wrong/blank strategy | Ensure the current report JavaScript and backend are deployed; the saved-filter restoration must run before strategy defaults. |
| More than 50 Item Price rows appear | The limit is 50 items. Each item can generate both a Regular and a B2B Item Price row. |
| A Purchase Receipt cannot be selected | Only submitted, non-return receipts for the selected Company are valid. Confirm the Company and receipt status. |
| Purchase Receipt is cleared with a warning | All receipt Items are disabled or have Maintain Stock turned off, so valuation-based pricing cannot be calculated. |
| Receipt results include Items not shown on the receipt | Active Pricing Group siblings are intentionally added so a complete group can be reviewed together. |

## 17. Deployment notes

DocType definition changes should be loaded using the ERPNext v12-compatible command format:

```bash
bench --site erp.worldshading.com reload-doc worldshading doctype pricing_strategy_template
```

The `reload-doc` subcommand in this environment does not accept `--force` after the command or a trailing `1`. When force is required, use the global option before `reload-doc`, as shown below.

For Pricing Group deployment:

1. Load the new master DocType:

```bash
bench --site erp.worldshading.com reload-doc worldshading doctype pricing_group
```

If the normal load does not import the definition because of an existing timestamp, place the global Frappe v12 force option before the command:

```bash
bench --site erp.worldshading.com --force reload-doc worldshading doctype pricing_group
```

2. Confirm the Pricing Group list opens with Company, Item Group, Pricing Strategy and Included Items.
3. Create the Item Custom Field from **Pricing Group setup on Item** above if it does not already exist.
4. Open every existing Pricing Group and manually set Company, Item Group and Pricing Strategy.
5. Confirm Included Items shows the current Item assignments and correct any Item Group mismatch.
6. Select the Pricing Group in Pricing Strategy Analysis and confirm Company, Item Group and Pricing Strategy fill automatically before rebuilding.

The Pricing Strategy Analysis report JSON was not changed for this feature, so a report `reload-doc` is not required.

The Purchase Receipt button is registered through the custom app's `doctype_js` hook. Its activation should follow the normal approved asset/deployment process for this production site. No schema reload or migration is required for this client-script addition.

Rollback must preserve Pricing Group masters and the Item field until dependencies are reviewed. Item Price and Pricing Rule business records already created from the report must never be deleted automatically.

Do not run `bench migrate`, `bench test`, restart services, or clear production caches for this feature.
