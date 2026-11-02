# WooCommerce hardening release

This release refines the existing connector. It does not create or modify Woo catalog content, images, prices or stock during installation. It preserves saved mappings, credentials, switches and cutoff. It requires no WordPress deployment, new dependency, full migrate or bench test runner.

## Schedule and performance

| Path | When | Work |
| --- | --- | --- |
| Normal Item/stock/price/reservation changes | After a successful ERP transaction | One coalesced short-queue notification for committed changed links; absolute Woo quantities are recomputed after reconciling orders. |
| Recovery | Native cron `*/10 * * * *` | A small callback enqueues one long-queue job. Poll missed orders/retries, compare local hashes, and publish changed targets only. No unconditional full product PUT. |
| Remote verification | Once an individual link has not been verified for an hour | Recovery verifies remote values, within the same 25-product/90-second product-work limits. Large queues can take longer; this is not an exact hourly deadline. |
| Optional automatic SKU linking | Recovery only, separate opt-in switch | Existing bounded catalog discovery. A completed scan waits one hour. Never scans the catalog in response to a stock event. |

Frappe scheduler tick, worker backlog and Woo latency affect actual start times. The job is not guaranteed to finish every ten minutes. HTTP operations/pagination can be slow. Native recovery has a 1500-second job timeout and a 1560-second notification lease. If it times out before polling advances, the stable order window is retried; order IDs and absolute stock writes remain idempotent. Recovery is serialized with the old CLI entry point and all exports share the existing cycle/product locks. Existing unrelated scheduled tasks are preserved.

Fusion comparison (source reviewed at `ab71a15`): Fusion combines document event hooks, hourly inbound product/order checks, daily stock/price tasks, and a one-minute optional batch-queue check. Its batch flush interval is configurable. It does not use one universal five-minute full sync. See [Fusion hooks](https://github.com/Starktail/woocommerce_fusion/blob/ab71a15d322232fff58d93fa0aa469812bfa9a30/woocommerce_fusion/hooks.py) and [batch queue](https://github.com/Starktail/woocommerce_fusion/blob/ab71a15d322232fff58d93fa0aa469812bfa9a30/woocommerce_fusion/tasks/batch/queue_manager.py).

## Linking workflow

SKU is the normal lookup/matching input. The connector discovers and retains the parent product ID and variation ID internally. Simple products use variation ID 0. Existing independent ERP Items do not need to become variant templates. A manual link may intentionally map different SKU/Item Codes; future SKU matching preserves it.

Bulk preview pauses at 25 displayed rows or ten catalog chunks. No linking or remote writes occur during preview. Select the specific rows after confirming their Item and website selling unit, then Create Reviewed Links. New bulk links are active for stock only; prices stay off. If Automatic Sync is enabled, stock may publish after linking. Next Batch continues from the saved scan position, including unshown results from the previous API response. It does not repeat the whole catalog.

Save Preview stores the current batch and continuation position in this browser for 24 hours, separated by ERP hostname and logged-in user. Resume Saved Preview restores it. This is not a shared/server-side report and will not survive clearing browser storage or changing devices. Every application rechecks the configured store, current own SKU/unique target, Item timestamp, permissions, existing mappings and native UOM. A stale saved preview can therefore be rejected and must be refreshed. Unselected rows are never created.

The per-product page shows all variations. Suggestions are not selected automatically. Select only the desired rows and confirm Selling UOM, then Save Links. New manual links remain inactive. An empty variable product now explains that variations must be set up in Woo first. Matching SKU alone cannot establish whether a website variation sells Meter or Roll; catalog cleanup remains necessary.

## Item data preservation and sync state

Mapping writes use the native connector child controller plus Item write permission, an SQL Item row lock, a checked Item modification timestamp, connector table validation and an Item Version audit entry. Only the mapping row and Item modification metadata are written. They do not invoke full Item.save, so missing legacy image files cannot cause image/thumbnail references to be cleared while linking. Unrelated Item fields and other child tables are preserved. Normal direct Item editing still follows ERPNext's normal rules.

Manual product sync now records success/failure against the revision captured before publishing. Successful work does not trigger a redundant background remote check. A newer revision arriving during HTTP remains pending. Failures use the existing retry backoff. Sync results continue to live in operational state/log records, rather than saving Item on every sync.

## Update an installed live site

The operator performs these steps; the release author has not changed production.

1. Use a quiet window and take the normal restorable backup. Record the existing commit. Turn Automatic Sync off and allow running connector jobs to finish. If the old external timer was installed, stop and disable only `ws-woocommerce@erp.worldshading.com.timer`; do not alter unrelated timers. This avoids redundant order polls after switching to native scheduling.
2. After the PR is reviewed/merged, pull `main` in `~/frappe-bench/apps/worldshading`.
3. From `~/frappe-bench`, run:

```sh
bench --site erp.worldshading.com execute worldshading.integration.woocommerce.install.upgrade_hardening
bench --site erp.worldshading.com clear-cache
bench restart
```

The targeted upgrade reloads only connector Settings and the two connector Pages, clears the native scheduler hook cache and reports the recovery cron. It does not run migrate, create core Custom Fields, run tests, import orders, export products or change sync switches. No build is needed for these directly served scripts/templates. Hard-refresh the browser.

4. Confirm the existing ERP scheduler is enabled and both short and long workers run. Do not enable global scheduling blindly if the server intentionally has it disabled: all existing ERP schedules would then run too. This release does not enable the global scheduler itself.
5. Keep optional Automatically Link Matching SKUs off during catalog cleanup. Preview one approved mapping and check its unit, expected available quantity, price configuration and image references. Check saved preview, row selection and a stopped/continued batch before creating approved links.
6. Turn Automatic Sync on only for accepted mappings. Make one normal business stock/reservation/price change and verify the immediate background result. Check Settings and logs after the next ten-minute boundary for recovery. A quiet product does not require a new Product sync log every ten minutes.
7. Check one controlled Woo order end to end, signed webhook handling, draft order holds, VAT/total preservation, duplicate delivery and retry behavior. Add approved products gradually.

## Acceptance and rollback

Local no-site tests are not a live load test or proof of the production queue installation. Before broad activation, verify native scheduling, child persistence/audit, stock reservations, failure recovery and signed webhooks on a disposable clone or an approved controlled production test. Do not run bench test/run-tests against business data.

For rollback, turn Automatic Sync off, drain running connector jobs, revert the application commit through the normal process, clear cache and restart. Preserve connector records and audit/logs. If returning to a release that requires the old external timer, re-enable that timer only after the native recovery hook is removed/refreshed. Do not run both by design. Reverting code does not undo Woo writes or ERP orders already created.

Recovery interval refinement: the user selected ten minutes to halve scheduled recovery frequency compared with five minutes. Immediate event processing stays the same. Missed webhooks, retries and changes bypassing hooks can wait up to the next recovery run, plus queue/HTTP time. This does not halve total connector load.
