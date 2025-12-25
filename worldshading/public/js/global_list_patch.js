
frappe.listview_settings['Sales Order'] = {
    onload: function(listview) {
        // Wait for menu to actually render
        setTimeout(() => {
            // Remove Close and Re-open from the actions menu
            listview.page.actions_menu.find("a").each(function() {
                let txt = $(this).text().trim();
                if (txt === "Close" || txt === "Re-open") {
                    $(this).parent().remove();
                }
            });
        }, 300);
    }
};


