from __future__ import unicode_literals

import unittest

try:
	from unittest.mock import MagicMock, patch
except ImportError:
	from mock import MagicMock, patch

from worldshading.api import email_signature


class TestEmailSignatureSingleAccount(unittest.TestCase):
	def setUp(self):
		email_signature.frappe.init(site="erp.worldshading.com")
		email_signature.frappe.local.db = MagicMock()

	def tearDown(self):
		email_signature.frappe.destroy()

	@patch.object(email_signature.frappe, "call")
	@patch.object(email_signature.frappe, "get_all")
	@patch.object(email_signature.frappe.db, "get_value")
	def test_missing_sender_uses_only_permitted_account(
		self, get_value, get_all, frappe_call
	):
		get_all.return_value = [{"email_account": "IT Support"}]

		def get_value_side_effect(doctype, filters, fieldname):
			if doctype == "Email Account" and filters == {
				"name": "IT Support", "enable_outgoing": 1
			}:
				return "IT Support"
			if doctype == "Email Account" and filters == "IT Support" and \
				fieldname == "email_id":
				return "it.development@worldshading.com"
			if doctype == "Email Account" and filters == "IT Support" and \
				fieldname == "custom_default_cc":
				return "hussainaljad@worldshading.com"
			return None

		get_value.side_effect = get_value_side_effect
		frappe_call.return_value = {"name": "COMM-TEST"}

		email_signature.make_with_default_cc(
			send_email=1,
			communication_medium="Email",
			recipients="customer@example.com",
			cc="accounts@example.com",
		)

		kwargs = frappe_call.call_args[1]
		self.assertEqual(
			kwargs["sender"], "it.development@worldshading.com"
		)
		self.assertEqual(
			kwargs["cc"],
			"hussainaljad@worldshading.com, accounts@example.com"
		)


if __name__ == "__main__":
	unittest.main()
