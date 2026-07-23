// Copyright (c) 2026, Hilal Habeeb and contributors
// For license information, please see license.txt
//
// Work Estimate — Type-driven Sales Order work estimate (Phase B: input UI).
// The existing "Production Estimate" popup is intentionally left untouched.

frappe.pages['work-estimate'].on_page_load = function (wrapper) {
	var page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __('Work Estimate'),
		single_column: true
	});
	wrapper.work_estimate = new WorkEstimate(page);
};

frappe.pages['work-estimate'].on_page_show = function (wrapper) {
	var sales_order = (frappe.get_route() || [])[1];
	if (wrapper.work_estimate) {
		wrapper.work_estimate.load(sales_order);
	}
};

var WE_SIZES = ['Small', 'Medium', 'Big'];

class WorkEstimate {
	constructor(page) {
		this.page = page;
		this.sales_order = null;
		this.state = null;
		this.inject_styles();
		this.setup_layout();
	}

	inject_styles() {
		if (document.getElementById('work-estimate-styles')) return;
		var css = [
			'.we-wrap { max-width: 1080px; margin: 0 auto; padding: 10px 0 60px; font-size: 13px; }',
			'.we-header { margin-bottom: 6px; }',
			'.we-section { margin-top: 26px; }',
			'.we-title { margin: 0 0 8px; font-size: 12px; font-weight: 600; text-transform: uppercase; letter-spacing: .5px; color: var(--text-muted,#8d99a6); }',
			'.we-table { width: 100%; border-collapse: collapse; font-size: 13px; table-layout: fixed; }',
			'.we-table th, .we-table td { border: 1px solid var(--border-color,#d1d8dd); padding: 8px 12px; vertical-align: middle; overflow: hidden; text-overflow: ellipsis; }',
			'.we-table th { background: var(--bg-light-gray,#f7f7f7); font-weight: 600; white-space: nowrap; }',
			'.we-num { text-align: right; }',
			'.we-input { width: 100%; border: 1px solid var(--border-color,#d1d8dd); border-radius: 5px; padding: 5px 8px; font-size: 13px; background: var(--control-bg,#fff); color: inherit; }',
			'.we-tag { display: inline-flex; align-items: center; gap: 6px; padding: 2px 10px; margin: 2px 4px 2px 0; border-radius: 12px; background: var(--primary,#2490ef); color: #fff; font-size: 12px; white-space: nowrap; }',
			'.we-tag-x { cursor: pointer; font-weight: bold; opacity: .85; }',
			'.we-tag-x:hover { opacity: 1; }',
			'.we-add { border: 1px dashed var(--border-color,#c0c8ce); border-radius: 12px; padding: 3px 8px; font-size: 12px; background: transparent; color: var(--text-muted,#8d99a6); max-width: 140px; }',
			'.we-type-head { display: flex; align-items: center; gap: 10px; margin: 24px 0 0; padding: 8px 12px; background: var(--bg-light-gray,#f7f7f7); border: 1px solid var(--border-color,#d1d8dd); border-bottom: none; border-radius: 6px 6px 0 0; }',
			'.we-type-head .we-type-name { font-size: 14px; font-weight: 600; flex: 1; }',
			'.we-type-head .we-lbl { font-size: 12px; color: var(--text-muted,#8d99a6); }',
			'.we-type-head + .we-table { border-top-left-radius: 0; border-top-right-radius: 0; }',
			'.we-priority { width: 56px; padding: 4px 6px; }',
			'.we-muted { color: var(--text-muted,#8d99a6); }',
			'.we-auto { color: var(--text-muted,#8d99a6); }',
			'.we-group td { background: var(--bg-light-gray,#f7f7f7); padding: 6px 12px; }',
			'.we-group-head { display: flex; align-items: center; gap: 10px; }',
			'.we-group-head .we-type-name { font-weight: 600; flex: 1; font-size: 13.5px; }',
			'.we-order { width: 56px; padding: 4px 6px; }'
		].join('\n');
		$('<style id="work-estimate-styles">').text(css).appendTo(document.head);
	}

