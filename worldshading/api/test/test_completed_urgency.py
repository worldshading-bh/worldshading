import unittest
from unittest.mock import MagicMock, patch

import frappe
from worldshading.api import purchase_order_urgency as po
from worldshading.api import payment_entry_urgency as pe
from worldshading.api import gl_payment_urgency as glp


class TestCompletedUrgency(unittest.TestCase):
	def test_completion_clears_both_fields_for_draft_and_submitted_documents(self):
		workflow = frappe._dict(workflow_state_field="approval_status")
		with patch.object(po, "get_workflow_name", return_value="Active"):
			with patch.object(po, "get_workflow", return_value=workflow):
				for doctype in ("Purchase Order", "Payment Entry", "GL Payment"):
					for status in (0, 1):
						doc = frappe._dict(doctype=doctype, docstatus=status,
							approval_status="Completed", custom_is_urgent=1,
							custom_urgent_reason="Pay today")
						po.clear_completed_urgency(doc)
						self.assertEqual(doc.custom_is_urgent, 0)
						self.assertEqual(doc.custom_urgent_reason, "")

	def test_noncompleted_and_cancelled_documents_are_unchanged(self):
		with patch.object(po, "get_workflow_name", return_value="Active"):
			with patch.object(po, "get_workflow", return_value=frappe._dict(workflow_state_field="workflow_state")):
				for state, status in (("Pending Payment", 1), ("Completed", 2)):
					doc = frappe._dict(doctype="Purchase Order", docstatus=status,
						workflow_state=state, custom_is_urgent=1, custom_urgent_reason="Pay today")
					po.clear_completed_urgency(doc)
					self.assertEqual(doc.custom_is_urgent, 1)
					self.assertEqual(doc.custom_urgent_reason, "Pay today")

	def test_completed_documents_cannot_be_marked_urgent_again(self):
		for module, setter in ((po, po.set_purchase_order_urgency), (pe, pe.set_payment_entry_urgency), (glp, glp.set_gl_payment_urgency)):
			doc = MagicMock(docstatus=1)
			with patch.object(frappe, "get_doc", return_value=doc), \
				patch.object(module, "_get_workflow_allowed_role", return_value=None), \
				patch.object(module, "_get_user_roles", return_value=[]), \
				patch.object(module, "is_completed_workflow", return_value=True), \
				patch.object(frappe, "throw", side_effect=frappe.ValidationError):
				with self.assertRaises(frappe.ValidationError):
					setter("TEST-1", 1, "Pay today")
			doc.db_set.assert_not_called()
			doc.save_version.assert_not_called()
