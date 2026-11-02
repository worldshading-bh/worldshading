const fs=require('fs'),vm=require('vm'),assert=require('assert');
let refresh,dirty=false;const buttons={},routes=[],messages=[],groups=[];
const frappe={ui:{form:{on(dt,h){refresh=h.refresh;}}},sys_defaults:{time_zone:'Asia/Bahrain'},utils:{escape_html:String},
 call(){},set_route(...r){routes.push(r);},msgprint(m){messages.push(m);}};
vm.runInNewContext(fs.readFileSync('worldshading/worldshading/doctype/ws_woocommerce_settings/ws_woocommerce_settings.js','utf8'),{frappe});
refresh({doc:{company:'WS'},is_dirty:()=>dirty,set_query(){},set_df_property(){},add_custom_button(label,fn,group){buttons[label]=fn;groups.push(group);}});
assert.ok(groups.length>=8);assert.ok(groups.every(g=>g==='WooCommerce'),'ungrouped connector action');
dirty=true;buttons['Link Matching Items']();assert.strictEqual(routes.length,0);assert.strictEqual(messages.length,1);
dirty=false;buttons['Link Matching Items']();assert.strictEqual(routes[0].join('/'),'ws-woocommerce-link/bulk');
console.log('PASS: all Settings actions use WooCommerce group; bulk action guards unsaved settings and opens preview only');
