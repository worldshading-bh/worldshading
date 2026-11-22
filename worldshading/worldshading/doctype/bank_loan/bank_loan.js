frappe.ui.form.on('Bank Loan', {
    setup: bank_loan_queries,
    validate: prepare_bank_loan_revision,
    before_workflow_action: function (frm) {
        return prepare_bank_loan_revision(frm).then(function (ready) {
            if (!ready) {
                frm.selected_workflow_action = null;
                return Promise.reject(new Error(__('Revision cancelled.')));
            }
        });
    },
    loan_position: sync_bank_loan_opening,
    original_principal: sync_bank_loan_opening,
    disbursement_date: sync_bank_loan_opening,
    company: bank_loan_queries,
    currency: function (frm) {
        bank_loan_queries(frm);
        if ((frm.doc.schedule || []).length) {
            frappe.msgprint(__('Currency changed. Review the principal, schedule amounts and ledger accounts; amounts have not been converted.'));
        }
    },
    refresh: function (frm) {
        const locked = frm.doc.workflow_state && frm.doc.workflow_state !== 'Draft';
        bank_loan_lock_fields(frm, locked);
        const maker = frappe.session && (frappe.session.user === 'Administrator' ||
            (frappe.user_roles || []).includes('Maker - ACC (Workflow)'));
        if (!locked && !frm.doc.docstatus && maker) {
            frm.add_custom_button(__('Generate Schedule'), function () { show_bank_loan_schedule_dialog(frm); });
        }
    }
});

function bank_loan_plan_changed(doc) {
    let baseline;
    try { baseline = JSON.parse(doc.approved_plan); } catch (error) { return false; }
    const numeric = ['original_principal', 'opening_principal', 'annual_interest_rate',
        'principal_amount', 'interest_amount', 'charges_amount'];
    const normalize = function (value, key) {
        if (numeric.includes(key)) return Number(value || 0);
        if (key === 'agreement_number') return String(value || '').trim().replace(/\s+/g, ' ').toUpperCase() || null;
        return value || null;
    };
    return Object.keys(baseline).some(function (key) {
        if (key !== 'schedule') return normalize(doc[key], key) !== normalize(baseline[key], key);
        const rows = doc.schedule || [], previous = baseline.schedule || [];
        return rows.length !== previous.length || previous.some(function (row, index) {
            return Object.keys(row).some(function (field) {
                return normalize(rows[index][field], field) !== normalize(row[field], field);
            });
        });
    });
}

async function prepare_bank_loan_revision(frm) {
    if (!frm.doc.approved_plan || frm.doc.workflow_state !== 'Draft') return true;
    const dates = (frm.doc.schedule || []).map(function (row) { return row.due_date; }).filter(Boolean).sort();
    const last = dates[dates.length - 1];
    if (last && last > frm.doc.maturity_date) await frm.set_value({maturity_date: last});
    if (!bank_loan_plan_changed(frm.doc)) return true;
    if ((frm.doc.revision_reason || '').trim()) {
        if (!frm.doc.revision_effective_date) await frm.set_value({revision_effective_date: frappe.datetime.get_today()});
        return true;
    }
    return new Promise(function (resolve) {
        let accepted = false;
        const dialog = new frappe.ui.Dialog({
            title: __('Reason for Loan Revision'),
            fields: [
                {fieldname: 'reason', label: __('What changed and why?'), fieldtype: 'Small Text', reqd: 1},
                {fieldname: 'revision_date', label: __('Revision Date'), fieldtype: 'Date', read_only: 1,
                    default: frappe.datetime.get_today()}
            ],
            primary_action_label: __('Continue'),
            primary_action: async function (values) {
                const reason = String(values.reason || '').trim();
                if (!reason) return;
                await frm.set_value({revision_reason: reason, revision_effective_date: frappe.datetime.get_today()});
                accepted = true;
                dialog.hide();
                resolve(true);
            },
            onhide: function () {
                if (!accepted) { frappe.validated = false; resolve(false); }
            }
        });
        dialog.show();
    });
}

