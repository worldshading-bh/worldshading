frappe.ready(function() {
    if (!frappe.realtime) {
        return;
    }

    var shown = {};
    ensure_call_toast_area();

    frappe.realtime.on("pbx_incoming_call", function(data) {
        data = data || {};

        var key = [data.linkedid || "", data.extension || ""].join(":");
        if (shown[key]) {
            return;
        }
        shown[key] = true;

        var caller = data.caller || "Unknown";
        var extension = data.extension || "";
        var queue_number = data.queue_number || "";
        var queue_name = data.queue_name || "";
        var caller_info = data.caller_info || {};
        var display_name = caller_info.display_name || "";
        var match_type = caller_info.match_type || "Unknown";
        var customer = caller_info.customer || "";
        var contact = caller_info.contact || "";
        var lead = caller_info.lead || "";

        show_call_toast({
            caller: caller,
            extension: extension,
            linkedid: data.linkedid || "",
            match_type: match_type,
            display_name: display_name,
            customer: customer,
            contact: contact,
            lead: lead,
            queue_number: queue_number,
            queue_name: queue_name
        });
    });

    function ensure_call_toast_area() {
        if (!$("#ws-call-toast-style").length) {
            $("head").append([
                "<style id='ws-call-toast-style'>",
                ".ws-call-toast-wrap{position:fixed;right:18px;bottom:18px;z-index:1050;width:340px;max-width:calc(100vw - 36px);}",
                ".ws-call-toast{display:flex;gap:12px;background:#fff;border:1px solid #e2e8f0;border-radius:8px;box-shadow:0 10px 28px rgba(15,23,42,.18);padding:12px;margin-top:10px;}",
                ".ws-call-toast-icon{width:34px;height:34px;border-radius:50%;background:#fff4e0;color:#b76e00;display:flex;align-items:center;justify-content:center;font-size:17px;flex:0 0 auto;}",
                ".ws-call-toast-main{min-width:0;flex:1;}",
                ".ws-call-toast-head{display:flex;justify-content:space-between;gap:10px;align-items:flex-start;margin-bottom:3px;}",
                ".ws-call-toast-title{font-weight:600;font-size:14px;color:#1f2937;}",
                ".ws-call-toast-close{border:0;background:transparent;color:#94a3b8;font-size:18px;line-height:1;padding:0 2px;}",
                ".ws-call-toast-body{font-size:12px;color:#64748b;line-height:1.45;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}",
                ".ws-call-toast-actions{margin-top:8px;}",
                ".ws-call-toast-actions .btn{padding:3px 9px;font-size:12px;}",
                "</style>"
            ].join(""));
        }

        if (!$("#ws-call-toast-wrap").length) {
            $("<div id='ws-call-toast-wrap' class='ws-call-toast-wrap'></div>").appendTo("body");
        }
    }

    function show_call_toast(data) {
        ensure_call_toast_area();

        var card = $("<div class='ws-call-toast'></div>");
        var title = data.display_name || data.caller || __("Unknown Caller");
        var subtitle = data.customer ? __("Customer {0}", [data.customer]) : data.match_type || __("Unknown");

        card.html([
            "<div class='ws-call-toast-icon'>☎</div>",
            "<div class='ws-call-toast-main'>",
              "<div class='ws-call-toast-head'>",
                "<div>",
                    "<div class='ws-call-toast-title'>", frappe.utils.escape_html(__("Incoming Call")), "</div>",
                "</div>",
                "<button class='ws-call-toast-close js-close-call-toast'>×</button>",
              "</div>",
              "<div class='ws-call-toast-body'>",
                frappe.utils.escape_html(title),
                " · ",
                frappe.utils.escape_html(data.caller || ""),
                data.extension ? " · Ext " + frappe.utils.escape_html(data.extension) : "",
                "<br>",
                frappe.utils.escape_html(subtitle),
              "</div>",
              "<div class='ws-call-toast-actions'>",
                "<button class='btn btn-primary btn-sm js-open-call-assistant'>", __("Open"), "</button>",
              "</div>",
            "</div>"
        ].join(""));

        card.find(".js-open-call-assistant").on("click", function() {
            frappe.route_options = {
                caller: data.caller,
                linkedid: data.linkedid,
                extension: data.extension,
                customer: data.customer,
                contact: data.contact,
                lead: data.lead
            };
            frappe.set_route("call-assistant");
        });

        card.find(".js-close-call-toast").on("click", function() {
            card.remove();
        });

        $("#ws-call-toast-wrap").prepend(card);
    }
});
