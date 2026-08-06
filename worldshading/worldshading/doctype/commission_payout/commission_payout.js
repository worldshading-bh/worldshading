// Copyright (c) 2026, Hilal Habeeb and contributors
// For license information, please see license.txt

frappe.ui.form.on('Commission Payout', {
	refresh: function(frm) {
		if (frm.doc.docstatus === 0) {
			frm.add_custom_button(__('Fetch Details'), function() {
				ws_fetch_payout_details(frm);
			}).addClass('btn-primary');
		}

		if (frm.doc.docstatus === 1 && !frm.doc.journal_entry) {
			frm.add_custom_button(__('Create Journal Entry'), function() {
				ws_create_payout_journal_entry(frm);
			}).addClass('btn-primary');
		}
	}
});

function ws_create_payout_journal_entry(frm) {
	var saved = {};
	try {
		saved = JSON.parse(localStorage.getItem('ws_cp_je_defaults') || '{}');
	} catch (e) { saved = {}; }

	var dialog = new frappe.ui.Dialog({
		title: __('Create Journal Entry'),
		fields: [
			{
				fieldname: 'entry_type', fieldtype: 'Select', label: __('Entry Type'),
				options: ['Journal Entry', 'Bank Entry', 'Cash Entry'],
				default: saved.entry_type || 'Journal Entry', reqd: 1
			},
			{
				fieldname: 'expense_account', fieldtype: 'Link', options: 'Account',
				label: __('Expense Account (Debit)'), reqd: 1,
				default: saved.expense_account,
				get_query: function() {
					return { filters: { company: frm.doc.company, is_group: 0, root_type: 'Expense' } };
				}
			},
			{
				fieldname: 'payment_account', fieldtype: 'Link', options: 'Account',
				label: __('Payment Account (Credit)'), reqd: 1,
				default: saved.payment_account,
				get_query: function() {
					return { filters: { company: frm.doc.company, is_group: 0 } };
				}
			},
			{ fieldname: 'col_1', fieldtype: 'Column Break' },
			{
				fieldname: 'total_html', fieldtype: 'HTML',
				options: '<div style="padding:8px 0;"><div style="color:var(--text-muted);font-size:11px;text-transform:uppercase;">' +
					__('Total to post') + '</div><div style="font-size:22px;font-weight:700;">' +
					format_currency(frm.doc.total_amount, 'BHD') + '</div></div>'
			},
			{ fieldname: 'reference_no', fieldtype: 'Data', label: __('Reference No') },
			{ fieldname: 'reference_date', fieldtype: 'Date', label: __('Reference Date') }
		],
		primary_action_label: __('Create'),
		primary_action: function(values) {
			dialog.hide();

			localStorage.setItem('ws_cp_je_defaults', JSON.stringify({
				entry_type: values.entry_type,
				expense_account: values.expense_account,
				payment_account: values.payment_account
			}));

			frappe.call({
				method: 'worldshading.worldshading.doctype.commission_payout.commission_payout.create_journal_entry',
				args: {
					name: frm.doc.name,
					expense_account: values.expense_account,
					payment_account: values.payment_account,
					entry_type: values.entry_type,
					reference_no: values.reference_no,
					reference_date: values.reference_date
				},
				freeze: true,
				freeze_message: __('Creating Journal Entry...'),
				callback: function(r) {
					if (r.message) {
						frappe.set_route('Form', 'Journal Entry', r.message);
					}
				}
			});
		}
	});

	dialog.show();
}

function ws_fetch_payout_details(frm) {
	if (!frm.doc.payout_month || !frm.doc.posting_date) {
		frappe.msgprint(__('Set Payout Month and Posting Date first.'));
		return;
	}

	frappe.call({
		method: 'worldshading.worldshading.doctype.commission_payout.commission_payout.get_payout_details',
		args: {
			payout_month: frm.doc.payout_month,
			posting_date: frm.doc.posting_date,
			commission_type: frm.doc.commission_type
		},
		freeze: true,
		freeze_message: __('Calculating commission...'),
		callback: function(r) {
			var rows = r.message || [];

			frm.clear_table('details');

			rows.forEach(function(row) {
				var child = frm.add_child('details');
				Object.keys(row).forEach(function(key) {
					child[key] = row[key];
				});
			});

			frm.doc.total_amount = rows.reduce(function(total, row) {
				return total + (row.amount || 0);
			}, 0);

			frm.refresh_field('details');
			frm.refresh_field('total_amount');
			frm.dirty();

			if (!rows.length) {
				frappe.msgprint(__('Nothing pending for this period.'));
			}
		}
	});
}
