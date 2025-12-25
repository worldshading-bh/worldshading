from __future__ import unicode_literals
__version__ = '0.0.1'


# worldshading/__init__.py

# def _patch_packed_item_make():
#     try:
#         # 1) Import the core module that defines make_packing_list
#         from erpnext.stock.doctype.packed_item import packed_item as core_module

#         # 2) Keep a handle to the original (handy for fallback)
#         if not hasattr(core_module, "_original_make_packing_list"):
#             core_module._original_make_packing_list = core_module.make_packing_list

#         # 3) Import your custom function
#         from .overrides.packed_item import make_packing_list as custom_make

#         # 4) Swap the reference
#         core_module.make_packing_list = custom_make

#     except Exception as e:
#         # Fail-safe: never break boot; you’ll see this in logs
#         import frappe
#         frappe.log_error(f"Worldshading patch failed: {e}", "worldshading _patch_packed_item_make")

# # Run the patch on app import
# _patch_packed_item_make()
