(function () {
	"use strict";

	var settings = frappe.listview_settings["GL Payment"] || {};
	var original_onload = settings.onload;
	settings.add_fields = settings.add_fields || [];

	if (!frappe.meta.get_docfield("GL Payment", "custom_is_urgent")) {
		return;
	}

	if (settings.add_fields.indexOf("custom_is_urgent") === -1) {
		settings.add_fields.push("custom_is_urgent");
	}

	var urgency_field = frappe.meta.get_docfield(
		"GL Payment", "custom_is_urgent"
	);
	if (urgency_field) {
		urgency_field.in_list_view = 0;
	}

	settings.onload = function (listview) {
		if (original_onload) {
			original_onload(listview);
		}

		if (listview._ws_urgency_badge_installed) {
			return;
		}

		var original_get_subject_html = listview.get_subject_html.bind(listview);

		listview.get_subject_html = function (doc) {
			var html = original_get_subject_html(doc);
			if (!Number(doc.custom_is_urgent)) {
				return html;
			}

			var badge = [
				'<span role="img"',
				' aria-label="' + __("Urgent GL Payment") + '"',
				' title="' + __("Urgent GL Payment") + '"',
				' style="display:inline-flex;width:17px;height:17px;',
				'vertical-align:middle;flex:0 0 17px;">',
				'<svg viewBox="0 0 24 24" width="17" height="17"',
				' aria-hidden="true" focusable="false">',
				'<circle cx="12" cy="12" r="10" fill="#e24c4c"/>',
				'<path fill="#fff" d="M11 5h2v9h-2z"/>',
				'<circle cx="12" cy="17.5" r="1.4" fill="#fff"/>',
				'</svg></span>'
			].join("");

			// Use the fixed like-icon slot, outside the truncated supplier link.
			return html.replace(/<i\b[^>]*class="[^"]*\blike-action\b[^"]*"[^>]*>[\s\S]*?<\/i>/, function () {
				return badge;
			}).replace(/<span\b[^>]*class="likes-count"[^>]*>[\s\S]*?<\/span>/, "");
		};

		listview._ws_urgency_badge_installed = true;
	};

	frappe.listview_settings["GL Payment"] = settings;
})();
