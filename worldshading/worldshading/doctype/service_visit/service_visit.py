# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import html
from urllib.parse import quote

import frappe

from frappe.model.document import Document
from frappe.model.mapper import get_mapped_doc


class ServiceVisit(Document):

    def validate(self):
        set_skip_confirmation(self)


def get_service_visit_visitor(source):
	for row in source.get("assigned_users") or []:
		if not row.user:
			continue

		if frappe.db.exists("Has Role", {
			"parent": row.user,
			"role": "Visitor (Workflow)"
		}):
			return row.user

	return None

@frappe.whitelist()
def make_quotation(source_name, target_doc=None):

	def set_missing_values(source, target):

		target.quotation_to = "Customer"
		target.party_name = source.customer
		target.service_visit = source.name

		visitor = get_service_visit_visitor(source)

		if visitor:
			target.follow_up_mode = "Visitor"
			target.visitor = visitor
		else:
			target.follow_up_mode = "Sales"
			target.visitor = None

		target.run_method("set_missing_values")

		if source.whatsapp_no:
			target.whatsapp_no = source.whatsapp_no

		target.run_method("set_taxes")
		target.run_method("calculate_taxes_and_totals")

	doc = get_mapped_doc(
		"Service Visit",
		source_name,
		{
			"Service Visit": {
				"doctype": "Quotation"
			}
		},
		target_doc,
		set_missing_values
	)

	return doc

# @frappe.whitelist()
# def make_quotation(source_name, target_doc=None):

# 	def set_missing_values(source, target):

# 		target.quotation_to = "Customer"
# 		target.party_name = source.customer
# 		target.service_visit = source.name
# 		target.run_method("set_missing_values")
# 		target.run_method("set_taxes")
# 		target.run_method("calculate_taxes_and_totals")

# 	doc = get_mapped_doc(
# 		"Service Visit",
# 		source_name,
# 		{
# 			"Service Visit": {
# 				"doctype": "Quotation"
# 			}
# 		},
# 		target_doc,
# 		set_missing_values
# 	)

# 	return doc


@frappe.whitelist()
def make_sales_order(source_name, target_doc=None):

    from frappe.model.mapper import get_mapped_doc

    def set_missing_values(source, target):

        target.customer = source.customer
        target.service_visit = source.name

        target.run_method("set_missing_values")

    doc = get_mapped_doc(
        "Service Visit",
        source_name,
        {
            "Service Visit": {
                "doctype": "Sales Order"
            }
        },
        target_doc,
        set_missing_values
    )

    return doc

from frappe.utils import now_datetime

@frappe.whitelist()
def make_follow_up_visit(source_name, target_doc=None):

    def set_missing_values(source, target):

        target.is_follow_up = 1
        target.parent_service_visit = source.name
        target.date = now_datetime()

    doc = get_mapped_doc(
        "Service Visit",
        source_name,
        {
            "Service Visit": {
                "doctype": "Service Visit"
            }
        },
        target_doc,
        set_missing_values
    )

    return doc

@frappe.whitelist()
def make_service_visit(source_name, target_doc=None, source_doctype=None):

	allowed_sources = {
		"Quotation": "quotation",
		"Sales Order": "sales_order",
		"Sales Invoice": "sales_invoice"
	}

	if not source_doctype:
		source_doctype = "Quotation"

	if source_doctype not in allowed_sources:
		frappe.throw(_("Cannot create Service Visit from {0}").format(source_doctype))

	link_field = allowed_sources[source_doctype]

	def set_missing_values(source, target):

		target.type = "Measurement"
		target.subject = source.name

		if source_doctype == "Quotation":
			target.customer = source.party_name
		else:
			target.customer = source.customer

		target.customer_name = source.customer_name
		target.set(link_field, source.name)

		target.customer_address = source.customer_address
		target.address_display = source.address_display

		target.contact_person = source.contact_person
		target.contact_display = source.contact_display

		if source.get("contact_mobile"):
			target.mobile_number = source.contact_mobile

	doc = get_mapped_doc(
		source_doctype,
		source_name,
		{
			source_doctype: {
				"doctype": "Service Visit",
				"field_map": {
					"name": link_field
				},
				"field_no_map": [
					"source"
				]
			}
		},
		target_doc,
		set_missing_values
	)

	return doc


@frappe.whitelist()
def make_service_visit_from_quotation(source_name, target_doc=None):
	return make_service_visit(source_name, target_doc, "Quotation")


@frappe.whitelist()
def make_service_visit_from_sales_order(source_name, target_doc=None):
	return make_service_visit(source_name, target_doc, "Sales Order")


@frappe.whitelist()
def make_service_visit_from_sales_invoice(source_name, target_doc=None):
	return make_service_visit(source_name, target_doc, "Sales Invoice")



from frappe.utils import flt


import frappe
from frappe import _
from frappe.utils import nowdate, flt, getdate, add_days