	setup_layout() {
		var me = this;
		this.$wrap = $('<div class="we-wrap">').appendTo($(this.page.main));

		this.$header = $('<div class="we-header">').appendTo(this.$wrap);
		this.header_fields = new frappe.ui.FieldGroup({
			fields: [
				{ fieldtype: 'Datetime', fieldname: 'requested_start', label: __('Requested Start'), reqd: 1 },
				{ fieldtype: 'Column Break' },
				{ fieldtype: 'Select', fieldname: 'delivery_type', label: __('Delivery Type'), options: 'One Time Delivery\nPartial Delivery', default: 'One Time Delivery' }
			],
			body: this.$header.get(0)
		});
		this.header_fields.make();
		this.header_fields.set_value('requested_start', frappe.datetime.now_datetime());

		this.$items = $('<div class="we-section we-items">').appendTo(this.$wrap);
		this.$types = $('<div class="we-section we-types">').appendTo(this.$wrap);

		var $actions = $('<div class="we-section">').appendTo(this.$wrap);
		this.$check = $('<button class="btn btn-default btn-sm">' + __('Check Estimate') + '</button>').appendTo($actions);
		this.$results = $('<div class="we-section we-results">').appendTo(this.$wrap);

		this.$check.on('click', function () { me.check(); });
		this.page.set_primary_action(__('Save Estimate'), function () { me.save(); });
	}

	load(sales_order) {
		var me = this;
		if (!sales_order) {
			this.$items.html('<div class="we-muted">' + __('Open this page from a Sales Order (Work Estimate button).') + '</div>');
			this.$types.empty();
			return;
		}
		if (this.sales_order === sales_order && this.state) return;
		this.sales_order = sales_order;
		this.page.set_title(__('Work Estimate') + ' — ' + sales_order);

		frappe.call({
			method: 'worldshading.api.production_bom.get_work_estimate_setup',
			args: { sales_order: sales_order },
			freeze: true,
			callback: function (r) {
				me.init_state(r.message || {});
				me.render();
			}
		});
	}

	init_state(data) {
		var teams_by_type = {};
		var priority = {};
		// Default the Order to a clean 1,2,3… by pipeline position (dense rank of the
		// Work Type sequence). Equal sequences share a number (i.e. run in parallel),
		// and it can never default to 0.
		var last_seq = null;
		var rank = 0;
		(data.work_types || []).forEach(function (wt) {
			teams_by_type[wt.work_type] = wt.teams || [];
			if (wt.sequence !== last_seq) { rank += 1; last_seq = wt.sequence; }
			priority[wt.work_type] = rank;
		});
		this.state = {
			items: (data.items || []).map(function (it) {
				return {
					sales_order_item: it.sales_order_item,
					item_code: it.item_code,
					item_name: it.item_name,
					qty: it.qty,
					types: []
				};
			}),
			work_types: data.work_types || [],
			teams_by_type: teams_by_type,
			priority: priority,
			requirements: {}
		};
	}

	req_key(soi, wt) { return soi + '::' + wt; }

	// Auto-pick the team for a (work_type, size): exact size, else next-bigger, else smaller.
	resolve_team(work_type, size) {
		var teams = this.state.teams_by_type[work_type] || [];
		if (!teams.length) return null;
		var by_size = {};
		teams.forEach(function (t) { if (!by_size[t.team_size]) by_size[t.team_size] = t; });
		if (size && by_size[size]) return by_size[size];
		if (size) {
			var idx = WE_SIZES.indexOf(size);
			for (var i = idx + 1; i < WE_SIZES.length; i++) { if (by_size[WE_SIZES[i]]) return by_size[WE_SIZES[i]]; }
			for (var j = idx - 1; j >= 0; j--) { if (by_size[WE_SIZES[j]]) return by_size[WE_SIZES[j]]; }
		}
		return teams[0];
	}

	render() {
		this.render_items();
		this.render_types();
	}

