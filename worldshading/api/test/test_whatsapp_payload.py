from __future__ import unicode_literals

import unittest

from worldshading.api.whatsapp import (
    build_template_payload,
    get_meta_template_data,
    get_meta_url_buttons
)


class FakeResponse(object):
    def __init__(self, data):
        self.status_code = 200
        self.text = ""
        self.data = data

    def json(self):
        return self.data


class TestWhatsAppTemplatePayload(unittest.TestCase):
    def test_extracts_dynamic_url_button(self):
        components = [{
            "type": "BUTTONS",
            "buttons": [{"type": "URL", "text": "Pay Now", "url": "https://pay.test/{{1}}"}]
        }]
        self.assertEqual(get_meta_url_buttons(components), [{
            "index": "0", "text": "Pay Now", "url": "https://pay.test/{{1}}", "dynamic": True
        }])

    def test_button_index_includes_non_url_buttons(self):
        components = [{
            "type": "BUTTONS",
            "buttons": [
                {"type": "QUICK_REPLY", "text": "Help"},
                {"type": "URL", "text": "Pay", "url": "https://pay.test/{{1}}"}
            ]
        }]
        self.assertEqual(get_meta_url_buttons(components)[0]["index"], "1")

    def test_fetches_all_meta_pages(self):
        responses = {
            "first": FakeResponse({"data": [{"name": "one"}], "paging": {"next": "second"}}),
            "second": FakeResponse({"data": [{"name": "two"}]})
        }
        calls = []

        def request_get(url, **kwargs):
            calls.append((url, kwargs))
            return responses[url]

        result = get_meta_template_data("first", {"Authorization": "token"}, request_get)
        self.assertEqual([row["name"] for row in result], ["one", "two"])
        self.assertEqual(calls[0][1]["params"], {"limit": 100})
        self.assertIsNone(calls[1][1]["params"])

    def test_adds_dynamic_url_button_parameter(self):
        payload = build_template_payload(
            "97312345678", "payment_request", "en_US", ["Customer"],
            button_parameters=[{"index": 0, "value": "5fc3ca92a8e98e11"}])
        self.assertEqual(payload["template"]["components"][-1], {
            "type": "button",
            "sub_type": "url",
            "index": "0",
            "parameters": [{"type": "text", "text": "5fc3ca92a8e98e11"}]
        })

    def test_existing_body_payload_is_unchanged(self):
        payload = build_template_payload("97312345678", "status", "en_US", [" A\n B "])
        self.assertEqual(payload["template"]["components"], [{
            "type": "body", "parameters": [{"type": "text", "text": "A B"}]
        }])

    def test_document_header_is_preserved(self):
        payload = build_template_payload(
            "97312345678", "invoice", "en_US", [], "media-1", "INV-1.pdf", "DOCUMENT")
        self.assertEqual(payload["template"]["components"][0], {
            "type": "header",
            "parameters": [{
                "type": "document",
                "document": {"id": "media-1", "filename": "INV-1.pdf"}
            }]
        })


if __name__ == "__main__":
    unittest.main()
