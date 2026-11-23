from __future__ import unicode_literals

from collections import defaultdict

import frappe


def get_role_preferences(users):
	if not users:
		return {}
	preferences = defaultdict(set)
	for row in frappe.get_all("Workflow Assignment Role", filters={
		"parent": ["in", users], "parenttype": "User",
		"parentfield": "workflow_assignment_preference"
	}, fields=["parent", "role"]):
		preferences[row.parent].add(row.role)
	return preferences


def get_company_permissions(doctype, users):
	"""Return allowed companies for users with applicable Company User Permissions."""
	if not users:
		return {}
	allowed = defaultdict(set)
	for row in frappe.get_all("User Permission", filters={
		"allow": "Company", "user": ["in", users]
	}, fields=["user", "applicable_for", "for_value"]):
		if not row.applicable_for or row.applicable_for == doctype:
			allowed[row.user].add(row.for_value)
	if not allowed:
		return allowed

	# Company is a nested set in v12. Parent permissions include descendants.
	tree = frappe.get_all("Company", fields=["name", "lft", "rgt"])
	by_name = {row.name: row for row in tree}
	expanded = {}
	for companies in allowed.values():
		for company in tuple(companies):
			if company not in expanded:
				parent = by_name.get(company)
				expanded[company] = {
					row.name for row in tree
					if parent and parent.lft and parent.rgt and row.lft and row.rgt
					and parent.lft < row.lft and row.rgt < parent.rgt
				}
			companies.update(expanded[company])
	return allowed


def get_popup_filters(doctype, workflow, user_roles):
	"""Keep workflow and Company restrictions inside the permission-aware list query."""
	routes = [(row.state, row.allow_edit) for row in workflow.states
		if row.allow_edit and row.allow_edit in user_roles]
	if not routes:
		return []

	user = frappe.session.user
	preference = get_role_preferences([user]).get(user)
	states = []
	for state, role in routes:
		if (not preference or role in preference) and state not in states:
			states.append(state)
	if not states:
		return []

	filters = [
		["custom_is_urgent", "=", 1],
		["docstatus", "!=", 2],
		[workflow.workflow_state_field, "in", states]
	]
	companies = get_company_permissions(doctype, [user]).get(user)
	if companies:
		filters.append(["company", "in", sorted({name for name in companies if name} | {""})])
	return filters
