# Purchase Plan Report — Functional and Technical Handoff

Last reviewed against the implementation on 19 August 2026.

This document is the primary handoff for the **Purchase Plan** Script Report. It
describes current behavior, including decisions that are not obvious from the column
names. When this document and the code disagree, the current code is authoritative and
this document must be updated in the same release.

## 1. Purpose

Purchase Plan estimates how much of each purchasing item is needed by combining:

- historical sales in a selected period;
- an optional allowance for sales missed while stock was unavailable;
- optional conversion of repacked-item demand back to the source item actually bought;
- a growth percentage;
- current stock across all warehouses;
- outstanding submitted Purchase Orders;
- lead time and minimum-stock reserves; and
- the existing Item Reorder level.

It also shows the current default selling price, historical/configured Item Suppliers
ranked by their latest comparable cost, and the least supplier cost.

It also provides two controlled actions:

1. create a draft Request for Quotation from items that need purchasing; and
2. update Item Reorder rows for a selected Item Group in a background job.

This is a planning aid. It does not submit an RFQ, Purchase Order, Material Request or
Stock Entry automatically.

## 2. Files and report registration

| Concern | File |
|---|---|
| Calculations, bulk queries, RFQ mapping and reorder update | `worldshading/worldshading/report/purchase_plan/purchase_plan.py` |
| Filters, dialogs, sticky columns, formatting and row highlighting | `worldshading/worldshading/report/purchase_plan/purchase_plan.js` |
| Report registration, roles and prepared-report setting | `worldshading/worldshading/report/purchase_plan/purchase_plan.json` |
| Historical business references (advanced clone/server-local; intentionally excluded from the Git release) | `worldshading/Documentation/purchase plan/*.xlsx` |
| Safe deployment from the advanced clone | `worldshading/Documentation/safe_feature_release.md` |

The report is a standard Script Report over Item. It is available to **Accounts
Manager** and **Purchase User**. Prepared Report is enabled; users must use **Rebuild**
when current stock, sales or orders are required.

Target compatibility is ERPNext/Frappe v12 and Python 3.6.

## 3. Eligibility and filters

Only Items with `is_stock_item = 1` and `is_fixed_asset = 0` are eligible. Disabled Item
behavior follows Frappe's Item queries; do not assume another explicit disabled filter
exists in every report path.

| Filter | Current behavior |
|---|---|
| Start Date / End Date | Required. Start cannot exceed End. End cannot exceed today. |
| Supplier | Includes items found on submitted Purchase Invoices for that Supplier. |
| Supplier Group | Includes Suppliers in the selected group and all descendant groups, then items found on their submitted Purchase Invoices. |
| Supplier Country | Includes Suppliers with that country, then items found on their submitted Purchase Invoices. |
| Item | Exact Item. It must also satisfy every active Supplier filter. |
| Disabled Items Only | Unchecked returns only enabled Items. Checked returns only disabled Items. Disabled Items remain unavailable to the RFQ and Item Reorder actions. |
| Parent Item Groups | Multi-select. Includes every descendant Item Group. |
| Child Item Groups | Multi-select of enabled leaf groups. Disabled groups are excluded. If parent groups are selected, choices are limited to their descendants. |
| Item Purchase Country | Exact match against Item `purchased_from`. |
| Item Country of Origin | Exact match against Item `country_of_origin`. |
| How Many Months to Arrive? | Lead time used to calculate demand before replenishment arrives. |
| Percentage | Growth/safety percentage added to adjusted historical demand. |
| Min Stock for How Many Months? | Number of average-sales months in one minimum-stock reserve. The order formula deliberately subtracts this reserve twice. |
| Include Repack to Parent | Converts target/repacked demand and usable stock back to purchasing/source Items. |
| Include Out of Stock Sales | Estimates missed demand for sufficiently active items. |

Months to Arrive, Percentage and Min Stock Months use Data controls so valid values are
shown without forced trailing zeros. The server requires each value to be present,
numeric and finite before running any calculations; invalid text, `NaN` and infinite
values produce a readable validation message.

### Supplier-filter meaning

Supplier filters do **not** read Item Default Supplier. They identify eligible Suppliers,
then select distinct Item Codes appearing on their submitted Purchase Invoice Items.
Consequently, an item never previously invoiced by that Supplier is not returned.

## 4. Date semantics