function bank_loan_queries(frm) {
    ['loan_account', 'interest_account', 'charges_account', 'payment_account'].forEach(function (field) {
        frm.set_query(field, function () {
            const filters = {company: frm.doc.company, account_currency: frm.doc.currency,
                is_group: 0, disabled: 0,
                root_type: field === 'loan_account' ? 'Liability' : field === 'payment_account' ? 'Asset' : 'Expense'};
            if (field === 'payment_account') filters.account_type = 'Bank';
            return {filters: filters};
        });
    });
    frm.set_query('cost_center', function () {
        return {filters: {company: frm.doc.company, is_group: 0}};
    });
}

function bank_loan_lock_fields(frm, locked) {
    if (!frm._bank_loan_editable_fields) {
        frm._bank_loan_editable_fields = (frm.meta.fields || []).filter(function (field) {
            return !field.read_only && !['Section Break', 'Column Break', 'HTML'].includes(field.fieldtype);
        }).map(function (field) { return field.fieldname; });
    }
    frm._bank_loan_editable_fields.forEach(function (field) {
        frm.set_df_property(field, 'read_only', locked ? 1 : 0);
    });
}

function sync_bank_loan_opening(frm) {
    if (frm.doc.loan_position !== 'New Loan' ||
        (frm.doc.workflow_state && frm.doc.workflow_state !== 'Draft')) return;
    const values = {};
    const principal = frm.doc.original_principal || 0;
    const start = frm.doc.disbursement_date || null;
    if (frm.doc.opening_principal !== principal) values.opening_principal = principal;
    if ((frm.doc.tracking_start_date || null) !== start) values.tracking_start_date = start;
    if (Object.keys(values).length) return frm.set_value(values);
}

function show_bank_loan_schedule_dialog(frm) {
    if (frm.doc.workflow_state && frm.doc.workflow_state !== 'Draft') {
        frappe.msgprint(__('Return the loan to Draft before generating a schedule.'));
        return;
    }
    const variable = frm.doc.interest_rate_type === 'Variable';
    const existing = frm.doc.schedule || [];
    const months = {Monthly: 1, Quarterly: 3, 'Half-yearly': 6, Yearly: 12};
    const first = existing.length ? existing[0].due_date : frappe.datetime.add_months(
        frm.doc.disbursement_date || frappe.datetime.get_today(), months[frm.doc.repayment_frequency] || 1);
    const upcoming = existing.filter(function (row) { return row.due_date >= frappe.datetime.get_today(); });
    let requestNumber = 0;
    let settings;
    const fields = [];
    if (!variable) {
        fields.push({fieldname: 'calculation_mode', label: __('Calculate Using'), fieldtype: 'Select',
            options: 'Interest Rate\nInstallment Amount', default: 'Interest Rate',
            onchange: function () { if (settings) update_bank_loan_rate_fields(settings); }});
    }
    fields.push(
        {fieldname: 'method', label: __('Repayment Method'), fieldtype: 'Select', reqd: 1,
            options: 'Equal Installments\nEqual Principal\nInterest Only / Balloon', default: 'Equal Installments'}
    );
    if (!variable) {
        const row = existing[0] || {};
        fields.push({fieldname: 'installment_amount', label: __('Installment Amount'), fieldtype: 'Currency', hidden: 1,
            default: Number(row.principal_amount || 0) + Number(row.interest_amount || 0),
            description: __('Principal + interest only. Add separate charges in the schedule.')});
    }
    if (variable && existing.length) {
        fields.push({fieldname: 'rate_change', label: __('Update Future Rate Only'), fieldtype: 'Check', default: 0,
            onchange: function () { if (settings) update_bank_loan_rate_fields(settings); }});
    }
    fields.push(
        {fieldname: 'first_due_date', label: __('First Payment Date'), fieldtype: 'Date', reqd: 1, default: first},
        {fieldname: 'periods', label: __('Number of Installments'), fieldtype: 'Int', reqd: 1, default: existing.length || 12}
    );
    if (variable && existing.length) {
        fields.push(
            {fieldname: 'effective_date', label: __('Rate Effective Date'), fieldtype: 'Date', hidden: 1,
                default: upcoming.length ? upcoming[0].due_date : frappe.datetime.get_today()},
            {fieldname: 'new_rate', label: __('New Annual Rate (%)'), fieldtype: 'Percent', hidden: 1,
                default: frm.doc.annual_interest_rate || 0}
        );
    }
    settings = new frappe.ui.Dialog({
        title: __('Generate Loan Schedule'),
        fields: fields,
        primary_action_label: __('Preview'),
        primary_action: function (values) {
            if (!values) return;
            const snapshot = JSON.stringify(frm.doc);
            const parameters = JSON.stringify(values);
            const options = Object.assign({}, values);
            if (values.calculation_mode === 'Installment Amount') {
                options.rate_source = 'Use Recorded Rate';
                options.remaining_balance = 'Add Final Settlement';
            }
            const request = ++requestNumber;
            frappe.call({
                method: 'worldshading.api.bank_loan_schedule.preview_schedule',
                args: {loan: snapshot, options: JSON.stringify(options)}, freeze: true,
                callback: function (reply) {
                    if (!reply.message || request !== requestNumber) return;
                    if (snapshot !== JSON.stringify(frm.doc) || parameters !== JSON.stringify(settings.get_values())) {
                        frappe.msgprint(__('Inputs changed. Preview the schedule again.'));
                        return;
                    }
                    show_bank_loan_schedule_preview(frm, reply.message, snapshot, settings);
                }
            });
        }
    });
    update_bank_loan_rate_fields(settings);
    settings.show();
}

