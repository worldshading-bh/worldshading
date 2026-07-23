frappe.views.calendar["Service Visit"] = {
    field_map: {
        "start": "date",
        "end": "date",
        "id": "name",
        "title": "customer_name"
    },

    filters: [
        {
            "fieldtype": "Link",
            "fieldname": "workflow_state",
            "label": __("Workflow State"),
            "options": "Workflow State"
        },
        {
            "fieldtype": "Select",
            "fieldname": "time",
            "label": __("Time Slot"),
            "options": "\n07:00 AM to 08:00 AM\n08:00 AM to 09:00 AM\n09:00 AM to 10:00 AM\n10:00 AM to 11:00 AM\n11:00 AM to 12:00 PM\n12:00 PM to 01:00 PM\n01:00 PM to 02:00 PM\n02:00 PM to 03:00 PM\n03:00 PM to 04:00 PM\n04:00 PM to 05:00 PM\n05:00 PM to 06:00 PM\n06:00 PM to 07:00 PM\n07:00 PM to 08:00 PM\n08:00 PM to 09:00 PM\n09:00 PM to 10:00 PM\n10:00 PM to 11:00 PM\n11:00 PM to 12:00 AM\n12:00 AM to 01:00 AM\n01:00 AM to 02:00 AM\n02:00 AM to 03:00 AM\n03:00 AM to 04:00 AM\n04:00 AM to 05:00 AM\n05:00 AM to 06:00 AM\n06:00 AM to 07:00 AM"
        },
        {
            "fieldtype": "Link",
            "fieldname": "city",
            "options": "City",
            "label": __("City")
        }
    ],

    options: {
        defaultView: "month",
        eventLimit: 5,
        eventOrder: "ws_time_order,title",
        displayEventTime: false,
        height: "auto",

        eventRender: function(event, element) {
            ws_service_visit_calendar_render_event(event, element);
        },

        eventClick: function(event) {
            frappe.set_route("Form", "Service Visit", event.name);
        }
    },

    get_args: function(start, end) {
        return {
            doctype: this.doctype,
            start: this.get_system_datetime(start),
            end: this.get_system_datetime(end),
            field_map: this.field_map,
            filters: ws_service_visit_calendar_filters(this.list_view.filter_area.get()),
            fields: [
                "name",
                "date",
                "customer_name",
                "time",
                "workflow_state",
                "city"
            ]
        };
    },

    prepare_events: function(events) {
        ws_service_visit_calendar_load_workflow_styles(this);

        events = frappe.views.Calendar.prototype.prepare_events.call(this, events);

        (events || []).forEach(function(event) {
            event.ws_time_order = ws_service_visit_calendar_time_order(event.time);
        });

        return events;
    },

    // Standard core calendar engine method.
    get_events_method: "frappe.desk.calendar.get_events"
};

function ws_service_visit_calendar_render_event(event, element) {
    var color = ws_service_visit_calendar_color(event);
    var title = ws_service_visit_calendar_title(event);
    var tooltip = ws_service_visit_calendar_tooltip(event);

    element.attr("title", tooltip);
    element.css({
        "background": color.background,
        "border-color": color.border,
        "color": color.text,
        "border-left": "4px solid " + color.border
    });

    element.find(".fc-title").html(
        '<div class="ws-sv-cal-event">' +
            '<div class="ws-sv-cal-head">' +
                '<span class="ws-sv-cal-time">' + ws_service_visit_calendar_escape(ws_service_visit_calendar_time_label(event.time)) + '</span>' +
            '</div>' +
            '<div class="ws-sv-cal-title">' + ws_service_visit_calendar_escape(title) + '</div>' +
        '</div>'
    );

    ws_service_visit_calendar_add_styles();
}

function ws_service_visit_calendar_title(event) {
    return event.customer_name || event.name || __("Service Visit");
}

function ws_service_visit_calendar_tooltip(event) {
    var lines = [
        __("Service Visit") + ": " + event.name,
        __("Customer") + ": " + ws_service_visit_calendar_title(event),
        __("Time") + ": " + (event.time || __("No Time")),
        __("Workflow") + ": " + (event.workflow_state || __("Draft"))
    ];

    if (event.city) {
        lines.push(__("City") + ": " + event.city);
    }

    return lines.filter(Boolean).join("\n");
}

function ws_service_visit_calendar_color(event) {
    var style = ws_service_visit_calendar_state_style(event.workflow_state || "");
    var colors = {
        primary: {
            background: "#eef2ff",
            border: "#3f51b5",
            text: "#1f2a6d"
        },
        info: {
            background: "#eaf5ff",
            border: "#5aa6e8",
            text: "#174a7c"
        },
        success: {
            background: "#edf9f0",
            border: "#2f855a",
            text: "#22543d"
        },
        warning: {
            background: "#fff4e5",
            border: "#f08c00",
            text: "#7a3e00"
        },
        danger: {
            background: "#fff1f0",
            border: "#d93025",
            text: "#7a271a"
        },
        inverse: {
            background: "#111827",
            border: "#000000",
            text: "#ffffff"
        },
        default: {
            background: "#f2f4f7",
            border: "#98a2b3",
            text: "#344054"
        }
    };

    return colors[style] || colors.default;
}

