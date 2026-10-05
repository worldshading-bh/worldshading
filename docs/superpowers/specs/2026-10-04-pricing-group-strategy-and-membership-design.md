# Pricing Group Strategy and Membership Design

## Objective

Make Pricing Group the configuration entry point for grouped pricing. A user should be able to select a Pricing Group in Pricing Strategy Analysis and have the correct Company, Item Group and Pricing Strategy populated automatically. The Pricing Group form must also show which Items currently belong to it and prevent incompatible Item membership.

## Scope

This change extends the existing Pricing Group and Pricing Strategy Analysis features. It does not replace the Item `pricing_group` field, create a second membership table, change pricing formulas, or automatically update Item Price or Pricing Rule records.

## Pricing Group fields

Add these fields to Pricing Group:

- `company`: required Link to Company.
- `item_group`: required Link to Item Group.
- `pricing_strategy`: required Link to Pricing Strategy Template.
- `included_items_html`: read-only HTML area populated from Item records.

Keep the existing Pricing Group Name, Disabled and Description fields.

The Pricing Strategy query must show only enabled Pricing Strategy Templates belonging to the selected Company. When Company changes, a strategy belonging to another company must be cleared.

## Membership source of truth

The existing Item `pricing_group` Link remains the only persisted membership source. The Pricing Group must not have a manually maintained child table because that would duplicate membership and could become inconsistent with Item.

The Included Items section is generated from Items whose `pricing_group` equals the current Pricing Group. It displays:

- Item Code
- Item Name
- Item Group
- Brand
- Stock UOM
- Enabled or Disabled status

The form also displays the number of included Items and provides a **View Items** button that opens the Item list filtered by the current Pricing Group.

New unsaved Pricing Groups show an instruction to save the group before assigning Items.

## Enforcement

Membership is enforced on the server and supplemented by client-side guidance.

When an Item is saved with a Pricing Group:

1. The Pricing Group must exist and be enabled.
2. The Item's Item Group must equal the Pricing Group's configured Item Group.
3. Otherwise saving is blocked with a clear validation message naming both groups.

When a Pricing Group is saved:

1. Company, Item Group and Pricing Strategy are required.
2. The Pricing Strategy must be enabled and belong to the configured Company.
3. Changing Item Group is blocked when any assigned Item belongs to a different Item Group. The message lists a small sample of mismatched Item codes and the total mismatch count.

Disabling a populated Pricing Group is allowed so an existing group can be retired without removing historical Item assignments. Disabled groups cannot receive new Item assignments and are excluded from normal report selection.

No workflow, permissions or direct database writes are bypassed.

## Pricing Strategy Analysis behavior

Place Pricing Group before the dependent Company/Strategy controls in the report filter flow while retaining all existing filters.

When a user selects Pricing Group:

1. Fetch its Company, Item Group, Pricing Strategy and Disabled state.
2. Reject a disabled or incompletely configured group with a clear message.
3. Set Company to the group's Company.
4. Set Item Group to the group's Item Group for visibility.
5. Set Pricing Strategy to the group's Pricing Strategy.
6. Load the strategy settings through the existing strategy loader.

Pricing Strategy remains visible as confirmation but is not manually required when a configured Pricing Group is selected. When no Pricing Group is selected, the current standalone Company and Pricing Strategy workflow continues unchanged.

Prepared Report restoration must restore saved filters without the Pricing Group change handler overwriting the historical Company, Item Group or Pricing Strategy values. Existing restoration guards must be reused.

The backend remains authoritative. If a Pricing Group is provided, it validates the group configuration and applies the group's Company, Item Group and Pricing Strategy consistently before calculation. A crafted client request must not mix a Pricing Group with another company's strategy.

## Existing Pricing Groups

Existing Pricing Groups may initially have blank new fields after the DocType definition is loaded. They are not modified automatically.

An administrator must open each existing group and set:

- Company
- Item Group
- Pricing Strategy Template

Until configured, the group cannot be used as the report's automatic configuration source. The report displays a clear incomplete-configuration message rather than silently choosing defaults.

Existing Item assignments remain intact. Saving an existing assigned Item before its Pricing Group is configured must show a clear configuration message so the administrator can configure the group first.

## ERPNext v12 implementation boundaries

- Use the custom `worldshading` app only; do not edit ERPNext core.
- Use ERPNext/Frappe v12-compatible Python and JavaScript.
- Add Pricing Group form JavaScript through `doctype_js` or the DocType JavaScript file, following the app's current structure.
- Enforce Item membership with an Item `validate` doc event in the custom app.
- Use `frappe.get_all`, `frappe.db.get_value` and normal document validation APIs.
- Do not use `frappe.qb`, type hints, dataclasses or newer framework APIs.
- Do not run migration, production database updates, restarts or cache-clearing commands as part of implementation.

## Permissions and security

- Pricing Group form access continues to use its existing roles.
- Included Items are fetched through a whitelisted read method that checks read permission for Pricing Group and Item.
- Report access and Pricing Strategy access continue to follow existing permissions.
- Server validation cannot rely only on client-side filters.

## Testing

Add focused tests for:

- Pricing Group strategy/company validation.
- Item membership accepted for the matching Item Group.
- Item membership rejected for a mismatched Item Group.
- Assignment to a disabled or incomplete Pricing Group rejected.
- Pricing Group Item Group change rejected when existing members mismatch.
- Included Items response and ordering.
- Report selection auto-populates Company, Item Group and Pricing Strategy.
- Standalone report use without Pricing Group remains unchanged.
- Prepared Report restoration does not trigger unwanted auto-overwrites.
- Backend rejects inconsistent crafted filters.

Run only direct Python unit tests, Node client tests, Python compilation and scoped diff checks. Do not run `bench test`, `bench migrate`, restart or cache-clear commands.

## Rollback

Rollback removes the new report auto-selection and validation hooks, then removes the new Pricing Group fields only after confirming they are no longer referenced. Existing Pricing Group masters and Item `pricing_group` assignments must be preserved. No generated Item Price or Pricing Rule records are deleted automatically.
