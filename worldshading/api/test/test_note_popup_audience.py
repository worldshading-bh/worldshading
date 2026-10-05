from __future__ import unicode_literals

import unittest
from unittest.mock import patch

import frappe


class TestNotePopupAudience(unittest.TestCase):

	def test_filters_only_popup_notes_by_any_selected_role(self):
		from worldshading.api import note_popup_audience as audience
		boot = frappe._dict(notes=[frappe._dict(name=name) for name in ['Public', 'Sales', 'Managers', 'Either']])
		rows = [frappe._dict(parent=name, role=role) for name, role in [
			('Sales', 'Salesman'), ('Managers', 'Sales Manager'),
			('Either', 'Accounts User'), ('Either', 'Salesman')]]
		with patch.object(frappe, 'get_all', return_value=rows) as query:
			with patch.object(frappe, 'get_roles', return_value=['Salesman', 'All']):
				audience.filter_note_popups(boot)
		self.assertEqual([note.name for note in boot.notes], ['Public', 'Sales', 'Either'])
		self.assertEqual(query.call_args[1]['filters']['parenttype'], 'Note')
		self.assertEqual(query.call_args[1]['filters']['parentfield'], 'custom_popup_audience_roles')

	def test_unconfigured_notes_remain_visible(self):
		from worldshading.api import note_popup_audience as audience
		boot = frappe._dict(notes=[frappe._dict(name='Manual Note')])
		with patch.object(frappe, 'get_all', return_value=[]):
			with patch.object(frappe, 'get_roles', return_value=['Accounts User']):
				audience.filter_note_popups(boot)
		self.assertEqual([note.name for note in boot.notes], ['Manual Note'])

	def test_empty_boot_does_not_query(self):
		from worldshading.api import note_popup_audience as audience
		boot = frappe._dict(notes=[])
		with patch.object(frappe, 'get_all') as query:
			audience.filter_note_popups(boot)
		query.assert_not_called()

	def test_blank_selected_role_does_not_broadcast_restricted_note(self):
		from worldshading.api import note_popup_audience as audience
		boot = frappe._dict(notes=[frappe._dict(name='Restricted')])
		with patch.object(frappe, 'get_all', return_value=[frappe._dict(parent='Restricted', role='')]):
			with patch.object(frappe, 'get_roles', return_value=['Salesman']):
				audience.filter_note_popups(boot)
		self.assertEqual(boot.notes, [])
