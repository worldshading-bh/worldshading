def apply():
    import frappe

    # ✅ Log once per boot (verified)
    frappe.logger("worldshading").info("WorldShading core overrides applied")

    # ✅ Override make_packing_list
    import erpnext.stock.doctype.packed_item.packed_item as original
    from worldshading.overrides.packed_item import make_packing_list
    original.make_packing_list = make_packing_list

    # ✅ Override StatusUpdater
    from erpnext.controllers import status_updater
    from worldshading.overrides.custom_status_updater import CustomStatusUpdater
    status_updater.StatusUpdater = CustomStatusUpdater
