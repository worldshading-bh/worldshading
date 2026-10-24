# Campaign Contact Autofill Design

## Intent

Make Campaign Customer records immediately usable for outreach by copying the
Customer's primary Contact and all available contact details into blank fields.
This must work both when a user selects a Customer in the form and when records
are created in bulk from Customer Retention Analysis.

## Behavior

- Use `Customer.customer_primary_contact` as the Contact Person when the
  Campaign Customer has no Contact Person.
- Prefer the selected Contact's `mobile_no`, then `phone`, for Mobile Number.
- Use the selected Contact's `mobile_no` for WhatsApp Number.
- Prefer the selected Contact's `email_id`, then `Customer.email_id`, for Email
  Address.
- Fall back to `Customer.mobile_no` for Mobile Number and WhatsApp Number when
  the Contact has no mobile/phone.
- Server validation fills blank Campaign Customer fields only and never
  replaces manually entered values. Deliberately selecting a different
  Customer on the form resets Contact Person to that Customer's primary
  Contact, while preserving manually entered number and email fields.
- If source data is missing, leave the corresponding field blank.
- Do not update historical Campaign Customer records in bulk.

## Approach

Use matching client and server safeguards. The form script fills values
immediately after Customer or Contact selection. A controller helper runs
during validation so imports and report bulk creation receive the same missing
values. A client-only change would miss bulk creation; a server-only change
would delay the visible form update until save.

## Constraints and Risk

- ERPNext/Frappe v12 and Python 3.6 compatibility.
- Custom app files only; no SQL and no database migration.
- Respect Contact and Customer source data as-is.
- Primary risk is overwriting staff corrections; blank-only filling prevents
  that.

## Testing and Rollback

Add isolated JavaScript behavior tests for Customer/Contact selection and
Python unit tests for validation and bulk-created documents. Revert the
task-scoped commit to roll back; existing records and schema remain unchanged.
