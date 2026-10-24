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
			"naming_series", "campaign_customer_key", "contact_section", "customer",
			"customer_name", "contact_column", "contact_person", "mobile_number",
			"whatsapp_number", "work_section", "campaign", "caller", "status",
			"work_column", "priority", "planned_contact_date", "planned_contact_time",
			"progress_section", "last_contact_on", "last_outcome", "latest_note",
			"progress_column", "next_follow_up", "next_action", "visit_required",
			"opportunity", "details_section", "customer_group", "territory",
			"details_column", "email_address", "number_of_interactions",
			"interactions_section", "interactions", "notes_section", "general_notes"
		])
		for fieldname in (
			"contact_section", "work_section", "progress_section", "details_section",
			"interactions_section", "notes_section"
		):
			self.assertEqual(fields[fieldname].get("fieldtype"), "Section Break")
		for fieldname in (
			"contact_column", "work_column", "progress_column", "details_column"
		):
			self.assertEqual(fields[fieldname].get("fieldtype"), "Column Break")
		for fieldname in ("details_section", "interactions_section", "notes_section"):
			self.assertEqual(fields[fieldname].get("collapsible"), 1)

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
		for property_name in ("hidden", "read_only", "unique", "no_copy"):
			self.assertEqual(fields["campaign_customer_key"].get(property_name), 1)

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
		for fieldname in (
			"last_contact_on", "last_outcome", "latest_note", "number_of_interactions"
		):
			self.assertEqual(fields[fieldname].get("read_only"), 1)
		for fieldname in ("next_follow_up", "last_outcome", "latest_note"):
			self.assertEqual(fields[fieldname].get("in_list_view"), 1)
		self.assertEqual(fields["next_follow_up"].get("in_standard_filter"), 1)
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
			"set_campaign_customer_key", "validate_unique_campaign_customer", "update_interaction_summary",
			"validate_opportunity_customer"
		):
			self.assertTrue(hasattr(campaign_customer, name), "Missing controller helper: {0}".format(name))
		self.assertIn("validate", campaign_customer.CampaignCustomer.__dict__)


