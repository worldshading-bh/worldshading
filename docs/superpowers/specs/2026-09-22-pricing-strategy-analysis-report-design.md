# Pricing Strategy Analysis Report Design

Date: 22 September 2026  
Application: `worldshading`  
Platform: ERPNext 12 / Frappe 12 / Python 3.6

## 1. Objective

Add a read-only Script Report named **Pricing Strategy Analysis**. The report helps an
authorized user compare current costs and historical sales with proposed regular, B2B,
and quantity-tier selling prices.

All changeable calculation assumptions are report filters. This phase creates no
settings DocType, does not update Item Price, does not create Pricing Rules, and does
not modify ERPNext core files.

## 2. Reference Workbook

The design is based on `worldshading/Documentation/Price strategy.xlsx`:

- rows 1-18 contain a worked calculation example;
- rows 19-22 contain calculation inputs;
- row 25 contains the report headings; and
- rows 26 onward contain item results.

The workbook labels its percentages as margins but calculates markup on cost. The
ERPNext report will use the accurate label **Target Markup %** and will separately show
the resulting **Gross Margin %**.

The workbook is only the reference for price-tier calculations. It does not contain
historical-sales or expense calculations; those are defined explicitly below.

## 3. Scope

### Included

- One ERPNext v12 Script Report under the existing `worldshading` module.
- One result row per enabled stock Item matching the report filters.
- Three selectable cost sources.
- Submitted purchase and sales history in company currency and Stock UOM.
- Current Item Price comparisons.
- Regular, B2B, and four quantity-tier recommendations.
- VAT-inclusive price rounding equivalent to the workbook.
- Profit, markup, gross-margin, discount, and warning columns.
- Export through the standard Frappe report export facility.
- Focused automated tests that do not require a migrated production site.

### Excluded

- New DocTypes or custom fields.
- Saving filter presets as commercial policy.
- Updating or creating Item Price records.
- Updating or creating Pricing Rules.
- Background jobs, scheduled tasks, workflow actions, and notifications.
- ERPNext core changes.
- Automatic allocation of General Ledger expenses to individual items.

## 4. Report Access and Safety

The report JSON will assign access to `Accounts Manager` and `System Manager`. It will
remain read-only and expose no whitelisted mutation method or update button.

The report remains a normal synchronous Script Report rather than a Prepared Report.
Pricing analysis is interactive, and observed execution is approximately 2.6 seconds;
preparing and storing a new result for frequent assumption changes would add delay
without a current performance benefit.

The report must not bypass standard document permissions. If the established report
pattern in this application does not automatically apply user permissions, the server
code will explicitly verify access to the report and relevant records before returning
data.

## 5. Filters

### 5.1 Selection filters

| Label | Field type | Required | Default/behavior |
|---|---|---:|---|
| Company | Link / Company | Yes | User default company, otherwise global default |
| From Date | Date | Yes | One year before To Date |
| To Date | Date | Yes | Current date |
| Item | Link / Item | No | Exact item |
| Item Group | Link / Item Group | No | Selected group and descendants |
| Brand | Link / Brand | No | Exact brand |
| Warehouse | Link / Warehouse | No | Company warehouse; blank aggregates all company warehouses |
| Regular Price List | Link / Price List | Yes | Selling Settings default price list when available |
| B2B Price List | Link / Price List | No | Optional protected selling price list |
| Include Items Without Sales | Check | No | Enabled by default |

Only enabled stock items are included. Item variants are treated as separate items.
Templates and disabled items are excluded.

### 5.2 Cost and expense filters

| Label | Field type | Required | Default/behavior |
|---|---|---:|---|
| Cost Source | Select | Yes | `Current Valuation Rate` |
| Expense Burden % | Percent | Yes | `0` |

Cost Source options are:

1. `Current Valuation Rate`
2. `Latest Purchase Rate`
3. `Weighted Average Purchase Rate`

The purchase date range is the same From Date and To Date used for sales analysis.
Expense Burden % is a user-supplied analytical assumption, not a value derived from GL
Entry. This prevents arbitrary allocation and avoids double-counting landed costs that
are already part of valuation.

### 5.3 Pricing and rounding filters

| Label | Field type | Required | Default |
|---|---|---:|---:|
| VAT % | Percent | Yes | 10 |
| Regular Markup % | Percent | Yes | 43 |
| B2B Markup % | Percent | Yes | 33 |
| Show Pricing Rule Strategy | Check | No | Disabled |
| Tier 1 Qty Range | Data | Yes | `5:9` |
| Tier 1 Markup % | Percent | Yes | 31 |
| Tier 2 Qty Range | Data | Yes | `10:19` |
| Tier 2 Markup % | Percent | Yes | 29 |
| Tier 3 Qty Range | Data | Yes | `20:39` |
| Tier 3 Markup % | Percent | Yes | 27 |
| Tier 4 Qty Range | Data | Yes | `40+` |
| Tier 4 Markup % | Percent | Yes | 25 |