from erpnext.accounts.doctype.journal_entry.journal_entry import (
    get_default_bank_cash_account
)
from erpnext.accounts.party import get_party_account
from erpnext.accounts.utils import get_account_currency

# set skip confirmation based on visit date
def set_skip_confirmation(doc):
    if not doc.get("date"):
        doc.skip_confirmation = 0
        return

    today = getdate(nowdate())
    tomorrow = add_days(today, 1)
    visit_date = getdate(doc.date)
    doc.skip_confirmation = 1 if today <= visit_date <= tomorrow else 0


def set_value_if_field_exists(doc, fieldname, value):
    if value and doc.meta.has_field(fieldname):
        doc.set(fieldname, value)


@frappe.whitelist()
def update_service_visit_workflow_schedule(
    service_visit,
    visit_date,
    selected_time,
    users,
    validity_date=None,
    reference_image=None
):
    doc = frappe.get_doc("Service Visit", service_visit)

    doc.date = visit_date
    doc.time = selected_time

    if validity_date:
        doc.validity_date = validity_date

    if reference_image:
        doc.reference_image = reference_image

    set_skip_confirmation(doc)

    doc.set("assigned_users", [])

    for user in get_schedule_users(users):
        child = doc.append("assigned_users", {})
        child.user = user

    doc.save(ignore_permissions=True)

    return {
        "name": doc.name,
        "docstatus": doc.docstatus,
        "workflow_state": doc.workflow_state,
        "skip_confirmation": doc.get("skip_confirmation")
    }


@frappe.whitelist()
def create_service_visit_payment(
    service_visit,
    payments,
    reference_date,
    reference_no,
    attachment=None,
    pb_branch=None,
    pb_pos_profile=None
):

    # ==================================================
    # PARSE PAYMENTS
    # ==================================================

    if isinstance(payments, str):
        payments = frappe.parse_json(payments)

    # ==================================================
    # GET SERVICE VISIT
    # ==================================================

    doc = frappe.get_doc("Service Visit", service_visit)

    # ==================================================
    # CLEAR EXISTING ROWS
    # ==================================================

    doc.set("payments", [])

    # ==================================================
    # ADD PAYMENT ROWS
    # ==================================================

    for row in payments:

        mode_of_payment = row.get("mode_of_payment")
        amount = flt(row.get("amount"))

        if not mode_of_payment or amount <= 0:
            continue

        child = doc.append("payments", {})

        child.mode_of_payment = mode_of_payment
        child.amount = amount
        child.reference_date = reference_date
        child.reference_no = reference_no
        child.attachment = attachment

        set_value_if_field_exists(child, "pb_branch", pb_branch)
        set_value_if_field_exists(child, "pb_pos_profile", pb_pos_profile)

    # ==================================================
    # SAVE SERVICE VISIT FIRST
    # ==================================================

    doc.save(ignore_permissions=True)

    # ==================================================
    # CREATE PAYMENT ENTRIES
    # ==================================================

    created_pes = []

    for payment_row in doc.payments:

        # ==================================================
        # GET DEFAULT BANK / CASH ACCOUNT
        # ==================================================

        bank = get_default_bank_cash_account(
            doc.company,
            "Bank",
            mode_of_payment=payment_row.mode_of_payment
        )

        if not bank:

            bank = get_default_bank_cash_account(
                doc.company,
                "Cash",
                mode_of_payment=payment_row.mode_of_payment
            )

        if not bank:

            frappe.throw(
                _("No default Bank/Cash account found for Mode of Payment {0}")
                .format(payment_row.mode_of_payment)
            )

        # ==================================================
        # CREATE PAYMENT ENTRY
        # ==================================================

        pe = frappe.new_doc("Payment Entry")

        pe.payment_type = "Receive"

        pe.company = doc.company

        pe.posting_date = nowdate()

        pe.party_type = "Customer"
        pe.party = doc.customer

        pe.mode_of_payment = payment_row.mode_of_payment

        # Customer receivable account
        pe.paid_from = None

        # Bank/Cash account
        pe.paid_to = bank.account

        pe.paid_amount = payment_row.amount
        pe.received_amount = payment_row.amount

        pe.reference_no = reference_no
        pe.reference_date = reference_date

        pe.service_visit = doc.name

        set_value_if_field_exists(pe, "pb_branch", pb_branch)
        set_value_if_field_exists(pe, "pb_pos_profile", pb_pos_profile)

        pe.remarks = _(
            "Service Visit Payment for {0}"
        ).format(doc.name)

        # ==================================================
        # ERPNext Core Initializers
        # ==================================================

        pe.setup_party_account_field()

        pe.set_missing_values()

        pe.set_exchange_rate()

        pe.set_amounts()

        # ==================================================
        # INSERT & SUBMIT
        # ==================================================

        pe.insert(ignore_permissions=True)

        pe.submit()

        # ==================================================
        # ATTACH FILE
        # ==================================================

        if attachment:

            file_doc = frappe.get_doc({
                "doctype": "File",
                "file_url": attachment,
                "attached_to_doctype": "Payment Entry",
                "attached_to_name": pe.name
            })

            file_doc.insert(ignore_permissions=True)

        # ==================================================
        # UPDATE CHILD ROW
        # ==================================================

        payment_row.payment_entry = pe.name

        created_pes.append(pe.name)

    # ==================================================
    # SAVE AGAIN WITH PE LINKS
    # ==================================================

    doc.save(ignore_permissions=True)

    # ==================================================
    # VALIDATION
    # ==================================================

    if not created_pes:

        frappe.throw(
            _("No Payment Entries were created.")
        )

    # ==================================================
    # SUCCESS MESSAGE
    # ==================================================

    frappe.msgprint(_(
        "Payment Entries Created:<br>{0}"
    ).format("<br>".join(created_pes)))

    return created_pes

