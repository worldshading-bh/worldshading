// home/hilal/frappe-bench/apps/worldshading/worldshading/public/js/material_request.js
frappe.ui.form.on('Material Request', {
  setup: function (frm) {
    frm.set_query('pb_to_warehouse', function () {
      return {
        filters: {
          company: frm.doc.company,
          is_group: 0,
        },
      };
    });
  },

  refresh: function (frm) {
    // 🧩 Auto-add a row to from_items if needed
    _maybe_add_from_items_row(frm);

    // Only show custom "Create Stock Entry" button for submitted repack/production MRs
    if (
      frm.doc.docstatus == 1 &&
      ["Repack", "Production"].includes(frm.doc.material_request_type) &&
      !["Transferred", "Received"].includes(frm.doc.status)
    ) {
      frm.add_custom_button(__("Create Stock Entry"), function () {
        frappe.run_serially([
          () => {
            const stock_entry = frappe.model.get_new_doc("Stock Entry");
            stock_entry.stock_entry_type = frm.doc.material_request_type;
            stock_entry.company = frm.doc.company;
            stock_entry.naming_series = "MT.YY.-";

            // 🔵 Add Source Items from 'from_items' (custom table)
            frm.doc.from_items?.forEach(function (item) {
              const st_item = frappe.model.add_child(stock_entry, "Stock Entry Detail", "items");
              Object.assign(st_item, {
                item_code: item.item_code,
                item_name: item.item_name,
                item_group: item.item_group,
                set_basic_rate_manually: 1,
                qty: item.qty,
                transfer_qty: item.qty,
                basic_rate: item.rate,
                description: item.description,
                uom: item.uom,
                stock_uom: item.stock_uom,
                conversion_factor: item.conversion_factor,
                s_warehouse: item.s_warehouse || item.warehouse,
                t_warehouse: null,
                actual_qty: item.actual_qty,
                cost_center: item.cost_center,
                transferred_qty: item.qty,
                material_request: frm.doc.name,
                material_request_item: item.name
              });
            });

            // 🟢 Add Target Items from core 'items' table
            frm.doc.items.forEach(function (item) {
              const st_item = frappe.model.add_child(stock_entry, "Stock Entry Detail", "items");
              Object.assign(st_item, {
                item_code: item.item_code,
                item_name: item.item_name,
                item_group: item.item_group,
                set_basic_rate_manually: 1,
                qty: item.qty,
                transfer_qty: item.qty,
                basic_rate: item.rate,
                description: item.description,
                uom: item.uom,
                stock_uom: item.stock_uom,
                conversion_factor: item.conversion_factor,
                s_warehouse: null,
                t_warehouse: item.t_warehouse || item.warehouse,
                actual_qty: item.actual_qty,
                cost_center: item.cost_center,
                transferred_qty: item.qty,
                material_request: frm.doc.name,
                material_request_item: item.name,
                is_finished_item: 1 // ✅ Important flag
              });
            });

            frappe.set_route("Form", "Stock Entry", stock_entry.name);
          }
        ]);
      }).css({
        color: "white",
        backgroundColor: "#5E64FF",
        borderColor: "#444bff",
        fontWeight: "500"
      });
    }

    _make_custom_buttons(frm);
  },

  material_request_type: function (frm) {
    // 🧩 Auto-add a row when switching type to Repack/Production
    _maybe_add_from_items_row(frm);
  },

  pb_to_warehouse: function (frm) {
    _set_items_warehouse(frm);
  },

  validate: function (frm) {
    const req_date = frm.doc.schedule_date;

    // ✅ On Save: Sync schedule_date from main form into all 'items' rows
    frm.doc.items.forEach(item => {
      item.schedule_date = req_date;
    });

    // ✅ On Save: Sync schedule_date from main form into all 'from_items' rows
    if (frm.doc.from_items) {
      frm.doc.from_items.forEach(item => {
        item.schedule_date = req_date;
      });
    }
  }
});

// 📦 Update warehouses in both 'items' and 'from_items' tables
function _set_items_warehouse(frm) {
  // Update 'items' (target)
  frm.doc.items.forEach((item) => {
    frappe.model.set_value(item.doctype, item.name, 'warehouse', frm.doc.pb_to_warehouse);
  });

  // Update 'from_items' (source)
  frm.doc.from_items?.forEach((item) => {
    frappe.model.set_value(item.doctype, item.name, 'warehouse', frm.doc.pb_to_warehouse);
    frappe.model.set_value(item.doctype, item.name, 's_warehouse', frm.doc.pb_to_warehouse);
  });
}

// 🧩 Auto-add a blank row to 'from_items' only for Repack / Production
function _maybe_add_from_items_row(frm) {
  if (["Repack", "Production"].includes(frm.doc.material_request_type)) {
    if (!frm.doc.from_items || frm.doc.from_items.length === 0) {
      frappe.model.add_child(frm.doc, "Material Request Item", "from_items");
      frm.refresh_field("from_items");
    }
  }
}
