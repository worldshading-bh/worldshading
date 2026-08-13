# Integration Profile — for BENEFIT, KFH and Mastercard

A single page answering the questions an acquirer or gateway support team asks. Safe to
share: it contains no credentials, no keys and no card data.

Last verified: **12 August 2026**

---

## 1. Who we are and what we run

| | |
|---|---|
| Merchant | World Shading, Kingdom of Bahrain |
| Platform | **ERPNext v12.26.0** on **Frappe Framework v12.16.3** — an open-source ERP |
| Server | Python 3.6, MariaDB, Ubuntu Linux |
| Integration | Custom application module inside our ERPNext instance. No third-party plug-in, no shopping-cart product, no hosted e-commerce platform |
| Environment under test | `https://demo.worldshading.com` — a **demonstration/staging** instance, publicly reachable over HTTPS on port 443 with a valid certificate |
| Production | A separate ERPNext instance. Credentials and endpoints will be issued separately at go-live |

**Note on the environment.** `demo.worldshading.com` is a staging copy used solely for
integration testing. It holds no live customer payments. Production go-live will use a
different host, and we will request production credentials from each acquirer at that
point.

## 2. What our integration does

We raise an invoice in ERPNext and send the customer a payment link. The customer
chooses **Debit Card** or **Credit Card**, is taken to the acquirer's own hosted payment
page, pays there, and returns to us. On confirmation we post the payment against the
invoice automatically.

**Card data never reaches our server.** Card number, expiry, CVC and PIN are entered
only on the acquirer's hosted page. We never see, transmit or store them, which keeps us
outside PCI DSS SAQ D. This was a deliberate constraint on the design, not a
side effect.

## 3. Integration method per gateway

### BENEFIT Payment Gateway

| | |
|---|---|
| Method | **REST API**, bank-hosted purchase (`/payment/API/hosted.htm`) |
| Why not the plug-in | BENEFIT ships plug-ins for Java, .NET and PHP only. Our platform is Python, so we implemented the documented AES envelope directly |
| Encryption | AES-256-CBC, PKCS7, static IV `PGKEYENCDECIVSPC`, uppercase hex, plaintext URL-encoded before encryption, per Integration Guide v1.4 §4.2–4.4 |
| Transaction | `action=1` (Purchase), currency `048` (BHD), amount as a decimal string at 3 dp |
| Merchant Notification | Enabled. We reply with `REDIRECT=<url>` and nothing else, then process asynchronously |
| Status | **Certified — all four scenarios passed, 10 August 2026** |

### KFH MPGS (Mastercard Payment Gateway Services)

| | |
|---|---|
| Method | **Hosted Checkout** |
| API | REST-JSON, **version 100**, HTTP Basic auth as `merchant.<merchant ID>` |
| Operation | `INITIATE_CHECKOUT` with `interaction.operation = PURCHASE` |
| Payment page | Mastercard's `checkout.min.js` → `Checkout.showPaymentPage()` |
| Result | `resultIndicator` compared against the stored `successIndicator`, then confirmed authoritatively with **RETRIEVE ORDER** before any accounting entry is made |
| Notifications | Webhook, verified via the `X-Notification-Secret` header |
| Currency | BHD only (confirmed by the gateway itself) |
| Status | **Gateway payment verified through capture** — see §5; ERP posting awaits a valid Bank/Cash deposit account |

## 4. BENEFIT certification results

Completed 10 August 2026 against the test terminal, Tranportal ID `200007408`.

| # | Scenario | Result | Payment ID |
|---|---|---|---|
| 1 | Approved | `CAPTURED` | `119202622279638127` |
| 2 | Declined | `NOT CAPTURED` | `119202622278759804` |
| 3 | Cancelled | `CANCELED` | `119202622278700186` |
| 4 | Denied by risk | `DENIED BY RISK` | `119202622222002897` |

Further approved transactions: `119202622278118956`, `119202622221920234`,
`119202622221905521`, `119202622221984834`.

Multiple payments settled end to end without manual intervention.

**Open questions for BENEFIT**

1. The test OTP, and whether OTP applies always or only as a risk step-up. An OTP step
   appeared after several rapid attempts on one card and cleared afterwards.
