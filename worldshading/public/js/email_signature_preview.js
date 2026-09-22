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
		dialog, fieldname, sender, composer
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
				var account_defaults = r.message || {};
				var signature = (account_defaults.signature || "").trim();
				if (signature) {
					wrapper.find(".worldshading-account-signature-content").html(signature);
					wrapper.find(".worldshading-account-signature-preview").show();
				}
				apply_account_cc(composer, account_defaults.default_cc || "");
			}
		});
	};

	function apply_account_cc(composer, account_cc) {
		if (!composer || !composer.dialog) return;
		account_cc = split_cc(account_cc).join(", ");
		composer.worldshading_account_cc = account_cc;
		composer.dialog.worldshading_account_cc = account_cc;
		if (composer.dialog.fields_dict.worldshading_default_cc) {
			composer.dialog.set_value("worldshading_default_cc", account_cc);
		}

		var optional_cc = composer.dialog.fields_dict.cc;
		if (account_cc && optional_cc) {
			var default_addresses = split_cc(account_cc).map(function (address) {
				return address.toLowerCase();
			});
			var remaining = split_cc(optional_cc.get_value()).filter(
				function (address) {
					return default_addresses.indexOf(address.toLowerCase()) === -1;
				}
			);
			optional_cc.set_value(remaining.join(", "));
		}
	}

	function split_cc(value) {
		return (value || "").split(/[,;\n\r]+/).map(function (address) {
			return address.trim();
		}).filter(Boolean);
	}

	function merge_cc(account_cc, optional_cc) {
		var addresses = [];
		[account_cc, optional_cc].forEach(function (value) {
			split_cc(value).forEach(function (address) {
				if (address && addresses.map(function (item) {
					return item.toLowerCase();
				}).indexOf(address.toLowerCase()) === -1) {
					addresses.push(address);
				}
			});
		});
		return addresses.join(", ");
	}
	worldshading.email_signature.merge_cc = merge_cc;

	function remove_repeated_message_parts(composer) {
		var content_field = composer.dialog.fields_dict.content;
		if (!content_field) return;

		var content = content_field.get_value() || "";
		var separator_index = content.indexOf(frappe.separator_element);
		var message = separator_index === -1 ? content : content.substring(0, separator_index);
		var quoted_history = separator_index === -1 ? "" : content.substring(separator_index);

		var salutations = message.match(
			/<p>\s*Dear[\s\S]*?<\/p>\s*<!-- salutation-ends -->\s*<br\s*\/?>/gi
		) || [];
		if (salutations.length > 1) {
			message = message.replace(
				/<p>\s*Dear[\s\S]*?<\/p>\s*<!-- salutation-ends -->\s*<br\s*\/?>/gi,
				""
			);
			message = salutations[0] + message;
		}

		var signature = (frappe.boot.user.email_signature || "").trim();
		if (signature && !frappe.utils.is_html(signature)) {
			signature = signature.replace(/\n/g, "<br>");
		}
		if (signature && message.split(signature).length > 2) {
			message = message.split(signature).join("") + signature;
		}

		message = message.replace(
			/^(?:\s*<div><br\s*\/?>\s*<\/div>){2,}/i,
			"<div><br></div>"
		);
		var cleaned_content = message + quoted_history;
		if (cleaned_content !== content) {
			content_field.set_value(cleaned_content);
		}
	}

	function get_composer_sender(composer) {
		var sender_field = composer.dialog.fields_dict.sender;
		var sender = sender_field ?
			(sender_field.get_value() || sender_field.input.value || "") : "";
		if (sender) return sender;

		var outgoing_accounts = (frappe.boot.email_accounts || []).filter(
			function (account) {
				return account.enable_outgoing &&
					["All Accounts", "Sent", "Spam", "Trash"].indexOf(
						account.email_account
					) === -1;
			}
		);
		return outgoing_accounts.length === 1 ? outgoing_accounts[0].email_id : "";
	}
	worldshading.email_signature.get_effective_sender = get_composer_sender;

	function apply_effective_sender(values, composer) {
		if (!values.sender) {
			values.sender = get_composer_sender(composer);
		}
		return values;
	}
	worldshading.email_signature.apply_effective_sender = apply_effective_sender;

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
			get_composer_sender(composer),
			composer
		);

		var sender_field = composer.dialog.fields_dict.sender;
		if (sender_field) {
			$(sender_field.input).off("change.worldshading_signature").on(
				"change.worldshading_signature",
				function () {
					worldshading.email_signature.update_account_preview(
						composer.dialog,
						"worldshading_account_signature_preview",
						get_composer_sender(composer),
						composer
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

		var original_get_fields = frappe.views.CommunicationComposer.prototype.get_fields;
		frappe.views.CommunicationComposer.prototype.get_fields = function () {
			var fields = original_get_fields.apply(this, arguments);
			var cc_index = fields.findIndex(function (field) {
				return field.fieldname === "cc";
			});
			if (cc_index !== -1) {
				fields.splice(cc_index, 0, {
					label: __("Default CC"),
					fieldtype: "Data",
					fieldname: "worldshading_default_cc",
					read_only: 1
				});
			}
			return fields;
		};

		var original_get_values = frappe.views.CommunicationComposer.prototype.get_values;
		frappe.views.CommunicationComposer.prototype.get_values = function () {
			var values = original_get_values.apply(this, arguments);
			if (!values) return values;
			apply_effective_sender(values, this);
			values.cc = merge_cc(this.worldshading_account_cc, values.cc);
			delete values.worldshading_default_cc;
			return values;
		};

		var original_setup_earlier_reply =
			frappe.views.CommunicationComposer.prototype.setup_earlier_reply;
		frappe.views.CommunicationComposer.prototype.setup_earlier_reply = function () {
			var composer = this;
			var frm = composer.frm;
			var saved_draft = "";
			if (!composer.txt && frm && frm.doctype && frm.docname) {
				saved_draft = localStorage.getItem(frm.doctype + frm.docname) || "";
			}
			if (saved_draft) {
				composer.message = saved_draft;
				composer.dialog.fields_dict.content.set_value(saved_draft);
				remove_repeated_message_parts(composer);
				return Promise.resolve();
			}
			var result = original_setup_earlier_reply.apply(this, arguments);
			return Promise.resolve(result).then(function (value) {
				remove_repeated_message_parts(composer);
				return value;
			});
		};

		var original_make = frappe.views.CommunicationComposer.prototype.make;
		frappe.views.CommunicationComposer.prototype.make = function () {
			original_make.apply(this, arguments);
			add_core_composer_preview(this);
		};
		frappe.views.CommunicationComposer.prototype.worldshading_signature_preview = true;
	}

	install_core_composer_preview();
	$(document).on("app_ready", install_core_composer_preview);
	if (frappe.require) {
		frappe.require("/assets/worldshading/js/email_validation.js");
	}
})();
