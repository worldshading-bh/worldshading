# WooCommerce Item linking popup

User-approved intent: choose the ERP Item and its existing selling UOM from the product mapping popup, automatically populate Woo identity, save the mapping and open the ERP Item. Save Link stays separate from stock/price sync.

Design: a same-origin authenticated ERPNext Desk popup, launched from the Woo manager toolbar or a variation row. The popup fetches Woo identities from the configured store through the existing server credentials and uses ordinary ERP session/CSRF protection. No ERP credentials in WordPress, no guest endpoints, no CORS changes or cross-origin write bridge. ERP System Manager and Item write permissions stay required. New links are disabled (stock selected, price off) until reviewed and enabled in ERP. Existing enabled links can be reopened or saved unchanged, but cannot be reassigned or edited through this convenience form. Existing inactive links can change UOM with optimistic Item timestamp validation.

Tasks:
- [x] Add failing no-site API tests: permission gates, authoritative Woo identity, permitted Items/UOMs, disabled new links, duplicate/stale/conflicting saves and enabled-link protection.
- [x] Implement linking endpoints in a dedicated module using existing settings, Item normalization, save validation and target lock.
- [x] Add native ERP Page with variation selection, searchable Item, UOM choice, clear linked/inactive state and Open Item. No save on load; reject async stale responses.
- [x] Add a page-only upgrade command; update initial setup. No migration or business-site tests.
- [x] Prepare Woo helper 1.13.7 with popup launcher and per-row Link Item. Preserve copy/ID page fallback and manager gates.
- [x] Standalone suites, PHP/JS/Python3.6 checks, independent review, release PR and concrete deployment instructions. Do not deploy broken Woo launch links before the ERP page is installed. No live ERP SSH access is available or requested.

Review focus: no API writes to Woo; fresh links inactive; no browser-supplied SKU trusted; duplicate target/Item concurrency; no permission bypass; popup must use real ERP login and CSRF; browser success must not imply ERP deployment or a real mapping save until the user installs the release.

Verification: 204 no-site Python tests passed; Node UI regressions and syntax passed; PHP normal/bad-origin fixtures and both helper/entry syntax checks passed; changed Python modules parse with Python 3.6 grammar. Independent review findings were fixed and re-reviewed. Production activation and live save remain pending the documented ERP update and paired Woo helper installation.
