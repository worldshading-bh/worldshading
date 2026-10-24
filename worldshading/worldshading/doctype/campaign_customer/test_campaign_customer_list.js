const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const scriptPath = path.join(__dirname, "campaign_customer_list.js");
assert.ok(fs.existsSync(scriptPath), "Missing Campaign Customer list script");

let lastDialog;
let lastCall;
let message;
const sandbox = {
    __: function(value) { return value; },
    frappe: {
        listview_settings: {},
        ui: {
            Dialog: function(options) {
                this.options = options;
                this.values = {};
                this.fields_dict = {};
                options.fields.forEach((field) => {
                    if (!field.fieldname) { return; }
                    this.values[field.fieldname] = field.default || "";
                    this.fields_dict[field.fieldname] = {
                        set_value: (value) => { this.values[field.fieldname] = value; }
                    };
                });
                this.get_value = (fieldname) => this.values[fieldname];
                this.show = () => { this.shown = true; };
                this.hide = () => { this.hidden = true; };
                lastDialog = this;
            }
        },
        call: function(options) {
            lastCall = options;
            options.callback({message: {name: options.args.name}});
        },
        msgprint: function(value) { message = value; }
    }
};

vm.runInNewContext(fs.readFileSync(scriptPath, "utf8"), sandbox, {
    filename: scriptPath
});

function plain(value) {
    return JSON.parse(JSON.stringify(value));
}

const settings = sandbox.frappe.listview_settings["Campaign Customer"];
assert.ok(settings);
assert.deepStrictEqual(plain(settings.add_fields), [
    "status", "caller", "planned_contact_date", "next_follow_up",
    "last_outcome", "latest_note", "next_action"
]);

const expectedIndicators = {
    "Planned": ["Planned", "gray", "status,=,Planned"],
    "Follow Up": ["Follow Up", "orange", "status,=,Follow Up"],
    "Interested": ["Interested", "blue", "status,=,Interested"],
    "Not Interested": ["Not Interested", "red", "status,=,Not Interested"],
    "Converted": ["Converted", "green", "status,=,Converted"],
    "Closed": ["Closed", "darkgrey", "status,=,Closed"]
};
Object.keys(expectedIndicators).forEach((status) => {
    assert.deepStrictEqual(plain(settings.get_indicator({status: status})), expectedIndicators[status]);
});

assert.strictEqual(settings.button.show({status: "Planned"}), true);
assert.strictEqual(settings.button.show({status: "Follow Up"}), true);
assert.strictEqual(settings.button.show({status: "Converted"}), false);
assert.strictEqual(settings.button.show({status: "Closed"}), false);
assert.strictEqual(settings.button.get_label({}), "Record Contact");

const listview = {
    refresh: function() { this.refresh_count = (this.refresh_count || 0) + 1; }
};
settings.onload(listview);
settings.button.action({
    name: "CC-2026-00001",
    status: "Planned",
    next_follow_up: "",
    next_action: "Call"
});
assert.ok(lastDialog.shown);
assert.deepStrictEqual(
    plain(lastDialog.options.fields.filter((field) => field.fieldname).map((field) => field.fieldname)),
    ["channel", "outcome", "notes", "status", "next_follow_up", "next_action"]
);

lastDialog.values.outcome = "Not Interested";
lastDialog.options.fields.find((field) => field.fieldname === "outcome").onchange();
assert.strictEqual(lastDialog.values.status, "Not Interested");

lastDialog.options.primary_action({
    channel: "Call",
    outcome: "Not Interested",
    notes: "Customer declined",
    status: "Not Interested",
    next_follow_up: "",
    next_action: "None"
});
assert.strictEqual(
    lastCall.method,
    "worldshading.worldshading.doctype.campaign_customer.campaign_customer.record_contact"
);
assert.deepStrictEqual(plain(lastCall.args), {
    name: "CC-2026-00001",
    channel: "Call",
    outcome: "Not Interested",
    notes: "Customer declined",
    status: "Not Interested",
    next_follow_up: null,
    next_action: "None"
});
assert.ok(lastDialog.hidden);
assert.strictEqual(listview.refresh_count, 1);

settings.button.action({
    name: "CC-2026-00002",
    status: "Follow Up",
    next_follow_up: "",
    next_action: "Call"
});
message = null;
lastCall = null;
lastDialog.options.primary_action({
    channel: "Call",
    outcome: "No Answer",
    notes: "No response",
    status: "Follow Up",
    next_follow_up: "",
    next_action: "Call"
});
assert.ok(message);
assert.strictEqual(lastCall, null);

console.log("Campaign Customer list behavior: OK");
