frappe.pages['ws-woocommerce-guide'].on_page_load = function(wrapper) {
    const page = frappe.ui.make_app_page({
        parent: wrapper,
        title: 'WooCommerce Connector Guide',
        single_column: true
    });
    page.main.append(frappe.render_template('ws_woocommerce_guide', {}));
    page.set_primary_action('Connector Settings', () => {
        frappe.set_route('Form', 'WS WooCommerce Settings', 'WS WooCommerce Settings');
    });
    page.main.on('click', '[data-guide-target]', function() {
        const target = page.main.find('[data-guide-section="' + $(this).attr('data-guide-target') + '"]')[0];
        if (target) {
            target.scrollIntoView({block: 'start'});
            target.focus({preventScroll: true});
        }
    });
};
