const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const routes = [];
const sandbox = {
    console: console,
    __: function(value) { return value; },
    encodeURIComponent: encodeURIComponent,
    decodeURIComponent: decodeURIComponent,
    $: function(value) { return value; },
    frappe: {
        query_reports: {},
        datetime: {get_today: function() { return "2026-11-04"; }},
        set_route: function() { routes.push(Array.prototype.slice.call(arguments)); }
    }
};

const scriptPath = path.join(__dirname, "sales_target_performance.js");
const source = fs.readFileSync(scriptPath, "utf8");
vm.runInNewContext(source, sandbox, {filename: scriptPath});

const config = sandbox.frappe.query_reports["Sales Target Performance"];
assert.ok(config);

const filters = {};
for (const filter of config.filters) {
    filters[filter.fieldname] = filter;
}
assert.strictEqual(filters.sales_target.fieldtype, "Link");
assert.strictEqual(filters.sales_target.options, "Sales Target");
assert.strictEqual(filters.sales_target.reqd, 1);
assert.strictEqual(filters.sales_target.get_query().filters.docstatus, 1);
assert.strictEqual(
    filters.sales_target.get_query().filters.target_model, "Recurring Plan");
assert.strictEqual(filters.frequency.fieldtype, "Select");
assert.strictEqual(filters.frequency.reqd, 1);
assert.deepStrictEqual(
    filters.frequency.options.split("\n"),
    ["Daily", "Weekly", "Monthly", "Quarterly", "Annual"]);
assert.strictEqual(filters.sales_employee.fieldtype, "Link");
assert.strictEqual(filters.sales_employee.options, "Employee");
assert.ok(!filters.sales_employee.reqd);
assert.strictEqual(filters.as_of_date.default, "2026-11-04");

function defaultFormatter(value) { return String(value); }
const statuses = ["Not Started", "Behind", "On Track", "Achieved", "Not Achieved"];
const renderedStatuses = statuses.map(function(status) {
    return config.formatter(
        status, null, {fieldname: "status"}, {status: status}, defaultFormatter);
});
for (let index = 0; index < statuses.length; index += 1) {
    assert.ok(renderedStatuses[index].indexOf(statuses[index]) !== -1);
    assert.ok(renderedStatuses[index].indexOf('class="indicator ') !== -1);
    assert.ok(renderedStatuses[index].indexOf("indicator-pill") === -1);
}

const maliciousEmployee = 'EMP-" onclick="danger()';
const row = {
    invoice_count: 3,
    company: "World Shading",
    sales_employee: maliciousEmployee,
    from_date: "2026-11-01",
    effective_to_date: "2026-11-04"
};
const invoiceLink = config.formatter(
    3, null, {fieldname: "invoice_count"}, row, defaultFormatter);
assert.ok(invoiceLink.indexOf("sales-target-invoice-link") !== -1);
assert.ok(invoiceLink.indexOf(maliciousEmployee) === -1);
assert.ok(invoiceLink.indexOf("onclick=") === -1);
assert.strictEqual(
    config.formatter(0, null, {fieldname: "invoice_count"},
        Object.assign({}, row, {invoice_count: 0}), defaultFormatter),
    "0");

const employeeLink = config.formatter(
    "EMP-A", null, {fieldname: "sales_employee"},
    Object.assign({}, row, {sales_employee: "EMP-A"}), defaultFormatter);
assert.ok(employeeLink.indexOf("sales-target-invoice-link") !== -1);
assert.ok(employeeLink.indexOf("EMP-A") !== -1);
assert.ok(employeeLink.indexOf("onclick=") === -1);

let delegatedEvent = null;
let delegatedSelector = null;
let delegatedHandler = null;
const report = {
    $report: {
        off: function() { return this; },
        on: function(event, selector, handler) {
            delegatedEvent = event;
            delegatedSelector = selector;
            delegatedHandler = handler;
            return this;
        }
    }
};
config.onload(report);
assert.strictEqual(delegatedEvent, "click.sales_target_performance");
assert.strictEqual(delegatedSelector, ".sales-target-invoice-link");
assert.strictEqual(typeof delegatedHandler, "function");

const attributes = {
    "data-company": encodeURIComponent(row.company),
    "data-employee": encodeURIComponent(row.sales_employee),
    "data-from-date": encodeURIComponent(row.from_date),
    "data-to-date": encodeURIComponent(row.effective_to_date)
};
const link = {attr: function(name) { return attributes[name]; }};
let prevented = false;
delegatedHandler.call(link, {preventDefault: function() { prevented = true; }});
assert.strictEqual(prevented, true);
assert.strictEqual(routes.length, 1);
assert.strictEqual(routes[0][0], "List");
assert.strictEqual(routes[0][1], "Sales Invoice");
assert.strictEqual(routes[0][2].company, "World Shading");
assert.strictEqual(routes[0][2].pb_sales_employee, maliciousEmployee);
assert.strictEqual(routes[0][2].docstatus, 1);
assert.strictEqual(routes[0][2].posting_date[0], "between");
assert.strictEqual(routes[0][2].posting_date[1][0], "2026-11-01");
assert.strictEqual(routes[0][2].posting_date[1][1], "2026-11-04");

console.log("sales_target_performance recurring client behavior: ok");
