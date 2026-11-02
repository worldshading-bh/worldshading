/* ERP session only; WooCommerce receives no ERP credentials. */
frappe.WSWooLinkForm = class {
    constructor(wrapper) {
        this.page=frappe.ui.make_app_page({parent:wrapper,title:'Link WooCommerce Items',single_column:true});
        this.body=$('<div class="ws-woo-linking"></div>').appendTo(this.page.main);
        $('<style>.ws-woo-linking{padding:24px;max-width:1400px;margin:auto}.ws-woo-linking .ws-intro{margin-bottom:24px}.ws-woo-linking .ws-tools{display:flex;flex-wrap:wrap;gap:12px;align-items:flex-end;margin:16px 0}.ws-woo-linking .ws-search{width:360px;max-width:75%}.ws-woo-linking .form-group{margin-bottom:0}.ws-woo-linking .ws-table{overflow-x:auto;border:1px solid #d1d8dd;border-radius:6px;margin:20px 0}.ws-woo-linking table{width:100%;margin:0}.ws-woo-linking th{background:#f7fafc;white-space:nowrap}.ws-woo-linking th,.ws-woo-linking td{padding:14px!important;vertical-align:top!important}.ws-woo-linking .ws-unit{min-width:140px}.ws-woo-linking .ws-item{min-width:230px}.ws-woo-linking .ws-name{min-width:190px}.ws-woo-linking .ws-note{font-size:12px;color:#6c7680;margin-top:6px}.ws-woo-linking .ws-focus{background:#fff9e8}.ws-woo-linking .ws-status{min-width:170px}.ws-woo-linking small{display:block;margin-top:6px}.ws-woo-linking [role=status]{margin:12px 0}@media(max-width:767px){.ws-woo-linking{padding:16px}.ws-woo-linking th,.ws-woo-linking td{padding:10px!important}}</style>').appendTo(this.body);
        this.heading=$('<div class="ws-intro"></div>').appendTo(this.body);
        this.tools=$('<div class="ws-tools"></div>').appendTo(this.body);
        this.skuField=this.control('Data','woo_sku','Find product by SKU',$('<div class="ws-search"></div>').appendTo(this.tools),()=>{});
        this.findButton=$('<button class="btn btn-default" type="button">Find Product</button>').appendTo(this.tools).on('click',()=>this.find_sku());
        this.nextBatchButton=$('<button class="btn btn-default" type="button">Next Batch</button>').appendTo(this.tools).on('click',()=>this.scan(true));
        this.savePreviewButton=$('<button class="btn btn-default" type="button">Save Preview</button>').appendTo(this.tools).on('click',()=>this.save_preview());
        this.resumeButton=$('<button class="btn btn-default" type="button">Resume Saved Preview</button>').appendTo(this.tools).on('click',()=>this.restore_preview());
        this.scanButton=$('<button class="btn btn-default" type="button">Preview Matching Items</button>').appendTo(this.tools).on('click',()=>this.scan());
        this.stopButton=$('<button class="btn btn-default" type="button">Stop and Review</button>').appendTo(this.tools).on('click',()=>{this.stopRequested=true;this.stopButton.prop('disabled',true);});
        this.status=$('<p role="status" aria-live="polite"></p>').appendTo(this.body);
        this.filters=$('<div class="btn-group"></div>').appendTo(this.body);this.filter='Ready';
        ['Ready','Review','All'].forEach(label=>$('<button type="button" class="btn btn-default"></button>').text(label).appendTo(this.filters).on('click',()=>{this.filter=label;this.render();}));
        this.table=$('<div class="ws-table"></div>').appendTo(this.body);
        this.moreButton=$('<button class="btn btn-default" type="button">Load More Variations</button>').appendTo(this.body).on('click',()=>this.load(this.nextPage));
        this.page.set_primary_action('Save Links',()=>this.save());
        this.page.add_inner_button('Reload',()=>{if(!this.busy&&!this.loading)this.show_route();},'WooCommerce');
        this.page.add_inner_button('Settings',()=>frappe.set_route('Form','WS WooCommerce Settings','WS WooCommerce Settings'),'WooCommerce');
        this.rows=[];this.epoch=0;this.ready=true;
    }
    control(fieldtype,fieldname,label,parent,change,options) {
        return frappe.ui.form.make_control({parent,df:{fieldtype,fieldname,label,options,change:()=>{if(this.ready)change();}},render_input:true});
    }
    escape(v){return frappe.utils.escape_html(String(v==null?'':v));}
    call(method,args,done,always,module='linking') {
        frappe.call({method:'worldshading.integration.woocommerce.'+module+'.'+method,args,callback:r=>{if(r.message)done(r.message);},always});
    }
    reset(bulk) {
        ++this.epoch;this.rows=[];this.loading=false;this.busy=false;this.bulk=bulk;this.reviewed=false;this.cursor={page:1,variation_page:1};this.pendingRows=[];this.catalogDone=false;
        this.table.empty().hide();this.moreButton.hide();this.status.text('');this.filters.toggle(bulk);
        this.tools.find('.ws-search').toggle(!bulk);this.findButton.toggle(!bulk);this.scanButton.toggle(bulk);this.stopButton.hide();this.update_save();
    }
    show_route() {
        if(this.busy)return;
        const seed=frappe.route_options&&frappe.route_options.ws_woo_link_seed;
        if(seed){this.seedItem=seed.item_code;this.skuField.set_value(seed.sku||'');frappe.route_options=null;}else this.seedItem=null;
        const route=frappe.get_route();this.reset(route[1]==='bulk');
        if(this.bulk){this.heading.html('<h4>Link matching SKUs</h4><p class="text-muted">Preview website SKUs against ERP Item Codes. Review the matches, then create active stock-only links. Existing links are preserved; prices stay off.</p>');return;}
        this.heading.html('<h4>Link a website product</h4><p class="text-muted">Choose the ERP Item and selling unit for each variation, then Save Links. New manual links are saved inactive for review.</p>');
        if(!route[1]){if(seed&&seed.sku)this.find_sku();return;}
        if(!/^[1-9][0-9]{0,11}$/.test(route[1])||!route[3]||!/^[a-zA-Z0-9.-]+$/.test(route[3])){this.status.text('Open ERPNext Mapping from the configured WooCommerce store.');return;}
        this.productId=route[1];this.sourceHost=route[3];this.focusVariation=route[2];this.load(1);
    }
    find_sku() {
        if(this.busy||this.loading)return;
        const sku=this.skuField.get_value();if(!sku){this.status.text('Enter a website SKU.');return;}
        const epoch=++this.epoch;this.loading=true;this.update_save();let found=false;
        this.call('find_by_sku',{sku},data=>{
            if(epoch!==this.epoch)return;
            found=true;this.productId=data.targets[0].product_id;this.sourceHost=data.source_host;this.focusVariation=data.targets[0].variation_id;
            this.rows=[];this.loading=false;this.load(1);
        },()=>{if(epoch===this.epoch&&!found){this.loading=false;this.status.text('No unique own SKU found. Check the SKU or open the product from WooCommerce.');this.update_save();}});
    }
    load(page) {
        if(this.busy||this.loading)return;
        if(page===1){this.rows=[];this.table.empty().hide();}
        const epoch=this.epoch;this.loading=true;this.update_save();let loaded=false;this.status.text('Loading product variations...');
        // A variation URL always opens the full parent sheet.
        this.call('product_sheet',{product_id:this.productId,source_host:this.sourceHost,page},data=>{
            if(epoch!==this.epoch)return;
            loaded=true;this.loading=false;
            this.heading.html('<h4>'+this.escape(data.product_name)+'</h4><p class="text-muted">Choose an Item and selling unit for each variation. Existing active links are shown for reference.</p>');
            data.targets.forEach(target=>this.rows.push({target,epoch:0,dirty:false}));
            this.nextPage=data.page+1;this.moreButton.toggle(data.has_more);this.render();
            this.status.text(this.rows.length ? this.rows.length+' variations loaded. Select the rows to save and confirm their selling units. New links stay inactive.' : 'This product has no variations to link. Set up its variations in WooCommerce, then Reload.');
            if(data.has_more)this.load(this.nextPage);
        },()=>{if(epoch===this.epoch&&!loaded){this.loading=false;this.status.text('Could not load more variations. Retry Load More or Reload.');this.moreButton.show();this.nextPage=page;this.update_save();}});
    }
    render() {
        this.filters.find('button').each((index,button)=>{const selected=$(button).text()===this.filter;$(button).toggleClass('btn-primary',selected).attr('aria-pressed',selected?'true':'false');});
        this.table.empty().show();
        const table=$('<table class="table"><thead><tr><th>Select</th><th>Product / variation</th><th>Woo SKU</th><th>ERPNext Item</th><th>Selling UOM</th><th>Status</th></tr></thead><tbody></tbody></table>').appendTo(this.table);
        const body=table.find('tbody');
        this.rows.forEach((row,index)=>{
            if(this.bulk&&this.filter!=='All'&&row.statusText!==this.filter)return;
            const t=row.target,tr=$('<tr></tr>').appendTo(body);
            const selectable=this.bulk?row.statusText==='Ready':!t.link||!t.link.enabled;
            const selector=$('<input type="checkbox" aria-label="Select this mapping">').prop('checked',!!row.selected).prop('disabled',!selectable||this.busy||this.loading);
            $('<td></td>').append(selector).appendTo(tr);
            selector.on('change',()=>{row.selected=selector.prop('checked');this.update_save();});
            row.selector=selector;
            if(String(t.variation_id)===String(this.focusVariation))tr.addClass('ws-focus');
            $('<td class="ws-name"></td>').html(this.escape(t.label)+'<div class="ws-note">Product '+this.escape(t.product_id)+(t.variation_id?' / Variation '+this.escape(t.variation_id):'')+'</div>').appendTo(tr);
            $('<td></td>').html(this.escape(t.sku||'-')+(t.sku_inherited?'<div class="ws-note">Inherited; set an own SKU for bulk matching</div>':'')).appendTo(tr);
            const itemCell=$('<td class="ws-item"></td>').appendTo(tr),unitCell=$('<td class="ws-unit"></td>').appendTo(tr);row.status=$('<td class="ws-status"></td>').appendTo(tr);
            if(this.bulk){
                if(row.item_code)itemCell.html('<a href="/desk#Form/Item/'+encodeURIComponent(row.item_code)+'">'+this.escape(row.item_code)+'</a>');else itemCell.text('-');
                unitCell.text(row.sale_uom||'-');this.row_status(row,row.statusText,row.reason);return;
            }
            const oldCode=row.itemField&&row.itemField.get_value(),oldUom=row.uomField&&row.uomField.get_value();
            row.itemField=this.control('Link','item_'+index,'',itemCell,()=>this.choose_item(row),'Item');row.itemField.get_query=()=>({query:'worldshading.integration.woocommerce.linking.search_items'});
            row.uomField=this.control('Select','uom_'+index,'',unitCell,()=>{row.dirty=true;this.update_save();});
            const code=oldCode||(t.link&&t.link.item_code)||(t.suggestion&&t.suggestion.item_code)||(String(t.variation_id)===String(this.focusVariation)?this.seedItem:'')||'';
            this.ready=false;row.itemField.set_value(code);this.ready=true;
            this.row_status(row,t.link?(t.link.enabled?'Active link':'Inactive link'):'Not linked',t.suggestion&&t.suggestion.reason);
            if(row.options&&row.options.item_code===code)this.set_units(row,row.options,oldUom);else if(code)this.choose_item(row);
        });this.update_save();
    }
    row_status(row,title,note) {
        row.status.html('<strong>'+this.escape(title||'')+'</strong>'+(note?'<small>'+this.escape(note)+'</small>':'')+(row.target.link?'<small><a href="/desk#Form/Item/'+encodeURIComponent(row.target.link.item_code)+'">Open Item</a></small>':''));
    }
    choose_item(row) {
        if(this.busy)return;
        const epoch=++row.epoch,loadEpoch=this.epoch,code=row.itemField.get_value();row.options=null;row.dirty=true;
        row.uomField.df.options='';row.uomField.refresh();this.ready=false;row.uomField.set_value('');this.ready=true;this.update_save();if(!code)return;
        this.call('item_uoms',{item_code:code},data=>{
            if(loadEpoch!==this.epoch||epoch!==row.epoch||code!==row.itemField.get_value())return;
            row.options=data;this.set_units(row,data,row.target.link&&row.target.link.sale_uom);this.update_save();
        });
    }
    set_units(row,data,preferred) {
        row.uomField.df.options=[''].concat(data.uoms.map(u=>u.uom)).join('\n');row.uomField.refresh();
        this.ready=false;row.uomField.set_value(data.uoms.some(u=>u.uom===preferred)?preferred:data.default_uom||'');this.ready=true;
    }
    valid(row) {
        return !this.bulk&&row.selected&&row.dirty&&row.target.linkable&&!(row.target.link&&row.target.link.enabled)&&row.options&&row.options.item_code===row.itemField.get_value()&&row.options.uoms.some(u=>u.uom===row.uomField.get_value());
    }
    update_save() {
        if(!this.page.btn_primary)return;
        const ready=this.bulk?this.reviewed&&this.rows.some(r=>r.selected&&r.statusText==='Ready'):this.rows.some(r=>this.valid(r));
        this.page.btn_primary.text(this.bulk?'Create Reviewed Links':'Save Links').prop('disabled',!!(this.busy||this.loading||!ready));
        [this.findButton,this.scanButton,this.moreButton,this.nextBatchButton,this.savePreviewButton,this.resumeButton].forEach(button=>{if(button)button.prop('disabled',!!(this.busy||this.loading));});
        if(this.nextBatchButton)this.nextBatchButton.toggle(!!(this.bulk&&this.reviewed&&(!this.catalogDone||(this.pendingRows||[]).length)));
        if(this.savePreviewButton)this.savePreviewButton.toggle(!!(this.bulk&&this.reviewed&&this.rows.length));
        if(this.resumeButton)this.resumeButton.toggle(!!this.bulk);
        this.rows.forEach(row=>{if(row.selector)row.selector.prop('checked',!!row.selected).prop('disabled',!!(this.busy||this.loading||(this.bulk?row.statusText!=='Ready':row.target.link&&row.target.link.enabled)));});
        if(this.skuField){this.skuField.df.read_only=!!(this.busy||this.loading);this.skuField.refresh();}
        this.rows.forEach(row=>{if(row.itemField){row.itemField.df.read_only=!!(this.busy||this.loading||row.target.link);row.itemField.refresh();row.uomField.df.read_only=!!(this.busy||this.loading||row.target.link&&row.target.link.enabled);row.uomField.refresh();}});
    }
    scan(continuing=false) {
        if(this.busy||this.loading)return;
        if(continuing&&this.rows.some(r=>r.selected&&r.statusText==='Ready')){
            frappe.confirm('Leave the selected unsaved rows and load the next batch?',()=>{this.rows.forEach(r=>r.selected=false);this.scan(true);});return;
        }
        if(!continuing){this.cursor={page:1,variation_page:1};this.pendingRows=[];this.catalogDone=false;}
        this.rows=[];this.filter='Ready';this.reviewed=false;this.stopRequested=false;this.loading=true;
        this.stopButton.show().prop('disabled',false);this.update_save();const epoch=++this.epoch;let chunks=0;
        const consume=()=>{
            while(this.rows.length<25&&this.pendingRows.length){
                const r=this.pendingRows.shift();this.rows.push(Object.assign({},r,{target:r,statusText:r.status,selected:false}));
            }
        };
        const next=()=>{
            consume();this.render();
            if(this.rows.length>=25||this.catalogDone||this.stopRequested||chunks>=10){this.finish_scan(!this.catalogDone||this.pendingRows.length>0);return;}
            let completed=false;chunks++;
            this.call('preview',this.cursor,data=>{
                if(epoch!==this.epoch)return;
                completed=true;this.sourceHost=data.source_host||this.sourceHost;
                this.pendingRows.push(...data.rows);this.cursor={page:data.page,variation_page:data.variation_page};this.catalogDone=!!data.done;
                this.status.text('Checking this batch...');next();
            },()=>{if(epoch===this.epoch&&!completed){this.finish_scan(true);this.status.text('Preview interrupted. Save this preview or use Next Batch to retry from this position.');}},'bulk_linking');
        };next();
    }
    preview_key() {
        return 'ws-woo-preview-v1:'+window.location.host+':'+frappe.session.user;
    }
    save_preview() {
        if(!this.bulk||this.loading||this.busy||!this.reviewed)return;
        const rows=this.rows.map(r=>({target:r.target,statusText:r.statusText,reason:r.reason,item_code:r.item_code,
            sale_uom:r.sale_uom,modified:r.modified,sku:r.sku,product_id:r.product_id,variation_id:r.variation_id,selected:!!r.selected}));
        try{
            window.localStorage.setItem(this.preview_key(),JSON.stringify({version:1,saved:Date.now(),rows,cursor:this.cursor,
                pendingRows:this.pendingRows,catalogDone:this.catalogDone,sourceHost:this.sourceHost}));
            this.status.text('Preview saved in this browser for 24 hours. Resume Saved Preview restores it; every link is checked again when saved.');
        }catch(e){this.status.text('This browser could not save the preview. Keep this page open while reviewing.');}
    }
    restore_preview() {
        if(!this.bulk||this.loading||this.busy)return;
        try{
            const raw=window.localStorage.getItem(this.preview_key());
            if(!raw||raw.length>262144)throw new Error('missing');
            const saved=JSON.parse(raw);
            if(saved.version!==1||!saved.saved||Date.now()-saved.saved>86400000||!Array.isArray(saved.rows)||saved.rows.length>25||!Array.isArray(saved.pendingRows)||saved.pendingRows.length>25||!saved.cursor)throw new Error('expired');
            ++this.epoch;this.rows=saved.rows;this.cursor=saved.cursor;this.pendingRows=saved.pendingRows;
            this.catalogDone=!!saved.catalogDone;this.sourceHost=saved.sourceHost;this.filter='Ready';this.reviewed=true;
            this.render();this.finish_scan(!this.catalogDone||this.pendingRows.length>0);
        }catch(e){this.status.text('No usable saved preview for this user and site. Start a new preview.');}
    }
    finish_scan(partial) {
        this.loading=false;this.reviewed=true;this.stopButton.hide();const count=status=>this.rows.filter(r=>r.statusText===status).length;
        this.status.text((partial?'Batch paused. ':'Preview complete. ')+count('Ready')+' ready / '+count('Review')+' need review / '+count('Skipped')+' skipped. Select reviewed rows to create links; confirm the website unit for each.');this.update_save();
    }
    save() {
        if(this.busy||this.loading)return;
        if(this.bulk){const rows=this.rows.filter(r=>r.selected&&r.statusText==='Ready');if(!this.reviewed||!rows.length)return;
            frappe.confirm('Create '+rows.length+' reviewed stock-only links? If Automatic Sync is enabled, stock can publish after these links are saved.',()=>this.apply_bulk(rows));return;}
        const rows=this.rows.filter(r=>this.valid(r));if(!rows.length)return;this.busy=true;this.update_save();const epoch=this.epoch;
        const next=index=>{
            if(epoch!==this.epoch)return;
            if(index===rows.length){this.busy=false;this.update_save();this.status.text('Save finished. Check each row for its result. New manual links are inactive.');return;}
            const row=rows[index],t=row.target,o=row.options;let saved=false;
            this.call('save_link',{item_code:o.item_code,sale_uom:row.uomField.get_value(),source_host:this.sourceHost,product_id:t.product_id,variation_id:t.variation_id,expected_sku:t.sku,expected_modified:o.modified},data=>{
                saved=true;t.link=data;row.dirty=false;row.selected=false;const previous=o.modified;o.modified=data.modified;
                this.rows.forEach(other=>{if(other!==row&&other.options&&other.options.item_code===o.item_code&&other.options.modified===previous)other.options.modified=data.modified;});
                this.row_status(row,data.enabled?'Active link':'Saved inactive','Review and enable in the ERPNext Item when ready.');
            },()=>{if(!saved)this.row_status(row,'Not saved','Review the error, then retry this row.');next(index+1);});
        };next(0);
    }
    apply_bulk(rows) {
        if(this.busy||this.loading)return;this.busy=true;this.update_save();const epoch=this.epoch;
        const next=index=>{
            if(epoch!==this.epoch)return;
            if(index>=rows.length){this.busy=false;this.filter='All';this.render();this.status.text('Linking finished. Linked rows are active for stock; prices remain off. Preview again to retry failures.');this.update_save();return;}
            const batch=rows.slice(index,index+10);let received=false;
            this.call('apply',{rows:JSON.stringify(batch.map(r=>({product_id:r.product_id,variation_id:r.variation_id,sku:r.sku,item_code:r.item_code,sale_uom:r.sale_uom,modified:r.modified,source_host:this.sourceHost})))},data=>{
                received=true;data.rows.forEach((result,i)=>{batch[i].statusText=result.status;batch[i].reason=result.reason;if(result.status==='Linked'||result.status==='Skipped')batch[i].selected=false;});this.render();
            },()=>{if(!received){this.busy=false;this.reviewed=false;this.status.text('Apply interrupted. Restart the preview before retrying; existing links are preserved.');this.update_save();return;}next(index+10);},'bulk_linking');
        };next(0);
    }
};
frappe.pages['ws-woocommerce-link'].on_page_load=function(wrapper){wrapper.woo_link_form=new frappe.WSWooLinkForm(wrapper);};
frappe.pages['ws-woocommerce-link'].on_page_show=function(wrapper){wrapper.woo_link_form.show_route();};
