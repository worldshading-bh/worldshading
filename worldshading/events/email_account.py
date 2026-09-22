from __future__ import unicode_literals

import re

from frappe.utils import validate_email_address


def sync_signature_html(doc, method=None):
	"""Normalize composer settings and sync the editable account signature."""
	default_cc = doc.get("custom_default_cc") or ""
	addresses = []
	seen = set()
	for address in re.split(r"[,;\n\r]+", default_cc):
		address = address.strip()
		if not address:
			continue
		address = validate_email_address(address, throw=True)
		if address.lower() not in seen:
			seen.add(address.lower())
			addresses.append(address)
	doc.custom_default_cc = ", ".join(addresses)

	signature_html = (doc.get("signature_html") or "").strip()
	if not signature_html:
		return

	doc.signature = signature_html
	doc.add_signature = 1