Sales quantity and invoice count currently use the child row's `creation` timestamp,
not Sales Invoice `posting_date`. Working days also use submitted Sales Invoice
`creation` dates. This is intentional current behavior and must not be silently changed;
a move to posting dates requires business confirmation and comparison testing.

The report interval is inclusive for sales and stock-day traversal. However, planning
months use:

```text
date_diff(End Date, Start Date) / 30
```

and are zero when the difference is under 30 days. The value is later converted to an
integer for monthly calculations. Short intervals therefore need careful review.

One implementation detail needs regression coverage: the distinct-invoice-count SQL
passes date-only values directly to a Datetime `BETWEEN` comparison. MariaDB can treat
End Date as midnight, so invoices created later on End Date may be omitted from the
count even when sales aggregation includes them. Do not change this casually, but fix
it together with tests if the count and Direct Sales disagree on an end-boundary day.

## 5. Core data sources

| Value | Source and rules |
|---|---|
| Direct Sales | Submitted Sales Invoice Item quantity plus submitted Sales-Invoice Packed Item quantity, grouped by Item. |
| No. of Sales Invoices | Distinct parent Sales Invoices across Sales Invoice Item and Packed Item rows. |
| Available Quantity | Sum of `Bin.actual_qty` across all warehouses. |
| On Purchase | Remaining stock quantity on submitted, open Purchase Orders: `(qty - received_qty) * conversion_factor`; excludes supplier-delivered rows. |
| On Purchase PO | Names of the Purchase Orders included in On Purchase. |
| Existing Re-order Level | Purchase-type Item Reorder level for `All Warehouses - <company abbreviation>`. |
| Re-order Quantity | Sum of Purchase-type Item Reorder quantities for the item. |
| Last Sale Date | Latest negative Stock Ledger movement from Sales Invoice or Delivery Note. |
| Last Purchase Date | Latest positive Stock Ledger movement from Purchase Invoice or Purchase Receipt. |
| Selling Price | Current valid Item Price from the Selling Settings default Price List. If none exists, Item `standard_rate` is used for compatibility with the legacy Regular Price setup. |
| Item Suppliers | Enabled Suppliers configured in Item Supplier or found on submitted Purchase Invoices for the selected Company. |
| Last Purchase Cost | Cost on the Item's latest submitted Purchase Invoice, in Company currency per stock UOM. |

Last purchase/sale dates are ledger dates over all history, not restricted to the report
period. This makes receipt-only and delivery-note-only stock movements visible.

### Supplier cost and ranking

For each Item and Supplier, the report takes the latest submitted Purchase Invoice row
with a valid comparable cost for the selected/default Company and calculates:

```text
Comparable Supplier Cost = base_net_rate / conversion_factor
```

This uses Company currency, includes the applied purchase discount and normalizes the
transaction UOM to stock UOM. Suppliers are sorted by each Supplier's latest cost. The
cheapest Supplier is green, the second cheapest is yellow, and all remaining priced
Suppliers are red. Active configured Suppliers without purchase history are placed after
priced Suppliers and shown in grey. Hovering a Supplier shows its latest cost, Purchase
Invoice and posting date. Last Purchase Cost is the cost from the latest submitted
Purchase Invoice for the Item overall, so it can differ from the green Supplier's cost.

The August 2026 demo has no Item Supplier rows, so historical submitted Purchase
Invoices are presently the effective Supplier source. Both sources remain supported.

### Selling price fallback

The default selling Price List comes from Selling Settings. Only currently valid Item
Prices for the Item's stock UOM, or with no UOM restriction, are eligible. The August
2026 demo uses Regular Price in BHD but has no Item Price rows; its selling values are
stored in Item `standard_rate`. The report falls back to `standard_rate` only when no
applicable default-list Item Price exists.

## 6. Formula glossary

For each purchasing item, define:

```text
D = Direct Sales
O = Estimated Out-of-Stock Sales Qty (or 0)
R = Converted Repack Sales (or 0)
P = Percentage / 100
T = integer planning months in the report period
A = Available Quantity + usable Converted Repack Available
PO = On Purchase
L = How Many Months to Arrive
M = Min Stock for How Many Months
RL = existing Re-order Level
```

Current formulas are:

