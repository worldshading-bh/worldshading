# Item-wise Sales Register WS Design

## Objective

Create an ERPNext v12 Script Report named **Item-wise Sales Register WS** in the
Worldshading module. The report combines direct Sales Invoice Item sales and physical
products recorded in Sales Invoice Packed Items without double-counting invoice revenue.
It opens in a compact view, offers an optional detailed view, and runs as a Prepared
Report for performance.

The reusable sales aggregation must also become the sales source for Pricing Strategy
Analysis so both reports agree for equivalent filters.

## Constraints

- Keep all code compatible with ERPNext/Frappe v12 and Python 3.6.
- Do not change ERPNext core, `pos_bahrain`, or database schema.
- Do not create DocTypes.
- Do not alter Prepared Report cleanup settings.
- Do not run migration, restart, update, test, cache-clear, backup, restore, or service
  commands.
- Keep production data read-only.

## Inspected Production Facts

- There are 4,210 submitted Sales Invoice Packed Item rows.
- `parent_detail_docname` exists but is empty on every submitted packed row.
- Packed `rate` and `amount` are populated, and `amount` agrees with `rate * qty`.
- Every packed row can be associated with a parent Sales Invoice Item through Sales
  Invoice plus `parent_item`.
- 1,347 packed rows belong to an invoice/parent-item group containing duplicate parent
  Sales Invoice Item rows. Individual-row attribution is therefore unavailable, although
  group-level attribution remains deterministic.
- Return packed quantities and amounts are negative.
- Three invoice/item combinations contain the same Item both directly and as a packed
  component.
- Frappe Prepared Report auto-deletion is disabled. Worldshading cleanup deletes
  unlinked Prepared Reports older than three days. This behavior remains unchanged.

## Selected Architecture

### Shared sales allocation service

Add a small report-support module in `worldshading/reporting/`. It will:

1. validate and normalize common sales filters;
2. load submitted invoices, direct lines, and packed rows in bounded bulk queries;
3. reconcile packed revenue at the Sales Invoice plus `parent_item` boundary;
4. expose normalized transaction rows and item-level aggregates; and
5. emit structured reconciliation warnings.

The new report uses transaction rows. Pricing Strategy Analysis uses item-level
aggregates from the same normalized rows. This establishes a single definition for sold
stock quantity, sales value, weighted-average rate, invoice count, and last sale date.

### Query boundaries

All sales queries join child records to submitted Sales Invoices and apply:

- company;
- Sales Invoice posting date;
- customer and project;
- direct or packed source;
- relevant Item master filters; and
- warehouse where applicable.

The exact Item Code filter is applied independently to direct and packed result paths.
Packed records are never filtered by their creation date. Detail-only payment, tax, and
reference data is not loaded for the compact view.

Item master data, Item Default supplier data, company-warehouse Bin stock, payments,
taxes, and employee/salesperson data are batch-loaded. There is no query per output row.

## Packed Revenue Reconciliation

### Reconciliation boundary

Use `parent_detail_docname` when it is present and points to a parent line on the same
invoice. Otherwise, group by:

```text
Sales Invoice + Packed Item.parent_item
```

All matching Sales Invoice Item rows form the parent pool. Duplicate parent rows produce
an ambiguity warning but do not prevent group-level reconciliation.

### Allocation algorithm

For each parent pool:

1. Sum the signed Sales Invoice Item `base_net_amount` as `parent_net_value`.
2. Sum absolute declared Packed Item `amount` values as `declared_packed_value`.
3. Use each absolute Packed Item amount as its allocation weight.
4. If an amount is unavailable, fall back to `abs(rate * qty)` and warn.
5. If no monetary weights exist, fall back to absolute quantity and warn.
6. Set the allocatable packed magnitude to the smaller of the declared packed magnitude
   and parent net magnitude.
7. Allocate this value proportionally across packed components.
8. Apply the sign of the parent net value, including negative returns.
9. Correct the final component for the currency-rounding remainder.
10. Retain the signed remainder as a direct parent/service value.

The invariant is:

```text
sum(allocated packed value) + retained parent value = parent base net value
```

Examples:

```text
Parent net 100; packed 60 + 30 => packed 60 + 30; parent residual 10
Parent net  80; packed 60 + 40 => packed 48 + 32; parent residual  0
Return     -80; packed -60 -40 => packed -48 -32; parent residual  0
Parents 70 + 30; packed 40 + 30 => packed 40 + 30; residual 30; ambiguity warning
```

Zero parent value produces zero packed allocation while preserving quantity and a
warning. A zero quantity with non-zero allocated value also produces a warning.

### Quantities and rates

- Direct quantity uses Sales Invoice Item `stock_qty`.
- Packed quantity uses Packed Item `qty`, which is already in its packed Item UOM; the
  Item master stock UOM is shown.
- Net rate is `net value / sold stock quantity` when quantity is non-zero.
- Return quantity and value remain negative, while their unit rate remains meaningful.
- When the same Item is both direct and packed on one invoice, quantities and values are
  combined and Sales Basis is `Direct + Packed`.

