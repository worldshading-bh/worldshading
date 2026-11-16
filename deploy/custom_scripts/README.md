# Sales Invoice WhatsApp verification

`sales_invoice_whatsapp_verification.js` is a reference copy of the deployed
WhatsApp `before_workflow_action` handler in Custom Script `Sales Invoice-Client`.
It was verified against production on 2026-11-16. It is not loaded by hooks,
fixtures, or migration scripts. Do not load it alongside the database handler:
that would register the workflow handler twice.

## Scope and behavior

The handler covers Complete and Request Cutting, excluding returns. It preserves
locked numbers, dynamic contacts and the existing country-code choices. Contact
update and invoice-save failures reject the pending workflow rather than leaving
it unresolved. Confirmation is guarded against repeated clicks. A two-minute
save watchdog stops the attempt without automatically retrying or submitting;
late save responses cannot resume that stopped workflow. A timed-out request may
still finish on the server: reload the invoice before retrying.

Invoice saves use `frm.save` callbacks and verify the returned document because
this Frappe v12 installation catches some save errors internally. Contact requests
are wrapped in `Promise.resolve`: jQuery 2.2.4 Deferreds do not implement `.catch()`.
The initial deployment omitted that wrapper; the corrected deployment includes it.

The handler does not send WhatsApp messages. The existing server notification
queues automatic invoice messages on submission after the database commit.

## Isolated verification

Run from the app repository:

```sh
node --check deploy/custom_scripts/sales_invoice_whatsapp_verification.js
node tests/sales_invoice_whatsapp_verification.test.js
```

These are isolated JavaScript tests with mocked Frappe calls and a jQuery 2-style
thenable, not bench tests. They cover successful and failed contact/invoice saves,
load failure, cancellation, timeout, repeated clicks, unchanged numbers, dynamic
contacts, missing contacts, locked numbers and late responses. They do not replace
browser verification or reproduce all production request/refresh behavior.

## Maintenance and rollback

Only replace the handler between `// WhatsApp verirification in invoice` and
`// WS_RETURN_REASON_DIALOG_V1` in the database Custom Script; retain the latter
marker and all surrounding code. Back up the current record and check for edits
before replacement. This file must not replace the entire Custom Script.

The original production record and script are preserved on the production host:

- `/home/erpadmin/frappe-bench/private-diagnostics/invoice-confirmation-20261116/original.json`
- `/home/erpadmin/frappe-bench/private-diagnostics/invoice-confirmation-20261116/original.js`

For rollback, restore only the original handler if other sections have since
changed. Reload affected browser pages after a script update. No migrate, bench
test, service restart or invoice submission is required to maintain this reference.
Reverting this Git commit alone does not change the database Custom Script.
