# Customer Retention Multi-Item-Group Design

## Intent

Allow managers to select multiple exact Item Groups in Customer Retention Analysis. The report must treat the selection as one combined product basket for retention decisions while showing each selected group's contribution in yearly sales tooltips.

## Approved Behavior

- Replace the Item Group Link with ERPNext v12 `MultiSelectList`; blank means all Item Groups.
- Keep the `item_group` fieldname so existing prepared reports remain compatible.
- Visible sales, status, change, importance, inactivity, chart, summary, and invoice counts use the combined net sales/activity of any selected exact Item Group.
- Yearly sales tooltips show every selected group separately, the combined selected-groups total, total customer sales across all groups, and combined share of total.
- Groups with no sales in a displayed year appear as zero in the tooltip.
- Top Item Group 1–3 remains the positive-sales ranking within the selected groups.
- No child Item Groups are included automatically.

## Approaches

1. **Native `MultiSelectList` with bound SQL `IN` filters — selected.** This follows existing ERPNext v12 and Purchase Plan patterns, preserves prepared reports, and filters before ranking.
2. Comma-separated text input — rejected because names containing punctuation and manual entry would be unreliable.
3. Client-side filtering — rejected because Top Results, status, and importance would be calculated from the wrong population.

## Constraints and Safety

- ERPNext/Frappe v12 and Python 3.6 compatible; no type hints, query builder, or modern APIs.
- Accept new arrays, JSON-array strings, and legacy scalar Item Group values.
- Bind all Item Group values as SQL parameters; never interpolate user values.
- Run the per-group tooltip query only when groups are selected and only for final displayed customers and explicit reporting years.
- No migration, Bench tests, reload-doc, restart, cache operation, database write, or push.
