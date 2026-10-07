const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");
const script = fs.readFileSync(path.join(__dirname, "notification_sound.js"), "utf8");
const listeners = [], calls = [], alerts = [];
let timer, plays = 0;
const context = {
	__: value => value,
	strip_html: value => value.replace(/<[^>]*>/g, ""),
	setTimeout: callback => { timer = callback; return 1; },
	clearTimeout: () => { timer = null; },
	Audio: function () {
		this.play = function () { plays += 1; throw new Error("Autoplay blocked"); };
	},
	frappe: {
		session: {user: "user@example.com"},
		after_ajax: callback => callback(),
		realtime: {on: (event, callback) => {
			assert.strictEqual(event, "notification"); listeners.push(callback);
		}},
		utils: {escape_html: value => value.replace(/&/g, "&amp;").replace(/</g, "&lt;")
			.replace(/>/g, "&gt;").replace(/"/g, "&quot;")},
		call: options => calls.push(options),
		show_alert: (options, duration) => { assert.strictEqual(duration, 10); alerts.push(options); }
	}
};
vm.createContext(context);
vm.runInContext(script, context);
vm.runInContext(script, context);
assert.strictEqual(listeners.length, 1, "Hooks and startup loader must not duplicate alerts");
listeners[0](); listeners[0](); listeners[0]();
timer();
assert.strictEqual(calls.length, 1, "Batch notification bursts");
assert.strictEqual(calls[0].args.filters.for_user, "user@example.com");
assert.strictEqual(calls[0].args.limit_page_length, 1);
const row = {name: "N-1", subject: '<b>Assigned</b> <img src=x onerror=alert(1)>',
	document_type: "Purchase Order", document_name: 'PO/1"'};
calls[0].callback({message: [row]});
assert.strictEqual(alerts.length, 1);
assert.ok(alerts[0].message.includes("Assigned"));
assert.ok(!alerts[0].message.includes("<img"));
assert.ok(alerts[0].message.includes("#Form/Purchase%20Order/PO%2F1%22"));
assert.strictEqual(plays, 1, "Audio failure does not prevent the visual alert");
listeners[0](row);
assert.strictEqual(alerts.length, 1, "Do not repeat the same latest notification");
listeners[0]({subject: "New assignment"});
assert.strictEqual(alerts.length, 2);
assert.strictEqual(calls.length, 1, "No lookup when an event includes the subject");
listeners[0](); timer(); calls[1].error();
assert.ok(alerts[2].message.includes("You have a new notification"));
const beforeRemoval = alerts.length;
const soundBeforeRemoval = plays;
const removal = {name: "N-removed", type: "Assignment",
	subject: 'Your assignment on <b>Purchase Order</b> <b>PO-1</b> has been removed by <b>Administrator</b>'};
listeners[0](); timer(); calls[2].callback({message: [removal]});
listeners[0](Object.assign({}, removal, {name: "N-removed-direct"}));
assert.strictEqual(alerts.length, beforeRemoval, "No alert for assignment removal via fetch or payload");
assert.strictEqual(plays, soundBeforeRemoval, "No sound for assignment removal");
listeners[0]({name: "N-new", type: "Assignment",
	subject: "Administrator assigned a new task Purchase Order PO-1 to you"});
listeners[0]({name: "N-urgent", type: "Assignment",
	subject: "Urgent Purchase Order PO-1 needs your action — Pending. Reason: Pay today"});
assert.strictEqual(alerts.length, beforeRemoval + 2, "New assignments and urgency still alert");
assert.strictEqual(plays, soundBeforeRemoval + 2);
console.log("Notification alerts: removals silent; new assignments, urgency and audio fallback OK");
