from __future__ import unicode_literals

import unittest
from unittest.mock import MagicMock, patch

import frappe

try:
	from worldshading.api import journal_entry_urgency
except ImportError:
	journal_entry_urgency = None


class TestJournalEntryUrgency(unittest.TestCase):

	def setUp(self):
		self.assertIsNotNone(
			journal_entry_urgency,
			"Journal Entry urgency API has not been implemented"
		)
		self.journal_entry = MagicMock()
		self.completed_patch = patch.object(journal_entry_urgency, "is_completed_workflow", return_value=False)
		self.completed_patch.start()
		self.addCleanup(self.completed_patch.stop)
		self.meta_patch = patch.object(frappe, "get_meta", return_value=MagicMock())
		self.meta_patch.start()
		self.addCleanup(self.meta_patch.stop)
		self.journal_entry.doctype = "Journal Entry"
		self.journal_entry.docstatus = 1
		self.journal_entry.get.return_value = "Pending"
		self.workflow = frappe._dict({
			"workflow_state_field": "workflow_state",
			"states": [frappe._dict({"state": "Pending", "allow_edit": "Purchase User"})]
		})
		self.workflow_name_patch = patch.object(
			journal_entry_urgency, "get_workflow_name",
			return_value="Journal Entry Workflow"
		)
		self.workflow_name_patch.start()
		self.addCleanup(self.workflow_name_patch.stop)
		self.workflow_patch = patch.object(
			journal_entry_urgency, "get_workflow", return_value=self.workflow
		)
		self.workflow_patch.start()
		self.addCleanup(self.workflow_patch.stop)
		self.roles_patch = patch.object(
			journal_entry_urgency,
			"_get_user_roles",
			return_value=["Purchase User"],
			create=True
		)
		self.roles_patch.start()
		self.addCleanup(self.roles_patch.stop)
		self.throw_patch = patch.object(frappe, "throw", side_effect=self.raise_validation_error)
		self.throw_patch.start()
		self.addCleanup(self.throw_patch.stop)

	@staticmethod
	def raise_validation_error(message):
		raise frappe.ValidationError(message)

	def test_mark_urgent_requires_and_trims_reason(self):
		with patch.object(frappe, "get_doc", return_value=self.journal_entry):
			result = journal_entry_urgency.set_journal_entry_urgency(
				"JE-0001", 1, "  Party needs advance today  "
			)

		self.journal_entry.check_permission.assert_called_once_with("write")
		self.journal_entry.db_set.assert_called_once_with({
			"custom_is_urgent": 1,
			"custom_urgent_reason": "Party needs advance today"
		}, notify=True)
		self.assertEqual(result["urgent"], 1)
		self.assertEqual(result["reason"], "Party needs advance today")
		self.journal_entry.save_version.assert_called_once_with()
		methods = [call[0] for call in self.journal_entry.method_calls]
		self.assertLess(methods.index("db_set"), methods.index("save_version"))

	def test_mark_urgent_rejects_empty_reason(self):
		with patch.object(frappe, "get_doc", return_value=self.journal_entry):
			with self.assertRaises(frappe.ValidationError):
				journal_entry_urgency.set_journal_entry_urgency("JE-0001", 1, "   ")

		self.journal_entry.db_set.assert_not_called()
		self.journal_entry.save_version.assert_not_called()

	def test_mark_normal_clears_reason(self):
		with patch.object(frappe, "get_doc", return_value=self.journal_entry):
			result = journal_entry_urgency.set_journal_entry_urgency(
				"JE-0001", 0, "old reason"
			)

		self.journal_entry.db_set.assert_called_once_with({
			"custom_is_urgent": 0,
			"custom_urgent_reason": ""
		}, notify=True)
		self.assertEqual(result, {"urgent": 0, "reason": ""})
		self.journal_entry.save_version.assert_called_once_with()

	def test_version_failure_is_not_silenced(self):
		self.journal_entry.save_version.side_effect = RuntimeError("Audit failed")
		with patch.object(frappe, "get_doc", return_value=self.journal_entry):
			with self.assertRaises(RuntimeError):
				journal_entry_urgency.set_journal_entry_urgency("JE-0001", 1, "Urgent")

	def test_cancelled_journal_entry_cannot_be_changed(self):
		self.journal_entry.docstatus = 2
		with patch.object(frappe, "get_doc", return_value=self.journal_entry):
			with self.assertRaises(frappe.ValidationError):
				journal_entry_urgency.set_journal_entry_urgency(
					"JE-0001", 1, "Urgent"
				)

		self.journal_entry.db_set.assert_not_called()

	def test_journal_entry_name_is_required(self):
		with self.assertRaises(frappe.ValidationError):
			journal_entry_urgency.set_journal_entry_urgency(None, 1, "Urgent")

	def test_writer_outside_current_workflow_role_can_change_urgency(self):
		with patch.object(journal_entry_urgency, "_get_user_roles",
				return_value=["Purchase Manager"], create=True):
			with patch.object(frappe, "get_doc", return_value=self.journal_entry):
				for urgent, reason in ((1, "Urgent"), (0, "")):
					result = journal_entry_urgency.set_journal_entry_urgency(
						"JE-0001", urgent, reason
					)
					self.assertEqual(result, {"urgent": urgent, "reason": reason})
		self.assertEqual(self.journal_entry.db_set.call_count, 2)
		self.assertEqual(self.journal_entry.save_version.call_count, 2)
		self.journal_entry.check_permission.assert_called_with("write")

	def test_current_workflow_state_supplies_allowed_edit_role(self):
		self.assertTrue(hasattr(journal_entry_urgency, "_get_workflow_allowed_role"))
		journal_entry = MagicMock()
		journal_entry.doctype = "Journal Entry"
		journal_entry.get.return_value = "Pending Accounts"
		workflow = frappe._dict({
			"workflow_state_field": "workflow_state",
			"states": [
				frappe._dict({"state": "Draft", "allow_edit": "Purchase User"}),
				frappe._dict({"state": "Pending Accounts", "allow_edit": "Accounts User"})
			]
		})

		with patch.object(journal_entry_urgency, "get_workflow_name",
				return_value="Journal Entry Workflow", create=True):
			with patch.object(journal_entry_urgency, "get_workflow",
					return_value=workflow, create=True):
				role = journal_entry_urgency._get_workflow_allowed_role(journal_entry)

		self.assertEqual(role, "Accounts User")

	def test_setup_creates_only_po_urgency_fields_and_refreshes_metadata(self):
		self.assertTrue(hasattr(
			journal_entry_urgency, "setup_journal_entry_urgency_fields"
		))
		cache = MagicMock()
		with patch.object(journal_entry_urgency, "create_custom_fields",
				create=True) as create_fields:
			with patch.object(frappe, "cache", return_value=cache):
				with patch.object(frappe, "get_hooks") as get_hooks:
					with patch.object(frappe, "clear_cache") as clear_cache:
						result = journal_entry_urgency.setup_journal_entry_urgency_fields()

		create_fields.assert_called_once_with(
			journal_entry_urgency.JOURNAL_ENTRY_URGENCY_FIELDS,
			update=True
		)
		cache.delete_key.assert_called_once_with("app_hooks")
		get_hooks.assert_called_once_with()
		clear_cache.assert_called_once_with(doctype="Journal Entry")
		self.assertEqual(result, {
			"doctype": "Journal Entry",
			"fields": ["custom_is_urgent", "custom_urgent_reason"]
		})

	def test_popup_query_filters_urgent_pos_by_workflow_roles_in_one_query(self):
		self.assertTrue(hasattr(
			journal_entry_urgency, "get_urgent_journal_entries"
		), "Urgent Journal Entry popup endpoint has not been implemented")
		self.workflow.states = [
			frappe._dict({"state": "Draft", "allow_edit": "Purchase User"}),
			frappe._dict({"state": "Pending Payment", "allow_edit": "Maker - ACC (Workflow)"}),
			frappe._dict({"state": "Pending Finance", "allow_edit": "Finance (Workflow)"})
		]
		rows = [frappe._dict({
			"name": "JE-0001",
			"workflow_state": "Pending Payment",
			"custom_urgent_reason": "Advance required"
		})]

		with patch.object(journal_entry_urgency, "_get_user_roles",
				return_value=["Purchase User", "Maker - ACC (Workflow)"]):
			with patch.object(frappe, "get_list", return_value=rows) as get_list:
				result = journal_entry_urgency.get_urgent_journal_entries()

		self.assertEqual(result, rows)
		get_list.assert_called_once_with(
			"Journal Entry",
			filters=[
				["custom_is_urgent", "=", 1],
				["docstatus", "!=", 2],
				["workflow_state", "in", ["Draft", "Pending Payment"]]
			],
			fields=[
				"name", "company", "total_debit",
				"workflow_state as workflow_state", "custom_urgent_reason", "modified"
			],
			order_by="modified desc",
			limit_page_length=50
		)

	def test_popup_query_skips_database_when_user_has_no_workflow_state(self):
		self.assertTrue(hasattr(
			journal_entry_urgency, "get_urgent_journal_entries"
		), "Urgent Journal Entry popup endpoint has not been implemented")
		with patch.object(journal_entry_urgency, "_get_user_roles",
				return_value=["Sales User"]):
			with patch.object(frappe, "get_list") as get_list:
				result = journal_entry_urgency.get_urgent_journal_entries()

		self.assertEqual(result, [])
		get_list.assert_not_called()

	def test_popup_before_field_installation_is_empty(self):
		frappe.get_meta.return_value.has_field.return_value = False
		with patch.object(frappe, "get_list") as get_list:
			self.assertEqual(journal_entry_urgency.get_urgent_journal_entries(), [])
		get_list.assert_not_called()

	def test_popup_resolves_company_currencies_in_one_batch(self):
		rows = [frappe._dict(name="JE-1", company="Company A"),
			frappe._dict(name="JE-2", company="Company A"),
			frappe._dict(name="JE-3", company="Company B")]
		companies = [frappe._dict(name="Company A", default_currency="BHD"),
			frappe._dict(name="Company B", default_currency="USD")]
		with patch.object(frappe, "get_list", return_value=rows), \
			patch.object(frappe, "get_all", return_value=companies) as get_all:
			result = journal_entry_urgency.get_urgent_journal_entries()
		self.assertEqual([row.currency for row in result], ["BHD", "BHD", "USD"])
		self.assertEqual(get_all.call_count, 1)
		self.assertEqual(get_all.call_args[0], ("Company",))
		self.assertEqual(set(get_all.call_args[1]["filters"]["name"][1]),
			{"Company A", "Company B"})

	def test_popup_uses_configured_workflow_field(self):
		self.workflow.workflow_state_field = "approval_status"
		with patch.object(frappe, "get_list", return_value=[]) as get_list:
			journal_entry_urgency.get_urgent_journal_entries()
		args = get_list.call_args[1]
		self.assertIn(["approval_status", "in", ["Pending"]], args["filters"])
		self.assertIn("approval_status as workflow_state", args["fields"])

	def test_write_permission_denial_prevents_changes_and_history(self):
		self.journal_entry.check_permission.side_effect = frappe.PermissionError
		with patch.object(frappe, "get_doc", return_value=self.journal_entry):
			with self.assertRaises(frappe.PermissionError):
				journal_entry_urgency.set_journal_entry_urgency("JE-0001", 1, "Urgent")
		self.journal_entry.db_set.assert_not_called()
		self.journal_entry.save_version.assert_not_called()


if __name__ == "__main__":
	unittest.main()