### Taxes

Use ERPNext v12 Sales Taxes and Charges item-wise tax detail as the source. First derive
tax at the parent Sales Invoice Item pool, then distribute it across packed and retained
parent results using the same final net-value proportions. Actual invoice-level charges
without item-wise detail are distributed using the standard report's net-value method.
Allocated tax is rounding-corrected so output tax totals reconcile with the applicable
invoice tax allocation.

## Report Output

Rows are aggregated by posting date, Sales Invoice, and Item Code. This keeps invoice
links visible while combining direct and packed appearances deterministically.

### Compact columns

- Posting Date
- Sales Invoice
- Item Code
- Item Name
- Item Group
- Brand
- Sales Basis
- Stock UOM
- Sold Stock Qty
- Net Rate
- Net Amount
- Tax
- Total
- Current Stock Qty
- Default Supplier
- Supplier Name

### Detailed columns

Detailed mode adds non-redundant fields supported by the source records:

- Customer, Customer Name, Customer Group, Territory, and Project
- Sales Order and Delivery Note
- Parent/Bundle Item and Warehouse
- Income Account and Cost Center
- Mode of Payment and Currency
- Invoice Quantity, Invoice UOM, and Conversion Factor
- Price-list rate, gross amount, discount percentage, and discount amount
- Tax account/detail fields
- Supported salesperson/employee fields
- Direct quantity, packed quantity, direct net value, allocated packed net value
- Invoice count, last sold date, and reconciliation warning

Where combined rows contain more than one value, distinct values are displayed in a
stable comma-separated form rather than selecting an arbitrary source row.

### Filters

- Company, From Date, and To Date are required.
- Item Code, Item Name, Item Group, Brand, Customer, Warehouse, and Project are optional.
- Sales Basis supports All, Direct, and Packed. `Direct + Packed` rows qualify for both
  Direct and Packed selections because they contain both requested sources.
- Include Returns defaults to enabled.
- Show Detailed Report defaults to disabled.

All applicable filters are enforced server-side before normalization.

## User Interface

Adapt the proven Purchase Plan patterns without coupling the reports:

- persistent labels above filter controls;
- compact filter spacing and active-filter summary;
- sticky Item Code and Item Name columns;
- subtle highlights on quantity, net value, tax, total, and stock columns;
- selected-row persistence during DataTable re-rendering;
- a user-selectable row-highlight color saved only in browser local storage; and
- Prepared Report filter restoration and current-result download handling.

The default view stays compact. Detail columns exist only when the detailed filter is
enabled, which also avoids unnecessary detail queries.

## Warnings and Reconciliation

The report message summarizes warning counts. Detailed mode provides row-level warning
text for:

- missing or invalid parent link;
- ambiguous duplicate parent rows;
- missing packed amount/rate and fallback use;
- an unreconciled allocation invariant;
- zero quantity with non-zero value; and
- net returns equal to or exceeding sales at item-summary level.

Warnings do not silently remove rows. A truly unmatched packed group remains visible
with quantity, zero allocated revenue, and a warning; it does not create revenue.

## Prepared Report Metadata

The Report JSON uses:

```json
"prepared_report": 1,
"disable_prepared_report": 0
```

Existing system and Worldshading cleanup configuration is not modified.

## Files

New files:

- `worldshading/reporting/__init__.py`
- `worldshading/reporting/item_wise_sales.py`
- `worldshading/reporting/test_item_wise_sales.py`
- `worldshading/worldshading/report/item_wise_sales_register_ws/__init__.py`
- `worldshading/worldshading/report/item_wise_sales_register_ws/item_wise_sales_register_ws.py`
- `worldshading/worldshading/report/item_wise_sales_register_ws/item_wise_sales_register_ws.js`
- `worldshading/worldshading/report/item_wise_sales_register_ws/item_wise_sales_register_ws.json`
- focused report tests if report assembly tests are clearer in a separate file

Modified files:

- Pricing Strategy Analysis Python and focused tests, limited to consuming the shared
  sales aggregation.

No ERPNext or `pos_bahrain` files are modified.

## Testing and Verification

Database-free unit tests use fabricated rows and mocks. Required cases are:

- direct-only;
- packed-only;
- mixed direct and packed Item;
- discounted bundle scaling;
- multiple packed components;
- retained parent/service residual;
- negative return;
- missing link;
- duplicate/ambiguous parent rows;
- missing amount/rate fallback;
- zero quantity with value;
- distinct invoice count;
- report filter/column behavior; and
- Pricing Strategy Analysis parity.

Verification includes focused Python tests, Python 3.6 compilation, JavaScript syntax,
JSON parsing, report metadata checks, and static inspection of SQL filter placement. No
forbidden bench operation is used.

## Risk and Rollback

Risk is medium-high because this is financial reporting logic. The principal controls are
an exact allocation invariant, Decimal arithmetic, warning visibility, shared logic,
focused tests, and leaving existing operational documents and reports unchanged.

Rollback is to revert the Pricing Strategy Analysis integration and remove the new report
and helper files. No schema or data rollback is required.
