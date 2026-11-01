"""One grouped ERP read per data type for enabled linked Items only."""
from collections import defaultdict
import frappe
from .inventory import stock_warehouses


class Snapshot:
    def __init__(self,mappings,config):
        self._items={};self._bins=defaultdict(list);self._prices=defaultdict(list);self._drafts={}
        codes=sorted(set(row['item_code'] for row in mappings))
        if not codes:return
        fields=['name','stock_uom','is_stock_item','is_sales_item','disabled','has_variants']
        for row in frappe.get_all('Item',filters={'name':['in',codes]},fields=fields):
            row.uoms=[];self._items[row.name]=row
        for row in frappe.get_all('UOM Conversion Detail',filters={'parent':['in',codes],'parenttype':'Item'},fields=['parent','uom','conversion_factor']):
            if row.parent in self._items:self._items[row.parent].uoms.append(row)
        warehouses=stock_warehouses(config);self.warehouses=warehouses
        for row in frappe.get_all('Bin',filters={'item_code':['in',codes],'warehouse':['in',warehouses]},
                fields=['item_code','actual_qty','reserved_qty','reserved_qty_for_production','reserved_qty_for_sub_contract']):
            self._bins[row.item_code].append(row)
        placeholders=','.join(['%s']*len(codes));warehouses_sql=','.join(['%s']*len(warehouses))
        rows=frappe.db.sql('''SELECT i.item_code,SUM(i.stock_qty) AS qty FROM `tabSales Order Item` i
            JOIN `tabSales Order` s ON s.name=i.parent
            WHERE s.docstatus=0 AND COALESCE(s.ws_woo_order_id,'')<>''
            AND i.item_code IN ('''+placeholders+') AND i.warehouse IN ('+warehouses_sql+') GROUP BY i.item_code',
            codes+warehouses,as_dict=True)
        self._drafts={row.item_code:row.qty for row in rows}
        priced=sorted(set(row['item_code'] for row in mappings if row.get('sync_price')))
        if priced:
            for row in frappe.get_all('Item Price',filters={'item_code':['in',priced],'price_list':config.price_list},fields=['*']):
                self._prices[row.item_code].append(row)

    def item(self,code):
        if code not in self._items:raise ValueError('Mapped ERP Item no longer exists: '+str(code))
        return self._items[code]

    def bins(self,code):return self._bins[code]
    def prices(self,code):return self._prices[code]
    def drafts(self,code):return self._drafts.get(code,0)
