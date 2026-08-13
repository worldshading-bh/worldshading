# Online Payments — BENEFIT and KFH MPGS

Customers pay an invoice online by card. They choose Debit or Credit, pay on the bank's
own page, and the payment posts itself against the invoice.

Status, 12 August 2026:

| Gateway | State |
|---|---|
| **BENEFIT** (Debit Card) | **Live in test and certified.** All four scenarios passed; payments settle end to end |
| **KFH MPGS** (Credit Card) | **Gateway payment verified.** A BHD 47.300 test reached `CAPTURED` after unique order and transaction references were added; ERP settlement awaits a valid Bank/Cash deposit account |

---

## Read in this order

| # | Document | For |
|---|---|---|
| 1 | **`architecture.md`** | How the whole thing fits together. Start here. |
| 2 | **`benefit_gateway.md`** | The BENEFIT protocol — AES envelope, purchase flow, result codes, test cards, and where the live gateway contradicts its own PDF |
| 3 | **`kfh_mpgs.md`** | The MPGS protocol, what is verified, and the exact blocker |
| 4 | **`operations.md`** | Running it: setup, daily checks, what to do when a payment goes wrong |
| 5 | **`integration_profile.md`** | **Give this to a bank.** One page, no secrets — who we are, what we implemented, certification results, and what we need |
| — | `open_questions.md` | Decisions and questions still outstanding |
| — | `vendor/` | Supplier documents, unmodified |

---

## The shape of it

```
Sales Invoice
   └─ Payment Request            ERPNext's own doctype — we did not replace it
        └─ payment link  ──►  /payment-methods        the customer chooses
                                   ├─ Debit Card  ──►  BENEFIT hosted page
                                   └─ Credit Card ──►  MPGS hosted page
                                            │
                                   bank confirms, server to server
                                            │
                                   ──►  Payment Entry, posted and submitted
```

Three doctypes, and no more:

| Doctype | Holds |
|---|---|
| `WS Payment Gateway` | One **row per gateway**, including the router. Credentials, accounts, presentation |
| `WS Payment Transaction` | One row per payment **attempt**. Correlation keys, raw payloads, settlement state |
| `Payment Gateway` (core) | Frappe's registry. A signpost pointing at our rows |

---

## The rules that hold this together

**Card data never touches our server.** Every card field is entered on the bank's page.
That is what keeps us out of PCI SAQ D, and it is the reason both gateways are
redirect-style. Do not add a card field to any page in this app.

**Never post money on a browser redirect.** A customer's browser can be closed, replayed
or forged. Accounting entries are made only after a server-to-server confirmation, and
for MPGS only after RETRIEVE ORDER confirms it.

**Settlement is idempotent, under a row lock.** Two success signals routinely arrive for
one payment. One payment must never become two Payment Entries.

**Never guess about money.** An outcome we do not recognise is flagged for a human. It is
never assumed to be a failure, and never assumed to be a success.

**Adding a gateway is a row, not a doctype.** A new gateway needs a `WS Payment Gateway`
record, a client module, and one line in the client registry. Nothing else changes.
