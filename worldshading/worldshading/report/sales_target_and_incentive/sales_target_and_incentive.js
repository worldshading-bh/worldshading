frappe.query_reports["Sales Target and Incentive"] = {
    filters: [
        // Row 1
        {
            fieldname: "reference_year",
            label: __("Reference Year"),
            fieldtype: "Int",
            default: new Date().getFullYear() - 1,
            reqd: 1
        },
        {
            fieldname: "target_increase_pct",
            label: __("Target Increase %"),
            fieldtype: "Float",
            default: 10,
            reqd: 1
        },
        {
            fieldname: "sales_manager_headcount",
            label: __("Manager Headcount"),
            fieldtype: "Int",
            default: 1,
            reqd: 1
        },
        {
            fieldname: "salesman_headcount",
            label: __("Team Members Headcount"),
            fieldtype: "Int",
            default: 4,
            reqd: 1
        },
        {
            fieldname: "company",
            label: __("Company"),
            fieldtype: "Link",
            options: "Company",
            default: frappe.defaults.get_user_default("Company"),
            reqd: 1
        },
        {
            fieldname: "item_group_filter_mode",
            label: __("Item Group Filter Mode"),
            fieldtype: "Select",
            options: [
                "Exclude Selected Item Groups",
                "Include Only Selected Item Groups"
            ],
            default: "Exclude Selected Item Groups"
        },
        {
            fieldname: "exclude_item_groups",
            label: __("Item Groups to Filter"),
            fieldtype: "MultiSelectList",
            options: "Item Group",
            get_data: function (txt) {
                return frappe.db.get_link_options("Item Group", txt);
            }
        },

        {
            fieldname: "incentive_rate",
            label: __("Incentive Rate Policy"),
            fieldtype: "Link",
            options: "Incentive Rate",
            description: __("Optional: Overrides profit-based incentive logic")
        },

        // Row 2
        {
            fieldname: "use_manual_split",
            label: __("Use Manual Incentive Split %"),
            fieldtype: "Check",
            default: 0,
            on_change: function (report) {
                toggle_manual_split_fields(report);
            }
        },
        {
            fieldname: "manager_share_pct",
            label: __("Sales Manager Incentive %"),
            fieldtype: "Data",
            placeholder: __("Enter Manager %")
        },
        {
            fieldname: "team_share_pct",
            label: __("Sales Team Incentive %"),
            fieldtype: "Data",
            placeholder: __("Enter Sales Team %")
        }
    ],

    onload: function (report) {
        toggle_manual_split_fields(report);

        // ✅ Generate Incentive Plan → Backend test
        report.page.add_inner_button(
            __("Generate Incentive Plan"),
            function () {
                const filters = report.get_values();
                const rows = frappe.query_report.data || [];
        
                frappe.confirm(
                    __("This will create an Incentive Plan and freeze quarterly values. Continue?"),
                    function () {
                        frappe.call({
                            method: "worldshading.api.incentive_plan.create_incentive_plan_from_report",
                            args: {
                                filters: filters,
                                rows: rows
                            },
                            freeze: true,
                            freeze_message: __("Creating Incentive Plan..."),
                            callback: function (r) {
                                if (!r.exc && r.message) {
                                    frappe.msgprint({
                                        title: __("Incentive Plan Created"),
                                        message: __("Document: {0}", [r.message.name]),
                                        indicator: "green"
                                    });
        
                                    frappe.set_route("Form", "Incentive Plan", r.message.name);
                                }
                            }
                        });
                    }
                );
            }
        );
        
        
    }
};


function toggle_manual_split_fields(report) {
    const use_manual = report.get_filter_value("use_manual_split");

    const manager_filter = report.get_filter("manager_share_pct");
    const team_filter = report.get_filter("team_share_pct");

    if (manager_filter && team_filter) {
        manager_filter.$wrapper.toggle(use_manual);
        team_filter.$wrapper.toggle(use_manual);
    }
}
