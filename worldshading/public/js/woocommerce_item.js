frappe.ui.form.on('Item', {
    refresh(frm) {
        if (!frm.fields_dict.ws_woocommerce_links) return;
        const manager = frappe.user.has_role('System Manager');
        frm.set_df_property('ws_woocommerce_links', 'read_only', !manager);
        frm.set_query('sale_uom', 'ws_woocommerce_links', () => ({filters: {
            name: ['in', [...new Set([frm.doc.stock_uom].concat((frm.doc.uoms || []).map(row => row.uom)).filter(Boolean))]]
        }}));
        const escape = value => frappe.utils.escape_html(String(value == null ? '' : value));
        const display = value => escape(value === true ? 'Yes' : value === false ? 'No' : value);
        const status = () => {
            if (frm.is_new() || !manager) return;
            frappe.call({method:'worldshading.integration.woocommerce.api.item_status',args:{item_code:frm.doc.name},
                callback(r) {
                    if (!r.message) return;
                    let html = '<p>Sync status is read from Sync Log. Checking or syncing does not save this Item.</p>';
                    if ((r.message.stock_orders || []).length) html += '<p><strong>Stock for this Item is held by orders '+r.message.stock_orders.map(escape).join(', ')+'. Price updates can continue. Resolve these orders, then retry import.</strong></p>';
                    for (const row of r.message.links) {
                        const label = {Skipped:'Already matching',Success:'Synced',Failed:'Failed'}[row.status] || row.status;
                        html += '<p><strong>'+escape(row.sku)+'</strong>: '+escape(label)+
                            '. Last successful check: '+escape(row.last_success ? String(row.last_success).split('.')[0] : 'Not checked')+'.'+
                            (row.error ? '<br>'+escape(row.error) : '')+'</p>';
                    }
                    frm.fields_dict.ws_woocommerce_status.$wrapper.html(html);
                }
            });
        };
        status();
        if (frm.is_new() || !manager) return;
        const run = (method, row) => frappe.call({
            method:'worldshading.integration.woocommerce.api.'+method,args:{name:row.name},freeze:true,
            callback(r) {
                const result=r.message;
                if (!result) return;
                let message='';
                if (method==='preview_product') {
                    const labels={regular_price:'Regular price',sale_price:'Sale price',stock_quantity:'Available stock',manage_stock:'Manage stock',stock_status:'Stock status',backorders:'Backorders'};
                    message='<p>'+escape(result.item_code)+' — preview only</p>';
                    if (result.product_url) message+='<p><a href="'+escape(result.product_url)+'" target="_blank" rel="noopener noreferrer">Open product in WooCommerce ↗</a></p>';
                    message+='<table class="table table-bordered"><thead><tr><th>Field</th><th>WooCommerce now</th><th>ERPNext value</th></tr></thead><tbody>';
                    for (const key of Object.keys(result.expected)) message+='<tr><td>'+escape(labels[key] || key)+'</td><td>'+display(result.current[key])+'</td><td>'+display(result.expected[key])+'</td></tr>';
                    message+='</tbody></table>';
                    if ((result.warehouses || []).length) message+='<p>Stock warehouses: '+result.warehouses.map(escape).join(', ')+'.</p>';
                    message+='<p>'+escape(result.message)+'</p>';
                } else {
                    for (const product of result.products || []) {
                        message+='<p>'+escape(product.item_code)+': '+escape(product.status)+(product.error ? ' — '+escape(product.error) : '')+'</p>';
                        if (product.stock_blocked) message+='<p>Stock held for orders '+(product.stock_orders || []).map(escape).join(', ')+'. Any price result above applies to price only.</p>';
                    }
                }
                if (method==='preview_product' && result.stock_blocked) message+='<p><strong>Stock for this Item is held by orders '+(result.stock_orders || []).map(escape).join(', ')+'. Price updates can continue. Stock values above are a preview only.</strong></p>';
                frappe.msgprint({title:'WooCommerce item',message:message});
                status();
            }
        });
        const choose = method => {
            if (frm.is_dirty()) {frappe.msgprint('Save the Item before previewing or syncing WooCommerce links.');return;}
            const rows=(frm.doc.ws_woocommerce_links || []).filter(row => row.enabled);
            if (!rows.length) {frappe.msgprint('Add and enable a WooCommerce link in this Item first.');return;}
            if (rows.length===1) {run(method,rows[0]);return;}
            frappe.prompt([{fieldname:'link',label:'WooCommerce Link',fieldtype:'Select',options:rows.map(row => row.name).join('\n'),reqd:1}],
                values => run(method,rows.find(row => row.name===values.link)),'Choose WooCommerce Link');
        };
        frm.add_custom_button('Preview WooCommerce', () => choose('preview_product'));
        frm.add_custom_button('Sync WooCommerce', () => choose('sync_product'));
    }
});