@frappe.whitelist()
def make_payment_entry(service_visit):

    from frappe.utils import nowdate

    doc = frappe.get_doc("Service Visit", service_visit)

    # ==================================================
    # CREATE PAYMENT ENTRY
    # ==================================================

    pe = frappe.new_doc("Payment Entry")

    pe.payment_type = "Receive"

    pe.company = doc.company

    pe.posting_date = nowdate()

    pe.party_type = "Customer"
    pe.party = doc.customer

    pe.service_visit = doc.name

    party_account = get_party_account(
        pe.party_type,
        pe.party,
        pe.company
    )

    pe.paid_from = party_account
    pe.paid_from_account_currency = get_account_currency(party_account)

    # ==================================================
    # OPTIONAL PREFILL
    # ==================================================

    if doc.get("total_amount"):

        pe.paid_amount = doc.total_amount
        pe.received_amount = doc.total_amount

    # ==================================================
    # ERPNext Core Initializers
    # ==================================================

    pe.setup_party_account_field()

    pe.set_missing_values()

    pe.set_exchange_rate()

    pe.set_amounts()

    return pe




# ---------------------------------------------------------------------------
# Web form customer processing (before_insert)
# ---------------------------------------------------------------------------

SERVICE_VISIT_CUSTOMER_PROCESSING_SOURCE = "web form"


def process_webform_customer(doc, method=None):
    """Match or create customer details for Service Visit web-form flow."""
    source = (doc.get("source") or "").lower()

    if source != SERVICE_VISIT_CUSTOMER_PROCESSING_SOURCE:
        return

    log_lines = []

    _set_webform_customer_name(doc)
    _ensure_service_visit_city_exists(doc)
    _set_service_visit_site_address(doc)
    _append_webform_entry_summary(doc, log_lines)

    customer_matches = []
    match_method = ""

    if doc.get("customer_type") == "Company" and doc.get("cr_no"):
        match_method = _find_customer_matches_by_cr_no(doc, customer_matches)

    whatsapp_clean = _get_last_digits(doc.get("whatsapp_no"), 8)
    mobile_clean = _get_last_digits(doc.get("mobile_number"), 8)

    if not customer_matches:
        match_method = _find_customer_matches_by_phone(
            doc,
            customer_matches,
            whatsapp_clean,
            mobile_clean
        )

    _apply_customer_processing_result(
        doc,
        customer_matches,
        match_method,
        log_lines
    )

    _set_service_visit_customer_party_details(doc)

    doc.web_form_details = "<br>".join(log_lines)


def _append_webform_entry_summary(doc, log_lines):
    log_lines.append("<b>WEB FORM ENTRY DETAILS</b>")
    log_lines.append("<hr>")

    _append_webform_detail(log_lines, "Source", doc.get("source"))
    _append_webform_detail(log_lines, "Customer Type", doc.get("customer_type"))
    _append_webform_detail(log_lines, "Customer Name", doc.get("customer_name"))
    _append_webform_detail(log_lines, "First Name", doc.get("first_name"))
    _append_webform_detail(log_lines, "Last Name", doc.get("last_name"))
    _append_webform_detail(log_lines, "CR No", doc.get("cr_no"))
    _append_webform_detail(log_lines, "WhatsApp No", doc.get("whatsapp_no"))
    _append_webform_detail(log_lines, "Mobile Number", doc.get("mobile_number"))
    _append_webform_detail(log_lines, "Subject", doc.get("subject"))
    _append_webform_detail(log_lines, "Date", doc.get("date"))
    _append_webform_detail(log_lines, "Time", doc.get("time"))
    _append_webform_detail(log_lines, "Site Address", _get_webform_site_address(doc))
    _append_webform_detail(log_lines, "Google Maps Link", doc.get("google_maps_link"))
    _append_webform_detail(log_lines, "Visit Notes", doc.get("visit_notes"))