function ws_service_visit_calendar_state_style(state) {
    var fallback_styles = {
        "Ordered": "success",
        "Invoiced": "success"
    };
    var style_map = window.ws_service_visit_workflow_state_styles || {};
    var style = style_map[state] || fallback_styles[state] || "";

    return (style || "default").toLowerCase();
}

function ws_service_visit_calendar_load_workflow_styles(calendar) {
    if (
        window.ws_service_visit_workflow_state_styles_loaded ||
        window.ws_service_visit_workflow_state_styles_loading
    ) {
        return;
    }

    window.ws_service_visit_workflow_state_styles_loading = true;

    frappe.call({
        method: "frappe.client.get_list",
        args: {
            doctype: "Workflow State",
            fields: ["workflow_state_name", "style"],
            limit_page_length: 1000
        },
        callback: function(r) {
            var style_map = {};

            (r.message || []).forEach(function(row) {
                if (row.workflow_state_name) {
                    style_map[row.workflow_state_name] = row.style || "";
                }
            });

            window.ws_service_visit_workflow_state_styles = style_map;
            window.ws_service_visit_workflow_state_styles_loaded = true;

            if (calendar && calendar.refresh) {
                calendar.refresh();
            }
        },
        always: function() {
            window.ws_service_visit_workflow_state_styles_loading = false;
        }
    });
}

function ws_service_visit_calendar_time_order(time) {
    var order = {
        "07:00 AM to 08:00 AM": 1,
        "08:00 AM to 09:00 AM": 2,
        "09:00 AM to 10:00 AM": 3,
        "10:00 AM to 11:00 AM": 4,
        "11:00 AM to 12:00 PM": 5,
        "12:00 PM to 01:00 PM": 6,
        "01:00 PM to 02:00 PM": 7,
        "02:00 PM to 03:00 PM": 8,
        "03:00 PM to 04:00 PM": 9,
        "04:00 PM to 05:00 PM": 10,
        "05:00 PM to 06:00 PM": 11,
        "06:00 PM to 07:00 PM": 12,
        "07:00 PM to 08:00 PM": 13,
        "08:00 PM to 09:00 PM": 14,
        "09:00 PM to 10:00 PM": 15,
        "10:00 PM to 11:00 PM": 16,
        "11:00 PM to 12:00 AM": 17,
        "12:00 AM to 01:00 AM": 18,
        "01:00 AM to 02:00 AM": 19,
        "02:00 AM to 03:00 AM": 20,
        "03:00 AM to 04:00 AM": 21,
        "04:00 AM to 05:00 AM": 22,
        "05:00 AM to 06:00 AM": 23,
        "06:00 AM to 07:00 AM": 24
    };

    return order[time] || 999;
}

function ws_service_visit_calendar_time_label(time) {
    if (!time) {
        return __("No Time");
    }

    return time.replace(" to ", " - ");
}

function ws_service_visit_calendar_filters(filters) {
    filters = filters || [];

    filters.push(["Service Visit", "workflow_state", "!=", "Cancelled"]);
    filters.push(["Service Visit", "docstatus", "!=", 2]);

    return filters;
}

function ws_service_visit_calendar_escape(value) {
    return $("<div>").text(value || "").html();
}

function ws_service_visit_calendar_add_styles() {
    if ($("#ws-service-visit-calendar-style").length) {
        return;
    }

    $("head").append(
        '<style id="ws-service-visit-calendar-style">' +
            '.fc-event .ws-sv-cal-event {' +
                'font-size: 11px;' +
                'line-height: 1.35;' +
                'padding: 3px 4px;' +
                'white-space: normal;' +
            '}' +
            '.fc-event .ws-sv-cal-head {' +
                'display: flex;' +
                'align-items: center;' +
                'justify-content: space-between;' +
                'gap: 4px;' +
                'margin-bottom: 2px;' +
            '}' +
            '.fc-event .ws-sv-cal-time {' +
                'display: block;' +
                'font-size: 10px;' +
                'font-weight: 700;' +
                'line-height: 1.2;' +
                'overflow: hidden;' +
                'text-overflow: ellipsis;' +
                'white-space: nowrap;' +
            '}' +
            '.fc-event .ws-sv-cal-title {' +
                'font-weight: 700;' +
                'overflow: hidden;' +
                'text-overflow: ellipsis;' +
                'white-space: nowrap;' +
            '}' +
            '.fc-month-view .fc-event {' +
                'margin-bottom: 2px;' +
            '}' +
        '</style>'
    );
}
