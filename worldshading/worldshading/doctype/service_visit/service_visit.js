// Copyright (c) 2026, Hilal Habeeb and contributors
// For license information, please see license.txt

frappe.ui.form.on("Service Visit", {

	refresh(frm) {
		calculate_total_charges(frm);
		ws_set_min_visit_date(frm.fields_dict.date);

		frm.make_methods = frm.make_methods || {};
		frm.make_methods["Quotation"] = function (frm) {
			frappe.model.open_mapped_doc({
				method: "worldshading.worldshading.doctype.service_visit.service_visit.make_quotation",
				frm: frm
			});
		};

		frm.add_custom_button(__("Check Availability"), function () {
			show_booking_dialog(frm);
		});

		if (!frm.is_new() && frm.doc.workflow_state === "Pending Payment") {
			frm.add_custom_button(__("Payment Entry"), function () {
				frappe.model.open_mapped_doc({
					method: "worldshading.worldshading.doctype.service_visit.service_visit.make_payment_entry",
					frm: frm
				});
			}, __("Create"));
		}
	}

});

frappe.ui.form.on("Service Charge Item", {

	amount(frm, cdt, cdn) {
		calculate_total_charges(frm);
	},

	service_charge_items_remove(frm) {
		calculate_total_charges(frm);
	}

});

function calculate_total_charges(frm) {

	let total = 0;

	(frm.doc.service_charge_items || []).forEach(row => {

		total += flt(row.amount);

	});

	frm.set_value("total_amount", total);

}


frappe.ui.form.on("Service Visit", {

    check_availability(frm) {
        show_booking_dialog(frm);
    }

});


function show_booking_dialog(frm) {

    let selected_time = "";

    const dialog = new frappe.ui.Dialog({

        title: __("Booking Assistance"),

        fields: [

            {
                fieldtype: "Date",
                fieldname: "visit_date",
                label: __("Visit Date"),
                reqd: 1,
                default: frm.doc.date
                    ? frm.doc.date.split(" ")[0]
                    : frappe.datetime.get_today()
            },

            {
                fieldtype: "Table",
                fieldname: "assigned_users",
                label: __("Taken By"),
                cannot_add_rows: false,
                in_place_edit: true,
                data: ws_get_existing_assigned_users(frm),
                on_setup(grid) {
                    ws_setup_dialog_user_grid(grid);
                },
                fields: [
                    {
                        fieldtype: "Link",
                        fieldname: "user",
                        label: __("User"),
                        options: "User",
                        in_list_view: 1,
                        reqd: 1
                    }
                ]
            },

            {
                fieldtype: "Button",
                fieldname: "load_schedule",
                label: __("Check Availability")
            },

            {
                fieldtype: "HTML",
                fieldname: "schedule_html"
            },

            {
                fieldtype: "Data",
                fieldname: "selected_time",
                label: __("Selected Time"),
                read_only: 1
            }

        ],

        primary_action_label: __("Save Schedule"),

        primary_action(values) {

            save_booking_schedule(frm, dialog, values, selected_time);
        }
    });

    dialog.show();

    ws_set_min_visit_date(dialog.fields_dict.visit_date);

    dialog.$wrapper.find(".modal-dialog").css({
        "max-width": "980px",
        "width": "calc(100% - 30px)"
    });

    ws_bind_schedule_dialog_events(frm, dialog, function (time) {
        selected_time = time;
    });
}


function load_staff_schedule(frm, dialog, on_select_time) {

    const visit_date = dialog.get_value("visit_date");
    const users = ws_get_dialog_assigned_users(dialog);

    if (!ws_validate_schedule_inputs(visit_date, users)) {
        return;
    }

    ws_set_schedule_loading(dialog, true);

    frappe.call({

        method: "worldshading.worldshading.doctype.service_visit.service_visit.get_staff_day_schedule",

        args: {
            visit_date: visit_date,
            user: JSON.stringify(users),
            current_service_visit: frm.doc.name
        },

        callback(r) {

            const data = r.message || {};

            ws_render_schedule(dialog, visit_date, data, on_select_time);
        },

        always() {
            ws_set_schedule_loading(dialog, false);
        }
    });
}


function ws_bind_schedule_dialog_events(frm, dialog, on_time_change, options) {

    options = options || {};

    function clear_selected_schedule() {

        const time = ws_clear_selected_time(dialog);

        ws_clear_schedule(dialog);
        on_time_change(time);

        if (options.on_clear) {
            options.on_clear();
        }
    }

    dialog.fields_dict.load_schedule.$input.on("click", function () {

        const time = ws_clear_selected_time(dialog);

        on_time_change(time);

        if (options.on_load) {
            options.on_load();
        }

        load_staff_schedule(frm, dialog, function (selected_time) {
            dialog.set_value("selected_time", selected_time);
            on_time_change(selected_time);

            if (options.on_select) {
                options.on_select();
            }
        });
    });

    dialog.fields_dict.visit_date.$input.on("change", clear_selected_schedule);
    dialog.fields_dict.assigned_users.$wrapper.on("change", clear_selected_schedule);
}


