from __future__ import unicode_literals


def sync_signature_html(doc, method=None):
	"""Use the editable HTML source as the Email Account signature."""
	signature_html = (doc.get("signature_html") or "").strip()
	if not signature_html:
		return

	doc.signature = signature_html
	doc.add_signature = 1
