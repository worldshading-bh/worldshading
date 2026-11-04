# Sales Target Performance Row Highlight Design

## Intent

Make achievement immediately visible across each Sales Target Performance result row while preserving ERPNext v12's native DataTable layout and interaction.

## Behavior

- Apply a subtle green background to the complete result row when `achievement_percent >= 100`.
- Apply a subtle red background when `achievement_percent < 100`.
- Do not color header, filter, footer, or empty-state rows.
- Reapply row classes after DataTable redraws so sorting, filtering, and virtual rendering keep the correct color.
- Keep calculations, status indicators, invoice drill-down, columns, and summary cards unchanged.

## Approach

Selected: reuse the row-class and redraw-observer pattern already used by World Shading reports. It colors the native `.dt-cell` elements, including the serial-number cell, without replacing Frappe's table markup.

Rejected alternatives:

- Formatter-level backgrounds do not cover the complete row or serial-number cell.
- Styling rows by visible text is fragile under translation and formatting changes.

## Scope and Safety

Only the Sales Target Performance client script and its executable client test change. This is presentation-only, ERPNext/Frappe v12 compatible, and requires only report `reload-doc`. Rollback is a single commit revert followed by the same report-only reload.