function save_booking_schedule(frm, dialog, values, selected_time) {

    const users = ws_get_dialog_assigned_users(dialog);

    if (!ws_validate_schedule_inputs(values.visit_date, users)) {
        return;
    }

    if (!selected_time) {
        frappe.msgprint(__("Please select an available time slot."));
        return;
    }

    frappe.call({

        method: "worldshading.worldshading.doctype.service_visit.service_visit.get_staff_day_schedule",

        args: {
            visit_date: values.visit_date,
            user: JSON.stringify(users),
            current_service_visit: frm.doc.name
        },

        freeze: true,
        freeze_message: __("Checking selected time slot..."),

        callback(r) {

            const slots = (r.message && r.message.slots) || [];
            const selected_slot = slots.find(row => row.time === selected_time);

            if (
                !selected_slot ||
                !selected_slot.available ||
                ws_is_past_slot(values.visit_date, selected_time)
            ) {
                frappe.msgprint(
                    __("Selected time is no longer available. Please load schedule again.")
                );
                return;
            }

            ws_apply_schedule_to_form(frm, values.visit_date, selected_time, users);

            frm.save().then(() => {
                dialog.hide();
                frappe.msgprint(__("Schedule updated successfully."));
            });
        }
    });
}


function ws_apply_schedule_to_form(frm, visit_date, selected_time, users) {

    frm.set_value("date", visit_date);
    frm.set_value("time", selected_time);

    frm.clear_table("assigned_users");

    users.forEach(user => {
        const child = frm.add_child("assigned_users");
        child.user = user;
    });

    frm.refresh_field("assigned_users");
}


function ws_render_schedule(dialog, visit_date, data, on_select_time) {

    const slots = data.slots || [];
    const summary = data.summary || [];
    const visible_slots = slots.filter(row => !ws_is_past_slot(visit_date, row.time));
    const html = [
        '<div class="ws-booking-schedule">',
        ws_get_schedule_styles(),
        ws_render_capacity_summary(summary),
        ws_render_slot_table(visible_slots),
        '</div>'
    ].join("");

    const $wrapper = dialog.fields_dict.schedule_html.$wrapper;

    $wrapper.html(html);
    $wrapper.find(".ws-select-slot").on("click", function () {

        const time = $(this).attr("data-time");

        on_select_time(time);

        $wrapper.find(".ws-select-slot")
            .removeClass("btn-success")
            .addClass("btn-primary")
            .text(__("Select"));

        $(this)
            .removeClass("btn-primary")
            .addClass("btn-success")
            .text(__("Selected"));
    });
}


function ws_render_capacity_summary(summary) {

    let html = `
        <div class="ws-capacity-panel">
            <div class="ws-panel-title">${__("Selected Staff Capacity")}</div>
    `;

    summary.forEach(row => {

        const status_class = row.daily_available ? "ws-status-available" : "ws-status-unavailable";
        const status_text = row.daily_available ? __("Available") : __("Daily Limit Reached");

        html += `
            <div class="ws-capacity-row">
                ${ws_render_ellipsis(row.user, "ws-capacity-user")}
                <div class="ws-capacity-detail">
                    <b>${row.booked || 0}</b> / <b>${row.max_visits || 0}</b>
                    <span class="ws-detail-separator">|</span>
                    ${__("Remaining")}: <b>${row.remaining || 0}</b>
                    <span class="ws-detail-separator">|</span>
                    <span class="${status_class}">${status_text}</span>
                </div>
            </div>
        `;
    });

    return html + "</div>";
}


function ws_render_slot_table(slots) {

    if (!slots.length) {
        return `
            <div class="ws-no-slots">
                ${__("No remaining time slots available for this date.")}
            </div>
        `;
    }

    let html = `
        <div class="ws-slot-table-wrapper">
            <table class="table table-bordered ws-slot-table">
                <thead>
                    <tr>
                        <th>${__("Time Slot")}</th>
                        <th>${__("Status")}</th>
                        <th>${__("Taken By")}</th>
                        <th>${__("Service Visit")}</th>
                        <th>${__("Customer")}</th>
                        <th>${__("Workflow")}</th>
                        <th>${__("Action")}</th>
                    </tr>
                </thead>
                <tbody>
    `;

    slots.forEach(row => {

        const bookings = row.bookings || [];
        const service_visit_bookings = ws_get_unique_service_visit_bookings(bookings);
        const row_class = row.available ? "ws-slot-available" : "ws-slot-unavailable";
        const status_class = row.available ? "ws-status-available" : "ws-status-unavailable";
        const status_text = row.available ? __("Available") : __(row.reason || "Booked");
        const action = row.available
            ? `<button type="button" class="btn btn-xs btn-primary ws-select-slot"
                    data-time="${ws_escape_html(row.time)}">${__("Select")}</button>`
            : '<button type="button" class="btn btn-xs btn-default ws-slot-disabled" disabled>--</button>';

        html += `
            <tr class="${row_class}">
                <td><b>${ws_escape_html(row.time)}</b></td>
                <td><span class="${status_class}">${ws_escape_html(status_text)}</span></td>
                <td>${ws_render_booking_lines(bookings, "user", "ws-col-taken-by")}</td>
                <td>${ws_render_booking_lines(service_visit_bookings, "service_visit", "ws-col-service-visit")}</td>
                <td>${ws_render_booking_lines(service_visit_bookings, "customer_name", "ws-col-customer")}</td>
                <td>${ws_render_booking_lines(service_visit_bookings, "workflow_state", "ws-col-workflow")}</td>
                <td>${action}</td>
            </tr>
        `;
    });

    return html + "</tbody></table></div>";
}


