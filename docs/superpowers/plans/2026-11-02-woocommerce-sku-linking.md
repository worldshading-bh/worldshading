# SKU-assisted Item linking implementation plan

> Implement inline using superpowers:executing-plans. User approved the SKU-first workflow and requested implementation on 2 November 2026.

Goal: link existing products with SKU entry or automatic exact Item Code suggestions, without manual Woo IDs.
Architecture: retain Item-owned mappings and normal save_link; read-only SKU resolution and read-only suggestions use pinned Woo REST v3 credentials. Page gets a SKU lookup field; Item gets Link WooCommerce button. Save remains explicit and inactive. No bulk/automatic persistence or live ERP writes.
Tech stack: ERPNext/Frappe v12, Python3.6-compatible modules and native Desk JavaScript. No schema changes.

Approaches: SKU-only runtime identity rejected because codes can change or be inherited; manual IDs rejected as inconvenient; approved SKU discovery plus saved Woo IDs retains correct endpoints and simplifies linking.

- [x] Write failing adapter tests for exact simple/variation SKU lookup, parent rejection, incomplete/ambiguous/wrong-case results, authoritative edit-context SKU, permissions and no writes.
- [x] Implement bounded SKU resolver and selected-target exact ERP Item suggestion. Existing links win; inherited/blank SKU and conflicting Item links never auto-match. Only read native Item UOMs.
- [x] Test/implement Page SKU lookup and safe async suggestion preselection. Prevent stale lookup/suggestion callbacks, including edits during requests. Keep technical IDs collapsed.
- [x] Add Item Link WooCommerce action using route_options to seed Item code/SKU without fragile SKU-in-URL routing. Refuse dirty Item and perform no automatic save.
- [x] Document page-only refresh via existing upgrade_linking, cache clear/restart; no bench test or migrate. Run no-site suite, JS fixtures, Python3.6 grammar and independent review; create release PR.

Review focus: inherited parent SKU; conflicting mappings; no background persistence; case-sensitive exactness despite database collation; lookup completion after manual Item changes; permissions; API boundedness and malformed identity.

Completed: 216 no-site Python tests; Page and Item-action Node fixtures; JS syntax; Python3.6 grammar. Independent review found the Woo variation endpoint can inherit SKU even in edit context; fixed with conservative parent-SKU detection and canonical products-collection verification, then re-reviewed. No live ERP writes or deployment.
