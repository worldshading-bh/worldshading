frappe.ui.form.on("Request for Quotation", {
	setup: function (frm) {
		frm.fields_dict.suppliers.grid.get_field("supplier").get_query = function () {
			return {
				query: "worldshading.api.request_for_quotation.supplier_query",
				filters: {
					item_codes: (frm.doc.items || []).map(function (row) {
						return row.item_code;
					}).filter(Boolean),
					country_of_purchase: frm.doc.country_of_purchase
				}
			};
		};
	},

	refresh: function (frm) {
		if (frm.doc.docstatus === 1) {
			replace_send_supplier_emails_button(frm);
			return;
		}

		if (frm.doc.docstatus !== 0) return;

		frm.add_custom_button(__("Add Suppliers by Item Group"), function () {
			fetch_matching_suppliers(frm);
		}, __("Suppliers"));
	},

	fetch_matching_suppliers: function (frm) {
		fetch_matching_suppliers(frm);
	}
});

function replace_send_supplier_emails_button(frm) {
	frm.remove_custom_button(__("Send Supplier Emails"));
	frm.add_custom_button(__("Send Supplier Emails"), function () {
		show_supplier_email_dialog(frm);
	});
}

function show_supplier_email_dialog(frm) {
	var suppliers = (frm.doc.suppliers || []).filter(function (row) {
		return row.send_email && row.email_id;
	});
	var missing_emails = (frm.doc.suppliers || []).filter(function (row) {
		return row.send_email && !row.email_id;
	});

	if (missing_emails.length) {
		frappe.msgprint({
			title: __("Supplier Email Required"),
			indicator: "red",
			message: __("Add an email address for: {0}", [
				missing_emails.map(function (row) {
					return row.supplier_name || row.supplier;
				}).join(", ")
			])
		});
		return;
	}

	if (!suppliers.length) {
		frappe.msgprint(__("Select Send Email for at least one supplier."));
		return;
	}

	var email_accounts = (frappe.boot.email_accounts || []).filter(function (account) {
		return account.enable_outgoing &&
			["All Accounts", "Sent", "Spam", "Trash"].indexOf(account.email_account) === -1;
	});
	var sender_options = email_accounts.map(function (account) {
		return account.email_id;
	});
	var print_formats = ((frm.print_preview || {}).print_formats || ["Standard"]);
	var default_print_format = frm.meta.default_print_format || print_formats[0];

	if (!sender_options.length) {
		frappe.msgprint(__("No outgoing Email Account is linked to your User."));
		return;
	}

	var dialog = new frappe.ui.Dialog({
		title: __("Review Supplier Emails"),
		fields: [
			{
				fieldname: "sender",
				fieldtype: "Select",
				label: __("From"),
				options: sender_options,
				reqd: 1
			},
			{
				fieldname: "recipients",
				fieldtype: "Small Text",
				label: __("To"),
				read_only: 1,
				default: suppliers.map(function (row) {
					return (row.supplier_name || row.supplier) + " <" + row.email_id + ">";
				}).join("\n")
			},
			{
				fieldname: "separate_email_notice",
				fieldtype: "HTML",
				options: '<p class="text-muted small">' +
					__("Each supplier will receive a separate email with the RFQ PDF.") +
					'</p>'
			},
			{
				fieldname: "email_template",
				fieldtype: "Link",
				options: "Email Template",
				label: __("Email Template"),
				onchange: function () {
					load_email_template(dialog, frm);
				}
			},
			{
				fieldname: "subject",
				fieldtype: "Data",
				label: __("Subject"),
				default: __("Request for Quotation"),
				reqd: 1
			},
			{
				fieldname: "message",
				fieldtype: "Text Editor",
				label: __("Message"),
				default: frm.doc.message_for_supplier || "",
				reqd: 1
			},
			{
				fieldtype: "Section Break"
			},
			{
				fieldname: "send_me_a_copy",
				fieldtype: "Check",
				label: __("Send me a copy"),
				default: frappe.boot.user.send_me_a_copy || 0
			},
			{
				fieldname: "send_read_receipt",
				fieldtype: "Check",
				label: __("Send Read Receipt"),
				default: 0
			},
			{
				fieldname: "attach_document_print",
				fieldtype: "Check",
				label: __("Attach Document Print"),
				default: 1,
				onchange: function () {
					dialog.fields_dict.print_format.$wrapper.toggle(
						Boolean(dialog.get_value("attach_document_print"))
					);
				}
			},
			{
				fieldname: "print_format",
				fieldtype: "Select",
				label: __("Select Print Format"),
				options: print_formats,
				default: default_print_format
			},
			{
				fieldname: "language",
				fieldtype: "Select",
				label: __("Select Languages"),
				options: frappe.get_languages(),
				default: frm.doc.language || frappe.boot.lang || "en"
			},
			{
				fieldtype: "Column Break"
			},
			{
				fieldname: "select_attachments",
				fieldtype: "HTML",
				label: __("Select Attachments")
			}
		],
		primary_action_label: __("Send Separate Emails"),
		primary_action: function (values) {
			send_supplier_emails(frm, dialog, values);
		}
	});

	dialog.show();
	dialog.fields_dict.print_format.$wrapper.toggle(
		Boolean(dialog.get_value("attach_document_print"))
	);
	render_attachment_selector(dialog, frm);
}

