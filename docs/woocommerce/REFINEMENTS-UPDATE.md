# WooCommerce connector refinements: update an existing installation

This release fixes the import cutoff picker and customer-key namespace, and rearranges the native connector forms. The recovery timer and the immediate queue scheduling are unchanged. API response performance is not diagnosed or fixed by this release.

## Changes

- Settings: clear Connection, Company and Pricing, Stock, Online Warehouses, Order Defaults, Order Import, Accounts, Webhooks and Sync Status sections. Short descriptions, native columns and a full-width warehouse table.
- Item link: product identity and sync options grouped; stock/price switches visible in the grid. UOM conversion still comes from the Item.
- Order inbox, Sync Log and Sync State: readable summaries, visible errors, collapsed technical details. The Warehouse child table already has a single field and needs no extra layout.
- The visible **Import Orders Created Since** uses the ERP site timezone, as the standard v12 Now button does. The hidden `order_since` and `poll_cursor` remain UTC for polling and webhook filtering. Saving converts the selected site time to UTC. For Bahrain, 15:17 becomes 12:17 UTC automatically.
- Existing UTC cutoffs are shown in site time once; their actual import boundary is unchanged. Repeat setup and saves do not subtract the offset again. New selections during ambiguous/nonexistent daylight-saving times require another valid time.
- New customers use a `woo:` key that includes a hash of the store origin and Woo buyer identity. Existing exact legacy keys are reused without bulk rewriting customer records. Updates to linked orders accept those legacy identities. Conflicting legacy and current links require review. Ordinary ERP email/mobile matching is unchanged and is still deferred. Legacy keys were not store-scoped; reuse assumes this is an upgrade of the same site/store pairing. Review legacy customers separately before repointing a site to a different store.

## Before updating

Use your normal production database/files backup procedure and keep Automatic Sync off during this controlled rollout. Check the site timezone in System Settings. Ensure the Worldshading working tree is clean and preserve any existing Frappe/ERPNext core edits.

## Update after the release PR is merged

From the bench directory:

```bash
cd ~/frappe-bench/apps/worldshading
git pull --ff-only origin main
cd ~/frappe-bench
bench --site erp.worldshading.com execute worldshading.integration.woocommerce.install.preflight
bench --site erp.worldshading.com execute worldshading.integration.woocommerce.install.upgrade_refinements
bench --site erp.worldshading.com clear-cache
bench restart
```

This targeted upgrade reloads the six connector DocTypes and the guide Page, fills only a missing local-time cutoff from the existing UTC cutoff, and clears metadata cache. It does not run `migrate`, a test runner, core Custom Field creation, customer migration, imports, stock/price exports or activation. It preserves credentials, accounts, warehouses, mappings, sync switches and polling cursor. It does not install the recovery timer. Restart loads the Python/JS changes; hard-refresh the browser afterward. A build is not required for these directly served DocType and Item scripts.

## Confirm the cutoff before importing

If the old value was intentionally entered in UTC, the upgrade already preserves the correct instant. Do not subtract three hours manually.

If **Now** was selected in the old UTC-labelled picker, its value was actually site time, so the old boundary was wrong. The upgrade cannot safely guess that intent. After updating, select the intended start time again in **Import Orders Created Since**, or select **Now** to start with new orders, then save. The connector performs the UTC conversion. Selecting Now excludes earlier orders; choose an earlier deliberate start if those orders must be included. A previously advanced polling cursor is not automatically rewound by changing the cutoff; review any intended historical backfill separately.

## Controlled acceptance

1. Hard-refresh Settings; confirm saved credentials, accounts and warehouse rows remain, and Automatic Sync stays off.
2. Confirm the timezone under the cutoff picker. Re-select the intended cutoff as described above.
3. Map one approved Item. Check its child-row layout, UOM and stock/price switches. Run Preview, then a manual sync only after values are confirmed.
4. Place one approved test order after the cutoff, import manually and inspect customer, Item, quantities, taxes, shipping and exact total. Re-import/update to confirm the same Customer and Sales Order are reused.
5. Confirm Order Inbox and Sync Log errors/details are readable. Finish signed webhook and recovery service acceptance before enabling Automatic Sync.

The automated verification is standalone and does not initialize a business site. Native form rendering and production acceptance must be checked on ERPNext v12 after this update; source metadata checks alone do not prove screen layout or live API writes.

## Release verification

185 standalone tests pass, including the actual Settings validation method under a no-site harness, Bahrain/UTC day boundaries, DST rejection and repeat saves, legacy customer reuse, store isolation, and the scoped metadata update. Python 3.6 grammar, JavaScript syntax, metadata field order and preserved permissions/data fields were checked. Independent code review found no blocking issues. These checks do not access production.
