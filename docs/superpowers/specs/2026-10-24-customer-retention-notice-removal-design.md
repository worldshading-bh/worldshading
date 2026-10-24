# Customer Retention Notice Removal Design

## Intent

Remove all year-to-date explanatory messages from Customer Retention Analysis so the report is visually cleaner. The underlying current-year and previous-year calculations must remain unchanged.

## Goals

- Remove the custom yellow year-to-date banner from the report client.
- Stop returning the similar backend report message.
- Remove dead banner styling, rendering calls, and layout-anchor handling.
- Place the result summary directly after the filter summary without an empty gap.

## Non-goals

- Do not change calendar-year boundaries, retention statuses, sorting, totals, charts, or prepared-report behavior.
- Do not change any DocType, database schema, workflow, or ERPNext core file.
- Do not modify the unrelated Pricing Group change in the main checkout.

## Approaches

1. **Clean removal (selected):** remove both message sources and all banner-only client code, then anchor the result summary directly to the filter summary. This avoids dead code and prevents the notice from reappearing in prepared reports.
2. **Visual hiding (rejected):** hide the client banner with CSS while retaining the backend message and dead code. This is smaller initially but is harder to maintain and can expose the notice through another rendering path.

## Implementation

- In the Python report, make the report message empty for all analysis years while retaining the existing date and status calculations.
- In the JavaScript report, remove the partial-year notice CSS, function, and calls.
- Insert the result summary directly after `.cra-filter-summary`.
- Update the isolated Python and client tests to prove the notice is absent and the remaining summary behavior is intact.

## Risk and rollback

Risk is low because only display/message behavior changes. Rollback is `git revert` of the implementation commit. No migration, reload-doc, cache clear, process restart, database update, or push is required as part of implementation.
