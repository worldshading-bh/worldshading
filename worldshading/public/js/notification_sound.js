// 🔔 Smart Notification Sound & Full Message Display (final version)
frappe.provide("worldshading");

(function() {
    console.log("✅ notification_sound.js loaded (full message version)");

    frappe.after_ajax(() => {
        console.log("⚡ Realtime listener attached for notifications");

        frappe.realtime.on("notification", function(data) {
            console.log("📩 Realtime event:", data);

            // Extract the same text as shown in the notification dropdown
            let msg = "";
            if (data && data.subject) {
                msg = data.subject; // this is the full message (e.g., "Manu Mohan assigned a new task ...")
            } else {
                msg = __("You have a new notificationnnnn");
            }

            // Optionally add clickable link if document info is available
            if (data && data.document_type && data.document_name) {
                msg += ` <a href="/desk#Form/${data.document_type}/${data.document_name}" target="_blank" style="color:#ffd43b;">[View]</a>`;
            }

            // ✅ Play ERPNext chat notification sound
            try {
                const audio = new Audio("/assets/frappe/sounds/chat-notification.mp3");
                audio.play().catch(err => console.warn("⚠️ Sound play blocked:", err));
            } catch (e) {
                console.error("Sound play error:", e);
            }

            // ✅ Show the same message in a green alert bar
            frappe.show_alert({
                message: "🔔 " + msg,
                indicator: "green"
            }, 10);
        });
    });
})();
