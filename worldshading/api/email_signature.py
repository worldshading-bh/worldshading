from __future__ import unicode_literals

from email.utils import parseaddr

import frappe
from frappe import _
from frappe.core.doctype.communication.email import make
from frappe.utils import cint, split_emails, validate_email_address


@frappe.whitelist()
def get_account_signature_preview(sender=None):
	"""Return composer defaults for the outgoing account available to this user."""
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
		account_name = _get_outgoing_account_name()
		account = frappe.get_doc("Email Account", account_name) \
			if account_name else None

	if not account:
		return {"signature": "", "default_cc": ""}

	return {
		"email_account": account.name,
		"signature": account.signature if account.add_signature else "",
		"default_cc": account.get("custom_default_cc") or "",
	}


@frappe.whitelist()
def make_with_default_cc(**kwargs):
	"""Enforce the outgoing Email Account's Default CC before core sending."""
	if cint(kwargs.get("send_email")) and \
		(kwargs.get("communication_medium") or "Email") == "Email":
		account_name = _get_outgoing_account_name(kwargs.get("sender"))
		if account_name:
			if not (parseaddr(kwargs.get("sender") or "")[1] or
				(kwargs.get("sender") or "").strip()):
				kwargs["sender"] = frappe.db.get_value(
					"Email Account", account_name, "email_id"
				)
			default_cc = frappe.db.get_value(
				"Email Account", account_name, "custom_default_cc"
			) or ""
			kwargs["cc"] = _merge_email_addresses(default_cc, kwargs.get("cc"))

	# Use frappe.call so request-only keys such as cmd and _lang are filtered
	# against the ERPNext v12 core method signature before delegation.
	return frappe.call(make, **kwargs)


def _get_outgoing_account_name(sender=None):
	sender_email = parseaddr(sender or "")[1] or (sender or "").strip()
	filters = {"enable_outgoing": 1}
	if sender_email:
		filters["email_id"] = sender_email
		return frappe.db.get_value("Email Account", filters, "name")

	account_name = _get_single_user_outgoing_account_name()
	if account_name:
		return account_name

	filters["default_outgoing"] = 1
	return frappe.db.get_value("Email Account", filters, "name")


def _get_single_user_outgoing_account_name():
	rows = frappe.get_all(
		"User Email",
		filters={
			"parent": frappe.session.user,
			"parenttype": "User",
			"enable_outgoing": 1,
		},
		fields=["email_account"],
	)
	account_names = set([
		row.get("email_account") for row in rows if row.get("email_account")
	])
	if len(account_names) != 1:
		return None

	account_name = account_names.pop()
	return frappe.db.get_value(
		"Email Account",
		{"name": account_name, "enable_outgoing": 1},
		"name",
	)


def _merge_email_addresses(default_cc, optional_cc):
	addresses = []
	seen = set()
	for value in (default_cc, optional_cc):
		for address in split_emails(value or ""):
			address = validate_email_address(address, throw=True)
			if address.lower() not in seen:
				seen.add(address.lower())
				addresses.append(address)
	return ", ".join(addresses)
