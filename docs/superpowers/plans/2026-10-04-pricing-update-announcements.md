# Pricing Update Announcements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Announce actual pricing changes in a compact public popup that repeats when staff open Desk for three calendar days from the update date.

**Architecture:** Reuse the existing Frappe Note popup mechanism. Create one new Note per successful report update operation, containing all changed items or rules, within the same database transaction as the pricing changes. Keep the existing production-item announcement intact.

**Tech Stack:** ERPNext/Frappe v12, Python 3.6, existing direct unittest harness; no new DocType or frontend library.

**Spec:** In-chat design on 4 October 2026: reuse public Notes, repeat on login, expire three days from the update date. The user requested investigation and a plan only.

## Scope Decision

The user approved implementation of this plan. Both Pricing Strategy Analysis update buttons are covered, consistent with the preceding conversation. Manual edits and imports are outside this implementation; no global Item Price hook is added.

If global coverage is requested, revise the integration task first: capture actual old/new rate changes in Item Price document events, define import batching and workflow activation behavior, and prevent duplicate announcements from report updates. A per-document hook alone would create up to 100 popups for one report batch, so it is not an equivalent implementation.

## Existing Implementation Verified

- Enabled database Server Script: `Auto Note Creation - Notify users about the new item`.
- Configured event: Item Price / Before Save (its inline comment incorrectly says After Save).
- It requires `workflow_state == "Active"` and Item `is_production_item`, skips its recognized Data Import path, and creates a Note only if that item's fixed title does not already exist.
- It sets `public`, `notify_on_login`, and `notify_on_every_login` to 1, and expiry to `add_days(nowdate(), 3)`.
- Existing Notes confirm that this mechanism has been used for production items.
- Its permanent per-item deduplication cannot announce subsequent price revisions. Do not reuse that title or reset existing Notes.
- Core `frappe/boot.py:get_unseen_notes` loads unexpired Notes; `frappe/public/js/frappe/desk.js:show_notes` displays them when Desk loads. This is not a realtime broadcast to already-open sessions.
- An active Item Price Approval workflow exists. Saved prices can be pending, Active, or Inactive. Never describe a pending saved price as approved for use.

## Global Constraints

- Planning only in this turn; no runtime edits or database writes.
- Keep implementation in the worldshading app, compatible with ERPNext/Frappe v12 and Python 3.6.
- Preserve normal save/insert permissions, existing workflow, report previews, concurrency checks, group completeness, and the 50-item limit.
- Do not modify the existing Server Script or Frappe core. A custom-app guard for generated pricing Notes is required by the verified native dismissal bug described in the implementation record.
- No migration, restart, production cache clearing, or bench test.
- No `ignore_permissions` in the new helper. The existing script uses it, but that behavior is not carried into the new feature.
- Public means all Desk users receiving these Notes. Include selling prices and rule information only; omit costs, margins, expense calculations, and customer-specific pricing.
- Preserve unrelated worktree changes.

## Popup Contract

- One Note per confirmed operation, only if at least one record was created or its pricing configuration actually changed.
- Item Price content: Item Code/Name, Price List, UOM, currency, previous net price, new net price, and saved workflow state. Group Regular/B2B entries by item for readability.
- New records use `Not previously set` for the old price. Pending or inactive records are visibly identified; the popup must not instruct staff to use them immediately.
- Pricing Rule content: changed rule names, affected items, quantity ranges, final discount percentages, and enabled/disabled status. Use actual saved specifications, not stale preview counts.
- Include update date/time and updater. A Prepared Report reference can be shown, but access remains subject to existing permissions; do not expose a public report snapshot.
- Use an escaped HTML table in the existing popup with a bounded scrollable content area for large batches. Include all actual changes, not a separate popup per row.
- Use a unique Note title, such as `Prices Updated - <date/time> - <operation suffix>`; rule operations use `Pricing Rules Updated`.
- Set `public=1`, `notify_on_login=1`, `notify_on_every_login=1`, and `expire_notification_on=add_days(nowdate(), 3)` using site time.
- Calendar-day interpretation follows the existing script: an update on 4 October expires at the start of 7 October, covering 4, 5 and 6 October. This is not an exact 72-hour timer.
- Every new operation gets its own expiry. Older announcements retain theirs and may coexist during the three-day window.
- No announcement for preview, all-unchanged results, validation failure, or rolled-back changes.

