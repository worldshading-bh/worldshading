# Running It

Setup, daily checks, and what to do when a payment goes wrong.

---

## 1. Taking a payment

1. Open the **Sales Invoice** → **Payment Request** → set Payment Gateway Account to
   **`WS Payments - BHD`** (the router — this is what offers the customer a choice) →
   Submit
2. The **Payment URL** field now holds the link. Email is disabled on the demo site, so
   copy it by hand there
3. The customer opens it, picks a method, pays on the bank's page
4. A **Payment Entry** is created and submitted automatically; the Payment Request moves
   to **Paid** and the invoice's outstanding drops

If you point the Payment Request at `Benefit - BHD` or `KFH MPGS - BHD` instead, the
customer skips the chooser and goes straight to that gateway. Useful for testing, not
for normal use.

## 2. Configuration, in one place

**WS Payment Gateway** — one row per gateway.

| Row | Type | Purpose |
|---|---|---|
| `WS Payments` | Router | Shows the chooser. Takes no money, holds no credentials |
| `Benefit` | Benefit | Debit Card. Deposits to `Benefit - WS`, Mode of Payment `Benefit Pay` |
| `KFH MPGS` | KFH MPGS | Credit Card. Deposits to `BDB Credit Card - WS`, Mode of Payment `Credit Card` |

Every gateway row needs, without exception:

- **Enabled** — it appears on the chooser only while this is ticked
- **Method Label** — the button text
- **Deposit Account** — where its money lands
- **Mode of Payment** — mandatory on Payment Entry here; **settlement fails without it**
- **Display Order** — Debit 10, Credit 20

> **A gateway with no Mode of Payment will take the customer's money and then fail to
> post it.** That is not theoretical; it happened on the first live BENEFIT payment.
> Never tick Enabled before both accounting fields are set.

### Credentials

Entered directly into the row and stored encrypted. Never in code, never in logs.

**A warning about browser autofill.** Chrome has repeatedly filled credential fields that
are hidden by `depends_on` — writing BENEFIT's password onto the MPGS row and vice
versa. It is harmless, since each gateway reads only its own fields, but check after
saving that no other gateway's secrets were written.

## 3. Daily checks

**WS Payment Transaction** list, filtered on:

| Filter | Means | Do |
|---|---|---|
| **Needs Review = Yes** | The gateway never gave a clear answer. **Money may have been taken** | Look the order up in the bank's portal, then settle or fail it by hand |
| Status **Redirected**, older than an hour | Customer left the bank's page, or a callback was lost | Reconciliation will chase it; nothing manual unless it persists |
| Status **Captured**, Settled = No | The payment succeeded but no Payment Entry exists | See §4 |

`Initiated` rows are harmless — a link that was issued and never opened.

## 4. When something goes wrong

**Captured but not settled.** Money took, ledger did not. Look in **Error Log** for
`Payment settlement failed`. The usual cause is a missing Mode of Payment or deposit
account. Fix it, then:

```bash
bench --site erp.worldshading.com execute worldshading.payments.utils.settle \
  --kwargs "{'txn_name':'WSPAY-2026-000XX'}"
```

Safe to run twice — settlement is idempotent.

**A payment we know nothing about.** Force a sweep:

```bash
bench --site erp.worldshading.com execute worldshading.payments.reconcile.run
```

**Testing the MPGS connection** without touching a card:

```bash
bench --site erp.worldshading.com execute worldshading.payments.mpgs.ping
bench --site erp.worldshading.com execute worldshading.payments.mpgs.test_session
```

**Where to look**

| Source | Holds |
|---|---|
| The **WS Payment Transaction** record | Raw gateway payloads, decrypted result, correlation keys |
| `logs/frappe.log` | Every gateway request and response, logged before anything else touches it |
| **Error Log** | Tracebacks |
| `logs/worker.error.log` | Settlement failures |

## 5. Tests

```bash
bench --site erp.worldshading.com run-tests --module worldshading.payments.test.test_benefit
bench --site erp.worldshading.com run-tests --module worldshading.payments.test.test_mpgs
```

Pure unit tests — no database, no network, no records. They cover the places this can
produce a **wrong result** rather than an error: the AES envelope, BHD's three decimals,
result parsing, and the rule that only `CAPTURED` counts as success.

## 6. Going live

Nothing below is done, and none of it is a code change.

- [ ] **BENEFIT**: production Tranportal ID, password, resource key, and the confirmed
      production API path. Set Environment to Production
- [ ] **MPGS**: production host, merchant ID (**without** the `TEST` prefix) and API
      password. The prefix is test-only and will fail in production
- [ ] Both acquirers to whitelist the production host; whitelist their hosts outbound
- [ ] MPGS webhook URL and secret configured against production
- [ ] **Resume the scheduler** — `pause_scheduler` currently stops reconciliation
- [ ] Re-certify against production terminals
- [ ] Confirm the deposit accounts with Finance
- [ ] Re-check `Link Valid For (Days)` and the chooser labels

An enabled collecting gateway is validated on save. It must have a customer-facing
label, Mode of Payment, a deposit account whose Account Type is Bank or Cash, and all
required credentials. MPGS also requires its webhook secret. The MPGS operation is
fixed to `PURCHASE`, and 3-D Secure uses the gateway default; diagnostic overrides are
not exposed in production configuration.

## 7. Not built, deliberately

- **Refunds** through the API. BENEFIT needs acquirer approval, separate certification
  and a 14-day window; MPGS supports REFUND but it is untested here. Use the bank
  portals
- **Card storage / tokenisation.** BENEFIT's Faster Checkout exists; we do not store
  cards
- **Apple Pay, BenefitPay app.** Google Pay already appears on the MPGS hosted page
  without any work from us; the others need confirmation from each bank about how they
  are delivered
- **The ERPNext shopping cart.** Payment Request is how payments are collected here
