from __future__ import print_function

import json
from datetime import datetime

import config


_frappe_ready = False
_pushed_linkedids = set()


def handle_business_event(event):
    """Prototype ERP client: print clean business events only."""
    event_type = event.get("type")

    print("")
    print("[{0}] [{1}]".format(_now(), event_type))

    if event_type == "CALL_CREATED":
        print("  LinkedID : {0}".format(event.get("linkedid")))
        print("  Caller   : {0}".format(event.get("caller") or "Unknown"))

    elif event_type == "POPUP_CANDIDATE":
        print("  LinkedID : {0}".format(event.get("linkedid")))
        print("  Caller   : {0}".format(event.get("caller") or "Unknown"))
        print("  Extension: {0}".format(event.get("extension")))
        print("  Queue No.: {0}".format(event.get("queue_number") or ""))
        print("  Queue    : {0}".format(event.get("queue_name") or ""))
        publish_incoming_call(event)

    elif event_type == "CALL_ANSWERED":
        print("  LinkedID : {0}".format(event.get("linkedid")))
        print("  Caller   : {0}".format(event.get("caller") or "Unknown"))
        print("  Answered : {0}".format(event.get("answered_extension") or ""))

    elif event_type == "CALL_ENDED":
        print("  LinkedID : {0}".format(event.get("linkedid")))
        print("  Caller   : {0}".format(event.get("caller") or "Unknown"))
        print("  Queue No.: {0}".format(event.get("queue_number") or ""))
        print("  Queue    : {0}".format(event.get("queue_name") or ""))
        print("  Ringing  : {0}".format(", ".join(event.get("ringing_extensions") or [])))
        print("  Answered : {0}".format(event.get("answered_extension") or ""))
        print("  Status   : {0}".format(event.get("status") or ""))


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def publish_incoming_call(event):
    """Send minimal realtime event to one ERPNext user for prototype testing."""
    if not config.REALTIME_ENABLED:
        return

    caller = str(event.get("caller") or "").strip()
    if not caller or caller.lower() == "unknown":
        print("  Realtime: skipped non-customer/internal call")
        return

    linkedid = event.get("linkedid")
    if config.REALTIME_DEDUP_PER_CALL and linkedid in _pushed_linkedids:
        print("  Realtime: skipped duplicate popup for this call")
        return

    try:
        _ensure_frappe()

        import frappe

        caller_info = safe_lookup_caller(event.get("caller"))

        message = {
            "linkedid": event.get("linkedid"),
            "caller": event.get("caller"),
            "extension": event.get("extension"),
            "queue_number": event.get("queue_number"),
            "queue_name": event.get("queue_name"),
            "event_time": _now(),
            "caller_info": caller_info,
        }

        frappe.publish_realtime(
            config.REALTIME_EVENT_NAME,
            message=message,
            user=config.REALTIME_TEST_USER,
        )

        if config.REALTIME_EVAL_JS_ENABLED:
            # Temporary visible test for ERPNext v12 Desk. The browser already
            # listens for eval_js, so this confirms websocket delivery even if
            # the custom JS include has not refreshed yet.
            frappe.publish_realtime(
                "eval_js",
                message=_build_test_popup_js(message),
                user=config.REALTIME_TEST_USER,
            )

        print("  Realtime: pushed to {0}".format(config.REALTIME_TEST_USER))
        if config.REALTIME_DEDUP_PER_CALL and linkedid:
            _pushed_linkedids.add(linkedid)
        _print_lookup_summary(caller_info)

    except BaseException as exc:
        if isinstance(exc, ImportError) and "frappe" in str(exc):
            print("  Realtime: failed - run with bench Python:")
            print("            /home/erpadmin/frappe-bench/env/bin/python listener.py")
        elif isinstance(exc, SystemExit):
            print("  Realtime: failed - could not initialize ERP site {0}".format(
                config.ERP_SITE
            ))
            print("            sites path: {0}".format(config.SITES_PATH))
        else:
            print("  Realtime: failed - {0}".format(exc))


def _ensure_frappe():
    global _frappe_ready

    if _frappe_ready:
        return

    import frappe

    frappe.init(site=config.ERP_SITE, sites_path=config.SITES_PATH)
    frappe.connect()
    _frappe_ready = True


