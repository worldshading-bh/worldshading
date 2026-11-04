# Customer Retention Analysis User Sticky Columns Design

## Intent

Let a user pin useful analytical columns into the Customer Retention Analysis sticky
section without changing report data or ERPNext core behavior.

## Selected Experience

- The standard column menu gains a **Pin / Unpin Column** action.
- Pinning an analytical column moves it immediately after the current sticky block.
- Multiple analytical columns may be pinned; they remain contiguous after Customer
  and Customer Name.
- Unpinning moves the column to the first non-sticky position and keeps the remaining
  pinned columns contiguous.
- Row number, Customer, and Customer Name are permanent identity columns and cannot
  be unpinned.
- Pinned field names survive report filter/rebuild refreshes during the current page
  session, but reset on a browser reload. Nothing is stored in the database or
  `localStorage`.

## Constraints and Non-goals

- Keep ERPNext/Frappe v12 and ES5 compatibility.
- Use the report's existing Frappe DataTable and SortableJS instance.
- Preserve native sort, reset-sort, remove-column and analytical drag behavior.
- Recalculate sticky left offsets, the sticky edge, header/footer positioning,
  field-based colors, tooltips, empty layout and row highlighting after changes.
- Do not change backend calculations, prepared-report data, permissions or core files.
- Do not persist sticky choices across browser reloads.

## Approaches

1. **Column-menu pin/unpin with session state — selected.** It is discoverable beside
   existing column actions, supports several pinned columns, and needs no server write.
2. **Toolbar dialog selecting sticky columns.** Easier to manage in bulk but slower for
   the common one-column action and visually detached from the chosen column.
3. **Persist choices in `localStorage`.** Convenient across reloads, but creates stale
   preferences when dynamic report columns change and was not requested.

## Implementation Shape

The report supplies the v12 DataTable header menu actions plus Pin / Unpin Column.
Pinned field names live on the DataTable instance. A small alignment routine performs
one native column switch at a time until pinned fields occupy the contiguous sticky
block; the existing `onSwitchColumn` event continues alignment and then rebuilds the
report-specific sticky CSS from current widths and indexes. Drag guards use the current
sticky-block size, preventing pinned columns from being dragged out.

## Testing and Rollback

Standalone client tests cover menu preservation, pinning, unpinning, multiple pinned
columns, refresh realignment, permanent identity columns and the dynamic drag boundary.
JavaScript syntax and whitespace checks remain required. Manual browser verification
covers menu interaction, horizontal scrolling, resizing, filtering and repeated pin /
unpin actions.

Rollback removes this incremental menu/state/layout behavior while retaining the prior
analytical-column reordering fix. No database rollback is needed.
