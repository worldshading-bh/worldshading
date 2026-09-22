from __future__ import unicode_literals

import base64
import datetime
import difflib
import hashlib
import hmac
import json
import os
import re

import frappe
import requests
from Crypto.Cipher import AES
from frappe.utils import add_months, cint, getdate, get_datetime, now_datetime, nowdate


SIJILAT_API = "https://api.sijilat.bh/api/"
SIJILAT_TOKEN_URL = "https://api.sijilat.bh/token"

HMAC_KEY = "UHxNtYMRYwvfpO1dS5pWLKL0M2DgOj40EbN4SoBWgfc"
TOKEN_PASSWORD = "sijilat_test"
AES_PASSWORD = b"MySecretKey"
MAX_AUTOMATIC_RECHECK_ATTEMPTS = 3
AUTO_VERIFICATION_RETRY_HOURS = 24
NAME_MATCH_MINIMUM_SCORE = 50
BUSINESS_NAME_LEGAL_WORDS = set((
    "BSC", "CO", "COMPANY", "EST", "ESTABLISHMENT", "LTD", "LIMITED",
    "LLC", "SPC", "WLL"
))


class SijilatTemporaryError(frappe.ValidationError):
    pass


class SijilatPermanentError(frappe.ValidationError):
    pass


@frappe.whitelist()
def fetch_cr_details(cr_no, branch_no=None):
    cr_no = str(cr_no or "").strip()

    if not cr_no:
        frappe.throw("CR No is required")

    if "-" in cr_no:
        cr_input = cr_no
    elif branch_no:
        cr_input = "{0}-{1}".format(cr_no, branch_no)
    else:
        frappe.throw("Enter CR No in the format 12345-1, including the branch number")

    normalized_cr = _normalize_customer_cr_input(cr_input)
    if not normalized_cr:
        frappe.throw(
            "Invalid CR No format. Use 4 to 6 digits, a hyphen, and the branch number; "
            "for example 12345-1"
        )
    cr_no, branch_no = normalized_cr.split("-", 1)

    body = {
        "CR_NO": cr_no,
        "BRANCH_NO": branch_no,

        "cult_lang": "EN",
        "Input_CULT_LANG": "EN",
        "CULT_LANG": "EN",
        "cultLang": "EN",

        "CurrentMenuTyp": "A",
        "CurrentMenu_Type": "A",
        "MENU_TYPE": "A",

        "cpr_no": "",
        "CPR_NO_LOGIN": "",
        "CPR_GCC_NO": "",
        "CPR_OR_GCC_NO": "",
        "Login_CPR_No": "",
        "Login_CPR": "",
        "APPCNT_CPR_NO": "",
        "cprno": "",
        "LOGIN_PB_NO": "",
        "PB_NO": "",
        "Input_PB_NO": "",

        "SESSION_ID": ""
    }

    headers = {
        "Accept": "*/*",
        "Content-Type": "application/encrypted+json; charset=utf-8",
        "Origin": "https://www.sijilat.bh",
        "Referer": "https://www.sijilat.bh/",
        "User-Agent": "Mozilla/5.0"
    }

    try:
        token = get_sijilat_token()
        if not token:
            raise SijilatTemporaryError(
                "Sijilat did not return an access token"
            )
        headers["Authorization"] = "Bearer {0}".format(token)
        encrypted_body = cryptojs_aes_encrypt(
            json.dumps(body, separators=(",", ":"))
        )
        response = requests.post(
            SIJILAT_API + "CRdetails/CompleteCRDetails",
            data=encrypted_body,
            headers=headers,
            timeout=20
        )
        response.raise_for_status()
        result = response.json()
        if not isinstance(result, dict):
            raise SijilatTemporaryError("Sijilat returned an invalid response")
        if result.get("Status_Code") != "200":
            raise SijilatTemporaryError(
                result.get("Status_Message") or "Sijilat returned an error"
            )
        json_data = result.get("jsonData") or {}
        formatted = format_sijilat_data(json_data)
    except SijilatTemporaryError:
        raise
    except Exception:
        frappe.log_error(frappe.get_traceback(), "Sijilat CR Fetch Failed")
        raise SijilatTemporaryError(
            "Sijilat could not verify this CR right now. Please confirm the CR No and try again later"
        )

    return {
        "cr_no": cr_no,
        "branch_no": branch_no,
        "raw_api": json_data,
        "formatted": formatted
    }


