# Customer CR Verification and B2B Secret Pricing

Last updated: 20 September 2026  
Application: `worldshading`  
Platform: ERPNext 12 / Frappe 12

## 1. Purpose

This feature has two independent responsibilities:

1. **Business verification** confirms a Bahrain company's identity and CR status through
   Sijilat.
2. **Secret pricing authorization** decides whether a Customer may use a protected B2B
   Selling Price List.

These responsibilities are intentionally separate. A verified company does not
automatically receive B2B pricing, and an approved individual or unverified Customer can
receive B2B pricing when an authorized manager explicitly grants it.

```
Customer
   ├─ Verify CR
   │    └─ Sijilat identity/status verification
   │         └─ Does not change pricing
   │
   └─ Apply Secret Price List
        └─ Authorized commercial decision
             └─ Does not change CR verification
```

## 2. Main files and records

| Component | Location / record | Responsibility |
|---|---|---|
| Sijilat integration | `worldshading/api/sijilat.py` | CR validation, preview, confirmation, expiry and rechecks |
| B2B pricing | `worldshading/api/business_pricing.py` | Secret Price List assignment, transaction authorization and item rates |
| Packed pricing | `worldshading/api/quotation_packed_pricing.py` | Quotation packed-item, calculated parent-rate and warranty pricing |
| Hooks | `worldshading/hooks.py` | Customer validation, transaction validation and schedulers |
| Customer form | Custom Script `Customer-Client` | Buttons, dialogs, visibility and client-side validation |
| Customer list badge | `worldshading/public/js/customer_list.js` | Blue verification badge in Customer List |
| Price List control | Custom field on Price List | Marks a Price List as protected |

ERPNext core files are not modified.

## 3. Data model

### 3.1 Customer fields

| Label | Fieldname | Type | Purpose |
|---|---|---|---|
| CR No | `cr_no` | Data | Bahrain CR number including branch, for example `90666-1` |
| Verify CR | `verify_cr` | Button | Starts the Sijilat preview and confirmation flow |
| Apply Secret Price List | `apply_secret_price_list` | Button | Opens the controlled protected Price List selector |
| Business Verification Status | `business_verification_status` | Select | `Not Verified`, `Pending`, `Verified`, `Rejected`, or `Expired` |
| CR Expiry Date | `cr_expiry_date` | Date | Expiry returned by Sijilat |
| Verified Business Details | `verified_business_details` | Small Text | Saved legal name, CR status, activities, address and related information |
| Last Sijilat Check | `last_sijilat_check` | Datetime | Last manual or automatic Sijilat check |
| Sijilat Recheck Attempts | `sijilat_recheck_attempts` | Int | Monthly automatic attempts in the current expiry cycle |
| Default Price List | `default_price_list` | Link | The Customer's explicitly assigned protected Price List, when applicable |

The two scheduler tracking fields are read-only and cannot be copied to another
Customer.

### 3.2 Price List field

| Label | Fieldname | Type | Meaning |
|---|---|---|---|
| Only for verified customers | `only_for_verified_customers` | Check | Marks an enabled Selling Price List as protected/secret |

The original label remains for compatibility. In the current design, the checkbox means
**protected Secret Price List**; CR verification is not required to receive it.

Multiple protected Price Lists are supported. The assignment dialog lists every Price
List where:

- `only_for_verified_customers = 1`
- `enabled = 1`
- `selling = 1`

### 3.3 Sales transaction item fields

The following fields exist on Quotation Item, Sales Order Item and Sales Invoice Item:

| Label | Fieldname | Type | Purpose |
|---|---|---|---|
| Regular Price List Rate | `regular_price_list_rate` | Currency | Snapshot of the global regular Selling Price List rate |
| Applied Price List | `applied_price_list` | Link to Price List | Identifies whether the protected list or regular fallback supplied the item price |

