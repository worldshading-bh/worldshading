# Purchase Plan Report — Manager and AI Reference

This document explains World Shading's **Purchase Plan** report from a business
perspective. It can be uploaded to ChatGPT or another AI assistant when discussing
future improvements.

The calculations below describe the currently approved behavior. Any proposed formula
change should show both the old result calculation, the new calculation and a worked example.

## 1. Purpose

The report estimates purchasing requirements using:

- historical sales and expected growth;
- available stock and open Purchase Orders;
- expected sales while waiting for replenishment;
- purchase coverage months;
- minimum-stock reserve;
- existing Item Re-Order Level;
- optional missed sales while out of stock; and
- optional demand and stock from repacked Items.

## 2. Understanding the order quantity

**Expected Order Quantity** is signed:

- negative means purchasing is required;
- zero or positive means the calculation does not request a purchase; and
- **RFQ Order Qty** converts a negative requirement into a positive editable quantity.

```text
Expected Order Quantity = -500
RFQ Order Qty            = 500
```

## 3. Filters

| Filter | Business meaning |
|---|---|
| Start Date | Beginning of the historical sales period. Selecting it suggests the final day of that year as End Date. |
| End Date | End of the historical period. It remains editable or clearable and cannot be later than today. |
| Supplier | Items previously purchased on submitted invoices from the selected Supplier. |
| Supplier Group | Items purchased from Suppliers in the selected group or its subgroups. |
| Supplier Country | Items purchased from Suppliers in the selected country. |
| Item | One exact Item, still subject to the other active filters. |
| Parent Item Groups | Multiple parents may be selected. Each parent includes itself and all groups below it. |
| Child Item Groups | Multiple enabled child groups may be selected and added to the parent-group results. |
| Item Purchase Country | Matches the purchase country recorded on the Item. |
| Item Country of Origin | Matches the origin country recorded on the Item. |
| How Many Months to Arrive? | Expected time between ordering and having the stock available. |
| Percentage | Expected growth or safety percentage added to historical demand. |
| Min Stock for How Many Months? | Controls Min. The calculated Min is applied once to the order requirement. It has no default. |
| Purchase Plan for How Many Months? | Months of sales the new purchase should cover after arrival. Applied once. |
| Brand | Items belonging to the selected Brand. |
| Include Repack to Parent | Includes relevant demand and usable stock from repacked Items in purchasing/source Items. |
| Include Out of Stock Sales | Estimates sales potentially missed while Items were out of stock. |
| Purchase Required Items Only | Shows only rows with a negative Expected Order Quantity. |
| Disabled Items Only | Shows only disabled Items. Disabled Items cannot be added to an RFQ or updated through Item Reorder. |

Required numeric filters must contain valid numbers.

### Parent and child Item Groups

These filters use **OR/combined behavior**:

- selecting a parent includes the entire parent hierarchy;
- selecting another child outside that hierarchy adds it to the result; and
- selecting a child already covered by the parent does not duplicate Items.

## 4. Sales calculations

The report starts with:

```text
Adjusted Sales =
    Direct Sales
    + Estimated Out-of-Stock Sales
    + Converted Repack Sales

Expected Total Sale = Adjusted Sales × (1 + Percentage / 100)
```

The report period is converted into 30-day months:

```text
Total Report Months = whole number of (days between Start Date and End Date) / 30
```

Monthly and annual values are:

```text
Monthly Sales = Expected Total Sale / Total Report Months
Annual Sales  = Monthly Sales × 12
```

The current report retains its existing whole-number handling while calculating Monthly
Sales. This should not be changed without comparing actual report results.

## 5. Arrival-period demand

**Arrival Period Exp Sales** estimates sales while waiting for replenishment:

```text
Arrival Period Exp Sales = Monthly Sales × Months to Arrive
```

The projected balance after that waiting period is:

```text
Shortage Happend =
    Available Quantity
    + usable Converted Repack Available
    + On Purchase
    - Arrival Period Exp Sales
```

Only a positive balance is reusable in the order calculation:

```text
Usable Balance = maximum of Shortage Happend or zero
```