## Review Focus

- A bulk operation must produce one announcement with all changed records, including multiple price lists.
- Subsequent updates must be announced even when the item was announced previously; identical no-op retries must not generate another Note.
- A failing Note insert must not leave committed price changes without their announcement; preserve transaction atomicity and do not commit inside helpers.
- Public content must escape item names and omit commercial cost/margin details.
- Pending workflow states and expiry boundaries must be represented accurately.

## Task 1: Build and Test the Note Helper

**Files:**
- Create: `worldshading/api/pricing_update_notifications.py`
- Create: `worldshading/api/test/test_pricing_update_notifications.py`

**Interface:** `create_pricing_update_note(update_kind, prepared_report_name, changes)` returns the inserted Note name, or `None` for empty changes. `update_kind` is `item_price` or `pricing_rule`. Changes are server-built dictionaries from actual saved records, never arbitrary client HTML. Item-price entries carry item identity, price list, UOM, currency, old/new rate and workflow state. Rule entries carry saved rule name, item codes, quantity bounds, discount and disabled status.

- [ ] Add failing tests for empty changes, one Note for multiple items/price lists, unique titles for successive operations, three-day expiry, notification flags, escaped HTML, omitted costs, and visible pending/inactive status.
- [ ] Run from `apps/worldshading`: `../../env/bin/python -B -m unittest worldshading.api.test.test_pricing_update_notifications`. Confirm failures correspond to the missing helper.
- [ ] Implement the helper with normal `frappe.new_doc("Note")` and `insert()`, site-date utilities, existing escaping conventions and no explicit commit. Let permission/insert failures propagate for transaction rollback.
- [ ] Run the same focused tests; require all to pass.

## Task 2: Integrate the Report Update Operations

**Files:**
- Modify: `worldshading/worldshading/report/pricing_strategy_analysis/pricing_strategy_analysis.py`
- Test: `worldshading/worldshading/report/pricing_strategy_analysis/test_pricing_strategy_analysis.py`

**Interfaces:** Existing `execute_item_price_update(preview_token=None, selected_rows=None)` and `execute_bulk_pricing_rule_update(preview_token=None, tier_discounts=None)` call the Task 1 helper once per operation. Existing response fields remain compatible; add `notification_note` for traceability.

- [ ] Add failing integration tests for mixed created/updated/unchanged batches, all-unchanged batches, rule discount edits, partial-save failure, Note permission/insert failure, and existing workflow state preservation.
- [ ] Run the direct report unittest module and confirm new assertions fail for missing integration.
- [ ] Preflight Note create permission when actual changes will be saved. Accumulate only successfully changed records, using actual post-save values and states.
- [ ] Call the helper after all pricing saves and audit comments, before deleting the preview token. Do not add commits, swallow insert errors, or change workflow state. If Note creation fails, the request must fail and the framework transaction must roll back both Notes and price changes.
- [ ] Test that the preview token is not consumed on notification failure, successful no-op retries generate no Note, and existing production-item automation remains unmodified. Its separate new-item announcement may coexist when a new production item first qualifies.
- [ ] Run `../../env/bin/python -B -m unittest worldshading.api.test.test_pricing_update_notifications worldshading.worldshading.report.pricing_strategy_analysis.test_pricing_strategy_analysis`; require all focused tests to pass. Mocks prove call ordering/error propagation; verify real rollback separately on a disposable test site.

## Task 3: Document and Verify

**File:** Update `worldshading/Documentation/pricing_strategy_analysis.md`.

