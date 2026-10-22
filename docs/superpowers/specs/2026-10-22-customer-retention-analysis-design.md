# Customer Retention Analysis Design

## Objective

Add a read-only prepared Script Report named **Customer Retention Analysis** to the `worldshading` app. The report will help sales managers identify important customers whose purchasing has stopped or declined, understand their invoice activity and preferred Item Groups, and connect the findings to the existing Campaign Customer follow-up process.

Success means a user can select an analysis year, compare it with one to five complete previous calendar years, rank the most commercially important customers, understand each customer's retention status at a glance, and reopen a completed Prepared Report without rerunning the analysis synchronously.

## Approved Business Rules

- Every comparison period is a full calendar year from 1 January through 31 December.
- The selected **Analysis Year** is the current period shown by the report. When it is the current calendar year, future dates naturally contain no transactions; the report does not annualize or prorate the result.
- The selected Analysis Year is compared directly with the complete previous calendar year even when the Analysis Year is still in progress.
- Users may include one to five previous calendar years.
- The default decrease and increase threshold is 20 percent.
- Sales value is submitted Sales Invoice company-currency net value. Returns and credit notes reduce sales.
- The report is analytical and read-only. It does not update Customers, Sales Invoices, Campaign Customers, Opportunities, workflows, or accounting records.

## Scope

The first version adds:

- A prepared Script Report in the Worldshading module.
- Calendar-year sales and invoice activity by Customer.
- Retention status classification.
- Configurable ranking and result limits.
- Last-purchase and inactivity information.
- Up to three preferred Item Groups per Customer.
- Latest Campaign Customer follow-up context when available.
- Visual status formatting, summary indicators, and a decline chart compatible with the ERPNext v12 report view.
- Isolated unit tests for calculations and report metadata.

The first version does not:

- Create Campaign Customer records from selected rows.
- Send WhatsApp messages, email, SMS, or notifications.
- Schedule automatic report generation.
- Store a second copy of sales aggregates in a custom DocType.
- Modify ERPNext core reports or accounting logic.
- Change Campaign Customer permissions, validation, or workflow behavior.

Those capabilities require separate approval after staff have used the read-only report.

## Chosen Architecture

### Prepared Script Report

The report will use Frappe v12's standard Prepared Report mechanism by setting `prepared_report` to `1` and leaving prepared reports enabled in the Report JSON. Frappe will execute the report through its existing background-job path and store the generated result as a Prepared Report attachment.

This approach is preferred over a snapshot DocType because it avoids duplicate business data, cleanup rules, and synchronization problems. It is preferred over a custom Page because it preserves standard report filters, permissions, export, background preparation, and familiar navigation.

The custom app's existing prepared-report implementations provide the v12-compatible reference for restoring saved filters and presenting completed results. No new scheduler or cache table is needed.

### Data Retrieval

The server implementation will use a small fixed number of aggregate queries rather than querying once per Customer:

1. Aggregate submitted Sales Invoices by Customer and calendar year.
2. Aggregate invoice activity for the selected years and find the last submitted
   non-return Sales Invoice date from the Customer's complete history up to the
   Analysis Year end.
3. After classification, sorting, and limiting, aggregate Sales Invoice Item
   values only for the displayed Customers and the current Item master
   `item_group` to determine preferred groups.
4. Fetch relevant Campaign Customer records only for the displayed Customers
   and select the latest record in Python when the current user can read
   Campaign Customer.

The result limit is applied only after all requested filters, calculations, classification, and sorting. This prevents a database-level limit from excluding a customer who should rank in the final top results.

All SQL parameters will be bound values. Dynamic SQL will be restricted to controlled clauses selected by server code; user-provided strings will never be interpolated into SQL.

## Filters

### Required filters

- **Company** — Link to Company; defaults to the user's Company.
- **Analysis Year** — Int; defaults to the current calendar year.
- **Previous Years** — Select with values 1 through 5; defaults to 1.

### Optional scope filters

- **Customer** — Link to Customer.
- **Customer Group** — Link to Customer Group.
- **Territory** — Link to Territory.
- **Retention Status** — Select: blank/All, Lost, Decreased, Stable, Increased, New, Reactivated.
- **Minimum Historical Sales** — Currency; defaults to zero.

### Ranking filters

- **Top Results** — Select: 20, 50, 100, 250, All; defaults to 100.
- **Sort By** — Select: Importance, Decrease Amount, Current Sales, Previous Sales, Inactive Days, Current Invoice Count; defaults to Importance.
- **Sort Direction** — Select: Descending, Ascending; defaults to Descending.

The 20 percent status threshold is a constant in the first version, matching the approved rule. Making it a user filter can be considered after real-world review if different teams need different sensitivity.

Minimum Historical Sales is compared with the highest annual sales value among
the selected previous years. This keeps a formerly important Customer visible
even when the immediately previous year was already inactive.

