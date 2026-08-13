# BENEFIT Payment Gateway — Integration Reference

Distilled from `vendor/benefit/BENEFIT Payment Gateway - Integration Guide v1.4.pdf`,
`Faster checkout v1.51.pdf`, the two test-case sheets, and the onboarding email
(`vendor/benefit/Benefit-Gateway-email (1).txt`).

This file records **what the gateway requires**. It is not a design document.

---

## 1. Which integration mode we must use

BENEFIT offers two modes. Only one of them is usable from Frappe.

| Mode | Delivery | Usable here? |
|---|---|---|
| **Plug-in** (`iPayBenefitPipe`) | Java JAR / .NET DLL / PHP — plus `resource.cgn` + `KeyStore.bin` files | **No.** There is no Python plug-in. Guide §3.3 lists JDK 1.7/1.8, IKVM 7.2, PHP 7 only. |
| **REST API** (Guide Chapter 4) | Plain HTTPS POST + AES payload, no vendor binaries | **Yes — this is our path.** |

The onboarding email also marks API integration as *"Recommended"*.

Consequence: we never download the plug-in, the keystore, or the resource file. We
implement the AES envelope ourselves in Python. The only secret we need is the
**Terminal Resource Key**.

---

## 2. Credentials and endpoints (test)

| Item | Value |
|---|---|
| Merchant portal | `https://test.benefit-gateway.bh/portal/merchant.htm` |
| API endpoint | `https://test.benefit-gateway.bh/payment/API/hosted.htm` |
| Institution ID | `AUB` |
| Merchant ID | `200007408` |
| Tranportal ID | `200007408` |
| Tranportal Password | see onboarding email — **must be stored in the Settings doctype as a `Password` field, never in code or in this folder's tracked docs** |
| Terminal Resource Key | 32 characters — see onboarding email — **same rule** |

Production hosts differ (`https://www.benefit-gateway.bh`). Both must be firewall-whitelisted
**in both directions**. If domain whitelisting is unavailable, the guide lists IPs
`79.171.242.91` (443 + 80), `79.171.242.90`, `79.171.247.90`, `79.171.240.90` (443) —
but the guide states domain whitelisting is the reliable approach.

---

## 3. The AES envelope

Everything in both directions is wrapped in `trandata`.

```
Algorithm : AES / CBC / PKCS5Padding   (PKCS7 — identical for AES block size)
Key       : the Terminal Resource Key, used as raw UTF-8 bytes
            32 chars -> AES-256
IV        : the literal ASCII string "PGKEYENCDECIVSPC"   (static, 16 bytes)
Encoding  : ciphertext is transmitted as an UPPERCASE hex string
```

**The step that is easy to miss, and that the guide states twice:**

- **Before encrypting**, URL-encode the plaintext JSON.
- **After decrypting**, URL-decode the result.

A static IV is weak by modern standards. We do not get a choice — it is fixed by the
gateway. Note it in any future security review rather than "fixing" it.

---

## 4. Purchase flow (REST, bank-hosted)

### 4.1 Request

`POST` to the API endpoint, body is a **JSON array with one object**:

```json
[{ "id": "<Tranportal ID>", "trandata": "<UPPERCASE HEX>" }]
```

Plaintext inside `trandata`, also a **single-element JSON array**:

```json
[{
  "amt": "12.000",
  "action": "1",
  "password": "<Tranportal Password>",
  "id": "<Tranportal ID>",
  "currencycode": "048",
  "trackId": "<our unique reference>",
  "udf1": "", "udf2": "", "udf3": "", "udf4": "", "udf5": "",
  "responseURL": "https://<our host>/<response path>",
  "errorURL":    "https://<our host>/<error path>"
}]
```

Field notes:

