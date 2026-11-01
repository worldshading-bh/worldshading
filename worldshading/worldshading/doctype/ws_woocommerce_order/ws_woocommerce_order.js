frappe.ui.form.on('WS WooCommerce Order', {
    refresh(frm) {
        const escape=value => frappe.utils.escape_html(String(value == null ? '' : value));
        if (!frm.is_new()) frappe.call({method:'worldshading.integration.woocommerce.api.order_review',args:{name:frm.doc.name},
            callback(r) {
                if (!r.message) return;
                if (r.message.error) {frm.dashboard.add_section('<p>'+escape(r.message.error)+'</p>','Product mappings');return;}
                const rows=r.message.lines || [];
                if (!rows.length) return;
                let html='<p>Link every product to its correct ERP Item and selling UOM, then click Retry Import. Unrelated products can continue syncing.</p><table class="table table-bordered"><thead><tr><th>WooCommerce product</th><th>Product / variation</th><th>ERP Item / action needed</th></tr></thead><tbody>';
                for (const row of rows) html+='<tr><td>'+escape(row.name)+'<br>'+escape(row.sku)+'</td><td>'+escape(row.product_id)+' / '+escape(row.variation_id)+'</td><td>'+escape(row.item_code || row.error)+'</td></tr>';
                html+='</tbody></table>';
                frm.dashboard.add_section(html,'Product mappings');
            }
        });
        if (!frm.is_new()) frm.add_custom_button('Retry Import', () => frappe.call({
            method:'worldshading.integration.woocommerce.api.retry_order',args:{name:frm.doc.name},freeze:true,
            callback(r) { frappe.msgprint('<pre>'+frappe.utils.escape_html(JSON.stringify(r.message,null,2))+'</pre>');frm.reload_doc(); }
        }));
        if (!frm.is_new()) frm.add_custom_button('Ignore Import', () => frappe.prompt({
            fieldname:'reason',fieldtype:'Small Text',label:'Review reason',reqd:1
        }, values => frappe.call({method:'worldshading.integration.woocommerce.api.ignore_order',
            args:{name:frm.doc.name,reason:values.reason},callback() {frm.reload_doc();}}),
            'Skip this import (does not cancel either order)'));
    }
});