function ws_get_unique_service_visit_bookings(bookings) {

    const service_visits = [];

    return bookings.filter(row => {

        if (!row.service_visit || service_visits.indexOf(row.service_visit) !== -1) {
            return false;
        }

        service_visits.push(row.service_visit);

        return true;
    });
}


function ws_render_booking_lines(bookings, fieldname, class_name, fallback_fieldname) {

    if (!bookings.length) {
        return ws_render_ellipsis("", class_name);
    }

    return bookings.map(row => {

        const value = row[fieldname] || row[fallback_fieldname] || "";

        return ws_render_ellipsis(value, class_name + " ws-booking-line");
    }).join("");
}


function ws_render_ellipsis(value, class_name) {

    const escaped_value = ws_escape_html(value || "");

    return `<div class="ws-ellipsis ${class_name}" title="${escaped_value}">${escaped_value}</div>`;
}


function ws_get_schedule_styles() {

    return `
        <style>
            .ws-booking-schedule { margin-top: 12px; }
            .ws-capacity-panel {
                padding: 12px;
                margin-bottom: 14px;
                background: #f8f9fa;
                border: 1px solid #dfe3e8;
                border-radius: 8px;
            }
            .ws-panel-title { margin-bottom: 8px; font-size: 14px; font-weight: 700; }
            .ws-capacity-row {
                display: flex;
                justify-content: space-between;
                gap: 10px;
                padding: 6px 0;
                border-bottom: 1px solid #edf0f2;
                font-size: 13px;
            }
            .ws-capacity-row:last-child { border-bottom: 0; }
            .ws-capacity-user { max-width: 420px; font-weight: 600; }
            .ws-capacity-detail { text-align: right; }
            .ws-detail-separator { padding: 0 6px; color: #8d99a6; }
            .ws-status-available { color: #16813d; font-weight: 700; }
            .ws-status-unavailable { color: #c53030; font-weight: 700; }
            .ws-no-slots {
                padding: 12px;
                color: #8a5a00;
                background: #fff7e6;
                border: 1px solid #ffd591;
                border-radius: 8px;
                font-weight: 600;
            }
            .ws-slot-table-wrapper {
                width: 100%;
                overflow-x: hidden;
            }
            .ws-slot-table {
                width: 100%;
                max-width: 100%;
                margin-bottom: 0;
                table-layout: fixed;
                font-size: 13px;
            }
            .ws-slot-table th, .ws-slot-table td {
                padding: 7px 8px;
                overflow: hidden;
            }
            .ws-slot-table th:nth-child(1) { width: 18%; }
            .ws-slot-table th:nth-child(2) { width: 12%; }
            .ws-slot-table th:nth-child(3) { width: 17%; }
            .ws-slot-table th:nth-child(4) { width: 12%; }
            .ws-slot-table th:nth-child(5) { width: 18%; }
            .ws-slot-table th:nth-child(6) { width: 14%; }
            .ws-slot-table th:nth-child(7) { width: 9%; }
            .ws-slot-available { background: #f7fff7; }
            .ws-slot-unavailable { background: #fff7f7; }
            .ws-ellipsis {
                overflow: hidden;
                text-overflow: ellipsis;
                white-space: nowrap;
            }
            .ws-col-taken-by, .ws-col-service-visit,
            .ws-col-customer, .ws-col-workflow { max-width: 100%; }
            .ws-booking-line { margin-bottom: 3px; }
            .ws-booking-line:last-child { margin-bottom: 0; }
            .ws-select-slot, .ws-slot-disabled {
                width: 100%;
                min-width: 0;
                padding-left: 4px;
                padding-right: 4px;
            }
        </style>
    `;
}


function ws_validate_schedule_inputs(visit_date, users) {

    if (!visit_date) {
        frappe.msgprint(__("Please select Visit Date."));
        return false;
    }

    if (!users.length) {
        frappe.msgprint(__("Please add at least one Taken By user."));
        return false;
    }

    return true;
}


function ws_set_min_visit_date(date_field) {

    if (!date_field || !date_field.datepicker) {
        return;
    }

    date_field.datepicker.update(
        "minDate",
        frappe.datetime.str_to_obj(frappe.datetime.get_today())
    );
}


function ws_get_existing_assigned_users(frm) {

    return (frm.doc.assigned_users || [])
        .filter(row => row.user)
        .map(row => {
            return {
                name: ws_get_dialog_row_name(),
                user: row.user
            };
        });
}


