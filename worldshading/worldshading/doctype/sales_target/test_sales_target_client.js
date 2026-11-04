const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const handlers = {};
const messages = [];
let databaseWrites = 0;

const sandbox = {
    console: console,
    flt: function(value) { return Number(value || 0); },
    __: function(value) { return value; },
    frappe: {
        ui: {form: {on: function(doctype, events) { handlers[doctype] = events; }}},
        db: {
            get_value: function(doctype, name, fieldname, callback) {
                assert.strictEqual(doctype, "Company");
                assert.ok(name);
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
for (const event of ["refresh", "company"]) {
    assert.strictEqual(typeof handlers["Sales Target"][event], "function");
}
assert.strictEqual(handlers["Sales Target"].period_type, undefined);
for (const event of [
    "daily_target", "weekly_target", "monthly_target",
    "quarterly_target", "annual_target", "targets_add", "targets_remove"
]) {
    assert.strictEqual(typeof handlers["Sales Target Detail"][event], "function");
}
assert.strictEqual(handlers["Sales Target Detail"].target_amount, undefined);
assert.strictEqual(source.includes("set_period_defaults"), false);
assert.strictEqual(source.includes("pad_date_part"), false);

function makeForm(targets) {
    const values = [];
    const queries = [];
    const doc = {
        company: "World Shading",
        currency: null,
        from_date: "2026-01-01",
        to_date: "2026-12-31",
        targets: targets || [
            {
                sales_employee: "EMP-001", currency: null,
                daily_target: 1.2345, weekly_target: 10,
                monthly_target: "100.125", quarterly_target: 1000,
                annual_target: 10000
            },
            {
                sales_employee: "EMP-002", currency: null,
                daily_target: 2.3456, weekly_target: null,
                monthly_target: "", quarterly_target: 2000,
                annual_target: 20000
            }
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

const frm = makeForm();
handlers["Sales Target"].refresh(frm);
assert.strictEqual(frm.queries[0].fieldname, "sales_employee");
assert.strictEqual(frm.queries[0].childTable, "targets");
assert.strictEqual(frm.queries[0].result.filters.status, "Active");
assert.strictEqual(frm.queries[0].result.filters.company, "World Shading");
assert.strictEqual(frm.doc.total_daily_target, 3.58);
assert.strictEqual(frm.doc.total_weekly_target, 10);
assert.strictEqual(frm.doc.total_monthly_target, 100.125);
assert.strictEqual(frm.doc.total_quarterly_target, 3000);
assert.strictEqual(frm.doc.total_annual_target, 30000);

const totalFields = [
    "total_daily_target", "total_weekly_target", "total_monthly_target",
    "total_quarterly_target", "total_annual_target"
];
for (const event of [
    "daily_target", "weekly_target", "monthly_target",
    "quarterly_target", "annual_target", "targets_add", "targets_remove"
]) {
    frm.values.length = 0;
    handlers["Sales Target Detail"][event](frm);
    assert.deepStrictEqual(frm.values.map(function(value) { return value[0]; }), totalFields);
}

const openingForm = makeForm([{sales_employee: null, currency: null}]);
handlers["Sales Target"].company(openingForm);
assert.strictEqual(messages.length, 0);

const originalDates = [frm.doc.from_date, frm.doc.to_date];
handlers["Sales Target"].company(frm);
assert.strictEqual(messages.length, 0);
frm.doc.company = "Another Company";
handlers["Sales Target"].company(frm);
assert.strictEqual(frm.doc.currency, "BHD");
assert.deepStrictEqual(frm.doc.targets.map(row => row.currency), ["BHD", "BHD"]);
assert.deepStrictEqual([frm.doc.from_date, frm.doc.to_date], originalDates);
assert.strictEqual(messages.length, 1);
assert.strictEqual(frm.doc.targets.length, 2);
assert.strictEqual(databaseWrites, 0);

console.log("sales_target recurring client behavior: ok");
