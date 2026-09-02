from __future__ import unicode_literals

import frappe
from frappe import _


@frappe.whitelist()
def get_account_signature_preview(sender=None):
	"""Return the signature for the outgoing account available to this user."""
	account = None
	sender = (sender or "").strip()

	if sender:
		account_name = frappe.db.get_value(
			"Email Account",
			{"email_id": sender, "enable_outgoing": 1},
			"name"
		)
		if not account_name:
			frappe.throw(_("The selected outgoing Email Account is unavailable."))

		linked_account = frappe.db.get_value(
			"User Email",
			{
				"parent": frappe.session.user,
				"parenttype": "User",
				"email_account": account_name,
				"enable_outgoing": 1,
			},
			"name"
		)
		if not linked_account:
			frappe.throw(_("You are not permitted to use this Email Account."))
		account = frappe.get_doc("Email Account", account_name)
	else:
		account_name = frappe.db.get_value(
			"Email Account",
			{"enable_outgoing": 1, "default_outgoing": 1},
			"name"
		)
		account = frappe.get_doc("Email Account", account_name) \
			if account_name else None

	if not account or not account.add_signature or not account.signature:
		return {"signature": ""}

	return {
		"email_account": account.name,
		"signature": account.signature,
	}