2. The **production API endpoint URL**. The guide names the host
   `https://www.benefit-gateway.bh` but not the full path; we currently assume
   `/payment/API/hosted.htm` as in test.
3. The Inquiry (`action=8`) request and response format **for the REST endpoint**. It is
   documented only for the older Tranportal HTTP plug-in. We use it to reconcile
   payments where a notification was lost.

## 5. KFH MPGS — unique-reference fix verified

**Merchant `TEST200007408`, `test-bh-kfh.mtf.gateway.mastercard.com`, API v100.**

Verified working:

- Authentication as `merchant.TEST200007408`
- `INITIATE_CHECKOUT` returns `201` / `result: SUCCESS` with a session and successIndicator
- The hosted payment page opens, correctly branded, with the correct BHD amount
- **3-D Secure v2 completes successfully** — `AUTHENTICATION_SUCCESSFUL`,
  `transactionStatus: "Y"`, ECI 02, protocol 2.2.0, `gatewayCode: APPROVED`,
  `gatewayRecommendation: PROCEED`

Not working:

> After successful authentication, **no payment transaction is ever created.** The order
> remains at `status: AUTHENTICATED` with `totalAuthorizedAmount: 0` and
> `totalCapturedAmount: 0`. There is no PURCHASE or AUTHORIZE transaction, not even a
> declined one. The customer is never charged.

Example orders: `260810000039` (2.000 BHD), `260810000033` (130.000 BHD).

**What we have ruled out, by direct test**

| Suspected cause | Evidence it is not the cause |
|---|---|
| Wrong card | Same result on Mastercard `5123450000000008` and Visa `4508750015741019` |
| Wrong merchant ID | `TEST200007408` authenticates and does 3DS; `200007408` reports `payerInteraction: NOT_POSSIBLE`, `authenticationVersion: NONE` |
| 3-D Secure | Passes cleanly. With `interaction.action.3DSecure: BYPASS`, **no transaction is created at all** and RETRIEVE ORDER returns *"Unable to find order"* |
| Wrong operation | Identical outcome with `PURCHASE` and with `AUTHORIZE` |
| Amount format | `25`, `25.00`, `25.000`, `25.0000` and numeric `25.0` all accepted at session creation |
| Wrong currency | Gateway states: *"Only the following currencies are supported: [BHD]"* — BHD is what we send |
| Malformed request | Every `INITIATE_CHECKOUT` returns `201 SUCCESS`; invalid input is rejected immediately and by name, as USD was |

**Root cause confirmed by Mastercard, 12 August 2026.** The API returned
`INVALID_REQUEST - Field must be set to a unique value`. Merchant `TEST200007408` has
both **Enforce Unique Merchant Transaction Reference** and **Enforce Unique Order
Reference** enabled, while the checkout request omitted `transaction.reference` and
`order.reference`.

The integration now sends `ORD-<track_id>` as `order.reference` and
`TXN-<track_id>` as `transaction.reference`. Each payment attempt already receives a
fresh `track_id`.

Retest order `260812000002` for BHD 47.300 completed successfully: the order reached
`CAPTURED`, both authorised and captured totals were BHD 47.300, and MPGS created an
approved `PAYMENT` transaction through `AUB_033042_S2I` with acquirer response code
`00`. This verifies the gateway fix.

ERPNext did not post the Payment Entry because the temporary deposit account was not
typed as Bank or Cash. This is local accounting configuration and is separate from the
verified MPGS payment flow.

For go-live we still need the **production gateway host and merchant ID**.

## 6. Security and operational posture

- Card data never touches our servers; all entry is on the acquirer's hosted page
- Credentials are stored encrypted in the application database, never in source code,
  and never written to logs
- All gateway traffic is HTTPS on default ports with valid certificates
- Every gateway request and response is logged for audit, as BENEFIT Integration Guide
  chapter 7 requires, including the payer's IP address
- Payments are posted to the ledger only after an authoritative server-to-server
  confirmation — never on a browser redirect alone
- Settlement is idempotent and locked, so a duplicated notification cannot produce a
  duplicate accounting entry
- Unresolved payments are re-checked automatically and flagged for human review rather
  than assumed failed

## 7. Contact

World Shading — IT Development
`it.development@worldshading.com`