	render_items() {
		var me = this;
		var st = this.state;
		var esc = frappe.utils.escape_html;
		if (!st || !st.items.length) {
			this.$items.html('<div class="we-title">' + __('Items') + '</div><div class="we-muted">' + __('No Sales Order items found.') + '</div>');
			return;
		}
		var has_types = (st.work_types || []).length > 0;
		var html = ['<div class="we-title">' + __('Items') + '</div>'];
		html.push('<table class="we-table"><thead><tr>');
		html.push('<th style="width:34px;">#</th><th style="width:110px;">' + __('Code') + '</th><th>' + __('Item Name') + '</th>');
		html.push('<th class="we-num" style="width:60px;">' + __('Qty') + '</th><th style="width:48%;">' + __('Type') + '</th>');
		html.push('</tr></thead><tbody>');

		st.items.forEach(function (it, idx) {
			html.push('<tr><td>' + (idx + 1) + '</td>');
			html.push('<td>' + esc(it.item_code || '') + '</td>');
			html.push('<td>' + esc(it.item_name || '') + '</td>');
			html.push('<td class="we-num">' + esc(String(it.qty)) + '</td>');
			html.push('<td>');
			if (!has_types) {
				html.push('<span class="we-muted">' + __('No Work Types with teams yet.') + '</span>');
			} else {
				it.types.forEach(function (t) {
					html.push('<span class="we-tag">' + esc(t) + ' <span class="we-tag-x" data-idx="' + idx + '" data-type="' + esc(t) + '">&times;</span></span>');
				});
				var remaining = st.work_types.filter(function (wt) { return it.types.indexOf(wt.work_type) === -1; });
				if (remaining.length) {
					var opts = ['<option value="">' + __('+ Add type') + '</option>'];
					remaining.forEach(function (wt) { opts.push('<option value="' + esc(wt.work_type) + '">' + esc(wt.work_type) + '</option>'); });
					html.push('<select class="we-add we-add-type" data-idx="' + idx + '">' + opts.join('') + '</select>');
				}
			}
			html.push('</td></tr>');
		});
		html.push('</tbody></table>');
		this.$items.html(html.join(''));

		this.$items.find('.we-add-type').on('change', function () {
			var val = $(this).val();
			if (val) me.add_type(parseInt($(this).attr('data-idx'), 10), val);
		});
		this.$items.find('.we-tag-x').on('click', function () {
			me.remove_type(parseInt($(this).attr('data-idx'), 10), $(this).attr('data-type'));
		});
	}

	add_type(idx, type) {
		var it = this.state.items[idx];
		if (it.types.indexOf(type) === -1) it.types.push(type);
		this.render_items();
		this.render_types();
	}

	remove_type(idx, type) {
		var it = this.state.items[idx];
		var pos = it.types.indexOf(type);
		if (pos !== -1) it.types.splice(pos, 1);
		this.render_items();
		this.render_types();
	}

	selected_types_ordered() {
		var me = this;
		var set = {};
		this.state.items.forEach(function (it) { it.types.forEach(function (t) { set[t] = true; }); });
		return Object.keys(set).sort(function (a, b) {
			var pa = we_flt(me.state.priority[a]), pb = we_flt(me.state.priority[b]);
			return pa !== pb ? pa - pb : (a < b ? -1 : 1);
		});
	}

