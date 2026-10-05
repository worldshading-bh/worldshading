(function() {
    var settings = frappe.listview_settings["Customer"] || {};
    var original_onload = settings.onload;
    var add_fields = settings.add_fields || [];

    if (add_fields.indexOf("business_verification_status") === -1) {
        add_fields.push("business_verification_status");
    }
    if (add_fields.indexOf("default_price_list") === -1) {
        add_fields.push("default_price_list");
    }

    settings.add_fields = add_fields;

    settings.onload = function(listview) {
        if (original_onload) {
            original_onload(listview);
        }

        if (listview._ws_verification_badge_installed) {
            return;
        }

        listview._ws_protected_price_lists = {};

        frappe.call({
            method: "frappe.client.get_list",
            args: {
                doctype: "Price List",
                filters: {
                    only_for_verified_customers: 1,
                    enabled: 1,
                    selling: 1
                },
                fields: ["name"],
                limit_page_length: 0
            },
            callback: function(response) {
                (response.message || []).forEach(function(price_list) {
                    listview._ws_protected_price_lists[price_list.name] = true;
                });
                listview.refresh();
            }
        });

        var original_get_subject_html = listview.get_subject_html.bind(listview);

        listview.get_subject_html = function(doc) {
            var html = original_get_subject_html(doc);
            var badges = [];

            if (doc.business_verification_status === "Verified") {
                badges.push([
                    '<span role="img"',
                    ' aria-label="' + __("Sijilat Verified Business") + '"',
                    ' title="' + __("Sijilat Verified Business") + '"',
                    ' style="display:inline-flex;width:17px;height:17px;margin-left:5px;',
                    'vertical-align:middle;flex:0 0 17px;">',
                    '<svg viewBox="0 0 24 24" width="17" height="17"',
                    ' aria-hidden="true" focusable="false">',
                    '<path fill="#2490ef" d="M12 0.8l3.1 2.1 3.7-.3.8 3.6 3 2.2-1.5 3.4',
                    ' 1.5 3.4-3 2.2-.8 3.6-3.7-.3L12 23.2l-3.1-2.1-3.7.3-.8-3.6',
                    '-3-2.2 1.5-3.4-1.5-3.4 3-2.2.8-3.6 3.7.3z"/>',
                    '<path fill="#fff" d="M9.7 16.8l-4-4 1.8-1.8 2.2 2.2 6.8-6.8',
                    ' 1.8 1.8z"/>',
                    '</svg></span>'
                ].join(""));
            } else if (doc.business_verification_status === "Expired") {
                badges.push([
                    '<span role="img"',
                    ' aria-label="' + __("CR Expired") + '"',
                    ' title="' + __("CR Expired") + '"',
                    ' style="display:inline-flex;width:17px;height:17px;margin-left:5px;',
                    'vertical-align:middle;flex:0 0 17px;">',
                    '<svg viewBox="0 0 24 24" width="17" height="17"',
                    ' aria-hidden="true" focusable="false">',
                    '<circle cx="12" cy="12" r="9.5" fill="none"',
                    ' stroke="#f97316" stroke-width="3"/>',
                    '<path d="M12 6.5v6l4 2" fill="none" stroke="#f97316"',
                    ' stroke-width="2.5" stroke-linecap="round"',
                    ' stroke-linejoin="round"/>',
                    '</svg></span>'
                ].join(""));
            }

            if (
                doc.default_price_list &&
                listview._ws_protected_price_lists[doc.default_price_list]
            ) {
                badges.push([
                    '<span aria-label="' + __("B2B Special Pricing Enabled") + '"',
                    ' title="' + __("B2B Special Pricing Enabled") + '"',
                    ' style="display:inline-flex;align-items:center;margin-left:5px;',
                    'padding:1px 5px;border-radius:8px;vertical-align:middle;',
                    'font-size:10px;line-height:14px;font-weight:700;',
                    'color:#B45309;background:#FFF7E6;border:1px solid #F59E0B;">',
                    'B2B</span>'
                ].join(""));
            }

            if (!badges.length) {
                return html;
            }

            return html.replace("</a>", badges.join("") + "</a>");
        };

        listview._ws_verification_badge_installed = true;
    };

    frappe.listview_settings["Customer"] = settings;
})();
