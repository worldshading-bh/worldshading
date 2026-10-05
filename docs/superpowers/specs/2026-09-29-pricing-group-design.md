# Pricing Group Design

**Date:** 29 September 2026
**Application:** World Shading
**Target:** ERPNext/Frappe v12, Python 3.6
**Status:** Proposed for review

## 1. Objective

Add a simple Pricing Group master so related Items, such as colour variants, can be identified, analysed, and updated as one pricing family. Every member of a Pricing Group must receive the same recommended Regular price, B2B price, and quantity-tier prices.

The feature must preserve the existing Prepared Report audit trail, 50-item safety limit, Item Price workflow, and Pricing Rule workflow.

## 2. Data model

### Pricing Group

Create a normal, non-tree DocType named **Pricing Group** in the Worldshading module.

Fields:

| Label | Fieldname | Type | Rules |
|---|---|---|---|
| Pricing Group Name | `pricing_group_name` | Data | Required, unique, title field, autoname source |
| Description | `description` | Small Text | Optional |
| Disabled | `disabled` | Check | Default 0, shown in list view |

The DocType does not store an Items child table. This prevents group membership from being duplicated in two places.

### Item membership

Add one custom Link field to Item:

| Property | Value |
|---|---|
| Label | Pricing Group |
| Fieldname | `pricing_group` |
| Type | Link |
| Options | Pricing Group |
| Required | No |

The Item field is the single source of truth. An Item can belong to zero or one Pricing Group. Existing Items without a Pricing Group continue to behave exactly as they do now.

The Pricing Group document may later receive a read-only **View Group Items** action, but no duplicate membership table is part of this implementation.

## 3. Group pricing policy

For each price level, the shared group recommendation is the highest valid recommendation among the group members:

```text
Group Regular Price = maximum member Recommended Regular Net
Group B2B Price     = maximum member Recommended B2B Net
Group Tier N Price  = maximum member Tier N Net
```

Each price level is calculated independently. The policy protects the member with the highest required selling price and prevents a lower-cost variant from pulling the family price below the requirement of a higher-cost variant.

The report retains each member's individual cost and calculation for explanation. Group recommendations are applied only to grouped price outputs and update actions.

## 4. Report behavior

Add **Pricing Group** as:

- an optional report filter;
- a result column in Full Analysis View; and
- an identity column in Simple Price View.

The filter returns Items whose `pricing_group` matches the selected Pricing Group. Existing Item Group, Item, Stock UOM, Brand, and Warehouse filters remain available.

For every group represented in the result, calculate the shared Regular, B2B, and tier recommendations after all individual rows have been calculated. Populate the group recommendation on every member row so users can see the common price that will be used.

Ungrouped Items continue to use their individual recommendations.

### Group integrity statuses

The report must identify:

- **Ready** — every active group member is present and has valid recommendations;
- **Different Current Prices** — members currently have different Item Prices, but the group can be aligned;
- **Incomplete Group** — one or more active members are absent from the Prepared Report result;
- **Missing Cost** — one or more present members cannot produce a valid recommendation; and
- **Disabled Group** — the linked Pricing Group is disabled.

Warnings must be concise in the report and update dialogs. Detailed member names may be shown in a tooltip or secondary message, not as a large warning block.

## 5. Complete-group safety rule

Item Price and Pricing Rule updates must never silently update only part of a Pricing Group.

A grouped update is allowed only when all non-disabled Items linked to that Pricing Group:

1. are present in the saved Prepared Report result;
2. are within the first-50-items update scope;
3. have a valid Base Cost and required recommendations; and
4. remain assigned to the same Pricing Group at execution time.

If any condition fails, block only that Pricing Group and explain the count/reason. Other complete groups and ungrouped Items may continue after confirmation.

The update APIs must use the saved Prepared Report rows. They must not silently calculate or add Items that were not visible in the audited report snapshot.

## 6. Item Price update

The preview groups member rows visually by Pricing Group and shows:

- Pricing Group;
- Item Code and Item Name;
- Price List;
- current price;
- member's individual recommendation;
- shared group price; and
- action.

For grouped Items, the saved Item Price uses the shared group recommendation. All members of the same complete group must remain together in the preview. Removing one member removes or deselects the whole group; partial group execution is rejected by the backend.

Ungrouped Item Price rows retain the existing removable-row behavior.

