(function () {
	var TABLE_FIELD = "production_bom_items";
	var TOTAL_FIELD = "total_raw_materials_price";

	var TRANSACTION_DOCTYPES = {
		"Quotation": true,
		"Sales Order": true
	};

	var PRODUCTION_BOM_FIELDS = [
		"parent_item_row",
		"parent_detail",
		"parent_item",
		"master_bom",
		"transaction_bom",
		"item_code",
		"item_name",
		"description",
		"qty",
		"uom",
		"rate",
		"amount",
		"source_warehouse",
		"include_item_in_manufacturing"
	];

	function is_supported_transaction(frm) {
		return frm && (frm.doctype === "Quotation" || frm.doctype === "Sales Order");
	}

	function has_field(frm, fieldname) {
		return frm.fields_dict && frm.fields_dict[fieldname];
	}

	function get_parent_key(parent_row) {
		return parent_row.name || ("idx:" + parent_row.idx + ":" + parent_row.item_code);
	}

	function setup_tracking(frm) {
		frm.__production_bom_customized_parents = frm.__production_bom_customized_parents || {};
		frm.__production_bom_loaded_qty_by_parent = frm.__production_bom_loaded_qty_by_parent || {};
	}

	function calculate_totals(frm) {
		var total = 0;
		var table_changed = false;

		(frm.doc[TABLE_FIELD] || []).forEach(function (row) {
			var amount = flt(row.qty) * flt(row.rate);

			if (flt(row.amount, 6) !== flt(amount, 6)) {
				row.amount = amount;
				table_changed = true;
			}

			total += flt(row.amount);
		});

		if (has_field(frm, TOTAL_FIELD) && flt(frm.doc[TOTAL_FIELD], 6) !== flt(total, 6)) {
			if (frm.doc.docstatus === 0) {
				frm.set_value(TOTAL_FIELD, total);
			} else {
				frm.doc[TOTAL_FIELD] = total;
				frm.refresh_field(TOTAL_FIELD);
			}
		}

		if (table_changed) {
			frm.refresh_field(TABLE_FIELD);
		}
	}

	function copy_production_bom_row(source, target) {
		PRODUCTION_BOM_FIELDS.forEach(function (fieldname) {
			target[fieldname] = source[fieldname];
		});
	}

	function remove_rows_for_parent(frm, parent_row) {
		var existing_rows = frm.doc[TABLE_FIELD] || [];
		var keep_rows = [];

		existing_rows.forEach(function (row) {
			if (row.parent_detail === parent_row.name || cint(row.parent_item_row) === cint(parent_row.idx)) {
				return;
			}

			keep_rows.push(frappe.model.get_doc(row.doctype, row.name));
		});

		frm.clear_table(TABLE_FIELD);

		keep_rows.forEach(function (row) {
			var new_row = frm.add_child(TABLE_FIELD);
			copy_production_bom_row(row, new_row);
		});
	}

	function get_rows_for_parent(frm, parent_row) {
		return (frm.doc[TABLE_FIELD] || []).filter(function (row) {
			return row.parent_detail === parent_row.name || cint(row.parent_item_row) === cint(parent_row.idx);
		});
	}

	function reload_existing_parent_bom(frm, parent_row, existing_rows) {
		if (!existing_rows.length) {
			return false;
		}

		setup_tracking(frm);

		if (
			frm.__production_bom_customized_parents[get_parent_key(parent_row)]
			|| !frm.__production_bom_loaded_qty_by_parent[get_parent_key(parent_row)]
		) {
			calculate_totals(frm);
			return true;
		}

		frappe.call({
			method: "worldshading.api.production_bom.get_default_bom_items",
			args: {
				item_code: parent_row.item_code,
				qty: parent_row.qty || 1
			},
			callback: function (r) {
				var data = r.message || {};

				remove_rows_for_parent(frm, parent_row);

				if (data.bom && data.items && data.items.length) {
					add_bom_rows(frm, parent_row, data);
					frm.__production_bom_loaded_qty_by_parent[get_parent_key(parent_row)] = flt(parent_row.qty) || 1;
				}

				calculate_totals(frm);
			}
		});

		return true;
	}

	function add_bom_rows(frm, parent_row, bom_data) {
		(bom_data.items || []).forEach(function (bom_item) {
			var row = frm.add_child(TABLE_FIELD);

			$.extend(row, {
				parent_item_row: parent_row.idx,
				parent_detail: parent_row.name,
				parent_item: parent_row.item_code,
				master_bom: bom_data.bom,
				item_code: bom_item.item_code,
				item_name: bom_item.item_name,
				description: bom_item.description,
				qty: bom_item.qty,
				uom: bom_item.uom,
				rate: bom_item.rate,
				amount: bom_item.amount,
				source_warehouse: bom_item.source_warehouse,
				include_item_in_manufacturing: bom_item.include_item_in_manufacturing ? 1 : 0
			});
		});
	}

	function load_parent_bom(frm, parent_row, opts) {
		opts = opts || {};

		if (!is_supported_transaction(frm) || !has_field(frm, TABLE_FIELD) || frm.doc.docstatus !== 0) {
			return;
		}

		if (!parent_row || !parent_row.item_code) {
			return;
		}

		var existing_rows = get_rows_for_parent(frm, parent_row);
		var same_parent_item_rows = existing_rows.filter(function (row) {
			return row.parent_item === parent_row.item_code;
		});

		if (same_parent_item_rows.length) {
			if (opts.reload_existing) {
				reload_existing_parent_bom(frm, parent_row, same_parent_item_rows);
			} else {
				calculate_totals(frm);
			}
			return;
		}

		if (existing_rows.length && !opts.reload_if_parent_item_changed) {
			calculate_totals(frm);
			return;
		}

		frappe.call({
			method: "worldshading.api.production_bom.get_default_bom_items",
			args: {
				item_code: parent_row.item_code,
				qty: parent_row.qty || 1
			},
			callback: function (r) {
				var data = r.message || {};

				remove_rows_for_parent(frm, parent_row);

				if (data.bom && data.items && data.items.length) {
					add_bom_rows(frm, parent_row, data);
					setup_tracking(frm);
					frm.__production_bom_loaded_qty_by_parent[get_parent_key(parent_row)] = flt(parent_row.qty) || 1;
				}

				calculate_totals(frm);
			}
		});
	}

	function remove_orphan_rows(frm) {
		if (!has_field(frm, TABLE_FIELD)) {
			return;
		}

		var valid_parent_keys = {};

		(frm.doc.items || []).forEach(function (item) {
			if (item.item_code) {
				valid_parent_keys[item.name] = true;
				valid_parent_keys["idx:" + item.idx + ":" + item.item_code] = true;
			}
		});

		var keep_rows = [];
		(frm.doc[TABLE_FIELD] || []).forEach(function (row) {
			if (valid_parent_keys[row.parent_detail] || valid_parent_keys["idx:" + row.parent_item_row + ":" + row.parent_item]) {
				keep_rows.push(frappe.model.get_doc(row.doctype, row.name));
			}
		});

		if (keep_rows.length === (frm.doc[TABLE_FIELD] || []).length) {
			return;
		}

		frm.clear_table(TABLE_FIELD);
		keep_rows.forEach(function (row) {
			var new_row = frm.add_child(TABLE_FIELD);
			copy_production_bom_row(row, new_row);
		});

		calculate_totals(frm);
	}

	function load_all_missing_boms(frm) {
		if (!is_supported_transaction(frm) || !has_field(frm, TABLE_FIELD) || frm.doc.docstatus !== 0) {
			return;
		}

		(frm.doc.items || []).forEach(function (item) {
			if (!item.item_code) {
				return;
			}

			var has_rows = (frm.doc[TABLE_FIELD] || []).some(function (row) {
				return row.parent_detail === item.name || cint(row.parent_item_row) === cint(item.idx);
			});

			if (!has_rows) {
				load_parent_bom(frm, item);
			}
		});
	}

	function load_raw_material_details(frm, row) {
		if (!row || !row.item_code || !TRANSACTION_DOCTYPES[row.parenttype]) {
			calculate_totals(frm);
			return;
		}

		frappe.call({
			method: "worldshading.api.production_bom.get_raw_material_details",
			args: {
				item_code: row.item_code
			},
			callback: function (r) {
				var data = r.message || {};

				frappe.model.set_value(row.doctype, row.name, "item_name", data.item_name || "");
				frappe.model.set_value(row.doctype, row.name, "description", data.description || "");
				frappe.model.set_value(row.doctype, row.name, "uom", data.uom || "");
				frappe.model.set_value(row.doctype, row.name, "rate", data.rate || 0);

				calculate_totals(frm);
			}
		});
	}

	function mark_bom_row_customized(frm, row) {
		if (!row || !row.parent_item_row) {
			return;
		}

		setup_tracking(frm);

		(frm.doc.items || []).forEach(function (item) {
			if (cint(item.idx) === cint(row.parent_item_row) && item.item_code === row.parent_item) {
				frm.__production_bom_customized_parents[get_parent_key(item)] = true;
			}
		});
	}

	function build_drawing_title_html(item, row_number) {
		var meta_parts = [];
		if (item.item_name) {
			meta_parts.push(item.item_name);
		}
		meta_parts.push(__("Qty") + " " + item.pending_qty);

		return '<span>' + row_number + ". " + frappe.utils.escape_html(item.item_code) + '</span>'
			+ '<span style="font-size:11px; color:#8d99a6;"> : '
			+ frappe.utils.escape_html(meta_parts.join(" : "))
			+ '</span>';
	}

	function get_file_display_name(file_url) {
		var name = (file_url || "").split("/").pop();
		try {
			return decodeURIComponent(name);
		} catch (e) {
			return name;
		}
	}

	function render_item_uploader(block, item_state) {
		var upload_section = block.find(".ws-drawing-upload");
		var files_section = block.find(".ws-drawing-files");
		var addmore_section = block.find(".ws-drawing-addmore");

		upload_section.empty();
		addmore_section.hide().empty();

		new frappe.ui.FileUploader({
			wrapper: upload_section,
			allow_multiple: true,
			restrictions: {
				allowed_file_types: ["image/*", ".pdf"]
			},
			on_success: function (file) {
				item_state.file_docnames.push(file.name);

				files_section.append(
					'<div style="display:flex; align-items:center; gap:8px; padding:6px 10px; margin-bottom:6px;'
					+ ' background:#f8f9fa; border-radius:6px; font-size:13px;">'
					+ '<span>📎</span>'
					+ '<div style="flex:1; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">'
					+ frappe.utils.escape_html(file.file_name)
					+ '</div></div>'
				);

				frappe.show_alert({ message: __("Uploaded: ") + file.file_name, indicator: "green" });

				upload_section.empty();
				addmore_section.html(
					'<button class="btn btn-default btn-xs ws-drawing-addmore-btn" type="button">'
					+ __("+ Add More Files")
					+ '</button>'
				).show();
			}
		});
	}

	function setup_production_drawings(dialog, items, state) {
		var wrapper = dialog.fields_dict.production_drawings.$wrapper;
		wrapper.empty();

		wrapper.append(
			'<div style="font-weight:700; font-size:14px; margin-bottom:2px;">'
			+ __("Production Drawings")
			+ '</div>'
			+ '<div class="text-muted" style="font-size:12px; margin-bottom:10px;">'
			+ __("Attach the drawings if any of the items need one.")
			+ '</div>'
		);

		(items || []).forEach(function (item, index) {
			var sales_order_item = item.sales_order_item;

			state[sales_order_item] = {
				file_docnames: [],
				existing_url: item.production_attachment || ""
			};

			var block = $(
				'<div class="ws-drawing-block" style="padding:10px 0; border-top:1px solid #ebeff2;">'
				+ '<div style="font-size:13px; margin-bottom:6px;">'
				+ build_drawing_title_html(item, index + 1)
				+ '</div>'
				+ '<div class="ws-drawing-existing" style="margin-bottom:6px;"></div>'
				+ '<div class="ws-drawing-upload"></div>'
				+ '<div class="ws-drawing-files" style="margin-top:8px;"></div>'
				+ '<div class="ws-drawing-addmore" style="margin-top:8px;"></div>'
				+ '</div>'
			);

			block.data("drawingState", state[sales_order_item]);
			wrapper.append(block);

			if (state[sales_order_item].existing_url) {
				var existing_url = state[sales_order_item].existing_url;
				block.find(".ws-drawing-existing").html(
					'<a href="' + frappe.utils.escape_html(existing_url) + '" target="_blank">'
					+ frappe.utils.escape_html(get_file_display_name(existing_url))
					+ '</a>'
				);
			}

			render_item_uploader(block, state[sales_order_item]);
		});

		wrapper.on("click", ".ws-drawing-addmore-btn", function (e) {
			e.preventDefault();
			var block = $(this).closest(".ws-drawing-block");
			render_item_uploader(block, block.data("drawingState"));
		});
	}

	function collect_drawing_attachments(state, items) {
		var attachments = {};

		(items || []).forEach(function (item) {
			var item_state = state[item.sales_order_item] || {};
			attachments[item.sales_order_item] = {
				file_docnames: item_state.file_docnames || [],
				existing_url: item_state.existing_url || ""
			};
		});

		return attachments;
	}

	function show_order_specific_work_order_dialog(frm, items) {
		var item_table_field = {
			label: __("Items"),
			fieldtype: "Table",
			fieldname: "items",
			description: __("Order-specific BOM will be used where available."),
			fields: [{
				fieldtype: "Read Only",
				fieldname: "item_code",
				label: __("Item Code"),
				in_list_view: 1
			}, {
				fieldtype: "Read Only",
				fieldname: "item_name",
				label: __("Item Name"),
				in_list_view: 1
			}, {
				fieldtype: "Link",
				fieldname: "bom",
				options: "BOM",
				reqd: 1,
				label: __("BOM"),
				in_list_view: 1,
				read_only: 1
			}, {
				fieldtype: "Float",
				fieldname: "pending_qty",
				reqd: 1,
				label: __("Qty"),
				in_list_view: 1
			}, {
				fieldtype: "Data",
				fieldname: "sales_order_item",
				reqd: 1,
				label: __("Sales Order Item"),
				hidden: 1
			}, {
				fieldtype: "Data",
				fieldname: "warehouse",
				hidden: 1
			}, {
				fieldtype: "Text",
				fieldname: "description",
				hidden: 1
			}],
			data: items,
			get_data: function () {
				return items;
			}
		};

		var drawings_state = {};

		var dialog = new frappe.ui.Dialog({
			title: __("Select Items to Manufacture"),
			fields: [item_table_field, {
				fieldtype: "Section Break"
			}, {
				fieldtype: "HTML",
				fieldname: "production_drawings"
			}],
			primary_action_label: __("Create"),
			primary_action: function () {
				var values = dialog.get_values();
				if (!values) {
					return;
				}

				frappe.call({
					method: "worldshading.api.production_bom.make_order_specific_work_orders",
					args: {
						items: values.items,
						sales_order: frm.doc.name,
						company: frm.doc.company,
						project: frm.doc.project,
						attachments: JSON.stringify(collect_drawing_attachments(drawings_state, items))
					},
					freeze: true,
					callback: function (r) {
						if (r.message) {
							frappe.msgprint({
								message: __("Work Orders Created: {0}", [
									r.message.map(function (name) {
										return repl('<a href="#Form/Work Order/%(name)s">%(name)s</a>', { name: name });
									}).join(", ")
								]),
								indicator: "green"
							});
						}

						dialog.hide();
					}
				});
			}
		});

		dialog.show();
		dialog.$wrapper.find(".modal-dialog").addClass("modal-lg");

		setup_production_drawings(dialog, items, drawings_state);
	}

	function make_order_specific_work_order(frm) {
		frappe.call({
			method: "worldshading.api.production_bom.get_order_specific_work_order_items",
			args: {
				sales_order: frm.doc.name
			},
			callback: function (r) {
				var items = r.message || [];

				if (!items.length) {
					frappe.msgprint({
						title: __("Work Order not created"),
						message: __("No pending Sales Order items with BOM found."),
						indicator: "orange"
					});
					return;
				}

				show_order_specific_work_order_dialog(frm, items);
			}
		});
	}

	function get_estimate_row_by_item(rows, sales_order_item) {
		var match = null;

		(rows || []).forEach(function (row) {
			if ((row.sales_order_item || row.name) === sales_order_item) {
				match = row;
			}
		});

		return match;
	}

	function format_estimate_datetime(value) {
		if (!value) {
			return "";
		}

		// Readable date + 12-hour time with AM/PM, e.g. "21-07-2026 02:00 PM".
		return moment(value, "YYYY-MM-DD HH:mm:ss").format("DD-MM-YYYY hh:mm A");
	}

	function render_estimate_table(title, rows) {
		if (!rows || !rows.length) {
			return "";
		}

		var html = [
			'<h4 style="margin: 16px 0 8px;">' + frappe.utils.escape_html(title) + '</h4>',
			'<table class="table table-bordered" style="margin-bottom: 0;">',
			'<thead><tr>',
			'<th style="width: 6%;">#</th>',
			'<th style="width: 32%;">' + __("Item") + '</th>',
			'<th style="width: 17%;">' + __("Team") + '</th>',
			'<th style="width: 9%;">' + __("Hours") + '</th>',
			'<th style="width: 18%;">' + __("Start") + '</th>',
			'<th style="width: 18%;">' + __("End") + '</th>',
			'</tr></thead><tbody>'
		];

		rows.forEach(function (row, index) {
			var item_label = frappe.utils.escape_html(row.item_code || "");
			if (row.item_name) {
				item_label += " : " + frappe.utils.escape_html(row.item_name);
			}

			html.push(
				'<tr>',
				'<td>' + (index + 1) + '</td>',
				'<td>' + item_label + '</td>',
				'<td>' + frappe.utils.escape_html(row.team || "") + '</td>',
				'<td>' + frappe.utils.escape_html(row.hours || "") + '</td>',
				'<td>' + frappe.utils.escape_html(format_estimate_datetime(row.start)) + '</td>',
				'<td>' + frappe.utils.escape_html(format_estimate_datetime(row.end)) + '</td>',
				'</tr>'
			);
		});

		html.push("</tbody></table>");
		return html.join("");
	}

	function refresh_production_estimate_results(dialog, data) {
		data = data || {};
		var production = data.production || [];
		var fixing = data.fixing || [];
		var warnings = data.warnings || [];
		var summary = data.summary || {};
		var html = ['<div style="margin-top: 12px;">'];

		if (!production.length && !fixing.length) {
			html.push('<div class="text-muted">' + __("No estimate result found.") + '</div></div>');
			dialog.fields_dict.estimate_results.$wrapper.html(html.join(""));
			return;
		}

		// Warnings appear above the tables, not as rows inside them.
		warnings.forEach(function (message) {
			html.push('<div class="text-muted" style="margin-bottom: 6px;">⚠ ' + frappe.utils.escape_html(message) + '</div>');
		});

		html.push(render_estimate_table(__("Production Estimate"), production));
		html.push(render_estimate_table(__("Fixing Estimate"), fixing));

		if (summary.final_completion) {
			// Per-item completions are already shown in the rows above, so the summary
			// only needs the overall order completion + the chosen delivery type.
			html.push(
				'<div style="margin-top: 16px; padding: 12px 14px; border: 1px solid var(--border-color, #d1d8dd); border-radius: 6px;">',
				'<div><strong>' + __("Final Order Completion") + ':</strong> ' + frappe.utils.escape_html(format_estimate_datetime(summary.final_completion)) + '</div>',
				'<div><strong>' + __("Delivery Type") + ':</strong> ' + frappe.utils.escape_html(summary.delivery_type || "") + '</div>',
				'</div>'
			);
		}

		html.push("</div>");
		dialog.fields_dict.estimate_results.$wrapper.html(html.join(""));
	}

	function check_sales_order_production_estimate(frm, dialog) {
		var values = dialog.get_values();
		if (!values) {
			return;
		}

		var fixing_needed = values.fixing_needed ? 1 : 0;

		frappe.call({
			method: "worldshading.api.production_bom.get_sales_order_production_estimate",
			args: {
				sales_order: frm.doc.name,
				items: dialog._items || values.items || [],
				requested_start: values.requested_start,
				delivery_type: values.delivery_type,
				fixing_needed: fixing_needed
			},
			freeze: true,
			callback: function (r) {
				refresh_production_estimate_results(dialog, r.message || {});
			}
		});
	}

	function save_sales_order_production_estimate(frm, dialog) {
		var values = dialog.get_values();
		if (!values) {
			return;
		}

		frappe.call({
			method: "worldshading.api.production_bom.save_sales_order_production_estimate",
			args: {
				sales_order: frm.doc.name,
				items: dialog._items || values.items || [],
				delivery_type: values.delivery_type
			},
			freeze: true,
			callback: function () {
				dialog.hide();
				frm.reload_doc();
			}
		});
	}

	function show_sales_order_production_estimate_dialog(frm, items) {
		var dialog = new frappe.ui.Dialog({
			title: __("Production Estimate"),
			fields: [{
				fieldtype: "Datetime",
				fieldname: "requested_start",
				label: __("Requested Start"),
				default: frappe.datetime.now_datetime(),
				reqd: 1
			}, {
				fieldtype: "Select",
				fieldname: "delivery_type",
				label: __("Delivery Type"),
				options: "One Time Delivery\nPartial Delivery",
				default: frm.doc.allow_partial_manufacturing_delivery ? "Partial Delivery" : "One Time Delivery",
				reqd: 1
			}, {
				fieldtype: "Check",
				fieldname: "fixing_needed",
				label: __("Fixing Needed"),
				default: 0
			}, {
				fieldtype: "Section Break"
			}, {
				fieldtype: "Table",
				fieldname: "items",
				label: __("Manufacturing Items"),
				cannot_add_rows: true,
				cannot_delete_rows: true,
				in_place_edit: true,
				fields: [{
					fieldtype: "Data",
					fieldname: "item_code",
					label: __("Code"),
					read_only: 1,
					in_list_view: 1,
					columns: 1
				}, {
					fieldtype: "Data",
					fieldname: "item_name",
					label: __("Item Name"),
					read_only: 1,
					in_list_view: 1,
					columns: 4
				}, {
					fieldtype: "Float",
					fieldname: "qty",
					label: __("Qty"),
					read_only: 1,
					in_list_view: 1,
					columns: 1
				}, {
					fieldtype: "Float",
					fieldname: "production_estimated_hours",
					label: __("Production Hours"),
					in_list_view: 1,
					columns: 2
				}, {
					fieldtype: "Link",
					fieldname: "production_team",
					options: "Work Team",
					label: __("Production Team"),
					in_list_view: 1,
					columns: 2,
					get_query: function () {
						return { filters: { team_type: "Production", disabled: 0 } };
					}
				}, {
					fieldtype: "Data",
					fieldname: "sales_order_item",
					hidden: 1
				}],
				data: items,
				get_data: function () {
					return items;
				}
			}, {
				fieldtype: "Table",
				fieldname: "items_fixing",
				label: __("Manufacturing Items"),
				cannot_add_rows: true,
				cannot_delete_rows: true,
				in_place_edit: true,
				fields: [{
					fieldtype: "Data",
					fieldname: "item_code",
					label: __("Code"),
					read_only: 1,
					in_list_view: 1,
					columns: 1
				}, {
					fieldtype: "Data",
					fieldname: "item_name",
					label: __("Item Name"),
					read_only: 1,
					in_list_view: 1,
					columns: 2
				}, {
					fieldtype: "Float",
					fieldname: "qty",
					label: __("Qty"),
					read_only: 1,
					in_list_view: 1,
					columns: 1
				}, {
					fieldtype: "Float",
					fieldname: "production_estimated_hours",
					label: __("Prod Hrs"),
					in_list_view: 1,
					columns: 1
				}, {
					fieldtype: "Link",
					fieldname: "production_team",
					options: "Work Team",
					label: __("Prod Team"),
					in_list_view: 1,
					columns: 2,
					get_query: function () {
						return { filters: { team_type: "Production", disabled: 0 } };
					}
				}, {
					fieldtype: "Float",
					fieldname: "fixing_estimated_hours",
					label: __("Fixing Hrs"),
					in_list_view: 1,
					columns: 1
				}, {
					fieldtype: "Link",
					fieldname: "fixing_team",
					options: "Work Team",
					label: __("Fixing Team"),
					in_list_view: 1,
					columns: 2,
					get_query: function () {
						return { filters: { team_type: "Fixing", disabled: 0 } };
					}
				}, {
					fieldtype: "Data",
					fieldname: "sales_order_item",
					hidden: 1
				}],
				data: items,
				get_data: function () {
					return items;
				}
			}, {
				fieldtype: "Section Break"
			}, {
				fieldtype: "Button",
				fieldname: "check_estimate",
				label: __("Check Estimate")
			}, {
				fieldtype: "HTML",
				fieldname: "estimate_results"
			}],
			primary_action_label: __("Save Estimate"),
			primary_action: function () {
				save_sales_order_production_estimate(frm, dialog);
			}
		});

		dialog._items = items;

		dialog.show();
		dialog.$wrapper.find(".modal-dialog").addClass("modal-lg").css({ width: "1150px", "max-width": "96vw" });
		dialog.fields_dict.check_estimate.$input.on("click", function () {
			check_sales_order_production_estimate(frm, dialog);
		});
		// Swap between the plain table and the one that also carries Fixing columns
		// (both are bound to the same rows, so only one is ever visible).
		dialog.fields_dict.fixing_needed.$input.on("change", function () {
			toggle_fixing_columns(dialog, dialog.get_value("fixing_needed"));
		});
		toggle_fixing_columns(dialog, dialog.get_value("fixing_needed"));
		dialog.fields_dict.estimate_results.$wrapper.html(
			'<div class="text-muted" style="margin-top: 10px;">' +
			__("Enter hours and team, then click Check Estimate.") +
			'</div>'
		);
	}

	function toggle_fixing_columns(dialog, show) {
		dialog.fields_dict.items.$wrapper.toggle(!show);
		dialog.fields_dict.items_fixing.$wrapper.toggle(!!show);
		var grid = show ? dialog.fields_dict.items_fixing.grid : dialog.fields_dict.items.grid;
		grid.refresh();
	}

	function show_sales_order_production_estimate(frm) {
		frappe.call({
			method: "worldshading.api.production_bom.get_sales_order_production_estimate_items",
			args: {
				sales_order: frm.doc.name
			},
			callback: function (r) {
				var items = r.message || [];

				if (!items.length) {
					frappe.msgprint({
						title: __("Production Estimate"),
						message: __("No Sales Order items with BOM found."),
						indicator: "orange"
					});
					return;
				}

				show_sales_order_production_estimate_dialog(frm, items);
			}
		});
	}

	frappe.ui.form.on("Quotation", {
		refresh: function (frm) {
			calculate_totals(frm);
		},
		validate: function (frm) {
			remove_orphan_rows(frm);
			calculate_totals(frm);
		}
	});

	frappe.ui.form.on("Sales Order", {
		refresh: function (frm) {
			calculate_totals(frm);

			if (!frm.doc.__islocal) {
				frm.add_custom_button(__("Production Estimate"), function () {
					show_sales_order_production_estimate(frm);
				});
				frm.add_custom_button(__("Work Estimate"), function () {
					frappe.set_route("work-estimate", frm.doc.name);
				});
			}

			if (frm.doc.docstatus === 1 && frm.doc.status !== "Closed") {
				frm.add_custom_button(__("Order Specific Work Order"), function () {
					make_order_specific_work_order(frm);
				}, __("Create"));
			}
		},
		validate: function (frm) {
			remove_orphan_rows(frm);
			calculate_totals(frm);
		}
	});

	frappe.ui.form.on("Quotation Item", {
		item_code: function (frm, cdt, cdn) {
			load_parent_bom(frm, locals[cdt][cdn], {
				reload_if_parent_item_changed: true
			});
		},
		qty: function (frm, cdt, cdn) {
			load_parent_bom(frm, locals[cdt][cdn], {
				reload_existing: true
			});
		},
		items_remove: function (frm) {
			remove_orphan_rows(frm);
		}
	});

	frappe.ui.form.on("Sales Order Item", {
		item_code: function (frm, cdt, cdn) {
			load_parent_bom(frm, locals[cdt][cdn], {
				reload_if_parent_item_changed: true
			});
		},
		qty: function (frm, cdt, cdn) {
			load_parent_bom(frm, locals[cdt][cdn], {
				reload_existing: true
			});
		},
		items_remove: function (frm) {
			remove_orphan_rows(frm);
		}
	});

	frappe.ui.form.on("Production BOM Item", {
		item_code: function (frm, cdt, cdn) {
			var row = locals[cdt][cdn];
			mark_bom_row_customized(frm, row);
			load_raw_material_details(frm, row);
		},
		qty: function (frm, cdt, cdn) {
			mark_bom_row_customized(frm, locals[cdt][cdn]);
			calculate_totals(frm);
		},
		rate: function (frm, cdt, cdn) {
			mark_bom_row_customized(frm, locals[cdt][cdn]);
			calculate_totals(frm);
		},
		production_bom_items_remove: function (frm) {
			setup_tracking(frm);
			(frm.doc[TABLE_FIELD] || []).forEach(function (row) {
				mark_bom_row_customized(frm, row);
			});
			calculate_totals(frm);
		}
	});

	window.worldshading_load_missing_production_boms = load_all_missing_boms;
})();