@frappe.whitelist()
def verify_customer_cr(customer):
    """Backward-compatible preview; verification requires explicit confirmation."""
    return get_customer_cr_verification_preview(customer)


@frappe.whitelist()
def get_customer_cr_verification_preview(customer):
    """Fetch Sijilat details without changing the Customer."""
    customer_doc = _get_customer_for_cr_verification(customer)
    verification = _fetch_customer_cr_verification(customer_doc)
    name_match = _get_business_name_match(
        customer_doc.customer_name,
        verification.get("official_customer_name"),
        verification.get("official_customer_name_ar")
    )

    if name_match.get("level") == "blocked":
        return {
            "status": "Name Mismatch",
            "current_customer_name": customer_doc.customer_name,
            "name_matches": False,
            "name_match_level": name_match.get("level")
        }

    return {
        "status": verification.get("status"),
        "current_customer_name": customer_doc.customer_name,
        "official_customer_name": verification.get("official_customer_name"),
        "name_matches": name_match.get("level") == "approved",
        "name_match_level": name_match.get("level"),
        "name_similarity_score": name_match.get("score"),
        "details": verification.get("details"),
        "expiry_date": verification.get("expiry_date")
    }


@frappe.whitelist()
def confirm_customer_cr_verification(customer, override_reason=None):
    """Recheck Sijilat and atomically update the Customer with its legal name."""
    customer_doc = _get_customer_for_cr_verification(customer)
    _validate_unique_customer_cr(customer_doc)
    verification = _fetch_customer_cr_verification(customer_doc)
    name_match = _get_business_name_match(
        customer_doc.customer_name,
        verification.get("official_customer_name"),
        verification.get("official_customer_name_ar")
    )

    if name_match.get("level") == "blocked":
        frappe.throw(
            "The Customer name does not sufficiently match this CR. Verification is blocked"
        )

    if verification.get("status") != "Verified":
        frappe.throw(
            "This CR cannot be verified because its status is {0}".format(
                verification.get("status")
            )
        )

    customer_doc.customer_name = verification.get("official_customer_name")
    customer_doc.cr_no = _normalize_customer_cr_input(customer_doc.cr_no)
    customer_doc.verified_business_details = verification.get("details")
    customer_doc.cr_expiry_date = verification.get("expiry_date")
    customer_doc.business_verification_status = "Verified"
    customer_doc.last_sijilat_check = now_datetime()
    customer_doc.sijilat_recheck_attempts = 0
    customer_doc.flags.sijilat_verification = True
    customer_doc.save()

    return {
        "status": customer_doc.business_verification_status,
        "customer_name": customer_doc.customer_name,
        "details": customer_doc.verified_business_details,
        "expiry_date": customer_doc.cr_expiry_date,
        "name_match_level": name_match.get("level"),
        "name_similarity_score": name_match.get("score")
    }


def _get_customer_for_cr_verification(customer):
    if not customer:
        frappe.throw("Customer is required")

    customer_doc = frappe.get_doc("Customer", customer)
    customer_doc.check_permission("write")

    if customer_doc.customer_type != "Company":
        frappe.throw("CR verification is available only for Company customers")

    if customer_doc.territory != "Bahrain":
        frappe.throw("CR verification is available only for customers in Bahrain")

    if not customer_doc.get("cr_no"):
        frappe.throw("Please enter CR No first")

    return customer_doc


def _fetch_customer_cr_verification(customer_doc):
    result = fetch_cr_details(customer_doc.cr_no)
    formatted = result.get("formatted") or {}
    summary = formatted.get("Company Summary") or {}
    official_customer_name = str(summary.get("Commercial Name (EN)") or "").strip()
    official_customer_name_ar = str(summary.get("Commercial Name (AR)") or "").strip()

    if not official_customer_name:
        raise SijilatPermanentError(
            "Sijilat did not return the official English commercial name"
        )

    if _normalize_cr(summary.get("CR No.")) != _normalize_cr(customer_doc.cr_no):
        raise SijilatPermanentError(
            "The CR returned by Sijilat does not match the Customer CR"
        )

    expiry_date = _get_sijilat_date(summary.get("Expiration Date"))
    verification_status = _get_verification_status(summary, expiry_date)

    return {
        "status": verification_status,
        "official_customer_name": official_customer_name,
        "official_customer_name_ar": official_customer_name_ar,
        "details": _format_business_details(formatted),
        "expiry_date": expiry_date
    }


