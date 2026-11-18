"""Exercise the versioned safe-exec script without connecting to a site."""
import json
import unittest
from pathlib import Path
from types import SimpleNamespace

from RestrictedPython import compile_restricted
from RestrictedPython.Guards import safe_builtins
import frappe
from frappe.model.workflow import has_approval_access


class Doc(frappe._dict):
    def get_doc_before_save(self):
        return self.get('_previous')


class TestSecurityReissue(unittest.TestCase):
    def test_original_maker_can_send_replacement_to_checker(self):
        definitions = json.loads((Path(__file__).parents[1] / 'fixtures/workflow.json').read_text())
        workflow = next(r for r in definitions if r['name'] == 'Payment Entry')
        transition = next(r for r in workflow['transitions'] if r['action'] == 'Submit Security Cheque')
        self.assertTrue(has_approval_access('maker', Doc(owner='maker'), transition))

    def test_finance_can_void_own_document_like_existing_cancellation_policy(self):
        definitions = json.loads((Path(__file__).parents[1] / 'fixtures/workflow.json').read_text())
        for workflow in definitions:
            for transition in workflow['transitions']:
                if transition['action'] == 'Void Cheque':
                    self.assertTrue(has_approval_access('finance', Doc(owner='finance'), transition))

    def execute(self, doc, files=None):
        definitions = json.loads((Path(__file__).parents[1] / 'fixtures/server_script.json').read_text())
        script = next(r['script'] for r in definitions if r['name'] == 'Payment Entry Security Cheque Validation')
        def get_all(dt, filters, **kwargs):
            assert dt == 'File'
            rows = files or []
            after = filters.get('creation', [None, None])[1]
            return [r for r in rows if not after or r['creation'] >= after]
        facade = SimpleNamespace(ValidationError=ValueError,
            utils=SimpleNamespace(cint=lambda value: int(value or 0)), get_all=get_all,
            get_doc=lambda dt, name: Doc(signature_confirmed_on='2026-11-18 12:00:00'))
        namespace = {'__builtins__': safe_builtins, '_getattr_': getattr,
                     '_write_': lambda obj: obj, '_getitem_': lambda obj, key: obj[key],
                     'frappe': facade, 'doc': doc}
        exec(compile_restricted(script, '<security-cheque>', 'exec'), namespace)

    def test_void_returns_to_security_preparation_without_submission(self):
        doc = Doc(workflow_state='Prepare Security Cheque', docstatus=0, mode_of_payment='Cheque',
                  is_security_cheque=1, _previous=Doc(workflow_state='Security Cheque Issued'))
        self.execute(doc)
        self.assertEqual((doc.is_security_cheque, doc.docstatus), (1, 0))

    def test_security_reissue_cannot_escape_into_ordinary_workflow(self):
        doc = Doc(workflow_state='Draft', docstatus=0, mode_of_payment='Cheque',
                  is_security_cheque=1, _previous=Doc(workflow_state='Security Cheque Issued'))
        with self.assertRaises(ValueError):
            self.execute(doc)

    def test_old_attachment_cannot_authorize_new_cheque_handover(self):
        doc = Doc(name='PE-1', workflow_state='Security Cheque Issued', docstatus=0,
                  mode_of_payment='Cheque', is_security_cheque=1, cheque_leaf='CL-2')
        with self.assertRaises(ValueError):
            self.execute(doc, [{'name': 'OLD', 'creation': '2026-11-18 11:00:00'}])
        self.execute(doc, [{'name': 'NEW', 'creation': '2026-11-18 12:10:00'}])


if __name__ == '__main__':
    unittest.main()