The report always rounds upward. It applies upward rounding to the raw VAT-inclusive
price using this fixed commercial schedule:

| Raw VAT-inclusive price | Increment |
|---|---:|
| Below BHD 0.100 | BHD 0.005 (5 fils) |
| BHD 0.100 to below BHD 30 | BHD 0.100 (100 fils) |
| BHD 30 to below BHD 100 | BHD 0.500 (500 fils) |
| BHD 100 to below BHD 1,000 | BHD 1.000 |
| BHD 1,000 and above | BHD 10.000 |

The exact lower boundary belongs to the new band. The resulting ERPNext net rate is
calculated by removing VAT from the rounded gross price.

The default view is an Item Price strategy covering Regular and B2B price lists. When
Show Pricing Rule Strategy is disabled, all tier filters, calculations, and columns are
omitted. Enabling it reveals the Tier 1-4 controls and returns quantity-tier columns.

Quantity ranges use `From:To` for a bounded range and `From+` for an open-ended final
tier. Filter labels remain visible above their controls after values are entered.

## 6. Input Validation

Before querying item data, the report will reject:

- From Date after To Date;
- negative VAT, expense burden, or markup values;
- zero or negative tier quantities;
- a quantity range not written as `From:To` or `From+`;
- a tier maximum below its minimum;
- overlapping tiers;
- tiers not ordered by minimum quantity;
- a non-selling or disabled selected Price List;
- a selected B2B Price List that is not a selling Price List;
- a Warehouse belonging to another company; and
- unsupported Cost Source values.

Gaps between quantity tiers are permitted but produce a visible report message because
no proposed tier price will cover those quantities. Only the final tier may use the
open-ended `From+` form.

## 7. Data Sources and Normalization

### 7.1 Item and stock information

- `Item`: item code, name, group, brand, Stock UOM, disabled flag, and stock-item flag.
- `Warehouse`: company validation and warehouse filtering.
- `Bin`: current actual quantity and valuation rate.

When Warehouse is blank, available quantity is summed across non-disabled warehouses
for the selected company. Current valuation is the quantity-weighted Bin valuation:

```text
sum(actual_qty * valuation_rate) / sum(actual_qty)
```

Only positive on-hand quantities participate in the weighted valuation. If there is no
positive stock, the report falls back to the most recent company Stock Ledger Entry
valuation rate on or before To Date. The output identifies that fallback in Cost Source
Detail.

### 7.2 Purchase history

Purchase history comes from submitted Purchase Receipts and Purchase Receipt Items.
Rates are normalized to company currency and Stock UOM:

```text
purchase stock rate = base_net_amount / stock_qty
```

Returns reduce both base net amount and stock quantity according to their signed stored
values. Cancelled documents are excluded. Rows with zero stock quantity do not
participate.

`Latest Purchase Rate` is the normalized rate of the latest qualifying Purchase Receipt
row on or before To Date. The date range lower bound does not restrict this lookup;
otherwise an item with no purchase inside the analysis window would incorrectly have no
latest cost.

`Weighted Average Purchase Rate` uses qualifying purchase rows within From Date through
To Date:

```text
sum(signed base_net_amount) / sum(signed stock_qty)
```

If returns make the net quantity zero or negative, weighted purchase cost is unavailable
and the row receives a warning. Purchase Invoice is not mixed into this calculation,
because invoices and receipts can represent the same inventory and would double-count
purchases.

### 7.3 Historical sales

Sales history comes from submitted Sales Invoices and Sales Invoice Items in the
selected Company and date range. Returns reduce quantity and value using their signed
stored values.

All sales metrics use company currency and Stock UOM:

```text
sales quantity = sum(stock_qty)
sales value = sum(base_net_amount)
weighted average sold rate = sales value / sales quantity
```

The report also returns invoice count, last sale date, last normalized sold rate, and
lowest/highest normalized sold rates. Cancelled documents and rows with zero Stock UOM
quantity are excluded. If net sales quantity is zero or negative, weighted average sold
rate is blank and a warning is shown.

### 7.4 Current prices

Current normal and B2B prices come from valid `Item Price` records for the selected
price lists and To Date. Matching respects Item, Stock UOM, validity dates, and the
Price List's UOM-dependence setting. ERPNext v12 Item Price has no minimum-quantity
field; quantity thresholds belong to Pricing Rule and are outside this read-only phase.

If multiple records are valid, the most recently valid record is used deterministically
and a duplicate-price warning is included. Currency conversion is outside this phase:
the selected Price Lists must use the selected Company's currency. A different currency
is rejected with a clear message.

The B2B list remains optional. If it is blank, B2B recommendations are still calculated
from the B2B Markup filter, but Current B2B Price is blank.

## 8. Calculation Rules

All calculations use Python `Decimal` values created from strings. They do not use
binary floating-point arithmetic for commercial rounding.

### 8.1 Loaded cost

```text
selected base cost = value supplied by Cost Source
expense amount = selected base cost * Expense Burden % / 100
fully loaded cost = selected base cost + expense amount
```