def _validate_unique_customer_cr(customer_doc):
    customer_cr = _normalize_cr(customer_doc.cr_no)
    customers = frappe.get_all(
        "Customer",
        filters={"cr_no": ["!=", ""]},
        fields=["name", "customer_name", "cr_no"]
    )

    for customer in customers:
        if customer.name == customer_doc.name:
            continue
        if _normalize_cr(customer.cr_no) == customer_cr:
            frappe.throw(
                "This CR is already assigned to Customer {0} ({1})".format(
                    customer.name, customer.customer_name
                )
            )


def _normalize_cr(value):
    value = str(value or "").strip()
    parts = value.split("-", 1)
    cr_no = re.sub(r"[^0-9]", "", parts[0])
    branch_no = re.sub(r"[^0-9]", "", parts[1]) if len(parts) > 1 else "1"
    return "{0}-{1}".format(cr_no, branch_no or "1")


def _normalize_customer_cr_input(value):
    value = str(value or "")
    match = re.match(r"^\s*([0-9]{4,6})\s*-\s*([0-9]{1,3})\s*$", value)
    if not match:
        return None
    return "{0}-{1}".format(match.group(1), match.group(2))


def _is_valid_customer_cr(value):
    return bool(_normalize_customer_cr_input(value))


def _normalize_business_name(value):
    value = str(value or "").upper().strip()
    value = re.sub(r"\bW[\s.]*L[\s.]*L\b", " WLL ", value)
    value = re.sub(r"[^\w]+", " ", value, flags=re.UNICODE)
    words = [
        word for word in value.split()
        if word and word not in BUSINESS_NAME_LEGAL_WORDS
    ]
    return " ".join(words)


def _get_business_name_match(customer_name, official_name_en, official_name_ar=None):
    """Return the strongest normalized similarity against Sijilat names."""
    customer_normalized = _normalize_business_name(customer_name)
    official_names = [official_name_en, official_name_ar]
    scores = []

    for official_name in official_names:
        official_normalized = _normalize_business_name(official_name)
        if not customer_normalized or not official_normalized:
            continue

        compact_score = difflib.SequenceMatcher(
            None,
            customer_normalized.replace(" ", ""),
            official_normalized.replace(" ", "")
        ).ratio()
        sorted_word_score = difflib.SequenceMatcher(
            None,
            " ".join(sorted(customer_normalized.split())),
            " ".join(sorted(official_normalized.split()))
        ).ratio()
        scores.append(max(compact_score, sorted_word_score) * 100)

    score = round(max(scores) if scores else 0, 2)
    if score > NAME_MATCH_MINIMUM_SCORE:
        level = "approved"
    else:
        level = "blocked"

    return {"score": score, "level": level}


def reset_customer_cr_verification(doc, method=None):
    """Invalidate saved verification when the identifying Customer data changes."""
    if doc.flags.get("sijilat_verification"):
        return

    if doc.is_new():
        if not doc.get("business_verification_status"):
            doc.business_verification_status = "Not Verified"
        return

    previous_doc = doc.get_doc_before_save()
    if not previous_doc:
        return

    verification_input_changed = (
        previous_doc.get("cr_no") != doc.get("cr_no") or
        previous_doc.get("customer_type") != doc.get("customer_type") or
        previous_doc.get("territory") != doc.get("territory") or
        previous_doc.get("customer_name") != doc.get("customer_name")
    )

    if verification_input_changed:
        doc.business_verification_status = "Not Verified"
        doc.verified_business_details = ""
        doc.cr_expiry_date = None
        doc.last_sijilat_check = None
        doc.sijilat_recheck_attempts = 0


