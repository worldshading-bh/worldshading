from erpnext.controllers.status_updater import StatusUpdater, status_map
from frappe.utils import getdate, nowdate
import frappe

# 🧩 Custom extended status map
custom_status_map = status_map.copy()

# ✅ Insert custom status before Partially Ordered to take precedence
custom_status_map["Material Request"].insert(4, [
    "Stock Entry In Progress",
    """eval:self.status != 'Stopped' and self.docstatus == 1 and self.per_ordered == 0 and self.material_request_type in ('Repack', 'Production') and get_value('Stock Entry Detail', {'material_request': self.name, 'docstatus': 0}, 'name')"""
])



# ✅ Append additional custom states
custom_status_map["Material Request"].extend([
    ["Repacked", "eval:self.status != 'Stopped' and self.per_ordered == 100 and self.docstatus == 1 and self.material_request_type == 'Repack'"],
    ["Partially Repacked", "eval:self.status != 'Stopped' and self.per_ordered < 100 and self.per_ordered > 0 and self.docstatus == 1 and self.material_request_type == 'Repack'"],
    ["Produced", "eval:self.status != 'Stopped' and self.per_ordered == 100 and self.docstatus == 1 and self.material_request_type == 'Production'"],
    ["Partially Produced", "eval:self.status != 'Stopped' and self.per_ordered < 100 and self.per_ordered > 0 and self.docstatus == 1 and self.material_request_type == 'Production'"]
])

class CustomStatusUpdater(StatusUpdater):
    def set_status(self, update=False, status=None, update_modified=True):
        if self.is_new():
            if self.get('amended_from'):
                self.status = 'Draft'
            return

        # use extended map only for Material Request
        map_to_use = custom_status_map if self.doctype == "Material Request" else status_map

        if self.doctype in map_to_use:
            _status = self.status
            if status and update:
                self.db_set("status", status)

            sl = map_to_use[self.doctype][:]
            sl.reverse()
            for s in sl:
                if not s[1]:
                    self.status = s[0]
                    break
                elif s[1].startswith("eval:"):
                    if frappe.safe_eval(s[1][5:], None, {
                        "self": self.as_dict(),
                        "getdate": getdate,
                        "nowdate": nowdate,
                        "get_value": frappe.db.get_value,
                        "frappe": frappe
                    }):
                        self.status = s[0]
                        break
                elif getattr(self, s[1])():
                    self.status = s[0]
                    break

            if self.status != _status and self.status not in (
                "Cancelled", "Partially Ordered", "Ordered", "Issued", "Transferred"
            ):
                self.add_comment("Label", frappe._(self.status))

            if update:
                self.db_set('status', self.status, update_modified=update_modified)
