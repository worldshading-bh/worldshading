# SKU-assisted linking

The confirmed design uses SKU to discover a match and saved Woo IDs for subsequent syncing. No background process creates links. Only Save Link persists a mapping, and new mappings remain inactive.

## From an ERP Item

Save any Item edits first. Click **Link WooCommerce**. The linking page searches WooCommerce using the ERP Item Code as the initial SKU. If the website uses a different SKU, enter that code and click **Find by SKU**. Confirm the displayed product and size, choose an existing native UOM, then Save Link. When the Item has several valid UOMs, none is guessed.

## From WooCommerce

Open the product's Link Item action. If the exact variation has a usable SKU matching one active ERP Item Code, the form selects that Item automatically. Check its size and UOM before saving. Existing links take precedence over suggestions. Conflicting links require manual review.

## What SKU matching means

- Exact, case-sensitive SKU equality. No fuzzy name matching or first-result selection.
- SKU filtering uses the configured Woo store only. A bounded products collection lookup includes variations; incomplete or ambiguous results are rejected. No catalog scan runs on stock events.
- A variable parent is not a sellable match. Its SKU cannot automatically select a size.
- Woo's variation endpoint can return the parent's SKU even with context=edit. A blank variation SKU or a response equal to the parent SKU is treated as inherited/unverified and excluded from automatic matching. The products collection's SKU query validates the exact target before an Item is suggested.
- Manual target selection remains available for inherited SKUs when the existing connector identity checks can validate a nonblank effective SKU. Truly blank products need a SKU before linking.
- SKU changes do not silently reassign existing links. Normal SKU guards and disabled-link review still apply.
- No ERP credentials are sent to WordPress. Existing ERP login, System Manager access and normal Item save permissions remain required.

## Production release steps

After merging this feature PR, run on the ERP server:

```sh
cd ~/frappe-bench/apps/worldshading
git pull --ff-only origin main
cd ~/frappe-bench
bench --site erp.worldshading.com execute worldshading.integration.woocommerce.install.upgrade_linking
bench --site erp.worldshading.com clear-cache
bench restart
```

This reuses the existing page-only upgrade: no migrate, no DocType reload and no business-site tests. Native Page JS and the existing Item doctype script are refreshed through the cache clear/restart and a browser hard refresh. No new WordPress deployment is required; its current Link Item buttons keep working.

## Acceptance without publishing

1. Use an approved SKU that already uniquely identifies a Woo simple product or variation. Open Link WooCommerce from its ERP Item or enter the SKU directly at /desk#ws-woocommerce-link.
2. Confirm the server filled the exact parent/variation IDs under Connection details.
3. From the Woo side, verify an exact ERP Item Code match preselects the Item. Check a mismatching case and an inherited parent SKU do not preselect an Item.
4. Verify multiple Item UOMs require a choice. Stop before Save Link for read-only acceptance.
5. Under explicit authorization, save one approved mapping; confirm inactive status and unchanged Woo stock/prices. Enable/sync remains a separate action.

No live ERP record, SKU or sync setting was changed during implementation. Standalone fixtures verify behavior; live Woo REST responses and Frappe v12 browser controls still need acceptance after deployment.

## References reviewed

- Fusion sync_items.py at ab71a15: existing server/ID link first, optional SKU-to-Item-Code matching.
- Libracore sync_products.py at 8b8cea4: barcode/SKU bootstrap stores Woo IDs.
- Odoo for WooCommerce official extension documentation: SKU maps to Internal Reference/Barcode.
- Woo REST v3 products and variations controllers: SKU collection filtering includes variations, but variation get_sku does not forward edit context.

These are design references, not copied connector implementations or a claim of identical behavior across all plugins.