function update_bank_loan_rate_fields(settings) {
    const changing = Number(settings.get_value('rate_change') || 0) === 1;
    const byAmount = settings.get_value('calculation_mode') === 'Installment Amount';
    const amountField = settings.fields_dict.installment_amount;
    if (amountField) { amountField.df.reqd = byAmount ? 1 : 0; amountField.toggle(byAmount); }
    if (byAmount) settings.set_value('method', 'Equal Installments');
    settings.fields_dict.method.df.reqd = byAmount ? 0 : 1;
    settings.fields_dict.method.toggle(!byAmount);
    ['first_due_date', 'periods', 'effective_date', 'new_rate'].forEach(function (name) {
        const field = settings.fields_dict[name];
        if (!field) return;
        const rateField = name === 'effective_date' || name === 'new_rate';
        const show = rateField ? changing : !changing;
        field.df.reqd = show ? 1 : 0;
        field.toggle(show);
    });
}

function show_bank_loan_schedule_preview(frm, result, snapshot, settings) {
    const escape = frappe.utils.escape_html;
    const amount = function (value) { return Number(value || 0).toFixed(result.precision); };
    let html = '<p>' + escape(__('Total: ')) + amount(result.scheduled_total) + ' ' + escape(frm.doc.currency || '');
    if (result.retained_rows) html += ' &nbsp; ' + escape(__('Earlier rows retained: ')) + Number(result.retained_rows);
    html += '</p>';
    if (result.calculation_mode === 'Installment Amount') {
        const recorded = result.rate_source === 'Use Recorded Rate';
        const rateLabel = recorded ? __('Annual Interest Rate: ') : __('Estimated Annual Rate (nominal): ');
        const rate = recorded ? result.recorded_annual_rate : result.estimated_annual_rate;
        html += '<p><strong>' + escape(__('Installment: ')) + amount(result.installment_amount) + ' ' + escape(frm.doc.currency || '') + '</strong>' +
            ' &nbsp; ' + escape(rateLabel) + (recorded ? Number(rate) : Number(rate).toFixed(6)) + '%</p>';
        if (recorded) {
            html += '<p>' + escape(__('Generated installments: ')) + result.rows.length + ' &nbsp; ' +
                escape(result.settlement_added ? __('Final Settlement: ') : __('Final payment: ')) + amount(result.final_payment_amount) + ' ' + escape(frm.doc.currency || '') + '</p>';
            html += '<p class="text-muted">' + escape(__('Uses the loan interest rate. Any remaining principal is added as a final payment. Confirm the schedule with the bank.')) + '</p>';
        } else {
            html += '<p class="text-muted">' + escape(__('Estimated split for regular periods; excludes separate fees/balloon. Confirm with the bank. Recorded loan rate unchanged.')) + '</p>';
            if (Number(result.final_payment_adjustment)) html += '<p>' + escape(__('Final payment adjustment: ')) + amount(result.final_payment_adjustment) + ' ' + escape(frm.doc.currency || '') + '</p>';
            if (Number(result.final_interest_adjustment)) html += '<p>' + escape(__('Final interest rounding: ')) + amount(result.final_interest_adjustment) + ' ' + escape(frm.doc.currency || '') + '</p>';
        }
        if (result.maturity_date) html += '<p class="text-warning">' + escape(__('Maturity extended: ')) + escape(result.previous_maturity_date) + ' → ' + escape(result.maturity_date) + '</p>';
    }
    html += '<div style="max-height:360px;overflow:auto"><table class="table table-bordered"><thead><tr>';
    ['Due Date', 'Principal', 'Interest', 'Charges', 'Total', 'Principal Balance'].forEach(function (label) {
        html += '<th>' + escape(__(label)) + '</th>';
    });
    html += '</tr></thead><tbody>';
    result.rows.forEach(function (row) {
        html += '<tr><td>' + escape(row.due_date);
        if (row.settlement_row) html += '<br><small>' + escape(__('Final Settlement')) + '</small>';
        else if (row.final_payment) html += '<br><small>' + escape(__('Final payment')) + '</small>';
        html += '</td>';
        ['principal_amount', 'interest_amount', 'charges_amount', 'total_amount', 'projected_principal_balance'].forEach(function (field) {
            html += '<td>' + amount(row[field]) + '</td>';
        });
        html += '</tr>';
    });
    html += '</tbody></table></div>';
    const preview = new frappe.ui.Dialog({
        title: __('Schedule Preview'),
        fields: [{fieldname: 'preview', fieldtype: 'HTML'}],
        primary_action_label: __('Apply to Draft'),
        primary_action: function () { return apply_bank_loan_schedule(frm, result, snapshot, preview); },
        secondary_action_label: __('Back'),
        onhide: function () { if (!preview._bank_loan_applied) settings.show(); }
    });
    preview.fields_dict.preview.$wrapper.html(html);
    settings.hide();
    preview.show();
}

