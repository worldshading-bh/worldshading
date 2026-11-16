/* Cashflow Forecast — temporary scenarios; no accounting transactions are created. */
(function () {
    'use strict';
    var method = 'worldshading.worldshading.report.cashflow_forecast.cashflow_forecast.';
    var esc = function (value) { return frappe.utils.escape_html(String(value === undefined || value === null ? '' : value)); };

    // Defaults only: intersect with the permitted company account list at load time.
    var default_excluded_accounts = [
        "Cashier Cash Change - WS",
        "BDB BANK SECURITY DEPOSIT - WS",
        "Cheque Sales - WS",
        "Online payment - WS",
        "Petty Cash - WS",
        "Cheque Return - WS",
        "TEMP Adjustment A/C - WS",
        "WS Payments - WS",
        "4001 - AUB HAMD TOWN - WS",
        "***00131 - KFH Bank - Debit Card - WS",
        "***03431 - BDB Bank - WS",
        "***18395 - KFH BANK CURRENT ACCOUNT - WS",
        "BANK TIME DEPOSIT - WS",
        "***52546 - Al Salam Bank - Savings Account - WS",
        "***63001 - KFH Benefit pay - WS",
        "***96002 - AUB RESERVE ACCOUNT BANK - WS",
        "***96060 - AHLI UNITED BANK - WS"
];

    var detail_fields = [['opening_cash','Opening Cash'],['expected_receipts','Expected Sales Receipts'],
        ['other_receipts','Other Incoming'],['fixed_expenses','Fixed Expenses'],['payroll','Payroll'],
        ['supplier_payments','Supplier Payments'],['customs','Customs'],['import_vat','Import VAT'],
        ['quarterly_vat','Quarterly VAT Settlement'],['extra_expenses','Extra Expenses'],
        ['budget_expenses','Budget Expenses'],
        ['baseline_closing_cash','Closing Without Purchase'],
        ['other_payments','Other Scheduled Payments'],['total_payments','Total Payments'],
        ['closing_cash','Closing Cash'],['available_above_reserve','Cash Above Minimum Reserve']];
    var payment_fields = ['fixed_expenses','payroll','supplier_payments','customs','import_vat',
        'quarterly_vat','extra_expenses','budget_expenses','proposed_purchase','other_payments'];

    function context_for(report) {
        var raw = report && report.raw_data;
        return raw && raw.result && raw.result[0] && raw.result[0]._cashflow_context || {};
    }

    function reserve_for(report) {
        var snapshot = context_for(report);
        if (snapshot.minimum_reserve !== undefined) return Number(snapshot.minimum_reserve);
        var row = report && report.raw_data && report.raw_data.result && report.raw_data.result[0];
        return row && row.available_above_reserve !== undefined ? Number(row.closing_cash)-Number(row.available_above_reserve) : 0;
    }

    function apply_column_view(report) {
        if (!report.prepare_columns || !report.raw_data || !report.raw_data.result) return;
        var rows = report.raw_data.result;
        // Keep saved and quick-preview results compatible; never add a proposal twice.
        rows.forEach(function(row) {
            if (row.supplier_payments_without_purchase === undefined)
                row.supplier_payments_without_purchase = Number(row.supplier_payments || 0);
            row.supplier_payments = Number(row.supplier_payments_without_purchase) + Number(row.proposed_purchase || 0);
        });
        if (!rows.length) return;
        var saved = report.raw_data.columns || [];
        var has_purchase = rows.some(function(row) {
            return Number(row.proposed_purchase || 0) !== 0 || (row.sources || []).some(function(event) {return !!event.scenario;});
        });
        var date_field = Object.prototype.hasOwnProperty.call(rows[0],'month') ? 'month' : 'date';
        var columns = [{fieldname:date_field,label:__(date_field === 'month' ? 'Month' : 'Date'),
            fieldtype:date_field === 'month' ? 'Data' : 'Date',width:date_field === 'month' ? 110 : 145}];
        detail_fields.forEach(function(definition) {
            var name = definition[0];
            if (!Object.prototype.hasOwnProperty.call(rows[0],name)) return;
            var original = saved.find(function(col){return col.fieldname === name;}) || {};
            columns.push(Object.assign({},original,{fieldname:name,label:__(definition[1]),fieldtype:'Currency',
                options:'currency',precision:3,width:name === 'expected_receipts' ? 180 : (original.width || 145),
                hidden:(!has_purchase && name === 'baseline_closing_cash') ||
                    (name === 'available_above_reserve' && !reserve_for(report))}));
        });
        columns.push({fieldname:'source_details',label:__('Source Details'),fieldtype:'Data',width:150});
        columns.push({fieldname:'currency',label:__('Currency'),fieldtype:'Link',options:'Currency',hidden:1});
        columns=arranged_columns(columns,report);
        report.columns = report.prepare_columns(columns);
        report.raw_data.columns = columns;
    }

    function set_excluded_values(field, values) {
        if (!field) return;
        if (typeof values === 'string') {
            try {values=JSON.parse(values);} catch(error) {values=[values];}
        }
        values=Array.isArray(values)?values.slice():[];
        // Native v12 MultiSelectList.set_input does not restore its values array.
        // Use its setter with change handling suppressed, so loading a snapshot
        // cannot refresh or queue another report. Seed escaped selected labels.
        field._options=values.map(function(name){return {value:name,label:esc(name),description:''};}).concat(
            (field._options || []).filter(function(option){return values.indexOf(option.value)<0;}));
        field._selected_values=[];
        var changing=field.inside_change_event;
        field.inside_change_event=true;
        try {
            if(field.set_value)field.set_value(values);
            else if(field.set_input)field.set_input(values);
        } finally {field.inside_change_event=changing;}
    }

    function exclusion_options(report, text) {
        if(!report || report.report_name!=='Cashflow Forecast')return Promise.resolve([]);
        var company=report.get_filter_value('company');
        if(!company)return Promise.resolve([]);
        var cache=report._cashflow_account_options;
        if(!cache || cache.company!==company) {
            cache={company:company};report._cashflow_account_options=cache;
            cache.promise=frappe.call({method:method+'get_accounts',args:{company:company,names_only:1}}).then(function(response) {
                if(report.get_filter_value('company')!==company)return [];
                return (response.message || []).map(function(item){return {value:item.value,label:esc(item.label || item.value),description:esc(item.description || '')};});
            },function(error){if(report._cashflow_account_options===cache)report._cashflow_account_options=null;throw error;});
        }
        return cache.promise.then(function(options) {
            var search=String(text || '').toLowerCase();
            var selected=report.get_filter_value('excluded_accounts') || [];
            if(!Array.isArray(selected))selected=[selected];
            var chosen=selected.map(function(value){return options.find(function(option){return option.value===value;});}).filter(Boolean);
            var remaining=options.filter(function(option){return selected.indexOf(option.value)<0 && String(option.value).toLowerCase().indexOf(search)>=0;});
            return chosen.concat(remaining);
        });
    }

    function apply_default_exclusions(report) {
        var field=report.get_filter && report.get_filter('excluded_accounts');
        if(!field || !field.get_value || report._cashflow_default_company===report.get_filter_value('company'))return Promise.resolve();
        var company=report.get_filter_value('company'),revision=report._cashflow_defaults_revision || 0;
        report._cashflow_default_company=company;
        if((field.get_value() || []).length)return Promise.resolve();
        return exclusion_options(report,'').then(function(options){
            if(report.get_filter_value('company')!==company || (report._cashflow_defaults_revision || 0)!==revision)return;
            set_excluded_values(field,options.filter(function(option){return default_excluded_accounts.indexOf(option.value)>=0;}).map(function(option){return option.value;}));
        });
    }

    function company_changed(report) {
        if(report._cashflow_restoring)return Promise.resolve();
        report._cashflow_defaults_revision=(report._cashflow_defaults_revision || 0)+1;
        report._cashflow_account_options=null;
        var field=report.get_filter && report.get_filter('excluded_accounts');
        if(field)field._options=[];
        set_excluded_values(field,[]);
        return apply_default_exclusions(report).then(function(){account_scope_changed(report);});
    }

    function account_scope_changed(report) {
        report._cashflow_defaults_revision=(report._cashflow_defaults_revision || 0)+1;
        if(report.page && report.page.main && report.page.main.find) {
            var box=report.page.main.find('.cashflow-context');
            if(box.html)box.html('');
        }
        if(report.prepared_report && report.reset_report_view)report.reset_report_view();
        else if(!report._no_refresh && report.refresh)report.refresh();
    }

    function sales_tooltip(report, row) {
        var snapshot = context_for(report);
        var adjustment = snapshot.sales_adjustment;
        if (adjustment === undefined && Number(row.previous_year_sales) && row.adjusted_sales !== undefined) {
            adjustment = ((Number(row.adjusted_sales)/Number(row.previous_year_sales)-1)*100).toFixed(2);
        }
        var text=snapshot.manual_sales ? __('Average Daily Sales')+': '+format_currency(snapshot.average_daily_sales || 0,row.currency,3) :
            __('Prior-Year Sales')+': '+format_currency(row.previous_year_sales || 0,row.currency,3);
        if(!snapshot.manual_sales && adjustment!==undefined)text+='\n'+__('Sales Change')+': '+Number(adjustment)+'%';
        if(snapshot.manual_sales)text+='\n'+__('Holiday Lists')+': '+(snapshot.holiday_list || __('None'));
        text+='\n'+__('Expected Sales Receipts')+': '+format_currency(row.expected_receipts || 0,row.currency,3);
        var is_today=!row.month && String(row.date)===String(snapshot.forecast_date || (report && report.data && report.data[0] && report.data[0].date));
        if(snapshot.today_policy==='auto-v1' && (is_today || row.month)) {
            text+='\n'+__('Actual Sales Already Recorded')+': '+format_currency(row.sales_already_recorded || 0,row.currency,3);
            text+='\n'+__('Remaining Sales Expected Today')+': '+format_currency(row.remaining_sales_today || 0,row.currency,3);
            text+='\n'+__('Only the remaining sales are added to cash; actual sales are already reflected in opening cash.');
        } else if(is_today || row.month)text+='\n'+__('Saved report: today’s receipts use the original calculation.');

        return text;
    }

    function column_layout(report) {
        if(!report._cashflow_column_layout)report._cashflow_column_layout={pins:[],order:[]};
        return report._cashflow_column_layout;
    }
    function column_field(column) {return column && (column.fieldname || column.id);}
    function table_columns(table) {return table.datamanager && table.datamanager.getColumns ? table.datamanager.getColumns() : [];}
    function permanent_field(field) {return ['_rowIndex','_checkbox','date','month','opening_cash'].indexOf(field)>=0;}
    function arranged_columns(columns,report) {
        var state=column_layout(report),result=[],used={};
        function add(field){var column=columns.find(function(item){return item.fieldname===field;});if(column && !used[field]){result.push(column);used[field]=true;}}
        ['date','month','opening_cash'].concat(state.pins,state.order).forEach(add);
        columns.forEach(function(column){add(column.fieldname);});
        return result;
    }
    function save_column_order(table) {
        var report=table._cashflow_column_report;
        if(!report || report.report_name!=='Cashflow Forecast')return;
        var state=column_layout(report),fields=table_columns(table).map(column_field).filter(function(field){return field && !permanent_field(field);});
        state.order=fields.concat(state.order.filter(function(field){return fields.indexOf(field)<0;}));
    }
    function extra_pinned_fields(table) {
        var state=column_layout(table._cashflow_column_report || frappe.query_report),columns=table_columns(table);
        return state.pins.filter(function(field){return !permanent_field(field) && columns.some(function(column){return column_field(column)===field;});});
    }
    function column_index(element) {
        if(!element)return null;
        var index=element.dataset && element.dataset.colIndex;
        if(index!==undefined && /^\d+$/.test(String(index)))return Number(index);
        var match=String(element.className || '').match(/dt-cell--col-(\d+)/);
        return match?Number(match[1]):null;
    }
    function restore_drag_options(table) {
        var old=table._cashflow_guarded_sortable;
        if(old && old.sortable && old.sortable.option)Object.keys(old.options).forEach(function(key){old.sortable.option(key,old.options[key]);});
        table._cashflow_guarded_sortable=null;
    }
    function enable_column_drag(table) {
        var sortable=table.columnmanager && table.columnmanager.sortable;
        if(!sortable || !sortable.option)return;
        if(table._cashflow_guarded_sortable && table._cashflow_guarded_sortable.sortable===sortable)return;
        restore_drag_options(table);
        var original={};['onMove','filter','preventOnFilter','disabled'].forEach(function(key){original[key]=sortable.option(key);});
        table._cashflow_guarded_sortable={sortable:sortable,options:original};
        sortable.option('onMove',function(event){
            var from=column_index(event && event.dragged),to=column_index(event && event.related),count=table._cashflow_sticky_count;
            return from!==null && to!==null && from>=count && to>=count;
        });
        sortable.option('filter','.dt-cell__resize-handle, .dt-dropdown, .cashflow-sticky-header');
        sortable.option('preventOnFilter',false);sortable.option('disabled',false);
    }
    function align_pinned_columns(table,leading) {
        if(table._cashflow_aligning)return false;
        var columns=table_columns(table);
        if(!columns.length)return true;
        var date=columns.find(function(column){return ['date','month'].indexOf(column_field(column))>=0;});
        var desired=[date && column_field(date),'opening_cash'].concat(extra_pinned_fields(table));
        for(var index=0;index<desired.length;index++) {
            var column=columns.find(function(item){return column_field(item)===desired[index];});
            if(column && column.colIndex!==leading+index) {
                if(!table.columnmanager || !table.columnmanager.switchColumn)return true;
                table._cashflow_aligning=true;
                table.columnmanager.switchColumn(column.colIndex,leading+index);return false;
            }
        }
        return true;
    }
    function toggle_pinned_column(table,column) {
        var field=column_field(column);
        if(!field || permanent_field(field)) {
            if(field && field!=='_rowIndex' && field!=='_checkbox')frappe.msgprint(__('Date / Month and Opening Cash are always pinned.'));
            return;
        }
        var state=column_layout(table._cashflow_column_report || frappe.query_report),index=state.pins.indexOf(field);
        if(index<0)state.pins.push(field);else state.pins.splice(index,1);
        if(table._cashflow_pin_refresh)table._cashflow_pin_refresh();
    }

    // Same body-sticky/header-translation approach as Purchase Plan.
    function pin_columns(datatable) {
        var wrapper=datatable && datatable.wrapper,body=datatable && datatable.bodyScrollable;
        if(!wrapper || !body || !wrapper.querySelectorAll || typeof window==='undefined')return;
        if(datatable._cashflow_pin_cleanup)datatable._cashflow_pin_cleanup();
        var leading=(datatable.options && datatable.options.checkboxColumn?1:0)+(datatable.options && datatable.options.serialNoColumn===false?0:1);
        datatable._cashflow_column_report=frappe.query_report;
        var count=leading+2+extra_pinned_fields(datatable).length,frame=null,resizing=false;
        var selected=datatable._cashflow_selected_row===undefined?null:datatable._cashflow_selected_row;
        datatable._cashflow_sticky_count=count;
        datatable._cashflow_pin_refresh=function(reason){
            if(reason==='sort')datatable._cashflow_selected_row=null;
            if(datatable._cashflow_layout_frame)return;
            datatable._cashflow_layout_frame=window.requestAnimationFrame(function(){
                datatable._cashflow_layout_frame=null;
                if(frappe.query_report && frappe.query_report.report_name==='Cashflow Forecast')pin_columns(datatable);
            });
        };
        if(!datatable._cashflow_pin_events && datatable.on) {
            datatable._cashflow_pin_events=true;
            datatable.on('onSortColumn',function(){if(datatable._cashflow_pin_refresh)datatable._cashflow_pin_refresh('sort');});
            datatable.on('onSwitchColumn',function(){
                var aligning=datatable._cashflow_aligning;datatable._cashflow_aligning=false;
                if(!aligning)save_column_order(datatable);
                if(datatable._cashflow_pin_refresh)datatable._cashflow_pin_refresh();
            });
            datatable.on('onRemoveColumn',function(column){
                var state=column_layout(datatable._cashflow_column_report),field=column_field(column);
                state.pins=state.pins.filter(function(item){return item!==field;});
                save_column_order(datatable);
                if(datatable._cashflow_pin_refresh)datatable._cashflow_pin_refresh();
            });
            datatable.on('onDestroy',function(){if(datatable._cashflow_pin_cleanup)datatable._cashflow_pin_cleanup();});
        }
        if(datatable.removeColumn && !datatable._cashflow_remove_column_original) {
            var original_remove=datatable.removeColumn;datatable._cashflow_remove_column_original=original_remove;
            datatable.removeColumn=function(index){
                var current=frappe.query_report,column=table_columns(this)[index];
                if(current && current.report_name==='Cashflow Forecast' && permanent_field(column_field(column))) {
                    frappe.msgprint(__('Date / Month and Opening Cash cannot be removed.'));return;
                }
                return original_remove.apply(this,arguments);
            };
        }
        var cleanup_controls=function(){
            if(datatable._cashflow_layout_frame)window.cancelAnimationFrame(datatable._cashflow_layout_frame);
            datatable._cashflow_layout_frame=null;datatable._cashflow_pin_refresh=null;
            restore_drag_options(datatable);
            if(datatable._cashflow_remove_column_original){datatable.removeColumn=datatable._cashflow_remove_column_original;datatable._cashflow_remove_column_original=null;}
            datatable._cashflow_pin_cleanup=null;
        };
        datatable._cashflow_pin_cleanup=cleanup_controls;
        if(!align_pinned_columns(datatable,leading))return;
        save_column_order(datatable);
        wrapper.classList.remove('cashflow-pins-2','cashflow-pins-3','cashflow-pins-4');
        wrapper.classList.add('cashflow-sticky-columns');
        function update() {
            frame=null;enable_column_drag(datatable);
            var left=0;
            for(var index=0;index<count;index++) {
                var header=wrapper.querySelector('.dt-row-header .dt-cell--col-'+index);
                wrapper.style.setProperty('--cashflow-left-'+index,left+'px');
                left+=header && header.getBoundingClientRect().width || (index<leading?50:(index===leading?110:145));
                wrapper.querySelectorAll('.dt-header .dt-cell--col-'+index+', .dt-footer .dt-cell--col-'+index).forEach(function(cell){
                    cell.style.transform='translateX('+body.scrollLeft+'px)';
                    if(cell.classList && cell.closest && cell.closest('.dt-header'))cell.classList.add('cashflow-sticky-header');
                });
            }
            wrapper.querySelectorAll('.dt-row[data-row-index]').forEach(function(row){
                if(row.classList.contains('dt-row-header') || row.classList.contains('dt-row-filter') || row.closest('.dt-footer'))return;
                row.classList.toggle('cashflow-selected-row',selected!==null && row.getAttribute('data-row-index')===selected);
            });
            var empty=body.querySelector('.dt-scrollable__no-data'),headerRow=wrapper.querySelector('.dt-row-header');
            if(empty && headerRow) {
                var width=Math.max(headerRow.scrollWidth,headerRow.getBoundingClientRect().width);
                empty.style.width=width+'px';empty.style.minWidth=width+'px';
                body.scrollLeft=Math.min(datatable._cashflow_last_scroll || 0,Math.max(0,body.scrollWidth-body.clientWidth));
            }
        }
        function queue(){
            var current=frappe.query_report && frappe.query_report.report_name;
            if(current && current!=='Cashflow Forecast'){if(datatable._cashflow_pin_cleanup)datatable._cashflow_pin_cleanup();return;}
            if(frame===null)frame=window.requestAnimationFrame(update);
        }
        if(datatable._cashflow_last_scroll===undefined)datatable._cashflow_last_scroll=body.scrollLeft;
        function scroll(){
            var empty=body.querySelector('.dt-scrollable__no-data');
            if(!empty || body.scrollWidth>body.clientWidth)datatable._cashflow_last_scroll=body.scrollLeft;
            queue();
        }
        function select(event) {
            var cell=event.target.closest('.dt-cell'),row=cell && cell.closest('.dt-row');
            if(!row || row.classList.contains('dt-row-header') || row.classList.contains('dt-row-filter') || row.closest('.dt-footer'))return;
            var index=row.getAttribute('data-row-index');if(!/^\d+$/.test(index || ''))return;
            selected=index;datatable._cashflow_selected_row=index;queue();
        }
        function start_resize(event){if(event.target.closest('.dt-cell__resize-handle'))resizing=true;}
        function finish_resize(){if(resizing){resizing=false;queue();}}
        wrapper.addEventListener('click',select);
        wrapper.addEventListener('mousedown',start_resize);
        wrapper.addEventListener('dblclick',queue);
        body.addEventListener('scroll',scroll,{passive:true});
        window.addEventListener('resize',queue);
        document.addEventListener('mouseup',finish_resize);
        var observer=typeof MutationObserver!=='undefined'?new MutationObserver(queue):null;
        if(observer)observer.observe(body,{childList:true,subtree:true});
        var resizeObserver=typeof ResizeObserver!=='undefined'?new ResizeObserver(queue):null;
        if(resizeObserver)resizeObserver.observe(wrapper);
        var headerObserver=typeof MutationObserver!=='undefined' && datatable.header?new MutationObserver(queue):null;
        if(headerObserver)headerObserver.observe(datatable.header,{childList:true,subtree:true});
        datatable._cashflow_pin_cleanup=function(){
            if(frame!==null)window.cancelAnimationFrame(frame);
            wrapper.classList.remove('cashflow-sticky-columns','cashflow-pins-2','cashflow-pins-3','cashflow-pins-4');
            for(var i=0;i<count;i++)wrapper.querySelectorAll('.dt-header .dt-cell--col-'+i+', .dt-footer .dt-cell--col-'+i).forEach(function(cell){cell.style.transform='';if(cell.classList)cell.classList.remove('cashflow-sticky-header');});
            if(observer)observer.disconnect();if(resizeObserver)resizeObserver.disconnect();if(headerObserver)headerObserver.disconnect();
            datatable._cashflow_pin_refresh=null;
            wrapper.removeEventListener('click',select);wrapper.removeEventListener('mousedown',start_resize);wrapper.removeEventListener('dblclick',queue);
            body.removeEventListener('scroll',scroll);window.removeEventListener('resize',queue);document.removeEventListener('mouseup',finish_resize);
            cleanup_controls();
        };
        var style=document.getElementById('cashflow-sticky-style');
        if(!style){style=document.createElement('style');style.id='cashflow-sticky-style';document.head.appendChild(style);}
        var css='';
        for(var i=0;i<count;i++) {
            var cell='.cashflow-sticky-columns .dt-cell--col-'+i;
            css+=cell+'{position:sticky;left:var(--cashflow-left-'+i+');z-index:3;background:#fff;}';
            css+='.cashflow-sticky-columns .dt-header .dt-cell--col-'+i+','+
                '.cashflow-sticky-columns .dt-footer .dt-cell--col-'+i+
                '{position:relative;left:auto;z-index:30!important;background:#f7fafc!important;isolation:isolate;}';
        }
        var edge='.cashflow-sticky-columns .dt-cell--col-'+(count-1);
        css+=edge+'{box-shadow:2px 0 2px rgba(0,0,0,.08);}';
        css+=edge+'::after{content:"";position:absolute;right:0;top:0;bottom:0;width:1px;background:#cbd5e1;z-index:5;pointer-events:none;}';
        css+='.cashflow-sticky-columns .dt-dropdown__list{z-index:60!important;}';
        if(style.textContent!==css)style.textContent=css;
        update();
    }

    function short_note(value) {
        var note=String(value || '');
        var replacements=[
            ['Payroll Entry / salary-period link missing; verify against salary estimates and final settlements. No period inferred from remarks.','Missing payroll reference. Check for duplicate salary amounts.'],
            ['Supplier invoice/PO reference missing or ambiguous; verify overlap with outstanding supplier obligations.','Check the invoice/PO reference and unpaid balance.'],
            ['Cheque payment uses posting date provisionally; verify expected clearance/payment date.','Check the cheque payment date.'],
            ['Offsetting journal lines prevent safe obligation matching; verify allocations.','Check journal allocations.'],
            ['Some referenced amounts were not matched to an outstanding obligation; verify already-paid items, competing prepared payments or missing source access.','Some allocations could not be matched. Check existing payments.'],
            ['Possible fixed-expense schedule overlap; JE has no explicit Fixed Expense link. Verify existing payment matching.','Check for an existing fixed-expense payment.']
        ];
        replacements.forEach(function(pair){note=note.split(pair[0]).join(__(pair[1]));});return note;
    }

    function plain_text(html) {
        if (typeof document !== 'undefined' && document.createElement) {
            var node=document.createElement('div');node.innerHTML=String(html || '');return node.textContent || '';
        }
        return String(html || '').replace(/<[^>]*>/g,'');
    }
    function update_forecast_end(report, change, notify) {
        if (!change || !change.end_date) return;
        var field=(report.filters || []).find(function(control){return control.df.fieldname==='end_date';});
        if(field && typeof field.set_input==='function')field.set_input(change.end_date);
        if(notify)frappe.msgprint({title:__('Forecast Until Updated'),indicator:'blue',
            message:__('Forecast Until changed to')+' '+date_label(change.end_date)+' '+__('to include the last outstanding purchase payment.')});
    }

    function date_label(value) {
        return /^\d{4}-\d{2}-\d{2}$/.test(String(value)) ? String(value).split('-').reverse().join('-') : String(value || '');
    }
    function manual_inputs(report) {
        var groups = {support:[],expenses:[],purchases:[]};
        var rows = report && report.raw_data && report.raw_data.result || [];
        rows.forEach(function(row) {
            (row.sources || []).forEach(function(item) {
                if (!isFinite(Number(item.amount)) || Number(item.amount) <= 0) return;
                if (item.manual_support && item.category === 'other_receipts') groups.support.push(item);
                else if (item.category === 'extra_expenses') groups.expenses.push(item);
                else if (item.scenario && item.category !== 'vat_accrual') groups.purchases.push(item);
            });
        });
        return groups;
    }

    function manual_input_strip(report, currency) {
        var groups = manual_inputs(report);
        var labels = {support:__('Support'),expenses:__('Extra Expenses'),purchases:__('Purchases')};
        var buttons = Object.keys(groups).filter(function(key){return groups[key].length;}).map(function(key) {
            var total = groups[key].reduce(function(sum,item){return sum+Math.round(Number(item.amount)*1000);},0)/1000;
            return '<button type="button" class="cashflow-manual-input" data-input-kind="'+key+'" title="'+
                esc(__('View dates and amounts'))+'">'+esc(labels[key])+' · <b>'+format_currency(total,currency,3)+'</b></button>';
        }).join('');
        return buttons ? '<div class="cashflow-manual-inputs">'+buttons+'</div>' : '';
    }

    function manual_input_details(report, kind) {
        var groups = manual_inputs(report),items = groups[kind];
        if (!items || !items.length) return;
        var labels = {support:__('Support'),expenses:__('Extra Expenses'),purchases:__('Purchases')};
        var first = (report.raw_data.result || [])[0] || {};
        var currency = first.currency;
        var html = '<div style="max-height:60vh;overflow:auto"><table class="table table-bordered"><thead><tr><th>'+__('Date')+
            '</th><th>'+__('Details')+'</th><th class="text-right">'+__('Amount')+'</th></tr></thead><tbody>';
        items.slice().sort(function(a,b){return String(a.date).localeCompare(String(b.date));}).forEach(function(item) {
            var description = item.description || labels[kind];
            if (kind === 'purchases') {
                var type = item.category === 'customs' ? __('Customs') : (item.category === 'import_vat' ? __('Import VAT') :
                    (item.scenario_kind === 'arrival' ? __('Import Charges') : __('Supplier Payment')));
                description = (item.purchase_number ? __('Purchase')+' '+item.purchase_number+' · ' : '')+type;
            }
            html += '<tr><td style="white-space:nowrap">'+esc(date_label(item.date))+'</td><td>'+esc(description)+
                '</td><td class="text-right" style="white-space:nowrap">'+format_currency(item.amount,currency,3)+'</td></tr>';
        });
        html += '</tbody></table></div>';
        var dialog = new frappe.ui.Dialog({title:labels[kind],fields:[{fieldtype:'HTML',options:html}]});
        dialog.show();
    }

    function opening_accounts(snapshot,message) {
        var accounts=(snapshot.opening_accounts || (snapshot.calculation_inputs || {}).accounts_breakdown || []).slice();
        if (!accounts.length) {
            message.split(/<br\s*\/?\s*>/i).forEach(function(part){
                if (part.indexOf(';')<0 || part.indexOf(':')<0) return;
                plain_text(part).split(';').forEach(function(entry){
                    var match=entry.match(/^\s*(.+):\s*(-?[\d,]+\.\d{3})\s*$/);
                    if(match) accounts.push({account:match[1],amount:match[2].replace(/,/g,'')});
                });
            });
        }
        return accounts;
    }

    function collapse_styles() {
        return '<style>'+
            '.cashflow-expandable>summary,.cashflow-review-group>summary{list-style:none;display:flex;align-items:center;gap:8px;cursor:pointer;padding:3px 0;}'+
            '.cashflow-expandable>summary::-webkit-details-marker,.cashflow-review-group>summary::-webkit-details-marker{display:none;}'+
            '.cashflow-expandable>summary::marker,.cashflow-review-group>summary::marker{content:"";}'+
            '.cashflow-collapse-chevron{display:inline-block;flex:0 0 12px;width:12px;font-size:12px;line-height:1;color:#52647a;transform:rotate(0deg);}'+
            '.cashflow-expandable[open]>summary>.cashflow-collapse-chevron,.cashflow-review-group[open]>summary>.cashflow-collapse-chevron{transform:rotate(90deg);}'+
            '.cashflow-expandable>summary:focus,.cashflow-review-group>summary:focus{outline:2px solid #9bbcf2;outline-offset:2px;}'+
            '</style>';
    }

    function collapse_heading(html) {
        return '<summary><span class="cashflow-collapse-chevron" aria-hidden="true">&#9656;</span><span>'+html+'</span></summary>';
    }

    function excluded_accounts_html(snapshot, currency) {
        var rows=snapshot.excluded_opening_accounts || [];
        if(!rows.length)return '';
        var html='<details class="cashflow-expandable">'+collapse_heading(esc(__('Excluded Accounts')))+'<table class="table table-condensed"><tbody>';
        rows.forEach(function(row){html+='<tr><td>'+esc(row.account)+'</td><td class="text-right">'+format_currency(row.amount,currency,3)+'</td></tr>';});
        return html+'</tbody></table></details>';
    }

    function opening_balance_details(report) {
        var raw=report.raw_data || {},snapshot=context_for(report),first=(raw.result || [])[0] || {};
        var accounts=opening_accounts(snapshot,snapshot.message || raw.message || '');
        var html=collapse_styles()+'<div style="max-height:65vh;overflow:auto">';
        html+='<p>'+__('As of')+' '+esc(date_label(snapshot.forecast_date || first.date))+'</p>';
        if (accounts.length) {
            html+='<table class="table table-condensed"><thead><tr><th>'+__('Account')+'</th><th class="text-right">'+__('Balance')+'</th></tr></thead><tbody>';
            var total=0;
            accounts.forEach(function(account){
                var amount=Number(account.amount) || 0;
                total+=Math.round(amount*1000);
                html+='<tr><td>'+esc(account.account)+'</td><td class="text-right">'+format_currency(amount.toFixed(3),first.currency,3)+'</td></tr>';
            });
            var support=Number(snapshot.support_amount || (snapshot.base_filters || {}).support_amount) || 0;
            if (support) {
                total+=Math.round(support*1000);
                html+='<tr><td>'+__('Support')+'</td><td class="text-right">'+format_currency(support.toFixed(3),first.currency,3)+'</td></tr>';
            }
            html+='</tbody><tfoot><tr><th>'+__('Opening Available Cash')+'</th><th class="text-right">'+format_currency((total/1000).toFixed(3),first.currency,3)+'</th></tr></tfoot></table>';
        } else html+='<p>'+__('Account breakdown is not available in this saved report. Generate a new report to include it.')+'</p>';
        html+=excluded_accounts_html(snapshot,first.currency)+'</div>';
        var dialog=new frappe.ui.Dialog({title:__('Opening Cash'),size:'large',fields:[{fieldtype:'HTML',options:html}]});dialog.show();
    }

    function report_notes(report) {
        var raw=report.raw_data || {},snapshot=context_for(report),rows=raw.result || [],first=rows[0] || {};
        var message=snapshot.message || raw.message || '';
        var accounts=opening_accounts(snapshot,message);
        var warnings=snapshot.warnings || (message.match(/<li[^>]*>[\s\S]*?<\/li>/gi) || []).map(plain_text);
        var summary=snapshot.report_summary || raw.report_summary || [];
        var actual=summary.find(function(card){return card.label === __('Actual Sales Today (Reference)');});
        var html=collapse_styles()+'<div style="font-size:13px;line-height:1.6;color:#334155;max-height:65vh;overflow:auto">';
        html+='<table class="table table-condensed"><tbody><tr><td>'+__('Forecast Date')+'</td><td>'+esc(date_label(snapshot.forecast_date || first.date))+'</td></tr>';
        if(snapshot.manual_sales) {
            html+='<tr><td>'+__('Average Daily Sales')+'</td><td>'+format_currency(snapshot.average_daily_sales || 0,first.currency,3)+'</td></tr>';
            html+='<tr><td>'+__('Holiday List')+'</td><td>'+esc(snapshot.holiday_list || __('None'))+'</td></tr>';
        }
        if(!snapshot.manual_sales && snapshot.sales_adjustment!==undefined) html+='<tr><td>'+__('Sales Change')+'</td><td>'+esc(Number(snapshot.sales_adjustment))+'%</td></tr>';
        if(Number(snapshot.support_amount)) html+='<tr><td>'+__('Support Added to Opening Cash')+'</td><td>'+format_currency(snapshot.support_amount,first.currency,3)+'</td></tr>';
        if(actual) html+='<tr><td>'+__('Actual Sales Today')+'</td><td>'+(actual.datatype==='Currency'?format_currency(actual.value,actual.currency,3):esc(actual.value))+'</td></tr>';
        html+='</tbody></table>';
        if(accounts.length) {
            html+='<details class="cashflow-expandable">'+collapse_heading(esc(__('Opening Account Balances')))+'<table class="table table-condensed"><thead><tr><th>'+__('Account')+'</th><th class="text-right">'+__('Balance')+'</th></tr></thead><tbody>';
            accounts.forEach(function(account){html+='<tr><td>'+esc(account.account)+'</td><td class="text-right">'+format_currency(account.amount,first.currency,3)+'</td></tr>';});
            html+='</tbody></table></details>';
        }
        if(snapshot.payroll_reconciliation) {
            var payroll=snapshot.payroll_reconciliation;
            html+='<h5>'+__('Payroll Payable')+'</h5><table class="table table-condensed"><tbody>';
            [['Account',esc(payroll.account || '')],['Recorded Balance',format_currency(payroll.balance || 0,first.currency,3)],
             ['Covered by Scheduled Payments',format_currency(payroll.scheduled || 0,first.currency,3)],
             ['Remaining to Schedule',format_currency(payroll.remaining || 0,first.currency,3)]].forEach(function(item){
                html+='<tr><td>'+__(item[0])+'</td><td>'+item[1]+'</td></tr>';
            });
            html+='</tbody></table>';
        }
        if(snapshot.vat_reconciliation && snapshot.vat_reconciliation.length) {
            html+='<h5>'+__('VAT Recorded by Quarter')+'</h5><table class="table table-condensed"><thead><tr><th>'+__('Quarter')+'</th><th>'+__('Net VAT')+'</th><th>'+__('Paid')+'</th><th>'+__('Credit Used')+'</th><th>'+__('Balance')+'</th><th>'+__('Status / Payment')+'</th></tr></thead><tbody>';
            snapshot.vat_reconciliation.forEach(function(period){
                var links=(period.documents || []).map(function(ref){return '<a target="_blank" rel="noopener" href="#Form/'+encodeURIComponent(ref.doctype)+'/'+encodeURIComponent(ref.name)+'">'+esc(ref.name)+'</a>';}).join(', ');
                html+='<tr><td>'+esc(period.quarter)+'</td><td>'+format_currency(period.net_vat,first.currency,3)+'</td><td>'+format_currency(period.paid,first.currency,3)+'</td><td>'+format_currency(period.credit_used || 0,first.currency,3)+'</td><td>'+format_currency(period.balance,first.currency,3)+'</td><td>'+esc(__(period.status))+'<br>'+links+'</td></tr>';
            });
            html+='</tbody></table>';
        }
        if(warnings.length) html+='<h5 style="margin-top:16px">'+__('Items to Review')+'</h5><ul style="padding-left:20px">'+warnings.map(function(note){return '<li style="margin-bottom:7px">'+esc(short_note(note))+'</li>';}).join('')+'</ul>';
        html+=excluded_accounts_html(snapshot,first.currency);
        if(!warnings.length && !accounts.length && message) html+='<p>'+esc(plain_text(message))+'</p>';
        html+='</div>';
        var dialog=new frappe.ui.Dialog({title:__('Report Notes'),size:'large',fields:[{fieldtype:'HTML',options:html}]});dialog.show();
    }

    function scenarios(report, field) {
        try { return JSON.parse(report.get_filter_value(field || 'extra_expenses') || '[]'); }
        catch (e) { return []; }
    }

    function edit_expenses(report, support) {
        var filter = support ? 'support_payments' : 'extra_expenses';
        var title = support ? __('Support') : __('Extra Expenses');
        var rows = scenarios(report, filter);
        var legacy = support ? Number(report.get_filter_value('support_amount') || 0) : 0;
        if (legacy > 0) rows.unshift({date:frappe.datetime.get_today(),amount:legacy,description:''});
        var dialog = new frappe.ui.Dialog({
            title: title, size: 'large',
            fields: [
                {fieldtype: 'HTML', options: '<p>'+(support ? __('Add incoming support by date.') : __('Add expenses not already included.'))+'</p>'},
                {fieldname: 'expenses', fieldtype: 'Table', label: title,
                    cannot_add_rows: false, in_place_edit: true, data: rows,
                    fields: [
                        {fieldname: 'date', fieldtype: 'Date', label: support ? __('Date') : __('Payment Date'), reqd: 1, in_list_view: 1},
                        {fieldname: 'amount', fieldtype: 'Currency', precision: 3, label: __('Amount'), reqd: 1, in_list_view: 1},
                        {fieldname: 'description', fieldtype: 'Data', label: __('Description'), reqd: support ? 0 : 1, in_list_view: 1}
                    ]}
            ],
            primary_action_label: __('Apply'),
            primary_action: function (values) {
                var data = values.expenses || [];
                var valid = data.every(function (row) {
                    return row.date >= frappe.datetime.get_today() && row.date <= report.get_filter_value('end_date') &&
                        isFinite(Number(row.amount)) && (support ? Number(row.amount) > 0 : Number(row.amount) >= 0) &&
                        String(row.description || '').trim().length <= 500 && (support || String(row.description || '').trim());
                });
                if (!valid || data.length > 500) { frappe.msgprint(support ? __('Enter up to 500 rows, each with a date within the forecast period and a positive amount. Description is optional, maximum 500 characters.') : __('Each row needs a date within the forecast period, a nonnegative amount and a description.')); return; }
                var value = JSON.stringify(data.map(function (row) {
                    return {date: row.date, amount: row.amount, description: row.description || ''};
                }));
                if (legacy > 0) {
                    // v12 batches this into one refresh; reset legacy opening support last.
                    report.set_filter_value({support_payments:value,support_amount:0});
                } else report.set_filter_value(filter, value);
                dialog.hide();
            }
        });
        dialog.show();
    }

    function download_purchase_check(report) {
        var raw=report.raw_data || {},cols=(raw.columns || []).filter(function(col){return !col.hidden;});
        var quote=function(value){return '"'+String(value===undefined || value===null?'':value).replace(/"/g,'""')+'"';};
        var lines=[cols.map(function(col){return quote(col.label);}).join(',')];
        (raw.result || []).forEach(function(row){lines.push(cols.map(function(col){var value=row[col.fieldname];
            if(typeof value==='string' && /^[=+@\t\r]/.test(value))value="'"+value;return quote(value);}).join(','));});
        var url=URL.createObjectURL(new Blob(['\ufeff'+lines.join('\r\n')],{type:'text/csv;charset=utf-8'}));
        var link=document.createElement('a');link.href=url;link.download='cashflow-purchase-check.csv';link.click();
        setTimeout(function(){URL.revokeObjectURL(url);},1000);
    }

    function toggle_sales_fields(report) {
        if (!report.get_filter) return;
        var enabled=Number(report.get_filter_value('manual_sales'));
        ['average_daily_sales'].forEach(function(name){var field=report.get_filter(name);if(field && field.toggle)field.toggle(!!enabled);});
        var change=report.get_filter('sales_adjustment');if(change && change.toggle)change.toggle(!enabled);
    }

    function check_purchase(report) {
        var saved = {};
        try { saved = JSON.parse(report.get_filter_value('purchase_scenario') || '{}'); } catch (error) {}
        var simple = saved.schema === 2, current = saved.schema === 3;
        var payments = saved.payments || [];
        var dialog, busy = false;
        function set_purchase(purchase) {
            var field = report.get_filter && report.get_filter('purchase_scenario');
            if (field && field.set_input) field.set_input(JSON.stringify(purchase));
            else return report.set_filter_value('purchase_scenario',JSON.stringify(purchase));
        }
        function finish(purchase) {
            if (busy) return;
            busy = true;
            var raw = report.raw_data || {}, snapshot = context_for(report);
            var name = raw.prepared_report_name || (raw.doc && raw.doc.name);
            if (name && snapshot.calculation_inputs && snapshot.vat_policy === 'quarter-v4' && snapshot.today_policy === 'auto-v1') {
                var filters = Object.assign({},report.get_filter_values(true),{purchase_scenario:JSON.stringify(purchase)});
                return frappe.call({method:method+'recalculate_purchase',type:'POST',
                    args:{prepared_report_name:name,filters:filters},freeze:true,freeze_message:__('Checking purchase…')})
                    .then(function(response) {
                        var data = response.message;
                        set_purchase(purchase);
                        data.doc = raw.doc;
                        report.prepare_report_data(data);
                        if (report.$chart) report.$chart.empty();
                        var options = report.get_chart_options(data);
                        if (options) report.render_chart(options);
                        report.render_datatable();
                        dialog.hide();
                        frappe.show_alert({message:__('Purchase checked using this report’s balances.'),indicator:'blue'});
                    }).then(function(result){busy=false;return result;},function(error){busy=false;throw error;});
            }
            return Promise.resolve(set_purchase(purchase)).then(function() {
                dialog.hide();
                return report.generate_background_report();
            }).then(function(result){busy=false;return result;},function(error){busy=false;throw error;});
        }
        var drafts;
        if ((saved.schema===4 || saved.schema===5) && Array.isArray(saved.purchases) && saved.purchases.length) {
            drafts=JSON.parse(JSON.stringify(saved.purchases));
        } else {
            var amount=simple || current?saved.amount:saved.purchase_value;
            if(simple || (current && !Number(saved.split_payments)))payments=[{date:saved.date || frappe.datetime.get_today(),amount:amount || 0}];
            if(!payments.length)payments=[{date:frappe.datetime.get_today(),amount:0}];
            var eta=saved.eta_date;
            if(!eta && simple && saved.date)eta=saved.interval_unit==='Months'?
                frappe.datetime.add_months(saved.date,saved.interval || 0):
                (frappe.datetime.add_days?frappe.datetime.add_days(saved.date,saved.interval || 0):saved.date);
            drafts=[{payments:payments.map(function(row){return {date:row.date,amount:row.amount};}),
                international:simple?saved.include_customs_vat:saved.international || 0,eta_date:eta}];
        }
        drafts.forEach(function(draft) {
            if(saved.schema!==5) {
                draft.customs_required=Number(draft.international || 0);
                draft.import_vat_required=Number(draft.international || 0);
                draft.customs_date=draft.eta_date;
                draft.import_vat_date=draft.eta_date;
            }
        });
        function key(name,index){return index?name+'_'+index:name;}
        function update_import_fields(index) {
            if(!dialog)return;
            var enabled=Number(dialog.get_value(key('include_customs_vat',index)))===1;
            dialog.set_df_property(key('import_charges',index),'hidden',enabled?0:1);
        }
        function renumber() {
            var number=0;
            drafts.forEach(function(draft,index){
                if(draft.removed)return;
                var section=dialog.fields_dict['purchase_section_'+index];
                number++;section.df.label=__('Purchase')+' '+number;
                if(section.head)section.head.find('a').text(section.df.label);
            });
        }
        function purchase_fields(index) {
            var draft=drafts[index];
            return [
                {fieldname:'purchase_section_'+index,fieldtype:'Section Break',label:__('Purchase')+' '+(index+1),collapsible:1},
                {fieldname:key('payments',index),fieldtype:'Table',label:__('Supplier Payments'),in_place_edit:true,
                    data:draft.payments.map(function(row){return Object.assign({},row);}),fields:[
                        {fieldname:'date',fieldtype:'Date',label:__('Payment Date'),in_list_view:1,reqd:1},
                        {fieldname:'amount',fieldtype:'Currency',precision:3,label:__('Amount'),in_list_view:1,reqd:1}]},
                {fieldname:key('include_customs_vat',index),fieldtype:'Check',label:__('Include Customs & VAT'),
                    default:Number(draft.customs_required || 0) || Number(draft.import_vat_required || 0),onchange:function(){update_import_fields(index);}},
                {fieldname:key('import_charges',index),fieldtype:'Table',label:__('Customs & VAT'),in_place_edit:true,
                    cannot_add_rows:true,hidden:!Number(draft.customs_required || draft.import_vat_required),
                    description:__('Leave a date blank to exclude that charge.'),
                    data:[{charge:__('Customs'),date:Number(draft.customs_required)?draft.customs_date:null},
                          {charge:__('Import VAT'),date:Number(draft.import_vat_required)?draft.import_vat_date:null}],
                    fields:[{fieldname:'charge',fieldtype:'Data',label:__('Charge'),read_only:1,in_list_view:1},
                            {fieldname:'date',fieldtype:'Date',label:__('Payment Date'),in_list_view:1}]},
                {fieldname:key('suggest_date',index),fieldtype:'Button',label:__('Suggest Date'),click:suggestion_action},
                {fieldname:key('remove_purchase',index),fieldtype:'Button',label:__('Remove Purchase'),click:function(){
                    if(busy)return;
                    drafts[index].removed=true;
                    var section=dialog.fields_dict['purchase_section_'+index];section.df.hidden=1;section.refresh();
                    renumber();
                }},
                {fieldname:key('suggestion',index),fieldtype:'HTML',hidden:1},
                {fieldname:key('apply_suggestion',index),fieldtype:'Button',label:__('Use Date'),hidden:1,click:function(){return apply_suggestion(index);}}
            ];
        }
        function add_purchase() {
            if(busy)return;
            if(drafts.filter(function(draft){return !draft.removed;}).length>=20){frappe.msgprint(__('Maximum 20 purchases.'));return;}
            drafts.forEach(function(draft,index){
                var section=dialog.fields_dict['purchase_section_'+index];if(section && section.collapse)section.collapse(true);
            });
            var index=drafts.length;
            drafts.push({payments:[{date:frappe.datetime.get_today(),amount:0}],customs_required:0,import_vat_required:0});
            dialog.add_fields(purchase_fields(index));update_import_fields(index);renumber();style_purchase_actions();
            var section=dialog.fields_dict['purchase_section_'+index];if(section.collapse)section.collapse(false);
            // Keep Add More below the appended purchase, without recreating any grids.
            var actions=dialog.fields_dict.purchase_actions;
            if(actions && actions.wrapper)actions.wrapper.appendTo(dialog.body);
        }
        var suggested={}, suggestedInput=null;
        function collect_purchases(values) {
            if(!values)return;
            var purchases=[];
            for(var index=0;index<drafts.length;index++) {
                if(drafts[index].removed)continue;
                var rows=(values[key('payments',index)] || []).map(function(row){return {date:row.date,amount:row.amount};});
                var charges=Number(values[key('include_customs_vat',index)] || 0) ? values[key('import_charges',index)] || [] : [];
                var customsRow=charges.find(function(row){return row.charge===__('Customs');});
                var vatRow=charges.find(function(row){return row.charge===__('Import VAT');});
                var customsDate=customsRow && customsRow.date,vatDate=vatRow && vatRow.date;
                var customs=customsDate?1:0,vat=vatDate?1:0;
                // Ignore untouched extra sections; partially entered payments still require correction.
                if(rows.every(function(row){return !Number(row.amount || 0);}) && !customs && !vat)continue;
                if(!rows.length || rows.some(function(row){return !row.date || !isFinite(Number(row.amount)) || Number(row.amount)<=0;})) {
                    frappe.msgprint(__('Enter a date and positive amount for every payment in Purchase')+' '+(purchases.length+1));return;
                }
                purchases.push({payments:rows,customs_required:customs,import_vat_required:vat,
                    customs_date:customs?customsDate:null,import_vat_date:vat?vatDate:null});
            }
            if(!purchases.length){frappe.msgprint(__('Add a supplier payment, or use Clear All Purchases.'));return;}
            return {schema:5,purchases:purchases};
        }
        function suggestion_action() {
            if(busy)return;
            var purchase=collect_purchases(dialog.get_values());if(!purchase)return;
            var raw=report.raw_data || {},snapshot=context_for(report),name=raw.prepared_report_name || (raw.doc && raw.doc.name);
            if(!name || !snapshot.calculation_inputs){frappe.msgprint(__('Generate the report before suggesting dates.'));return;}
            busy=true;
            var input=JSON.stringify(purchase);
            return frappe.call({method:method+'recalculate_purchase',type:'POST',freeze:true,freeze_message:__('Finding purchase dates…'),
                args:{prepared_report_name:name,suggest_purchase_dates:1,filters:Object.assign({},report.get_filter_values(true),{purchase_scenario:input})}})
                .then(function(response){
                    suggested={};suggestedInput=input+'|'+String(report.get_filter_value('maximum_shortage'));
                    (response.message.suggestions || []).forEach(function(result){suggested[result.purchase_number]=result;});
                    var number=0;
                    drafts.forEach(function(draft,index){
                        if(draft.removed)return;
                        var rows=dialog.get_values()[key('payments',index)] || [];
                        if(rows.every(function(row){return !Number(row.amount || 0);}))return;
                        number++;var result=suggested[number];
                        draft.suggestion=result;
                        var valid=result && result.first_cost_date;
                        var currency=(report.data && report.data[0] && report.data[0].currency) || 'BHD';
                        var low=valid && result.lowest_cash!==undefined?Number(result.lowest_cash):null;
                        var state=valid?(low!==null && low<0?'is-tolerated':'is-positive'):'is-unavailable';
                        var html='<div class="cashflow-result-box '+state+'"><div class="cashflow-result-copy">';
                        if(valid) {
                            html+='<div class="cashflow-result-date">'+esc(Number(result.shift_days)===0?__('Payment date'):__('Suggested payment date'))+
                                ' <strong>'+esc(date_label(result.supplier_date))+'</strong></div>';
                            if(low!==null) {
                                html+='<div>'+__('Lowest closing cash after this purchase')+': <strong>'+format_currency(low,currency,3)+'</strong></div>';
                                html+='<div class="cashflow-result-status">'+(low<0?
                                    __('Shortage')+' '+format_currency(Math.abs(low),currency,3)+' '+__('is within your')+' '+
                                    format_currency(report.get_filter_value('maximum_shortage') || 0,currency,3)+' '+__('tolerance.'):
                                    __('No cash shortage.'))+'</div>';
                            }
                            if(result.first_cost_date!==result.supplier_date)html+='<div class="cashflow-result-note">'+__('First customs/VAT payment')+': '+esc(date_label(result.first_cost_date))+'</div>';
                            html+='<div class="cashflow-result-note">'+__('From the first payment through forecast end.')+'</div>';
                        } else {
                            html+='<strong>'+__('No suitable date within this forecast.')+'</strong>';
                        }
                        if(purchase.purchases.length>1)html+='<div class="cashflow-result-note">'+__('Other purchases keep their dates.')+'</div>';
                        html+='</div><div class="cashflow-result-apply"></div></div>';
                        var resultField=dialog.fields_dict[key('suggestion',index)];
                        var useField=dialog.fields_dict[key('apply_suggestion',index)];
                        // Preserve the native button and its handler across result refreshes.
                        if(useField.$wrapper && useField.$wrapper.detach)useField.$wrapper.detach();
                        dialog.set_df_property(key('suggestion',index),'hidden',0);
                        resultField.$wrapper.html(html);
                        if(useField.$wrapper && useField.$wrapper.appendTo && resultField.$wrapper.find)
                            useField.$wrapper.appendTo(resultField.$wrapper.find('.cashflow-result-apply'));
                        dialog.set_df_property(key('apply_suggestion',index),'hidden',valid && Number(result.shift_days)>0?0:1);
                    });
                }).then(function(){busy=false;},function(error){busy=false;throw error;});
        }
        function apply_suggestion(index) {
            if(busy)return;
            var purchase=collect_purchases(dialog.get_values());
            if(!purchase || JSON.stringify(purchase)+'|'+String(report.get_filter_value('maximum_shortage'))!==suggestedInput){frappe.msgprint(__('Payments changed. Suggest dates again.'));return;}
            var result=drafts[index].suggestion;if(!result || !result.first_cost_date)return;
            ['payments','import_charges'].forEach(function(name){
                var grid=dialog.fields_dict[key(name,index)].grid;
                (grid.get_data ? grid.get_data() : grid.df.data).forEach(function(row){if(row.date)row.date=frappe.datetime.add_days(row.date,result.shift_days);});
                grid.refresh();
            });
            return suggestion_action();
        }
        function style_purchase_actions() {
            if(!dialog || !dialog.fields_dict)return;
            Object.keys(dialog.fields_dict).forEach(function(name){
                var field=dialog.fields_dict[name],wrapper=field.$wrapper;
                if(!wrapper || !wrapper.addClass)return;
                if(/^(suggest_date|remove_purchase|add_purchase|clear_purchase)(_|$)/.test(name))wrapper.addClass('cashflow-purchase-action');
                if(/^suggestion(_|$)/.test(name))wrapper.addClass('cashflow-purchase-result');
                if(/^apply_suggestion(_|$)/.test(name))wrapper.addClass('cashflow-purchase-use');
            });
        }
        var fields=[];
        drafts.forEach(function(draft,index){fields=fields.concat(purchase_fields(index));});
        fields=fields.concat([
            {fieldname:'purchase_actions',fieldtype:'Section Break'},
            {fieldname:'add_purchase',fieldtype:'Button',label:__('Add More Purchase'),click:add_purchase},
            {fieldname:'clear_purchase',fieldtype:'Button',label:__('Clear All Purchases'),click:function(){return finish({});}}
        ]);
        dialog=new frappe.ui.Dialog({title:__('Check Purchase'),fields:fields,primary_action_label:__('Check Purchases'),primary_action:function(values){
            if(busy)return;
            var purchase=collect_purchases(values);
            if(purchase)return finish(purchase);
        }});
        dialog.show();
        drafts.forEach(function(draft,index){
            update_import_fields(index);
            var section=dialog.fields_dict && dialog.fields_dict['purchase_section_'+index];
            if(section && section.collapse)section.collapse(index!==0);
        });
        style_purchase_actions();
        if(dialog.$wrapper){
            dialog.$wrapper.find('.modal-dialog').css('max-width','740px');
            dialog.$wrapper.addClass('cashflow-purchase-dialog').prepend('<style>'+
                '.cashflow-purchase-dialog .cashflow-purchase-action{display:inline-block;margin:8px 12px 4px 0;}'+
                '.cashflow-purchase-dialog .cashflow-purchase-result{display:block;width:100%;margin:12px 0 0;font-size:13px;line-height:1.6;}'+
                '.cashflow-purchase-dialog .cashflow-result-box{display:flex;align-items:center;justify-content:space-between;gap:16px;padding:12px 14px;border:1px solid #dce3eb;border-radius:6px;background:#f8fafc;}'+
                '.cashflow-purchase-dialog .cashflow-result-box.is-tolerated{background:#fff9ed;border-color:#ead8aa;}'+
                '.cashflow-purchase-dialog .cashflow-result-box.is-positive{background:#f2f8f4;border-color:#cce2d3;}'+
                '.cashflow-purchase-dialog .cashflow-result-date{margin-bottom:5px;color:#475569;}'+
                '.cashflow-purchase-dialog .cashflow-result-date strong{display:inline;margin-left:6px;font-size:15px;color:#172b4d;}'+
                '.cashflow-purchase-dialog .cashflow-result-status{font-weight:500;color:#36704d;margin-top:3px;}'+
                '.cashflow-purchase-dialog .is-tolerated .cashflow-result-status{color:#855c19;}'+
                '.cashflow-purchase-dialog .cashflow-result-note{font-size:12px;color:#64748b;margin-top:4px;}'+
                '.cashflow-purchase-dialog .cashflow-result-apply{flex-shrink:0;}'+
                '@media(max-width:480px){.cashflow-purchase-dialog .cashflow-result-box{align-items:flex-start;flex-direction:column;gap:8px;}}'+
                '.cashflow-purchase-dialog .cashflow-purchase-use{display:inline-block;vertical-align:middle;margin:0;}'+
                '.cashflow-purchase-dialog .cashflow-purchase-result.hide,.cashflow-purchase-dialog .cashflow-purchase-use.hide{display:none;}'+
                '</style>');
        }
    }

    function show_details(report,key,kind) {
        var row=(report.data || []).find(function(item){return String(item.month || item.date)===key;});if(!row)return;
        var definition=detail_fields.find(function(field){return field[0]===kind;});
        var title=kind==='sales'?__('Expected Sales Receipts'):(definition?__(definition[1]):__('Payment Details'));
        var currency=row.currency;
        var html='<p>'+esc(date_label(key))+'</p>';
        if(kind==='sales') {
            html+='<p style="white-space:pre-line">'+esc(sales_tooltip(report,row))+'</p>';
            var salesDialog=new frappe.ui.Dialog({title:title,fields:[{fieldtype:'HTML',options:html}]});salesDialog.show();return;
        }
        html+='<table class="table table-bordered"><thead><tr><th>'+__('Payment')+'</th><th>'+__('Amount')+'</th><th>'+__('Document / Notes')+'</th></tr></thead><tbody>';
        var items=(row.sources || []).filter(function(item){
            if(kind==='sales')return false;
            if(kind==='other_receipts')return item.category===kind;
            if(kind==='supplier_payments')return item.category===kind || item.category==='proposed_purchase';
            if(payment_fields.indexOf(kind)>=0)return item.category===kind || (kind==='quarterly_vat' && item.category==='vat_settlement');
            if(kind==='payments')return payment_fields.indexOf(item.category)>=0 || item.category==='vat_settlement';
            return true;
        });
        if(items.some(function(item){return item.category==='budget_expenses';})) {
            items=items.filter(function(item){return item.category!=='budget_expenses';});
            items.push({category:'budget_expenses',amount:row.budget_expenses,description:row.month?__('Monthly budget'):__('Daily budget')});
        }
        var vat_items=items.filter(function(item){return item.category==='vat_accrual';});
        items=items.filter(function(item){return item.category!=='vat_accrual';});
        if(!items.length)html+='<tr><td colspan="3">'+__('No entries for this date.')+'</td></tr>';
        items.forEach(function(item){
            var field=detail_fields.find(function(value){return value[0]===item.category;});
            var label=item.category==='proposed_purchase'?__('Proposed Supplier Payment'):(field?__(field[1]):(item.category==='vat_settlement'?__('Quarterly VAT Settlement'):__('VAT Adjustment for Quarter-End')));
            var notes='';
            if(item.doctype && item.name)notes='<a target="_blank" rel="noopener" href="#Form/'+encodeURIComponent(item.doctype)+'/'+encodeURIComponent(item.name)+'">'+esc(item.name)+'</a>';
            var related=Array.isArray(item.related_documents)?item.related_documents.slice():[];
            if(item.related_doctype && item.related_name)related.push({doctype:item.related_doctype,name:item.related_name});
            if(related.length)notes+='<div>'+related.map(function(ref){return '<a target="_blank" rel="noopener" href="#Form/'+encodeURIComponent(ref.doctype)+'/'+encodeURIComponent(ref.name)+'">'+esc(ref.name)+'</a>';}).join(', ')+'</div>';
            var description=item.description || '';
            if(item.scenario) description=item.purchase_number?__('Purchase')+' '+item.purchase_number:(['customs','import_vat'].indexOf(item.category)>=0?__('Proposed purchase'):'');
            if(description && !item.scenario) description=description.replace(/^Scheduled payment; /,'').replace(/; original due \d{4}-\d{2}-\d{2}/g,'');
            if(item.party_type==='Supplier' && (item.supplier_name || item.party))notes+='<div>'+esc(item.supplier_name || item.party)+'</div>';
            if(description)notes+='<div>'+esc(description)+'</div>';
            if(item.workflow_state)notes+='<div class="text-muted">'+esc(item.workflow_state)+'</div>';
            if(item.original_due_date)notes+='<div class="text-muted">'+__('Due')+': '+esc(date_label(item.original_due_date))+'</div>';
            if(item.review_note)notes+='<div>'+esc(short_note(item.review_note))+'</div>';
            html+='<tr><td>'+esc(label)+'</td><td style="white-space:nowrap">'+format_currency(item.amount,currency,3)+'</td><td>'+notes+'</td></tr>';
        });
        html+='</tbody></table>';
        if(vat_items.length) {
            html+='<h5>'+__('VAT Adjustment for Quarter-End')+'</h5><p class="text-muted">'+__('Used to calculate quarter-end VAT. Not a payment today.')+'</p><table class="table table-bordered"><thead><tr><th>'+__('Type')+'</th><th>'+__('Amount')+'</th><th>'+__('Document')+'</th></tr></thead><tbody>';
            vat_items.forEach(function(item){
                var link=item.doctype && item.name?'<a target="_blank" rel="noopener" href="#Form/'+encodeURIComponent(item.doctype)+'/'+encodeURIComponent(item.name)+'">'+esc(item.name)+'</a>':'';
                html+='<tr><td>'+__('VAT Adjustment for Quarter-End')+'<div class="text-muted">'+(Number(item.amount)<0?__('Reduces VAT payable'):__('Increases VAT payable'))+'</div></td><td>'+format_currency(item.amount,currency,3)+'</td><td>'+link+'</td></tr>';
            });
            html+='</tbody></table>';
        }
        var dialog=new frappe.ui.Dialog({title:title,size:'large',fields:[{fieldtype:'HTML',fieldname:'details',options:html}]});dialog.show();
    }

    function saved_overdue_review(report) {
        var snapshot=context_for(report),first=((report.raw_data || {}).result || [])[0] || {};
        var rows=Number((snapshot.base_filters || {}).include_overdue)===1 ? ((snapshot.calculation_inputs || {}).overdue || []) : [];
        var grouped={};
        rows.forEach(function(row){
            var amount=Number(row.amount);
            if (!isFinite(amount) || amount<=0) return;
            var key=JSON.stringify([String(row.date),row.doctype || '',row.name || '',row.category]);
            if (!grouped[key]) grouped[key]=Object.assign({},row,{date:String(row.date),amount:0,related_documents:[],descriptions:[],review_notes:[]});
            var item=grouped[key];
            item.amount=(Math.round(item.amount*1000)+Math.round(amount*1000))/1000;
            if(row.description && item.descriptions.indexOf(row.description)<0)item.descriptions.push(row.description);
            if(row.review_note && item.review_notes.indexOf(row.review_note)<0)item.review_notes.push(row.review_note);
            var related=(row.related_documents || []).slice();
            if(row.related_doctype && row.related_name)related.push({doctype:row.related_doctype,name:row.related_name});
            related.forEach(function(ref){if(!item.related_documents.some(function(existing){return existing.doctype===ref.doctype && existing.name===ref.name;}))item.related_documents.push(ref);});
        });
        var items=Object.keys(grouped).map(function(key){
            var item=grouped[key];item.description=item.descriptions.join(' | ');item.review_note=item.review_notes.join(' ');
            delete item.descriptions;delete item.review_notes;return item;
        }).sort(function(a,b){return [a.date,a.doctype || '',a.name || ''].join('|').localeCompare([b.date,b.doctype || '',b.name || ''].join('|'));});
        var sections=[["pe_supplier", "Supplier payments — PE prepared", "Review the Payment Entry, allocation and payment date."], ["pe_other", "Other Payment Entries (PE)", "Review the Payment Entry and its payment date."], ["gl", "GL Payments", "Review the GL Payment, source link and payment date."], ["jv", "Journal Entries (JV)", "Review the net cash movement, workflow, references and matching notes."], ["supplier_due", "Supplier / PO obligations — payment needs review", "Verify outstanding balances and existing payments before preparing or linking a payment."], ["fixed_due", "Fixed-expense schedules — payment needs review", "Verify each occurrence and link an existing GL Payment if already paid."], ["payroll_due", "Payroll — payment or matching needs review", "Verify salary-period and Payroll Entry payment links; do not repay an already settled salary."], ["vat_due", "Quarterly VAT", "Review unpaid VAT and settlement journals."], ["other_due", "Other obligations", "Verify the source obligation and payment date."]];
        var buckets={};
        items.forEach(function(item){
            var kind=item.doctype,category=item.category;
            var group=kind==='Payment Entry' ? (category==='supplier_payments' || item.party_type==='Supplier' ? 'pe_supplier':'pe_other') :
                kind==='GL Payment' ? 'gl' : kind==='Journal Entry' ? 'jv' :
                kind==='Purchase Invoice' || kind==='Purchase Order' ? 'supplier_due' : kind==='Fixed Expense' ? 'fixed_due' :
                category==='vat_settlement' || category==='quarterly_vat' ? 'vat_due' : category==='payroll' ? 'payroll_due' : 'other_due';
            (buckets[group] || (buckets[group]=[])).push(item);
        });
        var groups=sections.filter(function(section){return buckets[section[0]];}).map(function(section){
            var entries=buckets[section[0]];
            return {id:section[0],title:section[1],action:section[2],items:entries,
                total_amount:entries.reduce(function(total,item){return total+Math.round(item.amount*1000);},0)/1000};
        });
        return {items:items,groups:groups,currency:first.currency,journal_stats:snapshot.journal_stats || {},saved:true,
            forecast_date:snapshot.forecast_date || first.date};
    }

    function show_overdue_review(report, review) {
        var labels = {fixed_expenses: __('Fixed Expense'), payroll: __('Payroll'),
            supplier_payments: __('Supplier Payment'), customs: __('Customs'), import_vat: __('Import VAT'),
            quarterly_vat: __('VAT Settlement'), vat_settlement: __('VAT Settlement'), other_payments: __('Other Payment')};
        var items = review.items || [];
        var html=collapse_styles()+(review.saved ? '<p>'+__('Overdue payments included in this report')+' — '+esc(date_label(review.forecast_date))+'</p>' : '<p>'+__('Review overdue payments. Update dates or complete payment, or include them today.')+'</p>');
        html+='<p>'+__('Check existing payments before paying again.')+'</p><p>'+__('Overdue items')+': '+items.length+'</p>';
        var groups = review.groups || [{id:'legacy',title:__('Overdue items'),action:'',items:items,
            total_amount:items.reduce(function(total,item){return total+Number(item.amount || 0);},0)}];
        function document_link(doctype, name) {
            return '<a target="_blank" rel="noopener" href="#Form/'+encodeURIComponent(doctype)+'/'+encodeURIComponent(name)+'">'+esc(name)+'</a>';
        }
        html += '<div style="max-height:520px;overflow:auto">';
        groups.forEach(function(group){
            html += '<details class="cashflow-review-group" data-group="'+esc(group.id)+'" style="margin:12px 0;border:1px solid #ddd;padding:10px">'+
                collapse_heading('<strong>'+esc(__(group.title))+'</strong> — '+group.items.length+' '+__('items')+' — '+
                format_currency(group.total_amount,review.currency,3))+'<p class="text-muted" style="margin-top:8px">'+esc(__(group.action || ''))+'</p>'+
                '<table class="table table-bordered"><thead><tr><th>'+__('Due Date')+'</th><th>'+__('Purpose')+'</th><th>'+__('Amount')+
                '</th><th>'+__('Document / Workflow')+'</th><th>'+__('Notes')+'</th></tr></thead><tbody>';
            group.items.forEach(function(item){
                var link = item.doctype && item.name ? document_link(item.doctype,item.name) : __('Source needs review');
                var related = (item.related_documents || []).map(function(ref){return document_link(ref.doctype,ref.name);}).join(', ');
                html += '<tr><td>'+esc(item.date)+'</td><td>'+esc(labels[item.category] || item.category)+'</td><td>'+
                    format_currency(item.amount,review.currency,3)+'</td><td>'+link+'<br><span class="text-muted">'+esc(item.workflow_state || item.basis || '')+
                    '</span></td><td>'+esc(item.description);
                if (item.basis) html += '<div class="text-muted">'+esc(item.basis)+'</div>';
                if (related) html += '<div>'+__('Related sources')+': '+related+'</div>';
                if (item.review_note) html += '<div class="text-warning"><strong>'+__('Review')+': </strong>'+esc(short_note(item.review_note))+'</div>';
                html += '</td></tr>';
            });
            html += '</tbody></table></details>';
        });
        var stats = review.journal_stats || {};
        if (stats.internal_or_noncash) html += '<p class="text-muted">'+__('JEs with no net cash effect')+': '+Number(stats.internal_or_noncash)+'</p>';
        html += '</div>';
        var dialog = new frappe.ui.Dialog({title: __('Review Overdue Commitments'), size: 'large',
            fields: [{fieldtype:'HTML',fieldname:'overdue',options:html}],
            primary_action_label: review.saved ? __('Close') : __('Close and Review'), primary_action: function () { dialog.hide(); }});
        dialog.show();
    }

    frappe.query_reports['Cashflow Forecast'] = {
        filters: [
            {fieldname: 'forecast_date', label: __('Forecast Date'), fieldtype: 'Date', read_only: 1, hidden: 1,
                default: frappe.datetime.get_today()},
            {fieldname: 'company', label: __('Company'), fieldtype: 'Link', options: 'Company', reqd: 1,
                default: frappe.defaults.get_user_default('Company'),on_change:company_changed},
            {fieldname:'excluded_accounts',label:__('Exclude Accounts'),fieldtype:'MultiSelectList',default:[],placeholder:__('Exclude Accounts'),
                get_data:function(text){return exclusion_options(frappe.query_report,text);},on_change:account_scope_changed},
            {fieldname: 'end_date', label: __('Forecast Until'), fieldtype: 'Date', reqd: 1,
                default: (Number(frappe.datetime.get_today().slice(0,4))+1)+'-12-31'},
            {fieldname: 'account_scope', fieldtype: 'Data', hidden: 1, default: 'parent-groups-v1'},
            {fieldname:'manual_sales',label:__('Use Average Daily Sales'),fieldtype:'Check',default:0,on_change:function(report){toggle_sales_fields(report);}},
            {fieldname:'average_daily_sales',label:__('Average Daily Sales'),fieldtype:'Currency',precision:3,default:0,description:__('Including VAT.'),depends_on:'eval:doc.manual_sales'},
            {fieldname: 'sales_adjustment', label: __('Sales Change % (+/−)'), fieldtype: 'Float', default: 0,depends_on:'eval:!doc.manual_sales'},
            {fieldname: 'support_amount', label: __('Support Amount'), fieldtype: 'Currency', precision: 3, hidden: 1, default: 0},
            {fieldname: 'support_payments', label: __('Support'), fieldtype: 'Small Text', hidden: 1, default: '[]'},
            {fieldname:'maximum_shortage',label:__('Max Shortage Tolerance'),fieldtype:'Currency',precision:3,default:1000,on_change:function(){}},
            {fieldname: 'minimum_reserve', label: __('Minimum Cash Reserve'), fieldtype: 'Currency', precision: 3, default: 0},
            {fieldname: 'overdue_policy', fieldtype: 'Data', hidden: 1, default: 'review-v1'},
            {fieldname: 'purchase_scenario', fieldtype: 'Small Text', hidden:1, default:'{}'},
            {fieldname:'today_policy',fieldtype:'Data',hidden:1,default:'auto-v1'},
            {fieldname:'payroll_policy',fieldtype:'Data',hidden:1,default:'ledger-v1'},
            {fieldname:'sales_policy',fieldtype:'Data',hidden:1,default:'auto-holidays-v1'},
            {fieldname:'vat_policy',fieldtype:'Data',hidden:1,default:'quarter-v4'},
            {fieldname: 'scenario_policy', fieldtype:'Data', hidden:1, default:'purchase-budget-v4'},
            {fieldname: 'supplier_policy', fieldtype: 'Data', hidden: 1, default: 'installments-v2'},
            {fieldname: 'journal_policy', fieldtype: 'Data', hidden: 1, default: 'pending-v1'},
            {fieldname: 'layout_policy', fieldtype: 'Data', hidden: 1, default: 'compact-v1'},
            {fieldname: 'view', label: __('View'), fieldtype: 'Select', options: 'Daily\nMonthly', default: 'Daily'},
            {fieldname: 'include_overdue', label: __('Include Overdue Commitments'), fieldtype: 'Check', default: 0},
            {fieldname: 'extra_expenses', label: __('Scenario Expenses JSON'), fieldtype: 'Small Text', hidden: 1, default: '[]'}
        ],
        onload: function (report) {
            var excluded=(report.filters || []).find(function(field){return field.df && field.df.fieldname==='excluded_accounts';});
            if(excluded)set_excluded_values(excluded,excluded.get_value ? excluded.get_value() : []);
            toggle_sales_fields(report);
            if (!report._cashflow_export_wrapped && typeof report.export_report==='function') {
                var original_export=report.export_report;
                report.export_report=function(){
                    if(this.report_name==='Cashflow Forecast' && this.raw_data && this.raw_data.purchase_preview)return download_purchase_check(this);
                    return original_export.apply(this,arguments);
                };
                report._cashflow_export_wrapped=true;
            }
            if (!report._cashflow_load_wrapped && typeof report.load_report==='function') {
                var original_load=report.load_report;
                report.load_report=function(){
                    var previous=this._cashflow_pinned_table;
                    if(previous && previous._cashflow_pin_cleanup)previous._cashflow_pin_cleanup();
                    this._cashflow_pinned_table=null;
                    return original_load.apply(this,arguments);
                };
                report._cashflow_load_wrapped=true;
            }
            if (report.page.main && report.page.main.addClass) report.page.main.addClass('cashflow-page');
            if (!report._cashflow_chart_wrapped && typeof report.get_chart_options === 'function') {
                var original_chart_options = report.get_chart_options;
                report.get_chart_options = function () {
                    var options = original_chart_options.apply(this,arguments);
                    if (!options || this.report_name !== 'Cashflow Forecast') return options;
                    return Object.assign({},options,{height:200,
                        axisOptions:Object.assign({},options.axisOptions,{xIsSeries:1,xAxisMode:'tick'}),
                        lineOptions:Object.assign({},options.lineOptions,{hideDots:1}),
                        data:Object.assign({},options.data,{yMarkers:[{label:__('Zero Cash'),value:0}]})});
                };
                report._cashflow_chart_wrapped = true;
            }
            if (!report._cashflow_prepare_wrapped && typeof report.prepare_report_data === 'function') {
                var original_prepare = report.prepare_report_data;
                report.prepare_report_data = function () {
                    var result = original_prepare.apply(this, arguments);
                    if (this.report_name === 'Cashflow Forecast') apply_column_view(this);
                    return result;
                };
                report._cashflow_prepare_wrapped = true;
            }
            // Frappe v12 hardcodes GET in refresh. Change only this report's synchronous
            // request construction to POST; restore frappe.call before any async work.
            if (!report._cashflow_refresh_wrapped) {
                var original_refresh = report.refresh;
                report.refresh = function () {
                    if (this.report_name !== 'Cashflow Forecast') return original_refresh.apply(this, arguments);
                    if (this.page && this.page.main) this.page.main.find('.cashflow-context').remove();
                    var original_call = frappe.call;
                    frappe.call = function (options) {
                        if (options && options.method === 'frappe.desk.query_report.run' &&
                            options.args && options.args.report_name === 'Cashflow Forecast') options.type = 'POST';
                        return original_call.apply(this, arguments);
                    };
                    try { return original_refresh.apply(this, arguments); }
                    finally { frappe.call = original_call; }
                };
                report._cashflow_refresh_wrapped = true;
            }
            if (!report._cashflow_generate_wrapped && typeof report.generate_background_report === 'function') {
                var original_generate = report.generate_background_report;
                report.generate_background_report = function () {
                    if (this.report_name !== 'Cashflow Forecast') return original_generate.apply(this, arguments);
                    var current = this;
                    var filters = current.get_filter_values(true);
                    if (!filters || !filters.company || !filters.end_date) return Promise.resolve();
                    current.toggle_primary_button_disabled(true);
                    return frappe.call({method: 'frappe.desk.query_report.background_enqueue_run', type:'POST',
                        args:{report_name:'Cashflow Forecast',filters:filters}, freeze:true,
                        freeze_message: Number(filters.include_overdue) ? __('Queueing forecast…') : __('Checking unpaid overdue commitments…'),
                        always:function(){ current.toggle_primary_button_disabled(false); }
                    }).then(function(response){
                        var result = response.message || {};
                        update_forecast_end(current,result.end_date_adjustment,true);
                        if (result.blocked) { show_overdue_review(current, result.overdue_review || {}); return; }
                        if (!result.name) return;
                        current.prepared_report_doc_name = result.name;
                        frappe.show_alert({message:__('Report queued. You can track it')+' <a href="#Form/Prepared%20Report/'+
                            encodeURIComponent(result.name)+'">'+__('here')+'</a>',indicator:'orange'},10);
                        current.toggle_nothing_to_show(true);
                    });
                };
                report._cashflow_generate_wrapped = true;
            }
            var purchase_button = report.page.add_inner_button(__('Check Purchase'), function () { check_purchase(report); });
            if (purchase_button && purchase_button.addClass) purchase_button.addClass('btn-primary');
            report.page.add_inner_button(__('Report Notes'),function(){report_notes(report);});
            report.page.add_inner_button(__('Add Support'), function () { edit_expenses(report, true); });
            report.page.add_inner_button(__('Add Extra Expenses'), function () { edit_expenses(report); });
            report.page.add_inner_button(__('Download Scenario'), function () {
                var payload = {report: 'Cashflow Forecast', assumptions: report.get_filter_values()};
                var url = URL.createObjectURL(new Blob([JSON.stringify(payload, null, 2)], {type:'application/json'}));
                var a = document.createElement('a'); a.href = url; a.download = 'cashflow-scenario.json'; a.click();
                setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
            });
            if (report.page.main && report.page.main.find) {
                var labels = report.page.main.find('.page-form .frappe-control .control-label');
                if (labels.removeClass && labels.show) labels.removeClass('hide').show();
            }
            var params = report.get_query_params ? report.get_query_params() : {};
            if (!params.prepared_report_name) {
                (report.filters || []).forEach(function (field) {
                    if (field.df.fieldname === 'forecast_date') field.set_input(frappe.datetime.get_today());
                });
                return apply_default_exclusions(report);
            }
            report._cashflow_defaults_revision=(report._cashflow_defaults_revision || 0)+1;
            report._cashflow_restoring=true;
            return frappe.call({method: method+'get_prepared_filters',
                args: {prepared_report_name: params.prepared_report_name}}).then(function (response) {
                var values = response.message || {};
                (report.filters || []).forEach(function (field) {
                    var name = field.df.fieldname;
                    if(name==='excluded_accounts')set_excluded_values(field,values[name] || []);
                    else if (Object.prototype.hasOwnProperty.call(values, name)) field.set_input(values[name]);
                });
                toggle_sales_fields(report);
            }).then(function(){report._cashflow_restoring=false;},function(error){report._cashflow_restoring=false;throw error;});
        },
        get_datatable_options: function (options) {
            options.disableReorderColumn=false;
            options.headerDropdown=(options.headerDropdown || []).concat([{label:__('Pin / Unpin Column'),
                action:function(column){toggle_pinned_column(this,column);}}]);
            (options.columns || []).forEach(function(column){
                if (column.fieldname === 'date') column.width = Math.max(Number(column.width) || 0,145);
            });
            return options;
        },
        formatter: function (value, row, column, data, default_formatter) {
            var output;
            if (column.fieldname === 'source_details' && data && data.sources && data.sources.length) {
                output = '<a href="#" class="cashflow-details" data-key="'+esc(data.month || data.date)+'">'+
                    __('View')+' '+data.sources.length+' '+__('items')+'</a>';
            }
            if (output === undefined) output = default_formatter(value, row, column, data);
            if (column.fieldname === 'date' && data && /^\d{4}-\d{2}-\d{2}$/.test(String(data.date || ''))) {
                var parts = data.date.split('-').map(Number);
                var weekday = new Date(Date.UTC(parts[0],parts[1]-1,parts[2])).getUTCDay();
                output += ' '+esc(__(['Sun','Mon','Tue','Wed','Thu','Fri','Sat'][weekday]));
            }

            if (data && (['total_payments','expected_receipts','other_receipts'].indexOf(column.fieldname) !== -1 || payment_fields.indexOf(column.fieldname)>=0)) {
                var detail_kind = column.fieldname === 'expected_receipts' ? 'sales' : (column.fieldname === 'total_payments' ? 'payments' : column.fieldname);
                var tooltip = column.fieldname === 'expected_receipts' ? ' title="'+esc(sales_tooltip(frappe.query_report,data))+'"' : '';
                output = '<a href="#" class="cashflow-details" data-kind="'+detail_kind+'" data-key="'+esc(data.month || data.date)+'"'+tooltip+'>'+output+'</a>';
            }
            if(data) {
                var negative=Number(data.closing_cash)<0, purchase=data.scenario_arrival || data.scenario_supplier;
                var classes=[];
                if(negative)classes.push('cashflow-negative-cell');
                var manual = column.fieldname === 'other_receipts' && (data.sources || []).some(function(item){return item.manual_support && Number(item.amount)>0;}) ||
                    column.fieldname === 'extra_expenses' && Number(data.extra_expenses)>0;
                if(manual)classes.push('cashflow-manual-cell');
                if(purchase)classes.push('cashflow-purchase-cell',data.scenario_arrival?'cashflow-scenario-arrival':'cashflow-scenario-supplier');
                var style=column.fieldname==='closing_cash' && negative?'color:#b42318;font-weight:700;':'';
                if(!negative && column.fieldname==='closing_cash' && data.below_reserve)style='color:#a15c00;font-weight:700;';
                if(classes.length || style)return '<span class="'+classes.join(' ')+'" style="display:block;'+style+'">'+output+'</span>';
            }
            return output;
        },
        after_datatable_render: function (datatable) {
            var report = frappe.query_report;
            var table=datatable || report.datatable;
            if(report._cashflow_pinned_table && report._cashflow_pinned_table!==table && report._cashflow_pinned_table._cashflow_pin_cleanup)report._cashflow_pinned_table._cashflow_pin_cleanup();
            report._cashflow_pinned_table=table;
            pin_columns(table);
            report.page.main.off('click.cashflow', '.cashflow-details, .cashflow-opening-balance, .cashflow-overdue-total, .cashflow-manual-input').on('click.cashflow', '.cashflow-details, .cashflow-opening-balance, .cashflow-overdue-total, .cashflow-manual-input', function (event) {
                event.preventDefault();
                if (this.classList && this.classList.contains('cashflow-manual-input')) {manual_input_details(report,$(this).attr('data-input-kind'));return;}
                if (this.classList && this.classList.contains('cashflow-opening-balance')) {opening_balance_details(report);return;}
                if (this.classList && this.classList.contains('cashflow-overdue-total')) {show_overdue_review(report,saved_overdue_review(report));return;}
                show_details(report, String($(this).attr('data-key')), $(this).attr('data-kind'));
            });
            var box = report.page.main.find('.cashflow-context');
            if (!box.length) box = $('<div class="cashflow-context" style="padding:6px 0"></div>').insertAfter(report.page.main.find('.page-form'));
            var raw = report.raw_data || {};
            var first = raw.result && raw.result[0];
            var snapshot = first && first._cashflow_context;
            if (snapshot) {
                raw.message = snapshot.message;
                raw.report_summary = snapshot.report_summary;
                if(snapshot.forecast_end_date)update_forecast_end(report,{end_date:snapshot.forecast_end_date},false);

            }
            if (!raw.chart) {
                raw.chart = snapshot && snapshot.chart || (raw.result && raw.result.length ? {
                    data:{labels:raw.result.map(function(row){return String(row.month || row.date);}),
                        datasets:[{name:__('Closing Cash'),values:raw.result.map(function(row){return Number(row.closing_cash);})}],
                        yMarkers:[{label:__('Zero Cash'),value:0}]},type:'line',height:200,colors:['#2563eb']
                } : null);
                if (raw.chart && typeof report.render_chart === 'function') report.render_chart(report.get_chart_options(raw));
            }
            // V12 reuses the first download callback across rebuilt snapshots.
            if (raw.doc && raw.doc.name) {
                report.page.inner_toolbar.find('button[data-label="'+encodeURIComponent(__('Download Report'))+'"]')
                    .off('click').on('click', function () {
                        if (raw.purchase_preview) {download_purchase_check(report);} else window.open(frappe.urllib.get_full_url('/api/method/frappe.core.doctype.prepared_report.prepared_report.download_attachment?dn='+encodeURIComponent(raw.doc.name)));
                    });
            }
            var summaries = (raw.report_summary || []).map(function(card){return Object.assign({},card);});
            // Correct older saved daily comparisons without a new accounting query.
            var comparison=summaries.find(function(card){return card.label===__('Lowest Cash Without Purchase');});
            var daily=raw.result || [];
            if(comparison && daily.length && daily.every(function(row){return !row.month && row.baseline_closing_cash!==undefined && isFinite(Number(row.baseline_closing_cash));})) {
                var lowest=daily.reduce(function(low,row){return Number(row.baseline_closing_cash)<Number(low.baseline_closing_cash)?row:low;});
                comparison.value=Number(lowest.baseline_closing_cash);comparison.date=lowest.date;
            }
            var get_card = function(label){return summaries.find(function(card){return card.label === __(label);});};
            var opening = get_card('Opening Available Cash');
            if (!opening && first) summaries.unshift({label:__('Opening Available Cash'),value:first.opening_cash,datatype:'Currency',currency:first.currency});
            var low_date = get_card('Lowest Balance Date');
            var date_text = function(value){
                return /^\d{4}-\d{2}-\d{2}$/.test(String(value)) ? String(value).split('-').reverse().join('-') : String(value || '');
            };
            var cards = summaries.filter(function(card){
                return [__('Lowest Balance Date'),__('Coverage'),__('Actual Sales Today (Reference)'),__('Lowest Cash With Purchase')].indexOf(card.label)<0;
            }).map(function(card){
                var label = card.label === __('Lowest Balance') ? __('Lowest Closing Cash') : (card.label === __('Ending Balance') ? __('Ending Cash') : card.label);
                var value = card.datatype === 'Currency' ? format_currency(card.value,card.currency,3) : esc(date_text(card.value));
                if (card.label === __('Opening Available Cash')) {
                    value='<button type="button" class="cashflow-opening-balance" title="'+esc(__('View account balances'))+'" aria-label="'+esc(__('View account balances'))+'">'+value+'</button>';
                }
                var tooltip=card.label===__('Lowest Balance') ? __('Across the whole forecast, including added purchases.') :
                    (card.label===__('Lowest Cash Without Purchase') ? __('Across the whole forecast, excluding added purchases. Support and extra expenses stay included.') : '');
                var note = card.label === __('Lowest Balance') && low_date ? '<small>'+__('On')+' '+esc(date_text(low_date.value))+'</small>' : '';
                if(card.label===__('Lowest Cash Without Purchase') && card.date)note='<small>'+__('On')+' '+esc(date_text(card.date))+'</small>';
                if (card.label === __('Opening Available Cash') && snapshot &&
                    Number((snapshot.base_filters || {}).include_overdue) === 1) {
                    var overdue = ((snapshot.calculation_inputs || {}).overdue || []).reduce(function(total,item){
                        var amount = Number(item.amount);
                        return total + (isFinite(amount) && amount > 0 ? Math.round(amount*1000) : 0);
                    },0);
                    if (overdue > 0) {
                        note += '<small><button type="button" class="cashflow-overdue-total" title="'+esc(__('Review overdue payments'))+'">'+
                            __('Overdue')+': <b>'+format_currency(overdue/1000,card.currency,3)+'</b></button></small>';
                    }
                }
                var risk = card.indicator === 'Red' || (card.datatype === 'Currency' && Number(card.value)<0);
                return '<div class="cashflow-card'+(risk ? ' is-risk' : '')+'"><div class="cashflow-card-label"'+(tooltip?' title="'+esc(tooltip)+'"':'')+'>'+esc(label)+'</div><strong>'+value+'</strong>'+note+'</div>';
            }).join('');
            var reserve = reserve_for(report);
            if (reserve) cards += '<div class="cashflow-card"><div class="cashflow-card-label">'+__('Minimum Cash Reserve')+'</div><strong>'+format_currency(reserve,first && first.currency,3)+'</strong></div>';
            var css = '<style>'+
                '.cashflow-summary{display:grid;grid-template-columns:repeat(auto-fit,minmax(175px,1fr));gap:8px;margin:4px 0 6px;align-items:stretch;}'+
                '.cashflow-card{background:#fff;border:1px solid #e2e8f0;border-radius:5px;padding:8px 12px;min-width:0;}'+
                '.cashflow-card.is-risk{border-top:3px solid #d66b6b;background:#fffafa;}'+
                '.cashflow-card-label{font-size:12px;color:#64748b;margin-bottom:3px;} .cashflow-card strong{display:block;font-size:15px;line-height:1.3;color:#172b4d;}'+
                '.cashflow-card small{display:block;color:#64748b;margin-top:2px;}'+
                '.cashflow-overdue-total{background:none;border:0;padding:0;font:inherit;color:#b42318;text-align:left;cursor:pointer;}'+
                '.cashflow-overdue-total:hover{text-decoration:underline;}'+
                '.cashflow-opening-balance{background:none;border:0;padding:0;color:inherit;font:inherit;text-align:left;cursor:pointer;}'+
                '.cashflow-opening-balance:hover{text-decoration:underline;}'+


                '.cashflow-manual-inputs{display:flex;flex-wrap:wrap;gap:6px;margin:4px 0 6px;}'+
                '.cashflow-manual-input{background:#fff9e5;border:1px solid #eadfb9;border-radius:4px;padding:3px 8px;font-size:12px;color:#57481e;cursor:pointer;}'+
                '.cashflow-manual-input:hover{background:#fff4cc;}'+
                '.cashflow-page .dt-row:has(.cashflow-negative-cell) .dt-cell{background:#fff4f4!important;}'+
                '.cashflow-page .cashflow-negative-cell a{color:inherit;}'+
                '.cashflow-page .cashflow-selected-row .dt-cell{background:#edf4ff!important;box-shadow:inset 0 1px #9bbcf2,inset 0 -1px #9bbcf2;}'+
                '.cashflow-page .dt-row:has(.cashflow-purchase-cell) .dt-cell{background:#fff4cc!important;}'+
                '.cashflow-page .dt-row .dt-cell:has(.cashflow-manual-cell){background:#fff4cc!important;}'+
                '</style>';
            box.html(css+'<div class="cashflow-summary">'+cards+'</div>'+manual_input_strip(report,first && first.currency));

        }
    };
}());