def _set_webform_customer_name(doc):
    if doc.get("customer_type") == "Individual":
        first_name = doc.get("first_name") or ""
        last_name = doc.get("last_name") or ""

        full_name = (first_name + " " + last_name).strip()

        if full_name:
            doc.customer_name = full_name

    elif doc.get("customer_type") == "Company":
        if doc.get("customer_name"):
            doc.customer_name = doc.customer_name.strip()


def _ensure_service_visit_city_exists(doc):
    city = _clean_detected_city_for_match(doc.get("city"))

    if not city:
        doc.city = ""
        return

    if frappe.db.exists("City", city):
        doc.city = city
        return

    matched_city = _find_existing_city_by_normalized_name(city)

    if matched_city:
        doc.city = matched_city
        return

    doc.city = _create_service_visit_city(city)


def _clean_detected_city_for_match(city):
    city = (city or "").strip()

    if not city:
        return ""

    city = city.replace("\r", " ").replace("\n", " ")
    city = " ".join(city.split())
    city = city.strip(" ,،-")

    parts = []

    for part in city.replace("،", ",").split(","):
        part = part.strip(" ,،-")

        if not part:
            continue

        if _is_ignored_detected_city_part(part):
            continue

        if _is_detected_city_address_part(part):
            continue

        parts.append(part)

    if parts:
        city = parts[0]

    if _is_ignored_detected_city_part(city) or _is_detected_city_address_part(city):
        return ""

    return city[:140]


def _is_ignored_detected_city_part(value):
    normalized_value = _normalize_city_name(value)

    return normalized_value in (
        "bahrain",
        "kingdom of bahrain"
    )


def _is_detected_city_address_part(value):
    normalized_value = _normalize_city_name(value)

    if not normalized_value:
        return False

    address_words = (
        "road",
        "rd",
        "street",
        "st",
        "avenue",
        "ave",
        "block",
        "blk"
    )

    for word in address_words:
        if normalized_value.startswith(word + " "):
            return True

    return False


def _create_service_visit_city(city):
    city = (city or "").strip()

    if not city:
        return ""

    city_doc = frappe.get_doc({
        "doctype": "City",
        "city_name": city,
        "country": "Bahrain"
    })
    city_doc.insert(ignore_permissions=True)

    return city_doc.name


def _find_existing_city_by_normalized_name(city):
    normalized_city = _normalize_city_name(city)

    if not normalized_city:
        return ""

    existing_cities = frappe.get_all(
        "City",
        fields=["name", "city_name"],
        limit_page_length=0
    )

    for existing_city in existing_cities:
        if _normalize_city_name(existing_city.get("city_name") or existing_city.get("name")) == normalized_city:
            return existing_city.get("name")

    return ""


def _normalize_city_name(city):
    city = (city or "").strip().lower()

    if not city:
        return ""

    return " ".join(city.replace("-", " ").split())


def _set_service_visit_site_address(doc):
    parts = []
    line1 = []
    line2 = []

    if doc.get("flat_no"):
        line1.append("Flat " + str(doc.get("flat_no")))

    if doc.get("building_no"):
        line1.append("Building " + str(doc.get("building_no")))

    if line1:
        parts.append(", ".join(line1))

    if doc.get("road_no"):
        line2.append("Road " + str(doc.get("road_no")))

    if doc.get("block"):
        line2.append("Block " + str(doc.get("block")))

    if line2:
        parts.append(", ".join(line2))

    if doc.get("city"):
        parts.append(str(doc.get("city")))

    if doc.get("country"):
        parts.append(str(doc.get("country")))

    doc.site_address = "\n".join(parts)


def _set_service_visit_customer_party_details(doc):
    if not doc.get("customer"):
        return

    selected_contact = doc.get("contact_person")
    details = _get_service_visit_party_details(doc.customer)

    if details:
        doc.customer_address = details.get("customer_address") or doc.get("customer_address")
        doc.address_display = details.get("address_display") or doc.get("address_display")
        doc.contact_person = selected_contact or details.get("contact_person")

        if not selected_contact:
            doc.contact_display = _get_service_visit_contact_display(details)

        if not selected_contact and details.get("contact_mobile"):
            doc.mobile_number = details.get("contact_mobile")

    _set_service_visit_selected_contact_details(doc)

    if not doc.get("mobile_number") and doc.get("whatsapp_no"):
        doc.mobile_number = doc.whatsapp_no


def _set_service_visit_selected_contact_details(doc):
    if not doc.get("contact_person"):
        return

    contact = frappe.db.get_value(
        "Contact",
        doc.contact_person,
        [
            "first_name",
            "last_name",
            "mobile_no",
            "whatsapp_no"
        ],
        as_dict=True
    )

    if not contact:
        return

    contact_display = _get_service_visit_selected_contact_display(contact)

    if contact_display:
        doc.contact_display = contact_display

    if contact.get("mobile_no"):
        doc.mobile_number = contact.get("mobile_no")

    if contact.get("whatsapp_no"):
        doc.whatsapp_no = contact.get("whatsapp_no")


