frappe.listview_settings['Bank Loan'] = {
    add_fields: ['bank', 'company', 'currency', 'status', 'maturity_date'],
    get_indicator: function (doc) {
        const colors = {Active: 'green', Inactive: 'orange', Closed: 'gray'};
        return [__(doc.status || 'Inactive'), colors[doc.status] || 'orange',
            'status,=,' + (doc.status || 'Inactive')];
    }
};
