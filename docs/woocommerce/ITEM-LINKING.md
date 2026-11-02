# Link WooCommerce products to ERPNext Items

Start in **WS WooCommerce Settings → WooCommerce → Link Matching Items** for catalog-wide matching. Prepare Woo SKUs in Excel/CSV so each simple product or variation has its own SKU exactly equal to the ERP Item Code. Preview a batch, review the proposed Item and selling UOM, select the rows, then create the reviewed links. Each batch pauses after at most 25 results or ten catalog requests. Use Next Batch to continue, or Save Preview / Resume Saved Preview to return in the same browser within 24 hours. These links are active for stock only; price sync remains off. Existing links are preserved.

Sales UOM is taken from the ERP Item only when its normal conversion is valid. With no Sales UOM, a sole valid unit is used. Items with ambiguous units go to Review. The connector never creates an Item or invents a conversion.

For exceptions, open **ERPNext Mapping** from WooCommerce. The ERP page shows all variations together, including when launched from a single variation. Choose the Item and selling UOM per row, select only the rows to create, then **Save Links**. Prefilled suggestions are not selected automatically. New manual links remain inactive for review; existing active links are read-only. IDs and SKUs are read from the configured store, so no manual copying is needed. Both methods use the normal logged-in ERP session and normal Item permissions.

See [current production update and acceptance](PRODUCTION-HARDENING.md) for the targeted upgrade command, optional automatic matching, failure handling and rollback. This update needs no WordPress deployment when the current mapping links already open ERP correctly.
