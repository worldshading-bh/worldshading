import frappe
import random
import requests
import base64
from frappe.utils import now_datetime, add_to_date

# ============================================================
# SEND OTP
# ============================================================
@frappe.whitelist(allow_guest=True)
def send_otp(mobile):
    if not mobile:
        return {"status": "error", "message": "Mobile number is required"}

    # Generate OTP
    otp = str(random.randint(100000, 999999))

    # Store OTP in cache (expires in 3 minutes)
    frappe.cache().set_value(f"otp_{mobile}", otp, expires_in_sec=180)

    # Get Twilio API Settings
    settings = frappe.get_single("API Settings")

    sid = settings.twilio_account_sid
    token = settings.twilio_auth_token
    from_number = settings.twilio_phone_number
    template = settings.otp_message_template or "Your OTP is {otp}"

    msg = template.replace("{otp}", otp)

    # Twilio API URL
    url = f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"
    auth_header = base64.b64encode(f"{sid}:{token}".encode()).decode()

    payload = {"From": from_number, "To": f"+{mobile}", "Body": msg}
    headers = {"Authorization": "Basic " + auth_header}

    # Send SMS
    response = requests.post(url, data=payload, headers=headers)

    if response.status_code not in (200, 201):
        frappe.log_error(response.text, "Twilio OTP Error")
        return {"status": "error", "message": "Failed to send OTP"}

    return {"status": "success", "message": "OTP sent successfully"}






# ============================================================
# VERIFY OTP
# ============================================================
# @frappe.whitelist(allow_guest=True)
# def verify_otp(mobile, otp):
#     if not mobile or not otp:
#         return {"status": "error", "message": "Mobile and OTP are required"}

#     # Get the most recent OTP record
#     records = frappe.db.get_all(
#         "OTP Log",
#         fields=["name", "otp", "expiry", "verified"],
#         filters={"mobile": mobile},
#         order_by="creation desc",
#         limit=1
#     )

#     if not records:
#         return {"status": "error", "message": "No OTP found for this number"}

#     log = records[0]

#     # 1. Check if OTP already used
#     if log.verified:
#         return {"status": "error", "message": "This OTP has already been used"}

#     # 2. Check if OTP matches
#     if otp != log.otp:
#         return {"status": "error", "message": "Invalid OTP"}

#     # 3. Check expiry
#     if now_datetime() > log.expiry:
#         return {"status": "error", "message": "OTP has expired"}

#     # 4. Mark OTP as verified
#     frappe.db.set_value("OTP Log", log.name, "verified", 1)

#     return {"status": "success", "verified": 1, "message": "OTP verified successfully"}



@frappe.whitelist(allow_guest=True)
def verify_otp(mobile, otp):
    if not mobile or not otp:
        return {"status": "error", "message": "Mobile and OTP required"}

    cached_otp = frappe.cache().get_value(f"otp_{mobile}")

    if not cached_otp:
        return {"status": "error", "message": "OTP expired or not found"}

    if str(cached_otp) != str(otp):
        return {"status": "error", "message": "Invalid OTP"}

    # Clear OTP after successful verification
    frappe.cache().delete_value(f"otp_{mobile}")

    return {"status": "success", "message": "OTP verified successfully"}
