const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

const source_path = __dirname + "/report_download_visibility.js";

function make_context(is_system_manager) {
	const state = {
		original_calls: [],
		removed_labels: []
	};

	function QueryReport() {}
	QueryReport.prototype.add_prepared_report_buttons = function () {
		state.original_calls.push({
			instance: this,
			arguments: Array.prototype.slice.call(arguments)
		});
		return "standard-result";
	};

	const context = {
		console: console,
		__: function (value) { return value; },
		frappe: {
			user: {
				has_role: function (role) {
					return role === "System Manager" && is_system_manager;
				}
			},
			views: {QueryReport: QueryReport}
		}
	};
	vm.createContext(context);
	return {context: context, state: state, QueryReport: QueryReport};
}

function load_script(context) {
	vm.runInContext(fs.readFileSync(source_path, "utf8"), context, {
		filename: "report_download_visibility.js"
	});
}

const manager = make_context(true);
const manager_original = manager.QueryReport.prototype.add_prepared_report_buttons;
load_script(manager.context);
assert.strictEqual(
	manager.QueryReport.prototype.add_prepared_report_buttons,
	manager_original,
	"System Managers must retain the standard prepared-report method"
);
const manager_report = {
	page: {
		remove_inner_button: function (label) {
			manager.state.removed_labels.push(label);
		}
	}
};
assert.strictEqual(
	manager.QueryReport.prototype.add_prepared_report_buttons.call(manager_report, {name: "PREP-1"}),
	"standard-result"
);
assert.deepStrictEqual(manager.state.removed_labels, []);

const regular = make_context(false);
load_script(regular.context);
load_script(regular.context);
const regular_report = {
	page: {
		remove_inner_button: function (label) {
			regular.state.removed_labels.push(label);
		}
	}
};
const prepared_doc = {name: "PREP-2"};
assert.strictEqual(
	regular.QueryReport.prototype.add_prepared_report_buttons.call(
		regular_report, prepared_doc, "extra-argument"
	),
	"standard-result",
	"the wrapper must preserve the standard method return value"
);
assert.strictEqual(regular.state.original_calls.length, 1, "the method must be wrapped only once");
assert.strictEqual(regular.state.original_calls[0].instance, regular_report);
assert.deepStrictEqual(
	regular.state.original_calls[0].arguments,
	[prepared_doc, "extra-argument"],
	"the wrapper must preserve all standard method arguments"
);
assert.deepStrictEqual(
	regular.state.removed_labels,
	["Download Report"],
	"regular users must lose only the Download Report button after standard rendering"
);

const missing_globals = {console: console};
vm.createContext(missing_globals);
assert.doesNotThrow(function () {
	load_script(missing_globals);
}, "Desk startup must remain safe if query-report globals are unavailable");

console.log("report download visibility tests passed");