| Field | Notes |
|---|---|
| `amt` | **Decimal string, not minor units.** Guide examples: `"12.00"`, `"60.000"`, `"10.000"`. BHD has 3 decimals. |
| `action` | `1` Purchase · `2` Refund · `3` Void · `8` Inquiry |
| `currencycode` | `048` = BHD (ISO numeric) |
| `trackId` | Numeric, merchant-unique. Our correlation key back to the ERP document. |
| `udf1`–`udf5` | Optional, echoed back untouched. Must be **empty strings** when unused, not omitted. `udf1` is shown as "always keep it empty" in the ASP sample — treat `udf1` as reserved. |
| `responseURL` / `errorURL` | Mandatory, absolute, public HTTPS. |

### 4.2 Initial response — plain JSON, **not** encrypted

```json
Success: [{ "status": "1", "result": "<paymentId>:<payment page URL>", "error": null, "errorText": null }]
Failure: [{ "status": "2", "error": "IPAY0100124", "errorText": "...", "result": null }]
```

On success, split `result` on the **first** `:` — the remainder is a URL that itself
contains `https://`, so a naive split breaks. Then redirect the browser to:

```
<payment page URL>?PaymentID=<paymentId>
```

### 4.3 Merchant Notification (server-to-server) — the critical constraint

If Merchant Notification is enabled for our terminal, after the customer pays, BENEFIT
makes a **server-to-server call to our `responseURL`** carrying encrypted `trandata`,
and waits for an acknowledgement.

Our response body must be **exactly**:

```
REDIRECT=https://<our host>/<final result page>
```

Rules the guide is explicit about:

- The keyword must be **upper-case**.
- When Merchant Notification is enabled, **only server-side output is allowed on that
  page — no HTML, no CSS, no JavaScript.** The body is that one line and nothing else.
- **If we do not acknowledge in time, BENEFIT VOIDS the transaction.** The customer is
  debited and then reversed, and we would show a success we never actually kept.

The onboarding email gives the required ordering inside that handler, because slow
merchant-side work is a known cause of failed notification cycles:

1. Log the received response data to a file on the same server (backup if later steps fail).
2. Print `REDIRECT=someURL`.
3. *Only then* do internal processing (database updates, etc.).

**This shapes our implementation directly:** the notification endpoint must persist the
raw payload, emit the one-line body immediately, and push all ERP work (Payment Entry,
document status, notifications) to a background job. It cannot be a normal Frappe web
page, because those render HTML.

### 4.4 Final response

After acknowledging, BENEFIT redirects the browser to the URL we named, with `trandata`
(encrypted) and `paymentid` as parameters. Decrypt it and show the customer the outcome.

Decrypted response fields:

```
paymentId, result, ref (RRN), transId, date, trackId,
udf1..udf5, amt, authRespCode, authCode
```

