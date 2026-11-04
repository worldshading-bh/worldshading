const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const routes = [];
const formatCalls = [];
const createdMarkup = [];
const styleRules = [];
const observerInstances = [];
let summaryContainer = null;

function FakeObserver(callback) {
    this.callback = callback;
    this.disconnected = false;
    this.observed = null;
    observerInstances.push(this);
}
FakeObserver.prototype.observe = function(target, options) {
    this.observed = {target: target, options: options};
};
FakeObserver.prototype.disconnect = function() {
    this.disconnected = true;
};

function FakeRow(index, specialClass, inFooter) {
    this.index = index;
    this.classes = {};
    this.inFooter = Boolean(inFooter);
    if (specialClass) {
        this.classes[specialClass] = true;
    }
}
FakeRow.prototype.attr = function(name) {
    return name === "data-row-index" ? this.index : undefined;
};
FakeRow.prototype.hasClass = function(name) {
    return Boolean(this.classes[name]);
};
FakeRow.prototype.addClass = function(name) {
    this.classes[name] = true;
    return this;
};
FakeRow.prototype.removeClass = function(names) {
    const row = this;
    names.split(/\s+/).forEach(function(name) { delete row.classes[name]; });
    return this;
};
FakeRow.prototype.closest = function(selector) {
    return {length: selector === ".dt-footer" && this.inFooter ? 1 : 0};
};

function FakeCollection(rows) {
    this.rows = rows;
}
FakeCollection.prototype.each = function(callback) {
    this.rows.forEach(function(row) { callback.call(row); });
    return this;
};

function FakeWrapper(rows) {
    this.rows = rows;
    this.classes = {};
}
FakeWrapper.prototype.addClass = function(name) {
    this.classes[name] = true;
    return this;
};
FakeWrapper.prototype.find = function(selector) {
    if (selector === ".dt-row[data-row-index]") {
        return new FakeCollection(this.rows);
    }
    return new FakeCollection([]);
};

