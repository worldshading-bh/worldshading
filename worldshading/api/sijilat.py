from __future__ import unicode_literals

import base64
import hashlib
import hmac
import json
import os

import frappe
import requests
from Crypto.Cipher import AES


SIJILAT_API = "https://api.sijilat.bh/api/"
SIJILAT_TOKEN_URL = "https://api.sijilat.bh/token"

HMAC_KEY = "UHxNtYMRYwvfpO1dS5pWLKL0M2DgOj40EbN4SoBWgfc"
TOKEN_PASSWORD = "sijilat_test"
AES_PASSWORD = b"MySecretKey"


@frappe.whitelist()
def fetch_cr_details(cr_no, branch_no=None):
    cr_no = str(cr_no or "").strip()

    if not cr_no:
        frappe.throw("CR No is required")

    if "-" in cr_no:
        cr_no, branch_no = cr_no.split("-", 1)

    cr_no = cr_no.strip()
    branch_no = str(branch_no or "1").strip()

    token = get_sijilat_token()

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

    encrypted_body = cryptojs_aes_encrypt(json.dumps(body, separators=(",", ":")))

    headers = {
        "Accept": "*/*",
        "Content-Type": "application/encrypted+json; charset=utf-8",
        "Authorization": "Bearer {0}".format(token),
        "Origin": "https://www.sijilat.bh",
        "Referer": "https://www.sijilat.bh/",
        "User-Agent": "Mozilla/5.0"
    }

    try:
        response = requests.post(
            SIJILAT_API + "CRdetails/CompleteCRDetails",
            data=encrypted_body,
            headers=headers,
            timeout=20
        )
        response.raise_for_status()
        result = response.json()
    except Exception as e:
        frappe.throw("Unable to fetch CR details from Sijilat API: {0}".format(e))

    if result.get("Status_Code") != "200":
        frappe.throw(result.get("Status_Message") or "Sijilat returned an error")

    json_data = result.get("jsonData") or {}

    return {
        "cr_no": cr_no,
        "branch_no": branch_no,
        "raw_api": json_data,
        "formatted": format_sijilat_data(json_data)
    }


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
