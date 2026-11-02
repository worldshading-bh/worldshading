const fs = require('fs');
const vm = require('vm');
const assert = require('assert');
const context = {frappe:{pages:{'ws-woocommerce-link':{}},utils:{escape_html:String}}, console};
vm.createContext(context);
vm.runInContext(fs.readFileSync('worldshading/worldshading/page/ws_woocommerce_link/ws_woocommerce_link.js','utf8'),context);
function field(value='') {return {value,df:{},get_value(){return this.value;},set_value(v){this.value=v;},refresh(){}};}
function fixture() {
 const f=Object.create(context.frappe.WSWooLinkForm.prototype);
 f.itemEpoch=0;f.loadEpoch=0;f.itemField=field('A');f.uomField=field('Nos');f.targetField=field('first');
 f.skuField=field('SKU');
 f.target={product_id:1,variation_id:2,sku:'SKU',linkable:true};
 f.itemOptions={item_code:'A',modified:'timestamp',uoms:[{uom:'Nos'}]};
 f.status={value:'',text(v){this.value=v;}};
 f.heading={text(){}};f.identity={empty(){}};f.pager={empty(){}};
 const props={};f.page={btn_primary:{prop(k,v){if(arguments.length===1)return props[k];props[k]=v;}}};
 f.requests=[];f.call=(method,args,done,always)=>f.requests.push({method,args,done,always});return f;
}
{
 const f=fixture();f.choose_item();const first=f.requests[0];
 f.itemField.value='B';f.choose_item();const second=f.requests[1];
 first.done({item_code:'A',modified:'old',uoms:[{uom:'Nos'}]});assert.strictEqual(f.itemOptions,null,'stale Item response accepted');
 second.done({item_code:'B',modified:'new',uoms:[{uom:'Set'}]});assert.strictEqual(f.itemOptions.item_code,'B');assert.strictEqual(f.uomField.value,'Set');
}
{
 const f=fixture();f.target.link={enabled:true};f.save();assert.strictEqual(f.requests.length,0,'active link edited');
}
{
 const f=fixture();f.itemOptions.item_code='OTHER';f.save();assert.strictEqual(f.requests.length,0,'stale Item options saved');
}
{
 const f=fixture();f.save();assert.strictEqual(f.requests[0].method,'save_link');
 assert.strictEqual(f.itemField.df.read_only,true,'Item remains editable during save');
 assert.strictEqual(f.uomField.df.read_only,true,'UOM remains editable during save');
 assert.strictEqual(f.targetField.df.read_only,true,'variation remains editable during save');
 f.requests[0].done({item_code:'A',sale_uom:'Nos',enabled:false,modified:'saved timestamp'});f.requests[0].always();
 assert.strictEqual(f.itemOptions.modified,'saved timestamp','saved timestamp must refresh');
 assert.strictEqual(f.busy,false);assert.strictEqual(f.target.link.item_code,'A');
 assert.strictEqual(f.itemField.df.read_only,true,'existing target must remain pinned to its Item');
 assert.strictEqual(f.uomField.df.read_only,false,'inactive link UOM should remain editable');
 assert.strictEqual(f.targetField.df.read_only,false);
}
{
 const f=fixture();f.targets=[f.target];f.targetField.df.options='first';
 f.load(2);assert.strictEqual(f.targets.length,0,'old targets retained while loading');
 assert.strictEqual(f.targetField.value,'');assert.strictEqual(f.itemField.value,'');
 f.choose_target();f.save();assert.strictEqual(f.requests.length,1,'old target saved during load');
 f.requests[0].always();assert.strictEqual(f.loading,false);
 f.choose_target();f.save();assert.strictEqual(f.requests.length,1,'old target restored after failed load');
 assert.ok(f.status.value.includes('Reload'),'failed load lacks retry guidance');
}
console.log('PASS: stale Item callbacks, active-link protection, stale selection and save locking');
{
 const f=fixture();f.itemField.value='';f.suggest_item();
 assert.strictEqual(f.requests[0].method,'match_item');
 f.itemField.value='MANUAL';f.requests[0].done({item_code:'AUTO',reason:'matched'});
 assert.strictEqual(f.itemField.value,'MANUAL','late suggestion replaced manual Item choice');
}
{
 const f=fixture();f.itemField.value='';f.suggest_item();
 f.requests[0].done({item_code:'AUTO',reason:'matched'});
 assert.strictEqual(f.itemField.value,'AUTO');
 assert.strictEqual(f.requests[1].method,'item_uoms');
 assert.strictEqual(f.requests.filter(r=>r.method==='save_link').length,0,'suggestion saved automatically');
}
{
 const f=fixture();f.render_targets=data=>{f.rendered=data;};f.find_sku();
 assert.strictEqual(f.requests[0].method,'find_by_sku');
 assert.strictEqual(f.skuField.df.read_only,true,'SKU editable during lookup');
 ++f.loadEpoch;f.requests[0].done({source_host:'wrong',targets:[{product_id:9}]});f.requests[0].always();
 assert.strictEqual(f.rendered,undefined,'stale SKU response accepted');
}
console.log('PASS: SKU lookup locking, stale suggestions and read-only automatic matching');
{
 const f=fixture();f.itemField.value='';f.suggest_item();
 f.target={product_id:1,variation_id:3};f.requests[0].done({item_code:'OLD',reason:'old target'});
 assert.strictEqual(f.itemField.value,'','old variation suggestion accepted');
}
{
 const f=fixture();f.choose_item();
 f.requests[0].done({item_code:'A',modified:'new',uoms:[{uom:'Nos'},{uom:'Box'}]});
 assert.strictEqual(f.uomField.value,'','ambiguous selling UOM was guessed');
 assert.strictEqual(f.page.btn_primary.prop('disabled'),true);
}
{
 const f=fixture();f.render_targets=data=>{f.rendered=data;};f.find_sku();
 f.requests[0].done({source_host:'shop.example.com',targets:[{product_id:1}]});f.requests[0].always();
 assert.strictEqual(f.sourceHost,'shop.example.com');assert.strictEqual(f.productId,1);
 assert.ok(f.rendered);assert.strictEqual(f.skuField.df.read_only,false);
 assert.strictEqual(f.requests.filter(r=>r.method==='save_link').length,0);
}
