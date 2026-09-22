# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import unittest
from unittest.mock import patch

from worldshading.events.payment_entry_contact import (
	_get_source_values,
	set_payment_entry_contact,
)


class AttributeDict(dict):
	def __getattr__(self, key):
		return self.get(key)

	def __setattr__(self, key, value):
		self[key] = value


class TestPaymentEntryContact(unittest.TestCase):
	@patch("worldshading.events.payment_entry_contact._get_customer_contact_values")
	@patch("worldshading.events.payment_entry_contact._get_source_values")
	def test_source_is_used_before_customer(self, get_source_values, get_customer_values):
		get_source_values.return_value = {
			"whatsapp_no": "source-whatsapp",
			"contact_mobile": "source-mobile",
		}
		doc = AttributeDict({
			"party_type": "Customer",
			"party": "CUST-0001",
			"whatsapp_no": None,
			"contact_mobile": None,
		})

		set_payment_entry_contact(doc)

		self.assertEqual(doc.whatsapp_no, "source-whatsapp")
		self.assertEqual(doc.contact_mobile, "source-mobile")
		get_customer_values.assert_not_called()

	@patch("worldshading.events.payment_entry_contact._get_customer_contact_values")
	@patch("worldshading.events.payment_entry_contact._get_source_values")
	def test_customer_fills_values_missing_from_source(
		self, get_source_values, get_customer_values
	):
		get_source_values.return_value = {
			"whatsapp_no": "source-whatsapp",
			"contact_mobile": None,
		}
		get_customer_values.return_value = {
			"whatsapp_no": "customer-whatsapp",
			"contact_mobile": "customer-mobile",
		}
		doc = AttributeDict({
			"party_type": "Customer",
			"party": "CUST-0001",
			"whatsapp_no": None,
			"contact_mobile": None,
		})

		set_payment_entry_contact(doc)

		self.assertEqual(doc.whatsapp_no, "source-whatsapp")
		self.assertEqual(doc.contact_mobile, "customer-mobile")

	@patch("worldshading.events.payment_entry_contact._get_source_values")
	def test_existing_payment_entry_values_are_preserved(self, get_source_values):
		doc = AttributeDict({
			"party_type": "Customer",
			"party": "CUST-0001",
			"whatsapp_no": "manual-whatsapp",
			"contact_mobile": "manual-mobile",
		})

		set_payment_entry_contact(doc)

		self.assertEqual(doc.whatsapp_no, "manual-whatsapp")
		self.assertEqual(doc.contact_mobile, "manual-mobile")
		get_source_values.assert_not_called()

	@patch("worldshading.events.payment_entry_contact._get_document_contact_values")
	def test_sales_invoice_is_preferred_over_sales_order(self, get_contact_values):
		get_contact_values.side_effect = lambda doctype, name: {
			"whatsapp_no": name + "-whatsapp",
			"contact_mobile": name + "-mobile",
		}
		doc = AttributeDict({"references": [
			AttributeDict({
				"reference_doctype": "Sales Order",
				"reference_name": "SO-0001",
			}),
			AttributeDict({
				"reference_doctype": "Sales Invoice",
				"reference_name": "SINV-0001",
			}),
		]})

		values = _get_source_values(doc)

		self.assertEqual(values["whatsapp_no"], "SINV-0001-whatsapp")
		self.assertEqual(values["contact_mobile"], "SINV-0001-mobile")


if __name__ == "__main__":
	unittest.main()