def _is_existing_customer_auto_verification_eligible(customer_doc, checked_at=None):
    """Return whether an historical Customer may be checked by the migration job."""
    checked_at = get_datetime(checked_at or now_datetime())
    last_check = (
        get_datetime(customer_doc.last_sijilat_check)
        if customer_doc.last_sijilat_check else None
    )
    cooldown_started = checked_at - datetime.timedelta(
        hours=AUTO_VERIFICATION_RETRY_HOURS
    )

    return bool(
        not cint(customer_doc.disabled) and
        customer_doc.customer_type == "Company" and
        customer_doc.territory == "Bahrain" and
        customer_doc.cr_no and
        not customer_doc.business_verification_status and
        cint(customer_doc.sijilat_recheck_attempts) < MAX_AUTOMATIC_RECHECK_ATTEMPTS and
        (not last_check or last_check <= cooldown_started)
    )


def enqueue_existing_customer_cr_verification():
    """Queue at most one eligible historical Customer every scheduler run."""
    customers = frappe.get_all(
        "Customer",
        filters={
            "disabled": 0,
            "customer_type": "Company",
            "territory": "Bahrain",
            "cr_no": ["!=", ""],
            "business_verification_status": ["is", "not set"]
        },
        fields=[
            "name", "disabled", "customer_type", "territory", "cr_no",
            "business_verification_status", "last_sijilat_check",
            "sijilat_recheck_attempts", "creation"
        ],
        order_by="last_sijilat_check asc, creation desc",
        limit_page_length=20
    )
    checked_at = now_datetime()

    for customer in customers:
        if not _is_existing_customer_auto_verification_eligible(customer, checked_at):
            continue

        frappe.enqueue(
            "worldshading.api.sijilat.auto_verify_existing_customer_cr",
            queue="short",
            timeout=60,
            job_name="sijilat_existing_customer_auto_verification|{0}".format(
                customer.name
            ),
            customer=customer.name
        )
        return customer.name

    return None


def _set_existing_customer_not_verified(customer, checked_at, attempt_count):
    frappe.db.set_value(
        "Customer",
        customer,
        {
            "business_verification_status": "Not Verified",
            "last_sijilat_check": checked_at,
            "sijilat_recheck_attempts": attempt_count
        }
    )
    return "Not Verified"


def _handle_existing_customer_temporary_failure(
    customer, checked_at, attempt_count
):
    if attempt_count >= MAX_AUTOMATIC_RECHECK_ATTEMPTS:
        return _set_existing_customer_not_verified(
            customer, checked_at, attempt_count
        )
    return "Retry Pending"


def auto_verify_existing_customer_cr(customer):
    """Verify one historical Customer without changing any pricing authorization."""
    customer_doc = frappe.get_doc("Customer", customer)
    checked_at = now_datetime()
    verification_input = (
        customer_doc.customer_name,
        customer_doc.customer_type,
        customer_doc.territory,
        customer_doc.cr_no
    )

    if not _is_existing_customer_auto_verification_eligible(
        customer_doc, checked_at
    ):
        return None

    attempt_count = cint(customer_doc.sijilat_recheck_attempts) + 1
    frappe.db.set_value(
        "Customer",
        customer_doc.name,
        {
            "last_sijilat_check": checked_at,
            "sijilat_recheck_attempts": attempt_count
        }
    )
    frappe.db.commit()

    normalized_cr = _normalize_customer_cr_input(customer_doc.cr_no)
    if not normalized_cr:
        return _set_existing_customer_not_verified(
            customer_doc.name, checked_at, attempt_count
        )

    try:
        _validate_unique_customer_cr(customer_doc)
    except frappe.ValidationError:
        return _set_existing_customer_not_verified(
            customer_doc.name, checked_at, attempt_count
        )

    try:
        verification = _fetch_customer_cr_verification(customer_doc)
    except SijilatPermanentError:
        return _set_existing_customer_not_verified(
            customer_doc.name, checked_at, attempt_count
        )
    except SijilatTemporaryError:
        return _handle_existing_customer_temporary_failure(
            customer_doc.name, checked_at, attempt_count
        )
    except Exception:
        frappe.log_error(
            frappe.get_traceback(),
            "Historical Sijilat Verification Failed: {0}".format(
                customer_doc.name
            )
        )
        return _handle_existing_customer_temporary_failure(
            customer_doc.name, checked_at, attempt_count
        )

    verification_status = verification.get("status")
    if verification_status not in ("Verified", "Expired"):
        return _set_existing_customer_not_verified(
            customer_doc.name, checked_at, attempt_count
        )

    name_match = _get_business_name_match(
        customer_doc.customer_name,
        verification.get("official_customer_name"),
        verification.get("official_customer_name_ar")
    )
    if name_match.get("level") != "approved":
        return _set_existing_customer_not_verified(
            customer_doc.name, checked_at, attempt_count
        )

    customer_doc.reload()
    current_verification_input = (
        customer_doc.customer_name,
        customer_doc.customer_type,
        customer_doc.territory,
        customer_doc.cr_no
    )
    if (
        current_verification_input != verification_input or
        customer_doc.business_verification_status
    ):
        return None

    customer_doc.customer_name = verification.get("official_customer_name")
    customer_doc.cr_no = normalized_cr
    customer_doc.verified_business_details = verification.get("details")
    customer_doc.cr_expiry_date = verification.get("expiry_date")
    customer_doc.business_verification_status = verification_status
    customer_doc.last_sijilat_check = checked_at
    customer_doc.sijilat_recheck_attempts = 0
    customer_doc.flags.sijilat_verification = True
    customer_doc.save()

    return verification_status


