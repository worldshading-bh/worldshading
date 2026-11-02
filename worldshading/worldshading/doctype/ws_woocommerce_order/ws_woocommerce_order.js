frappe.ui.form.on('WS WooCommerce Order', {
    refresh(frm) {
        const escape=value => frappe.utils.escape_html(String(value == null ? '' : value));
        if (!frm.is_new()) frappe.call({method:'worldshading.integration.woocommerce.api.order_review',args:{name:frm.doc.name},
            callback(r) {
                if (!r.message) return;
                if (r.message.error) {frm.dashboard.add_section('<p>'+escape(r.message.error)+'</p>','Product mappings');return;}
                const rows=r.message.lines || [];
                if (!rows.length) return;
                let html='<p>Check the Item links and selling units. Resolve any errors, then click Retry Import.</p><table class="table table-bordered"><thead><tr><th>WooCommerce product</th><th>Product / variation</th><th>ERP Item / action needed</th></tr></thead><tbody>';
                for (const row of rows) html+='<tr><td>'+escape(row.name)+'<br>'+escape(row.sku)+'</td><td>'+escape(row.product_id)+' / '+escape(row.variation_id)+'</td><td>'+escape(row.item_code || row.error)+'</td></tr>';
                html+='</tbody></table>';
                frm.dashboard.add_section(html,'Product mappings');
            }
        });
        if (!frm.is_new()) frm.add_custom_button('Retry Import', () => frappe.call({
            method:'worldshading.integration.woocommerce.api.retry_order',args:{name:frm.doc.name},freeze:true,
            callback(r) { const result = r.message || {};
                frappe.msgprint({title:'Order Import', message:'<p>'+escape(result.status || 'Finished')+'</p>' +
                    (result.error ? '<p>'+escape(result.error)+'</p>' : '') +
                    (result.sales_order ? '<p>Sales Order: '+escape(result.sales_order)+'</p>' : '')});
                frm.reload_doc(); }
        }), 'WooCommerce');
        if (!frm.is_new()) frm.add_custom_button('Ignore Import', () => frappe.prompt({
            fieldname:'reason',fieldtype:'Small Text',label:'Review reason',reqd:1
        }, values => frappe.call({method:'worldshading.integration.woocommerce.api.ignore_order',
            args:{name:frm.doc.name,reason:values.reason},callback() {frm.reload_doc();}}),
            'Skip this import (does not cancel either order)'), 'WooCommerce');
    }
});
