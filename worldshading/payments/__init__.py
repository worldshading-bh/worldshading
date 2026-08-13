# -*- coding: utf-8 -*-
"""Online payment gateways for World Shading.

Layout:

    crypto.py   the AES envelope BENEFIT mandates (no vendor library exists for Python)
    utils.py    money formatting, track IDs, the transaction record, settlement
    benefit.py  BENEFIT REST client
    mpgs.py     KFH MPGS client -- blocked, see the module docstring
    web.py      guest endpoints the gateways call back into

Doctypes live under the existing Worldshading module (worldshading/worldshading/doctype)
rather than a module of their own: a new Frappe module needs a Module Def record, and
`bench migrate` does not create those from modules.txt -- only `install_app` does. Not
worth the migration risk for a naming preference.

Read Documentation/payments/ before changing anything here.
"""
from __future__ import unicode_literals