```text
Adjusted Sales          = D + O + R
Expected Total Sale     = Adjusted Sales * (1 + P)
Monthly Sales           = integer(Expected Total Sale) / integer(T), or 0
Annual Sales            = Monthly Sales * 12
Period Expected Sales   = Monthly Sales * L
Shortage Happend        = (A + PO) - Period Expected Sales
Min                     = round_half_up(Monthly Sales * M)
Usable Balance          = max(Shortage Happend, 0)
Expected Order Quantity = Usable Balance - Min - Min - RL
Priority Month          = (A + PO) / Monthly Sales, or 0
Available Total Qty     = A + PO
```

### Expected Order Quantity sign convention

- A **negative** value means purchasing is required. Buy its absolute value.
- Zero or a **positive** value means the formula does not request a purchase.
- Create RFQ includes only negative rows and converts them to positive quantities.

Example:

```text
Available after arrival = 40
Min                     = 30
Existing Re-order Level = 10

Expected Order Quantity = 40 - 30 - 30 - 10 = -30
RFQ quantity            = 30
```

### Why negative shortage is not added again

`Shortage Happend` is really the stock balance after lead-time demand:

- positive means stock remains after covering the arrival period;
- negative means stock would already have run out during that period.

Only a positive remainder is usable in the order formula. A negative value becomes zero
through `max(Shortage Happend, 0)`. This avoids adding historical/unrecoverable shortage
again to the future order quantity. Keep the Shortage column for information.

### Double minimum-stock reserve

`Min` is deliberately subtracted twice. With Min Stock Months = 3, the order formula
reserves the equivalent of six months of average sales, in addition to the existing
Item Reorder level. This behavior came from the original planning approach and was
confirmed during the report refinement. Do not simplify it to one reserve without
business approval.

## 7. Out-of-stock estimation

This feature runs only when **Include Out of Stock Sales** is checked.

### Activity threshold

The report calculates average monthly invoice frequency:

```text
completed months = integer(date difference / 30), when at least 30 days
average invoices = distinct Sales Invoice count / completed months
```

If average invoices are `<= 5`, stock-day analysis is skipped, estimated missed sales
remain zero, and the UI shows **N/A**. The threshold is invoice frequency, not quantity.

### Working-day strategy

There is no reliable holiday calendar for this business. A working day is therefore any
calendar date in the period on which at least one submitted Sales Invoice was created.
Fridays or other weekdays are not hardcoded.

For each active item:

1. obtain opening stock from all Stock Ledger Entries before Start Date;
2. aggregate Stock Ledger movement per day across all warehouses;
3. walk every day in the selected range;
4. on inferred working days, count the day as out of stock when balance is `<= 0`;
5. derive in-stock selling days; and
6. estimate missed demand as:

```text
Estimated Out-of-Stock Sales Qty
    = (Direct Sales / In-Stock Working Days) * Out-of-Stock Working Days
```

The estimate is included in Expected Total Sale. If there are no in-stock working days,
the estimate is zero rather than dividing by zero.

## 8. Repack conversion

This feature runs only when **Include Repack to Parent** is checked. It exists because
sales may occur in Meter/Each/repacked Items while purchasing occurs in Roll/Box/source
Items.

The relationship comes from active data in **Repack Production Rule** with `type =
Repack`, not from an Item checkbox. Current validation expects each rule to have at least
one source and exactly one target.

For a rule:

```text
conversion ratio = source quantity / target quantity
source demand     = target demand * conversion ratio
```

Direct target sales and their estimated out-of-stock sales are propagated recursively
to source Items. Cycles, duplicate target mappings and invalid quantities are rejected.
Converted demand is rounded to a whole purchasing unit using half-up rounding (`.5`
rounds upward). **Repack From** retains an explanatory trace with the unrounded values.

Target/repacked Items are removed from the purchasing rows when they lead to source
Items; the report displays the source Items that can actually be bought.

Converted target stock is also propagated to sources. Only the amount useful for the
converted planning requirement is included, preventing excess repacked stock from
overstating purchasing availability.

When repack conversion is enabled, the effective Last Sale Date of a source Item is the
later of its own ledger sale date and its connected target Items' sale dates.

## 9. Performance strategy

The legacy report suffered from repeated document/database work per item. The current
strategy is:

- filter the Item population first;
- fetch sales, invoice counts, stock, orders, ledger dates, reorder rows, selling prices,
  configured Suppliers and historical Supplier costs in bulk;
