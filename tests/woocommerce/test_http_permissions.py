import types
import unittest
from adapter_support import adapter


class HttpPermissionTests(unittest.TestCase):
    def test_connector_transaction_uses_read_committed_after_boundary(self):
        with adapter('common') as (module,frappe,unused,orders):
            events=[]
            frappe.db.commit.side_effect=lambda:events.append('commit')
            frappe.db.sql.side_effect=lambda query:events.append(query)
            module.start_operation()
            self.assertEqual(events,['commit','SET SESSION TRANSACTION ISOLATION LEVEL READ COMMITTED'])

    def test_mutating_actions_reject_get_but_allow_post_and_internal_calls(self):
        with adapter('common') as (module,frappe,unused,orders):
            frappe.get_roles=lambda:['System Manager']
            frappe.local=types.SimpleNamespace(request=types.SimpleNamespace(method='GET'))
            with self.assertRaises(PermissionError):module.manager_only(write=True)
            module.manager_only()
            frappe.local.request.method='POST';module.manager_only(write=True)
            frappe.local.request=None;module.manager_only(write=True)

    def test_post_does_not_bypass_manager_role(self):
        with adapter('common') as (module,frappe,unused,orders):
            frappe.get_roles=lambda:['Sales User']
            frappe.local=types.SimpleNamespace(request=types.SimpleNamespace(method='POST'))
            with self.assertRaises(PermissionError):module.manager_only(write=True)
