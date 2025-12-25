import frappe, json

@frappe.whitelist()
def declare_lost_custom(quotation, lost_reasons_list=None, detailed_reason=None):
    """Duplicate of ERPNext declare_enquiry_lost, but whitelisted for workflow popup"""
    doc = frappe.get_doc("Quotation", quotation)

    # Decode JSON if it's a string
    if isinstance(lost_reasons_list, str):
        try:
            lost_reasons_list = json.loads(lost_reasons_list)
        except Exception:
            lost_reasons_list = []

    if not doc.has_sales_order():
        # Update status
        doc.db_set('status', 'Lost')

        # Save detailed reason
        if detailed_reason:
            doc.db_set('order_lost_reason', detailed_reason)

        # Save lost reasons (child table)
        lost_reasons_list = lost_reasons_list or []
        for reason in lost_reasons_list:
            if isinstance(reason, dict) and reason.get("lost_reason"):
                doc.append("lost_reasons", {"lost_reason": reason["lost_reason"]})
            elif isinstance(reason, str):
                doc.append("lost_reasons", {"lost_reason": reason})

        # Update linked docs
        doc.update_opportunity()
        doc.update_lead()

        doc.save(ignore_permissions=True)

        # Build reason text for comment
        reason_text = ", ".join(
            [r.get("lost_reason") if isinstance(r, dict) else str(r) for r in lost_reasons_list]
        )

        # Add timeline comment
        frappe.get_doc({
            "doctype": "Comment",
            "comment_type": "Comment",
            "reference_doctype": "Quotation",
            "reference_name": doc.name,
            "content": f"❌ Quotation marked as Lost<br>"
                       f"📄 Reason(s): {reason_text}<br>"
                       f"{'📝 Detail: ' + detailed_reason if detailed_reason else ''}"
        }).insert(ignore_permissions=True)

        return True

    else:
        frappe.throw("Cannot set as Lost because a Sales Order already exists.")
