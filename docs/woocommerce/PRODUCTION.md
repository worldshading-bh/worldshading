# WooCommerce connector release

This feature branch starts at clean `main` commit `acf8ba81fe634988a6b301dd08afc1536f1c55ba` and ports only the reviewed connector from the separate demo feature repository. No dirty demo application snapshot is included. Existing application hooks, Item dashboard, pricing, rounding, permissions and schedules are preserved. This is a release candidate, not evidence of a production installation: live ERP was not accessed or changed.

## What is included

- ERP-to-Woo stock and regular price synchronization for explicitly linked existing simple products/variations.
- Woo-to-ERP draft Sales Orders, durable inbox/retries, affected-item stock holds and sync logs.
- Item-owned links using native UOM conversions and combined online warehouses.
- Immediate post-commit background processing, coalesced notifications, bounded batches, five-minute recovery and hourly remote verification.
- Six active connector DocTypes, operational state separate from Item, eight custom fields on Item/Sales Order/Customer, and the native operator guide.
- Standalone no-site tests under `tests/woocommerce/` and optional systemd recovery unit templates under `deploy/woocommerce/`.

Excluded: demo access scripts/credentials, server backups, mappings, test documents/prices/customers, sample VAT setup, demo Woo safety changes and unrelated custom-app work. The obsolete Product Map DocType is not installed on a fresh site; existing legacy records can be migrated once when that table already exists.

## Deployment sequence — no bench migrate

Do these steps later in an agreed maintenance window, after live version/schema review and a restorable backup. The branch does not deploy itself. Adding custom fields can alter large existing tables and build unique indexes; targeted setup is **not zero database change**, and MariaDB DDL can commit independently. Review data/field conflicts and allow time for table locks before running it. Never run the Frappe test runner on a business-data site.

1. Back up live database/files, `site_config.json`, and current application commit. Confirm the live Worldshading checkout is clean. If an older custom connector is already installed, pause its automatic operation before setup. Record native Frappe/ERPNext versions and running jobs; do not interrupt active workers.
2. Review this branch/PR against current `main`; use the approved merged/tagged commit through the normal release process. Do not copy the demo's hooks file or run its provisioning scripts. Pulling code alone does not complete setup.
3. In the intended site's existing `site_config.json`, add **both** explicit origins, preserving all other keys:

   ```json
   {
     "ws_woocommerce_erp_url": "https://YOUR-LIVE-ERP-HOST",
     "ws_woocommerce_store_url": "https://YOUR-LIVE-WOO-HOST"
   }
   ```

   Replace both placeholders with exact HTTPS origins, without a path, port, credentials or query string. The site's existing `host_name` must equal the ERP origin (an optional trailing slash is accepted). These are destinations, not API credentials. Partial configuration fails closed. Without either setting, only the original demo ERP/Testshop pair is permitted; an unconfigured live site cannot connect. No production host is guessed in this release.
4. As the normal bench owner, inside the bench directory, run the read-only feature preflight:

   ```sh
   bench --site YOUR-SITE execute worldshading.integration.woocommerce.install.preflight
   ```

   It reports the scoped metadata and rejects conflicting custom-field types or DocType ownership. It does not certify table sizes, duplicate existing values, all custom hooks, tax settings, worker health or database compatibility; review those separately on live before setup.
5. With backups/maintenance in place, run only the connector setup:

   ```sh
   bench --site YOUR-SITE execute worldshading.integration.woocommerce.install.execute
   bench --site YOUR-SITE clear-cache
   ```

   This reloads six connector DocTypes and the guide Page and creates/updates only the declared custom fields. It never calls `bench migrate`, never imports demo records and never enables automatic sync. Existing connector settings are preserved on repeat runs. Future full migrations, if performed for other work, can synchronize these standard DocTypes on other sites using this app; the guarded connector setup/custom-field hook only runs on a matching configured site. Unconfigured sites cannot sync.