function ws_setup_dialog_user_grid(grid) {

    const add_new_row = grid.add_new_row.bind(grid);

    grid.add_new_row = function () {

        add_new_row.apply(grid, arguments);

        const rows = grid.df.data || [];
        const new_row = rows[rows.length - 1];

        if (new_row && !new_row.name) {
            new_row.name = ws_get_dialog_row_name();
            grid.refresh();
        }
    };
}


function ws_get_dialog_row_name() {

    return "new-service-visit-user-" + frappe.utils.get_random(10);
}


function ws_clear_selected_time(dialog) {

    dialog.set_value("selected_time", "");

    return "";
}


function ws_clear_schedule(dialog) {

    dialog.fields_dict.schedule_html.$wrapper.html("");
}


function ws_set_slot_availability_collapsed(dialog, collapsed) {

    const schedule_field = dialog.fields_dict.schedule_html;

    if (schedule_field && schedule_field.section) {
        schedule_field.section.collapse(collapsed);
    }
}


function ws_set_schedule_loading(dialog, loading) {

    const $button = dialog.fields_dict.load_schedule.$input;

    $button.prop("disabled", loading);
    $button.text(loading ? __("Loading...") : __("Check Availability"));

    if (loading) {
        dialog.fields_dict.schedule_html.$wrapper.html(
            `<div class="text-muted" style="padding: 12px 0;">${__("Loading schedule...")}</div>`
        );
    }
}


function ws_get_dialog_assigned_users(dialog) {

    let users = [];
    let grid_data = [];

    if (
        dialog.fields_dict.assigned_users &&
        dialog.fields_dict.assigned_users.grid
    ) {
        grid_data = dialog.fields_dict.assigned_users.grid.get_data() || [];
    }

    grid_data.forEach(row => {

        if (row.user && users.indexOf(row.user) === -1) {
            users.push(row.user);
        }
    });

    return users;
}


function ws_escape_html(value) {

    return String(value || "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;");
}


function ws_is_past_slot(visit_date, slot) {

    let today = frappe.datetime.get_today();

    if (visit_date !== today) {
        return false;
    }

    let end_time = slot.split(" to ")[1];

    let slot_date = ws_make_datetime(visit_date, end_time);

    if (!slot_date) {
        return false;
    }

    let now = new Date();

    return slot_date <= now;
}


function ws_make_datetime(visit_date, time_text) {

    let match = time_text.match(/^(\d{1,2}):(\d{2})\s?(AM|PM)$/i);

    if (!match) {
        return null;
    }

    let hour = parseInt(match[1]);
    let minute = parseInt(match[2]);
    let ampm = match[3].toUpperCase();

    if (ampm === "PM" && hour !== 12) {
        hour = hour + 12;
    }

    if (ampm === "AM" && hour === 12) {
        hour = 0;
    }

    let parts = visit_date.split("-");

    return new Date(
        parseInt(parts[0]),
        parseInt(parts[1]) - 1,
        parseInt(parts[2]),
        hour,
        minute,
        0
    );
}


