frappe.pages["call-assistant"].on_page_load = function(wrapper) {
    var page = frappe.ui.make_app_page({
        parent: wrapper,
        title: __("Call Assistant"),
        single_column: true
    });

    frappe.call_assistant = new worldshading.CallAssistant(page);
};

frappe.pages["call-assistant"].on_page_show = function() {
    if (frappe.call_assistant) {
        frappe.call_assistant.refresh_from_route();
    }
};

frappe.provide("worldshading");

worldshading.CallAssistant = Class.extend({
    init: function(page) {
        this.page = page;
        this.data = null;
        this.make();
        this.bind();
    },

    make: function() {
        this.page.main.html([
            "<div class='ws-call-assistant'>",
                "<style>",
                    ".ws-call-assistant{background:#f7f8fa;margin:-15px;padding:18px;min-height:calc(100vh - 110px);}",
                    ".ws-ca-header{display:flex;justify-content:space-between;gap:16px;align-items:flex-start;background:#fff;border:1px solid #dfe3e8;padding:16px;border-radius:6px;margin-bottom:14px;}",
                    ".ws-ca-title{font-size:18px;font-weight:600;margin-bottom:6px;}",
                    ".ws-ca-meta{display:flex;flex-wrap:wrap;gap:8px;color:#5e6c7b;}",
                    ".ws-ca-pill{background:#eef2f7;border:1px solid #dfe3e8;border-radius:4px;padding:4px 8px;font-size:12px;}",
                    ".ws-ca-actions{display:flex;gap:8px;flex-wrap:wrap;justify-content:flex-end;}",
                    ".ws-ca-grid{display:grid;grid-template-columns:320px minmax(0,1fr) 280px;gap:14px;}",
                    ".ws-ca-panel{background:#fff;border:1px solid #dfe3e8;border-radius:6px;padding:14px;min-width:0;}",
                    ".ws-ca-panel h3{font-size:13px;text-transform:uppercase;letter-spacing:0;color:#6b7785;margin:0 0 10px;}",
                    ".ws-ca-name{font-size:20px;font-weight:600;margin-bottom:4px;}",
                    ".ws-ca-muted{color:#74808c;}",
                    ".ws-ca-row{display:flex;justify-content:space-between;gap:12px;border-top:1px solid #edf0f3;padding:8px 0;}",
                    ".ws-ca-row:first-child{border-top:0;}",
                    ".ws-ca-label{color:#74808c;}",
                    ".ws-ca-value{text-align:right;font-weight:500;}",
                    ".ws-ca-list{display:flex;flex-direction:column;gap:8px;}",
                    ".ws-ca-item{border:1px solid #edf0f3;border-radius:5px;padding:10px;background:#fbfcfd;}",
                    ".ws-ca-item-title{font-weight:600;}",
                    ".ws-ca-item-meta{font-size:12px;color:#74808c;margin-top:3px;}",
                    ".ws-ca-tabs{margin-top:14px;}",
                    ".ws-ca-tabs .nav{margin-bottom:10px;}",
                    ".ws-ca-empty{color:#74808c;padding:18px;text-align:center;border:1px dashed #dfe3e8;border-radius:5px;background:#fbfcfd;}",
                    ".ws-ca-loading{padding:36px;text-align:center;color:#74808c;}",
                    "@media(max-width:1100px){.ws-ca-grid{grid-template-columns:1fr 1fr}.ws-ca-side-right{grid-column:1/-1;}}",
                    "@media(max-width:760px){.ws-call-assistant{padding:10px}.ws-ca-header{flex-direction:column}.ws-ca-grid{grid-template-columns:1fr}.ws-ca-actions{justify-content:flex-start}.ws-ca-value{text-align:left}.ws-ca-row{flex-direction:column;gap:2px;}}",
                "</style>",
                "<div class='ws-ca-header'>",
                    "<div>",
                        "<div class='ws-ca-title'>", __("Live Call Workspace"), "</div>",
                        "<div class='ws-ca-meta js-call-meta'></div>",
                    "</div>",
                    "<div class='ws-ca-actions'>",
                        "<button class='btn btn-default btn-sm js-reload'>", __("Reload"), "</button>",
                        "<button class='btn btn-primary btn-sm js-open-customer hidden'>", __("Open Customer"), "</button>",
                        "<button class='btn btn-default btn-sm js-create-lead'>", __("Create Lead"), "</button>",
                        "<button class='btn btn-default btn-sm js-create-service-visit'>", __("Create Service Visit"), "</button>",
                        "<button class='btn btn-default btn-sm js-add-note'>", __("Add Note"), "</button>",
                    "</div>",
                "</div>",
                "<div class='js-body'><div class='ws-ca-loading'>", __("Waiting for call details..."), "</div></div>",
            "</div>"
        ].join(""));
    },

    bind: function() {
        var me = this;

        this.page.main.on("click", ".js-reload", function() {
            me.load();
        });

        this.page.main.on("click", ".js-open-customer", function() {
            if (me.data && me.data.caller_info && me.data.caller_info.customer) {
                frappe.set_route("Form", "Customer", me.data.caller_info.customer);
            }
        });

        this.page.main.on("click", ".js-create-lead", function() {
            frappe.new_doc("Lead", {
                mobile_no: me.get_caller(),
                lead_name: me.get_caller()
            });
        });

        this.page.main.on("click", ".js-create-service-visit", function() {
            var args = {
                mobile_number: me.get_caller()
            };
            if (me.data && me.data.caller_info && me.data.caller_info.customer) {
                args.customer = me.data.caller_info.customer;
            }
            frappe.new_doc("Service Visit", args);
        });

        this.page.main.on("click", ".js-add-note", function() {
            frappe.msgprint(__("Note capture will be added in the next phase."));
        });
    },

    refresh_from_route: function() {
        this.route_options = frappe.route_options || {};
        frappe.route_options = null;
        this.load();
    },

    load: function() {
        var me = this;
        var opts = this.route_options || {};

        this.page.main.find(".js-body").html("<div class='ws-ca-loading'>" + __("Loading customer context...") + "</div>");
        this.render_meta(opts);

        frappe.call({
            method: "worldshading.api.call_assistant.get_call_context",
            args: {
                caller: opts.caller || "",
                linkedid: opts.linkedid || "",
                extension: opts.extension || "",
                customer: opts.customer || "",
                contact: opts.contact || "",
                lead: opts.lead || ""
            },
            callback: function(r) {
                me.data = r.message || {};
                me.render();
            },
            error: function() {
                me.page.main.find(".js-body").html("<div class='ws-ca-empty'>" + __("Could not load call details.") + "</div>");
            }
        });
    },

    render_meta: function(opts) {
        var meta = [];
        if (opts.caller) meta.push(this.pill(__("Caller"), opts.caller));
        if (opts.extension) meta.push(this.pill(__("Extension"), opts.extension));
        if (opts.linkedid) meta.push(this.pill(__("LinkedID"), opts.linkedid));
        this.page.main.find(".js-call-meta").html(meta.join(""));
    },

    render: function() {
        var data = this.data || {};
        var info = data.caller_info || {};
        var customer = data.customer_profile || {};

        this.render_meta(data);
        this.page.main.find(".js-open-customer").toggleClass("hidden", !info.customer);

        this.page.main.find(".js-body").html([
            "<div class='ws-ca-grid'>",
                this.render_profile(info, customer, data.outstanding),
                this.render_activity(data),
                this.render_actions(data),
            "</div>",
            this.render_tabs(data),
        ].join(""));
    },

    render_profile: function(info, customer, outstanding) {
        return [
            "<div class='ws-ca-panel'>",
                "<h3>", __("Customer Profile"), "</h3>",
                "<div class='ws-ca-name'>", this.escape(info.display_name || __("Unknown Caller")), "</div>",
                "<div class='ws-ca-muted'>", this.escape(info.match_type || __("No ERP match yet")), "</div>",
                "<div style='height:10px'></div>",
                this.row(__("Caller"), info.phone || this.get_caller()),
                this.row(__("Customer"), info.customer || ""),
                this.row(__("Group"), customer.customer_group || ""),
                this.row(__("Territory"), customer.territory || ""),
                this.row(__("Mobile"), customer.mobile_no || ""),
                this.row(__("Email"), customer.email_id || ""),
                this.row(__("Outstanding"), format_currency((outstanding || {}).amount || 0)),
            "</div>"
        ].join("");
    },

    render_activity: function(data) {
        return [
            "<div class='ws-ca-panel'>",
                "<h3>", __("Live Context"), "</h3>",
                this.section(__("Open Service Visits"), data.open_service_visits, this.render_service_visit),
                "<div class='ws-ca-tabs'>",
                    this.render_transaction_tabs(data),
                "</div>",
            "</div>"
        ].join("");
    },

    render_actions: function(data) {
        return [
            "<div class='ws-ca-panel ws-ca-side-right'>",
                "<h3>", __("Call Summary"), "</h3>",
                this.row(__("Caller"), data.caller || ""),
                this.row(__("Extension"), data.extension || ""),
                this.row(__("LinkedID"), data.linkedid || ""),
                "<div style='height:10px'></div>",
                "<h3>", __("Contacts"), "</h3>",
                this.render_list(data.contacts, this.render_contact),
                "<div style='height:10px'></div>",
                "<h3>", __("Call History"), "</h3>",
                this.render_list(data.call_history, this.render_call_log),
            "</div>"
        ].join("");
    },

    render_tabs: function(data) {
        return [
            "<div class='ws-ca-panel ws-ca-tabs'>",
                "<h3>", __("Recent Documents"), "</h3>",
                this.section(__("Recent Quotations"), data.recent_quotations, this.render_doc_item),
                this.section(__("Recent Sales Orders"), data.recent_sales_orders, this.render_doc_item),
                this.section(__("Recent Sales Invoices"), data.recent_sales_invoices, this.render_doc_item),
            "</div>"
        ].join("");
    },

    render_transaction_tabs: function(data) {
        return [
            this.section(__("Outstanding Invoices"), ((data.outstanding || {}).invoices || []), this.render_invoice),
        ].join("");
    },

    section: function(title, rows, renderer) {
        return [
            "<h3 style='margin-top:14px'>", this.escape(title), "</h3>",
            this.render_list(rows, renderer),
        ].join("");
    },

    render_list: function(rows, renderer) {
        var me = this;
        rows = rows || [];
        if (!rows.length) {
            return "<div class='ws-ca-empty'>" + __("No records found") + "</div>";
        }
        return [
            "<div class='ws-ca-list'>",
            rows.map(function(row) {
                return renderer.call(me, row);
            }).join(""),
            "</div>"
        ].join("");
    },

    render_doc_item: function(row) {
        var date = row.transaction_date || row.posting_date || row.date || "";
        return this.item(row.name, [row.status, date, row.grand_total ? format_currency(row.grand_total) : ""].join(" "));
    },

    render_invoice: function(row) {
        return this.item(row.name, [row.status, row.posting_date, format_currency(row.outstanding_amount || 0)].join(" "));
    },

    render_service_visit: function(row) {
        return this.item(row.name, [row.subject, row.date, row.time, row.workflow_state].join(" "));
    },

    render_contact: function(row) {
        var name = [row.first_name, row.middle_name, row.last_name].filter(Boolean).join(" ") || row.name;
        return this.item(name, [row.mobile_no, row.phone, row.email_id].join(" "));
    },

    render_call_log: function(row) {
        return this.item(row.id || row.name, [row.status, row.creation, row.duration ? row.duration + "s" : ""].join(" "));
    },

    item: function(title, meta) {
        return [
            "<div class='ws-ca-item'>",
                "<div class='ws-ca-item-title'>", this.escape(title || ""), "</div>",
                "<div class='ws-ca-item-meta'>", this.escape(meta || ""), "</div>",
            "</div>"
        ].join("");
    },

    row: function(label, value) {
        return [
            "<div class='ws-ca-row'>",
                "<div class='ws-ca-label'>", this.escape(label), "</div>",
                "<div class='ws-ca-value'>", this.escape(value || ""), "</div>",
            "</div>"
        ].join("");
    },

    pill: function(label, value) {
        return "<span class='ws-ca-pill'>" + this.escape(label) + ": " + this.escape(value || "") + "</span>";
    },

    get_caller: function() {
        return (this.data && this.data.caller) || (this.route_options && this.route_options.caller) || "";
    },

    escape: function(value) {
        return frappe.utils.escape_html(String(value === null || value === undefined ? "" : value));
    }
});