If notification is **disabled**, there is no server-to-server leg at all — the encrypted
final response arrives by browser redirect only. That is less reliable (it depends on the
customer's browser completing the round trip) and should not be our configuration.

If BENEFIT gets no acknowledgement, it posts to our `errorURL` with plain parameters:
`payment id`, `Error`, `ErrorText`, `trackid`, `amt`.

---

## 4.5 Where the live gateway differs from the guide

Both of these were found on the first real transaction (2026-08-09, test terminal,
`trackId` 260809000001). The guide is wrong on both. Do not "fix" the code back to
what the PDF says.

**1. `result` is the complete URL, not `"<paymentId>:<url>"`.** What actually came back:

```json
[{"result":"https://test.benefit-gateway.bh/payment/paymentpage.htm?PaymentID=119202622138483730","status":"1"}]
```

PaymentID is already in the query string. Splitting on the first colon as the guide
describes yields `payment_id = "https"` and a malformed redirect carrying
`PaymentID` twice. `parse_init_response()` detects the URL form first and falls back
to the documented form.

**2. BENEFIT strips the query string from every URL we give it.** The notification
arrived at `responseURL` with **no `t` parameter**, and so did the browser redirect to
the URL named in our `REDIRECT=` reply. Anything we need on the way back must travel
in the payload, not the URL.

What BENEFIT does echo, in the clear, alongside the encrypted blob:

```
paymentid, trackid, tranid, amt, auth, ref, result, udf1..udf15,
postdate, avr, authRespCode, threeDSServerTranID, dsTranID, acsTranID
```

So correlation uses `udf3` (our token) and `trackId` (our reference), both echoed on
every leg. Note the response also carries **3-D Secure** fields the guide never
mentions, and `udf6`–`udf15`, well beyond the documented `udf1`–`udf5`.

**3. The success `result` is only in the encrypted payload.** The plain `result`
parameter posted alongside it is an **empty string** even for a captured payment.
Read the outcome from the decrypted `trandata`, never from the clear parameters.

---

## 4.6 Cross-check against BENEFIT's own Python plugin

`vendor/benefit/BenefitAPI.py`, `request.py`, `response.py` and
`Benefit PaymentGateway_Python Integration Guide.pdf` are the vendor's Python
integration files, downloaded from the portal. They **confirm our implementation**
and settle two things the PDF guide got wrong.

Confirmed identical to what we do:

| | |
|---|---|
| Transport | `POST`, `Content-Type: application/json`, `Accept: application/json`, body `json.dumps([{id, trandata}])` |
| AES | same static IV, PKCS7 padding, uppercase hex, key as raw UTF-8 |
| Decrypt | URL-decoded with `unquote_plus` |
| Notification reply | a bare `'REDIRECT=<url>'` string |
| Outcome source | read from the decrypted payload; errors from the plain `ErrorText` |

**`result` is the whole URL — confirmed.** Their `request.py` does
`webbrowser.open(result['result'])` with no parsing at all. §4.5 above was right and
the guide's `"<paymentId>:<url>"` is wrong.

**`trackId` need not be numeric.** Their sample uses `uuid.uuid1().hex`, contradicting
the guide's field table. More usefully, it mints a **fresh one per transaction**,
which is exactly why we create a new attempt per retry.

Deliberate divergences:

- **`resourceKey` inside the encrypted payload.** Their sample includes it; we do not.
  It is the key the payload is already encrypted with, so it conveys nothing. Verified
  unnecessary against the live terminal.
- **`quote` vs `quote_plus`.** They encode with `quote` (space → `%20`), we use
  `quote_plus` (space → `+`). Our payload does contain spaces — `json.dumps` puts them
  after every separator — and a real transaction captured successfully, so BENEFIT's
  decoder handles `+`. No change needed; noted so nobody "fixes" it later.

Adopted from them:

- **`cardType: "D"`**, which their sample marks do-not-change.
- **Populating the UDFs.** Their guide asks for invoice/customer identifiers in these
  fields because they appear in the merchant portal and are what you have to work with
  in a dispute. We now send `udf1` = the document being paid, `udf2` = the Payment
  Request, `udf3` = our link token.

---

## 5. Result and response codes

`result` values:

| Value | Meaning |
|---|---|
| `CAPTURED` | **The only success value for a purchase.** |
| `NOT CAPTURED` | Failure |
| `VOIDED` | Success for a Void |
| `DENIED BY RISK` | Risk profile rejected it |
| `HOST TIMEOUT` | No answer from the interchange |

Treat anything other than the expected success value as failure. Do not pattern-match
loosely — the Faster Checkout sample shows lower-case `"captured"` in one place and
upper-case elsewhere, so compare case-insensitively.

`authRespCode` (a selection): `00` approved · `14` invalid card · `33`/`54` expired ·
`36`/`62` restricted · `38`/`75` PIN tries exceeded · `51` insufficient funds ·
`55` incorrect PIN · `61` exceeds amount limit · `65` exceeds frequency limit ·
`76` ineligible account · `78` refer to issuer · `91` issuer inoperative.

Error codes are `IPAY…` strings (Guide Chapter 6). Ones we will meet while integrating:
`IPAY0100005/6` tranportal id missing/invalid · `IPAY0100015` invalid tranportal password ·
`IPAY0100013` invalid transaction data (usually an AES or URL-encoding mistake) ·
`IPAY0100022/25` invalid currency / amount · `IPAY0100008` terminal not enabled ·
`IPAY0100036` UDF mismatched.

---

## 6. Hard environment constraints

These are gateway rules, not preferences. Each one can block go-live.

1. **The request must originate from a public, internet-hosted domain/IP.** Not localhost,
   not a private address.
2. **No non-default ports.** `https://host/path` is fine; `https://host:400/path` errors.
   Same for HTTP and port 80.
3. **Total URL length ≤ 254 characters.** Our `responseURL`/`errorURL` must stay short —
   this rules out long query strings carrying document names.
4. **Valid SSL certificate, not self-signed**, in test *and* production.
5. Response, error, success and exception pages must be reachable and working **at all
   times** — an invalid URL is an error.

---

## 7. Refund

- `action` = `2`.
- Only for transactions **not older than 14 days**.
- Enabled only on acquirer approval, with **separate flags** for portal refunds and
  API refunds.
- Portal refunds (Transaction → Posted Transaction) need no integration or testing.
- Partial refunds are supported; over-refunding returns
  `IPAY0300024 — Failed credit greater than debit check`.
- Unknown track ID returns `IPAY0100263 — Transaction not found`.

Refund via API is a **separate certification exercise**. Recommend phase 2 — start with
portal refunds, which need nothing from us.

---

## 8. Faster Checkout / tokenisation (optional, phase 2)

Lets the customer store cards at BENEFIT (never with us — we stay non-PCI).

- Token is returned in **`udf7`** on a successful transaction.
- To reuse it, send `udf7` = token **and `udf8` = `"FC"`**. Sending `udf7` without
  `udf8="FC"` fails.
- If the customer deletes all saved cards, `udf9` comes back as `"DELETED"`.
- **If the customer just closes the payment page, no response is generated at all** — we
  never learn the token was deleted, so later requests with that token get rejected. The
  guide is explicit that the merchant must handle this rejection gracefully and clear its
  stored token.

Note `udf7`/`udf8`/`udf9` are not documented in the Chapter 4 REST parameter tables — they
appear only in the Faster Checkout document, whose examples use the query-string form.
**Confirm with BENEFIT that they are accepted in the REST `trandata` JSON** before
planning this phase.

---

## 9. Certification test set

The onboarding email requires us to run these and send back the Payment IDs:

1. Approved (`CAPTURED`)
2. Declined (`NOT CAPTURED`) — click **cancel** in the retry popup to complete the cycle
3. Cancelled — click cancel on the payment page
4. Denied by risk — more than 4 approved transactions on the same card within 5 minutes

Test cards. Any name, any future expiry, any 4-digit PIN. Full numbers below are from
`vendor/benefit/test cards.txt`; the prefix is fixed and the last 8 digits are free.

| Card number | Code | Outcome |
|---|---|---|
| `4600 4101 2345 6789` | 00 | **Approved** |
| `4550 1201 2345 6789` | 54 | Expired card |
| `4889 7801 2345 6789` | 61 | Limit exceeded |
| `4415 5501 2345 6789` | 51 | Insufficient funds |
| `4575 5501 2345 6789` | 78 | Refer to Issuer |
| `4845 5501 2345 6789` | 55 | Invalid PIN |
| `4895 5501 2345 6789` | 05 | Contact issuer |

Full scenario lists: `vendor/benefit/Test Cases - Faster Checkout.xlsx` and
`Test Cases - Refund.xlsx`.

---

## 10. Logging obligations

Chapter 7 makes these mandatory, not advisory:

- Log parameters before assignment, the request sent, and the response received at the
  response URL.
- Keep transaction logs in secure storage, **including the customer IP address**, for
  dispute and audit purposes.

`Integration Request` covers the request/response side. Customer IP needs to be captured
deliberately — it is not part of the gateway payload.