def lookup_caller(caller):
    """Read-only ERP lookup for caller number."""
    import frappe

    variants = get_phone_variants(caller)
    result = {
        "matched": False,
        "match_type": "",
        "display_name": "",
        "doctype": "",
        "name": "",
        "customer": "",
        "customer_name": "",
        "contact": "",
        "lead": "",
        "phone": caller or "",
        "phone_variants": variants,
        "last_quotation": None,
        "last_sales_order": None,
        "last_sales_invoice": None,
    }

    customer = _find_customer_by_phone(frappe, variants)
    if customer:
        result.update({
            "matched": True,
            "match_type": "Customer",
            "doctype": "Customer",
            "name": customer.get("name"),
            "customer": customer.get("name"),
            "customer_name": customer.get("customer_name"),
            "display_name": customer.get("customer_name") or customer.get("name"),
        })
        return result

    contact = _find_contact_by_phone(frappe, variants)
    if contact:
        result.update({
            "matched": True,
            "match_type": "Contact",
            "doctype": "Contact",
            "name": contact.get("name"),
            "contact": contact.get("name"),
            "display_name": contact.get("full_name") or contact.get("name"),
        })

        linked_customer = _find_customer_for_contact(frappe, contact.get("name"))
        if linked_customer:
            result.update({
                "customer": linked_customer.get("name"),
                "customer_name": linked_customer.get("customer_name"),
                "display_name": linked_customer.get("customer_name") or result.get("display_name"),
            })

        return result

    lead = _find_lead_by_phone(frappe, variants)
    if lead:
        result.update({
            "matched": True,
            "match_type": "Lead",
            "doctype": "Lead",
            "name": lead.get("name"),
            "lead": lead.get("name"),
            "display_name": lead.get("lead_name") or lead.get("company_name") or lead.get("name"),
        })
        return result

    return result


def safe_lookup_caller(caller):
    try:
        return lookup_caller(caller)
    except Exception as exc:
        print("  Lookup  : failed - {0}".format(exc))
        return {
            "matched": False,
            "match_type": "",
            "display_name": "",
            "doctype": "",
            "name": "",
            "customer": "",
            "customer_name": "",
            "contact": "",
            "lead": "",
            "phone": caller or "",
            "phone_variants": get_phone_variants(caller),
            "last_quotation": None,
            "last_sales_order": None,
            "last_sales_invoice": None,
        }


def get_phone_variants(number):
    digits = "".join([ch for ch in str(number or "") if ch.isdigit()])
    variants = []

    def add(value):
        value = str(value or "").strip()
        if value and value not in variants:
            variants.append(value)

    add(digits)

    if digits.startswith("00"):
        without_00 = digits[2:]
        add(without_00)
        add("+" + without_00)
    else:
        add("00" + digits)
        add("+" + digits)

    if digits.startswith("973") and len(digits) == 11:
        local = digits[-8:]
        add(local)
        add("00973" + local)
        add("973" + local)
        add("+973" + local)

    if digits.startswith("00973") and len(digits) == 13:
        local = digits[-8:]
        add(local)
        add("973" + local)
        add("+973" + local)

    if len(digits) == 8:
        add("973" + digits)
        add("00973" + digits)
        add("+973" + digits)

    return variants


def _find_customer_by_phone(frappe, variants):
    filters = _or_filters("Customer", ["mobile_no"], variants)
    if not filters:
        return None

    rows = frappe.get_all(
        "Customer",
        fields=["name", "customer_name", "mobile_no", "disabled"],
        filters={"disabled": 0},
        or_filters=filters,
        limit_page_length=1,
    )
    return rows[0] if rows else None


def _find_contact_by_phone(frappe, variants):
    filters = _or_filters("Contact", ["phone", "mobile_no"], variants)
    rows = frappe.get_all(
        "Contact",
        fields=["name", "first_name", "middle_name", "last_name", "phone", "mobile_no"],
        or_filters=filters,
        limit_page_length=1,
    ) if filters else []

    if rows:
        contact = rows[0]
        contact["full_name"] = " ".join([
            contact.get("first_name") or "",
            contact.get("middle_name") or "",
            contact.get("last_name") or "",
        ]).strip()
        return contact

    phone_rows = frappe.get_all(
        "Contact Phone",
        fields=["parent", "phone"],
        filters={"phone": ["in", variants]},
        limit_page_length=1,
    )

    if not phone_rows:
        return None

    contact_rows = frappe.get_all(
        "Contact",
        fields=["name", "first_name", "middle_name", "last_name", "phone", "mobile_no"],
        filters={"name": phone_rows[0].get("parent")},
        limit_page_length=1,
    )

    if not contact_rows:
        return None

    contact = contact_rows[0]
    contact["full_name"] = " ".join([
        contact.get("first_name") or "",
        contact.get("middle_name") or "",
        contact.get("last_name") or "",
    ]).strip()
    return contact


def _find_customer_for_contact(frappe, contact_name):
    if not contact_name:
        return None

    links = frappe.get_all(
        "Dynamic Link",
        fields=["link_name"],
        filters={
            "parenttype": "Contact",
            "parent": contact_name,
            "link_doctype": "Customer",
        },
        limit_page_length=1,
    )

    if not links:
        return None

    customers = frappe.get_all(
        "Customer",
        fields=["name", "customer_name"],
        filters={"name": links[0].get("link_name")},
        limit_page_length=1,
    )
    return customers[0] if customers else None


def _find_lead_by_phone(frappe, variants):
    filters = _or_filters("Lead", ["phone", "mobile_no"], variants)
    if not filters:
        return None

    rows = frappe.get_all(
        "Lead",
        fields=["name", "lead_name", "company_name", "status", "phone", "mobile_no"],
        or_filters=filters,
        limit_page_length=1,
    )
    return rows[0] if rows else None


