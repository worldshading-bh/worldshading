frappe.listview_settings['Material Request'] = {
	add_fields: ["material_request_type", "status", "per_ordered", "per_received"],
	get_indicator: function(doc) {
		var precision = frappe.defaults.get_default("float_precision");
		if (doc.status == "Stopped") {
			return [__("Stopped"), "red", "status,=,Stopped"];
		} else if (doc.docstatus == 1 && flt(doc.per_ordered, precision) == 0) {
			return [__("Pending"), "orange", "per_ordered,=,0"];
		}

		// ✅ Production Type
		else if (doc.docstatus == 1 && doc.material_request_type == "Production" && flt(doc.per_ordered, precision) < 100) {
			return [__("Partially Produced"), "yellow", "material_request_type,=,Production"];
		} else if (doc.docstatus == 1 && doc.material_request_type == "Production" && flt(doc.per_ordered, precision) == 100) {
			return [__("Produced"), "green", "material_request_type,=,Production"];
		}

		// ✅ Repack Type
		else if (doc.docstatus == 1 && doc.material_request_type == "Repack" && flt(doc.per_ordered, precision) < 100) {
			return [__("Partially Repacked"), "yellow", "material_request_type,=,Repack"];
		} else if (doc.docstatus == 1 && doc.material_request_type == "Repack" && flt(doc.per_ordered, precision) == 100) {
			return [__("Repacked"), "green", "material_request_type,=,Repack"];
		}

		// 🛒 Default logic for other types
		else if (doc.docstatus == 1 && flt(doc.per_ordered, precision) < 100) {
			return [__("Partially Ordered"), "yellow", "per_ordered,<,100"];
		} else if (doc.docstatus == 1 && flt(doc.per_ordered, precision) == 100) {
			if (doc.material_request_type == "Purchase" && flt(doc.per_received, precision) < 100 && flt(doc.per_received, precision) > 0) {
				return [__("Partially Received"), "yellow", "per_received,<,100"];
			} else if (doc.material_request_type == "Purchase" && flt(doc.per_received, precision) == 100) {
				return [__("Received"), "green", "per_received,=,100"];
			} else if (doc.material_request_type == "Purchase") {
				return [__("Ordered"), "green", "per_ordered,=,100"];
			} else if (doc.material_request_type == "Material Transfer") {
				return [__("Transferred"), "green", "per_ordered,=,100"];
			} else if (doc.material_request_type == "Material Issue") {
				return [__("Issued"), "green", "per_ordered,=,100"];
			} else if (doc.material_request_type == "Customer Provided") {
				return [__("Received"), "green", "per_ordered,=,100"];
			} else if (doc.material_request_type == "Manufacture") {
				return [__("Manufactured"), "green", "per_ordered,=,100"];
			}
		}
	}
};