function apply_bank_loan_schedule(frm, result, snapshot, preview) {
    return new Promise(function (resolve, reject) {
        const apply = function () {
            if (JSON.stringify(frm.doc) !== snapshot ||
                (frm.doc.workflow_state && frm.doc.workflow_state !== 'Draft')) {
                frappe.msgprint(__('The loan changed. Generate a fresh preview before applying.'));
                resolve(false);
                return;
            }
            const retained = result.retained_rows || 0;
            (frm.doc.schedule || []).slice(retained).forEach(function (row) {
                frappe.model.clear_doc(row.doctype, row.name);
            });
            result.rows.slice(retained).forEach(function (row) {
                const values = {};
                ['installment_number', 'due_date', 'principal_amount', 'interest_amount', 'charges_amount',
                    'total_amount', 'projected_principal_balance', 'remarks'].forEach(function (field) { values[field] = row[field]; });
                values.currency = frm.doc.currency;
                frm.add_child('schedule', values);
            });
            const totals = {};
            ['scheduled_principal', 'scheduled_interest', 'scheduled_charges', 'scheduled_total', 'unscheduled_principal'].forEach(function (field) {
                totals[field] = result[field];
            });
            if (result.maturity_date) totals.maturity_date = result.maturity_date;
            Promise.resolve(frm.set_value(totals)).then(function () {
                frm.refresh_field('schedule');
                frm.dirty();
                preview._bank_loan_applied = true;
                preview.hide();
                resolve(true);
            }).catch(reject);
        };
        if ((frm.doc.schedule || []).length > (result.retained_rows || 0)) {
            frappe.confirm(__('Replace the affected schedule rows with this preview? Earlier retained rows stay unchanged.'), apply, function () { resolve(false); });
        } else {
            apply();
        }
    });
}
