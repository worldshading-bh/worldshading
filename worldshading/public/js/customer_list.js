(function() {
    var settings = frappe.listview_settings["Customer"] || {};
    var original_onload = settings.onload;
    var add_fields = settings.add_fields || [];

    if (add_fields.indexOf("business_verification_status") === -1) {
        add_fields.push("business_verification_status");
    }

    settings.add_fields = add_fields;

    settings.onload = function(listview) {
        if (original_onload) {
            original_onload(listview);
        }

        if (listview._ws_verification_badge_installed) {
            return;
        }

        var original_get_subject_html = listview.get_subject_html.bind(listview);

        listview.get_subject_html = function(doc) {
            var html = original_get_subject_html(doc);

            if (doc.business_verification_status !== "Verified") {
                return html;
            }

            var badge = [
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
            ].join("");

            return html.replace("</a>", badge + "</a>");
        };

        listview._ws_verification_badge_installed = true;
    };

    frappe.listview_settings["Customer"] = settings;
})();