def _get_service_visit_selected_contact_display(contact):
    contact_details = []
    contact_name = (
        ((contact.get("first_name") or "") + " " + (contact.get("last_name") or "")).strip()
    )

    if contact_name:
        contact_details.append(contact_name)

    if contact.get("mobile_no"):
        contact_details.append("Mobile: " + str(contact.get("mobile_no")))

    return "\n".join(contact_details)


def _get_service_visit_party_details(customer):
    from erpnext.accounts.party import get_party_details

    try:
        return get_party_details(
            party=customer,
            party_type="Customer",
            ignore_permissions=True
        )
    except Exception:
        frappe.log_error(
            title="Service Visit party details failed ({0})".format(customer),
            message=frappe.get_traceback()
        )
        return {}


def _get_service_visit_contact_display(details):
    contact_details = []

    if details.get("contact_display"):
        contact_details.append(details.get("contact_display"))

    if details.get("contact_mobile"):
        contact_details.append("Mobile: " + str(details.get("contact_mobile")))

    return "\n".join(contact_details)


def _find_customer_matches_by_cr_no(doc, customer_matches):
    cr_customers = frappe.get_all(
        "Customer",
        filters={
            "cr_no": doc.get("cr_no")
        },
        fields=[
            "name",
            "customer_name"
        ]
    )

    for row in cr_customers:
        if row.name not in customer_matches:
            customer_matches.append(row.name)

    if customer_matches:
        return "CR No"

    return ""


def _find_customer_matches_by_phone(
    doc,
    customer_matches,
    whatsapp_clean,
    mobile_clean
):
    number_to_check = ""
    number_source = ""

    if whatsapp_clean:
        number_to_check = whatsapp_clean
        number_source = "WhatsApp No"

    elif mobile_clean:
        number_to_check = mobile_clean
        number_source = "Mobile Number"

    if not number_to_check:
        return ""

    last_four = number_to_check[-4:]

    contact_phones = frappe.get_all(
        "Contact Phone",
        filters={
            "phone": ["like", "%" + last_four + "%"]
        },
        fields=[
            "parent",
            "phone"
        ]
    )

    for row in contact_phones:
        saved_number = _get_last_digits(row.phone, 8)

        if saved_number != number_to_check:
            continue

        links = frappe.get_all(
            "Dynamic Link",
            filters={
                "parent": row.parent,
                "link_doctype": "Customer"
            },
            fields=["link_name"]
        )

        for link in links:
            if link.link_name not in customer_matches:
                customer_matches.append(link.link_name)

    if customer_matches:
        return number_source

    return ""


def _apply_customer_processing_result(doc, customer_matches, match_method, log_lines):
    log_lines.append("<br>")
    log_lines.append("<b>CUSTOMER RESULT</b>")
    log_lines.append("<hr>")

    if len(customer_matches) == 1:
        doc.customer = customer_matches[0]

        _append_webform_detail(log_lines, "Result", "Existing customer linked")
        _append_webform_detail(log_lines, "Match Method", match_method)
        log_lines.append("<b>Matched Customer:</b> " + _get_customer_link(doc.customer))

        if doc.get("customer_type") == "Company" and match_method == "CR No":
            _set_webform_contact_for_existing_company(doc, log_lines)

    elif len(customer_matches) > 1:
        _append_webform_detail(log_lines, "Result", "Multiple customers found")
        _append_webform_detail(log_lines, "Match Method", match_method)
        _append_webform_detail(log_lines, "Action", "Not auto-linked. Please verify manually.")
        log_lines.append(
            "<b>Matched Customers:</b> "
            + ", ".join([_get_customer_link(customer) for customer in customer_matches])
        )

    else:
        _create_webform_customer_details(doc, log_lines)


def _set_webform_contact_for_existing_company(doc, log_lines):
    contact = _find_customer_contact_by_whatsapp(doc.customer, doc.get("whatsapp_no"))

    if contact:
        doc.contact_person = contact
        _append_webform_detail(
            log_lines,
            "Contact Result",
            "Existing contact linked by WhatsApp No"
        )
        _append_webform_detail(log_lines, "Contact", contact)
        return

    customer = frappe.get_doc("Customer", doc.customer)
    contact = _create_webform_contact(doc, customer)
    doc.contact_person = contact.name

    _append_webform_detail(
        log_lines,
        "Contact Result",
        "New contact created for existing customer"
    )
    _append_webform_detail(log_lines, "Contact", contact.name)


def _find_customer_contact_by_whatsapp(customer, whatsapp_no):
    whatsapp_clean = _get_last_digits(whatsapp_no, 8)

    if not whatsapp_clean:
        return ""

    linked_contacts = frappe.get_all(
        "Dynamic Link",
        filters={
            "link_doctype": "Customer",
            "link_name": customer,
            "parenttype": "Contact"
        },
        fields=["parent"]
    )

    for linked_contact in linked_contacts:
        contact_phones = frappe.get_all(
            "Contact Phone",
            filters={
                "parent": linked_contact.parent
            },
            fields=["phone"]
        )

        for contact_phone in contact_phones:
            if _get_last_digits(contact_phone.phone, 8) == whatsapp_clean:
                return linked_contact.parent

    return ""


