frappe.query_reports["Incentive Progress"] = {
    filters: [
        {
            fieldname: "incentive_plan",
            label: __("Incentive Plan"),
            fieldtype: "Link",
            options: "Incentive Plan",
            reqd: 1,
            get_query: function () {
                return {
                    filters: {
                        "status": "Active"
                    }
                };
            }
        },
        
        {
            fieldname: "sales_person",
            label: __("Sales Person"),
            fieldtype: "Link",
            options: "Sales Person",
            reqd: 1
        }
    ],

    formatter: function (value, row, column, data, default_formatter) {
        value = default_formatter(value, row, column, data);

        if (!data) return value;

        // 🎯 Color Earned Incentive based on eligibility
        if (column.fieldname === "earned_incentive") {
            if (data.eligible === "Yes") {
                value = `<span style="color:#1a7f37;font-weight:600;">${value}</span>`;
            } else {
                value = `<span style="color:#c62828;font-weight:600;">${value}</span>`;
            }
        }

        return value;
    }
};