Do not reuse `pb_price_list` or `pb_price_list_rate`. Those fields belong to the older
POS Bahrain offer system.

Quotation Item, Sales Order Item and Sales Invoice Item also contain the read-only
fields `total_discount_percentage` (Percent) and `total_discount_amount` (Currency).
The standard ERPNext `discount_percentage` continues to represent only the reduction
from the transaction's selected `price_list_rate` to its final `rate`. For stock items,
the custom complete discount is:

```text
(regular_price_list_rate - rate) / regular_price_list_rate * 100

qty * (regular_price_list_rate - rate)
```

This lets sales users see the complete reduction from the ordinary customer price,
including both protected-price savings and any additional item discount. If the regular
comparison rate is unavailable, the selected `price_list_rate` is used as the baseline.
The value is zero when no positive reduction exists. It is informational and does not
participate in ERPNext's rate calculation.

### 3.4 Sales transaction pricing summary fields

Quotation, Sales Order and Sales Invoice contain the following read-only
transaction-currency fields. Quotation and Sales Order calculate them during
validation; the normal mapped document flow carries the corresponding values and item
snapshots forward to Sales Invoice:

| Label | Fieldname | Meaning |
|---|---|---|
| Subtotal (Regular) | `regular_price_list_subtotal` | Regular comparison value before protected-price savings |
| Total Item Discount | `total_item_discount` | Sum of each item's complete `total_discount_amount`, measured from the regular comparison price |

The visible summary intentionally uses only these two custom values. Protected-price
savings and any further item-level discount are combined into one understandable
discount amount:

```text
Subtotal (Regular)
    - Total Item Discount
    = ERPNext Total
```

When an item has no regular comparison price, its selected `price_list_rate` becomes
the comparison baseline. When an item falls back to the regular Price List, the fallback
rate becomes both its actual and comparison rate, so it creates no artificial saving.

`total_item_discount` is intentionally source-neutral. It includes both protected-price
savings and any further item-level discount because it is the sum of the child rows'
`total_discount_amount`. ERPNext's parent-level Additional Discount remains separate.
The older Quotation fields `special_price_savings` and `price_list_subtotal` may still
exist for backward compatibility, but they are not part of the current form or print
presentation.

## 4. CR verification workflow

### 4.1 Eligibility

The **Verify CR** button is available when:

- Customer Type is `Company`;
- Territory is `Bahrain`;
- the Customer has already been saved.

The CR must use this format:

```text
4 to 6 base digits - 1 to 3 branch digits
Example: 90666-1
```

Alphabetic characters, a missing branch and invalid lengths are rejected before calling
Sijilat.

Leading/trailing spaces and spaces around the hyphen are harmless formatting and are
normalized before validation. For example, ` 78860 - 1 ` becomes `78860-1`. The
Customer form saves the canonical value before continuing verification, and successful
automatic verification also stores the canonical value. Other separators and invalid
characters remain rejected.

### 4.2 Preview stage

`get_customer_cr_verification_preview(customer)`:

1. Checks Customer write permission.
2. Validates Company type, Bahrain territory and CR presence.
3. Fetches current information from Sijilat.
4. Confirms the returned CR matches the requested CR.
5. Displays the current Customer name and official Sijilat commercial name.
6. Highlights a name mismatch.
7. Displays CR status, expiry and business details.
8. Makes no database changes.

### 4.3 Name-similarity protection

The Customer name is normalized and compared with both the English and Arabic Sijilat
commercial names. Normalization ignores letter case, punctuation, spacing, word order and
common legal suffixes such as `W.L.L`, `WLL`, `CO`, `COMPANY`, `SPC`, `LLC`, `LTD` and
`ESTABLISHMENT`. Character similarity allows ordinary spelling mistakes.

| Similarity | Result |
|---|---|
| Above 50% | Approved; normal verification may continue |
| 50% or below | Blocked as an unrelated name |