An item with no positive selected cost remains visible, but recommendations are blank
and the row is marked `Missing Cost`.

### 8.2 Recommended price

For Regular, B2B, and each tier:

```text
raw net price = fully loaded cost * (1 + target markup % / 100)
raw gross price = raw net price * (1 + VAT % / 100)
rounding increment = fixed schedule lookup using raw gross price
rounded gross price = round raw gross price upward to the scheduled increment
recommended net price = rounded gross price / (1 + VAT % / 100)
profit per unit = recommended net price - fully loaded cost
actual markup % = profit per unit / fully loaded cost * 100
gross margin % = profit per unit / recommended net price * 100
```

An exact multiple remains unchanged; any remainder moves the price to the next scheduled
increment. Prices and monetary metrics are finally quantized to three decimal places for
display. Percentage metrics use three decimal places.

### 8.3 Discount comparisons

```text
B2B discount % =
    (recommended regular net - recommended B2B net)
    / recommended regular net * 100

Tier discount % =
    (recommended B2B net - recommended tier net)
    / recommended B2B net * 100

change from current normal = recommended regular net - current normal Item Price
change from current normal % = change / current normal Item Price * 100
```

This preserves the workbook's B2B and wholesale comparison bases. Division-dependent
values are blank when the denominator is zero.

## 9. Output Columns

The report returns the following groups in this order.

### Item and cost

- Item Code
- Item Name
- Item Group
- Brand
- Stock UOM
- Available Qty
- Selected Base Cost
- Cost Source Detail
- Fully Loaded Cost

### Historical sales and current prices

- Sales Qty
- Last Sold Rate
- Weighted Average Sold Rate
- Current Normal Price
- Current B2B Price

### Regular and B2B recommendations

- Recommended Regular Net
- Recommended Regular Including VAT
- Regular Gross Margin %
- Change from Current Normal
- Change from Current Normal %
- Recommended B2B Net
- Recommended B2B Including VAT
- B2B Discount from Regular %
- B2B Gross Margin %

### Quantity tiers

Quantity-tier columns appear only when Show Pricing Rule Strategy is enabled. Each tier
then returns:

- label containing its runtime quantity range;
- recommended net price;
- recommended VAT-inclusive price;
- discount from recommended B2B price;
- gross margin percentage.

### Decision support

- Suggested Action
- Warnings

Suggested Action is one of:

- `Set Initial Price` when no current normal Item Price exists;
- `Increase Price` when the recommendation exceeds the current price by at least one
  rounding increment;
- `Reduce Price` when it is lower by at least one rounding increment; or
- `Keep Price` when the absolute difference is below one rounding increment.

Warnings are semicolon-separated and may include missing cost, no recent sales,
recommended regular price below historical average, current price below loaded cost,
purchase-return imbalance, sales-return imbalance, valuation fallback, duplicate Item
Prices, and gaps in tier coverage.

## 10. Query and Performance Design

The implementation must not query the database once per item. It will:

1. select the filtered Item population;
2. fetch stock/valuation aggregates for all selected items;
3. fetch purchase aggregates and latest purchase rows in batches;
4. fetch sales aggregates and latest sales rows in batches;
5. fetch current Item Prices for all selected items and selected lists; and
6. calculate prices in Python using small, independently testable helpers.

SQL is justified for grouped purchase, sales, stock, and latest-row queries because the
Frappe v12 ORM cannot efficiently express these aggregates without N+1 queries. Every
SQL statement will be parameterized. Calculation helpers remain separate from database
access so they can be tested without a site or database.

## 11. Files

Expected implementation files:

```text
worldshading/worldshading/report/pricing_strategy_analysis/
    __init__.py
    pricing_strategy_analysis.json
    pricing_strategy_analysis.js
    pricing_strategy_analysis.py
    test_pricing_strategy_analysis.py
```

No existing pricing code will be modified unless implementation inspection reveals a
necessary integration. Any such discovery requires a design amendment and approval
before changing existing files.

## 12. Testing

Focused tests will cover:

- the workbook example (cost 46, VAT 10%, and its six markup levels);
- fixed upward rounding at every increment boundary;
- actual markup versus true gross margin;
- expense burden calculations;
- tier validation, overlap, gaps, and open-ended final tier;
- missing and zero cost;
- returns in weighted purchase and sales calculations;
- price-change action thresholds;
- warning composition;
- report filter defaults and column construction; and
- Python 3.6 compatibility.

No `bench test`, migration, restart, backup, cache clear, or production data write is
part of implementation verification. Permitted verification is limited to syntax
compilation, import-independent unit tests for pure helpers, JSON validation, static
inspection, and review of the resulting diff.

## 13. Rollout and Rollback

Deployment commands are outside this task. The implementation will be delivered as
custom-app source only.

The report is read-only and creates no business records. Rollback is removal or
reversion of the new report directory. Item Price, Pricing Rule, sales, purchase, stock,
and accounting records require no restoration.