def mark_expired_customer_crs():
    """Mark only Sijilat-verified Customers whose saved CR expiry has passed."""
    customers = frappe.get_all(
        "Customer",
        filters={
            "business_verification_status": "Verified",
            "cr_expiry_date": ["<", nowdate()],
            "verified_business_details": ["!=", ""]
        },
        fields=["name"]
    )

    for customer in customers:
        frappe.db.set_value(
            "Customer",
            customer.name,
            {
                "business_verification_status": "Expired",
                "sijilat_recheck_attempts": 0
            }
        )


def enqueue_expired_customer_cr_rechecks():
    """Queue one monthly Sijilat recheck per eligible expired Customer."""
    customers = frappe.get_all(
        "Customer",
        filters={
            "business_verification_status": "Expired",
            "cr_no": ["!=", ""],
            "verified_business_details": ["!=", ""],
            "sijilat_recheck_attempts": ["<", MAX_AUTOMATIC_RECHECK_ATTEMPTS]
        },
        fields=["name", "last_sijilat_check"]
    )
    earliest_recheck_date = getdate(add_months(nowdate(), -1))

    for customer in customers:
        if (
            customer.last_sijilat_check and
            getdate(customer.last_sijilat_check) > earliest_recheck_date
        ):
            continue

        frappe.enqueue(
            "worldshading.api.sijilat.recheck_expired_customer_cr",
            queue="short",
            timeout=60,
            customer=customer.name
        )


def recheck_expired_customer_cr(customer):
    """Recheck one expired Customer without changing its name or pricing."""
    customer_doc = frappe.get_doc("Customer", customer)

    if customer_doc.business_verification_status != "Expired":
        return
    if not customer_doc.cr_no or not customer_doc.verified_business_details:
        return
    if cint(customer_doc.sijilat_recheck_attempts) >= MAX_AUTOMATIC_RECHECK_ATTEMPTS:
        return

    earliest_recheck_date = getdate(add_months(nowdate(), -1))
    if (
        customer_doc.last_sijilat_check and
        getdate(customer_doc.last_sijilat_check) > earliest_recheck_date
    ):
        return

    attempt_count = cint(customer_doc.sijilat_recheck_attempts) + 1
    checked_at = now_datetime()
    frappe.db.set_value(
        "Customer",
        customer_doc.name,
        {
            "last_sijilat_check": checked_at,
            "sijilat_recheck_attempts": attempt_count
        }
    )

    try:
        verification = _fetch_customer_cr_verification(customer_doc)
    except Exception:
        frappe.log_error(
            frappe.get_traceback(),
            "Monthly Sijilat Recheck Failed: {0}".format(customer_doc.name)
        )
        return

    status = verification.get("status")
    values = {
        "business_verification_status": status,
        "verified_business_details": verification.get("details"),
        "cr_expiry_date": verification.get("expiry_date"),
        "last_sijilat_check": checked_at
    }

    if status == "Verified":
        values["sijilat_recheck_attempts"] = 0

    frappe.db.set_value("Customer", customer_doc.name, values)


