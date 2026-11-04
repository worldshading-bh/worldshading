const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const handlers = {};
const messages = [];
let databaseWrites = 0;

function addDays(value, days) {
    const date = new Date(value + "T00:00:00Z");
    date.setUTCDate(date.getUTCDate() + days);
    return date.toISOString().slice(0, 10);
}

const sandbox = {
    console: console,
    flt: function(value) { return Number(value || 0); },
    __: function(value) { return value; },
    frappe: {
        ui: {
            form: {
                on: function(doctype, events) {
                    handlers[doctype] = events;
                }
            }
        },
        datetime: {
            get_today: function() { return "2026-11-04"; },
            add_days: addDays,
            month_start: function() { return "2026-11-01"; },
            month_end: function() { return "2026-11-30"; }
        },
        db: {
            get_value: function(doctype, name, fieldname, callback) {
                assert.strictEqual(doctype, "Company");
                assert.strictEqual(name, "World Shading");
                assert.strictEqual(fieldname, "default_currency");
                callback({default_currency: "BHD"});
            },
            set_value: function() { databaseWrites += 1; }
        },
        msgprint: function(message) { messages.push(message); }
    }
};

const scriptPath = path.join(__dirname, "sales_target.js");
const source = fs.readFileSync(scriptPath, "utf8");
vm.runInNewContext(source, sandbox, {filename: scriptPath});

assert.ok(handlers["Sales Target"]);
assert.ok(handlers["Sales Target Detail"]);
for (const event of ["refresh", "company", "period_type"]) {
    assert.strictEqual(typeof handlers["Sales Target"][event], "function");
}
for (const event of ["target_amount", "targets_add", "targets_remove"]) {
    assert.strictEqual(typeof handlers["Sales Target Detail"][event], "function");
}

function makeForm(periodType) {
    const values = [];
    const queries = [];
    const doc = {
        company: "World Shading",
        currency: null,
        period_type: periodType,
        from_date: null,
        to_date: null,
        targets: [
            {sales_employee: "EMP-001", currency: null, target_amount: 10.125},
            {sales_employee: "EMP-002", currency: null, target_amount: "20.250"}
        ]
    };
    return {
        doc: doc,
        values: values,
        queries: queries,
        set_query: function(fieldname, childTable, callback) {
            queries.push({fieldname: fieldname, childTable: childTable, result: callback()});
        },
        set_value: function(fieldname, value) {
            doc[fieldname] = value;
            values.push([fieldname, value]);
        },
        refresh_field: function() {}
    };
}

const expectedDates = {
    Daily: ["2026-11-04", "2026-11-04"],
    Weekly: ["2026-11-04", "2026-11-10"],
    Monthly: ["2026-11-01", "2026-11-30"],
    Quarterly: ["2026-10-01", "2026-12-31"],
    Annual: ["2026-01-01", "2026-12-31"]
};

for (const periodType of Object.keys(expectedDates)) {
    const frm = makeForm(periodType);
    sandbox.set_period_defaults(frm);
    assert.deepStrictEqual(
        [frm.doc.from_date, frm.doc.to_date], expectedDates[periodType]);
}

const customForm = makeForm("Custom");
sandbox.set_period_defaults(customForm);
assert.strictEqual(customForm.doc.from_date, null);
assert.strictEqual(customForm.doc.to_date, null);

const preservedForm = makeForm("Daily");
preservedForm.doc.from_date = "2026-12-10";
preservedForm.doc.to_date = "2026-12-11";
sandbox.set_period_defaults(preservedForm);
assert.deepStrictEqual(
    [preservedForm.doc.from_date, preservedForm.doc.to_date],
    ["2026-12-10", "2026-12-11"]);

const frm = makeForm("Monthly");
sandbox.set_employee_query(frm);
assert.strictEqual(frm.queries[0].fieldname, "sales_employee");
assert.strictEqual(frm.queries[0].childTable, "targets");
assert.strictEqual(frm.queries[0].result.filters.status, "Active");
assert.strictEqual(frm.queries[0].result.filters.company, "World Shading");

sandbox.update_target_total(frm);
assert.strictEqual(frm.doc.total_target_amount, 30.375);

handlers["Sales Target"].company(frm);
assert.strictEqual(frm.doc.currency, "BHD");
assert.deepStrictEqual(frm.doc.targets.map(row => row.currency), ["BHD", "BHD"]);
assert.strictEqual(messages.length, 1);
assert.strictEqual(frm.doc.targets.length, 2);
assert.strictEqual(databaseWrites, 0);

console.log("sales_target client behavior: ok");
