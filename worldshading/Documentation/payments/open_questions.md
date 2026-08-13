# Open Questions

What is still outstanding, and who owns it. Everything settled has been moved into the
other documents.

Last reviewed: 12 August 2026

---

## 1. KFH MPGS — gateway verified

Mastercard confirmed that merchant `TEST200007408` enforces unique order and merchant
transaction references. The code now supplies both fields. The 12 August retest reached
`CAPTURED` and created an approved MPGS `PAYMENT` transaction.

Before retesting ERP settlement, replace the temporary `BDB Credit Card - WS` deposit
account with a Finance-approved account whose Account Type is Bank or Cash. Then retry
settlement for captured transaction `WSPAY-2026-00052`.

Still needed for go-live: production **gateway host and merchant ID** (the `TEST`
prefix is test-only).

## 2. With BENEFIT — not blocking

Certification passed; these matter for production and for reliability.

1. The **production API endpoint path**. The guide names the host
   `https://www.benefit-gateway.bh` but not the path; we assume the test path.
2. The **Inquiry (`action=8`) request and response format for the REST endpoint**. It is
   documented only for the older Tranportal HTTP plug-in. The unverified request path
   was removed before production; reconciliation flags these cases for manual review.
3. The **test OTP**, and whether OTP is always required or only a risk step-up. It
   appeared after several rapid attempts on one card and cleared afterwards.

## 3. Planned, not built

### Payment against a Quotation — decided, deferred

Wanted: take a deposit to confirm a quotation. Sometimes the full value, sometimes a
percentage.

**Decided approach: post it as an unallocated customer advance.** A Payment Entry
against the Customer with no reference row, allocated later when the Sales Order or
Invoice exists. Chosen because the amount varies: a percentage deposit must not
auto-create a Sales Order, and an advance handles any amount naturally.

Rejected: converting the Quotation to a Sales Order on payment. It would give a proper
reference chain, but submitting a Sales Order here triggers workflow state, Service Visit
linking and `create_order_specific_boms` — far too much to set in motion because a
customer tapped Pay, especially on a part payment.

Why it is not a small change — ERPNext deliberately does not support this, because a
quotation creates no obligation:

- `get_payment_entry()` has no `party_type` branch for Quotation, and Payment Entry
  Reference accepts a closed list that excludes it
- `get_amount()` has no Quotation branch, and `validate_payment_request_amount()` calls
  it again on any second request (Quotation has `order_type`, so that check runs)
- `update_payment_req_status()` reads `outstanding_amount`, which Quotation lacks, so
  the request would never reach `Paid` on its own

Work involved: our own creation path on Quotation rather than `make_payment_request`; a
settlement branch that builds the advance directly; marking the request Paid ourselves; a
link guard rule that does not rely on `outstanding_amount`; and a way to enter the
deposit amount. Roughly half a day plus testing.

**Note: Sales Order deposits already work today with no code at all** —
`grand_total − advance_paid`, posted as a proper advance. If the need is "take money
before committing crew and materials", that is the supported place to do it.

## 4. Ours to decide

1. **`order.id` per attempt or per request (MPGS).** We send `track_id`, so each attempt
   is its own order. Using a stable order id per Payment Request would let the gateway
   itself refuse a second capture — double-pay protection for free — at the cost of
   less direct correlation. Our link guards already prevent this; worth revisiting
   before go-live.
2. **Refunds.** Deliberately not built. BENEFIT needs acquirer approval, separate
   certification and a 14-day window; MPGS supports REFUND but it is untested. Portal
   refunds work today for both.
3. **Wallets.** Google Pay already appears on the MPGS hosted page with no work from us.
   Apple Pay and the BenefitPay app need each bank to say whether they arrive the same
   way or need separate integration.

## 5. Environment

1. **`pause_scheduler` is set on this site**, so reconciliation never fires by itself.
   Enqueued jobs still run, which is why settlement works. Must be resumed before
   production.
2. `disable_email` is set, so Payment Request emails do not send here — payment links
   have to be copied off the form by hand.
3. This is the **demo/staging** instance (`demo.worldshading.com`). Production is a
   separate instance with its own credentials.

## 6. Housekeeping

1. **`vendor/*.txt` files contain live test credentials** — BENEFIT's Tranportal password
   and resource key. They are gitignored, but they sit in the app directory. Move them
   to `/home/erpadmin/gateway-docs-private/` if that folder is ever shared.
2. **Browser autofill writes credentials into hidden fields** on the gateway rows —
   BENEFIT's password onto the MPGS row and vice versa. Cleared 11 August 2026; check
   again after editing a gateway row.
3. `vendor/MPGS/mpgs_guide_note_from_website.txt` is third-party analysis, not a supplier
   document. Accurate in the main, but it gives `PAY` where the enum value is `PURCHASE`,
   and cites `interaction.action.3DSecure = BYPASS` (the field is real; that value is
   documented, but it was unverified when written).