	render_types() {
		var me = this;
		var st = this.state;
		var esc = frappe.utils.escape_html;
		this.$types.empty();
		if (!st) return;

		var types = this.selected_types_ordered();
		if (!types.length) {
			this.$types.html('<div class="we-muted">' + __('Add a Type to the items above to plan each work stage.') + '</div>');
			return;
		}

		// One consolidated table, grouped by type. Each type gets a header row that also
		// carries its Order, then a row per item that selected it.
		var html = ['<div class="we-title">' + __('Work Stages') + '</div>'];
		html.push('<table class="we-table"><thead><tr>');
		html.push('<th style="width:110px;">' + __('Code') + '</th><th>' + __('Item Name') + '</th>');
		html.push('<th class="we-num" style="width:55px;">' + __('Qty') + '</th>');
		html.push('<th style="width:120px;">' + __('Est. Hours') + '</th>');
		html.push('<th style="width:120px;">' + __('Size') + '</th>');
		html.push('<th style="width:190px;">' + __('Team (auto)') + '</th>');
		html.push('</tr></thead><tbody>');

		types.forEach(function (wt) {
			var items = st.items.filter(function (it) { return it.types.indexOf(wt) !== -1; });

			html.push('<tr class="we-group"><td colspan="6"><div class="we-group-head">');
			html.push('<span class="we-type-name">' + esc(wt) + '</span>');
			html.push('<span class="we-lbl">' + __('Order') + '</span>');
			html.push('<input type="number" min="1" step="1" class="we-input we-order" data-type="' + esc(wt) + '" value="' + we_flt(me.state.priority[wt]) + '">');
			html.push('</div></td></tr>');

			items.forEach(function (it) {
				var req = st.requirements[me.req_key(it.sales_order_item, wt)] || {};
				var resolved = me.resolve_team(wt, req.team_size);
				html.push('<tr data-soi="' + esc(it.sales_order_item) + '" data-type="' + esc(wt) + '">');
				html.push('<td>' + esc(it.item_code || '') + '</td><td>' + esc(it.item_name || '') + '</td>');
				html.push('<td class="we-num">' + esc(String(it.qty)) + '</td>');
				html.push('<td><input type="number" step="0.5" min="0" class="we-input we-hours" value="' + (req.estimated_hours != null ? req.estimated_hours : '') + '"></td>');
				var size_opts = [''].concat(WE_SIZES).map(function (s) {
					var sel = (req.team_size || '') === s ? ' selected' : '';
					return '<option value="' + s + '"' + sel + '>' + (s || __('Any')) + '</option>';
				});
				html.push('<td><select class="we-input we-size">' + size_opts.join('') + '</select></td>');
				html.push('<td class="we-auto we-team-cell">' + (resolved ? esc(resolved.team_name) : '<span class="we-muted">' + __('No team') + '</span>') + '</td>');
				html.push('</tr>');
			});
		});
		html.push('</tbody></table>');
		this.$types.html(html.join(''));

		this.$types.find('.we-order').on('change', function () {
			var val = we_flt($(this).val());
			if (val < 1) val = 1;  // Order starts at 1; duplicates are allowed (parallel stages).
			me.state.priority[$(this).attr('data-type')] = val;
			me.render_types();
		});

		this.$types.find('tr[data-soi]').each(function () {
			var $tr = $(this);
			var wt = $tr.attr('data-type');
			var key = me.req_key($tr.attr('data-soi'), wt);
			function req() { if (!me.state.requirements[key]) me.state.requirements[key] = {}; return me.state.requirements[key]; }
			$tr.find('.we-hours').on('change', function () { req().estimated_hours = we_flt($(this).val()); });
			$tr.find('.we-size').on('change', function () {
				req().team_size = $(this).val();
				var resolved = me.resolve_team(wt, $(this).val());
				$tr.find('.we-team-cell').html(resolved ? frappe.utils.escape_html(resolved.team_name) : '<span class="we-muted">' + __('No team') + '</span>');
			});
		});
	}

	collect() {
		var st = this.state;
		var me = this;
		var requirements = [];
		st.items.forEach(function (it) {
			it.types.forEach(function (wt) {
				var req = st.requirements[me.req_key(it.sales_order_item, wt)] || {};
				var resolved = me.resolve_team(wt, req.team_size);
				requirements.push({
					sales_order_item: it.sales_order_item,
					item_code: it.item_code,
					item_name: it.item_name,
					qty: it.qty,
					work_type: wt,
					priority: we_flt(st.priority[wt]),
					estimated_hours: we_flt(req.estimated_hours),
					team_size: req.team_size || '',
					team: resolved ? resolved.name : ''
				});
			});
		});
		return {
			sales_order: this.sales_order,
			requested_start: this.header_fields.get_value('requested_start'),
			delivery_type: this.header_fields.get_value('delivery_type'),
			requirements: requirements
		};
	}