frappe.ui.form.on("Service Visit", {

    before_workflow_action(frm) {

        const action = frm.selected_workflow_action;
        const state = frm.doc.workflow_state;


        if (
            ["Pending Schedule", "Pending Schedule - Follow Up"].includes(state)
            && action === "Schedule Appointment"
        ) {
        
            let missing = [];
        
            if (!frm.doc.customer) {
                missing.push("Customer");
            }
            
            // Charges table
            if (
                !frm.doc.service_charge_items ||
                frm.doc.service_charge_items.length === 0
            ) {
                missing.push("Charges");
            } else {
            
                frm.doc.service_charge_items.forEach((row, index) => {
            
                    if (
                        row.amount === undefined ||
                        row.amount === null ||
                        row.amount === ""
                    ) {
                        missing.push("Charges Row " + (index + 1) + " Amount");
                    }
                });
            }
            
            if (missing.length) {
        
                frappe.validated = false;
        
                frappe.msgprint({
                    title: __("Required Fields Missing"),
                    indicator: "red",
                    message: missing
                        .map(d => "• " + d)
                        .join("<br>")
                });
        
                return new Promise(() => {
                    // Do not resolve.
                    // This blocks the workflow action.
                });
            }
        
            frappe.validated = false;
        
            return new Promise((resolve) => {
        
                open_schedule_popup({
        
                    frm,
                    resolve,
        
                    title:
                        "Schedule Appointment",
        
                    info_text:
                        "Please update the schedule date after contacting the customer.",
        
                    datetime_label:
                        "Visit Schedule Date",
        
                    comment_label:
                        "Call Note",
        
                    comment_title:
                        "Schedule Note"
                });
            });
        }
        // ==================================================
        // Reschedule Visit
        // ==================================================
        if (
            (
                state === "Pending Confirmation" ||
                state === "Pending Reschedule"
            )
            && action === "Reschedule Visit"
        ) {
        
            frappe.validated = false;
        
            return new Promise((resolve) => {
        
                open_schedule_popup({
        
                    frm,
                    resolve,
        
                    title:
                        "Reschedule Visit",
        
                    info_text:
                        "Please update the new visit schedule date after contacting the customer.",
        
                    datetime_label:
                        "New Visit Schedule Date",
        
                    comment_label:
                        "Reschedule Reason",
        
                    comment_title:
                        "Reschedule Note"
                });
            });
        }
        // ==================================================
        // Confirm Appointment Popup
        // ==================================================
        
        if (
            state === "Pending Confirmation"
            && action === "Confirm Appointment"
        ) {
        
            frappe.validated = false;
        
            return new Promise((resolve) => {
        
                const formatted_date = frappe.datetime.str_to_user(
                    frm.doc.date
                );
                
                const appointment_text =
                    formatted_date + " at " + (frm.doc.time || "");
        
                const dialog = new frappe.ui.Dialog({
        
                    title: __("Confirm Appointment"),
        
                    fields: [
        
                        {
                            fieldtype: "HTML",
                            fieldname: "confirmation_info",
        
                            options: `
                                <div style="
                                    margin-bottom: 12px;
                                    font-size: 13px;
                                    color: #666;
                                ">
                                    Please confirm that the customer verified the appointment for:

        
                                    <b>${appointment_text}</b>
                                </div>
                            `
                        },
        
                        {
                            fieldtype: "Small Text",
                            fieldname: "confirmation_note",
                            label: __("Confirmation Note")
                        }
        
                    ],
        
                    primary_action_label: __("Confirm & Continue"),
        
                    primary_action(values) {
        
                        let comment =
                            "Customer verified the visit for "
                            + appointment_text + ".";
        
                        if (values.confirmation_note) {
        
                            comment +=
                                "<br><br><b>Confirmation Note:</b><br>"
                                + values.confirmation_note;
                        }
        
                        frappe.call({
        
                            method:
                                "frappe.desk.form.utils.add_comment",
        
                            args: {
        
                                reference_doctype:
                                    frm.doctype,
        
                                reference_name:
                                    frm.doc.name,
        
                                content: comment,
        
                                comment_email:
                                    frappe.session.user
                            },
        
                            callback() {
        
                                dialog.hide();
        
                                frappe.validated = true;
        
                                resolve();
                            }
                        });
                    }
                });
        
                dialog.show();
            });
        }
        // ==================================================
        // Complete Visit Popup
        // ==================================================
        
        if (
            state === "Out For Visit" &&
            action === "Complete Visit"
        ) {
            frappe.validated = false;

            return new Promise((resolve) => {

                let uploaded_files = [];

                const dialog = new frappe.ui.Dialog({

                    title: __("Visit Completion"),

                    size: "large",

                    fields: [

                        {
                            fieldtype: "HTML",
                            fieldname: "uploader"
                        }

                    ],

                    primary_action_label: __("Complete Visit"),

                    primary_action() {

                        // --------------------------------------------------
                        // Validate Upload
                        // --------------------------------------------------

                        if (!uploaded_files.length) {

                            frappe.msgprint(
                                __("Please upload at least one file.")
                            );

                            return;
                        }

                        dialog.set_primary_action(
                            __("Processing..."),
                            null
                        );

                        // --------------------------------------------------
                        // Merge Documents
                        // --------------------------------------------------

                        frappe.call({

                            method: "worldshading.api.utility.merge_documents",

                            args: {
                                file_names: uploaded_files,

                                output_filename:
                                    `Service Visit - ${frm.doc.name}`,

                                attach_to_doctype: "Service Visit",

                                attach_to_name: frm.doc.name,

                                cleanup_originals: 1,

                                is_private: 0
                            },

                            freeze: true,

                            freeze_message: __("Generating report..."),

                            callback: function(r) {

                                if (!r.message || !r.message.success) {

                                    frappe.msgprint(
                                        __("Failed to generate report.")
                                    );

                                    dialog.set_primary_action(
                                        __("Complete Visit"),
                                        dialog.primary_action
                                    );

                                    return;
                                }

                                dialog.hide();

                                frappe.show_alert({
                                    message: __("Visit Report Generated"),
                                    indicator: "green"
                                });

                                frappe.validated = true;

                                resolve();
                            }
                        });
                    }
                });

                dialog.show();

                // --------------------------------------------------
                // Upload Area
                // --------------------------------------------------

                const wrapper = dialog.fields_dict.uploader.$wrapper;

                wrapper.html(`

                    <div id="upload-section"></div>

                    <div id="add-more-container"></div>

                    <div id="uploaded-files"
                        style="
                            margin-top:15px;
                        ">
                    </div>

                `);

                // --------------------------------------------------
                // Render Embedded Uploader
                // --------------------------------------------------

                function render_uploader() {
                
                    const upload_section =
                        wrapper.find("#upload-section");
                
                    // --------------------------------------------------
                    // Clear old uploader completely
                    // --------------------------------------------------
                
                    upload_section.empty();
                
                    // --------------------------------------------------
                    // Hide Add More button while uploader active
                    // --------------------------------------------------
                
                    wrapper.find("#add-more-container").hide();
                
                    // --------------------------------------------------
                    // Create uploader
                    // --------------------------------------------------
                
                    new frappe.ui.FileUploader({
                
                        wrapper: upload_section,
                
                        allow_multiple: true,
                
                        on_success(file) {
                
                            uploaded_files.push(file.name);
                
                            // --------------------------------------------------
                            // Add File Row
                            // --------------------------------------------------
                
                            wrapper.find("#uploaded-files").append(`
                
                                <div style="
                                    display:flex;
                                    align-items:center;
                                    gap:10px;
                                    padding:10px 12px;
                                    margin-bottom:8px;
                                    background:#f8f9fa;
                                    border-radius:8px;
                                    font-size:13px;
                                ">
                
                                    <span style="font-size:16px;">
                                        📎
                                    </span>
                
                                    <div style="
                                        flex:1;
                                        overflow:hidden;
                                        text-overflow:ellipsis;
                                        white-space:nowrap;
                                    ">
                
                                        ${file.file_name}
                
                                    </div>
                
                                </div>
                
                            `);
                
                            frappe.show_alert({
                                message:
                                    __("Uploaded: ") + file.file_name,
                                indicator: "green"
                            });
                
                            // --------------------------------------------------
                            // Remove uploader after upload
                            // --------------------------------------------------
                
                            upload_section.empty();
                
                            // --------------------------------------------------
                            // Show Add More button again
                            // --------------------------------------------------
                
                            wrapper.find("#add-more-container").html(`
                
                                <div style="
                                    margin-top:15px;
                                    text-align:center;
                                ">
                
                                    <button
                                        class="btn btn-default btn-sm"
                                        id="add-more-files"
                                    >
                
                                        + Add More Files
                
                                    </button>
                
                                </div>
                
                            `).show();
                
                        }
                    });
                }

                // --------------------------------------------------
                // Initial uploader
                // --------------------------------------------------

                render_uploader();

                // --------------------------------------------------
                // Add More Click
                // --------------------------------------------------

                wrapper.on("click", "#add-more-files", function() {
                
                    // --------------------------------------------------
                    // Fully recreate upload section
                    // --------------------------------------------------
                
                    wrapper.find("#upload-section").remove();
                
                    wrapper.find("#add-more-container").before(`
                        <div id="upload-section"></div>
                    `);
                
                    render_uploader();
                
                });

            });
        }
        // ==================================================
        // Create Quotation
        // ==================================================
        
        if (
            state === "Pending Quotation"
            && action === "Create Quotation"
        ) {
        
            frappe.validated = false;
        
            return new Promise((resolve) => {
        
                frappe.model.open_mapped_doc({
        
                    method:
                        "worldshading.worldshading.doctype.service_visit.service_visit.make_quotation",
        
                    frm: frm
                });
        
                // IMPORTANT:
                // Intentionally DO NOT resolve().
                // Workflow must remain in current state
                // until quotation is actually created/submitted.
            });
        }
        
        
    }
});