If Shortage Happend is negative, Usable Balance becomes zero. This preserves the current
approved behavior and avoids adding the same shortage again.

## 6. Purchase coverage, Min and final requirement

The two month controls are separate:

```text
Purchase Coverage Qty = Monthly Sales × Purchase Plan Months
Min                   = Monthly Sales × Min Stock Months
```

Purchase Coverage and Min are rounded individually to whole quantities.

The approved formula is:

```text
Expected Order Quantity =
    Usable Balance
    - Purchase Coverage Qty
    - Min
    - Existing Re-Order Level
```

Therefore:

- Purchase Plan Months is applied once;
- Min Stock Months calculates the displayed Min;
- that Min is applied once; and
- existing ERPNext Re-Order Level is applied separately.

Example:

```text
Monthly Sales           = 53.25
Purchase Plan Months    = 6
Min Stock Months        = 2
Purchase Coverage Qty   = round(53.25 × 6) = 320
Min                     = round(53.25 × 2) = 107
Usable Balance          = 1.072
Existing Re-Order Level = 0

Expected Order Quantity = 1.072 - 320 - 107 = -425.928
RFQ Order Qty            = round(425.928) = 426
```

## 7. Standard columns

| Column | Meaning |
|---|---|
| Item | Item code with a link to the Item. |
| Item Name | Current Item name. |
| Unit | Stock unit of measure. |
| Last Purchase Date | Latest purchasing stock movement from a Purchase Invoice or Purchase Receipt. Clicking opens the source document. |
| Last Sale Date | Latest selling stock movement from a Sales Invoice or Delivery Note. Clicking opens the source document. |
| No. of Sales Invoices | Number of distinct submitted Sales Invoices containing the Item during the report period. |
| Direct Sales | Sold quantity from submitted Sales Invoices, including relevant packed-item sales. |
| Item Group | Current Item Group. |
| Percentage % | Growth percentage entered in the filter. |
| Expected Total Sale | Adjusted historical sales after applying growth. |
| Min | Monthly Sales multiplied by Min Stock Months and rounded. Applied once in the order formula. |
| Available Quantity | Current stock across all warehouses. |
| On Purchase | Remaining quantity on submitted open Purchase Orders. |
| On Purchase PO | Purchase Orders contributing to On Purchase; document numbers are clickable. |
| Monthy Sales | Calculated average monthly sales. |
| Annual Sales | Monthly Sales multiplied by 12. |
| Arrival Period Exp Sales | Expected sales while waiting for the purchase to arrive. |
| Shortage Happend | Projected balance after arrival-period demand. |
| Re-Order Level | Existing Item Re-Order Level. |
| Re-Order quantity | Existing relevant Item Re-Order quantity. |
| Available Total Qty | Available planning stock plus On Purchase. |
| Expected Order Quantity | Signed purchasing result. Negative means purchase required. |
| RFQ Order Qty | Editable positive quantity used when creating an RFQ. |
| Priority Month | Available planning stock divided by Monthly Sales. |
| Item Suppliers | Suppliers ranked using their latest comparable purchase costs. |
| Last Purchase Cost | Cost from the Item's latest submitted Purchase Invoice, in company currency per stock unit. |
| Total Cost | RFQ Order Qty multiplied by Last Purchase Cost. |
| Selling Price | Current selling price from the default Selling Price List, with the legacy Item rate as fallback. |
| Total Selling Price | RFQ Order Qty multiplied by Selling Price. |

## 8. Optional columns and cases

When **Include Out of Stock Sales** is selected, the report adds:

- Out of Stock Days; and
- Estimated Out of Stock Sales Qty.

When **Include Repack to Parent** is selected, the report adds:

- Converted Repack Sales;
- Repack From; and
- Converted Repack Available.

## 9. Out-of-stock estimation

The optional estimate reviews the Item's stock position during the selected period and
identifies working days when its balance was zero or negative.

```text
Estimated Out-of-Stock Sales =
    sales per in-stock working day × out-of-stock working days
```

This amount is added to demand before applying the growth percentage. Low-activity Items
show N/A when the report does not consider the estimate reliable enough.

## 10. Repack case

Some Items are sold in a repacked form but purchased as a source Item, such as purchasing
a Roll and selling converted Meter Items.

