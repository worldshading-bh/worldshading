# Connector feature release plan

Base: worldshading-bh/worldshading main acf8ba81fe634988a6b301dd08afc1536f1c55ba.
Branch: feature/woocommerce-connector. Source feature: reviewed demo overlay commit beb6002.

User scope: prepare a connector-only release; no live ERP access or deployment. Do not import dirty demo app files, records, credentials, sample price/tax configuration, mappings, history, unrelated fixes or demo server scripts. Do not run bench migrate or business-site tests.

Design: copy six active connector DocTypes, feature modules, guide and Item JS; retain existing production hooks and Item script. Configure exact ERP/store HTTPS origins through site_config keys ws_woocommerce_erp_url and ws_woocommerce_store_url. Both values are required outside the existing default demo pair. This is an explicit destination allowlist; credentials remain native Password fields. Disabled/manual settings remain the defaults. A connector-only setup preflight and idempotent setup perform scoped metadata/custom-field changes, including necessary database schema updates, with no full migrate. Include an optional connector-only five-minute recovery timer; preserve global scheduling.

- [x] Clone clean main and create separate local feature branch; port allowlisted files; establish 155-test baseline.
- [x] Test first: explicit origin pair, rejected partial/mismatched/unsafe targets, actual transport target, hook coexistence, no-legacy-table setup, absent-schema Item guard.
- [x] Implement production configuration, additive hooks, scoped setup and neutral operator documentation.
- [x] Run standalone no-site suite, Python3.6 syntax checks, frontend syntax/template checks and credential/file-scope review.
- [x] Fresh independent code review; fix material findings.
- [x] Commit and publish feature branch/draft PR for review. Do not merge/deploy or access live ERP. Describe exact no-migrate setup and remaining live validation.

Review ledger:
- Release reviewer confirmed an important submitted-update lifecycle interaction with existing dynamic rounding. Added before_update_after_submit protection and a regression invoking the actual production handler; it failed before the fix and passes afterward.
- Recovery service fixed overall timeout could repeatedly kill slow backlog polling before cursor progress. TimeoutStartSec=0 lets finite HTTP/pagination finish. Immediate queued jobs remain bounded; the independent recovery path covers queue timeout/failure.
-167 standalone no-site tests pass; Python3.6 syntax and feature JS/native guide template syntax pass. No live ERP accessed or changed.

Published for review: https://github.com/worldshading-bh/worldshading/pull/42 (draft). Production main was not merged or deployed.
