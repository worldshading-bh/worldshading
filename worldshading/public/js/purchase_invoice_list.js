frappe.listview_settings['Purchase Invoice'] = {

    add_fields: ['supplier_name'],

    refresh: function(listview) {

        setTimeout(function () {

            // Build name → doc map once
            const docMap = {};
            listview.data.forEach(d => {
                docMap[d.name] = d;
            });

            listview.$result.find('.list-row').each(function () {

                const row = $(this);
                const link = row.find('a[data-name]');
                if (!link.length) return;

                const docname = link.attr('data-name');
                if (!docname) return;

                const doc = docMap[docname];
                if (!doc || !doc.supplier_name) return;

                link.removeAttr('title');
                link.attr('title', doc.supplier_name);
            });

        }, 300);
    }
};
