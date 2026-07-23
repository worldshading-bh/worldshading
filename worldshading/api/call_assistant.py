# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import frappe


@frappe.whitelist()
def get_call_context(caller=None, linkedid=None, extension=None, customer=None, contact=None, lead=None):
    caller_info = lookup_caller(caller, customer=customer, contact=contact, lead=lead)
    customer_name = caller_info.get("customer")

    data = {
        "caller": caller,
        "linkedid": linkedid,
        "extension": extension,
        "caller_info": caller_info,
        "customer_profile": {},
        "contacts": [],
        "open_service_visits": [],
        "recent_quotations": [],
        "recent_sales_orders": [],
        "recent_sales_invoices": [],
        "outstanding": {
            "amount": 0,
            "invoices": []
        },
        "call_history": [],
    }

    if customer_name:
        data["customer_profile"] = get_customer_profile(customer_name)
        data["contacts"] = get_customer_contacts(customer_name)
        data["open_service_visits"] = get_open_service_visits(customer_name)
        data["recent_quotations"] = get_recent_quotations(customer_name)
        data["recent_sales_orders"] = get_recent_sales_orders(customer_name)
        data["recent_sales_invoices"] = get_recent_sales_invoices(customer_name)
        data["outstanding"] = get_outstanding(customer_name)

    data["call_history"] = get_call_history(caller, caller_info)

    return data


def lookup_caller(caller, customer=None, contact=None, lead=None):
    variants = get_phone_variants(caller)
    result = _empty_caller_result(caller, variants)

    if customer:
        row = _get_customer(customer)
        if row:
            result.update({
                "matched": 1,
                "match_type": "Customer",
                "doctype": "Customer",
                "name": row.get("name"),
                "customer": row.get("name"),
                "customer_name": row.get("customer_name"),
                "display_name": row.get("customer_name") or row.get("name"),
            })
            return result

    if contact:
        row = _get_contact(contact)
        if row:
            _apply_contact_result(result, row)
            linked_customer = _find_customer_for_contact(row.get("name"))
            if linked_customer:
                _apply_customer_link(result, linked_customer)
            return result

    if lead:
        row = _get_lead(lead)
        if row:
            _apply_lead_result(result, row)
            return result

    row = _find_customer_by_phone(variants)
    if row:
        result.update({
            "matched": 1,
            "match_type": "Customer",
            "doctype": "Customer",
            "name": row.get("name"),
            "customer": row.get("name"),
            "customer_name": row.get("customer_name"),
            "display_name": row.get("customer_name") or row.get("name"),
        })
        return result

    row = _find_contact_by_phone(variants)
    if row:
        _apply_contact_result(result, row)
        linked_customer = _find_customer_for_contact(row.get("name"))
        if linked_customer:
            _apply_customer_link(result, linked_customer)
        return result

    row = _find_lead_by_phone(variants)
    if row:
        _apply_lead_result(result, row)

    return result


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


def get_customer_profile(customer):
    rows = frappe.get_all(
        "Customer",
        fields=[
            "name", "customer_name", "customer_group", "territory",
            "mobile_no", "email_id", "disabled", "customer_type"
        ],
        filters={"name": customer},
        limit_page_length=1,
    )
    return rows[0] if rows else {}


def get_customer_contacts(customer):
    links = frappe.get_all(
        "Dynamic Link",
        fields=["parent"],
        filters={
            "parenttype": "Contact",
            "link_doctype": "Customer",
            "link_name": customer,
        },
        limit_page_length=20,
    )
    names = [row.get("parent") for row in links if row.get("parent")]
    if not names:
        return []

    return frappe.get_all(
        "Contact",
        fields=["name", "first_name", "middle_name", "last_name", "phone", "mobile_no", "email_id"],
        filters={"name": ["in", names]},
        order_by="modified desc",
        limit_page_length=20,
    )


def get_open_service_visits(customer):
    filters = {"customer": customer}
    if frappe.db.has_column("Service Visit", "docstatus"):
        filters["docstatus"] = ["<", 2]

    fields = ["name", "subject", "customer_name", "mobile_number", "date", "time", "docstatus"]
    if frappe.db.has_column("Service Visit", "workflow_state"):
        fields.append("workflow_state")

    rows = frappe.get_all(
        "Service Visit",
        fields=fields,
        filters=filters,
        order_by="date desc, modified desc",
        limit_page_length=10,
    )

    return [
        row for row in rows
        if row.get("docstatus") != 2 and row.get("workflow_state") not in ("Completed", "Cancelled", "Closed")
    ]


def get_recent_quotations(customer):
    return frappe.get_all(
        "Quotation",
        fields=["name", "status", "transaction_date", "grand_total"],
        filters={"party_name": customer, "quotation_to": "Customer"},
        order_by="transaction_date desc, creation desc",
        limit_page_length=5,
    )


def get_recent_sales_orders(customer):
    return frappe.get_all(
        "Sales Order",
        fields=["name", "status", "transaction_date", "grand_total", "per_delivered", "per_billed"],
        filters={"customer": customer},
        order_by="transaction_date desc, creation desc",
        limit_page_length=5,
    )


