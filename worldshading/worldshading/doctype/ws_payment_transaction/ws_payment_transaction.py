# -*- coding: utf-8 -*-
"""One online payment attempt.

Intentionally almost behaviour-free. Everything is written by the gateway modules
through db_set, because most writes happen inside a callback that must finish fast,
and because the whole record is read-only to users -- it is evidence, not data entry.

See Documentation/payments/README.md.
"""
from __future__ import unicode_literals

from frappe.model.document import Document


class WSPaymentTransaction(Document):
	pass
