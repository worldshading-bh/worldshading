frappe.provide("worldshading.email_signature");

(function () {
	var USER_SIGNATURE_START = "<!-- worldshading-user-signature-start -->";
	var USER_SIGNATURE_END = "<!-- worldshading-user-signature-end -->";

	worldshading.email_signature.with_user_signature = function (content) {
		content = worldshading.email_signature.without_user_signature(content || "");
		var signature = (frappe.boot.user.email_signature || "").trim();
		if (!signature) return content;
		if (!frappe.utils.is_html(signature)) {
			signature = frappe.utils.escape_html(signature).replace(/\n/g, "<br>");
		}

		return content + "<br><br>" + USER_SIGNATURE_START +
			'<div class="worldshading-user-signature">' + signature + "</div>" +
			USER_SIGNATURE_END;
	};

	worldshading.email_signature.without_user_signature = function (content) {
		var start = content.indexOf(USER_SIGNATURE_START);
		var end = content.indexOf(USER_SIGNATURE_END);
		if (start === -1 || end === -1 || end < start) return content;
		return content.substring(0, start).replace(/(<br>\s*){1,2}$/, "") +
			content.substring(end + USER_SIGNATURE_END.length);
	};

	worldshading.email_signature.update_account_preview = function (
		dialog, fieldname, sender
	) {
		var field = dialog.fields_dict[fieldname];
		if (!field) return;
		var wrapper = $(field.wrapper);
		var request_id = String(new Date().getTime()) + String(Math.random());
		wrapper.data("signature-request-id", request_id);
		wrapper.html(
			'<div class="worldshading-account-signature-preview" style="display:none;">' +
			'<h6 class="text-muted">' +
			__("Email Account Signature") +
			'</h6><div class="worldshading-account-signature-content" ' +
			'style="padding:12px; border:1px solid #d1d8dd; border-radius:4px; ' +
			'overflow-x:auto;"></div></div>'
		);

		frappe.call({
			method: "worldshading.api.email_signature.get_account_signature_preview",
			args: {sender: sender || ""},
			callback: function (r) {
				if (wrapper.data("signature-request-id") !== request_id) return;
				var signature = ((r.message || {}).signature || "").trim();
				if (!signature) return;
				wrapper.find(".worldshading-account-signature-content").html(signature);
				wrapper.find(".worldshading-account-signature-preview").show();
			}
		});
	};

	function get_composer_sender(composer) {
		var sender_field = composer.dialog.fields_dict.sender;
		return sender_field ? sender_field.get_value() : "";
	}

	function add_core_composer_preview(composer) {
		if (!composer.dialog || !composer.dialog.fields_dict.content) return;
		var content_wrapper = $(composer.dialog.fields_dict.content.wrapper);
		var preview_wrapper = $('<div class="worldshading-core-signature-preview"></div>');
		content_wrapper.after(preview_wrapper);
		composer.dialog.fields_dict.worldshading_account_signature_preview = {
			wrapper: preview_wrapper
		};

		worldshading.email_signature.update_account_preview(
			composer.dialog,
			"worldshading_account_signature_preview",
			get_composer_sender(composer)
		);

		var sender_field = composer.dialog.fields_dict.sender;
		if (sender_field) {
			$(sender_field.input).off("change.worldshading_signature").on(
				"change.worldshading_signature",
				function () {
					worldshading.email_signature.update_account_preview(
						composer.dialog,
						"worldshading_account_signature_preview",
						sender_field.get_value()
					);
				}
			);
		}
	}

	function install_core_composer_preview() {
		if (!frappe.views || !frappe.views.CommunicationComposer ||
			frappe.views.CommunicationComposer.prototype.worldshading_signature_preview) {
			return;
		}
		var original_make = frappe.views.CommunicationComposer.prototype.make;
		frappe.views.CommunicationComposer.prototype.make = function () {
			original_make.apply(this, arguments);
			add_core_composer_preview(this);
		};
		frappe.views.CommunicationComposer.prototype.worldshading_signature_preview = true;
	}

	install_core_composer_preview();
	$(document).on("app_ready", install_core_composer_preview);
})();
