import frappe
import json
import requests
from werkzeug.wrappers import Response


@frappe.whitelist(allow_guest=True)
def webhook():

    # ==================================================
    # META VERIFICATION
    # ==================================================
    challenge = frappe.form_dict.get("hub.challenge")

    if challenge:
        return Response(challenge, status=200)


    # ==================================================
    # RECEIVE EVENTS
    # ==================================================
    try:

        data = json.loads(frappe.request.data)

        entries = data.get("entry", [])

        for entry in entries:

            changes = entry.get("changes", [])

            for change in changes:

                value = change.get("value", {})

                messages = value.get("messages", [])

                # Ignore delivery/read/status events
                if not messages:
                    continue


                for msg in messages:

                    from_number = msg.get("from")

                    if not from_number:
                        continue


                    # ==========================================
                    # SEND AUTO REPLY
                    # ==========================================
                    send_welcome_message(from_number)


        return Response("EVENT_RECEIVED", status=200)


    except Exception:

        frappe.log_error(
            frappe.get_traceback(),
            "WhatsApp Auto Reply Error"
        )

        return Response("ERROR", status=500)




# ==================================================
# SEND WELCOME MESSAGE
# ==================================================

def send_welcome_message(to_number):

    settings = frappe.get_single("WhatsApp Settings")

    url = (
        settings.base_url
        + "/"
        + settings.api_version
        + "/"
        + settings.phone_number_id
        + "/messages"
    )

    headers = {
        "Authorization": "Bearer " + settings.access_token,
        "Content-Type": "application/json"
    }

    message = (
        "Welcome to World Shading 🌟\n\n"
        "Bahrain’s leading supplier of shading materials "
        "and outdoor shading solutions.\n\n"
        "For sales enquiries, product support, and project "
        "assistance, please contact us directly using the "
        "details below:\n\n"
        "📞 Sales & Support: +973 17644117\n"
        "🌐 Website: www.worldshading.com\n\n"
        "Thank you.\n"
        "Have a nice day 😊"
    )

    payload = {
        "messaging_product": "whatsapp",
        "to": to_number,
        "type": "text",
        "text": {
            "body": message
        }
    }

    response = requests.post(
        url,
        headers=headers,
        json=payload
    )

    frappe.logger().info(response.text)



# using our knowledge base and ai_reply function
# import frappe
# import json
# import requests

# from werkzeug.wrappers import Response
# from worldshading.api.ai_reply import generate_ai_reply


# @frappe.whitelist(allow_guest=True)
# def webhook():

#     # ==================================================
#     # META VERIFICATION
#     # ==================================================

#     challenge = frappe.form_dict.get("hub.challenge")

#     if challenge:
#         return Response(challenge, status=200)

#     # ==================================================
#     # RECEIVE EVENTS
#     # ==================================================

#     try:

#         data = json.loads(frappe.request.data)

#         entries = data.get("entry", [])

#         for entry in entries:

#             changes = entry.get("changes", [])

#             for change in changes:

#                 value = change.get("value", {})

#                 messages = value.get("messages", [])

#                 # Ignore delivery/read/status events
#                 if not messages:
#                     continue

#                 for msg in messages:

#                     # ==================================================
#                     # ONLY TEXT MESSAGES
#                     # ==================================================

#                     if msg.get("type") != "text":
#                         continue

#                     from_number = msg.get("from")

#                     if not from_number:
#                         continue

#                     # ==================================================
#                     # MESSAGE TEXT
#                     # ==================================================

#                     customer_message = (
#                         msg.get("text", {})
#                         .get("body", "")
#                     ).strip()

#                     if not customer_message:
#                         continue

#                     # ==================================================
#                     # GENERATE AI REPLY
#                     # ==================================================

#                     ai_reply = generate_ai_reply(
#                         customer_message
#                     )

#                     if not ai_reply:
#                         continue

#                     # ==================================================
#                     # SEND REPLY
#                     # ==================================================

#                     send_whatsapp_message(
#                         from_number,
#                         ai_reply
#                     )

#         return Response("EVENT_RECEIVED", status=200)

#     except Exception:

#         frappe.log_error(
#             frappe.get_traceback(),
#             "WhatsApp AI Auto Reply Error"
#         )

#         return Response("ERROR", status=500)


# # ==================================================
# # SEND WHATSAPP MESSAGE
# # ==================================================

# def send_whatsapp_message(to_number, message):

#     settings = frappe.get_single("WhatsApp Settings")

#     url = (
#         settings.base_url
#         + "/"
#         + settings.api_version
#         + "/"
#         + settings.phone_number_id
#         + "/messages"
#     )

#     headers = {
#         "Authorization": "Bearer " + settings.access_token,
#         "Content-Type": "application/json"
#     }