For a blocked name, the preview deliberately does not return or display the official
Sijilat name, business details, CR expiry or current CR status. This prevents the dialog
from teaching a user which Customer name to enter. There is no confirmation button.

The similarity result is recalculated on the server during confirmation. Client-side
changes or a direct API call cannot bypass it. There is no manager-review level; any user
who can normally perform CR verification may proceed when the score is above 50%.

Name similarity reduces misuse but does not prove that the person presenting the number
owns or represents the CR. Staff should request supporting authorization for sensitive
or high-value cases.

### 4.4 Confirmation stage

When the user selects **Use Sijilat Name & Verify**,
`confirm_customer_cr_verification(customer)` re-fetches Sijilat rather than trusting the
preview.

It then:

- rejects duplicate CR numbers assigned to another Customer;
- rejects expired, inactive, cancelled, deleted or struck-off records;
- replaces the Customer name with the official English commercial name;
- stores the formatted Sijilat details;
- stores the CR expiry date;
- sets verification status to `Verified`;
- records the Sijilat check time;
- resets automatic recheck attempts to zero.

It does **not** assign, remove or change a Price List.

### 4.5 Verification invalidation

Changing any verified identity input invalidates the saved verification:

- CR number;
- Customer Type;
- Territory;
- Customer Name.

The status becomes `Not Verified`; business details, expiry and scheduler tracking values
are cleared. Secret pricing remains unchanged because it is a separate commercial
authorization.

### 4.6 Customer list badge

A blue scalloped verification badge is shown in Customer List for records whose
`business_verification_status` is `Verified`. The badge is only a visual indicator; it
does not authorize pricing.

## 5. Applying a Secret Price List

### 5.1 Permissions

Only users with either of these roles can see and use **Apply Secret Price List**:

- `Accounts Manager`
- `System Manager`

The role is checked again on the server. Hiding the button is not considered security.
The user must also have write permission on the Customer.

### 5.2 Assignment flow

1. Save the Customer and finish any unsaved changes.
2. Click **Apply Secret Price List**.
3. The server returns all enabled protected Selling Price Lists.
4. The current protected list is preselected; otherwise, the first available list is the
   default.
5. Select a Price List and click **Apply Price List**.
6. The server validates the Price List again and stores it in
   `Customer.default_price_list`.

This action works for companies, individuals, verified Customers and unverified
Customers. It represents management approval, not legal verification.

### 5.3 Protection against manual assignment

`validate_customer_secret_price_list_assignment` prevents a Customer from being changed
from a regular/unassigned Price List to a protected Price List through an ordinary save.
The server permits the change only when it comes through the controlled assignment
method.

The normal Default Price List selector is also filtered to exclude protected lists.
Existing protected assignments remain visible and can be saved unchanged.

## 6. Sales transaction authorization

The logic runs on validation of:

- Quotation;
- Sales Order;
- Sales Invoice.

When the transaction uses an ordinary Price List, the protected-pricing logic does not
interfere.

When it uses a protected Price List:

1. The Price List must be enabled and marked as Selling.
2. The transaction must belong to a Customer.
3. The transaction's `selling_price_list` must exactly equal that Customer's
   `default_price_list`.

CR status, Customer Type and Territory are deliberately not part of this authorization.
Selecting another protected list manually is blocked even if the Customer has access to
a different protected list.

A linked submitted Sales Invoice return may preserve the original Customer and protected
Price List so historical returns are not broken by later master-data changes.

### 6.1 Temporary sales lockdown

Protected pricing is temporarily locked while Accounts completes item prices and the
sales print formats are prepared. The application constant is:

```python
SECRET_PRICING_SALES_ENABLED = False
```

While the value is `False`:

- users without the `System Manager` role cannot save a Quotation, Sales Order or Sales
  Invoice using a protected Price List;
- System Managers may use protected pricing without the temporary restriction;
- linked submitted Sales Invoice returns remain allowed;
- regular Price Lists are unaffected; and
- Accounts may continue maintaining the protected Price List and its Item Prices.

