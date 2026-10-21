# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import json
import os
import unittest


class TestCampaignCustomerSchema(unittest.TestCase):

	def _load_definition(self, relative_path):
		path = os.path.abspath(os.path.join(os.path.dirname(__file__), relative_path))
		self.assertTrue(os.path.exists(path), "Missing DocType definition: {0}".format(path))
		with open(path) as definition_file:
			return json.load(definition_file)

	def _parent(self):
		return self._load_definition("campaign_customer.json")

	def _child(self):
		return self._load_definition(os.path.join(
			"..", "campaign_interaction_log", "campaign_interaction_log.json"
		))

	def _fields(self, definition):
		return dict((row["fieldname"], row) for row in definition["fields"])

	def test_parent_uses_approved_naming_and_layout(self):
		definition = self._parent()
		fields = self._fields(definition)
		self.assertEqual(definition.get("autoname"), "naming_series:")
		self.assertEqual(fields["naming_series"].get("options"), "CC-.YYYY.-.#####")
		self.assertEqual(definition.get("field_order"), [
			"naming_series", "campaign_schedule_section", "campaign", "status",
			"priority", "schedule_column", "caller", "planned_contact_date",
			"planned_contact_time", "customer_section", "customer", "customer_name",
			"customer_group", "territory", "contact_column", "contact_person",
			"mobile_number", "whatsapp_number", "email_address", "follow_up_section",
			"next_action", "next_follow_up", "visit_required", "conversion_column",
			"opportunity", "last_contact_on", "last_outcome",
			"number_of_interactions", "interactions_section", "interactions",
			"notes_section", "general_notes"
		])
		for fieldname in (
			"campaign_schedule_section", "customer_section", "follow_up_section",
			"interactions_section", "notes_section"
		):
			self.assertEqual(fields[fieldname].get("fieldtype"), "Section Break")
		for fieldname in ("schedule_column", "contact_column", "conversion_column"):
			self.assertEqual(fields[fieldname].get("fieldtype"), "Column Break")

	def test_parent_requires_operational_fields_and_options(self):
		fields = self._fields(self._parent())
		for fieldname in (
			"campaign", "customer", "caller", "planned_contact_date", "status", "priority"
		):
			self.assertEqual(fields[fieldname].get("reqd"), 1)
		self.assertEqual(fields["status"].get("options"),
			"Planned\nFollow Up\nInterested\nNot Interested\nConverted\nClosed")
		self.assertEqual(fields["priority"].get("options"), "Standard\nTop 20")
		self.assertEqual(fields["next_action"].get("options"),
			"\nCall\nWhatsApp\nSMS\nEmail\nVisit\nNone")

	def test_parent_list_filters_and_summaries_match_daily_work(self):
		fields = self._fields(self._parent())
		for fieldname in (
			"campaign", "customer", "caller", "planned_contact_date", "status", "priority"
		):
			self.assertEqual(fields[fieldname].get("in_standard_filter"), 1)
		for fieldname in (
			"campaign", "customer", "caller", "planned_contact_date", "status", "priority"
		):
			self.assertEqual(fields[fieldname].get("in_list_view"), 1)
		for fieldname in ("last_contact_on", "last_outcome", "number_of_interactions"):
			self.assertEqual(fields[fieldname].get("read_only"), 1)
		self.assertEqual(fields["interactions"].get("fieldtype"), "Table")
		self.assertEqual(fields["interactions"].get("options"), "Campaign Interaction Log")

	def test_parent_permissions_match_approved_roles(self):
		permissions = dict((row["role"], row) for row in self._parent()["permissions"])
		self.assertEqual(set(permissions), set(["Cashier", "Sales Manager", "System Manager"]))
		cashier_enabled = set(
			key for key, value in permissions["Cashier"].items()
			if key != "role" and value == 1
		)
		self.assertEqual(cashier_enabled, set(["create", "read", "write", "report"]))
		for role in ("Sales Manager", "System Manager"):
			for permission in (
				"create", "read", "write", "delete", "report", "export", "print", "email", "share"
			):
				self.assertEqual(permissions[role].get(permission), 1)

	def test_child_schema_preserves_multichannel_interactions(self):
		definition = self._child()
		fields = self._fields(definition)
		self.assertEqual(definition.get("istable"), 1)
		self.assertFalse(definition.get("permissions"))
		for fieldname in ("interaction_on", "channel", "handled_by", "outcome", "notes"):
			self.assertEqual(fields[fieldname].get("reqd"), 1)
		self.assertEqual(fields["channel"].get("options"),
			"Call\nWhatsApp\nSMS\nEmail\nVisit")
		self.assertEqual(fields["outcome"].get("options"),
			"No Answer\nBusy\nCall Back Later\nMessage Sent\nReplied\nInterested\n"
			"Not Interested\nWrong Number\nVisit Scheduled\nOrder Confirmed\nOther")
		self.assertEqual(fields["call_log"].get("options"), "Call Log")


if __name__ == "__main__":
	unittest.main()