def _create_webform_customer_details(doc, log_lines):
    if not doc.get("customer_name"):
        _append_webform_detail(log_lines, "Result", "Customer not created")
        _append_webform_detail(log_lines, "Reason", "Customer name is empty")
        return

    customer_data = {
        "doctype": "Customer",
        "customer_name": doc.customer_name,
        "customer_type": doc.get("customer_type") or "Individual",
        "customer_group": "Special customers",
        "territory": "Bahrain"
    }

    if doc.get("customer_type") == "Company" and doc.get("cr_no"):
        customer_data["cr_no"] = doc.cr_no

    customer = frappe.get_doc(customer_data)
    customer.insert(ignore_permissions=True)

    doc.customer = customer.name

    contact = _create_webform_contact(doc, customer)
    doc.contact_person = contact.name

    address = _create_webform_address(doc, customer)
    doc.customer_address = address.name

    customer.db_set("customer_primary_contact", contact.name)
    customer.db_set("customer_primary_address", address.name)

    _append_webform_detail(log_lines, "Result", "New customer created and linked")
    log_lines.append("<b>Customer:</b> " + _get_customer_link(customer.name))
    _append_webform_detail(log_lines, "Contact", contact.name)
    _append_webform_detail(log_lines, "Address", address.name)


def _create_webform_contact(doc, customer):
    submitted_first_name = (doc.get("first_name") or "").strip()
    submitted_last_name = (doc.get("last_name") or "").strip()

    if submitted_first_name or submitted_last_name:
        contact_first_name = submitted_first_name or submitted_last_name
        contact_last_name = submitted_last_name if submitted_first_name else ""
    else:
        contact_first_name = doc.get("customer_name")
        contact_last_name = ""

    submitted_mobile_number = doc.get("mobile_number")
    submitted_whatsapp_no = doc.get("whatsapp_no")

    final_mobile = _clean_webform_phone_number(
        submitted_mobile_number or submitted_whatsapp_no or ""
    )
    final_whatsapp = _clean_webform_phone_number(
        submitted_whatsapp_no or submitted_mobile_number or ""
    )

    if submitted_mobile_number:
        mobile_country_code = _get_webform_country_code(doc, "mobile_country_code")
    else:
        mobile_country_code = _get_webform_country_code(doc, "whatsapp_country_code")

    if submitted_whatsapp_no:
        whatsapp_country_code = _get_webform_country_code(doc, "whatsapp_country_code")
    else:
        whatsapp_country_code = _get_webform_country_code(doc, "mobile_country_code")

    contact_phone_rows = []

    if final_mobile:
        contact_phone_rows.append({
            "phone": final_mobile,
            "country_code": mobile_country_code,
            "is_primary_phone": 1,
            "is_primary_mobile_no": 1,
            "is_whatsapp": 0
        })

    if final_whatsapp and final_whatsapp != final_mobile:
        contact_phone_rows.append({
            "phone": final_whatsapp,
            "country_code": whatsapp_country_code,
            "is_primary_phone": 0,
            "is_primary_mobile_no": 0,
            "is_whatsapp": 1
        })

    if final_whatsapp and final_whatsapp == final_mobile:
        contact_phone_rows[0]["is_whatsapp"] = 1

    contact_email_rows = []
    email_id = (doc.get("email_id") or "").strip()

    if email_id:
        contact_email_rows.append({
            "email_id": email_id,
            "is_primary": 1
        })

    contact = frappe.get_doc({
        "doctype": "Contact",
        "first_name": contact_first_name,
        "last_name": contact_last_name,
        "phone_nos": contact_phone_rows,
        "email_ids": contact_email_rows,
        "links": [
            {
                "link_doctype": "Customer",
                "link_name": customer.name
            }
        ]
    })

    contact.insert(ignore_permissions=True)

    return contact


def _clean_webform_phone_number(value):
    phone = ""

    for ch in (value or ""):
        if ch.isdigit():
            phone = phone + ch

    if phone.startswith("0"):
        phone = phone[1:]

    return phone


def _get_webform_country_code(doc, fieldname):
    country_code = (doc.get(fieldname) or "").strip()

    if not country_code:
        country_code = "+973 Bahrain"

    return country_code


