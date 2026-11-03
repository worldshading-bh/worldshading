(function () {
	"use strict";

	if (typeof frappe === "undefined" || !frappe.views ||
			!frappe.views.QueryReport || !frappe.views.QueryReport.prototype) {
		return;
	}

	var prototype = frappe.views.QueryReport.prototype;
	var original = prototype.add_prepared_report_buttons;
	if (typeof original !== "function" || original._worldshading_download_visibility) {
		return;
	}

	if (frappe.user && typeof frappe.user.has_role === "function" &&
			frappe.user.has_role("System Manager")) {
		return;
	}

	var wrapped = function () {
		var result = original.apply(this, arguments);
		if (this.page && typeof this.page.remove_inner_button === "function") {
			this.page.remove_inner_button(__("Download Report"));
		}
		return result;
	};
	wrapped._worldshading_download_visibility = true;
	prototype.add_prepared_report_buttons = wrapped;
}());
