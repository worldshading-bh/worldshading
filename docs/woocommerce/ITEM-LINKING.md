# Link a WooCommerce product to an ERPNext Item

The WooCommerce manager button opens a small ERPNext window. Sign into ERPNext there if needed, select the product variation, search for an existing Item by code or name, choose one of that Item's existing UOMs, and click **Save Link**. Product ID, variation ID and SKU come from the configured Woo store; no manual copying is required.

A new link is **inactive**, with stock selected and price unselected. Save Link never publishes stock or prices. Use **Open ERPNext Item**, review the link and its preview, then enable the intended sync options in the Item. An existing active link must be edited in the Item; the popup cannot reassign a target already owned by another Item. An inactive link can change its UOM. Use Reload if the Item or remote SKU changed while the window was open.

## Production update

Apply after the previous connector/refinement release. Keep Automatic Sync off during the controlled acceptance test. No live ERP access or activation is performed by this release.

After merging this release:

```sh
cd ~/frappe-bench/apps/worldshading
git pull --ff-only origin main
cd ~/frappe-bench
bench --site erp.worldshading.com execute worldshading.integration.woocommerce.install.upgrade_linking
bench --site erp.worldshading.com clear-cache
bench restart
```

`upgrade_linking` performs destination preflight, verifies the existing connector child DocType, reloads only the new native Page, clears cache and commits. It does not run migrate, reload DocTypes, change mappings/settings or run tests. Restart loads the new Python endpoints and the link-only Item hook guard into web and worker processes.

Before switching the Woo button, confirm this ERP route opens as an ERP System Manager:

`https://erp.worldshading.com/desk#ws-woocommerce-link/33166/all/shop.worldshading.com`

Loading the window makes read requests only. It requires the configured Woo credentials and matching store hostname. Save requires normal ERP System Manager and Item write permissions. Ordinary Woo shop-manager access alone does not grant ERP access.

Then update only the bounded mapping-helper block in the existing World Shading Custom WordPress plugin using `deploy/woocommerce/wordpress/mapping-helper.php`. Preserve the current entry-file prefix and every other plugin module. Do not replace the live plugin with an older full ZIP. The paired helper is the 1.13.7 update; see its deployment README.

## One-product acceptance

1. Log into both systems with the appropriate permissions. Open Pagoda Tent on Woo and click ERPNext Mapping.
2. Choose 3m (parent 33166, variation 33168, SKU DCPT0003), the approved existing ERP Item for that size, and its whole-tent UOM. Verify conversion in the Item's UOM table.
3. Save Link. Confirm the new child row exists under that Item and remains inactive. Confirm Woo stock and prices are unchanged.
4. Reopen the popup: it should show the same linked Item and inactive state. Saving unchanged must not create a duplicate. Repeat separately for 5m (variation 33169, SKU DCPT0005) using its own approved Item.
5. Review and preview the Item link before enabling or manually syncing it. Publishing remains the existing connector workflow.

## Authentication and behavior

WordPress stores no ERP credentials. The popup uses the normal ERP session, CSRF checks and existing configured Woo API credentials on the ERP server. There are no guest linking endpoints, CORS changes or Woo write calls. Remote identity is reread before save. Target locking, normal Item save validation and Item timestamp checks reject conflicting changes. Link-only saves suppress only this connector's Item-change notification; ordinary Item saves still request normal syncing.

Popup blocking falls back to a normal new tab. Modifier-click also opens normally. The admin identifier table and Copy controls remain available. Incorrect ERP-origin configuration falls back to that identifier page.

## Rollback and verification limits

Restore the previous Woo helper first, then revert the ERP release and restart web/workers if needed. The unused native Page can remain installed; no business records are deleted. A link deliberately saved during acceptance remains an inactive Item row and should be reviewed explicitly rather than automatically removed.

Standalone tests cover backend authorization, native UOMs, identity/ownership checks, timestamps, duplicate saves, no-publish hook behavior, UI stale responses/loading/save locking, and WordPress authorization/URLs/output. These checks do not establish successful production login, live Item validation or a live mapping save. Perform the acceptance sequence above after installation. Never run Frappe's business-site test runner for this release.
