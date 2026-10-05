from __future__ import unicode_literals

import frappe
from frappe.utils import now_datetime

from worldshading.api import sijilat


PREVIEW_CACHE_SECONDS = 600


def _require_customer_create_permission():
    if not frappe.has_permission("Customer", ptype="create"):
        frappe.throw(
            "You do not have permission to create a Customer",
            frappe.PermissionError
        )


def _normalize_name(value):
    return " ".join(str(value or "").strip().split())


def _preview_cache_key(token):
    return "sijilat_quick_entry:{0}:{1}".format(
        frappe.session.user,
        token
    )


def _find_duplicate_cr(normalized_cr):
    customers = frappe.get_all(
        "Customer",
        filters={"cr_no": ["!=", ""]},
        fields=["name", "customer_name", "cr_no", "disabled"]
    )

    for customer in customers:
        if sijilat._normalize_cr(customer.cr_no) == normalized_cr:
            return customer

    return None


@frappe.whitelist()
def preview_customer_cr(customer_name, cr_no, customer_type, territory):
    """Validate an unsaved Quick Entry Customer without writing Customer data."""
    _require_customer_create_permission()

    customer_name = _normalize_name(customer_name)
    customer_type = str(customer_type or "").strip()
    territory = str(territory or "").strip()
    normalized_cr = sijilat._normalize_customer_cr_input(cr_no)

    if customer_type != "Company" or territory != "Bahrain":
        frappe.throw(
            "CR verification is required only for Bahrain Company customers"
        )
    if not customer_name:
        frappe.throw("Company Name is required")
    if not normalized_cr:
        return {
            "outcome": "invalid_format",
            "message": (
                "Enter the CR No as 4 to 6 digits, a hyphen, and the branch "
                "number; for example 12345-1"
            )
        }

    duplicate = _find_duplicate_cr(normalized_cr)
    if duplicate:
        return {
            "outcome": "duplicate",
            "message": "This CR is already assigned to an existing Customer",
            "existing_customer": duplicate.name,
            "existing_customer_name": duplicate.customer_name,
            "existing_customer_disabled": duplicate.disabled
        }

    try:
        result = sijilat.fetch_cr_details(normalized_cr)
    except sijilat.SijilatTemporaryError:
        return {
            "outcome": "temporary_error",
            "message": (
                "The CR verification service is temporarily unavailable. You may proceed without "
                "verification and verify this Customer later"
            )
        }

    formatted = result.get("formatted") or {}
    summary = formatted.get("Company Summary") or {}
    official_name = _normalize_name(summary.get("Commercial Name (EN)"))
    official_name_ar = _normalize_name(summary.get("Commercial Name (AR)"))
    returned_cr = sijilat._normalize_cr(summary.get("CR No."))

    if not official_name or returned_cr != normalized_cr:
        return {
            "outcome": "invalid_cr",
            "message": "The verification service did not return a matching commercial registration"
        }

    name_match = sijilat._get_business_name_match(
        customer_name,
        official_name,
        official_name_ar
    )
    if name_match.get("level") != "approved":
        return {
            "outcome": "name_mismatch",
            "message": "The Company Name does not sufficiently match this CR",
            "name_similarity_score": name_match.get("score")
        }

    expiry_date = sijilat._get_sijilat_date(summary.get("Expiration Date"))
    verification_status = sijilat._get_verification_status(summary, expiry_date)
    details = sijilat._format_business_details(formatted)

    if verification_status != "Verified":
        return {
            "outcome": "business_rejection",
            "message": "This CR cannot be verified because its status is {0}".format(
                verification_status
            ),
            "status": verification_status,
            "official_customer_name": official_name,
            "name_similarity_score": name_match.get("score"),
            "expiry_date": expiry_date,
            "details": details
        }

    token = frappe.generate_hash(length=32)
    frappe.cache().set_value(
        _preview_cache_key(token),
        {
            "customer_name": official_name,
            "cr_no": normalized_cr,
            "territory": territory,
            "customer_type": customer_type,
            "verified_business_details": details,
            "cr_expiry_date": expiry_date,
            "checked_at": now_datetime()
        },
        expires_in_sec=PREVIEW_CACHE_SECONDS
    )

    return {
        "outcome": "verified",
        "verification_token": token,
        "normalized_cr": normalized_cr,
        "official_customer_name": official_name,
        "name_similarity_score": name_match.get("score"),
        "status": verification_status,
        "expiry_date": expiry_date,
        "details": details
    }


@frappe.whitelist()
def finalize_customer_cr(customer, verification_token):
    """Apply a recent successful Quick Entry preview to the created Customer."""
    if not customer or not verification_token:
        frappe.throw("Customer and verification token are required")

    cache_key = _preview_cache_key(verification_token)
    verification = frappe.cache().get_value(cache_key, expires=True)
    if not verification:
        frappe.throw(
            "The CR verification has expired. Please verify the Customer again"
        )

    customer_doc = frappe.get_doc("Customer", customer)
    customer_doc.check_permission("write")

    if (
        customer_doc.customer_type != verification.get("customer_type") or
        customer_doc.territory != verification.get("territory") or
        _normalize_name(customer_doc.customer_name) !=
            verification.get("customer_name") or
        sijilat._normalize_customer_cr_input(customer_doc.cr_no) !=
            verification.get("cr_no")
    ):
        frappe.throw(
            "Customer details changed after CR verification. Please verify again"
        )

    customer_doc.cr_no = verification.get("cr_no")
    customer_doc.business_verification_status = "Verified"
    customer_doc.verified_business_details = verification.get(
        "verified_business_details"
    )
    customer_doc.cr_expiry_date = verification.get("cr_expiry_date")
    customer_doc.last_sijilat_check = verification.get("checked_at")
    customer_doc.sijilat_recheck_attempts = 0
    customer_doc.flags.sijilat_verification = True
    customer_doc.save()
    frappe.cache().delete_value(cache_key)

    return {
        "customer": customer_doc.name,
        "status": customer_doc.business_verification_status
    }
