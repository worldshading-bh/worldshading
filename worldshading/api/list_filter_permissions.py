from __future__ import unicode_literals

import frappe


def has_permission(doc, user=None, ptype=None):
	"""Restrict deletion of global and other users' saved filters."""
	if ptype != "delete":
		return None

	user = user or frappe.session.user
	roles = frappe.get_roles(user)
	is_manager = "System Manager" in roles

	# An empty for_user value identifies a global saved filter.
	if not doc.for_user:
		return is_manager

	if is_manager:
		return True

	# Normal users may delete only their own personal saved filters.
	return doc.for_user == user