When repack is included:

- sales of all relevant target/repacked Items are converted back to the source Item;
- demand from multiple targets is added together;
- usable target stock may also be converted back to the source Item;
- purchasing rows show the source Item rather than a target that can be produced; and
- Repack From explains which target Items contributed to the source requirement.

The repack planning period follows the same approved logic:

```text
Repack Planning Months =
    Months to Arrive
    + Purchase Plan Months
    + Min Stock Months
```

## 11. Suppliers, colours and costs

The report includes enabled Suppliers configured for the Item or found in its submitted
Purchase Invoice history.

Each Supplier's latest cost is converted to company currency per stock unit so Suppliers
can be compared fairly. Suppliers are ordered by that latest comparable cost:

- cheapest: green;
- second cheapest: yellow;
- other Suppliers with a cost: red; and
- configured Suppliers without invoice history: grey and placed afterward.

The clickable value remains the Supplier code. Hovering shows:

```text
Supplier Name
Last Cost
Latest Purchase Invoice
Posting Date
No. of Purchases
```

No. of Purchases is the number of distinct submitted Purchase Invoices for that exact
Item and Supplier.

**Last Purchase Cost** is different from the colour ranking concept: it is the cost on
the Item's latest submitted Purchase Invoice overall. The green Supplier may have the
lowest latest comparable cost even when another Supplier supplied the most recent invoice.

## 12. Selling price

Selling Price comes from the default Selling Price List. If no applicable Item Price is
available in this legacy system, the Item's regular/standard rate is used as a fallback.

Price, supplier and cost information is shown for all report Items.

## 13. Create RFQ

- RFQ Order Qty starts as the rounded positive value of a negative Expected Order Quantity.
- Users may edit it before selecting Create RFQ.
- A zero RFQ quantity excludes that row.
- Positive manually entered quantities may include other report Items.
- Disabled Items cannot be added.
- The action opens a new unsaved RFQ for review.
- Active report filters are saved in the RFQ's report-filter field when that field exists.

Country and warehouse selection follow this priority:

1. Supplier Country filter;
2. exact selected Supplier's country;
3. Item Purchase Country filter; and
4. Item Country of Origin filter.

## 14. Update Item Reorder

The action uses the report's displayed rounded Min as the Item Re-Order Level for eligible
Items selected through the action.

Changing Min Stock Months therefore affects:

- Expected Order Quantity, where Min is applied once; and
- Update Item Reorder, where the displayed Min is stored once as the reorder level.

## 15. Totals and report behavior

- Expected Order Quantity total includes only negative values.
- Additive quantity, sales, cost and price columns have totals.
- Dates, percentages, Suppliers and Priority Month are not totaled.
- Editing RFQ Order Qty immediately updates Total Cost and Total Selling Price.
- Important columns use distinct background colours for easier reading.
- The first Item-identification and sales columns remain visible while scrolling.
- Column filters remain removable even when a filter returns no rows.
- Selected Parent and Child Item Groups appear first in their dropdown lists.

## 16. Important business assumptions

The following are intentional and should be confirmed before changing:

- Min is applied once.
- Purchase Plan Months is applied once.
- Existing Re-Order Level is additional to Purchase Coverage and the Min reserve.
- Negative arrival-period balance is treated as zero in the final order formula.
- Purchase Coverage and Min are rounded before calculating the final RFQ quantity.
- Report months use 30-day periods rather than calendar months.
- Available stock is company-wide across all warehouses.
- Last purchase and sale dates consider all history, not only the selected report dates.
- Supplier ranking uses each Supplier's latest comparable cost.
- Repack demand and usable stock can affect the purchasing/source Item.

Before changing any of these rules, confirm the expected result with a real Item example
and record the approved decision in this document.

## 17. Information to give an AI for a future change

Along with this document, provide:

- the exact requested change;
- one real Item example with current values;
- the current result and expected result;
- whether the change applies to normal, repack and out-of-stock cases;
- whether it should affect RFQ creation or Item Reorder; and
- confirmation if an approved formula above must change.

Ask the AI to preserve everything not explicitly included in the request.
