<?php
// Standalone fixture: never loads WordPress or a store database.
define('ABSPATH', __DIR__);
if (($argv[1]??'')==='bad-origin') define('WSC_ERP_MAPPING_ORIGIN','https://user@erp.example.com');
$allowed=true; $admin=false; $page_product=33166; $child_reads=0; $product_reads=0; $nodes=[]; $hooks=[];
function add_action($name, $callback, ...$args){global $hooks; $hooks[$name]=$callback;}
function current_user_can($cap,...$args){global $allowed; return $allowed;}
function is_admin(){global $admin; return $admin;}
function is_product(){return true;}
function is_admin_bar_showing(){return true;}
function get_queried_object_id(){global $page_product; return $page_product;}
function get_post_type($id){return 'product';}
function get_current_screen(){return (object)['base'=>'post','post_type'=>'product'];}
function get_the_ID(){global $page_product; return $page_product;}
function home_url($path=''){return 'https://shop.example.com'.$path;}
function wp_parse_url($url,$component=-1){return parse_url($url,$component);}
function admin_url($path){return 'https://shop.example/wp-admin/'.$path;}
function add_query_arg($args,$url){return $url.'?'.http_build_query($args);}
function esc_url($v){return htmlspecialchars($v,ENT_QUOTES);}
function esc_html($v){return htmlspecialchars((string)$v,ENT_QUOTES);}
function esc_attr($v){return esc_html($v);}
function wp_strip_all_tags($v){return strip_tags($v);}
function absint($v){return abs((int)$v);}
function wp_unslash($v){return $v;}
function wp_die($message,...$args){throw new RuntimeException($message);}
function add_submenu_page(...$args){} function add_meta_box(...$args){}
class FakeProduct {
 private $id; function __construct($id){$this->id=$id;}
 function get_id(){return $this->id;}
 function get_parent_id(){return 33166;}
 function is_type($type){return in_array($this->id===33166?'variable':'simple',(array)$type,true);}
 function get_name($context='view'){ $names=[33166=>'Pagoda Tent',33168=>'Pagoda Tent<span> - </span>3m × 3m',33169=>'5m × 5m',44=>'Simple & Tent']; return $names[$this->id];}
 function get_sku(){return [33166=>'',33168=>'DCPT0003',33169=>'DCPT0005',44=>'SKU"<unsafe>'][$this->id];}
 function get_children(){global $child_reads; $child_reads++; return [33168,33169];}
}
function wc_get_product($id){global $product_reads; $product_reads++; return in_array($id,[33166,33168,33169,44],true)?new FakeProduct($id):false;}
require dirname(__DIR__,2).'/deploy/woocommerce/wordpress/mapping-helper.php';
function check($condition,$message){if(!$condition)throw new Exception($message);}
$bar=new class { public $nodes=[]; function add_node($node){$this->nodes[]=$node;} };
$allowed=false; WSC_ERP_Product_Mapping::toolbar($bar);check(!$bar->nodes,'guest toolbar leak');
$_GET=['product_id'=>'33166'];try{WSC_ERP_Product_Mapping::page();throw new Exception('unauthorized mapping rendered');}catch(RuntimeException $e){}
check($product_reads===0,'unauthorized product lookup');
$allowed=true; WSC_ERP_Product_Mapping::toolbar($bar);check(count($bar->nodes)===1,'manager mapping button missing');
if (($argv[1]??'')==='bad-origin') {check(strpos($bar->nodes[0]['href'],'@')===false,'credential origin accepted');echo "PASS: invalid ERP origin falls back to ID viewer\n";exit;}
check(strpos($bar->nodes[0]['href'],'/desk#ws-woocommerce-link/33166')!==false,'wrong toolbar product');
check(strpos($bar->nodes[0]['href'],'/33166/all/shop.example.com')!==false,'source store missing from popup');
check($child_reads===0,'storefront traversed variations');
ob_start(); WSC_ERP_Product_Mapping::page(); $html=ob_get_clean();
foreach(['33166','33168','33169','DCPT0003','DCPT0005','3m','5m'] as $value)check(strpos($html,$value)!==false,'missing mapping '.$value);
check($child_reads===1,'mapping page traversed children repeatedly');
check(strpos($html,'/desk#ws-woocommerce-link/33166/33168')!==false,'direct variation popup link missing');
check(strpos($html,'&lt;span&gt;')===false,'theme HTML leaked into variation label');
$_GET=['product_id'=>'44'];ob_start();WSC_ERP_Product_Mapping::page();$html=ob_get_clean();
check(strpos($html,'SKU&quot;&lt;unsafe&gt;')!==false,'SKU not escaped');
check(strpos($html,'Simple &amp; Tent')!==false,'product name not escaped');
check(strpos($html,'value="0"')!==false,'simple product variation must be zero');
$_GET=['product_id'=>'999'];try{WSC_ERP_Product_Mapping::page();throw new Exception('invalid product accepted');}catch(RuntimeException $e){}
check(!isset($hooks['wp_ajax_nopriv_wsc_erp_mapping']),'public mapping endpoint');
echo "PASS: access control, lazy storefront, exact variations, simple mapping, escaping, invalid product and no public endpoint\n";