function ws_save_workflow_schedule(options) {

    if (options.dialog._ws_schedule_processing) {
        return;
    }

    ws_set_workflow_schedule_processing(options.dialog, true);

    frappe.call({

        method: "worldshading.worldshading.doctype.service_visit.service_visit.get_staff_day_schedule",

        args: {
            visit_date: options.values.visit_date,
            user: JSON.stringify(options.users),
            current_service_visit: options.frm.doc.name
        },

        freeze: true,
        freeze_message: __("Checking selected time slot..."),

        callback(r) {

            const slots = (r.message && r.message.slots) || [];
            const selected_slot = slots.find(row => row.time === options.selected_time);

            if (
                !selected_slot ||
                !selected_slot.available ||
                ws_is_past_slot(options.values.visit_date, options.selected_time)
            ) {
                frappe.msgprint(
                    __("Selected time is no longer available. Please load schedule again.")
                );
                ws_set_workflow_schedule_processing(options.dialog, false);
                return;
            }

            ws_get_workflow_reference_image(options, function (reference_image_url) {
                ws_complete_workflow_schedule(options, reference_image_url);
            });
        },

        error() {
            ws_set_workflow_schedule_processing(options.dialog, false);
        }
    });
}


function ws_get_workflow_reference_image(options, callback) {

    if (!options.uploaded_files.length) {
        callback("");
        return;
    }

    frappe.call({

        method: "worldshading.api.utility.merge_documents",

        args: {
            file_names: options.uploaded_files,
            output_filename: `Service Visit Reference - ${options.frm.doc.name}`,
            attach_to_doctype: "Service Visit",
            attach_to_name: options.frm.doc.name,
            cleanup_originals: 1,
            is_private: 0
        },

        freeze: true,
        freeze_message: __("Generating reference image..."),

        callback(r) {

            if (!r.message || !r.message.success) {
                frappe.msgprint(__("Failed to generate reference image."));
                ws_set_workflow_schedule_processing(options.dialog, false);
                return;
            }

            const reference_image_url =
                r.message.file_url
                || r.message.merged_file_url
                || r.message.url
                || "";

            callback(reference_image_url);
        },

        error() {
            ws_set_workflow_schedule_processing(options.dialog, false);
        }
    });
}