def _get_verification_status(summary, expiry_date):
    if expiry_date and expiry_date < getdate(nowdate()):
        return "Expired"

    sijilat_status = str(summary.get("Status") or "").strip().lower()
    rejected_statuses = ("inactive", "cancelled", "canceled", "deleted", "struck off")

    if any(status in sijilat_status for status in rejected_statuses):
        return "Rejected"

    return "Verified"


def _get_sijilat_date(value):
    if not value:
        return None

    value = str(value).strip()
    date_formats = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%m/%d/%Y")

    for date_format in date_formats:
        try:
            return datetime.datetime.strptime(value, date_format).date()
        except (TypeError, ValueError):
            pass

    return None


def _format_business_details(formatted):
    summary = formatted.get("Company Summary") or {}
    activities = formatted.get("Business Activities") or []
    address = formatted.get("Commercial Address") or {}
    lines = []

    for label in (
        "Commercial Name (EN)", "Commercial Name (AR)", "CR No.",
        "CR Type", "Registration Date", "Expiration Date", "Status",
        "Financial Year End", "Nationality"
    ):
        if summary.get(label):
            lines.append("{0}: {1}".format(label, summary.get(label)))

    activity_names = [row.get("Activity") for row in activities if row.get("Activity")]
    if activity_names:
        lines.append("Business Activities: {0}".format(", ".join(activity_names)))

    address_parts = []
    for label, value in address.items():
        if value:
            address_parts.append("{0}: {1}".format(label, value))
    if address_parts:
        lines.append("Commercial Address: {0}".format(", ".join(address_parts)))

    return "\n".join(lines)


