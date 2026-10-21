# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import json
import os
import unittest
from unittest.mock import patch

import frappe

from worldshading.worldshading.doctype.campaign_customer import campaign_customer


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


class TestCampaignCustomerControllerContract(unittest.TestCase):

	def test_controller_exposes_approved_validation_api(self):
		for name in (
			"validate_unique_campaign_customer", "update_interaction_summary",
			"validate_opportunity_customer"
		):
			self.assertTrue(hasattr(campaign_customer, name), "Missing controller helper: {0}".format(name))
		self.assertIn("validate", campaign_customer.CampaignCustomer.__dict__)


@unittest.skipUnless(
	all(hasattr(campaign_customer, name) for name in (
		"validate_unique_campaign_customer", "update_interaction_summary",
		"validate_opportunity_customer"
	)) and "validate" in campaign_customer.CampaignCustomer.__dict__,
	"Campaign Customer validation API is not implemented"
)
class TestCampaignCustomerController(unittest.TestCase):

	def _doc(self, **values):
		data = {
			"name": None,
			"campaign": "SAL-CAM-2026-00001",
			"customer": "CUST-0001",
			"opportunity": None,
			"interactions": [],
			"next_follow_up": "2026-10-25 09:00:00",
			"last_contact_on": None,
			"last_outcome": None,
			"number_of_interactions": 0
		}
		data.update(values)
		return frappe._dict(data)

	def _throw(self, message, *args, **kwargs):
		raise frappe.ValidationError(message)

	def test_new_duplicate_is_rejected_without_empty_name_filter(self):
		doc = self._doc()
		with patch.object(campaign_customer.frappe, "db", create=True) as db:
			db.get_value.return_value = "CC-2026-00001"
			with patch.object(campaign_customer.frappe, "throw", side_effect=self._throw):
				with self.assertRaisesRegex(frappe.ValidationError, "CUST-0001.*SAL-CAM"):
					campaign_customer.validate_unique_campaign_customer(doc)
		filters = db.get_value.call_args[0][1]
		self.assertEqual(filters, {
			"campaign": "SAL-CAM-2026-00001",
			"customer": "CUST-0001"
		})

	def test_saved_record_excludes_itself_from_duplicate_lookup(self):
		doc = self._doc(name="CC-2026-00001")
		with patch.object(campaign_customer.frappe, "db", create=True) as db:
			db.get_value.return_value = None
			campaign_customer.validate_unique_campaign_customer(doc)
		filters = db.get_value.call_args[0][1]
		self.assertEqual(filters["name"], ["!=", "CC-2026-00001"])

	def test_empty_history_preserves_manually_planned_follow_up(self):
		doc = self._doc()
		campaign_customer.update_interaction_summary(doc)
		self.assertEqual(doc.number_of_interactions, 0)
		self.assertIsNone(doc.last_contact_on)
		self.assertIsNone(doc.last_outcome)
		self.assertEqual(doc.next_follow_up, "2026-10-25 09:00:00")

	def test_summary_uses_latest_dated_interaction_and_latest_nonempty_follow_up(self):
		doc = self._doc(interactions=[
			frappe._dict({
				"interaction_on": "2026-10-18 09:00:00", "outcome": "Busy",
				"next_follow_up": "2026-10-22 09:00:00"
			}),
			frappe._dict({
				"interaction_on": "2026-10-20 11:00:00", "outcome": "Interested",
				"next_follow_up": None
			}),
			frappe._dict({
				"interaction_on": "", "outcome": "Other",
				"next_follow_up": "2026-10-30 09:00:00"
			}),
			frappe._dict({
				"interaction_on": "2026-10-19 10:00:00", "outcome": "Call Back Later",
				"next_follow_up": "2026-10-25 10:00:00"
			})
		])
		campaign_customer.update_interaction_summary(doc)
		self.assertEqual(doc.number_of_interactions, 4)
		self.assertEqual(doc.last_contact_on, "2026-10-20 11:00:00")
		self.assertEqual(doc.last_outcome, "Interested")
		self.assertEqual(doc.next_follow_up, "2026-10-25 10:00:00")

	def test_invalid_nonblank_interaction_date_is_rejected(self):
		doc = self._doc(interactions=[frappe._dict({
			"interaction_on": "not-a-date", "outcome": "Other", "next_follow_up": None
		})])
		with self.assertRaises((TypeError, ValueError)):
			campaign_customer.update_interaction_summary(doc)

	def test_opportunity_must_exist_and_belong_to_the_same_customer(self):
		doc = self._doc(opportunity="OPTY-0001")
		invalid_values = [
			None,
			frappe._dict({"opportunity_from": "Lead", "party_name": "LEAD-0001"}),
			frappe._dict({"opportunity_from": "Customer", "party_name": "CUST-0002"})
		]
		for values in invalid_values:
			with self.subTest(values=values):
				with patch.object(campaign_customer.frappe, "db", create=True) as db:
					db.get_value.return_value = values
					with patch.object(campaign_customer.frappe, "throw", side_effect=self._throw):
						with self.assertRaises(frappe.ValidationError):
							campaign_customer.validate_opportunity_customer(doc)

	def test_matching_customer_opportunity_is_accepted(self):
		doc = self._doc(opportunity="OPTY-0001")
		with patch.object(campaign_customer.frappe, "db", create=True) as db:
			db.get_value.return_value = frappe._dict({
				"opportunity_from": "Customer", "party_name": "CUST-0001"
			})
			campaign_customer.validate_opportunity_customer(doc)

	def test_document_validate_applies_all_rules(self):
		doc = self._doc(
			opportunity="OPTY-0001",
			interactions=[frappe._dict({
				"interaction_on": "2026-10-20 11:00:00",
				"outcome": "Interested",
				"next_follow_up": "2026-10-22 09:00:00"
			})]
		)
		with patch.object(campaign_customer.frappe, "db", create=True) as db:
			db.get_value.side_effect = [
				None,
				frappe._dict({
					"opportunity_from": "Customer", "party_name": "CUST-0001"
				})
			]
			campaign_customer.CampaignCustomer.validate(doc)
		self.assertEqual(doc.number_of_interactions, 1)
		self.assertEqual(doc.last_outcome, "Interested")


class TestCampaignCustomerCRMNavigation(unittest.TestCase):

	def test_crm_module_exposes_campaign_management(self):
		config_path = os.path.abspath(os.path.join(
			os.path.dirname(__file__), "..", "..", "..", "config", "crm.py"
		))
		self.assertTrue(os.path.exists(config_path),
			"Missing CRM module configuration: {0}".format(config_path))
		from worldshading.config import crm
		sections = crm.get_data()
		campaign_section = next(
			section for section in sections
			if section.get("label") == "Campaign Management"
		)
		items = dict((item["name"], item) for item in campaign_section["items"])
		self.assertEqual(set(items), set(["Campaign Customer", "Campaign"]))
		self.assertEqual(items["Campaign Customer"]["type"], "doctype")
		self.assertEqual(items["Campaign"]["type"], "doctype")


if __name__ == "__main__":
	unittest.main()
