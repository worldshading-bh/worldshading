(function () {
	var email_id = frappe.meta.get_docfield("Email Account", "email_id");
	if (email_id) {
		email_id.options = "Email";
	}

	var default_cc = frappe.meta.get_docfield("Email Account", "custom_default_cc");
	if (default_cc) {
		default_cc.fieldtype = "MultiSelect";
		default_cc.options = [];
	}
})();

frappe.ui.form.on("Email Account", {
	refresh: function (frm) {
		var field = make_default_cc_multiselect(frm);
		if (!field) return;

		field.get_data = function () {
			var value = field.get_value() || "";
			var match = value.match(/[^,;\n\r]*$/);
			var options = [];
			frappe.call({
				method: "frappe.email.get_contact_list",
				args: {txt: match ? match[0].trim() : ""},
				callback: function (r) {
					options = r.message || [];
					field.set_data(options);
				}
			});
			return options;
		};
	},

	validate: function (frm) {
		var field = frm.fields_dict.custom_default_cc;
		if (field) {
			frm.doc.custom_default_cc = field.get_value() || "";
		}
	}
});

function make_default_cc_multiselect(frm) {
	var field = frm.fields_dict.custom_default_cc;
	if (!field || field.awesomplete) return field;

	var marker = $('<div class="worldshading-default-cc-marker"></div>');
	marker.insertBefore(field.$wrapper);
	var old_field = field;
	var df = old_field.df;
	df.fieldtype = "MultiSelect";
	df.options = [];

	field = frappe.ui.form.make_control({
		df: df,
		doctype: frm.doctype,
		docname: frm.docname,
		parent: marker.parent().get(0),
		frm: frm,
		doc: frm.doc,
		render_input: true
	});
	field.$wrapper.insertAfter(marker);
	marker.remove();
	old_field.$wrapper.remove();

	field.layout = old_field.layout;
	field.section = old_field.section;
	field.perm = frm.perm;
	field.doc = frm.doc;
	field.doctype = frm.doctype;
	field.docname = frm.docname;
	frm.fields_dict.custom_default_cc = field;
	field.layout.fields_dict.custom_default_cc = field;
	field.section.fields_dict.custom_default_cc = field;
	replace_control(field.layout.fields_list, old_field, field);
	replace_control(field.section.fields_list, old_field, field);

	return field;
}

function replace_control(controls, old_field, new_field) {
	var index = controls.indexOf(old_field);
	if (index !== -1) controls[index] = new_field;
}