function render_attachment_selector(dialog, frm) {
	var wrapper = $(dialog.fields_dict.select_attachments.wrapper).empty();
	$("<h6 class='text-muted'>").text(__("Select Attachments")).appendTo(wrapper);
	var list = $("<div class='rfq-email-attachment-list'>").appendTo(wrapper);

	function add_attachment_row(file) {
		if (!file || !file.name || list.find('[data-file-name="' + file.name + '"]').length) {
			return;
		}
		var row = $("<p class='checkbox'>").appendTo(list);
		var label = $("<label>").appendTo(row);
		$("<input type='checkbox' class='rfq-email-attachment' checked>")
			.attr("data-file-name", file.name)
			.appendTo(label);
		$("<span class='small'>")
			.text(" " + (file.file_name || file.name))
			.appendTo(label);
	}

	(frm.get_files() || []).forEach(add_attachment_row);

	var add_link_row = $("<p>").appendTo(wrapper);
	var add_link = $("<a class='text-muted small' style='cursor:pointer'>")
		.text("+ " + __("Add Attachment"))
		.appendTo(add_link_row);
	add_link.on("click", function () {
		new frappe.ui.FileUploader({
			doctype: frm.doctype,
			docname: frm.docname,
			folder: "Home/Attachments",
			on_success: function (attachment) {
				frm.attachments.attachment_uploaded(attachment);
				add_attachment_row(attachment);
			}
		});
	});
}

function load_email_template(dialog, frm) {
	var template_name = dialog.get_value("email_template");
	if (!template_name) return;

	frappe.call({
		method: "frappe.email.doctype.email_template.email_template.get_email_template",
		args: {
			template_name: template_name,
			doc: frm.doc
		},
		callback: function (r) {
			if (!r.message) return;
			dialog.set_value("subject", r.message.subject || __("Request for Quotation"));
			dialog.set_value("message", r.message.message || "");
		}
	});
}

function send_supplier_emails(frm, dialog, values) {
	var button = dialog.get_primary_btn();
	var selected_attachments = $.map(
		$(dialog.wrapper).find(".rfq-email-attachment:checked"),
		function (element) {
			return $(element).attr("data-file-name");
		}
	);
	return frappe.call({
		method: "worldshading.api.request_for_quotation.send_supplier_emails_with_review",
		args: {
			rfq_name: frm.doc.name,
			sender: values.sender,
			subject: values.subject,
			message: values.message,
			email_template: values.email_template,
			send_me_a_copy: values.send_me_a_copy,
			read_receipt: values.send_read_receipt,
			attach_document_print: values.attach_document_print,
			print_format: values.print_format,
			language: values.language,
			selected_attachments: JSON.stringify(selected_attachments)
		},
		freeze: true,
		freeze_message: __("Preparing separate supplier emails..."),
		btn: button,
		callback: function (r) {
			if (!r.exc) {
				dialog.hide();
				frm.reload_doc();
				frappe.msgprint(__("{0} supplier email(s) added to the Email Queue.", [
					(r.message || {}).sent_count || 0
				]));
			}
		}
	});
}

function fetch_matching_suppliers(frm) {
	var item_codes = (frm.doc.items || []).map(function (row) {
		return row.item_code;
	}).filter(Boolean);

	if (!item_codes.length) {
		frappe.msgprint(__("Add RFQ items before fetching suppliers."));
		return;
	}

	frappe.call({
		method: "worldshading.api.request_for_quotation.get_suppliers_for_items",
		args: {
			item_codes: item_codes,
			country_of_purchase: frm.doc.country_of_purchase
		},
		freeze: true,
		freeze_message: __("Finding suppliers by Item Group..."),
		callback: function (r) {
			var result = r.message || {};
			var suppliers = result.suppliers || [];
			var existing = {};
			var added = 0;
			var grid_rows = frm.get_field("suppliers").grid.grid_rows || [];

			// ERPNext may create an empty first row automatically. Remove only
			// blank rows so the first matched supplier starts at row 1.
			grid_rows.slice().reverse().forEach(function (grid_row) {
				if (!grid_row.doc.supplier) grid_row.remove();
			});

			(frm.doc.suppliers || []).forEach(function (row) {
				if (row.supplier) existing[row.supplier] = true;
			});

			suppliers.forEach(function (supplier) {
				if (existing[supplier.name]) return;
				var row = frm.add_child("suppliers");
				row.supplier = supplier.name;
				existing[supplier.name] = true;
				added += 1;
				frm.script_manager.trigger("supplier", row.doctype, row.name);
			});

			frm.refresh_field("suppliers");
			if (!suppliers.length) {
				frappe.msgprint(__("No eligible suppliers are configured for the RFQ Item Groups."));
			} else {
				frappe.show_alert({
					message: __("{0} supplier(s) added; {1} already present.",
						[added, suppliers.length - added]),
					indicator: added ? "green" : "blue"
				});
			}
		}
	});
}
