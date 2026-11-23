import unittest
from unittest.mock import MagicMock, patch

import frappe
from worldshading.api import (
	gl_payment_urgency, journal_entry_urgency, payment_entry_urgency,
	purchase_order_urgency, urgency_notifications,
)

CEO = "CEO (Workflow)"
PURCHASE = "Purchase Manager (Workflow)"
USER = "dual@example.com"
WORKFLOW = frappe._dict(workflow_state_field="workflow_state", states=[
	frappe._dict(state="Purchasing", allow_edit=PURCHASE),
	frappe._dict(state="Both", allow_edit=PURCHASE),
	frappe._dict(state="Both", allow_edit=CEO),
	frappe._dict(state="CEO", allow_edit=CEO),
	frappe._dict(state="Finance", allow_edit="Finance"),
])
ENDPOINTS = (
	(gl_payment_urgency, "get_urgent_gl_payments", "GL Payment"),
	(journal_entry_urgency, "get_urgent_journal_entries", "Journal Entry"),
	(payment_entry_urgency, "get_urgent_payment_entries", "Payment Entry"),
	(purchase_order_urgency, "get_urgent_purchase_orders", "Purchase Order"),
)


class TestUrgencyRecipients(unittest.TestCase):
	def get_all(self, doctype, filters=None, fields=None):
		if doctype == "Has Role":
			return [frappe._dict(parent=USER, role=role) for role in (PURCHASE, CEO)
				if role in filters["role"][1]]
		if doctype == "User":
			return [frappe._dict(name=USER)]
		if doctype == "Workflow Assignment Role":
			self.assertEqual(filters["parenttype"], "User")
			self.assertEqual(filters["parentfield"], "workflow_assignment_preference")
			return [frappe._dict(parent=USER, role=role) for role in self.preferences]
		if doctype == "User Permission":
			self.assertEqual(filters["allow"], "Company")
			return [frappe._dict(user=USER, for_value=company, applicable_for=scope)
				for company, scope in self.company_rules]
		if doctype == "Company":
			return [frappe._dict(name=name, lft=left, rgt=right) for name, left, right in
				[("Group", 1, 4), ("Oman", 2, 3), ("Other", 5, 6)]]
		raise AssertionError(doctype)

	def setUp(self):
		self.preferences = [CEO]
		self.company_rules = [("Group", None), ("Other", "Sales Order")]

	def test_all_popup_endpoints_filter_before_the_fifty_row_limit(self):
		for module, method, doctype in ENDPOINTS:
			with self.subTest(doctype=doctype), patch.object(frappe, "session", frappe._dict(user=USER)), \
					patch.object(frappe, "get_meta") as meta, \
					patch.object(module, "get_workflow_name", return_value=doctype), \
					patch.object(module, "get_workflow", return_value=WORKFLOW), \
					patch.object(module, "_get_user_roles", return_value=[CEO, PURCHASE]), \
					patch.object(frappe, "get_all", side_effect=self.get_all), \
					patch.object(frappe, "get_list", return_value=[]) as listing:
				meta.return_value.has_field.return_value = True
				getattr(module, method)()
				self.assertEqual(listing.call_args[0][0], doctype)
				filters = listing.call_args[1]["filters"]
				self.assertIn(["workflow_state", "in", ["Both", "CEO"]], filters)
				companies = next(value for field, op, value in filters if field == "company")
				self.assertEqual(set(companies), {"", "Group", "Oman"})
				self.assertEqual(listing.call_args[1]["limit_page_length"], 50)

	def test_bell_matches_popup_eligibility_and_still_checks_read_access(self):
		for state, company, readable, expected in (
			("Purchasing", "Oman", True, 0),
			("CEO", "Other", True, 0),
			("Both", "Oman", False, 0),
			("Both", "Oman", True, 1),
		):
			with self.subTest(state=state, company=company, readable=readable):
				doc = MagicMock(doctype="Journal Entry", docstatus=1, name="JV-1")
				doc.get.side_effect = {"workflow_state":state, "company":company, "custom_is_urgent":1}.get
				doc.get_doc_before_save.return_value = None
				with patch.object(urgency_notifications, "get_workflow_name", return_value="JV"), \
						patch.object(urgency_notifications, "get_workflow", return_value=WORKFLOW), \
						patch.object(frappe, "session", frappe._dict(user="actor")), \
						patch.object(frappe, "get_all", side_effect=self.get_all), \
						patch.object(frappe, "get_list", return_value=[{"name":"JV-1"}]), \
						patch.object(frappe, "has_permission", return_value=readable), \
						patch.object(urgency_notifications, "is_notifications_enabled", return_value=True), \
						patch.object(urgency_notifications, "UrgencyNotificationLog") as log:
					urgency_notifications.notify_urgency_change(doc)
					self.assertEqual(log.call_count, expected)


if __name__ == "__main__":
	unittest.main()
