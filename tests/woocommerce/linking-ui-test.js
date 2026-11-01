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