def _create_webform_address(doc, customer):
    address_line1 = ""

    if doc.get("flat_no"):
        address_line1 = address_line1 + "Flat/Home: " + str(doc.flat_no)

    if doc.get("road_no"):
        if address_line1:
            address_line1 = address_line1 + ", "
        address_line1 = address_line1 + "Road/Street: " + str(doc.road_no)

    if doc.get("block"):
        if address_line1:
            address_line1 = address_line1 + ", "
        address_line1 = address_line1 + "Block: " + str(doc.block)

    if not address_line1:
        address_line1 = doc.get("site_address") or doc.get("customer_name")

    address = frappe.get_doc({
        "doctype": "Address",
        "address_title": doc.get("customer_name"),
        "address_type": "Billing",
        "address_line1": address_line1,
        "address_line2": doc.get("site_address") or "",
        "city": doc.get("city") or "Bahrain",
        "country": doc.get("country") or "Bahrain",
        "links": [
            {
                "link_doctype": "Customer",
                "link_name": customer.name
            }
        ]
    })

    address.insert(ignore_permissions=True)

    return address


def _append_webform_detail(log_lines, label, value):
    if value in (None, ""):
        value = ""

    log_lines.append(
        "<b>{0}:</b> {1}".format(
            _html(label),
            _html(value)
        )
    )


def _get_webform_site_address(doc):
    address_parts = []

    if doc.get("flat_no"):
        address_parts.append("Flat/Home: " + str(doc.get("flat_no")))

    if doc.get("road_no"):
        address_parts.append("Road/Street: " + str(doc.get("road_no")))

    if doc.get("block"):
        address_parts.append("Block: " + str(doc.get("block")))

    if doc.get("city"):
        address_parts.append(str(doc.get("city")))

    if doc.get("country"):
        address_parts.append(str(doc.get("country")))

    return ", ".join(address_parts)


def _get_customer_link(customer):
    customer_name = str(customer or "")

    if not customer_name:
        return ""

    return '<a href="/desk#Form/Customer/{0}">{1}</a>'.format(
        quote(customer_name, safe=""),
        _html(customer_name)
    )


def _html(value):
    return html.escape(str(value or ""), quote=True)


def _get_last_digits(value, length):
    digits = ""

    for ch in (value or ""):
        if ch.isdigit():
            digits = digits + ch

    return digits[-length:]


# ---------------------------------------------------------------------------
# Web form reference images (after_insert)
# ---------------------------------------------------------------------------

MERGED_REFERENCE_FILENAME = "SV_Customer_Reference"
REFERENCE_IMAGE_FIELD = "reference_image"


def merge_webform_reference_images(doc, method=None):
    """Merge uploaded File docs from reference_images_json into reference_image."""
    file_names = _parse_reference_images_json(doc.get("reference_images_json"))
    if not file_names:
        return

    if doc.get("source") == "Web Form":
        file_names = _filter_webform_upload_files(file_names)

    if not file_names:
        return

    try:
        _attach_merged_reference_image(doc, file_names)
    except Exception:
        frappe.log_error(
            title="Service Visit reference image merge failed ({0})".format(doc.name),
            message=frappe.get_traceback(),
        )


def _parse_reference_images_json(raw):
    if not raw:
        return []

    parsed = frappe.parse_json(raw)
    if isinstance(parsed, str):
        return [parsed] if parsed else []
    if isinstance(parsed, (list, tuple)):
        return [f for f in parsed if f]

    return []


def _filter_webform_upload_files(file_names):
    """Only merge unattached uploads owned by Guest or the current session user."""
    allowed_owners = {frappe.session.user, "Guest"}
    valid = []

    for name in file_names:
        if not frappe.db.exists("File", name):
            continue

        meta = frappe.db.get_value(
            "File",
            name,
            ["owner", "attached_to_doctype", "attached_to_name"],
            as_dict=True,
        )
        if not meta or meta.owner not in allowed_owners:
            continue
        if meta.attached_to_doctype and meta.attached_to_name:
            continue

        valid.append(name)

    return valid


def _attach_merged_reference_image(doc, file_names):
    from worldshading.api.utility import merge_documents

    result = merge_documents(
        file_names=file_names,
        output_filename=MERGED_REFERENCE_FILENAME,
        attach_to_doctype=doc.doctype,
        attach_to_name=doc.name,
        cleanup_originals=1,
        is_private=0,
    )

    if not result or not result.get("file_doc"):
        return

    file_doc_name = result["file_doc"]
    frappe.db.set_value(
        "File",
        file_doc_name,
        {
            "attached_to_doctype": doc.doctype,
            "attached_to_name": doc.name,
            "attached_to_field": REFERENCE_IMAGE_FIELD,
            "is_private": 0,
        },
        update_modified=False,
    )

    file_url = result.get("file_url") or frappe.db.get_value(
        "File", file_doc_name, "file_url"
    )
    if file_url:
        doc.db_set(REFERENCE_IMAGE_FIELD, file_url)

    doc.db_set("reference_images_json", None)



