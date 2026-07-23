// Copyright (c) 2026, Hilal Habeeb and contributors
// For license information, please see license.txt

frappe.ui.form.on('Work Team', {
	refresh: function (frm) {
		// Display-only sync on load so it never leaves the form in a dirty state.
		sync_working_hours_summary(frm, false);
	}
});

frappe.ui.form.on('Work Team Timing', {
	start_time: function (frm) {
		sync_working_hours_summary(frm, true);
	},
	end_time: function (frm) {
		sync_working_hours_summary(frm, true);
	},
	working_hours_remove: function (frm) {
		sync_working_hours_summary(frm, true);
	}
});

// Build the summary in row order (row 1, row 2, ...) to mirror work_team.py exactly.
function build_working_hours_summary(frm) {
	return (frm.doc.working_hours || [])
		.filter(function (row) { return row.start_time && row.end_time; })
		.map(function (row) { return format_time_12h(row.start_time) + ' - ' + format_time_12h(row.end_time); })
		.join(', ');
}

function sync_working_hours_summary(frm, mark_dirty) {
	var summary = build_working_hours_summary(frm);
	if ((frm.doc.working_hours_summary || '') === summary) {
		return;
	}
	if (mark_dirty) {
		// A genuine user edit of the times — dirtying the form is correct.
		frm.set_value('working_hours_summary', summary);
	} else {
		// On load: update the display without marking the form as unsaved.
		frm.doc.working_hours_summary = summary;
		frm.refresh_field('working_hours_summary');
	}
}

// Mirror of format_time_12h in work_team.py so the live preview matches the saved value.
function format_time_12h(time_str) {
	var parts = String(time_str).split(':');
	var hour = parseInt(parts[0], 10);
	var minute = parseInt(parts[1], 10) || 0;
	var meridiem = hour < 12 ? 'AM' : 'PM';
	var hour_12 = hour % 12 || 12;
	return hour_12 + ':' + (minute < 10 ? '0' + minute : minute) + ' ' + meridiem;
}