- aggregate with grouped queries and dictionaries;
- build the repack graph once and propagate values in memory;
- run expensive out-of-stock ledger analysis only when requested and only for active
  items above the invoice-frequency threshold;
- use a Prepared Report so ordinary viewing does not rerun the full calculation; and
- queue bulk Item Reorder writes on the long worker.

Some direct SQL remains because grouped unions, daily ledger aggregation and outstanding
Purchase Order calculations are substantially clearer and faster than per-document
ORM calls. Every SQL query is parameterized.

Do not reintroduce `frappe.get_doc()` inside the main report loop. Per-item writes are
acceptable only in the explicitly queued reorder job.

## 10. Update Item Reorder action

Only report Items with rounded `Min > 0` are eligible. The user must select one Item
Group; selecting a parent includes all descendants. The dialog displays the matching
count before confirmation.

Current dialog defaults are still hardcoded:

```text
Check in (group): All Warehouses - WS
Request for:      Ras Zuwayed - Warehouse - WS
Re-order Qty:     1
Type:             Purchase
```

The values remain editable. If configuration changes, consider moving these defaults to
WS Settings rather than renaming them only in code.

For each selected Item:

- Re-order Level is set to the report's rounded Min;
- Re-order Qty is the manually entered dialog value;
- a row matching warehouse group + request warehouse + Purchase is updated;
- otherwise a new Item Reorder row is appended.

The server revalidates permissions, warehouses, group membership, quantity and maximum
item count. It aborts the entire request before queueing when the same request warehouse
already appears in a conflicting reorder rule. This reflects the ERPNext v12 duplicate
warehouse restriction, which does not distinguish Material Request Type.

## 11. Create RFQ action

The editable **RFQ Order Qty** report column is initialized with the rounded positive
absolute value when Expected Order Quantity is negative, and zero otherwise. Create RFQ
uses this column as its only quantity source, so users can increase or reduce a calculated
requirement, set it to zero to exclude the Item, or enter a quantity for an Item whose
calculated requirement is zero. Positive RFQ quantities use the same red highlight as a
negative Expected Order Quantity. Edited values are temporary report-page values that reset
when the report is refreshed. A maximum of **1000 Items** is allowed. The server revalidates
RFQ permission and Item eligibility.

The RFQ is opened as a new unsaved draft; the user still reviews and saves it.

If Request for Quotation has a custom Small Text field named `report_filter`, Create RFQ
stores a readable snapshot of the active Purchase Plan filters in that field. Filters are
rebuilt server-side from an ordered allowlist; empty values and unchecked options are
omitted, while MultiSelect values are comma-separated. RFQ creation remains compatible
with sites where the custom field has not yet been added.

### Supplier mapping

Country of Purchase follows this priority:

1. Supplier Country report filter;
2. exact selected Supplier's country;
3. Item Purchase Country report filter; and
4. Item Country of Origin report filter.

If an exact Supplier filter is selected:

- the Supplier row is added;
- ERPNext party details provide Contact and Email ID;
- RFQ Supplier Group comes from the Supplier master; and
- the priority above resolves RFQ Country of Purchase.

Without an exact Supplier, Supplier Group comes from the report's Supplier Group filter,
and the same country priority applies without the Supplier-master step.

### Warehouse default

The server compares resolved Country of Purchase with the selected Company's country:

- same country -> `WS Settings.default_local_warehouse`;
- different country -> `WS Settings.default_import_warehouse`;
- no country or invalid/missing setting -> leave the dialog blank.

The configured Warehouse must be enabled, non-group and belong to the selected Company.
The user can always change the default before creating the RFQ.

These two WS Settings fields were created manually in August 2026 and may not be present
in Git-managed schema:

| Fieldname | Label | Type |
|---|---|---|
| `default_local_warehouse` | Default Local Warehouse | Link / Warehouse |
| `default_import_warehouse` | Default Import Warehouse | Link / Warehouse |

Any new site, restored database or automated deployment must verify these fields before
enabling RFQ creation.

## 12. User-interface behavior

- Serial number, Item, Item Name, Unit, Last Purchase Date, Last Sale Date and No. of
  Sales Invoices are sticky while horizontally scrolling.
- Selected Parent and Child Item Group options appear first when their MultiSelect
  dropdowns are opened, making them easier to review or remove.
