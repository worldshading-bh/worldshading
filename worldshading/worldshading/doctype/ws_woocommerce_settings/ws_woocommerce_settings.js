frappe.ui.form.on('WS WooCommerce Settings', {
    refresh(frm) {
        frm.add_custom_button('Connector Guide', () => frappe.set_route('ws-woocommerce-guide'), 'WooCommerce');
        frm.add_custom_button('Link Matching Items', () => {
            if (frm.is_dirty()) {frappe.msgprint('Save Settings before opening the bulk preview.');return;}
            frappe.set_route('ws-woocommerce-link','bulk');
        }, 'WooCommerce');
        const warehouseFilters=() => ({filters:{company:frm.doc.company,is_group:0,disabled:0}});
        frm.set_query('warehouse',warehouseFilters);
        frm.set_query('warehouse','stock_warehouses',warehouseFilters);
        const zone = frappe.sys_defaults.time_zone || 'site timezone';
        frm.set_df_property('order_since_local', 'description',
            'Time zone: ' + zone + '. Use Now to start with new orders.');
        const escape = value => frappe.utils.escape_html(String(value == null ? '' : value));
        const call = method => {
            if (frm.is_dirty()) {
                frappe.msgprint('Save your settings before running a connector action.');
                return;
            }
            frappe.call({
                method: 'worldshading.integration.woocommerce.api.' + method,
                freeze: true,
                callback(r) {
                    const result = r.message;
                    if (!result) return;
                    let message;
                    if (method === 'test_connection') {
                        message = '<p><strong>Connected to ' + escape(result.store_url) + '</strong></p>' +
                            '<p>Currency: ' + escape(result.currency) + '. Products and orders are readable.</p>' +
                            '<p>No records changed. Write access is checked during product sync.</p>';
                    } else {
                        const products = result.products || [];
                        message = '<p>Orders checked: ' + escape(result.orders) + '. Retried: ' + escape(result.retries) + '.</p>' +
                            '<p>Products updated: ' + products.filter(p => p.status === 'Updated').length +
                            '. Already matching: ' + products.filter(p => p.status === 'Unchanged').length +
                            '. Failed: ' + products.filter(p => p.status === 'Failed').length + '.</p>';
                        if (result.review_required) message += '<p><strong>' + escape(result.review_required) + ' orders require review in Order Inbox.</strong></p>';
                        if (result.stock_blocked) message += '<p>Stock held for '+escape(result.stock_blocked)+' affected products. Unrelated products and enabled price updates continue.</p>';
                        for (const product of products.filter(p => p.stock_blocked)) {
                            message += '<p>'+escape(product.item_code)+': stock held by orders '+(product.stock_orders || []).map(escape).join(', ')+'.</p>';
                        }
                        for (const product of products.filter(p => p.status === 'Failed')) {
                            message += '<p>' + escape(product.item_code) + ': ' + escape(product.error) + '</p>';
                        }
                    }
                    frappe.msgprint({title: 'WooCommerce connector', message: message});
                    frm.reload_doc();
                }
            });
        };
        frm.add_custom_button('Test Connection', () => call('test_connection'), 'WooCommerce');
        frm.add_custom_button('Import Orders', () => call('import_orders'), 'WooCommerce');
        frm.add_custom_button('Sync Prices and Stock', () => call('reconcile'), 'WooCommerce');
        for (const [label, type] of [['Items','Item'],['Order Inbox','WS WooCommerce Order'],['Sync Logs','WS WooCommerce Sync Log']]) {
            frm.add_custom_button(label, () => frappe.set_route('List',type), 'WooCommerce');
        }
        frappe.call({method:'worldshading.integration.woocommerce.api.dashboard',callback(r) {
            if (!r.message) return;
            const d = r.message;
            const mode = !d.enabled ? 'Connector disabled. Connection checks and previews are available.' :
                d.automatic_sync ? 'Automatic sync enabled. Background services must be running.' :
                'Manual mode. Orders and products change only when you run an action.';
            frm.fields_dict.dashboard.$wrapper.html('<p><strong>'+escape(d.mappings)+'</strong> active mappings · <strong>'+escape(d.imported)+'</strong> imported orders · <strong>'+escape(d.review)+'</strong> requiring review</p><p>'+mode+'</p>');
        }});
    }
});
