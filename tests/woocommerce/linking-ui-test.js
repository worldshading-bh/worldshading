const fs=require('fs'),vm=require('vm'),assert=require('assert');
const frappe={pages:{'ws-woocommerce-link':{}},utils:{escape_html:String},confirm(message,yes){this.confirmation={message,yes};}};
vm.runInNewContext(fs.readFileSync('worldshading/worldshading/page/ws_woocommerce_link/ws_woocommerce_link.js','utf8'),{frappe});
function element(){const props={};return {value:'',text(v){if(arguments.length){this.value=v;return this;}return this.value;},html(){return this;},empty(){return this;},show(){return this;},hide(){return this;},toggle(){return this;},prop(k,v){if(arguments.length===1)return props[k];props[k]=v;return this;}};}
function field(value=''){return {value,df:{},get_value(){return this.value;},set_value(v){this.value=v;},refresh(){},$wrapper:element()};}
function row(code='A'){return {epoch:0,dirty:true,target:{product_id:1,variation_id:2,sku:'SKU',linkable:true},
 itemField:field(code),uomField:field('Each'),options:{item_code:code,modified:'old',default_uom:'Each',uoms:[{uom:'Each'}]},status:element()};}
function fixture(){const f=Object.create(frappe.WSWooLinkForm.prototype);Object.assign(f,{epoch:1,rows:[],ready:true,bulk:false,requests:[],
 page:{btn_primary:element()},status:element(),heading:element(),table:element(),moreButton:element(),stopButton:element(),findButton:element(),scanButton:element(),skuField:field('SKU')});
 f.call=(method,args,done,always,module)=>f.requests.push({method,args,done,always,module});f.render=()=>{};return f;}
{
 const f=fixture(),r=row();f.rows=[r];f.choose_item(r);const first=f.requests[0];
 r.itemField.value='B';f.choose_item(r);first.done({item_code:'A',modified:'wrong',uoms:[{uom:'Each'}]});assert.strictEqual(r.options,null);
 f.requests[1].done({item_code:'B',modified:'new',uoms:[{uom:'Box'},{uom:'Each'}],default_uom:'Box'});assert.strictEqual(r.uomField.value,'Box');
 f.epoch++;r.options=null;f.requests[1].done({item_code:'B',uoms:[{uom:'Each'}]});assert.strictEqual(r.options,null,'old route callback accepted');
}
{
 const f=fixture(),r=row();f.rows=[r];r.target.link={enabled:true};f.save();assert.strictEqual(f.requests.length,0,'active mapping edited');
 r.target.link=null;r.options.item_code='OTHER';f.save();assert.strictEqual(f.requests.length,0,'stale Item options saved');
}
{
 const f=fixture(),a=row(),b=row('B');b.target.variation_id=3;f.rows=[a,b];f.sourceHost='shop.example.com';f.save();
 assert.strictEqual(f.requests.length,1);assert.strictEqual(a.itemField.df.read_only,true);assert.strictEqual(b.uomField.df.read_only,true);
 f.requests[0].done({item_code:'A',enabled:false,modified:'saved'});f.requests[0].always();
 assert.strictEqual(f.requests[1].args.variation_id,3,'second variation not saved');
 f.requests[1].always();assert.strictEqual(f.busy,false);assert.strictEqual(a.dirty,false);assert.strictEqual(b.dirty,true,'failed row cannot retry');
}
{
 const f=fixture();f.productId=123;f.sourceHost='shop.example.com';f.focusVariation=222;f.load(1);
 assert.strictEqual(f.requests[0].method,'product_sheet');assert.strictEqual(f.requests[0].args.variation_id,undefined,'launching variation filters sheet');
 f.requests[0].done({product_name:'Product',store_url:'shop',targets:[{variation_id:1},{variation_id:2}],page:1,has_more:true});
 assert.strictEqual(f.rows.length,2);assert.strictEqual(f.requests[1].args.page,2);
 f.requests[1].done({product_name:'Product',targets:[{variation_id:3}],page:2,has_more:false});
 assert.strictEqual(f.rows.length,3,'page replaces earlier variations');
}
{
 const f=fixture();f.bulk=true;f.scan();assert.strictEqual(f.requests[0].method,'preview');
 f.requests[0].done({rows:[{status:'Ready',product_id:1,variation_id:0,item_code:'A',sale_uom:'Each',sku:'A',modified:'old'}],page:2,variation_page:1,done:false});
 assert.strictEqual(f.requests.filter(r=>r.method==='apply').length,0,'preview writes');
 f.stopRequested=true;f.requests[1].done({rows:[],done:false,page:3,variation_page:1});assert.strictEqual(f.reviewed,true);
 f.save();assert.strictEqual(f.requests.filter(r=>r.method==='apply').length,0,'confirmation bypassed');
 frappe.confirmation.yes();assert.strictEqual(f.requests[2].method,'apply');assert.strictEqual(f.requests[2].module,'bulk_linking');
 f.requests[2].done({rows:[{status:'Linked'}]});f.requests[2].always();assert.strictEqual(f.rows[0].statusText,'Linked');assert.strictEqual(f.busy,false);
}
{
 const f=fixture();f.bulk=true;f.reviewed=false;f.rows=[{statusText:'Ready'}];f.save();assert.strictEqual(f.requests.length,0,'unreviewed preview applied');
}
console.log('PASS: row isolation, stale response guards, active protection, save-all, parent variation pagination, read-only bulk preview and explicit reviewed application');