function ws_complete_workflow_schedule(options, reference_image_url) {

    const validity_date = frappe.datetime.add_months(
        options.values.visit_date,
        1
    );

    ws_apply_schedule_to_form(
        options.frm,
        options.values.visit_date,
        options.selected_time,
        options.users
    );

    options.frm.set_value("validity_date", validity_date);
    options.frm.set_value(
        "reference_image",
        reference_image_url || options.frm.doc.reference_image || ""
    );

    if (ws_should_update_schedule_on_server(options.frm)) {
        ws_update_workflow_schedule_on_server(
            options,
            validity_date,
            reference_image_url
        );
        return;
    }

    options.frm.save(
        null,
        function (r) {

            if (r && r.exc) {
                ws_set_workflow_schedule_processing(options.dialog, false);
                return;
            }

            ws_add_workflow_schedule_comment(options);
        },
        null,
        function () {
            ws_set_workflow_schedule_processing(options.dialog, false);
        }
    );
}


function ws_should_update_schedule_on_server(frm) {

    return (
        cint(frm.doc.docstatus) === 1 ||
        frm.doc.workflow_state === "Pending Confirmation" ||
        frm.doc.workflow_state === "Pending Reschedule"
    );
}


function ws_update_workflow_schedule_on_server(options, validity_date, reference_image_url) {

    frappe.call({

        method: "worldshading.worldshading.doctype.service_visit.service_visit.update_service_visit_workflow_schedule",

        args: {
            service_visit: options.frm.doc.name,
            visit_date: options.values.visit_date,
            selected_time: options.selected_time,
            users: JSON.stringify(options.users),
            validity_date: validity_date,
            reference_image: reference_image_url || options.frm.doc.reference_image || ""
        },

        freeze: true,
        freeze_message: __("Updating schedule..."),

        callback(r) {

            if (r.exc) {
                ws_set_workflow_schedule_processing(options.dialog, false);
                return;
            }

            if (r.message) {
                options.frm.doc.docstatus = r.message.docstatus;
                options.frm.doc.workflow_state = r.message.workflow_state;
                options.frm.doc.skip_confirmation = r.message.skip_confirmation;
                options.frm.doc.visit_coordinator = r.message.visit_coordinator;
            }

            options.frm.doc.__unsaved = 0;
            ws_add_workflow_schedule_comment(options);
        },

        error() {
            ws_set_workflow_schedule_processing(options.dialog, false);
        }
    });
}


function ws_add_workflow_schedule_comment(options) {

    if (!options.values.call_note) {
        ws_continue_schedule_workflow(options);
        return;
    }

    frappe.call({

        method: "frappe.desk.form.utils.add_comment",

        args: {
            reference_doctype: options.frm.doctype,
            reference_name: options.frm.doc.name,
            content:
                "<b>" + options.comment_title + ":</b><br>"
                + options.values.call_note,
            comment_email: frappe.session.user
        },

        callback() {
            ws_continue_schedule_workflow(options);
        },

        error() {
            ws_set_workflow_schedule_processing(options.dialog, false);
        }
    });
}


function ws_continue_schedule_workflow(options) {

    options.dialog.hide();
    frappe.validated = true;
    options.resolve();
}


function ws_set_workflow_schedule_processing(dialog, processing) {

    dialog._ws_schedule_processing = processing;

    const $primary_button = dialog.get_primary_btn();

    $primary_button.prop("disabled", processing);
    $primary_button.text(processing ? __("Processing...") : __("Save & Continue"));
}


