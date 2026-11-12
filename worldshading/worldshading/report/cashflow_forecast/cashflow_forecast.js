/* Cashflow Forecast — temporary scenarios; no accounting transactions are created. */
(function () {
    'use strict';
    var method = 'worldshading.worldshading.report.cashflow_forecast.cashflow_forecast.';
    var esc = function (value) { return frappe.utils.escape_html(String(value === undefined || value === null ? '' : value)); };

    var detail_fields = [['opening_cash','Opening Cash'],['expected_receipts','Expected Sales Receipts'],
        ['other_receipts','Other Incoming'],['fixed_expenses','Fixed Expenses'],['payroll','Payroll'],
        ['supplier_payments','Supplier Payments'],['customs','Customs'],['import_vat','Import VAT'],
        ['quarterly_vat','Quarterly VAT Settlement'],['extra_expenses','Extra Expenses'],
        ['budget_expenses','Budget Expenses'],['proposed_purchase','Proposed Purchase'],
        ['baseline_closing_cash','Closing Without Purchase'],['purchase_impact','Purchase Impact'],
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
        if (!rows.length) return;
        var saved = report.raw_data.columns || [];
        var has_purchase = rows.some(function(row) {
            return Number(row.proposed_purchase || 0) !== 0 || (row.sources || []).some(function(event) {return !!event.scenario;});
        });
        var date_field = Object.prototype.hasOwnProperty.call(rows[0],'month') ? 'month' : 'date';
        var columns = [{fieldname:date_field,label:__(date_field === 'month' ? 'Month' : 'Date'),
            fieldtype:date_field === 'month' ? 'Data' : 'Date',width:110}];
        detail_fields.forEach(function(definition) {
            var name = definition[0];
            if (!Object.prototype.hasOwnProperty.call(rows[0],name)) return;
            var original = saved.find(function(col){return col.fieldname === name;}) || {};
            columns.push(Object.assign({},original,{fieldname:name,label:__(definition[1]),fieldtype:'Currency',
                options:'currency',precision:3,width:name === 'expected_receipts' ? 180 : (original.width || 145),
                hidden:(!has_purchase && ['proposed_purchase','baseline_closing_cash','purchase_impact'].indexOf(name)>=0) ||
                    (name === 'available_above_reserve' && !reserve_for(report))}));
        });
        columns.push({fieldname:'source_details',label:__('Source Details'),fieldtype:'Data',width:150});
        columns.push({fieldname:'currency',label:__('Currency'),fieldtype:'Link',options:'Currency',hidden:1});
        report.columns = report.prepare_columns(columns);
        report.raw_data.columns = columns;
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

    // Same body-sticky/header-translation approach as Purchase Plan.
    function pin_columns(datatable) {
        var wrapper=datatable && datatable.wrapper,body=datatable && datatable.bodyScrollable;
        if(!wrapper || !body || !wrapper.querySelectorAll || typeof window==='undefined')return;
        if(datatable._cashflow_pin_cleanup)datatable._cashflow_pin_cleanup();
        var leading=(datatable.options && datatable.options.checkboxColumn?1:0)+(datatable.options && datatable.options.serialNoColumn===false?0:1);
        var count=leading+2,frame=null,selected=null,resizing=false;
        wrapper.classList.remove('cashflow-pins-2','cashflow-pins-3','cashflow-pins-4');
        wrapper.classList.add('cashflow-sticky-columns','cashflow-pins-'+count);
        function update() {
            frame=null;
            var left=0;
            for(var index=0;index<count;index++) {
                var header=wrapper.querySelector('.dt-row-header .dt-cell--col-'+index);
                wrapper.style.setProperty('--cashflow-left-'+index,left+'px');
                left+=header && header.getBoundingClientRect().width || (index<leading?50:(index===leading?110:145));
                wrapper.querySelectorAll('.dt-header .dt-cell--col-'+index+', .dt-footer .dt-cell--col-'+index).forEach(function(cell){
                    cell.style.transform='translateX('+body.scrollLeft+'px)';
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
            selected=index;queue();
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
        datatable._cashflow_pin_refresh=function(){selected=null;queue();};
        if(!datatable._cashflow_pin_events && datatable.on) {
            datatable._cashflow_pin_events=true;
            ['onSortColumn','onSwitchColumn','onRemoveColumn'].forEach(function(name){datatable.on(name,function(){if(datatable._cashflow_pin_refresh)datatable._cashflow_pin_refresh();});});
        }
        if(datatable.columnmanager && datatable.columnmanager.sortable)datatable.columnmanager.sortable.option('disabled',true);
        datatable._cashflow_pin_cleanup=function(){
            if(frame!==null)window.cancelAnimationFrame(frame);
            wrapper.classList.remove('cashflow-sticky-columns','cashflow-pins-2','cashflow-pins-3','cashflow-pins-4');
            for(var i=0;i<count;i++)wrapper.querySelectorAll('.dt-header .dt-cell--col-'+i+', .dt-footer .dt-cell--col-'+i).forEach(function(cell){cell.style.transform='';});
            if(observer)observer.disconnect();if(resizeObserver)resizeObserver.disconnect();
            datatable._cashflow_pin_refresh=null;
            wrapper.removeEventListener('click',select);wrapper.removeEventListener('mousedown',start_resize);wrapper.removeEventListener('dblclick',queue);
            body.removeEventListener('scroll',scroll);window.removeEventListener('resize',queue);document.removeEventListener('mouseup',finish_resize);
        };
        if(!document.getElementById('cashflow-sticky-style')) {
            var style=document.createElement('style');style.id='cashflow-sticky-style';var css='';
            [2,3,4].forEach(function(total){for(var i=0;i<total;i++){
                var cell='.cashflow-sticky-columns.cashflow-pins-'+total+' .dt-cell--col-'+i;
                css+=cell+'{position:sticky;left:var(--cashflow-left-'+i+');z-index:3;background:#fff;}';
                css+='.cashflow-sticky-columns.cashflow-pins-'+total+' .dt-header .dt-cell--col-'+i+','+
                    '.cashflow-sticky-columns.cashflow-pins-'+total+' .dt-footer .dt-cell--col-'+i+
                    '{position:relative;left:auto;z-index:30!important;background:#f7fafc!important;isolation:isolate;}';
            }});
            [2,3,4].forEach(function(total){
                var edge='.cashflow-sticky-columns.cashflow-pins-'+total+' .dt-cell--col-'+(total-1);
                css+=edge+'{box-shadow:2px 0 2px rgba(0,0,0,.08);}';
                css+=edge+'::after{content:"";position:absolute;right:0;top:0;bottom:0;width:1px;background:#cbd5e1;z-index:5;pointer-events:none;}';
            });
            css+='.cashflow-sticky-columns .dt-dropdown__list{z-index:60!important;}';
            style.textContent=css;document.head.appendChild(style);
        }
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
    function date_label(value) {
        return /^\d{4}-\d{2}-\d{2}$/.test(String(value)) ? String(value).split('-').reverse().join('-') : String(value || '');
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

    function opening_balance_details(report) {
        var raw=report.raw_data || {},snapshot=context_for(report),first=(raw.result || [])[0] || {};
        var accounts=opening_accounts(snapshot,snapshot.message || raw.message || '');
        var html='<div style="max-height:65vh;overflow:auto">';
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
        html+='</div>';
        var dialog=new frappe.ui.Dialog({title:__('Opening Cash'),size:'large',fields:[{fieldtype:'HTML',options:html}]});dialog.show();
    }

    function report_notes(report) {
        var raw=report.raw_data || {},snapshot=context_for(report),rows=raw.result || [],first=rows[0] || {};
        var message=snapshot.message || raw.message || '';
        var accounts=opening_accounts(snapshot,message);
        var warnings=snapshot.warnings || (message.match(/<li[^>]*>[\s\S]*?<\/li>/gi) || []).map(plain_text);
        var summary=snapshot.report_summary || raw.report_summary || [];
        var actual=summary.find(function(card){return card.label === __('Actual Sales Today (Reference)');});
        var html='<div style="font-size:13px;line-height:1.6;color:#334155;max-height:65vh;overflow:auto">';
        html+='<table class="table table-condensed"><tbody><tr><td>'+__('Forecast Date')+'</td><td>'+esc(date_label(snapshot.forecast_date || first.date))+'</td></tr>';
        if(snapshot.manual_sales) {
            html+='<tr><td>'+__('Average Daily Sales')+'</td><td>'+format_currency(snapshot.average_daily_sales || 0,first.currency,3)+'</td></tr>';
            html+='<tr><td>'+__('Holiday List')+'</td><td>'+esc(snapshot.holiday_list || __('None'))+'</td></tr>';
        }
        if(!snapshot.manual_sales && snapshot.sales_adjustment!==undefined) html+='<tr><td>'+__('Sales Change')+'</td><td>'+esc(Number(snapshot.sales_adjustment))+'%</td></tr>';
        if(snapshot.support_amount!==undefined) html+='<tr><td>'+__('Support')+'</td><td>'+format_currency(snapshot.support_amount,first.currency,3)+'</td></tr>';
        if(actual) html+='<tr><td>'+__('Actual Sales Today')+'</td><td>'+(actual.datatype==='Currency'?format_currency(actual.value,actual.currency,3):esc(actual.value))+'</td></tr>';
        html+='</tbody></table>';
        if(accounts.length) {
            html+='<details><summary>'+__('Opening Account Balances')+'</summary><table class="table table-condensed"><thead><tr><th>'+__('Account')+'</th><th class="text-right">'+__('Balance')+'</th></tr></thead><tbody>';
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
        if(!warnings.length && !accounts.length && message) html+='<p>'+esc(plain_text(message))+'</p>';
        html+='</div>';
        var dialog=new frappe.ui.Dialog({title:__('Report Notes'),size:'large',fields:[{fieldtype:'HTML',options:html}]});dialog.show();
    }

    function scenarios(report) {
        try { return JSON.parse(report.get_filter_value('extra_expenses') || '[]'); }
        catch (e) { return []; }
    }

    function edit_expenses(report) {
        var dialog = new frappe.ui.Dialog({
            title: __('Extra Expenses'), size: 'large',
            fields: [
                {fieldtype: 'HTML', options: '<p>'+__('Add expenses not already included.')+'</p>'},
                {fieldname: 'expenses', fieldtype: 'Table', label: __('Extra Expenses'),
                    cannot_add_rows: false, in_place_edit: true, data: scenarios(report),
                    fields: [
                        {fieldname: 'date', fieldtype: 'Date', label: __('Payment Date'), reqd: 1, in_list_view: 1},
                        {fieldname: 'amount', fieldtype: 'Currency', precision: 3, label: __('Amount'), reqd: 1, in_list_view: 1},
                        {fieldname: 'description', fieldtype: 'Data', label: __('Description'), reqd: 1, in_list_view: 1}
                    ]}
            ],
            primary_action_label: __('Apply'),
            primary_action: function (values) {
                var data = values.expenses || [];
                var valid = data.every(function (row) {
                    return row.date >= frappe.datetime.get_today() && row.date <= report.get_filter_value('end_date') &&
                        isFinite(Number(row.amount)) && Number(row.amount) >= 0 && String(row.description || '').trim();
                });
                if (!valid) { frappe.msgprint(__('Each row needs a date within the forecast period, a nonnegative amount and a description.')); return; }
                report.set_filter_value('extra_expenses', JSON.stringify(data.map(function (row) {
                    return {date: row.date, amount: row.amount, description: row.description};
                })));
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
        if (saved.schema===4 && Array.isArray(saved.purchases) && saved.purchases.length) {
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
        function key(name,index){return index?name+'_'+index:name;}
        function update_import_fields(index) {
            if(!dialog)return;
            var enabled=Number(dialog.get_value(key('international',index)))===1;
            dialog.set_df_property(key('eta_date',index),'hidden',enabled?0:1);
            dialog.set_df_property(key('eta_date',index),'reqd',enabled?1:0);
            dialog.set_df_property(key('import_note',index),'hidden',enabled?0:1);
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
                {fieldname:key('international',index),fieldtype:'Check',label:__('International Purchase'),default:draft.international || 0,onchange:function(){update_import_fields(index);}},
                {fieldname:key('eta_date',index),fieldtype:'Date',label:__('Arrival Date (ETA)'),default:draft.eta_date,hidden:!Number(draft.international)},
                {fieldname:key('import_note',index),fieldtype:'HTML',options:'<p class="text-muted">'+__('Customs and import VAT are paid on ETA, separately from supplier payments.')+'</p>',hidden:!Number(draft.international)},
                {fieldname:key('remove_purchase',index),fieldtype:'Button',label:__('Remove Purchase'),click:function(){
                    if(busy)return;
                    drafts[index].removed=true;
                    dialog.set_df_property(key('eta_date',index),'reqd',0);
                    var section=dialog.fields_dict['purchase_section_'+index];section.df.hidden=1;section.refresh();
                    renumber();
                }}
            ];
        }
        function add_purchase() {
            if(busy)return;
            if(drafts.filter(function(draft){return !draft.removed;}).length>=20){frappe.msgprint(__('Maximum 20 purchases.'));return;}
            drafts.forEach(function(draft,index){
                var section=dialog.fields_dict['purchase_section_'+index];if(section && section.collapse)section.collapse(true);
            });
            var index=drafts.length;
            drafts.push({payments:[{date:frappe.datetime.get_today(),amount:0}],international:0});
            dialog.add_fields(purchase_fields(index));update_import_fields(index);renumber();
            var section=dialog.fields_dict['purchase_section_'+index];if(section.collapse)section.collapse(false);
            // Keep Add More below the appended purchase, without recreating any grids.
            var actions=dialog.fields_dict.purchase_actions;
            if(actions && actions.wrapper)actions.wrapper.appendTo(dialog.body);
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
            var purchases=[];
            for(var index=0;index<drafts.length;index++) {
                if(drafts[index].removed)continue;
                var rows=(values[key('payments',index)] || []).map(function(row){return {date:row.date,amount:row.amount};});
                var international=Number(values[key('international',index)] || 0),eta=values[key('eta_date',index)];
                // Ignore untouched extra sections; partially entered payments still require correction.
                if(rows.every(function(row){return !Number(row.amount || 0);}) && !international && !eta)continue;
                if(!rows.length || rows.some(function(row){return !row.date || !isFinite(Number(row.amount)) || Number(row.amount)<=0;})) {
                    frappe.msgprint(__('Enter a date and positive amount for every payment in Purchase')+' '+(purchases.length+1));return;
                }
                if(international && !eta){frappe.msgprint(__('Enter the arrival date for Purchase')+' '+(purchases.length+1));return;}
                purchases.push({payments:rows,international:international,eta_date:eta});
            }
            if(!purchases.length){frappe.msgprint(__('Add a supplier payment, or use Clear All Purchases.'));return;}
            return finish({schema:4,purchases:purchases});
        }});
        dialog.show();
        drafts.forEach(function(draft,index){
            update_import_fields(index);
            var section=dialog.fields_dict && dialog.fields_dict['purchase_section_'+index];
            if(section && section.collapse)section.collapse(index!==0);
        });
        if(dialog.$wrapper)dialog.$wrapper.find('.modal-dialog').css('max-width','740px');
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
        if(kind==='proposed_purchase' && row.baseline_closing_cash!==undefined) html+='<tr><td>'+__('Cash Without Purchase')+'</td><td>'+format_currency(row.baseline_closing_cash,currency,3)+'</td><td>'+__('Difference')+': '+format_currency(row.purchase_impact,currency,3)+'</td></tr>';
        var items=(row.sources || []).filter(function(item){
            if(kind==='sales')return false;
            if(kind==='other_receipts')return item.category===kind;
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
            var label=field?__(field[1]):(item.category==='vat_settlement'?__('Quarterly VAT Settlement'):__('VAT Adjustment for Quarter-End'));
            var notes='';
            if(item.doctype && item.name)notes='<a target="_blank" rel="noopener" href="#Form/'+encodeURIComponent(item.doctype)+'/'+encodeURIComponent(item.name)+'">'+esc(item.name)+'</a>';
            var related=Array.isArray(item.related_documents)?item.related_documents.slice():[];
            if(item.related_doctype && item.related_name)related.push({doctype:item.related_doctype,name:item.related_name});
            if(related.length)notes+='<div>'+related.map(function(ref){return '<a target="_blank" rel="noopener" href="#Form/'+encodeURIComponent(ref.doctype)+'/'+encodeURIComponent(ref.name)+'">'+esc(ref.name)+'</a>';}).join(', ')+'</div>';
            var description=item.description || '';
            if(item.scenario) description=item.purchase_number?__('Purchase')+' '+item.purchase_number:(['customs','import_vat'].indexOf(item.category)>=0?__('Proposed purchase'):'');
            if(description && !item.scenario) description=description.replace(/^Scheduled payment; /,'').replace(/; original due \d{4}-\d{2}-\d{2}/g,'');
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
        var html=review.saved ? '<p>'+__('Overdue payments included in this report')+' — '+esc(date_label(review.forecast_date))+'</p>' : '<p>'+__('Review overdue payments. Update dates or complete payment, or include them today.')+'</p>';
        html+='<p>'+__('Check existing payments before paying again.')+'</p><p>'+__('Overdue items')+': '+items.length+'</p>';
        var groups = review.groups || [{id:'legacy',title:__('Overdue items'),action:'',items:items,
            total_amount:items.reduce(function(total,item){return total+Number(item.amount || 0);},0)}];
        function document_link(doctype, name) {
            return '<a target="_blank" rel="noopener" href="#Form/'+encodeURIComponent(doctype)+'/'+encodeURIComponent(name)+'">'+esc(name)+'</a>';
        }
        html += '<div style="max-height:520px;overflow:auto">';
        groups.forEach(function(group){
            html += '<details open class="cashflow-review-group" data-group="'+esc(group.id)+'" style="margin:12px 0;border:1px solid #ddd;padding:10px">'+
                '<summary><strong>'+esc(__(group.title))+'</strong> — '+group.items.length+' '+__('items')+' — '+
                format_currency(group.total_amount,review.currency,3)+'</summary><p class="text-muted" style="margin-top:8px">'+esc(__(group.action || ''))+'</p>'+
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
                default: frappe.defaults.get_user_default('Company')},
            {fieldname: 'end_date', label: __('Forecast Until'), fieldtype: 'Date', reqd: 1,
                default: frappe.datetime.add_months(frappe.datetime.get_today(), 3)},
            {fieldname: 'account_scope', fieldtype: 'Data', hidden: 1, default: 'parent-groups-v1'},
            {fieldname:'manual_sales',label:__('Use Average Daily Sales'),fieldtype:'Check',default:0,on_change:function(report){toggle_sales_fields(report);}},
            {fieldname:'average_daily_sales',label:__('Average Daily Sales'),fieldtype:'Currency',precision:3,default:0,description:__('Including VAT.'),depends_on:'eval:doc.manual_sales'},
            {fieldname: 'sales_adjustment', label: __('Sales Change % (+/−)'), fieldtype: 'Float', default: 0,depends_on:'eval:!doc.manual_sales'},
            {fieldname: 'support_amount', label: __('Support Amount'), fieldtype: 'Currency', precision: 3, default: 0},
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
                return Promise.resolve();
            }
            return frappe.call({method: method+'get_prepared_filters',
                args: {prepared_report_name: params.prepared_report_name}}).then(function (response) {
                var values = response.message || {};
                (report.filters || []).forEach(function (field) {
                    var name = field.df.fieldname;
                    if (Object.prototype.hasOwnProperty.call(values, name)) field.set_input(values[name]);
                });
                toggle_sales_fields(report);
            });
        },
        get_datatable_options: function (options) {
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
            report.page.main.off('click.cashflow', '.cashflow-details, .cashflow-opening-balance, .cashflow-overdue-total').on('click.cashflow', '.cashflow-details, .cashflow-opening-balance, .cashflow-overdue-total', function (event) {
                event.preventDefault();
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
            var summaries = (raw.report_summary || []).slice();
            var get_card = function(label){return summaries.find(function(card){return card.label === __(label);});};
            var opening = get_card('Opening Available Cash');
            if (!opening && first) summaries.unshift({label:__('Opening Available Cash'),value:first.opening_cash,datatype:'Currency',currency:first.currency});
            var low_date = get_card('Lowest Balance Date');
            var date_text = function(value){
                return /^\d{4}-\d{2}-\d{2}$/.test(String(value)) ? String(value).split('-').reverse().join('-') : String(value || '');
            };
            var cards = summaries.filter(function(card){
                return [__('Lowest Balance Date'),__('Coverage'),__('Actual Sales Today (Reference)')].indexOf(card.label)<0;
            }).map(function(card){
                var label = card.label === __('Lowest Balance') ? __('Lowest Projected Cash') : (card.label === __('Ending Balance') ? __('Ending Cash') : card.label);
                var value = card.datatype === 'Currency' ? format_currency(card.value,card.currency,3) : esc(date_text(card.value));
                if (card.label === __('Opening Available Cash')) {
                    value='<button type="button" class="cashflow-opening-balance" title="'+esc(__('View account balances'))+'" aria-label="'+esc(__('View account balances'))+'">'+value+'</button>';
                }
                var note = card.label === __('Lowest Balance') && low_date ? '<small>'+__('On')+' '+esc(date_text(low_date.value))+'</small>' : '';
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
                return '<div class="cashflow-card'+(risk ? ' is-risk' : '')+'"><div class="cashflow-card-label">'+esc(label)+'</div><strong>'+value+'</strong>'+note+'</div>';
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


                '.cashflow-page .dt-row:has(.cashflow-negative-cell) .dt-cell{background:#fff4f4!important;}'+
                '.cashflow-page .cashflow-negative-cell a{color:inherit;}'+
                '.cashflow-page .cashflow-selected-row .dt-cell{background:#edf4ff!important;box-shadow:inset 0 1px #9bbcf2,inset 0 -1px #9bbcf2;}'+
                '.cashflow-page .dt-row:has(.cashflow-purchase-cell) .dt-cell{background:#fff4cc!important;}'+
                '</style>';
            box.html(css+'<div class="cashflow-summary">'+cards+'</div>');

        }
    };
}());
