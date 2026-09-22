(function () {
	var settings = frappe.listview_settings["Sales Order"] || {};
	var original_onload = settings.onload;

	settings.add_fields = settings.add_fields || [];
	if (settings.add_fields.indexOf("workflow_state") === -1) {
		settings.add_fields.push("workflow_state");
	}

	settings.formatters = settings.formatters || {};
	settings.formatters.workflow_state = function (value) {
		if (!value) {
			return "";
		}

		var colors = window.worldshading_workflow_state_colors || {};
		var color = colors[value] || frappe.utils.guess_colour(value) || "grey";

		return '<span class="indicator ' + color + '">' +
			frappe.utils.escape_html(value) + '</span>';
	};

	settings.onload = function (listview) {
		if (original_onload) {
			original_onload(listview);
		}

		load_workflow_state_colors(listview);

		setTimeout(function () {
			listview.page.actions_menu.find("a").each(function () {
				var text = $(this).text().trim();
				if (text === "Close" || text === "Re-open") {
					$(this).parent().remove();
				}
			});
		}, 300);
	};

	frappe.listview_settings["Sales Order"] = settings;


	function load_workflow_state_colors(listview) {
		if (window.worldshading_workflow_state_colors ||
			window.worldshading_workflow_state_colors_loading) {
			return;
		}

		window.worldshading_workflow_state_colors_loading = true;

		frappe.call({
			method: "frappe.client.get_list",
			args: {
				doctype: "Workflow State",
				fields: ["name", "style"],
				limit_page_length: 500
			},
			callback: function (response) {
				var style_colors = {
					"Success": "green",
					"Warning": "orange",
					"Danger": "red",
					"Primary": "blue",
					"Info": "blue",
					"Inverse": "grey"
				};
				var colors = {};

				(response.message || []).forEach(function (state) {
					colors[state.name] = style_colors[state.style] ||
						frappe.utils.guess_colour(state.name) || "grey";
				});

				window.worldshading_workflow_state_colors = colors;
				window.worldshading_workflow_state_colors_loading = false;
				listview.refresh();
			},
			error: function () {
				window.worldshading_workflow_state_colors_loading = false;
			}
		});
	}
})();