function open_schedule_popup({

    frm,
    resolve,

    title,
    info_text,

    datetime_label,

    comment_label,
    comment_title

}) {

    let uploaded_files = [];
    let selected_time = "";

    const dialog = new frappe.ui.Dialog({

        title: __(title),

        size: "large",

        fields: [

            {
                fieldtype: "HTML",
                fieldname: "schedule_info",
                options: `
                    <div style="
                        margin-bottom: 12px;
                        font-size: 13px;
                        color: #666;
                    ">
                        ${info_text}
                    </div>
                `
            },

            {
                fieldtype: "Date",
                fieldname: "visit_date",
                label: __(datetime_label),
                reqd: 1,
                default: frm.doc.date
            },

            {
                fieldtype: "Table",
                fieldname: "assigned_users",
                label: __("Taken By"),
                cannot_add_rows: false,
                in_place_edit: true,
                data: ws_get_existing_assigned_users(frm),
                on_setup(grid) {
                    ws_setup_dialog_user_grid(grid);
                },
                fields: [
                    {
                        fieldtype: "Link",
                        fieldname: "user",
                        label: __("User"),
                        options: "User",
                        in_list_view: 1,
                        reqd: 1
                    }
                ]
            },

            {
                fieldtype: "Button",
                fieldname: "load_schedule",
                label: __("Check Availability")
            },

            {
                fieldtype: "Section Break",
                fieldname: "slot_availability_section",
                label: __("Slot Availability"),
                collapsible: 1
            },

            {
                fieldtype: "HTML",
                fieldname: "schedule_html"
            },

            {
                fieldtype: "Section Break",
                fieldname: "schedule_details_section"
            },

            {
                fieldtype: "Data",
                fieldname: "selected_time",
                label: __("Selected Time"),
                read_only: 1,
                description: __("Requested Time Slot: {0}", [frm.doc.time || __("Not scheduled")])
            },

            {
                fieldtype: "HTML",
                fieldname: "reference_uploader"
            },

            {
                fieldtype: "Small Text",
                fieldname: "call_note",
                label: __(comment_label)
            }
        ],

        primary_action_label: __("Save & Continue"),

        primary_action(values) {

            const users = ws_get_dialog_assigned_users(dialog);

            if (!ws_validate_schedule_inputs(values.visit_date, users)) {
                return;
            }

            if (!selected_time) {
                frappe.msgprint(__("Please select an available time slot."));
                return;
            }

            ws_save_workflow_schedule({
                frm,
                dialog,
                resolve,
                values,
                users,
                selected_time,
                uploaded_files,
                comment_title
            });
        }
    });

    dialog.show();

    ws_set_min_visit_date(dialog.fields_dict.visit_date);

    ws_bind_schedule_dialog_events(
        frm,
        dialog,
        function (time) {
            selected_time = time;
        },
        {
            on_load() {
                ws_set_slot_availability_collapsed(dialog, false);
            },
            on_select() {
                ws_set_slot_availability_collapsed(dialog, true);
            },
            on_clear() {
                ws_set_slot_availability_collapsed(dialog, true);
            }
        }
    );

    const wrapper =
        dialog.fields_dict.reference_uploader.$wrapper;

    wrapper.html(`

        <div style="
            margin-top: 10px;
            margin-bottom: 8px;
            font-weight: 600;
            font-size: 13px;
        ">
            Reference Image / Files
        </div>

        <div id="upload-section"></div>

        <div id="add-more-container"></div>

        <div id="uploaded-files"
            style="
                margin-top:15px;
            ">
        </div>

    `);

    function render_uploader() {

        const upload_section =
            wrapper.find("#upload-section");

        upload_section.empty();

        wrapper.find("#add-more-container").hide();

        new frappe.ui.FileUploader({

            wrapper: upload_section,

            allow_multiple: true,

            on_success(file) {

                uploaded_files.push(file.name);

                wrapper.find("#uploaded-files").append(`

                    <div style="
                        display:flex;
                        align-items:center;
                        gap:10px;
                        padding:10px 12px;
                        margin-bottom:8px;
                        background:#f8f9fa;
                        border-radius:8px;
                        font-size:13px;
                    ">

                        <span style="font-size:16px;">
                            📎
                        </span>

                        <div style="
                            flex:1;
                            overflow:hidden;
                            text-overflow:ellipsis;
                            white-space:nowrap;
                        ">
                            ${file.file_name}
                        </div>

                    </div>

                `);

                frappe.show_alert({
                    message: __("Uploaded: ") + file.file_name,
                    indicator: "green"
                });

                upload_section.empty();

                wrapper.find("#add-more-container").html(`

                    <div style="
                        margin-top:15px;
                        text-align:center;
                    ">

                        <button
                            class="btn btn-default btn-sm"
                            id="add-more-reference-files"
                            type="button"
                        >
                            + Add More Files
                        </button>

                    </div>

                `).show();
            }
        });
    }

    render_uploader();

    wrapper.on("click", "#add-more-reference-files", function(e) {

        e.preventDefault();

        wrapper.find("#upload-section").remove();

        wrapper.find("#add-more-container").before(`
            <div id="upload-section"></div>
        `);

        render_uploader();
    });
}
frappe.ui.form.on("Service Visit", {

    refresh: function(frm) {

        frm.add_custom_button(__("WhatsApp"), function() {
        
            let default_message =
        `Hello ${frm.doc.customer_name},
        
        Your service visit has been scheduled for:
        
        ${frappe.datetime.str_to_user(frm.doc.date)}
        
        Thank you,
        World Shading`;
        
            let dialog = new frappe.ui.Dialog({
        
                title: __("Send WhatsApp Message"),
        
                fields: [
        
                    {
                        fieldtype: "Data",
                        fieldname: "whatsapp_no",
                        label: __("WhatsApp Number"),
                        reqd: 1,
                        default: frm.doc.whatsapp_no || frm.doc.mobile_number
                    },
        
                    {
                        fieldtype: "Small Text",
                        fieldname: "message",
                        label: __("Message"),
                        reqd: 1,
                        default: default_message
                    }
        
                ],
        
                primary_action_label: __("Send"),
        
                primary_action(values) {
        
                    open_whatsapp_chat(
                        values.whatsapp_no,
                        values.message
                    );
        
                    dialog.hide();
                }
            });
        
            dialog.show();
        
        });
    }
});

function open_whatsapp_chat(mobile, message) {

    if (!mobile) {
        frappe.msgprint("WhatsApp number not found");
        return;
    }

    // Clean number
    mobile = mobile.replace(/\D/g, "");

    // Bahrain default
    if (!mobile.startsWith("973")) {
        mobile = "973" + mobile;
    }

    let whatsapp_url =
        "https://wa.me/" +
        mobile +
        "?text=" +
        encodeURIComponent(message);

    window.open(whatsapp_url, "_blank");
}