Customer assignment remains available, but assignment does not allow ordinary users to
use the protected list during the lockdown. When pricing and print formats are ready,
change `SECRET_PRICING_SALES_ENABLED` to `True`; the normal Customer-assignment
authorization described above then resumes.

## 7. Item pricing and regular-price fallback

The global regular comparison list is read from **Selling Settings → Default Price
List**. It must be an enabled ordinary Selling Price List, not a protected one.

For each item on a protected transaction, the system respects transaction date, UOM,
conversion factor, quantity, item variants, Price List currency and transaction currency.

### 7.1 Result matrix

| Protected item price | Regular item price | Actual result | `regular_price_list_rate` | `applied_price_list` |
|---|---|---|---|---|
| Exists | Exists | Protected rate is used | Regular rate | Protected Price List |
| Exists | Missing | Protected rate is used | `0` | Protected Price List |
| Missing | Exists | Regular rate becomes the actual fallback rate | Regular rate | Global regular Price List |
| Missing | Missing | Existing ERPNext zero/manual-rate behavior remains | `0` | Blank |

When fallback is applied, the item `price_list_rate` and `rate` are updated to the
converted regular rate and taxes/totals are recalculated.

On an ordinary non-protected transaction, `regular_price_list_rate` stores the item's
current `price_list_rate`. `applied_price_list` is cleared because no protected-price or
regular-fallback source decision is required. This also prevents a stale protected-list
source copied from another document.

Quotation and Sales Order summary fields are recalculated on validation after the
protected-price and regular-fallback decisions are complete. They do not replace or
modify ERPNext's standard `total`, `net_total`, taxes, Additional Discount or grand
total calculations. Sales Invoice still runs protected-list authorization and item-rate
fallback; in the normal Quotation -> Sales Order -> Sales Invoice flow, its custom
display fields are carried from the mapped source document. A future direct-Sales-
Invoice requirement must be tested separately before relying on automatic summary
calculation there.

### 7.2 Dynamically priced service items

Only stock-maintained items (`Item.is_stock_item = 1`) participate in regular-versus-
protected price comparison in the active Quotation and Sales Order summary calculation.
A service/non-stock item's Item Price may be a placeholder used to load the row, while
its final `rate` is calculated from production or packed-item logic. After that
calculation, validation normalizes the service row as:

```text
price_list_rate = unchanged (actual selected Item Price/placeholder)
regular_price_list_rate = 0
discount_percentage = 0
discount_amount = 0
total_discount_percentage = 0
total_discount_amount = 0
applied_price_list = blank
```

Service rows are then excluded from protected-price lookup and regular-price fallback.
The placeholder `price_list_rate` is not presented as a comparison price. Their actual
`amount` contributes equally to the regular and used Price List subtotals, so they
create no artificial savings or discount while the sales transaction continues to
reconcile to ERPNext's standard total. In print, a service item therefore shows its
actual unit rate and no artificial Total Discount. Stock-item behavior is unchanged.

## 8. CR expiry and automatic Sijilat rechecks

Verification scheduling is independent of Secret pricing. Expiry or rejection never
removes the Customer's protected Price List.

### 8.1 Daily local expiry job

Scheduler method:

```text
worldshading.api.sijilat.mark_expired_customer_crs
```

The job uses saved data only; it does not call Sijilat. It selects Customers with:

- status `Verified`;
- an expiry date earlier than today;
- saved Sijilat business details.

It changes the status to `Expired` and starts a new automatic recheck cycle with zero
attempts.

The expiry date itself remains stored for audit and display.

### 8.2 Monthly recheck dispatcher

Scheduler method:

```text
worldshading.api.sijilat.enqueue_expired_customer_cr_rechecks
```

It selects only Customers with:

- status `Expired`;
- a CR number;
- saved Sijilat details;
- fewer than three attempts;
- no automatic check during the previous month.