const sandbox = {
    console: console,
    __: function(value) { return value; },
    encodeURIComponent: encodeURIComponent,
    decodeURIComponent: decodeURIComponent,
    window: {
        MutationObserver: FakeObserver,
        requestAnimationFrame: function(callback) {
            callback();
            return 1;
        }
    },
    $: function(value) {
        if (typeof value !== "string") {
            return value;
        }
        if (value.indexOf("<style") === 0) {
            return {
                appendTo: function() { return this; },
                text: function(rules) {
                    styleRules.push(rules);
                    return this;
                }
            };
        }
        createdMarkup.push(value);
        summaryContainer = {
            items: [],
            visible: false,
            insertedBefore: null,
            insertBefore: function(target) {
                this.insertedBefore = target;
                return this;
            },
            empty: function() {
                this.items = [];
                return this;
            },
            append: function(html) {
                this.items.push(html);
                return this;
            },
            toggle: function(value) {
                this.visible = Boolean(value);
                return this;
            }
        };
        return summaryContainer;
    },
    frappe: {
        query_reports: {},
        datetime: {get_today: function() { return "2026-11-04"; }},
        set_route: function() { routes.push(Array.prototype.slice.call(arguments)); },
        format: function(value, field, options, doc) {
            formatCalls.push({field: field, options: options, doc: doc});
            let formatted = String(value);
            if (field.fieldtype === "Currency") {
                formatted += " " + doc[field.options];
            } else if (field.fieldtype === "Percent") {
                formatted += "%";
            }
            return options && options.only_value ? formatted :
                "<div style='text-align: right'>" + formatted + "</div>";
        }
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
assert.ok(!filters.frequency.reqd);
assert.deepStrictEqual(
    filters.frequency.options.split("\n"),
    ["", "Daily", "Weekly", "Monthly", "Quarterly", "Annual"]);
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

const achievementGreen = config.formatter(
    100, null, {fieldname: "achievement_percent"},
    {achievement_percent: 100}, defaultFormatter);
const achievementRed = config.formatter(
    99.99, null, {fieldname: "achievement_percent"},
    {achievement_percent: 99.99}, defaultFormatter);
const achievementZero = config.formatter(
    0, null, {fieldname: "achievement_percent"},
    {achievement_percent: 0}, defaultFormatter);
assert.ok(achievementGreen.indexOf('class="indicator green"') !== -1);
assert.ok(achievementRed.indexOf('class="indicator red"') !== -1);
assert.ok(achievementZero.indexOf('class="indicator red"') !== -1);

function v12BlockPercentFormatter(value) {
    return "<div style='text-align: right'>" + value + "%</div>";
}
const v12Achievement = config.formatter(
    100, null, {fieldname: "achievement_percent"},
    {achievement_percent: 100}, v12BlockPercentFormatter);
assert.ok(v12Achievement.indexOf('style="text-align: right;"') !== -1);
assert.ok(v12Achievement.indexOf('class="indicator green"') !== -1);
assert.ok(v12Achievement.indexOf("100%") !== -1);
assert.ok(v12Achievement.indexOf("<span class=\"indicator green\"><div") === -1);

formatCalls.length = 0;

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
    raw_data: null,
    refresh_count: 0,
    refresh: function() {
        this.refresh_count += 1;
        return "refreshed";
    },
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
assert.ok(summaryContainer);
assert.strictEqual(summaryContainer.insertedBefore, report.$report);
assert.strictEqual(typeof config.after_datatable_render, "function");
assert.ok(createdMarkup[0].indexOf('class="sales-target-team-summary"') !== -1);
assert.ok(createdMarkup[0].indexOf('display:grid') !== -1);
assert.ok(createdMarkup[0].indexOf('sales-target-team-summary row') === -1);

report.raw_data = {
    report_summary: [
        {label: "Daily Achievement %", value: 100, datatype: "Percent", indicator: "green"},
        {label: "Weekly Achievement %", value: 52.5, datatype: "Percent", indicator: "red"}
    ]
};
config.after_datatable_render();
assert.strictEqual(summaryContainer.visible, true);
assert.strictEqual(summaryContainer.items.length, 2);
assert.ok(summaryContainer.items[0].indexOf("Daily Achievement %") !== -1);
assert.ok(summaryContainer.items[0].indexOf("100%") !== -1);
assert.ok(summaryContainer.items[0].indexOf("sales-target-summary-card") !== -1);
assert.ok(summaryContainer.items[0].indexOf("col-sm-") === -1);
assert.ok(summaryContainer.items[0].indexOf("indicator green") !== -1);
assert.ok(summaryContainer.items[1].indexOf("indicator red") !== -1);
assert.ok(summaryContainer.items[0].indexOf("&lt;div") === -1);
assert.strictEqual(formatCalls.length, 2);
assert.strictEqual(formatCalls[0].field.options, "currency");
assert.strictEqual(formatCalls[0].options.only_value, true);
assert.strictEqual(formatCalls[0].doc.currency, undefined);

const resultRows = [
    new FakeRow("0"),
    new FakeRow("1"),
    new FakeRow("2"),
    new FakeRow("3"),
    new FakeRow("0", "dt-row-header"),
    new FakeRow("1", "dt-row-filter"),
    new FakeRow("2", null, true),
    new FakeRow("invalid")
];
const datatable = {
    wrapper: new FakeWrapper(resultRows),
    bodyScrollable: {}
};
sandbox.frappe.query_report = {
    data: [
        {achievement_percent: 100},
        {achievement_percent: 99.99},
        {achievement_percent: 0},
        {achievement_percent: -5}
    ]
};
config.after_datatable_render(datatable);
assert.strictEqual(resultRows[0].hasClass("sales-target-achieved-row"), true);
assert.strictEqual(resultRows[0].hasClass("sales-target-below-row"), false);
assert.strictEqual(resultRows[1].hasClass("sales-target-below-row"), true);
assert.strictEqual(resultRows[2].hasClass("sales-target-below-row"), true);
assert.strictEqual(resultRows[3].hasClass("sales-target-below-row"), true);
assert.strictEqual(resultRows[4].hasClass("sales-target-achieved-row"), false);
assert.strictEqual(resultRows[5].hasClass("sales-target-below-row"), false);
assert.strictEqual(resultRows[6].hasClass("sales-target-below-row"), false);
assert.strictEqual(resultRows[7].hasClass("sales-target-below-row"), false);
assert.ok(styleRules[0].indexOf(
    ".sales-target-achieved-row " +
    ".dt-cell:not(.dt-cell--highlight):not(.dt-cell--dragging)"
) !== -1);
assert.ok(styleRules[0].indexOf(
    ".sales-target-below-row " +
    ".dt-cell:not(.dt-cell--highlight):not(.dt-cell--dragging)"
) !== -1);

resultRows[0].removeClass("sales-target-achieved-row");
observerInstances[0].callback();
assert.strictEqual(resultRows[0].hasClass("sales-target-achieved-row"), true);

const firstObserver = observerInstances[0];
config.after_datatable_render(datatable);
assert.strictEqual(firstObserver.disconnected, true);
assert.strictEqual(observerInstances.length, 2);

assert.strictEqual(report.refresh(), "refreshed");
assert.strictEqual(report.refresh_count, 1);
assert.strictEqual(summaryContainer.visible, false);
assert.strictEqual(summaryContainer.items.length, 0);

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
