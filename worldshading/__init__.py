# from __future__ import unicode_literals
# __version__ = '0.0.1'


from __future__ import unicode_literals
__version__ = '0.0.1'

def _apply_overrides():
    from worldshading.core_overrides import apply
    apply()

try:
    import frappe
    # ✅ Only apply when site context exists
    if getattr(frappe.local, "site", None):
        _apply_overrides()
except Exception:
    # ✅ Never break bench commands
    pass