The existing limit remains **50 Items**, not 50 Item Price records. Regular and B2B Item Prices may therefore create up to 100 records for 50 Items.

All current safeguards remain: permission checks, confirmation, concurrent-change validation, Prepared Report link, and audit comment.

## 7. Pricing Rule update

When Pricing Group is used, one rule set is created per complete Pricing Group, with one Pricing Rule per tier containing every group member.

Example:

```text
PSA - KSA PVC 680 GSM Colours - Tier 1
PSA - KSA PVC 680 GSM Colours - Tier 2
PSA - KSA PVC 680 GSM Colours - Tier 3
PSA - KSA PVC 680 GSM Colours - Tier 4
```

The Pricing Group name becomes the default Rule Set Name.

The tier discount must be derived from the shared group reference price and shared group tier price, so all members receive one exact percentage for that tier. The final discount remains editable in the confirmation preview.

**Mixed Conditions** retains its existing meaning: quantities from different members of the Pricing Group can be combined to reach the tier minimum.

Grouped Items do not use the current cross-item average calculation. Their shared price structure produces one group discount directly. Existing Combined, Separate by Item, and Group by Same Discount modes remain available for ungrouped selections.

The backend rejects partial groups, duplicate memberships, disabled groups, or membership changes between preview and execution.

## 8. Prepared Report and audit requirements

Group membership, individual recommendations, shared recommendations, and group integrity status must be stored in the Prepared Report output used by each update preview.

Created or updated Item Prices and Pricing Rules continue to receive:

- `pricing_prepared_report` Link value; and
- an audit comment identifying the Prepared Report and action.

Opening the Prepared Report link must restore the Pricing Group filter along with all existing saved filters.

## 9. Permissions

Recommended Pricing Group permissions:

- System Manager: read, create, write, delete;
- Accounts Manager: read, create, write;
- Sales Manager: read;
- Stock Manager: read.

Item editing remains governed by native Item permissions. Price and rule updates retain native Item Price and Pricing Rule permissions.

## 10. Validation and compatibility

- Use only ERPNext/Frappe v12-compatible APIs and Python 3.6 syntax.
- Keep all code inside the `worldshading` custom app.
- Do not modify ERPNext core files.
- Do not use `frappe.qb`, dataclasses, or modern-only APIs.
- Do not bypass DocType permissions, workflow, or validation.
- Do not run migrations, restarts, cache clears, or production bench tests automatically.
- Preserve all behavior for Items without a Pricing Group.

## 11. Test coverage

Automated tests must cover:

1. normal Pricing Group metadata and Item Link definition;
2. Pricing Group report filtering;
3. highest recommendation selected independently for every price level;
4. ungrouped Items remaining unchanged;
5. different current prices producing a warning but allowing alignment;
6. incomplete groups being blocked from Item Price and Pricing Rule updates;
7. a member with missing cost blocking only its group;
8. the 50-item limit not splitting a group;
9. group membership changing after preview being rejected;
10. shared Item Price creation/update for Regular and optional B2B;
11. one Pricing Rule per group tier;
12. Mixed Conditions propagation;
13. Prepared Report links and comments; and
14. existing non-group pricing tests continuing to pass.

## 12. Deployment and rollback

Deployment will require loading the new standard Pricing Group DocType and creating/loading the Item custom field using the agreed production-safe mechanism. Exact commands will be listed in the implementation plan and must be run manually after review.

Rollback sequence:

1. stop using Pricing Group update actions;
2. revert report and update-flow code;
3. leave the optional Item field and master records in place temporarily so historical links are not destroyed;
4. remove the field and DocType only after confirming no Items or audit records depend on them.

Pricing changes already saved to Item Price or Pricing Rule are business records and must not be deleted automatically during rollback.

## 13. Acceptance criteria

The feature is accepted when:

- a user can create a normal Pricing Group and assign it on Item;
- filtering the report by that group returns its Items;
- every group member shows the same shared recommendation for each price level;
- the common value is the highest valid member recommendation for that level;
- incomplete or invalid groups cannot be partially updated;
- Item Price updates align all members to the shared price;
- Pricing Rule updates create one rule per group tier containing all members;
- Mixed Conditions works for group members when selected;
- all generated records link back to the correct Prepared Report; and
- ungrouped Items behave exactly as before.
