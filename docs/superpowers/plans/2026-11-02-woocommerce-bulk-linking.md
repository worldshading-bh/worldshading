# WooCommerce bulk linking release

Accepted scope: exact SKU / Item Code bulk matching from Settings; review a catalog preview before creating active stock-only links; optional future automatic matching; never replace existing links. Native Item sales UOM is preferred only with a valid conversion, otherwise a sole valid UOM is used; ambiguous units require review. Group Woo actions and display all parent variations as editable rows. No live ERP writes and no full migrate.

Implementation:
1. Add bounded catalog discovery, safe exact matching/UOM selection and revalidated application with per-target isolation.
2. Add Settings preview/apply and opt-in recovery scanning (never on stock events), preserving background cursors on stale form saves.
3. Replace the linking page with a variation table, independent row state and explicit saves; group document buttons.
4. Add targeted metadata upgrade, guide and release instructions. Run isolated Python/JS checks, review the branch, publish PR.

Review focus: inherited parent SKUs, case sensitivity, existing mappings, UOM ambiguity, concurrent/stale preview, target ownership, partial failures, cursor retry, no writes from preview, disabled background switches, source pin and manager/POST checks.


Execution ledger:
- Bulk backend tests first failed because the new module was absent; implemented and verified discovery, UOM selection, canonical save checks and cursor behavior.
- Variation-table behavior checks cover stale responses, independent rows, multi-page accumulation, active-link protection, save-all retry, and read-only preview with explicit application.
- Local browser fixture visually checked the actual Page component with sample records. No live ERP writes were performed.
- Final fresh-context review found one important issue: slow discovery could exhaust the budget before any application. Added test_slow_discovery_still_applies_one_candidate_instead_of_starving, observed failure, then allowed one candidate before enforcing the budget. Remaining candidates stay on the cursor for retry. No deferred findings or scope deviations.
