# -*- coding: utf-8 -*-
# Copyright (c) 2026, Hilal Habeeb and Contributors
# See license.txt
from __future__ import unicode_literals

import unittest
from unittest.mock import MagicMock, patch

from worldshading.worldshading.doctype.commission_payout import commission_payout

class TestCommissionPayout(unittest.TestCase):
	def test_journal_entry_permission_uses_document_permissions_not_role_names(self):
		payout = MagicMock()

		with patch.object(
			commission_payout.frappe,
			"has_permission",
			return_value=True
		) as has_permission, patch.object(
			commission_payout.frappe,
			"get_roles",
			side_effect=AssertionError("role names must not be checked")
		):
			commission_payout._validate_journal_entry_permissions(payout)

		payout.check_permission.assert_called_once_with("read")
		has_permission.assert_called_once_with(
			"Journal Entry", ptype="create", throw=True
		)