- Compact labels appear above non-checkbox report filters so their meaning remains
  visible after values replace the placeholders. Equal-height wrappers preserve the
  existing horizontal alignment; checkbox filters use an invisible spacer because their
  text already appears beside the checkbox. Vertical spacing is compact, while horizontal
  margins and padding remain controlled by the standard Frappe theme.
- Duplicate inline placeholders are cleared because the persistent labels already identify
  empty controls. Entered values and MultiSelect status text remain visible normally.
- Sticky offsets are recalculated after column resizing.
- Column movement is disabled because reordered columns would invalidate fixed-index
  sticky CSS.
- Column-option popups are layered above the sticky header and body cells.
- Clicking a data row highlights the entire row; headers and filter rows are excluded.
- Direct Sales, Available Quantity, Available Total Qty, On Purchase, Min, Monthy Sales,
  Annual Sales, Shortage Happend, Expected Order Quantity and Priority Month have
  distinct background colors.
- Shortage Happend uses a light-red background, and negative values are red.
- Negative Expected Order Quantity is red.
- Priority Month displayed as zero is red.
- On Purchase PO values are clickable Purchase Order links.
- Item Suppliers are clickable, ordered by comparable cost and colored green, yellow,
  then red. Suppliers without a comparable cost are red.
- Item Suppliers, Last Purchase Cost and Selling Price are the final three visible columns, in
  that order.
- Total Months In Report and Months To Arrive remain calculation inputs but are not
  displayed as result columns.
- A compact single-row wrapping strip above the results shows Purchase Plan Date,
  integer Total Report Months and the remaining entered filters with shorter readable
  labels, including `Months to Arrive`. It remains hidden until both dates exist; Start
  and End Date are not repeated separately.

### Smart total row

The total row is enabled for additive values only: No. of Sales Invoices, Direct Sales,
out-of-stock and repack demand, Expected Total Sale, Min, Available Quantity, converted
repack availability, On Purchase, Available Total Qty, Monthy Sales, Annual Sales,
Period Expected Sales, Shortage Happend, Re-order Level, Re-order Quantity and Expected
Order Quantity, Selling Price and Last Purchase Cost. Expected Order Quantity totals only
negative values; positive balances are deliberately ignored. Item Suppliers,
percentages, dates, invoice frequency and Priority Month are not totaled. The footer's
Serial number, Item, Item Name, Unit, Last Purchase Date, Last Sale Date and No. of Sales
Invoices cells remain frozen while the remaining totals scroll horizontally.

This styling works around Frappe DataTable v12 behavior. Test sticky overlays, header
clicks, resizing and horizontal scrolling after changing column order or widths in code.

## 13. Prepared-report behavior

The report JSON has `prepared_report = 1`. Results represent the generated snapshot,
not necessarily current database state. **Refresh** can redisplay the snapshot; use
**Rebuild** to calculate current values. This design is a major reason the report is fast
and protects production from repeated heavy ledger calculations.

Selling prices and latest Supplier costs are also part of the prepared snapshot and do
not update until Rebuild.

The smart footer also requires `Report/Purchase Plan.add_total_row = 1`. Frappe v12
deliberately preserves this database value during Report JSON import, so every new or
restored site must verify and enable it explicitly; `reload-doc` alone does not apply
the JSON value.

## 14. Testing checklist

There is currently no dedicated automated Purchase Plan test module. Until one is added,
perform these checks on the clone before release:

1. Generate a small single-Item report and independently verify every core formula.
2. Test parent and child Item Group filters, including descendant behavior.
3. Test Supplier, parent Supplier Group and Supplier Country filters.
4. Confirm assets and non-stock Items are absent.
5. Verify On Purchase against open PO remaining quantity and links.
6. Verify last dates against Stock Ledger entries from both invoice and receipt/delivery.
7. Test out-of-stock estimation above and below the five-invoice average threshold.
8. Test repack demand, available conversion, trace and rounding with a known rule.
9. Verify negative shortage does not reduce Expected Order Quantity twice.
10. Create an RFQ with exact Supplier and without Supplier; check group, country,
    contact, email, warehouse and quantities.
11. Verify local and international warehouse defaults from WS Settings and manual
    override in the dialog.
12. Test Item Reorder selection count on a parent Item Group and inspect one updated and
    one newly created row.
