# System Manager Report Download Visibility Design

## Intent

Remove the convenient prepared-report **Download Report** action globally for Desk users who do not have the **System Manager** role, while preserving it for System Managers.

## Approach

Add one focused custom-app Desk script through `app_include_js`. The script wraps ERPNext v12's query-report prepared-button method once: it preserves the standard method, then removes only the translated **Download Report** inner button for non-System-Managers. This avoids ERPNext core changes, DOM polling, permanent observers, API calls, and database work.

## Alternatives Considered

- Per-report hiding was rejected because the approved policy applies to every query report and would duplicate code.
- CSS-only hiding was rejected because CSS cannot reliably apply the System Manager role condition.
- Server permission changes were rejected because the requested behavior is button visibility, not removal of report-view access.

## Boundaries

- This is a UI convenience restriction, not a security boundary; users who can view a report receive its data.
- Other prepared-report buttons and all report calculations remain unchanged.
- ERPNext/Frappe v12 compatibility is required.
- No migration, database update, core edit, restart, cache clear, or push is part of implementation.