@frappe.whitelist()
def get_staff_day_schedule(visit_date, user, current_service_visit=None):

    time_slots = [
        "07:00 AM to 08:00 AM",
        "08:00 AM to 09:00 AM",
        "09:00 AM to 10:00 AM",
        "10:00 AM to 11:00 AM",
        "11:00 AM to 12:00 PM",
        "12:00 PM to 01:00 PM",
        "01:00 PM to 02:00 PM",
        "02:00 PM to 03:00 PM",
        "03:00 PM to 04:00 PM",
        "04:00 PM to 05:00 PM",
        "05:00 PM to 06:00 PM",
        "06:00 PM to 07:00 PM",
        "07:00 PM to 08:00 PM",
        "08:00 PM to 09:00 PM",
        "09:00 PM to 10:00 PM",
        "10:00 PM to 11:00 PM",
        "11:00 PM to 12:00 AM",
        "12:00 AM to 01:00 AM",
        "01:00 AM to 02:00 AM",
        "02:00 AM to 03:00 AM",
        "03:00 AM to 04:00 AM",
        "04:00 AM to 05:00 AM",
        "05:00 AM to 06:00 AM",
        "06:00 AM to 07:00 AM"
    ]

    users = get_schedule_users(user)

    if not visit_date or not users:

        return {
            "users": [],
            "summary": [],
            "slots": []
        }

    settings = frappe.get_single("WS Settings")

    capacity_map = {}

    for row in settings.service_visit_staff_capacity:

        if row.active and row.user:

            capacity_map[row.user] = row.max_visits_per_day or 0

    visits = frappe.get_all(
        "Service Visit",
        filters={
            "docstatus": 1,
            "date": ["between", [visit_date + " 00:00:00", visit_date + " 23:59:59"]],
            "workflow_state": ["not in", ["Cancelled", "Completed", "Quotation Created"]],
            "name": ["!=", current_service_visit or ""]
        },
        fields=[
            "name",
            "customer_name",
            "date",
            "time",
            "workflow_state"
        ],
        order_by="date asc"
    )

    user_booked_visits = get_user_booked_visits(users, visits)

    summary = []

    for selected_user in users:

        max_visits = capacity_map.get(selected_user, 0)

        booked = len(user_booked_visits.get(selected_user, []))

        remaining = max(max_visits - booked, 0)

        summary.append({
            "user": selected_user,
            "max_visits": max_visits,
            "booked": booked,
            "remaining": remaining,
            "daily_available": booked < max_visits
        })

    slots = []

    for slot in time_slots:

        slot_bookings = []

        unavailable_users = []

        daily_limit_reached_users = []

        for selected_user in users:

            user_slot_booking = None

            for visit in user_booked_visits.get(selected_user, []):

                if visit.time == slot:
                    user_slot_booking = visit
                    break

            user_max_visits = capacity_map.get(selected_user, 0)
            user_booked_count = len(user_booked_visits.get(selected_user, []))

            if user_slot_booking:

                unavailable_users.append(selected_user)

                slot_bookings.append({
                    "user": selected_user,
                    "service_visit": user_slot_booking.name,
                    "customer_name": user_slot_booking.customer_name,
                    "workflow_state": user_slot_booking.workflow_state,
                    "reason": "Booked"
                })

            elif user_booked_count >= user_max_visits:

                unavailable_users.append(selected_user)

                daily_limit_reached_users.append(selected_user)

        available = len(unavailable_users) == 0

        reason = "Available"

        if slot_bookings:
            reason = "Booked"

        elif daily_limit_reached_users:
            reason = "Daily Limit Reached"

        slots.append({
            "time": slot,
            "available": available,
            "reason": reason,
            "unavailable_users": unavailable_users,
            "daily_limit_reached_users": daily_limit_reached_users,
            "bookings": slot_bookings
        })

    return {
        "users": users,
        "summary": summary,
        "slots": slots
    }


def get_schedule_users(user):

    users = []

    if not user:
        return users

    if isinstance(user, list):
        parsed_users = user
    else:
        try:
            parsed_users = frappe.parse_json(user)
        except Exception:
            parsed_users = [user]

    if not isinstance(parsed_users, list):
        parsed_users = [parsed_users]

    for selected_user in parsed_users:

        if selected_user and selected_user not in users:
            users.append(selected_user)

    return users


def get_user_booked_visits(users, visits):

    user_booked_visits = {}

    for selected_user in users:
        user_booked_visits[selected_user] = []

    if not visits:
        return user_booked_visits

    visit_map = {}

    for visit in visits:
        visit_map[visit.name] = visit

    assignments = frappe.get_all(
        "WS User Assignment",
        filters={
            "parent": ["in", list(visit_map.keys())],
            "parenttype": "Service Visit",
            "parentfield": "assigned_users",
            "user": ["in", users]
        },
        fields=[
            "parent",
            "user"
        ]
    )

    for assignment in assignments:

        visit = visit_map.get(assignment.parent)

        if visit and assignment.user in user_booked_visits:
            user_booked_visits[assignment.user].append(visit)

    return user_booked_visits