6. Safely reload web/queue processes so code and hooks refresh; keep the general ERP scheduler in its existing state. Confirm the short queue workers are running. This feature has not added or modified global scheduled jobs.
7. Open **WS WooCommerce Settings**. New settings default to connector disabled and Automatic Sync off. Configure the exact allowed Woo URL, dedicated read/write API credentials, company/currency/price list, integration user, online warehouses/default order warehouse, customer defaults, tax/shipping/fee accounts and the deliberate order-import starting point. Disable the legacy built-in Woo connector before enabling this one. Review older unfulfilled Woo orders before the first stock export.
8. Create native Woo `order.created` and `order.updated` webhooks using the production webhook URL shown in Settings and the matching secret. Verify Woo scheduled tasks/webhook delivery work. Use new production WooCommerce API credentials.
9. Map one approved real product/variation; do not reuse demo IDs blindly. Confirm exact SKU, selling UOM/conversion, approved net price, Woo tax class and VAT display. Enable the connector for manual connection/preview tests. A manual Sync performs writes and an order import may create ERP documents; perform those only as an approved controlled acceptance test. Check quantity, draft holds, VAT/shipping and exact order totals. Price sync assumes BHD-style three-decimal precision and net-entered Woo prices.
10. Install/enable the connector recovery timer only when paths, ownership and site instance have been checked. The supplied templates assume `/home/erpadmin/frappe-bench` and user/group `erpadmin`; adjust for the actual server. Copy templates to systemd, reload its configuration, then enable `ws-woocommerce@YOUR-SITE.timer`. It checks every300–305 seconds after the previous recovery completes. It uses the native integration user and exits without syncing while Automatic Sync is off. The service has no overall wall-clock timeout because a slow order backlog must stabilize before the polling cursor advances; individual HTTP calls and pagination remain bounded. It never overlaps its own recovery runs. Do not install the demo service or change unrelated jobs.
11. Enable Automatic Sync only after controlled acceptance. Monitor Settings, Order Inbox, Sync Logs and worker/service logs. Add more approved mappings gradually. The guide is at `/desk#ws-woocommerce-guide`, linked from Settings, with System Manager access.

Immediate jobs start after successful commit; queues and Woo response times determine actual latency. Direct v12 reservation writes, including close/reopen, can wait for recovery. Pending/failing orders hold only affected stock unless source identities are unreadable. Recent orders are reconciled before absolute stock exports. The connector does not submit imported orders, create invoices/payments/deliveries, match legacy ERP customers by email/mobile, create Woo catalogue content, or allocate order lines across warehouses.

## Tests and limits

Run only the standalone suite:

```sh
python -m unittest discover -s tests/woocommerce -q
```

It initializes no Frappe site/database. The release suite currently passes167 tests. The 155-test demo baseline covers stock/reservations, order idempotency/holds, prices, failures, concurrency, revision state and queue behavior; release tests add exact destination configuration, real target construction, metadata preflight and coexistence with all existing hooks. Demo end-to-end results do not replace acceptance on a current production-data clone. No production access, schema check, load benchmark or live end-to-end compatibility is claimed for this branch.

## Pause and rollback

Turn Automatic Sync off, disable the connector, pause only its Woo webhooks/recovery timer, and let already-running connector jobs finish before reverting code. Preserve inbox/logs and reconcile any orders or stock already synchronized. Restoring code does not undo external Woo writes or ERP documents. Do not delete populated custom fields/tables to roll back. Restore a database backup only as a coordinated recovery, accounting for business transactions since it was taken. The original application commit and backups are the recovery reference.

## Maintaining the guide

Guide assets live under `worldshading/worldshading/page/ws_woocommerce_guide/`. Installed Frappe v12 template generation requires HTML entities such as `&#39;` instead of literal apostrophes in HTML. Validate the generated script and browser rendering after changing content.

## Removing the former demo gateway fields

The production connector uses WooCommerce Consumer Key and Consumer Secret only. The former Gateway User/Password fields and HTTP Basic gateway handling have been removed. After deploying that patch, refresh only the Settings metadata, then clear cache and safely reload processes:

```sh
bench --site YOUR-SITE reload-doc worldshading doctype ws_woocommerce_settings
bench --site YOUR-SITE clear-cache
# During a quiet moment, after active jobs finish:
bench restart
```

Do not rerun the full connector installer for this change. No full migrate or test runner is needed. This removes the fields from the form; it does not delete unrelated settings or Woo API credentials. Frappe may retain obsolete stored singleton/password entries internally; the connector no longer reads or uses them. The production review reported those former gateway values unset, so no credential cleanup is required for that reviewed installation.
