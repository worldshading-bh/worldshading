(function () {
	"use strict";

	// This file can be loaded through hooks or the existing Desk startup asset.
	if (frappe._ws_notification_alert_installed) { return; }
	frappe._ws_notification_alert_installed = true;
	var sound;
	var last_notification;
	var timer;

	frappe.after_ajax(function () {
		frappe.realtime.on("notification", function (data) {
			if (data && data.subject) {
				show_notification(data);
				return;
			}
			// Native v12 sends no payload. Coalesce bursts into one latest-message alert.
			clearTimeout(timer);
			timer = setTimeout(function () {
				frappe.call({
					method: "frappe.client.get_list",
					args: {
						doctype: "Notification Log",
						filters: {for_user: frappe.session.user},
						fields: ["name", "type", "subject", "document_type", "document_name"],
						order_by: "creation desc",
						limit_page_length: 1
					},
					callback: function (response) {
						show_notification((response.message || [])[0] || {});
					},
					error: function () { show_notification({}); }
				});
			}, 250);
		});
	});

	function is_assignment_removal(data) {
		if (data.type && data.type !== "Assignment") { return false; }
		var subject = strip_html(String(data.subject || "")).replace(/\s+/g, " ").trim();
		var template = "Your assignment on {0} {1} has been removed by {2}";
		return [template, __(template)].some(function (text) {
			var pattern = text.replace(/\s+/g, " ").trim().split(/\{\d+\}/).map(function (part) {
				return part.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
			}).join(".+?");
			return new RegExp("^" + pattern + "$", "i").test(subject);
		});
	}

	function show_notification(data) {
		if (data.name && data.name === last_notification) { return; }
		last_notification = data.name;
		if (is_assignment_removal(data)) { return; }
		var message = frappe.utils.escape_html(
			strip_html(String(data.subject || __("You have a new notification")))
		);
		if (data.document_type && data.document_name) {
			var link = "#Form/" + encodeURIComponent(data.document_type) + "/" +
				encodeURIComponent(data.document_name);
			message += ' <a href="' + frappe.utils.escape_html(link) + '">' +
				frappe.utils.escape_html(__("View")) + '</a>';
		}
		frappe.show_alert({message: "🔔 " + message, indicator: "green"}, 10);
		try {
			sound = sound || new Audio("/assets/frappe/sounds/chat-notification.mp3");
			sound.currentTime = 0;
			var playing = sound.play();
			if (playing && playing.catch) { playing.catch(function () {}); }
		} catch (error) {
			// Browser audio restrictions must never prevent the visual alert.
		}
	}
})();