#     payload = {
#         "messaging_product": "whatsapp",
#         "to": to_number,
#         "type": "text",
#         "text": {
#             "body": message
#         }
#     }

#     response = requests.post(
#         url,
#         headers=headers,
#         json=payload
#     )

#     frappe.logger().info(response.text)

# using gemini
# import frappe
# import json
# import requests
# from werkzeug.wrappers import Response


# # ==================================================
# # GEMINI SETTINGS
# # ==================================================

# GEMINI_API_KEY = "AIzaSyDndp_nl_yLUFJ3M0BtP9BrUIsPV9RomSs"

# GEMINI_URL = (
#     "https://generativelanguage.googleapis.com/v1beta/models/"
#     "gemini-3-flash-preview:generateContent?key="
#     + GEMINI_API_KEY
# )


# # ==================================================
# # COMPANY CONTEXT
# # ==================================================

# COMPANY_CONTEXT = """
# You are World Shading AI assistant.

# Company Information:
# - World Shading is based in Bahrain
# - We specialize in shade fabrics
# - We provide automatic awnings
# - We provide outdoor shading solutions

# Rules:
# - Keep replies short
# - Reply professionally
# - Only answer company-related questions
# - If unsure, ask customer to contact support
# """



# @frappe.whitelist(allow_guest=True)
# def webhook():

#     # ==================================================
#     # META VERIFICATION
#     # ==================================================

#     challenge = frappe.form_dict.get("hub.challenge")

#     if challenge:
#         return Response(challenge, status=200)



#     # ==================================================
#     # RECEIVE EVENTS
#     # ==================================================

#     try:

#         data = json.loads(frappe.request.data)

#         entries = data.get("entry", [])

#         for entry in entries:

#             changes = entry.get("changes", [])

#             for change in changes:

#                 value = change.get("value", {})

#                 messages = value.get("messages", [])

#                 if not messages:
#                     continue


#                 for msg in messages:

#                     from_number = msg.get("from")

#                     if not from_number:
#                         continue


#                     # ==========================================
#                     # GET CUSTOMER MESSAGE
#                     # ==========================================

#                     customer_message = ""

#                     if msg.get("text"):
#                         customer_message = (
#                             msg.get("text", {})
#                             .get("body", "")
#                         )

#                     if not customer_message:
#                         continue


#                     # ==========================================
#                     # AI REPLY
#                     # ==========================================

#                     ai_reply = get_ai_reply(customer_message)


#                     # ==========================================
#                     # SEND WHATSAPP REPLY
#                     # ==========================================

#                     send_whatsapp_text(
#                         from_number,
#                         ai_reply
#                     )


#         return Response("EVENT_RECEIVED", status=200)


#     except Exception:

#         frappe.log_error(
#             frappe.get_traceback(),
#             "WhatsApp AI Error"
#         )

#         return Response("ERROR", status=500)




# # ==================================================
# # GEMINI AI
# # ==================================================

# def get_ai_reply(customer_message):

#     try:

#         prompt = (
#             COMPANY_CONTEXT
#             + "\n\nCustomer Message:\n"
#             + customer_message
#         )

#         payload = {
#             "contents": [
#                 {
#                     "parts": [
#                         {
#                             "text": prompt
#                         }
#                     ]
#                 }
#             ]
#         }

#         headers = {
#             "Content-Type": "application/json"
#         }

#         response = requests.post(
#             GEMINI_URL,
#             headers=headers,
#             json=payload
#         )

#         result = response.json()

#         frappe.log_error(
#             title="Gemini Raw Response",
#             message=frappe.as_json(result)
#         )

#         return (
#             result["candidates"][0]
#             ["content"]["parts"][0]["text"]
#         )


#     except Exception:

#         frappe.log_error(
#             frappe.get_traceback(),
#             "Gemini AI Error"
#         )

#         return (
#             "Thank you for contacting World Shading. "
#             "Please contact our support team for assistance."
#         )




# # ==================================================
# # SEND WHATSAPP TEXT
# # ==================================================

# def send_whatsapp_text(to_number, message):

#     settings = frappe.get_single("WhatsApp Settings")

#     url = (
#         settings.base_url
#         + "/"
#         + settings.api_version
#         + "/"
#         + settings.phone_number_id
#         + "/messages"
#     )

#     headers = {
#         "Authorization": "Bearer " + settings.access_token,
#         "Content-Type": "application/json"
#     }

#     payload = {
#         "messaging_product": "whatsapp",
#         "to": to_number,
#         "type": "text",
#         "text": {
#             "body": message
#         }
#     }

#     requests.post(
#         url,
#         headers=headers,
#         json=payload
#     )