Each Customer is sent to an individual short background job. This avoids one long job
and isolates a failure to one Customer.

### 8.3 Individual recheck

Worker method:

```text
worldshading.api.sijilat.recheck_expired_customer_cr
```

Before contacting Sijilat, the worker records the attempt and check time. Therefore, API
connection failures also count toward the maximum of three automatic attempts.

| Sijilat result | Customer result |
|---|---|
| Active with future expiry | Status becomes `Verified`; details and expiry update; attempts reset to `0` |
| Still expired | Status remains `Expired`; returned details/expiry update; attempt remains counted |
| Inactive/deleted/cancelled | Status becomes `Rejected`; monthly expired checks stop |
| Network/API/decryption error | Existing status, details and expiry remain unchanged; error is logged |

After three unsuccessful automatic attempts, no more monthly jobs are queued for that
expiry cycle. Staff can still click **Verify CR** manually. A successful manual
verification resets the attempt counter.

### 8.4 Historical data safeguard

`cr_expiry_date` existed before this project and was historically editable. During the
production audit on 16 September 2026:

- 6,172 Customers existed;
- 1,859 had historical/manual expiry values;
- only three were marked `Verified` through the new workflow.

For this reason, scheduler queries must never select all records by expiry date alone.
The status and saved Sijilat-details filters are mandatory.

### 8.5 Historical Customer auto-verification

This one-way migration gradually checks existing Customers that were created before the
verification workflow. It uses two methods:

```text
worldshading.api.sijilat.enqueue_existing_customer_cr_verification
worldshading.api.sijilat.auto_verify_existing_customer_cr
```

The dispatcher runs every five minutes and queues at most one Customer. Untouched
eligible Customers are processed from newest to oldest. A Customer is eligible only
when it is enabled, its Type is `Company`, its Territory is `Bahrain`, it has a CR
number, its Business Verification Status is empty, and it has fewer than three
temporary-error attempts.

The worker validates CR format and duplicate use before contacting Sijilat. When the CR
is active and unexpired and the existing name has more than 50 percent similarity with
the official name, it:

- replaces Customer Name with the official English commercial name;
- stores the verified business details and expiry date;
- sets Business Verification Status to `Verified`; and
- resets the attempt counter.

ERPNext saves the Customer normally, so its activity/version history retains the name
change. The job never assigns, removes or modifies a Secret Price List.

When Sijilat identifies a valid but expired CR and the existing Customer name has more
than 50 percent similarity with the official name, the worker applies the official
English commercial name, stores the returned business details and expiry date, and sets
the status to `Expired`. The attempt counter is reset to zero, so the normal monthly
expired-CR process can try up to three times to detect a renewal. Discovering the
expired CR during historical verification does not consume one of those three monthly
recheck attempts.

Invalid or duplicated CRs, rejected records, missing or mismatched Sijilat identity,
and name similarity of 50 percent or lower become `Not Verified`. The official Sijilat
identity and details are not stored for these Customers.

Network, token, timeout, server, parsing and decryption failures are temporary. The
status remains empty for the first two failures, with at least 24 hours before another
attempt. The third temporary failure changes the status to `Not Verified`. Staff can
still use **Verify CR** manually afterward.

There is no separate manual-review queue or migration audit record. To stop new
automatic checks, remove or comment the dispatcher entry in the five-minute cron group
and follow the normal deployment procedure. Already queued jobs must be allowed to
finish or handled through the normal worker process. Already renamed Customers are not
automatically reverted; restore them individually using ERPNext activity/version
history when necessary.

## 9. How the Sijilat integration works

The integration currently follows the public Sijilat web application's request flow:

1. Generate the encrypted token password expected by Sijilat.
2. Request a bearer token from the Sijilat token endpoint.
3. Build the CR and branch request payload.
4. Encrypt it using the required AES-compatible envelope.
5. Call the complete CR-details endpoint.
6. Parse and normalize the returned company summary, activities and address.

