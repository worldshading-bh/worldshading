# Customer Retention Analysis Column Reordering Design

## Intent

Restore the normal ERPNext v12 report experience of dragging columns into a useful
order while preserving the Customer Retention Analysis identity columns during
horizontal scrolling.

## Goals

- Keep the row-number column, Customer, and Customer Name anchored at the start of
  the report and sticky during horizontal scrolling.
- Allow every analytical column after Customer Name to be reordered through the
  existing Frappe DataTable drag-and-drop behavior.
- Reapply field-based colors, Item Group header tooltips, sticky offsets, empty-state
  layout, and selected-row highlighting after a column move.
- Remain compatible with ERPNext/Frappe v12 and the existing prepared Script Report.

## Non-goals

- Do not allow the three anchored identity columns to be moved.
- Do not persist a user's column order across reloads or prepared-report rebuilds.
- Do not change report calculations, filters, permissions, backend code, or data.
- Do not modify Frappe or ERPNext core files.

## Constraints

- Frappe DataTable v12 uses SortableJS for header movement and swaps DataTable column
  indexes after a drop.
- The existing report deliberately disables that SortableJS instance because the
  custom sticky layout depends on column indexes.
- The solution must prevent drag operations involving anchored columns while leaving
  native movement enabled for the remaining columns.

## Approaches Considered

1. **Anchored sticky identity columns; movable analytical columns — selected.**
   Preserve row number, Customer, and Customer Name at the start and exclude them
   from drag-and-drop. Recalculate report-specific decoration after other columns
   move. This preserves identity context without ambiguous non-contiguous sticky
   columns.
2. **All columns movable, with Customer fields sticky wherever moved.** This is more
   flexible but can create overlapping or confusing sticky regions when the identity
   columns are separated.
3. **Remove sticky behavior and use unrestricted native movement.** This is simpler
   but loses important customer context while reviewing wide reports.

## Implementation Shape

- Add a small report-local helper that enables the existing DataTable SortableJS
  instance and rejects any move whose source or destination crosses the anchored
  boundary.
- Keep the DataTable's native switch operation for permitted analytical-column moves.
- On `onSwitchColumn`, recompute column references and rebuild report-specific sticky
  and decoration rules from current field names and indexes.
- Add executable client regression coverage that first demonstrates the current
  disabled behavior, then verifies anchored columns cannot move and analytical
  columns can.

## Testing and Rollback

Run the standalone Customer Retention Analysis client tests and JavaScript syntax
checks. Manually verify dragging, horizontal scrolling, resizing, sorting, filtering,
empty results, row selection, colors, and tooltips in the report.

Rollback is a direct revert of the Customer Retention Analysis JavaScript, its client
test, and this design/implementation documentation. No database rollback is required.