- [ ] Document notification scope, public audience, old/new net prices, workflow labels, repeat display, expiry boundary, and coexistence of multiple announcements.
- [ ] Run `node worldshading/worldshading/report/pricing_strategy_analysis/test_pricing_strategy_analysis_client.js` and scoped `git diff --check`; require passing results without production database changes.
- [ ] On a disposable test site, change two items with both price lists and confirm one Note, complete rows, correct old/new values, and no cost disclosure. Repeat with one rule operation.
- [ ] Log in as another Desk user, close/reopen Desk, and verify repeat display before expiry and absence at the expiry boundary. Confirm there is no immediate broadcast to an already-open session.
- [ ] Verify an unchanged operation creates no Note, later changes create a fresh Note, pending prices are labelled pending, and a forced Note failure rolls back the pricing operation. Do not perform artificial price changes in production.

## Risk and Rollback

Implementation risk is low to medium: pricing calculations remain unchanged, but automatic Note creation adds a permission/validation dependency to a production write transaction. Confirm intended pricing operators can create Notes before deployment. Native public Notes are visible across companies; this follows the requested public-popup behavior.

Rollback removes only the helper and its report calls, preserving unrelated work. Disable the notification flags on the exact generated Notes if early withdrawal is needed, under explicit production-write authorization. Do not reverse Item Prices, Pricing Rules, workflow states, or delete existing production-item announcements as part of notification rollback.

## Implementation Record

- User authorized implementation with `ok do it`; restart, migrate and bench tests remain prohibited.
- Ruling: modify the existing checkout in place because it contains the approved, uncommitted pricing implementation. Preserve all existing work; do not reconstruct it from HEAD in a clean worktree.
- Ruling: cover only the two report buttons as presented in the approved plan. Broader manual/import coverage needs a separate design.
- Task 1 complete: Note helper and direct mocked unit tests, including three-day expiry, public/repeat flags, safe content, unique titles and insert failures.
- Task 2 complete: both execution methods collect saved changes, check Note permission before pricing writes, create a single Note before consuming the preview token, and return its name. Focused tests cover unchanged operations and failure propagation.
- Task 3 complete: operational guide updated. Direct Python and client checks are recorded in the completion message; no production database write tests will be run.
- Review found a native Frappe v12 defect: `show_notes` reopens repeat-login Notes immediately on dismissal. A Node VM test against the installed native method reproduced it before the fix.
- Ruling: add `public/js/pricing_update_notifications.js` and one `app_include_js` entry in `hooks.py`. The wrapper filters only generated pricing Notes already displayed in this Desk load and restores the original boot list; native callbacks never persist Seen By for them. This is necessary for the approved clean dismissal behavior and avoids core changes. Tests cover multiple announcements sharing a dialog, subsequent Desk loads, and unchanged behavior for other Notes.
- Verification: 120 direct Python unit tests passed; report client checks and native Desk popup regression checks passed. No production prices or Notes were created for testing. Real browser rendering and activation remain unverified.
- Remaining manual verification: real database rollback and browser repeat/expiry behavior on a disposable test site. These were not exercised on production.
- Live worker activation is not verified by unit tests. No restart, cache clearing, migration or bench test is part of this implementation.

## Approved UI Revision

The user subsequently requested a simpler Item Price popup, superseding the
original item-price content contract above. Keep report-only scope and three-day
expiry. Show Item, Item Name, UOM and New Price only, with price lists as section
headings. Remove currency, previous price, approval status and the preamble from
the Item Price content. Display short popup titles without changing the unique
stored Note title. Use a fixed-width table with natural item-name wrapping and
nonwrapping prices, relying on the native dialog's vertical scrolling.

The pictured existing announcement was not found by exact title, title prefix or
creation date in the connected site's Notes; no existing Note was modified.

### Side-by-side prices, 5 October

User approved combining Regular and B2B columns into one row per item/UOM.
Only changed price lists appear as columns, with Regular first; missing changes
within a displayed column say `Not changed`. Price-list role is passed from the
report entry for ordering even when the list has a custom name. Generated Item
Price dialogs use a 760px desktop width capped at the viewport minus 24px, with
table scrolling on narrow screens. Other messages retain their original width.
Existing stored Notes are not rewritten. Report-only scope and expiry stay intact.