	check() {
		if (!this.state) return;
		var me = this;
		var payload = this.collect();
		if (!payload.requirements.length) {
			frappe.msgprint(__('Add a Type to an item and enter hours.'));
			return;
		}
		frappe.call({
			method: 'worldshading.api.production_bom.get_work_estimate_schedule',
			args: {
				sales_order: payload.sales_order,
				requested_start: payload.requested_start,
				delivery_type: payload.delivery_type,
				requirements: payload.requirements
			},
			freeze: true,
			callback: function (r) { me.render_results(r.message || {}); }
		});
	}

	render_results(data) {
		var esc = frappe.utils.escape_html;
		var stages = data.stages || [];
		var warnings = data.warnings || [];
		var summary = data.summary || {};
		var html = ['<div class="we-title">' + __('Estimated Schedule') + '</div>'];

		if (!stages.length) {
			this.$results.html(html.join('') + '<div class="we-muted">' + __('Nothing to schedule.') + '</div>');
			return;
		}

		warnings.forEach(function (w) {
			html.push('<div class="we-muted" style="margin-bottom:6px;">&#9888; ' + esc(w) + '</div>');
		});

		// Group by work type, ordered by Order then name.
		var groups = {};
		stages.forEach(function (s) {
			var key = s.priority + '||' + s.work_type;
			(groups[key] = groups[key] || []).push(s);
		});
		var keys = Object.keys(groups).sort(function (a, b) {
			var pa = parseInt(a.split('||')[0], 10), pb = parseInt(b.split('||')[0], 10);
			return pa !== pb ? pa - pb : (a < b ? -1 : 1);
		});

		html.push('<table class="we-table"><thead><tr>');
		html.push('<th style="width:110px;">' + __('Code') + '</th><th>' + __('Item Name') + '</th>');
		html.push('<th style="width:160px;">' + __('Team') + '</th>');
		html.push('<th class="we-num" style="width:60px;">' + __('Hrs') + '</th>');
		html.push('<th style="width:180px;">' + __('Start') + '</th><th style="width:180px;">' + __('End') + '</th>');
		html.push('</tr></thead><tbody>');

		keys.forEach(function (key) {
			var rows = groups[key];
			var order = key.split('||')[0];
			var wt = rows[0].work_type;
			html.push('<tr class="we-group"><td colspan="6"><div class="we-group-head"><span class="we-type-name">' + esc(wt) + '</span><span class="we-lbl">' + __('Order {0}', [order]) + '</span></div></td></tr>');
			rows.forEach(function (s) {
				html.push('<tr>');
				html.push('<td>' + esc(s.item_code || '') + '</td><td>' + esc(s.item_name || '') + '</td>');
				html.push('<td>' + esc(s.team_name || '') + '</td>');
				html.push('<td class="we-num">' + esc(String(s.hours || '')) + '</td>');
				html.push('<td>' + esc(we_fmt_dt(s.start)) + '</td><td>' + esc(we_fmt_dt(s.end)) + '</td>');
				html.push('</tr>');
			});
		});
		html.push('</tbody></table>');

		if (summary.final_completion) {
			html.push('<div style="margin-top:16px; padding:12px 14px; border:1px solid var(--border-color,#d1d8dd); border-radius:6px;">');
			if (summary.delivery_type === 'Partial Delivery' && summary.first_completion) {
				html.push('<div><strong>' + __('First Item Ready') + ':</strong> ' + esc(we_fmt_dt(summary.first_completion)) + '</div>');
			}
			html.push('<div><strong>' + __('Final Order Completion') + ':</strong> ' + esc(we_fmt_dt(summary.final_completion)) + '</div>');
			html.push('<div><strong>' + __('Delivery Type') + ':</strong> ' + esc(summary.delivery_type || '') + '</div>');
			html.push('</div>');
		}

		this.$results.html(html.join(''));
	}

	save() {
		frappe.msgprint(__('Saving the estimate will be enabled in the next step.'));
	}
}

function we_flt(v) {
	var n = parseFloat(v);
	return isNaN(n) ? 0 : n;
}

function we_fmt_dt(v) {
	if (!v) return '';
	return moment(v, 'YYYY-MM-DD HH:mm:ss').format('DD-MM-YYYY hh:mm A');
}