Although CR search is publicly available, this should be treated as an external,
best-effort integration rather than a guaranteed permanent API contract. Sijilat may
change its token flow, encryption, headers, endpoint paths, response fields or access
policy.

Operational rules:

- never erase saved verification data because of an API error;
- use timeouts and error logging;
- keep manual verification available;
- avoid bulk synchronous calls;
- do not make pricing depend on Sijilat availability;
- monitor failures after any Sijilat website release.

The integration currently contains technical credentials in application source. A future
hardening task should move all secrets into protected site configuration or a Single
DocType with Password fields. Never copy credential values into this documentation.

## 10. Important invariants

Future changes must preserve these rules:

1. CR verification and Secret pricing are independent.
2. Verification preview never writes data.
3. Confirmation always re-fetches Sijilat.
4. Blocked name matches never expose the official Sijilat identity in the preview.
5. Name similarity is enforced again on the server during confirmation.
6. Scheduled checks never change the Customer name.
7. Scheduled checks never assign or remove a Price List.
8. A protected transaction list must exactly match the Customer assignment.
9. Missing protected item prices fall back to the regular item price when available.
10. Existing zero/manual-rate behavior remains when neither price exists.
11. Historical manual expiry dates are not automatically treated as Sijilat verification.
12. POS Bahrain `pb_*` pricing fields remain separate.

## 11. Operational testing checklist

### Customer verification

- Company + Bahrain + valid CR shows a preview.
- Invalid CR format is rejected before an API call.
- Duplicate CR is blocked.
- Legal suffixes, spelling mistakes and word-order differences score as related names.
- A clearly unrelated name is blocked without revealing the official name or details.
- A score of exactly 50% remains blocked; only scores above 50% are approved.
- Confirmation updates the official name, status, expiry, details and check time.
- Confirmation does not change the Customer Price List.
- Changing identity data invalidates verification but preserves Secret pricing.

### Secret Price List

- Accounts Manager/System Manager sees the button.
- Other users do not see it and are rejected by the server if they call the method.
- One protected list is preselected automatically.
- Multiple protected lists are selectable.
- Individual and unverified Customers can receive an approved list.
- Ordinary manual assignment of a protected list is blocked.

### Transactions

- Assigned protected list works on Quotation, Sales Order and Sales Invoice.
- An unassigned/different protected list is blocked.
- A configured B2B item uses its protected rate.
- A missing B2B item rate falls back to the regular rate.
- `Applied Price List` records the correct source.
- A missing regular comparison does not block a valid B2B item.
- Ordinary Quotation and Sales Order rows store their current Price List rate as the
  regular comparison rate.
- Stock-item `T.Discount (%)` and `T.Discount Amount` include protected-price savings
  plus any further item discount.
- Service items show no artificial discount and continue using their calculated rate.
- `Subtotal (Regular) - Total Item Discount = Total` for Quotation and Sales Order.
- Packed-parent pricing completes before the custom discount summary is calculated.
- Linked Sales Invoice returns remain possible.

### Print formats

- Item U.Discount is hidden when the document has no item discount.
- Stock items show the regular/default comparison rate as U.Price and their complete
  per-unit discount amount.
- Dynamically priced service items show their actual unit rate and no fake discount.
- Wholesale Discount equals `total_item_discount` and reconciles Subtotal to Total.
- VAT rows show the actual tax rate, including a zero amount when applicable.
- Shipping-charge rows are labelled as shipping rather than VAT.
- The Wholesale Discount row remains green and bold in both preview and browser/PDF
  printing.

### Scheduler

- A verified record expires only after its expiry date passes.
- Historical records with only manual dates remain untouched.
- Monthly dispatcher does not queue more than once per month.
- Attempts stop at three.
- Renewed CR returns to `Verified`.
- Rejected CR stops expired rechecks.
- API failure retains existing saved data and creates an Error Log.
- Historical migration queues no more than one blank-status Customer every five minutes.
- Historical migration retries temporary failures only after 24 hours and stops at three.
- Historical migration never changes Secret Price List authorization.