@unittest.skipUnless(
	all(hasattr(campaign_customer, name) for name in (
		"set_campaign_customer_key", "validate_unique_campaign_customer", "update_interaction_summary",
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
			"latest_note": None,
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

	def test_campaign_customer_key_is_stable_and_distinguishes_customer(self):
		doc = self._doc()
		campaign_customer.set_campaign_customer_key(doc)
		self.assertEqual(
			doc.campaign_customer_key,
			"bc37b210f1b88e1e7fb8c6a68003efd8786e0da38fde319552a0b30717b68524"
		)
		other_customer = self._doc(customer="CUST-0002")
		campaign_customer.set_campaign_customer_key(other_customer)
		self.assertNotEqual(other_customer.campaign_customer_key, doc.campaign_customer_key)

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
		self.assertIsNone(doc.latest_note)
		self.assertEqual(doc.next_follow_up, "2026-10-25 09:00:00")

	def test_latest_dated_interaction_owns_all_current_summary_values(self):
		doc = self._doc(interactions=[
			frappe._dict({
				"interaction_on": "2026-10-18 09:00:00", "outcome": "Busy",
				"notes": "First attempt", "next_follow_up": "2026-10-22 09:00:00"
			}),
			frappe._dict({
				"interaction_on": "2026-10-20 11:00:00", "outcome": "Interested",
				"notes": "Customer requested a quotation", "next_follow_up": None
			}),
			frappe._dict({
				"interaction_on": "", "outcome": "Other", "notes": "Undated",
				"next_follow_up": "2026-10-30 09:00:00"
			}),
			frappe._dict({
				"interaction_on": "2026-10-19 10:00:00", "outcome": "Call Back Later",
				"notes": "Asked for tomorrow", "next_follow_up": "2026-10-25 10:00:00"
			})
		])
		campaign_customer.update_interaction_summary(doc)
		self.assertEqual(doc.number_of_interactions, 4)
		self.assertEqual(doc.last_contact_on, "2026-10-20 11:00:00")
		self.assertEqual(doc.last_outcome, "Interested")
		self.assertEqual(doc.latest_note, "Customer requested a quotation")
		self.assertIsNone(doc.next_follow_up)

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
		self.assertEqual(
			doc.campaign_customer_key,
			"bc37b210f1b88e1e7fb8c6a68003efd8786e0da38fde319552a0b30717b68524"
		)

	def _contact_doc(self):
		class ContactDocument(frappe._dict):
			def check_permission(inner_self, permission_type):
				if inner_self.get("deny_write"):
					raise frappe.ValidationError("Not permitted")
				inner_self.checked_permission = permission_type

			def append(inner_self, fieldname, values):
				row = frappe._dict(values)
				inner_self[fieldname].append(row)
				return row

			def save(inner_self):
				campaign_customer.update_interaction_summary(inner_self)
				inner_self.saved = True

		return ContactDocument(self._doc(
			name="CC-2026-00001", status="Planned", next_action="Call"
		))

	def test_record_contact_appends_audited_interaction_and_returns_current_summary(self):
		doc = self._contact_doc()
		with patch.object(campaign_customer.frappe, "get_doc", return_value=doc), \
				patch.object(campaign_customer.frappe, "session", create=True) as session, \
				patch.object(
					campaign_customer, "now", return_value="2026-10-24 10:30:00", create=True
				):
			session.user = "cashier@example.com"
			result = campaign_customer.record_contact(
				"CC-2026-00001", "Call", "Interested", "Needs a quotation",
				"Interested", "2026-10-26 09:00:00", "Visit"
			)

		self.assertEqual(doc.checked_permission, "write")
		self.assertTrue(doc.saved)
		self.assertEqual(len(doc.interactions), 1)
		self.assertEqual(dict(doc.interactions[0]), {
			"interaction_on": "2026-10-24 10:30:00",
			"channel": "Call",
			"handled_by": "cashier@example.com",
			"outcome": "Interested",
			"notes": "Needs a quotation",
			"next_follow_up": "2026-10-26 09:00:00"
		})
		self.assertEqual(doc.status, "Interested")
		self.assertEqual(doc.next_action, "Visit")
		self.assertEqual(result, {
			"name": "CC-2026-00001",
			"status": "Interested",
			"last_contact_on": "2026-10-24 10:30:00",
			"last_outcome": "Interested",
			"latest_note": "Needs a quotation",
			"next_follow_up": "2026-10-26 09:00:00",
			"number_of_interactions": 1
		})

	def test_record_contact_rejects_invalid_options_before_loading_document(self):
		invalid_values = [
			("Fax", "Interested", "Planned", "Call"),
			("Call", "Maybe", "Planned", "Call"),
			("Call", "Interested", "Waiting", "Call"),
			("Call", "Interested", "Planned", "Fax")
		]
		for channel, outcome, status, next_action in invalid_values:
			with self.subTest(value=(channel, outcome, status, next_action)):
				with patch.object(campaign_customer.frappe, "get_doc") as get_doc, \
						patch.object(campaign_customer.frappe, "throw", side_effect=self._throw):
					with self.assertRaises(frappe.ValidationError):
						campaign_customer.record_contact(
							"CC-2026-00001", channel, outcome, "Note", status,
							"2026-10-26 09:00:00", next_action
						)
				get_doc.assert_not_called()

	def test_record_contact_requires_note_and_actionable_follow_up(self):
		invalid_values = [
			("   ", "Planned", None),
			("Call again", "Follow Up", None),
			("Send quote", "Interested", "")
		]
		for notes, status, next_follow_up in invalid_values:
			with self.subTest(value=(notes, status, next_follow_up)):
				with patch.object(campaign_customer.frappe, "get_doc") as get_doc, \
						patch.object(campaign_customer.frappe, "throw", side_effect=self._throw):
					with self.assertRaises(frappe.ValidationError):
						campaign_customer.record_contact(
							"CC-2026-00001", "Call", "No Answer", notes, status,
							next_follow_up, "Call"
						)
				get_doc.assert_not_called()

	def test_record_contact_stops_when_write_permission_is_denied(self):
		doc = self._contact_doc()
		doc.deny_write = True
		with patch.object(campaign_customer.frappe, "get_doc", return_value=doc):
			with self.assertRaises(frappe.ValidationError):
				campaign_customer.record_contact(
					"CC-2026-00001", "Call", "No Answer", "No response",
					"Follow Up", "2026-10-25 09:00:00", "Call"
				)
		self.assertEqual(doc.interactions, [])

	def test_bulk_creation_skips_existing_and_duplicates_without_consuming_batch(self):
		inserted_values = []

		class InsertDocument(object):
			def __init__(inner_self, values):
				inner_self.values = values
				inner_self.name = "CC-{0}".format(values["customer"])

			def insert(inner_self):
				inserted_values.append(inner_self.values)
				return inner_self

		def get_doc(values):
			return InsertDocument(values)

		with patch.object(campaign_customer.frappe, "has_permission", return_value=True), \
				patch.object(campaign_customer.frappe, "get_all", return_value=[
					{"customer": "CUST-0002"}
				]) as get_all, \
				patch.object(campaign_customer.frappe, "get_doc", side_effect=get_doc):
			result = campaign_customer.bulk_create_campaign_customers(
				"SPRINT-2026", ["CUST-0001", "CUST-0002", "CUST-0001", "CUST-0003", "CUST-0004"],
				"cashier@example.com", "2026-10-25", "Top 20", 2
			)

		get_all.assert_called_once_with(
			"Campaign Customer",
			filters={
				"campaign": "SPRINT-2026",
				"customer": ["in", ["CUST-0001", "CUST-0002", "CUST-0003", "CUST-0004"]]
			},
			fields=["customer"]
		)
		self.assertEqual(inserted_values, [
			{
				"doctype": "Campaign Customer", "campaign": "SPRINT-2026",
				"customer": "CUST-0001", "caller": "cashier@example.com",
				"planned_contact_date": "2026-10-25", "priority": "Top 20",
				"status": "Planned"
			},
			{
				"doctype": "Campaign Customer", "campaign": "SPRINT-2026",
				"customer": "CUST-0003", "caller": "cashier@example.com",
				"planned_contact_date": "2026-10-25", "priority": "Top 20",
				"status": "Planned"
			}
		])
		self.assertEqual(result, {
			"created": ["CC-CUST-0001", "CC-CUST-0003"],
			"created_count": 2,
			"skipped": ["CUST-0002"],
			"skipped_count": 1
		})

	def test_bulk_creation_requires_create_permission_before_data_access(self):
		with patch.object(campaign_customer.frappe, "has_permission", return_value=False), \
				patch.object(campaign_customer.frappe, "get_all") as get_all, \
				patch.object(campaign_customer.frappe, "throw", side_effect=self._throw):
			with self.assertRaises(frappe.ValidationError):
				campaign_customer.bulk_create_campaign_customers(
					"SPRINT-2026", ["CUST-0001"], "cashier@example.com", "2026-10-25"
				)
		get_all.assert_not_called()

	def test_bulk_creation_rejects_missing_invalid_or_oversized_input(self):
		valid = {
			"campaign": "SPRINT-2026", "customers": ["CUST-0001"],
			"caller": "cashier@example.com", "planned_contact_date": "2026-10-25",
			"priority": "Standard", "batch_size": 1
		}
		invalid_values = [
			dict(valid, campaign=""),
			dict(valid, customers=[]),
			dict(valid, caller=""),
			dict(valid, planned_contact_date=""),
			dict(valid, priority="Urgent"),
			dict(valid, batch_size=0),
			dict(valid, batch_size=251),
			dict(valid, customers=["CUST-{0}".format(index) for index in range(251)])
		]
		for values in invalid_values:
			with self.subTest(values=values):
				with patch.object(campaign_customer.frappe, "has_permission", return_value=True), \
						patch.object(campaign_customer.frappe, "get_all") as get_all, \
						patch.object(campaign_customer.frappe, "throw", side_effect=self._throw):
					with self.assertRaises(frappe.ValidationError):
						campaign_customer.bulk_create_campaign_customers(**values)
				get_all.assert_not_called()

	def test_bulk_creation_does_not_hide_insert_failure(self):
		insert_document = type("InsertDocument", (object,), {
			"insert": lambda inner_self: (_ for _ in ()).throw(RuntimeError("insert failed"))
		})()
		with patch.object(campaign_customer.frappe, "has_permission", return_value=True), \
				patch.object(campaign_customer.frappe, "get_all", return_value=[]), \
				patch.object(campaign_customer.frappe, "get_doc", return_value=insert_document):
			with self.assertRaisesRegex(RuntimeError, "insert failed"):
				campaign_customer.bulk_create_campaign_customers(
					"SPRINT-2026", ["CUST-0001"], "cashier@example.com", "2026-10-25"
				)


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
