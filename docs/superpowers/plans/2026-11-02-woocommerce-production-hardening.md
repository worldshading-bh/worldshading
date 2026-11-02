# WooCommerce production hardening implementation plan

> Execute inline with the executing-plans, test-driven-development and verification-before-completion skills. This implements the user-approved consolidation of tested defects and the Fusion-informed linking/scheduling direction.

**Goal:** Ship a focused release preserving business Item data, making reviewed linking manageable, and registering five-minute native recovery without full migrate.

**Architecture:** Existing transactional change markers and post-commit queue remain authoritative. Native Frappe v12 cron wakes a long-queue recovery job. Product-level SQL locks serialize publishers. Mapping edits persist only the connector child and Item modification/audit metadata. Browser previews pause after 25 results or ten catalog chunks and may be explicitly saved locally for later review; server application always revalidates.

**Constraints:** Python 3.6, Frappe 12.16.3, ERPNext 12.26.0; no live writes, no bench tests, no full migrate, no catalog/image sync, no new dependencies. Existing settings and manual mappings preserved. Meter/Roll business correctness remains the catalog owner's review.

**Approaches:** Retain external timer (extra server setup), republish entire catalog every five minutes (unnecessary API traffic), or native recovery over existing change hashes (chosen for this release). Derive parents from ERP templates as Fusion does, or retain Woo-derived IDs for legacy independent Items (retain existing model). Bypass all Item rules globally, or use an authenticated narrow mapping write with validation, timestamp checks, SQL row locking and Version audit (narrow write).

## Review focus
- Queue timeout, disabled settings and overlap must not cause duplicate recovery or alter unrelated jobs.
- A business event arriving during HTTP must stay pending after a manual sync acknowledges its captured revision.
- Linking must not clear missing-file image references or rewrite other Item fields/children.
- Stale/forged preview, occupied mappings and invalid native UOMs must still fail closed.
- Prefilled sibling suggestions must not save without selecting those rows; interrupted preview must resume safely.

## Task 1 Native recovery
Files: hooks.py, integration/woocommerce/worker.py and install.py, tests/woocommerce/test_recovery.py and test_release_config.py.
- [x] Add failing tests for appended idempotent cron, disabled/foreign-site guard, long queue dispatch and shared recovery lock.
- [x] Implement scheduled_recovery plus recover using the existing worker path, restoring integration identity after execution. Hook only */5 cron. Targeted upgrade clears scheduler_events cache and reloads connector metadata/pages only.
- [x] Verify no-site suite; commit.

## Task 2 Acknowledge manual products
Files: sync.py and tests/woocommerce/test_sync.py.
- [x] Add failing test: manual success acknowledges only revision captured before payload; concurrent later revision remains pending. Failure uses backoff; held stock does not acknowledge full-payload verification.
- [x] Reuse StateStore for manual processing, keep post-cycle notify for genuinely newer/unrelated work.
- [x] Verify suite; commit.

## Task 3 Scoped mapping persistence
Files: new integration/woocommerce/link_persistence.py, linking.py, bulk_linking.py, tests/woocommerce/test_link_persistence.py and adapter tests.
- [x] Add regression proving mapping change never invokes Item.save and retains image/thumbnail/UOM siblings; reject stale timestamp under Item row lock.
- [x] Validate connector table, persist only changed child with native child DB methods, update Item modification metadata and create Version; commit with mapping. All auth and remote validation remain at entry points.
- [x] Verify suite; commit.

## Task 4 Reviewed batches and UI
Files: ws_woocommerce_link.js, linking-ui-test.js.
- [x] Add failing behavior tests for selected-only saves, 25-result pause, bounded empty scan, explicit next batch and saved-preview resume.
- [x] Add row selectors; prefill never selects. Show unit confirmation and empty-product guidance. Save/resume browser-local preview bound to user/site/store with current server revalidation on apply. Preserve all variations workflow.
- [x] Run UI harness and suite; commit.

## Task 5 Release verification and instructions
Files: docs/woocommerce/PRODUCTION-HARDENING.md, production/linking guide and affected old deployment instructions.
- [x] Document Fusion schedule evidence, actual recovery timings/limits, targeted upgrade, timer retirement, rollback and live acceptance checklist.
- [x] Run no-site Python, JS, PHP checks and Python 3.6 syntax compatibility; inspect full diff and perform independent code review.
- [ ] Commit release and create/attach PR for user deployment. Do not claim live acceptance from local test results.

## Execution record

- Baseline: 235 no-site Python tests passed on origin/main 9fc19ec.
- New missing recovery APIs, absent manual acknowledgements, missing scoped persistence, continuous preview and changed-store application were reproduced before their fixes.
- Final independent review checked native Frappe v12.16.3 Document, naming, Version and scheduler sources; no critical/important finding. Native MariaDB/child lifecycle remains an acceptance limitation.
- Release uses the dedicated existing release checkout on a new feature branch; no live ERP access or writes.
- Saved preview is explicitly browser-local rather than a new server DocType, keeping this release small and avoiding new schema. It expires after 24 hours and all saves revalidate.

Final verification: 247 no-site Python tests, both JavaScript harnesses, JavaScript syntax, Python 3.6 AST syntax (23 connector/hook files), and git diff whitespace checks passed. No PHP files changed.
