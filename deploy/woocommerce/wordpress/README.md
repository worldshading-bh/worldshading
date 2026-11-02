# Paired WooCommerce helper 1.13.7

Install the ERP release and run its page-only upgrade first; see docs/woocommerce/ITEM-LINKING.md. Until that is done, retain the live 1.13.6 identifier viewer.

`mapping-helper.php` contains the complete replacement WSC_ERP_Product_Mapping class and registration. In the existing World Shading Custom plugin entry file, replace only the old bounded helper block (beginning `// Read-only ERPNext mapping helper. Keep this block together for rollback.`) with this helper, omitting its opening PHP tag and ABSPATH guard when appending inside the entry file. Keep a fresh backup of the live entry file first. Update the plugin header version from 1.13.6 to 1.13.7; preserve all preceding code and other modules.

The default public ERP origin is https://erp.worldshading.com. A deployment can override WSC_ERP_MAPPING_ORIGIN with an HTTPS origin only (no credentials, port, query or path). Source-store identity comes from WordPress home_url and must match the connector's configured store hostname. No ERP credentials belong in WordPress.

Verify saved source and PHP syntax, then check the product toolbar, edit-product sidebar and identifier-table row Link Item buttons. The ERP popup requires a separate ERP login and System Manager/Item write permissions. Guests and ordinary customers must see none of these manager controls.

Rollback: restore just the saved 1.13.6 entry file, leaving all other plugin files and ERP records intact. No WordPress database changes are introduced.