def _add_last_customer_documents(frappe, result):
    customer = result.get("customer")
    if not customer:
        return

    result["last_quotation"] = _get_last_doc(
        frappe,
        "Quotation",
        {"party_name": customer, "quotation_to": "Customer"},
        ["name", "status", "transaction_date", "grand_total"],
        "transaction_date desc, creation desc",
    )
    result["last_sales_order"] = _get_last_doc(
        frappe,
        "Sales Order",
        {"customer": customer},
        ["name", "status", "transaction_date", "grand_total"],
        "transaction_date desc, creation desc",
    )
    result["last_sales_invoice"] = _get_last_doc(
        frappe,
        "Sales Invoice",
        {"customer": customer},
        ["name", "status", "posting_date", "grand_total", "outstanding_amount"],
        "posting_date desc, creation desc",
    )


def _get_last_doc(frappe, doctype, filters, fields, order_by):
    rows = frappe.get_all(
        doctype,
        fields=fields,
        filters=filters,
        order_by=order_by,
        limit_page_length=1,
    )
    return rows[0] if rows else None


def _or_filters(doctype, fields, variants):
    filters = []
    for fieldname in fields:
        for value in variants:
            filters.append([doctype, fieldname, "=", value])
    return filters


def _print_lookup_summary(caller_info):
    if not caller_info:
        return

    if caller_info.get("matched"):
        print("  Match   : {0} - {1}".format(
            caller_info.get("match_type"),
            caller_info.get("display_name") or caller_info.get("name"),
        ))
    else:
        print("  Match   : Unknown caller")



def _build_test_popup_js(message):
    caller = json.dumps(message.get("caller") or "Unknown")
    extension = json.dumps(message.get("extension") or "")
    linkedid = json.dumps(message.get("linkedid") or "")
    caller_info = message.get("caller_info") or {}
    display_name = json.dumps(caller_info.get("display_name") or "")
    match_type = json.dumps(caller_info.get("match_type") or "Unknown")
    customer = json.dumps(caller_info.get("customer") or "")
    contact = json.dumps(caller_info.get("contact") or "")
    lead = json.dumps(caller_info.get("lead") or "")

    return """
var open_call_assistant = function() {
    frappe.route_options = {
        caller: %s,
        linkedid: %s,
        extension: %s,
        customer: %s,
        contact: %s,
        lead: %s
    };
    frappe.set_route("call-assistant");
};
var esc = function(value) {
    return $("<div>").text(value || "").html();
};
if (!$("#ws-call-toast-style").length) {
    $("head").append("<style id='ws-call-toast-style'>"
        + ".ws-call-toast-wrap{position:fixed;right:18px;bottom:18px;z-index:1050;width:340px;max-width:calc(100vw - 36px);}"
        + ".ws-call-toast{display:flex;gap:12px;background:#fff;border:1px solid #e2e8f0;border-radius:8px;box-shadow:0 10px 28px rgba(15,23,42,.18);padding:12px;margin-top:10px;}"
        + ".ws-call-toast-icon{width:34px;height:34px;border-radius:50%%;background:#fff4e0;color:#b76e00;display:flex;align-items:center;justify-content:center;font-size:17px;flex:0 0 auto;}"
        + ".ws-call-toast-main{min-width:0;flex:1;}"
        + ".ws-call-toast-head{display:flex;justify-content:space-between;gap:10px;align-items:flex-start;margin-bottom:3px;}"
        + ".ws-call-toast-title{font-weight:600;font-size:14px;color:#1f2937;}"
        + ".ws-call-toast-close{border:0;background:transparent;color:#94a3b8;font-size:18px;line-height:1;padding:0 2px;}"
        + ".ws-call-toast-body{font-size:12px;color:#64748b;line-height:1.45;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}"
        + ".ws-call-toast-actions{margin-top:8px;}"
        + ".ws-call-toast-actions .btn{padding:3px 9px;font-size:12px;}"
        + "</style>");
}
var wrap = $("#ws-call-toast-wrap");
if (!wrap.length) {
    wrap = $("<div id='ws-call-toast-wrap' class='ws-call-toast-wrap'></div>").appendTo("body");
}
var card = $("<div class='ws-call-toast'></div>");
card.html(
    "<div class='ws-call-toast-icon'>☎</div>"
    + "<div class='ws-call-toast-main'>"
        + "<div class='ws-call-toast-head'>"
            + "<div class='ws-call-toast-title'>Incoming Call</div>"
            + "<button class='ws-call-toast-close js-close-call-toast'>×</button>"
        + "</div>"
        + "<div class='ws-call-toast-body'>"
            + esc(%s || %s)
            + " · " + esc(%s)
            + (%s ? " · Ext " + esc(%s) : "")
            + "<br>"
            + esc(%s || %s || "Unknown")
        + "</div>"
        + "<div class='ws-call-toast-actions'>"
            + "<button class='btn btn-primary btn-sm js-open-call-assistant'>Open</button>"
        + "</div>"
    + "</div>"
);
card.find(".js-open-call-assistant").on("click", open_call_assistant);
card.find(".js-close-call-toast").on("click", function() {
    card.remove();
});
wrap.prepend(card);
""" % (
        caller,
        linkedid,
        extension,
        customer,
        contact,
        lead,
        display_name,
        caller,
        caller,
        extension,
        extension,
        customer,
        match_type,
    )
