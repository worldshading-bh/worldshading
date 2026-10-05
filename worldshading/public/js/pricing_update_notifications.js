(function () {
	"use strict";

	var prototype = frappe.Application && frappe.Application.prototype;
	if (!prototype || prototype._ws_pricing_notes_guard) {
		return;
	}
	var original = prototype.show_notes;
	var title_pattern = /^(Prices|Pricing Rules) Updated - \d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:\.\d+)? - [a-f0-9]{12}$/;
	function is_pricing_note(note) {
		return note.notify_on_every_login && title_pattern.test(note.title || "");
	}
	var style = document.createElement("style");
	style.textContent = ".modal.ws-pricing-note .modal-dialog { width: auto; max-width: 760px; margin-left: 12px; margin-right: 12px; } " +
		"@media (min-width: 784px) { .modal.ws-pricing-note .modal-dialog { width: 760px; margin-left: auto; margin-right: auto; } }";
	document.head.appendChild(style);
	var widen_pricing_popup = false;
	var original_msgprint = frappe.msgprint;
	frappe.msgprint = function () {
		var args = Array.prototype.slice.call(arguments);
		if (widen_pricing_popup && args[0] && typeof args[0] === "object") {
			args[0] = Object.assign({}, args[0], {wide: true});
		}
		var dialog = original_msgprint.apply(this, args);
		if (dialog && dialog.$wrapper) {
			dialog.$wrapper.toggleClass("ws-pricing-note", widen_pricing_popup);
		}
		return dialog;
	};

	prototype.show_notes = function () {
		var notes = frappe.boot.notes;
		var visible = notes.filter(function (note) {
			return !is_pricing_note(note) || !note._ws_pricing_shown;
		});
		var previous_width = widen_pricing_popup;
		widen_pricing_popup = visible.some(function (note) {
			return is_pricing_note(note) && note.title.indexOf("Prices Updated") === 0;
		});
		var titles = [];
		// Native v12 repeats all login Notes when its shared dialog is dismissed.
		visible.forEach(function (note) {
			if (is_pricing_note(note)) {
				note._ws_pricing_shown = true;
				titles.push({note: note, title: note.title});
				note.title = note.title.indexOf("Pricing Rules") === 0 ? "Pricing Rules Updated" : "Prices Updated";
			}
		});
		frappe.boot.notes = visible;
		try {
			return original.apply(this, arguments);
		} finally {
			widen_pricing_popup = previous_width;
			titles.forEach(function (entry) { entry.note.title = entry.title; });
			frappe.boot.notes = notes;
		}
	};
	prototype._ws_pricing_notes_guard = true;
}());
