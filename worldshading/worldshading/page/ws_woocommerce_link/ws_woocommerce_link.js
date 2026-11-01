/* Uses the logged-in ERP session. WooCommerce receives no ERP credentials. */
frappe.WSWooLinkForm = class {
    constructor(wrapper) {
        this.page = frappe.ui.make_app_page({parent:wrapper,title:'Link WooCommerce Item',single_column:true});
        this.body = $('<div class="ws-woo-link-form" style="max-width:960px;padding:15px 0"></div>').appendTo(this.page.main);
        this.heading = $('<p class="text-muted">Choose a website variation, then its ERPNext Item and selling unit.</p>').appendTo(this.body);
        this.targetField = this.control('Select','variation','WooCommerce Product / Variation',this.body,() => this.choose_target());
        this.identity = $('<div></div>').appendTo(this.body);
        const row = $('<div class="row"></div>').appendTo(this.body);
        this.itemField = this.control('Link','item_code','ERPNext Item',$('<div class="col-sm-6"></div>').appendTo(row),() => this.choose_item(),'Item');
        this.itemField.get_query = () => ({query:'worldshading.integration.woocommerce.linking.search_items'});
        this.uomField = this.control('Select','sale_uom','Selling UOM',$('<div class="col-sm-6"></div>').appendTo(row),() => this.update_save());
        this.status = $('<p role="status" aria-live="polite"></p>').appendTo(this.body);
        this.pager = $('<div class="btn-group"></div>').appendTo(this.body);
        this.page.set_primary_action('Save Link',() => this.save());
        this.page.add_inner_button('Reload',() => {if (!this.busy) this.show_route();});
        this.page.add_inner_button('Open ERPNext Item',() => {
            if (this.itemField.get_value()) frappe.set_route('Form','Item',this.itemField.get_value());
        });
        this.itemEpoch = 0;
        this.loadEpoch = 0;
        this.ready = true;
        this.update_save();
    }
    control(fieldtype,fieldname,label,parent,change,options) {
        const control = frappe.ui.form.make_control({parent:parent,df:{fieldtype,fieldname,label,options,change:() => {if (this.ready) change();},reqd:1},render_input:true});
        return control;
    }
    call(method,args,callback,always) {
        frappe.call({method:'worldshading.integration.woocommerce.linking.'+method,args:args,callback:r => {
            if (r.message) callback(r.message);
        },always:always});
    }
    escape(value) { return frappe.utils.escape_html(String(value == null ? '' : value)); }
    clear_selection() {
        ++this.itemEpoch;
        this.targets = []; this.target = null; this.itemOptions = null;
        this.targetField.df.options = ''; this.targetField.refresh(); this.targetField.set_value('');
        this.itemField.set_value('');
        this.uomField.df.options = ''; this.uomField.refresh(); this.uomField.set_value('');
        this.identity.empty(); this.pager.empty(); this.status.text('');
        this.update_save();
    }
    show_route() {
        const route = frappe.get_route();
        const id = route[1];
        const variation = route[2] === 'all' ? undefined : route[2];
        const source = route[3];
        if (!source || !/^[a-zA-Z0-9.-]+$/.test(source) || !/^[1-9][0-9]{0,11}$/.test(id || '') || (variation != null && !/^[0-9]{1,12}$/.test(variation))) {
            ++this.loadEpoch;
            this.loading = false;
            this.clear_selection();
            this.heading.text('Open a product using ERPNext Mapping in WooCommerce.');
            this.identity.empty(); this.pager.empty();
            this.update_save();
            return;
        }
        this.productId = id;
        this.sourceHost = source;
        this.load(1,variation);
    }
    load(page,variation) {
        const epoch = ++this.loadEpoch;
        this.loading = true;
        this.clear_selection(); this.set_busy(!!this.busy);
        this.heading.text('Loading WooCommerce product…');
        let loaded = false;
        this.call('product_targets',{product_id:this.productId,page:page,variation_id:variation,source_host:this.sourceHost},data => {
            if (epoch !== this.loadEpoch) return;
            loaded = true; this.loading = false;
            this.targets = data.targets;
            this.heading.text(data.product_name+' · '+data.store_url);
            this.targetField.df.options = this.targets.map(t => t.variation_id+': '+String(t.label).replace(/[\r\n]/g,' ')).join('\n');
            this.targetField.refresh();
            this.targetField.set_value(this.targets.length ? this.targetField.df.options.split('\n')[0] : '');
            this.choose_target();
            this.set_busy(!!this.busy);
            this.pager.empty();
            if (data.page > 1) $('<button type="button" class="btn btn-default">Previous variations</button>').appendTo(this.pager).on('click',() => this.load(data.page-1));
            if (data.has_more) $('<button type="button" class="btn btn-default">More variations</button>').appendTo(this.pager).on('click',() => this.load(data.page+1));
            if (variation != null) $('<button type="button" class="btn btn-default">All variations</button>').appendTo(this.pager).on('click',() => this.load(1));
            if (!this.targets.length) this.status.text('No variations on this page. Go back to the previous page.');
        },() => {
            if (epoch !== this.loadEpoch) return;
            this.loading = false; this.set_busy(!!this.busy);
            if (!loaded) this.status.text('Product could not be loaded. Use Reload to try again.');
        });
    }
    choose_target() {
        if (this.loading || this.busy) return;
        const index = (this.targetField.df.options || '').split('\n').indexOf(this.targetField.get_value());
        const next = (this.targets || [])[index] || null;
        if (next && this.target === next) return;
        ++this.itemEpoch;
        this.target = next;
        this.itemOptions = null;
        this.itemField.df.read_only = !!(this.target && this.target.link);
        this.itemField.refresh();
        this.uomField.df.read_only = !!(this.target && this.target.link && this.target.link.enabled);
        this.uomField.df.options = ''; this.uomField.refresh(); this.uomField.set_value('');
        this.identity.empty();
        if (this.target) {
            const t = this.target;
            this.identity.html('<table class="table table-bordered"><thead><tr><th>Product ID</th><th>Variation ID</th><th>SKU</th></tr></thead><tbody><tr><td>'+this.escape(t.product_id)+'</td><td>'+this.escape(t.variation_id)+'</td><td>'+this.escape(t.sku)+'</td></tr></tbody></table>');
            this.status.text(!t.linkable ? 'Set a SKU in WooCommerce before linking.' : t.link ?
                (t.link.enabled ? 'Linked and active. Edit this link in the ERPNext Item.' : 'Linked, inactive. Review and enable it in the ERPNext Item when ready.') :
                'A new link will be saved inactive. Review it in ERPNext before enabling stock or price sync.');
        }
        const item = this.target && this.target.link ? this.target.link.item_code : '';
        this.itemField.set_value(item);
        if (item) this.choose_item();
        this.update_save();
    }
    choose_item() {
        const epoch = ++this.itemEpoch;
        const target = this.target;
        const code = this.itemField.get_value();
        this.itemOptions = null;
        this.uomField.df.options = ''; this.uomField.refresh(); this.uomField.set_value('');
        this.update_save();
        if (!code || !target) return;
        this.call('item_uoms',{item_code:code},data => {
            if (epoch !== this.itemEpoch || target !== this.target || code !== this.itemField.get_value()) return;
            this.itemOptions = data;
            this.uomField.df.options = data.uoms.map(u => u.uom).join('\n');
            this.uomField.refresh();
            const previous = target.link && target.link.sale_uom;
            this.uomField.set_value(previous && data.uoms.some(u => u.uom===previous) ? previous : data.uoms.length===1 ? data.uoms[0].uom : '');
            this.update_save();
        });
    }
    update_save() {
        if (!this.page.btn_primary || !this.uomField || !this.itemField) return;
        const uom = this.uomField.get_value();
        const valid = !this.busy && !this.loading && this.target && this.target.linkable && !(this.target.link && this.target.link.enabled) && this.itemOptions &&
            this.itemOptions.item_code===this.itemField.get_value() && this.itemOptions.uoms.some(u => u.uom===uom);
        this.page.btn_primary.prop('disabled',!valid);
    }
    set_busy(value) {
        this.busy = value;
        this.targetField.df.read_only = !!(value || this.loading);
        this.targetField.refresh();
        this.itemField.df.read_only = !!(value || this.loading || this.target && this.target.link);
        this.itemField.refresh();
        this.uomField.df.read_only = !!(value || this.loading || this.target && this.target.link && this.target.link.enabled);
        this.uomField.refresh();
        this.update_save();
    }
    save() {
        this.update_save();
        if (this.page.btn_primary.prop('disabled')) return;
        const target = this.target, options = this.itemOptions;
        this.set_busy(true);
        this.call('save_link',{item_code:options.item_code,sale_uom:this.uomField.get_value(),
            source_host:this.sourceHost,product_id:target.product_id,variation_id:target.variation_id,expected_sku:target.sku,expected_modified:options.modified},data => {
            if (target !== this.target) return;
            target.link = data;
            options.modified = data.modified;
            this.status.text(data.enabled ? 'Linked and active.' : 'Link saved, inactive. Open the ERPNext Item to preview and enable it when ready.');
            this.itemField.df.read_only = true; this.itemField.refresh();
        },() => this.set_busy(false));
    }
};
frappe.pages['ws-woocommerce-link'].on_page_load = function(wrapper) {
    wrapper.woo_link_form = new frappe.WSWooLinkForm(wrapper);
};
frappe.pages['ws-woocommerce-link'].on_page_show = function(wrapper) {
    wrapper.woo_link_form.show_route();
};
