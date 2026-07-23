(function () {
	function has_field(frm, fieldname) {
		return frm.fields_dict && frm.fields_dict[fieldname];
	}

	function show_workshop_progress(frm) {
		if (!has_field(frm, "production_progress_percent")) {
			return;
		}

		var progress = flt(frm.doc.production_progress_percent);
		if (progress < 0) {
			progress = 0;
		}
		if (progress > 100) {
			progress = 100;
		}

		frm.dashboard.add_progress(__("Workshop Progress"), [{
			title: __("{0}% work progress", [flt(progress, 2)]),
			width: progress + "%",
			progress_class: "progress-bar-info"
		}], __("{0}% work progress", [flt(progress, 2)]));
	}

	function open_team_schedule_dialog(frm, opts) {
		opts = opts || {};
		var workflow_mode = typeof opts.on_assigned === "function";

		var dialog = new frappe.ui.Dialog({
			title: __("Assign Work Team"),
			size: "large",
			fields: [{
				fieldtype: "Datetime",
				fieldname: "planned_start_date",
				label: __("Requested Start Date"),
				reqd: 1,
				default: frm.doc.planned_start_date
			}, {
				fieldtype: "Float",
				fieldname: "estimated_hours",
				label: __("Estimated Hours"),
				description: __("Examples: 1 = 1 hour, 0.5 = 30 minutes, 0.25 = 15 minutes."),
				reqd: 1,
				default: frm.doc.estimated_hours
			}, {
				fieldtype: "Column Break"
			}, {
				fieldtype: "Select",
				fieldname: "production_priority",
				label: __("Priority"),
				options: "\nLow\nMedium\nHigh\nUrgent",
				default: frm.doc.production_priority || "Medium"
			}, {
				fieldtype: "Link",
				fieldname: "production_team",
				label: __("Work Team"),
				options: "Work Team",
				reqd: 1,
				default: frm.doc.production_team
			}, {
				fieldtype: "Data",
				fieldname: "selected_start_datetime",
				hidden: 1
			}, {
				fieldtype: "Data",
				fieldname: "selected_end_datetime",
				hidden: 1
			}, {
				fieldtype: "Section Break",
				label: __("Schedule")
			}, {
				fieldtype: "HTML",
				fieldname: "schedule_action_html"
			}, {
				fieldtype: "HTML",
				fieldname: "availability_html"
			}],
			primary_action_label: workflow_mode ? __("Assign Team & Continue") : __("Assign Team"),
			primary_action: function () {
				assign_team_from_dialog(frm, dialog, function () {
					if (workflow_mode) {
						opts.on_assigned();
					}
				});
			}
		});

		if (workflow_mode) {
			dialog.$wrapper.on("hide.bs.modal", function () {
				if (!dialog._assignment_done && typeof opts.on_cancel === "function") {
					opts.on_cancel();
				}
			});
		}

		bind_schedule_dialog_events(frm, dialog);
		dialog.show();
		set_assign_enabled(dialog, false);
		render_schedule_prompt(dialog);
	}

	function bind_schedule_dialog_events(frm, dialog) {
		["production_team", "planned_start_date", "estimated_hours", "production_priority"].forEach(function (fieldname) {
			dialog.fields_dict[fieldname].$input.on("change", function () {
				if (dialog._setting_suggested_slot) {
					return;
				}
				invalidate_schedule_selection(dialog);
			});
		});

		dialog.fields_dict.schedule_action_html.$wrapper.on("click", ".ws-check-schedule", function () {
			load_schedule_context(frm, dialog);
		});

		dialog.fields_dict.availability_html.$wrapper.on("click", ".ws-use-suggested-start", function () {
			var start = $(this).attr("data-start");
			var end = $(this).attr("data-end");
			if (start) {
				dialog._setting_suggested_slot = true;
				dialog.set_value("selected_start_datetime", start);
				dialog.set_value("selected_end_datetime", end);
				setTimeout(function () {
					dialog._setting_suggested_slot = false;
				}, 300);
				dialog._slot_selected = true;
				set_assign_enabled(dialog, true);
				dialog.fields_dict.availability_html.$wrapper.find(".ws-selected-start").html(
					__("Selected Slot") + ": <b>" + frappe.utils.escape_html(format_schedule_datetime(start)) + "</b> " + __("to") + " <b>" + frappe.utils.escape_html(format_schedule_datetime(end)) + "</b>"
				);
			}
		});
	}

	function set_assign_enabled(dialog, enabled) {
		var $primary = dialog.get_primary_btn ? dialog.get_primary_btn() : dialog.$wrapper.find(".modal-footer .btn-primary");
		if (enabled) {
			$primary.prop("disabled", false).removeAttr("disabled").removeClass("disabled");
		} else {
			$primary.prop("disabled", true).attr("disabled", "disabled").addClass("disabled");
		}
	}

	function invalidate_schedule_selection(dialog) {
		dialog._slot_selected = false;
		dialog.set_value("selected_start_datetime", "");
		dialog.set_value("selected_end_datetime", "");
		set_assign_enabled(dialog, false);
		render_schedule_prompt(dialog, __("Schedule changed. Click Check Schedule again."));
	}

	function get_system_datetime(value) {
		if (!value) {
			return value;
		}

		if (/^\d{4}-\d{2}-\d{2}/.test(value)) {
			return value;
		}

		if (frappe.datetime && frappe.datetime.user_to_str) {
			return frappe.datetime.user_to_str(value);
		}

		return value;
	}

	function render_schedule_prompt(dialog, message) {
		dialog.fields_dict.schedule_action_html.$wrapper.html([
			'<button type="button" class="btn btn-default ws-check-schedule">',
				__("Check Schedule"),
			'</button>'
		].join(""));
		dialog.fields_dict.availability_html.$wrapper.html(
			'<div class="text-muted ws-schedule-message">' + frappe.utils.escape_html(message || __("Choose team, requested start date, and estimated hours, then click Check Schedule.")) + '</div>'
		);
	}

	function load_schedule_context(frm, dialog) {
		var values = dialog.get_values() || {};

		if (!values.production_team || !values.planned_start_date || flt(values.estimated_hours) <= 0) {
			render_schedule_context(dialog, {
				message: __("Select Work Team, Requested Start Date, and Estimated Hours, then check schedule.")
			});
			return;
		}

		if (dialog._checking_schedule) {
			return;
		}

		dialog._checking_schedule = true;
		dialog._slot_selected = false;
		set_assign_enabled(dialog, false);
		dialog.fields_dict.schedule_action_html.$wrapper.find(".ws-check-schedule").prop("disabled", true);
		dialog.fields_dict.availability_html.$wrapper.html(
			'<div class="text-muted ws-schedule-message">' + __("Checking availability...") + '</div>'
		);

		function finish_check() {
			dialog._checking_schedule = false;
			dialog.fields_dict.schedule_action_html.$wrapper.find(".ws-check-schedule").prop("disabled", false);
		}

		frappe.call({
			method: "worldshading.api.work_order_team.get_team_booking_dialog_data",
			args: {
				work_order: frm.doc.name,
				production_team: values.production_team,
				planned_start_date: get_system_datetime(values.planned_start_date),
				estimated_hours: values.estimated_hours,
				production_priority: values.production_priority
			},
			callback: function (r) {
				var data = r.message || {};
				render_schedule_context(dialog, data);
				finish_check();
			},
			error: function () {
				render_schedule_context(dialog, {
					message: __("Could not check schedule. Please try again.")
				});
				finish_check();
			}
		});
	}

	function render_schedule_context(dialog, data) {
		if (data.message) {
			dialog.fields_dict.availability_html.$wrapper.html(
				'<div class="text-muted ws-schedule-message">' + frappe.utils.escape_html(data.message) + '</div>'
			);
			return;
		}

		var html = [
			get_schedule_dialog_styles(),
			render_current_status(data.current_status || {}, data.selected_team_plan || {}),
			render_selected_team_schedule(data.schedule_rows || []),
			render_same_sales_order_work_orders(data.same_sales_order_work_orders || [])
		].join("");

		dialog.fields_dict.availability_html.$wrapper.html(html);
	}

	function render_current_status(status, plan) {
		var css_class = status.status === "Available" ? "ws-ok" : (status.status === "Overbooked" ? "ws-bad" : "ws-muted");
		var use_button = plan && plan.suggested_start
			? '<button type="button" class="btn btn-primary btn-sm ws-use-suggested-start" data-start="' + frappe.utils.escape_html(plan.suggested_start || "") + '" data-end="' + frappe.utils.escape_html(plan.suggested_end || "") + '">' + __("Use This Slot") + '</button>'
			: "";
		var slot_details = plan && plan.suggested_start
			? [
				'<div class="ws-slot-grid">',
					'<div>',
						'<div class="ws-slot-label">' + __("Available Start") + '</div>',
						'<div class="ws-slot-time">' + frappe.utils.escape_html(format_schedule_datetime(plan.suggested_start)) + '</div>',
						'<div class="ws-slot-weekday">' + frappe.utils.escape_html(format_schedule_weekday(plan.suggested_start)) + '</div>',
					'</div>',
					'<div>',
						'<div class="ws-slot-label">' + __("Available End") + '</div>',
						'<div class="ws-slot-time">' + frappe.utils.escape_html(format_schedule_datetime(plan.suggested_end)) + '</div>',
						'<div class="ws-slot-weekday">' + frappe.utils.escape_html(format_schedule_weekday(plan.suggested_end)) + '</div>',
					'</div>',
				'</div>'
			].join("")
			: "";
		var note = plan.message ? '<div class="ws-slot-note">' + frappe.utils.escape_html(plan.message) + '</div>' : "";

		return [
			'<div class="ws-booking-summary ' + css_class + '">',
				'<div class="ws-booking-title">' + __("Best Available Slot") + '</div>',
				'<div class="ws-slot-action-row">',
					'<div class="ws-slot-details">',
						slot_details,
					'</div>',
					'<div class="ws-slot-action">',
						use_button,
					'</div>',
				'</div>',
				note,
				'<div class="ws-selected-start"></div>',
			'</div>'
		].join("");
	}

	function render_selected_team_schedule(rows) {
		if (!rows.length) {
			return [
				'<h5>' + __("Current Team Schedule") + '</h5>',
				'<div class="text-muted ws-empty-schedule">' + __("No Work Orders are scheduled for this team on this date.") + '</div>'
			].join("");
		}

		var body = rows.map(function (row) {
			return [
				'<tr>',
					'<td><a href="#Form/Work Order/' + frappe.utils.escape_html(row.name) + '">' + frappe.utils.escape_html(row.name) + '</a></td>',
					'<td>' + frappe.utils.escape_html(row.production_item || "") + '</td>',
					'<td>' + frappe.utils.escape_html(row.production_priority || "") + '</td>',
					'<td>' + frappe.utils.escape_html(String(row.estimated_hours || "")) + '</td>',
					'<td>' + frappe.utils.escape_html(row.workflow_state || row.status || "") + '</td>',
					'<td>' + frappe.utils.escape_html(format_schedule_datetime(row.planned_start_date)) + '</td>',
					'<td>' + frappe.utils.escape_html(format_schedule_datetime(row.production_planned_end_datetime)) + '</td>',
				'</tr>'
			].join("");
		}).join("");

		return [
			'<h5>' + __("Current Team Schedule") + '</h5>',
			'<div class="table-responsive"><table class="table table-bordered table-condensed ws-booking-table">',
				'<thead><tr>',
					'<th>' + __("Work Order") + '</th>',
					'<th>' + __("Main Item") + '</th>',
					'<th>' + __("Priority") + '</th>',
					'<th>' + __("Estimated Hours") + '</th>',
					'<th>' + __("Status") + '</th>',
					'<th>' + __("Start") + '</th>',
					'<th>' + __("Completion") + '</th>',
				'</tr></thead>',
				'<tbody>' + body + '</tbody>',
			'</table></div>'
		].join("");
	}

	function format_schedule_datetime(value) {
		if (!value) {
			return "";
		}

		if (window.moment) {
			return moment(value).format("DD MMM YYYY, h:mm A");
		}

		return String(value).replace(/:\d{2}$/, "");
	}

	function format_schedule_weekday(value) {
		if (!value) {
			return "";
		}

		if (window.moment) {
			return moment(value).format("dddd");
		}

		return "";
	}

	function render_same_sales_order_work_orders(rows) {
		if (!rows.length) {
			return "";
		}

		var body = rows.map(function (row) {
			return [
				'<tr>',
					'<td><a href="#Form/Work Order/' + frappe.utils.escape_html(row.name) + '">' + frappe.utils.escape_html(row.name) + '</a></td>',
					'<td>' + frappe.utils.escape_html(row.production_item || "") + '</td>',
					'<td>' + frappe.utils.escape_html(row.status || "") + '</td>',
					'<td>' + frappe.utils.escape_html(row.production_team || "") + '</td>',
					'<td>' + frappe.utils.escape_html(row.team_booking_status || "") + '</td>',
				'</tr>'
			].join("");
		}).join("");

		return [
			'<h5>' + __("Same Sales Order") + '</h5>',
			'<p class="text-muted">' + __("Other Work Orders from the same Sales Order are shown for reference.") + '</p>',
			'<div class="table-responsive"><table class="table table-bordered table-condensed ws-booking-table">',
				'<thead><tr>',
					'<th>' + __("Work Order") + '</th>',
					'<th>' + __("Item") + '</th>',
					'<th>' + __("Status") + '</th>',
					'<th>' + __("Team") + '</th>',
					'<th>' + __("Booking") + '</th>',
				'</tr></thead>',
				'<tbody>' + body + '</tbody>',
			'</table></div>'
		].join("");
	}

	function assign_team_from_dialog(frm, dialog, on_success) {
		var values = dialog.get_values();
		if (!values) {
			return;
		}

		if (!values.production_team || !dialog._slot_selected || !values.selected_start_datetime) {
			frappe.msgprint(__("Please check schedule and select a valid slot before assigning."));
			return;
		}

		frappe.call({
			method: "worldshading.api.work_order_team.assign_team_schedule",
			args: {
				work_order: frm.doc.name,
				production_team: values.production_team,
				selected_start_datetime: get_system_datetime(values.selected_start_datetime),
				estimated_hours: values.estimated_hours,
				production_priority: values.production_priority
			},
			freeze: true,
			freeze_message: __("Assigning production team..."),
			callback: function (r) {
				var result = r.message || {};
				var work_orders = result.work_orders || [];
				var wip_warehouse = result.wip_warehouse || "";

				dialog._assignment_done = true;
				frappe.show_alert({
					message: __("Updated Work Orders: {0}", [work_orders.join(", ")]),
					indicator: "green"
				});
				dialog.hide();

				// Reload the (server-saved) document before any workflow transition runs on it,
				// otherwise apply_workflow would use a stale timestamp and fail.
				frappe.model.remove_from_locals(frm.doctype, frm.docname);
				frappe.model.with_doc(frm.doctype, frm.docname, function () {
					frm.refresh();

					// The "Schedule" workflow action re-submits the in-memory frm.doc on top of
					// what the backend saved. Set the WIP Warehouse on frm.doc AFTER refresh so
					// that submit carries the team warehouse instead of overwriting it.
					if (wip_warehouse && frm.doc && frm.doc.docstatus === 0) {
						frm.doc.wip_warehouse = wip_warehouse;
					}

					if (typeof on_success === "function") {
						on_success();
					}
				});
			}
		});
	}

	function get_schedule_dialog_styles() {
		return [
			'<style>',
				'.modal-dialog.modal-lg { width: 90%; max-width: 1100px; }',
				'.ws-booking-summary { padding: 9px 12px; border: 1px solid #d1d8dd; margin: 12px 0; }',
				'.ws-booking-summary .btn { margin-top: 0; }',
				'.ws-assistant-note { padding: 12px; border: 1px solid #d1d8dd; margin-bottom: 12px; background: #f8f9fa; }',
				'.ws-booking-title { font-weight: 600; margin-bottom: 4px; }',
				'.ws-slot-action-row { display: grid; grid-template-columns: minmax(360px, 1fr) auto; gap: 12px; align-items: center; margin-top: 8px; }',
				'.ws-slot-details { min-width: 0; }',
				'.ws-slot-action { text-align: right; white-space: nowrap; }',
				'.ws-slot-grid { display: grid; grid-template-columns: repeat(2, minmax(160px, 1fr)); gap: 10px; }',
				'.ws-slot-grid > div { border: 1px solid #cfe8d6; border-radius: 6px; padding: 10px 12px; background: rgba(255, 255, 255, 0.55); }',
				'.ws-slot-label { color: #6c7680; font-size: 12px; text-transform: uppercase; letter-spacing: .02em; }',
				'.ws-slot-time { font-size: 16px; font-weight: 600; margin-top: 2px; }',
				'.ws-slot-weekday { color: #8d99a6; font-size: 12px; margin-top: 2px; }',
				'.ws-slot-note { color: #6c7680; margin-top: 8px; }',
				'.ws-selected-start { margin-top: 4px; }',
				'@media (max-width: 767px) { .ws-slot-action-row { grid-template-columns: 1fr; } .ws-slot-action { text-align: left; } .ws-slot-grid { grid-template-columns: 1fr; } }',
				'.ws-schedule-message { padding: 10px 0; }',
				'.ws-recommendation-grid { display: grid; grid-template-columns: minmax(180px, 1fr) minmax(240px, 2fr) auto; gap: 12px; align-items: center; }',
				'.ws-recommendation-action { text-align: right; }',
				'.ws-ok { border-color: #b7e4c7; background: #f1fff5; }',
				'.ws-bad { border-color: #ffc9c9; background: #fff5f5; }',
				'.ws-muted { background: #f8f9fa; }',
				'.ws-ok-text { color: #087f5b; font-weight: 600; }',
				'.ws-bad-text { color: #c92a2a; font-weight: 600; }',
				'.ws-team-card-list { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 8px; margin-bottom: 14px; }',
				'.ws-team-card { border: 1px solid #d1d8dd; padding: 10px; display: grid; grid-template-columns: 1fr minmax(190px, auto) auto; gap: 10px; align-items: start; background: #fff; }',
				'.ws-team-card-main { min-width: 0; }',
				'.ws-empty-schedule { padding: 10px 12px; background: #f8f9fa; border: 1px solid #d1d8dd; margin-bottom: 14px; }',
				'.ws-booking-table td { vertical-align: top !important; }',
				'.ws-overlap-line { margin-bottom: 6px; }',
			'</style>'
		].join("");
	}

	function handle_schedule_workflow_action(frm) {
		return new Promise(function (resolve, reject) {
			open_team_schedule_dialog(frm, {
				on_assigned: function () {
					resolve();
				},
				on_cancel: function () {
					reject();
				}
			});
		});
	}

	frappe.ui.form.on("Work Order", {
		refresh: function (frm) {
			show_workshop_progress(frm);

			if (!frm.is_new()) {
				frm.add_custom_button(__("Assign Team"), function () {
					open_team_schedule_dialog(frm);
				});
			}
		},

		before_workflow_action: function (frm) {
			if (frm.selected_workflow_action === "Schedule") {
				return handle_schedule_workflow_action(frm);
			}
		},

		production_team: function (frm) {
			apply_team_warehouse_to_form(frm);
		}
	});

	function apply_team_warehouse_to_form(frm) {
		if (!frm.doc.production_team) {
			return;
		}

		// WIP Warehouse is read-only after submit; only sync it on a draft form.
		// (Submitted rescheduling is handled server-side in assign_team_schedule.)
		if (frm.doc.docstatus !== 0) {
			return;
		}

		frappe.db.get_value("Work Team", frm.doc.production_team, "warehouse", function (r) {
			var warehouse = r && r.warehouse;
			if (warehouse && frm.doc.wip_warehouse !== warehouse) {
				frm.set_value("wip_warehouse", warehouse);
			}
		});
	}
})();