## 12. Deployment and maintenance notes

Changes to Python hooks or scheduler configuration require the application's normal
deployment/process reload before workers use the new hook configuration. Do not run
restart, migrate, cache-clear or scheduler commands casually on the production server.
Follow the production change procedure and take a backup when a future deployment
requires those operations.

When adding a new protected Price List:

1. Create/enable the Selling Price List.
2. Set its currency correctly.
3. Check `only_for_verified_customers`.
4. Add Item Prices.
5. Test assignment with an authorized user.
6. Test one item with a protected rate and one regular fallback item.
7. Confirm transaction validation rejects the list for an unassigned Customer.

## 13. Print formats

Print presentation is intentionally separate from the pricing calculation. The current
custom rollout covers:

| Document | Print format |
|---|---|
| Quotation | `PROFORMA INVOICE - WS` |
| Quotation | `PROFORMA INVOICE WITH DESCRIPTION - WS` |
| Sales Order | `PROFORMA INVOICE - SO` |
| Sales Order | `PROFORMA INVOICE WITH DESCRIPTION - SO` |
| Sales Invoice | `SALES INVOICE - WS` |
| Sales Invoice | `SALES INVOICE WITH DESCRIPTION - WS` |
| Sales Invoice | `Sales Invoice with Terms` |
| Sales Invoice | `Dot Matrix Invoice` |
| Sales Invoice | `POS Printer` |

The formats use the following presentation rules:

1. The item U.Price is the regular/default comparison rate for stock items.
2. Dynamically priced service items show their actual `rate` because a placeholder Item
   Price is not a meaningful comparison price.
3. `U.Discount` is the complete discount per unit, calculated for print as
   `total_discount_amount / qty`. The underlying item field continues storing the full
   row discount amount. Positive U.Discount values use `#22A06B` and bold text for
   emphasis; the heading and zero-value dash retain the normal table styling.
4. The U.Discount column is omitted when every item has zero complete discount.
5. The totals section shows Subtotal, Wholesale Discount, Total, applicable taxes or
   shipping, rounding and Grand Total.
6. Wholesale Discount is `total_item_discount`; it combines protected-price savings
   and further item discounts.
7. Tax and shipping rows use the Sales Taxes and Charges row description/type. A
   shipping-only charge is shown as shipping rather than being labelled VAT. VAT is
   still shown when its calculated amount is zero.
8. The Wholesale Discount label and amount use `#22A06B`, bold text and cell-level
   `!important` styling so Frappe/Bootstrap print CSS does not force them back to black.

These formats are database Print Format records. Changes to them do not require a
bench restart or migration, although an already-open print page may need to be refreshed
before reopening the browser print dialog.

## 14. Custom-app packed pricing

`worldshading.api.quotation_packed_pricing.apply_quotation_packed_pricing` is the
active custom-app replacement for the Server Script
`quotation packed item & warranty calculation`. The old Server Script is disabled and
the replacement is registered in the Quotation validation hooks. Do not enable the old
script while the hook is active.

Active Quotation validation order:

```text
Production BOM validation
    -> custom-app packed item / parent / warranty pricing
    -> ERPNext taxes and totals
    -> regular and protected pricing summaries
```

Calculated bundle/service parents and the `QC7026` warranty row use ERPNext margin
fields when their calculated rate differs from the placeholder Item Price. This keeps
the calculated rate from appearing as a negative discount and allows ERPNext totals to
recalculate without replacing it. Warranty remains 15% of all non-warranty item
amounts and is calculated after the packed parent rates are final.

Rollback removes the custom-app hook and re-enables the old Server Script. Never leave
both active because that would calculate and message twice.