def get_sijilat_token():
    encrypted_password = hmac.new(
        HMAC_KEY.encode("utf-8"),
        TOKEN_PASSWORD.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()

    response = requests.post(
        SIJILAT_TOKEN_URL,
        data={
            "username": "sijilat",
            "password": encrypted_password,
            "grant_type": "password"
        },
        headers={
            "content-type": "application/x-www-form-urlencoded",
            "User-Agent": "Mozilla/5.0"
        },
        timeout=20
    )

    response.raise_for_status()
    data = response.json()

    return data.get("access_token")


def cryptojs_aes_encrypt(message):
    salt = os.urandom(8)
    key_iv = evp_bytes_to_key(AES_PASSWORD, salt, 32, 16)

    key = key_iv[:32]
    iv = key_iv[32:48]

    padded = pkcs7_pad(message.encode("utf-8"))

    cipher = AES.new(key, AES.MODE_CBC, iv)
    encrypted = cipher.encrypt(padded)

    return base64.b64encode(b"Salted__" + salt + encrypted).decode("utf-8")


def evp_bytes_to_key(password, salt, key_len, iv_len):
    dtot = b""
    d = b""

    while len(dtot) < key_len + iv_len:
        d = hashlib.md5(d + password + salt).digest()
        dtot += d

    return dtot[:key_len + iv_len]


def pkcs7_pad(data):
    block_size = 16
    pad_len = block_size - (len(data) % block_size)
    return data + bytes([pad_len]) * pad_len


def format_sijilat_data(data):
    summary = data.get("company_summary") or {}
    address = data.get("commercialAddress") or {}
    activities = data.get("businessActivities") or []

    return {
        "Company Summary": {
            "Commercial Name (EN)": summary.get("CR_LNM"),
            "Commercial Name (AR)": summary.get("CR_ANM"),
            "CR No.": "{0}-{1}".format(summary.get("CR_NO") or "", summary.get("BRANCH_NO") or ""),
            "CR Type": summary.get("CM_TYP_DESC"),
            "Registration Date": summary.get("REG_DATE"),
            "Expiration Date": summary.get("EXPIRE_DATE"),
            "Status": summary.get("STATUS"),
            "Financial Year End": summary.get("FN_YEAR_END"),
            "Nationality": summary.get("CR_NAT"),
        },

        "Business Activities": [
            {
                "ISIC4 Code": row.get("ISIC4_CD") or row.get("ACT_CD"),
                "Activity": row.get("ISIC4_NM") or ""
            }
            for row in activities
        ],

        "Commercial Address": {
            "Flat / Shop No.": address.get("CR_FLAT"),
            "Building": address.get("CR_BULD") or address.get("CR_BUILD"),
            "Road/Street Number": address.get("CR_ROAD") or address.get("CR_ROAD_NM"),
            "Block": address.get("CR_BLOCK"),
            "Town": address.get("CR_TOWN_NM") or address.get("CR_TOWN"),
            "P.O. Box": address.get("CR_PBOX"),
            "Website": address.get("CR_URL"),
            "eStore / eMarketPlace": address.get("CR_ESTORE_URL") or address.get("CR_E_MARKETPLACE"),
        }
    }



# SIJILAT INTEGRATION NOTES

# Purpose:
# Fetch Bahrain Commercial Registration (CR) details directly from Sijilat API and display inside ERPNext Customer.

# How Integration Works:

# 1. Obtain access token from:
#    https://api.sijilat.bh/token

# 2. Password is generated using:
#    HMAC-SHA256
#    Key:
#    UHxNtYMRYwvfpO1dS5pWLKL0M2DgOj40EbN4SoBWgfc

#    Password:
#    sijilat_test

# 3. Encrypt request body using:
#    CryptoJS AES
#    Key:
#    MySecretKey

# 4. Send encrypted request to:
#    https://api.sijilat.bh/api/CRdetails/CompleteCRDetails

# 5. Receive JSON response and map fields into ERPNext.

# Troubleshooting Checklist:

# If Fetch CR Details suddenly stops working:

# STEP 1 - Check Token API

# Run in bench console:

# response = requests.post(
# "https://api.sijilat.bh/token",
# ...
# )

# Expected:
# HTTP 200
# access_token returned

# If token fails:

# * Sijilat changed authentication
# * HMAC key changed
# * Password changed

# ---

# STEP 2 - Check Sijilat Website

# Open:
# https://www.sijilat.bh/public-search-cr/search-cr-3.aspx?cr_no=90666&branch_no=1

# Verify website still loads CR details.

# If website itself fails:
# Issue is on Sijilat side.

# ---

# STEP 3 - Check API Endpoint

# Open browser DevTools:

# Network
# → CompleteCRDetails

# Verify endpoint still exists:

# /api/CRdetails/CompleteCRDetails

# If changed:
# Update ERPNext endpoint.

# ---

# STEP 4 - Check Encryption Key

# Open browser DevTools:

# Sources
# → config.js

# Search:

# CryptoJS.AES.encrypt

# Current key:

# MySecretKey

# If key changed:
# Update Python encryption code.

# ---

# STEP 5 - Check Token Logic

# Open:

# config.js

# Search:

# tokenRequest

# Current values:

# username = sijilat
# password = sijilat_test

# HMAC key:
# UHxNtYMRYwvfpO1dS5pWLKL0M2DgOj40EbN4SoBWgfc

# If changed:
# Update Python token code.

# ---

# STEP 6 - Check Response Structure

# Temporarily log response:

# frappe.log_error(
# frappe.as_json(json_data, indent=2),
# "Sijilat Response Debug"
# )

# Compare keys with current mappings.

# Common fields currently used:

# company_summary:

# * CR_LNM
# * CR_ANM
# * CR_NO
# * BRANCH_NO
# * STATUS
# * REG_DATE
# * EXPIRE_DATE

# businessActivities:

# * ISIC4_CD
# * ISIC4_NM

# commercialAddress:

# * CR_BULD
# * CR_ROAD
# * CR_BLOCK
# * CR_TOWN_NM
# * CR_URL

# If fields change:
# Update format_sijilat_data() mapping only.

# ---

# Design Recommendation:

# Keep all Sijilat logic inside one file:

# worldshading/api/sijilat.py

# All Customer, Supplier, Service Visit, and Web Forms should call:

# fetch_cr_details()

# This ensures future Sijilat changes require modification in only one place.