13. Resize columns, click headers, open column-option popups, scroll horizontally and
    confirm sticky alignment and that popups remain above sticky cells.
14. Click different rows and confirm the highlight moves.
15. Rebuild once with broad filters and review execution time and worker/database load.
16. Verify default-list Selling Price and the `standard_rate` fallback with known Items.
17. Verify three-Supplier ordering, colors, latest-cost selection, currency and UOM
    normalization against submitted Purchase Invoices.
18. Confirm Selling Price, Last Purchase Cost and Item Suppliers are shown for all Items
    wherever values exist.
19. Confirm the smart total row excludes positive Expected Order Quantity values and
    leaves non-additive columns blank. Confirm Selling Price and Last Purchase Cost totals, and
    verify that the first seven footer cells remain frozen during horizontal scrolling.
20. Confirm Total Months In Report and Months To Arrive are absent as result columns,
    while changing the arrival filter still changes the existing calculations.
21. Verify the compact filter strip after changing and rebuilding with several filters.
    Confirm the date range uses the user's date format, Total Report Months matches the
    integer 30-day calculation, and duplicate inline placeholders remain cleared.
22. Verify Months to Arrive, Percentage and Min Stock Months reject non-numeric and
    non-finite input with a readable message, while valid decimal values still run.

Syntax checks compatible with this stack:

```bash
node --check worldshading/worldshading/report/purchase_plan/purchase_plan.js
python3.6 -m py_compile worldshading/worldshading/report/purchase_plan/purchase_plan.py
git diff --check
```

## 15. Release and rollback

The advanced clone contains unrelated work and must never be merged wholesale. Follow
`Documentation/safe_feature_release.md`:

1. update `/home/hilal/payment-release` from GitHub `main`;
2. create a fresh feature branch;
3. copy only the approved Purchase Plan files;
4. validate and stage explicit paths;
5. push and merge through GitHub;
6. inspect `HEAD..origin/main` on production; and
7. pull with `--ff-only`.

If production was temporarily edited manually, first prove that the live files match
the release commit, save a patch, restore only those tracked paths with `git checkout --
<paths>`, then fast-forward pull. Never push from production and never use
`git reset --hard`.

For report JavaScript/Python changes, clear the site cache and reload the approved
processes according to the production procedure. Schema changes require their own
reviewed migration plan; the report itself normally needs no `reload-doc` unless its
Report JSON changed.

For this report's smart total footer, verify `Report/Purchase Plan.add_total_row = 1`
after deployment. This is a targeted Report configuration change, not a schema change,
and must be included explicitly in the release and rollback plan.

Rollback is normally a Git revert of the feature commit followed by the same controlled
deployment and process reload. Reorder updates and saved RFQs are data changes and are
not undone by reverting code; review and correct those records separately.

## 16. Known limitations and change-control warnings

- Sales period semantics use `creation`, not posting date.
- Working days are inferred from Sales Invoice activity, not Holiday List.
- Stock is company-wide/all-warehouse; there is no warehouse filter for calculations.
- Supplier matching is historical Purchase Invoice based.
- Distinct invoice counting has a possible End Date/Datetime boundary inconsistency.
- Planning months approximate a month as 30 days and truncate during calculations.
- Field labels retain legacy spelling such as `Monthy Sales` and `Shortage Happend`.
- Reorder-dialog defaults remain hardcoded.
- WS Settings purchase warehouse fields may not be represented in Git schema.
- Prepared results can be stale until Rebuild.
- Supplier ranking uses the latest positive submitted Purchase Invoice net rate, not a
  quotation, landed valuation rate or average historical cost.
- Suppliers with no valid comparable historical cost cannot be ranked and appear
  after priced Suppliers.
- Selling Price falls back to Item `standard_rate` because the current Regular Price
  list has no Item Price rows.
- There is no automated regression suite dedicated to this report.

Changes to date basis, shortage sign treatment, the double Min reserve, repack ratios,
working-day inference or Expected Order Quantity require a written before/after example
and business-owner confirmation.

## 17. Historical references

The Excel files under `Documentation/purchase plan/` explain the origin of the report,
but they are historical inputs rather than executable specifications. They remain
server-local on the advanced clone and are intentionally excluded from the runtime Git
release. Preserve them there for comparison. Current behavior is defined by the released
report code and this handoff.
