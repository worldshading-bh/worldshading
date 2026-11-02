const fs=require('fs'),vm=require('vm'),assert=require('assert');
let refresh,role=true,dirty=false;
const buttons={},calls=[],messages=[],routes=[];
const frappe={ui:{form:{on(dt,handlers){refresh=handlers.refresh;}}},user:{has_role(){return role;}},
 utils:{escape_html:String},call(args){calls.push(args);},msgprint(text){messages.push(text);},
 set_route(...route){routes.push(route);}};
vm.runInNewContext(fs.readFileSync('worldshading/public/js/woocommerce_item.js','utf8'),{frappe});
const frm={fields_dict:{ws_woocommerce_links:{}},doc:{name:'ITEM / 1',item_code:'SKU/1',stock_uom:'Each',uoms:[]},
 set_df_property(){},set_query(){},is_new(){return false;},is_dirty(){return dirty;},
 add_custom_button(label,fn){buttons[label]=fn;}};
refresh(frm);assert.ok(buttons['Link WooCommerce']);
dirty=true;buttons['Link WooCommerce']();assert.strictEqual(routes.length,0);assert.ok(messages.length);
dirty=false;buttons['Link WooCommerce']();
assert.strictEqual(routes[0][0],'ws-woocommerce-link');
assert.strictEqual(frappe.route_options.ws_woo_link_seed.item_code,'ITEM / 1');
assert.strictEqual(frappe.route_options.ws_woo_link_seed.sku,'SKU/1');
assert.strictEqual(calls.filter(c=>c.method.includes('save_link')).length,0);
delete buttons['Link WooCommerce'];role=false;refresh(frm);assert.strictEqual(buttons['Link WooCommerce'],undefined);
console.log('PASS: Item action permissions, dirty guard, exact route seed and no automatic save');