## Customer Population

The report includes Customers with non-zero net sales in at least one selected calendar year. A customer whose invoices and returns net exactly to zero across every selected year is excluded.

Disabled Customers remain visible when they have activity in the selected period because historical sales analysis must not erase them. Customer Group and Territory filters use the current Customer master values.

## Sales and Activity Calculations

### Sales value

For each submitted Sales Invoice (`docstatus = 1`) in the selected Company:

- Sales value uses `base_net_total`.
- Normal invoices add to sales.
- Return invoices and credit notes reduce sales through their negative net values.
- Tax and outstanding balance do not affect retention value.
- Cancelled and draft invoices are excluded.

Using base values keeps all results in the selected Company's currency.

### Invoice counts

Invoice activity counts distinct submitted non-return Sales Invoices. Return documents affect sales value but do not increase the purchasing-activity count.

The report shows:

- Analysis-year invoice count.
- Previous-year invoice count.
- Total non-return invoice count across the selected years.

### Historical values

- **Previous Sales** is the year immediately before the Analysis Year.
- **Average Historical Sales** is the arithmetic mean of all selected previous years, including zero-activity years.
- **Importance** is Previous Sales for the default ranking, matching the approved requirement to prioritize the preceding year's most important Customers.
- **Change Amount** is Analysis Year Sales minus Previous Sales.
- **Decrease Amount** used by the ranking option is Previous Sales minus Analysis Year Sales, floored at zero, so descending order places the largest losses first.
- **Change %** is `(Analysis Year Sales - Previous Sales) / Previous Sales * 100` when Previous Sales is positive.
- Change % is blank when Previous Sales is zero because a percentage is undefined.

Each selected previous year also appears as its own dynamic Currency column, newest year first.

## Retention Status

Classification is applied in this order:

1. **New** — Analysis Year Sales is positive and every selected previous year is zero or negative.
2. **Reactivated** — Analysis Year Sales is positive, Previous Sales is zero or negative, and at least one older selected year has positive sales.
3. **Lost** — Analysis Year Sales is zero or negative and at least one selected previous year has positive sales.
4. **Decreased** — Analysis Year Sales and Previous Sales are positive, and Change % is less than or equal to -20 percent.
5. **Increased** — Analysis Year Sales and Previous Sales are positive, and Change % is greater than or equal to 20 percent.
6. **Stable** — Analysis Year Sales and Previous Sales are positive, and Change % is between -20 percent and 20 percent.

The Lost rule includes customers whose last positive year is older than the immediately previous year. This ensures that selecting more history reveals long-inactive valuable Customers instead of leaving them unclassified.

At the exact threshold, -20 percent is Decreased and +20 percent is Increased.

## Inactivity

- **Last Invoice Date** is the latest submitted non-return Sales Invoice date up to 31 December of the Analysis Year.
- **Inactive Days** is the number of days between the earlier of today's date or 31 December of the Analysis Year and Last Invoice Date.
- For a historical Analysis Year, inactivity therefore stops at that year's end rather than measuring from today.
- Customers without a non-return invoice have no Last Invoice Date; return-only activity does not establish a purchase date.

## Preferred Item Groups

The report shows **Top Item Group 1**, **Top Item Group 2**, and **Top Item Group 3**.

- Item Group comes from the current `tabItem.item_group`, as requested, rather than relying on an old value copied onto an invoice row.
- Ranking uses total `Sales Invoice Item.base_net_amount` across all selected calendar years.
- Return item values reduce the group total.
- Only groups with a positive final net value qualify.
- Ties are resolved by Item Group name for deterministic output.

The first version displays group names only. Group amount columns can be added later if staff find them necessary.

## Campaign Customer Context

When one or more Campaign Customer records exist for a Customer, the report uses the most recently modified record and shows:

- Campaign Customer — Link to Campaign Customer.
- Campaign — Link to Campaign.
- Outreach Status.
- Priority.
- Planned Contact Date.
- Next Follow-up.
- Number of Interactions.

These fields are context only. The report does not change or create a Campaign Customer. Using the most recently modified record is deterministic and avoids guessing which campaign is operationally primary.

Campaign Customer context is fetched only for Customers remaining after report
classification, scope filtering, sorting, and the Top Results limit. Campaign
context does not influence ranking, so this avoids unnecessary work for rows the
user will not see.

If the current user does not have read permission for Campaign Customer, the
campaign-context columns remain blank and no Campaign Customer query runs. This
allows authorized finance users to use sales analysis without exposing campaign
records outside their DocType permissions.

## Output Columns

Columns appear in this order:

1. Rank.
2. Customer.
3. Customer Name.
4. Customer Group.
5. Territory.
6. Retention Status.
7. Analysis Year Sales.
8. Previous Sales.
9. Change Amount.
10. Change %.
11. Average Historical Sales.
12. Analysis Year Invoice Count.
13. Previous Year Invoice Count.
14. Total Invoice Count.
15. Last Invoice Date.
16. Inactive Days.
17. One dynamic sales column for each selected previous year.
18. Top Item Group 1.
19. Top Item Group 2.
20. Top Item Group 3.
21. Campaign Customer.
22. Campaign.
23. Outreach Status.
24. Priority.
25. Planned Contact Date.
26. Next Follow-up.
27. Number of Interactions.

The Analysis Year and Previous Year labels include their actual year numbers so exported files remain understandable outside ERPNext.

## Visual Presentation

The report remains a standard ERPNext v12 DataTable and does not introduce a separate UI framework.

- Retention Status is rendered as a colored indicator: red Lost, orange Decreased, gray Stable, green Increased, blue New, and purple Reactivated.
- Negative Change Amount and Change % values use warning colors; positive values use success colors.
- Rank, Customer, and Customer Name remain visually prominent and sticky where the v12 DataTable behavior permits it.
- Currency columns use the Company currency.
- A report summary shows counts for Lost, Decreased, Stable, Increased, New, and Reactivated in the final displayed rows, plus their total Previous Sales at risk for Lost and Decreased Customers.
- The report chart shows the largest sales decreases among the first ranked results. It uses the standard Frappe chart contract so it also appears with Prepared Report output.
- A compact filter summary is restored when opening a completed Prepared Report, following the existing Worldshading v12 prepared-report pattern.
- When the Analysis Year is the current unfinished year, the report displays a concise notice that the full-year status is based on year-to-date transactions compared with the complete previous year, as explicitly required by the business rule.

Visual formatting must degrade safely: exported values remain plain data, and failure to apply custom client formatting must not prevent users from reading the report.

## Permissions

The Report JSON grants access to:

- Cashier.
- Sales Manager.
- General Manager.
- Accounts Manager.
- System Manager.

The server verifies that the user can read the selected Company and restricts
every sales query to that Company. The report does not use
`ignore_permissions` and does not expose contact phone numbers or email
addresses. Access to aggregated Customer sales is intentionally controlled by
the report roles above; Campaign Customer details additionally require read
permission for Campaign Customer.

## Error Handling and Validation

The server will reject:

- A missing or inaccessible Company.
- Analysis Year outside a conservative supported range of 2000 through the current year.
- Previous Years outside 1 through 5.
- Negative Minimum Historical Sales.
- Unknown status, sort, direction, or result-limit values.

Empty results return valid columns, summary values of zero, and a clear informational message. Database errors are not swallowed.

## ERPNext v12 Compatibility

Implementation will use Python 3.6-compatible syntax and Frappe/ERPNext v12 APIs. It will not use:

- Type annotations.
- Dataclasses.
- `frappe.qb`.
- F-strings if the surrounding project convention avoids them.
- APIs introduced after Frappe v12.

All product files remain in the `worldshading` custom app. No ERPNext or Frappe core file is modified.

## Files

New files:

- `worldshading/worldshading/report/customer_retention_analysis/__init__.py`
- `worldshading/worldshading/report/customer_retention_analysis/customer_retention_analysis.json`
- `worldshading/worldshading/report/customer_retention_analysis/customer_retention_analysis.py`
- `worldshading/worldshading/report/customer_retention_analysis/customer_retention_analysis.js`
- `worldshading/worldshading/report/customer_retention_analysis/test_customer_retention_analysis.py`

No existing application file is expected to change.

## Verification

Implementation verification will respect the production restrictions:

- Do not run `bench migrate`.
- Do not run `bench test`.
- Do not run `reload-doc`.
- Do not restart services or clear caches.
- Do not execute the report against the production site during implementation.

Allowed verification is limited to isolated, database-mocked unit tests invoked directly with the Python interpreter, JSON parsing, Python compilation, JavaScript syntax/static checks already available in the repository, and `git diff --check`. If an allowed check would initialize the site or database, it will be skipped and reported rather than run.

The implementation plan will list exact manual production registration and smoke checks for a human operator to review separately. No production application command will be executed automatically.

## Risk and Rollback

Risk is medium:

- A broad five-year report may aggregate a large number of invoice and item rows.
- Incorrect return handling or period boundaries could misclassify customers.
- Current-year versus previous-full-year comparison may intentionally show large declines before the current year is complete.
- Staff may interpret a classification as a guarantee rather than a prioritization signal.

Mitigations are prepared execution, bounded history, aggregate queries, deterministic rules, explicit year labels, isolated calculation tests, and no mutation of business records.

Before report registration, rollback is removal or reversion of the five new report files. After manual registration, rollback is disabling or removing the Report metadata through a separately reviewed operation. Prepared Report attachments may be removed through the existing Prepared Report lifecycle. No Customer, Sales Invoice, Campaign Customer, workflow, stock, or accounting rollback is required because the report is read-only.
