# Architecture

How the payment integration is put together, and why each decision was made. Read this
before changing anything.

---

## 1. Files

```
worldshading/payments/
    gateways.py     which gateway handles what; the client registry
    utils.py        money, track IDs, the transaction record, settlement, link guards
    crypto.py       the AES envelope BENEFIT mandates (BENEFIT only)
    benefit.py      BENEFIT REST client
    mpgs.py         KFH MPGS client
    web.py          guest endpoints the gateways call back into
    reconcile.py    the sweep that chases payments we were never told about
    test/           pure unit tests, no database

worldshading/worldshading/doctype/
    ws_payment_gateway/       one row per gateway
    ws_payment_transaction/   one row per payment attempt

worldshading/www/
    payment-methods/   the customer chooses Debit or Credit
    mpgs-checkout/     launcher that opens Mastercard's hosted page
    payment-result/    the outcome the customer sees
```

`hooks.py` carries exactly one payments entry: the reconciliation schedule. Everything
else is discovered by Frappe through the `Payment Gateway` record.

## 2. The flow

```
Payment Request submitted
   └─ ERPNext asks the ROUTER gateway for a payment URL
        └─ creates a WS Payment Transaction (the link), status Initiated
        └─ returns /payment-methods?t=<token>

Customer clicks, and chooses a method
   └─ web.checkout(t, m)
        ├─ refuses if the link is closed (paid, cancelled, invoice settled, expired)
        ├─ adopts the link row for the chosen gateway, or opens a NEW attempt
        └─ client.initiate(txn)  ──►  the bank's hosted page

Customer pays

   BENEFIT                              MPGS
   ├─ server-to-server → web.notify     ├─ browser → web.mpgs_return
   │    reply "REDIRECT=<url>" FAST     │    then RETRIEVE ORDER (authoritative)
   │    then enqueue settlement         └─ webhook → web.mpgs_webhook
   └─ browser → web.result                   verified by X-Notification-Secret
        same handler again, idempotent

Background worker
   └─ utils.settle()   row lock, then Payment Entry created and submitted
        └─ ERPNext's update_payment_req_status moves the request to Paid
```

## 3. The router, and why it exists

A Payment Request is raised by staff, who **cannot know whether the customer holds a
debit or a credit card**. ERPNext requires exactly one gateway per Payment Request. So
`WS Payments` is a gateway that takes no money — its `get_payment_url()` returns our
chooser page, and the real gateway is decided when the customer picks.

Consequences worth knowing:

- The **link** is gateway-neutral; each **attempt** records the gateway that handled it
- A customer may try Credit, fail, and retry with Debit — two attempts, two gateways,
  one link, one Payment Entry
- Money follows the gateway, not the request: each gateway has its own **deposit
  account**, and `settle()` stamps `paid_to` from whichever gateway actually took the
  payment. Without this both would post to the router's account

## 4. One transaction per attempt

| Field | Scope |
|---|---|
| `token` | The **link**. Shared by every attempt behind it. Indexed, deliberately not unique. This is what appears in the customer's URL |
| `track_id` | The **attempt**. Unique, minted fresh each time. Sent as BENEFIT's `trackId` and as MPGS's `order.id` |
| `attempt` | 1, 2, 3 … for the list view |

`checkout` reuses the latest row only while it is still `Initiated` — never sent to a
gateway, so its track ID is unused. Otherwise it opens a new attempt.

**This is why `WS Payment Transaction` exists** rather than a few custom fields on
Payment Request. One row cannot hold three attempts' payment IDs, results and payloads,
and overwriting them would destroy the audit trail BENEFIT's guide requires. It also
gives us somewhere to record payments that have no Payment Request at all.

Callbacks resolve to the exact attempt by `trackId` / `order.id`. The link token is only
a fallback, and can answer no better than "the captured attempt, else the latest".

## 5. When a payment link stops working

`link_blocked_reason()`, checked in `checkout` and again on the result page:

- the Payment Request was cancelled, or is already Paid
- **the referenced document owes nothing** — however it was settled: cash, another
  gateway, a credit note
- the link is older than **Link Valid For (Days)** (default 30, `0` disables)

The middle one is the one that matters. Without it: invoice raised, link emailed,
customer pays cash at the counter, nobody cancels the request, and weeks later the
customer finds the old email and pays a second time.

## 6. Settlement

`utils.settle()` — enqueued, never run on the request thread.

1. `SELECT … FOR UPDATE` on the transaction, check `settled` inside the lock
2. Build the Payment Entry unsubmitted
3. Stamp **Mode of Payment** and **deposit account** from the gateway that took the money
4. Insert and submit

Three things that are the way they are for a reason:

**`mode_of_payment` is stamped explicitly.** It is mandatory on Payment Entry on this
site via a Property Setter, and ERPNext's `get_payment_entry()` never fills it. The first
live settlement died on exactly this, after the card had been charged.

**`workflow_state` is left alone.** Payment Entry has an active workflow. A new document
must enter at the first state, and Frappe's `set_workflow_state_on_action` moves it to
the docstatus-1 state during submit. Setting it ourselves is rejected as an illegal
transition.

**`on_payment_authorized()` is not used.** It wraps the same `set_as_paid()` in webshop
redirect logic that is meaningless for an emailed Payment Request.

## 7. Reconciliation

`reconcile.py`, scheduled every 15 minutes.

A transaction at **`Redirected`** means we sent the customer to the bank and never heard
back — ambiguous in a way no other state is: either they closed the tab, or the payment
captured and we lost the callback. Nothing else revisits those rows.

- **MPGS** — RETRIEVE ORDER is documented and authoritative. Ask, and act on the answer
- **BENEFIT** — Inquiry (`action=8`) is documented only for the older plug-in surface, so
  the unverified request path is not shipped. The sweep flags stale rows for review
- Anything not confidently understood sets **`needs_review`** and changes nothing

`Initiated` needs none of this: it never reached a gateway, so there is definitively no
money behind it. Those are only aged to `Expired` for tidiness.

**On this site `pause_scheduler` is set**, so the sweep does not fire on its own. Run it
by hand:

```bash
bench --site erp.worldshading.com execute worldshading.payments.reconcile.run
```

## 8. Why the doctypes look like this

**One doctype, one row per gateway.** The alternative — a Settings single per gateway —
meant a new doctype for every acquirer. Frappe's `Payment Gateway` record carries
`gateway_settings` and `gateway_controller`, which exist precisely so a shared doctype
can hold many gateways.

**Not on the core `Payment Gateway` doctype.** ERPNext calls methods on the controller,
and a doctype's methods come from its own Python file — which for `Payment Gateway` is
Frappe core. v13 added `override_doctype_class`; **v12 has no such hook**, so the only
route would be editing Frappe itself.

**Registration happens in `on_update()`, not `validate()`.** The Payment Gateway record
points back at its row through a Dynamic Link, and during `validate()` a new row does not
exist yet — producing *"Could not find Gateway Controller"*.
