# WooCommerce production refinements

Goal: correct customer identity and cutoff timezone handling, and simplify all six connector DocType layouts for ERPNext v12.

Design: use a store-scoped `woo:` customer key and adopt exact legacy links on demand, without merging ordinary ERP customers. Keep the existing UTC `order_since` as the internal value and add a site-timezone picker. Backfill that picker from the existing UTC value without changing the polling cursor or import scope. Save converts the picker back to UTC. This avoids guessing whether an existing operator entered local time or UTC; operators who selected local Now under the old label must reselect Now after upgrading. Use native sections/columns and concise operational descriptions; preserve field names, settings, permissions and sync behavior.

Constraints: Python 3.6 / ERPNext 12 / Frappe 12.16.3; no full migrate, no business-site test runner, no live access, no automatic activation, no new dependency (pytz is supplied by Frappe). UI only changes use normal metadata; no account or stock changes.

## Task 1: identity
- [x] Write failing tests for store separation, canonical URLs, legacy reuse and conflicting identities.
- [x] Add store-scoped identity with exact legacy compatibility in domain.py and orders.customer_for.
- [x] Run standalone tests.

## Task 2: cutoff
- [x] Write failing conversion, DST and repeat-upgrade tests.
- [x] Add timezone helpers, site-time picker, Settings validation and idempotent scoped upgrade.
- [x] Preserve existing UTC cutoff and poll cursor; do not auto-rewind imported history.
- [x] Verify polling and webhook use the same internal UTC value.

## Task 3: native forms and release
- [x] Reorganize all six JSON forms; keep child grids readable and technical sections collapsed.
- [x] Simplify Settings dashboard and repeated connection message; update guide and release instructions.
- [x] Verify metadata, Python 3.6 syntax, JS syntax, complete standalone suite and diff scope.
- [x] Independent code review, address material findings, commit and open release PR.

Review focus: legacy customers must not duplicate; stores must not share new identities; old UTC values must not shift on repeated setup/save; DST gaps/ambiguities must reject rather than silently shift; no existing saved credentials or sync switches change. Native form rendering still needs operator acceptance after reload in ERPNext v12.


Verification: baseline 168 standalone tests; final 185 tests pass. New identity/cutoff regression cases were run failing before implementation; further Settings-controller, upgrade-scope and UTC-boundary cases passed. All modified/new Python parsed with Python 3.6 grammar, three changed JS files pass Node syntax checks, metadata order/permissions/data-field preservation and 10-column Item grid verified. Independent reviewer found no Critical/Important issues. Runtime get_time_zone export, boot timezone and Now behavior checked against official Frappe v12.16.3 source. Live native rendering and signed API acceptance remain operator checks; no live access occurred. No whole-app version change, core code change or scheduling change.
