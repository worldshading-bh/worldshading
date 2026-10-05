(function () {
	"use strict";

	var requested = false;
	var sources = [
		{doctype: "Purchase Order", title: "Purchase Orders", label: "PO", party_label: "Supplier",
			method: "worldshading.api.purchase_order_urgency.get_urgent_purchase_orders",
			party: "supplier", party_name: "supplier_name", amount: "grand_total", currency: "currency"},
		{doctype: "Payment Entry", title: "Payment Entries", label: "PE", party_label: "Party",
			method: "worldshading.api.payment_entry_urgency.get_urgent_payment_entries",
			party: "party", party_name: "party_name", amount: "paid_amount", currency: "paid_from_account_currency"},
		{doctype: "GL Payment", title: "GL Payments", label: "GLP", party_label: "Party",
			method: "worldshading.api.gl_payment_urgency.get_urgent_gl_payments",
			party: "party", party_name: "party_name", amount: "total_amount", currency: "currency"}
	];

	$(document).on("app_ready", function () {
		if (requested) { return; }
		requested = true;
		setTimeout(load_urgent_documents, 500);
	});

	function load_urgent_documents() {
		var remaining = sources.length;
		sources.forEach(function (source) {
			var settled = false;
			function finish(rows, failed) {
				if (settled) { return; }
				settled = true;
				source.rows = rows || [];
				source.failed = failed;
				remaining -= 1;
				if (!remaining && sources.some(function (entry) {
					return entry.rows.length || entry.failed;
				})) {
					show_when_available();
				}
			}
			frappe.call({
				method: source.method,
				callback: function (response) { finish(response.message, Boolean(response.exc)); },
				error: function () { finish([], true); }
			});
		});
	}

	function show_when_available() {
		var dialog = frappe.msg_dialog;
		var modal = dialog && dialog.$wrapper && dialog.$wrapper.data("bs.modal");
		if (dialog && dialog.$wrapper && (dialog.$wrapper.is(":visible") ||
			(modal && (modal._isShown || modal._isTransitioning)))) {
			dialog.$wrapper.one("hidden.bs.modal.ws-urgent-documents", function () {
				setTimeout(show_when_available, 0);
			});
			return;
		}
		show_popup();
	}

	function show_popup() {
		var total = sources.reduce(function (count, source) { return count + source.rows.length; }, 0);
		var message = [
			'<style>.modal.ws-urgent-documents .modal-dialog { width: 900px; max-width: calc(100% - 24px); margin-left: auto; margin-right: auto; }',
			'.ws-urgent-document-sections { max-height: 65vh; overflow-y: auto; }',
			'.ws-urgent-document-sections td { overflow-wrap: anywhere; }</style>',
			'<p class="text-muted">' + escape_html(__("⚠ Please review and take action on these urgent documents.")) + '</p>',
			'<div class="ws-urgent-document-sections">'
		];
		sources.forEach(function (source) {
			if (source.failed) {
				message.push('<p class="text-warning">' + escape_html(__(source.title)) + ': ' +
					escape_html(__("Could not load urgent documents. Please refresh to try again.")) + '</p>');
			} else if (source.rows.length) {
				message.push(render_section(source));
			}
		});
		message.push('</div>');
		var dialog = frappe.msgprint({
			title: __("Urgent Documents") + " (" + total + ")",
			message: message.join(""),
			indicator: "red", wide: true, clear: true
		});
		dialog.custom_onhide = null;
		dialog.keep_open = true;
		dialog.$wrapper.addClass("ws-urgent-documents");
		dialog.$wrapper.one("hidden.bs.modal.ws-urgent-documents-width", function () {
			dialog.$wrapper.removeClass("ws-urgent-documents");
		});
	}

	function render_section(source) {
		var headings = [source.label, source.party_label, "Amount", "Workflow State", "Reason"];
		return '<section><h5>' + escape_html(__(source.title)) + ' (' + source.rows.length + ')</h5>' +
			'<div class="table-responsive"><table class="table table-bordered table-hover">' +
			'<thead><tr>' + headings.map(function (heading) {
				return '<th>' + escape_html(__(heading)) + '</th>';
			}).join("") + '</tr></thead><tbody>' +
			source.rows.map(function (doc) { return render_row(source, doc); }).join("") +
			'</tbody></table></div></section>';
	}

	function render_row(source, doc) {
		var link = frappe.utils.get_form_link(source.doctype, doc.name);
		return '<tr><td><span class="indicator red"></span><a href="' + escape_html(link) + '">' +
			escape_html(doc.name) + '</a></td><td>' +
			escape_html(doc[source.party_name] || doc[source.party] || "") +
			'</td><td class="text-right">' + escape_html(format_currency(
				doc[source.amount] || 0, doc[source.currency] || "")) +
			'</td><td>' + escape_html(doc.workflow_state || "") +
			'</td><td>' + escape_html(doc.custom_urgent_reason || "") + '</td></tr>';
	}

	function escape_html(value) {
		return frappe.utils.escape_html(String(value == null ? "" : value));
	}
})();
