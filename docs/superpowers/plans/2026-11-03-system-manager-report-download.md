# System Manager Report Download Visibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Hide the prepared query-report Download Report button globally from users without the System Manager role.

**Architecture:** Register one focused Desk script through the custom app's existing `app_include_js`. Wrap the ERPNext v12 query-report prepared-button method once, preserve its standard behavior, and remove only the Download Report button for non-System-Managers.

**Tech Stack:** ERPNext/Frappe v12 Desk JavaScript, ES5-compatible custom-app script, Node VM assertion harness.

**Spec:** `docs/superpowers/specs/2026-11-03-system-manager-report-download-design.md`

## Global Constraints

- Do not modify ERPNext core.
- Do not add polling, permanent DOM observers, API calls, or database work.
- System Managers retain the standard button; all other Desk users lose only that button.
- No migration, restart, cache clear, database update, or push.

## Review Focus

- A user whose roles include System Manager keeps the unmodified standard behavior.
- A user without System Manager has the button removed after every prepared-button render.
- Re-evaluating the script does not wrap the method more than once.
- The standard prepared-button method still receives its original instance and arguments.
- Missing query-report globals fail safely without breaking Desk startup.

---

### Task 1: Global role-based prepared-report download visibility

**Files:**
- Create: `worldshading/public/js/report_download_visibility.js`
- Create: `worldshading/public/js/test_report_download_visibility.js`
- Modify: `worldshading/hooks.py`

**Interfaces:**
- Consumes: `frappe.user.has_role("System Manager")`, `frappe.views.QueryReport.prototype.add_prepared_report_buttons`, and `page.remove_inner_button(label)`.
- Produces: the unchanged standard method for System Managers and a once-wrapped method that removes `__("Download Report")` for other users.

- [x] Write a Node VM test proving System Managers retain the button, regular users remove it after standard rendering, arguments/instance are preserved, repeated loading is idempotent, and missing globals are safe.
- [x] Run `node worldshading/public/js/test_report_download_visibility.js` and confirm RED because the script does not exist.
- [x] Add the minimal guarded wrapper in `report_download_visibility.js` and register it in `app_include_js`.
- [x] Run the Node test and both JavaScript syntax checks; confirm PASS.
- [x] Run `git diff --check` and review the scoped diff for ERPNext v12 compatibility and unrelated-file preservation.
- [x] Commit only the script, test, hook entry, design, and plan files.
