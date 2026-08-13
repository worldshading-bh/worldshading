# KFH MPGS — Hosted Checkout

Status: **gateway payment verified through capture.** Mastercard confirmed on 12 August
2026 that this merchant enforces unique order and transaction references. Both are now
sent for every attempt, and the first retest reached `CAPTURED`.

For the version to send a bank, see `integration_profile.md` §5.

---

## 1. Established facts

All confirmed by direct testing against the live gateway, not from documentation.

| | |
|---|---|
| Host | `https://test-bh-kfh.mtf.gateway.mastercard.com` |
| API version | **100** — probed directly; 101+ return 404 on `/information` |
| Gateway build | `26.7.0-123R`, status `OPERATING` |
| Auth | HTTP Basic, `merchant.<merchant ID>` : API password |
| Merchant (test) | **`TEST200007408`** — the `TEST` prefix is required for the card emulator |
| Currency | **BHD only.** The gateway states: *"Only the following currencies are supported: [BHD]"* |

`GET /api/rest/version/{v}/information` answers **without authentication** — a cheap way
to check a host and probe versions.

## 2. The two merchant profiles

On the same test host:

| Profile | Routes to | Behaviour |
|---|---|---|
| `200007408` | a real acquirer link, unconfigured | 3DS unavailable: `payerInteraction: NOT_POSSIBLE`, `authenticationVersion: NONE`, everything declined |
| **`TEST200007408`** | the **card emulator** | 3DS v2 works fully via `MPGS_ACS_SANDBOX` |

Use `TEST200007408` for all testing. **Production uses a different host as well as a
different merchant ID** — not merely the prefix removed.

## 3. The flow

```
1. INITIATE_CHECKOUT      POST /api/rest/version/100/merchant/<id>/session
                          → session.id + successIndicator   (store BOTH)
2. Launcher page          checkout.min.js → Checkout.configure → showPaymentPage()
3. Customer pays          on Mastercard's page; 3DS handled there
4. Return                 returnUrl?resultIndicator=…   → compare to successIndicator
5. RETRIEVE ORDER         GET /order/<order.id>          → AUTHORITATIVE. Settle on this
   Webhook (parallel)     X-Notification-Secret header   → same result, server to server
```

The request we send:

```json
{ "apiOperation": "INITIATE_CHECKOUT",
  "checkoutMode": "WEBSITE",
  "interaction": { "operation": "PURCHASE",
                   "merchant": {"name": "World Shading", "url": "https://…/"},
                   "returnUrl": "https://…/web.mpgs_return?t=<token>" },
  "order": { "currency": "BHD", "amount": "130.000",
             "id": "<our track_id>", "reference": "ORD-<our track_id>",
             "description": "Payment for ISA26-…" },
  "transaction": { "reference": "TXN-<our track_id>" } }
```

### Details that cost time to establish

**`interaction.operation` is `PURCHASE`, not `PAY`.** The prose says "a PAY, AUTHORIZE or
VERIFY transaction"; the enum values are `AUTHORIZE`, `NONE`, `PURCHASE`, `VERIFY`. `PAY`
is an `apiOperation`, a different field. `PURCHASE` produces a PAY transaction.

**`NONE` collects the card and performs no payment** — worth knowing, because it produces
exactly the symptom we are blocked on, and it is *not* what we send.

**There is no redirect-only option.** Hosted Checkout requires the Checkout JavaScript.
`/checkout/pay/<session>` looks like a redirect target but only renders for a session the
library has already initialised; a fresh session gets *"unable to complete your
payment"*. Fetching such a URL with curl returns a payment form regardless, which makes
the shortcut look viable when it is not.

**`order.id` is ours**, so we send our `track_id` and correlation is exact. MPGS does not
strip our query string, unlike BENEFIT — but the webhook does not rely on it either way.

**`resultIndicator` is a hint, not a receipt.** Mastercard: *"Do not use the value in the
resultIndicator parameter as the receipt number."* We compare it for display and settle
only on RETRIEVE ORDER.

## 4. Order statuses we act on

| `order.status` | Ours | Money |
|---|---|---|
| `CAPTURED` | Captured → settle | taken |
| `FAILED`, `DECLINED`, `EXPIRED` | Failed | none |
| `CANCELLED` | Cancelled | none |
| `AUTHENTICATION_UNSUCCESSFUL` | Failed | none |
| `AUTHENTICATED`, `AUTHENTICATION_INITIATED`, `PENDING` | unchanged, in progress | none |
| anything else | unchanged, logged, **never success** | unknown |

`AUTHORIZED` is deliberately **not** success: we ask for PURCHASE, so an
authorised-but-uncaptured order means something happened other than what we requested.

## 5. Missing unique references — fixed and verified

After successful 3-D Secure, **no payment transaction is created**. The order stays at
`AUTHENTICATED`, `totalAuthorizedAmount: 0`, `totalCapturedAmount: 0`.

Ruled out by direct test: the card, the merchant ID, 3-D Secure, `PURCHASE` vs
`AUTHORIZE`, the amount format, the currency, and the request shape.

The decisive result: with `interaction.action.3DSecure: BYPASS`, **no transaction is
created at all** — RETRIEVE ORDER returns *"Unable to find order"* though the session was
created successfully. With 3DS on, only an `AUTHENTICATION` transaction appears.

Mastercard investigated and reported the API error `INVALID_REQUEST - Field must be set
to a unique value`. The merchant profile enforces both **Enforce Unique Merchant
Transaction Reference** and **Enforce Unique Order Reference**, while our request sent
neither `order.reference` nor `transaction.reference`.

The request now sends `ORD-<track_id>` and `TXN-<track_id>`. A fresh `track_id` is
already created per attempt, so retries also get unique references. The earlier AUB
acquirer-link theory is superseded.

**Successful retest, 12 August 2026:** order `260812000002`, BHD 47.300, returned
`result: SUCCESS`, `status: CAPTURED`, `totalAuthorizedAmount: 47.300` and
`totalCapturedAmount: 47.300`. MPGS created a `PAYMENT` transaction through
`AUB_033042_S2I` with gateway response `APPROVED` / acquirer response code `00`.

The subsequent ERPNext Payment Entry failed validation because the temporary deposit
account `BDB Credit Card - WS` was not typed as Bank or Cash. That is an accounting
configuration issue, not a gateway failure. Configure a valid deposit account before
the next settlement test, then retry the captured transaction through the idempotent
settlement function.

## 6. Testing

Test cards (Mastercard standard list; the `TEST` profile is required):

| Brand | Number |
|---|---|
| Mastercard | `5123 4500 0000 0008`, `5111 1111 1111 1118` |
| Visa | `4508 7500 1574 1019`, `4012 0000 3333 0026` |

Expiry `01/39`, CSC `100`. On the ACS emulator choose
**(Y) Authentication/Account Verification Successful**. The other options — (N), (U),
(R) — are for certifying failure handling once payments work.

In the test environment **you** approve authentication; the emulator stands in for the
cardholder's bank. In production the real issuer does it, by OTP or app.

Diagnostics that touch no card:

```bash
bench --site erp.worldshading.com execute worldshading.payments.mpgs.ping
bench --site erp.worldshading.com execute worldshading.payments.mpgs.test_session
```

## 7. Reference

- API reference: `test-gateway.mastercard.com/api/documentation/apiDocumentation/…`
  (JavaScript-rendered; the content is in the HTML under `id="ContainerContent"`)
- Postman collection: **Downloads → Gateway API Operations** — machine-readable and more
  reliable than the prose. This is where `PURCHASE` was confirmed
- `vendor/MPGS/` — portal manuals, the API password guide, and third-party notes