def get_recent_sales_invoices(customer):
    return frappe.get_all(
        "Sales Invoice",
        fields=["name", "status", "posting_date", "grand_total", "outstanding_amount"],
        filters={"customer": customer},
        order_by="posting_date desc, creation desc",
        limit_page_length=5,
    )


def get_outstanding(customer):
    invoices = frappe.get_all(
        "Sales Invoice",
        fields=["name", "posting_date", "grand_total", "outstanding_amount", "status"],
        filters={
            "customer": customer,
            "docstatus": 1,
            "outstanding_amount": [">", 0],
        },
        order_by="posting_date desc, creation desc",
        limit_page_length=20,
    )

    amount = 0
    for invoice in invoices:
        amount += invoice.get("outstanding_amount") or 0

    return {
        "amount": amount,
        "invoices": invoices[:5],
    }


def get_call_history(caller, caller_info):
    variants = get_phone_variants(caller)
    conditions = []
    values = []

    for value in variants:
        conditions.append("`from` = %s")
        values.append(value)
        conditions.append("`to` = %s")
        values.append(value)

    if caller_info.get("contact"):
        conditions.append("contact = %s")
        values.append(caller_info.get("contact"))
    if caller_info.get("lead"):
        conditions.append("lead = %s")
        values.append(caller_info.get("lead"))

    if not conditions:
        return []

    # SQL is used here because ERPNext v12 Call Log has fields named "from"
    # and "to", which are reserved SQL words and are not escaped by get_all.
    return frappe.db.sql("""
        select
            id,
            `from` as from_number,
            `to` as to_number,
            status,
            duration,
            creation,
            contact,
            lead
        from `tabCall Log`
        where {conditions}
        order by creation desc
        limit 10
    """.format(conditions=" or ".join(conditions)), values, as_dict=True)


def _empty_caller_result(caller, variants):
    return {
        "matched": 0,
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
    }


def _find_customer_by_phone(variants):
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


def _find_contact_by_phone(variants):
    filters = _or_filters("Contact", ["phone", "mobile_no"], variants)
    rows = frappe.get_all(
        "Contact",
        fields=["name", "first_name", "middle_name", "last_name", "phone", "mobile_no", "email_id"],
        or_filters=filters,
        limit_page_length=1,
    ) if filters else []

    if rows:
        return rows[0]

    rows = frappe.get_all(
        "Contact Phone",
        fields=["parent", "phone"],
        filters={"phone": ["in", variants]},
        limit_page_length=1,
    )
    if not rows:
        return None

    return _get_contact(rows[0].get("parent"))


def _find_lead_by_phone(variants):
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


def _find_customer_for_contact(contact):
    if not contact:
        return None

    rows = frappe.get_all(
        "Dynamic Link",
        fields=["link_name"],
        filters={
            "parenttype": "Contact",
            "parent": contact,
            "link_doctype": "Customer",
        },
        limit_page_length=1,
    )
    if not rows:
        return None

    return _get_customer(rows[0].get("link_name"))


def _get_customer(customer):
    rows = frappe.get_all(
        "Customer",
        fields=["name", "customer_name", "mobile_no", "disabled"],
        filters={"name": customer},
        limit_page_length=1,
    )
    return rows[0] if rows else None


def _get_contact(contact):
    rows = frappe.get_all(
        "Contact",
        fields=["name", "first_name", "middle_name", "last_name", "phone", "mobile_no", "email_id"],
        filters={"name": contact},
        limit_page_length=1,
    )
    return rows[0] if rows else None


def _get_lead(lead):
    rows = frappe.get_all(
        "Lead",
        fields=["name", "lead_name", "company_name", "status", "phone", "mobile_no"],
        filters={"name": lead},
        limit_page_length=1,
    )
    return rows[0] if rows else None


def _apply_contact_result(result, contact):
    full_name = " ".join([
        contact.get("first_name") or "",
        contact.get("middle_name") or "",
        contact.get("last_name") or "",
    ]).strip()
    result.update({
        "matched": 1,
        "match_type": "Contact",
        "doctype": "Contact",
        "name": contact.get("name"),
        "contact": contact.get("name"),
        "display_name": full_name or contact.get("name"),
    })


def _apply_customer_link(result, customer):
    result.update({
        "customer": customer.get("name"),
        "customer_name": customer.get("customer_name"),
        "display_name": customer.get("customer_name") or result.get("display_name"),
    })


def _apply_lead_result(result, lead):
    result.update({
        "matched": 1,
        "match_type": "Lead",
        "doctype": "Lead",
        "name": lead.get("name"),
        "lead": lead.get("name"),
        "display_name": lead.get("lead_name") or lead.get("company_name") or lead.get("name"),
    })


def _or_filters(doctype, fields, variants):
    filters = []
    for fieldname in fields:
        for value in variants:
            filters.append([doctype, fieldname, "=", value])
    return filters
