(function () {
	if (!frappe.ui || !frappe.ui.form || !frappe.ui.form.ControlData) return;

	var control_data = frappe.ui.form.ControlData.prototype;
	if (control_data.worldshading_email_validation_timing) return;

	var original_bind_change_event = control_data.bind_change_event;
	control_data.bind_change_event = function () {
		var is_email_account_address = this.doctype === "Email Account" &&
			this.df && this.df.fieldname === "email_id";
		if (!this.df || (this.df.options !== "Email" && !is_email_account_address)) {
			return original_bind_change_event.apply(this, arguments);
		}

		var control = this;
		var change_handler = function (event) {
			if (control.change) {
				control.change(event);
			} else {
				control.parse_validate_and_set_in_model(
					control.get_input_value(), event
				);
			}
		};

		// Frappe v12 normally also binds a debounced input event here. For
		// Email fields that validates partial text and opens a blocking popup.
		// Native change still validates when the user leaves the field.
		this.$input.on("change", change_handler);
	};

	control_data.worldshading_email_validation_timing = true;
})();
