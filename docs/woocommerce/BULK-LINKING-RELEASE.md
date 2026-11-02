# WooCommerce linking release — production update

This release adds catalog-wide exact SKU matching, a native WooCommerce action menu, and one linking sheet containing all variations. It changes only connector code and metadata. No WordPress update is required if the current ERPNext Mapping links already work.

## Prepare the catalog

Use the standard WooCommerce CSV export/import (Excel is suitable). Set each simple product or variation's **own SKU** to the correct ERP **Item Code**. Each size/colour needs its own code. A variable parent's SKU cannot identify its children. Match the spelling and case exactly; do not replace existing SKUs until checking any other systems that use them.

In ERP, confirm each matching Item is active, sellable and is not a variant template. Set Sales UOM to the unit the website sells, with its normal positive Item UOM conversion. When Sales UOM is empty, only an Item with a single valid unit can be matched automatically. Multiple units go to Review.

## Deploy after merging

Take the normal production database backup first. From the bench:

```sh
cd ~/frappe-bench/apps/worldshading
git pull --ff-only origin main
cd ~/frappe-bench
bench --site erp.worldshading.com execute worldshading.integration.woocommerce.install.upgrade_bulk_linking
bench --site erp.worldshading.com clear-cache
bench restart
```

Hard refresh the browser. The upgrade reloads **WS WooCommerce Settings** and the **linking and guide Pages** only. It adds two connector settings (opt-in checkbox and internal cursor). It does not run full migrate, tests, change existing Item links, or enable either automatic switch. Existing switch values are preserved. No core DocTypes are reloaded.

## First acceptance

1. Keep Automatic Sync off for the controlled test. Save Settings.
2. Open **WooCommerce → Link Matching Items** in Settings. Click **Preview Matching Items**. Scanning is read-only and shows progress. You can Stop and Review a partial scan; restarting starts a new preview.
3. Review **Ready**, **Review**, and **All**. Existing targets or already-mapped Items are preserved. Blank/inherited SKUs, unsupported product types, no exact match and unclear units are not linked.
4. Click **Create Reviewed Links**, then confirm. Every target, unique stored SKU, Item, UOM and timestamp is checked again. Successful rows become active **stock-only** links; price sync remains off. Failures are isolated and shown per row. Restart Preview before retrying stale or interrupted results.
5. Open one Item, check its new child row and use **WooCommerce → Preview WooCommerce**. Under your controlled production test, manually sync that Item and confirm Woo stock; then test one order import. Creating links does not itself issue Woo writes, but Automatic Sync, when enabled, can publish the queued stock.
6. If desired, opt into **Automatically Link Matching SKUs** after reviewing these rules. With all three switches enabled and the existing recovery service running, future exact matches become active stock-only links automatically. This is ongoing approval for future matches; leave it off if every batch needs manual review.

## Manual linking and scheduling

The product link now opens the full parent sheet, even from a variation URL. Every variation has an independent Item/UOM row. Additional pages load into the same table. Existing active links are read-only; new manual links remain inactive. Save Links saves valid changed rows and reports individual failures.

Automatic catalog matching runs only in the existing recovery service after the normal order/stock work. It processes up to ten bounded chunks per invocation and checks elapsed time between chunks. A chunk contains one parent and up to 25 variations. A completed scan waits one hour before starting over; scan duration depends on catalog size and API speed. It never runs in the immediate stock-event queue. A failed chunk is retried without replacing successful existing links. Recovery failures are logged; successful creations are recorded in Sync Logs.

The release was checked with isolated tests and a local UI fixture; this does not replace the controlled production acceptance above. No live ERP records were modified during preparation. Do not run bench tests on the business site.

## Rollback

Turn off Automatically Link Matching SKUs first. Revert the release code and restart services. Added metadata can remain. Review any mappings deliberately created during acceptance; rolling back code does not remove Item links or revert stock already published.
