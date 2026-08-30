import frappe
import requests
from frappe.utils.pdf import get_pdf


def get_meta_url_buttons(components):
    """Return the URL-button metadata needed by the notification form."""
    buttons = []

    for component in components or []:
        if component.get("type") != "BUTTONS":
            continue

        for index, button in enumerate(component.get("buttons") or []):
            if button.get("type") != "URL":
                continue

            url = button.get("url") or ""
            buttons.append({
                "index": str(index),
                "text": button.get("text") or "",
                "url": url,
                "dynamic": "{{" in url and "}}" in url
            })

    return buttons


def get_meta_template_data(url, headers, request_get=None, max_pages=20):
    """Fetch Meta template pages with a hard bound against paging loops."""
    request_get = request_get or requests.get
    templates = []
    next_url = url
    visited = set()
    page = 0

    while next_url and page < max_pages and next_url not in visited:
        visited.add(next_url)
        response = request_get(
            next_url,
            headers=headers,
            params={"limit": 100} if page == 0 else None,
            timeout=10)

        if response.status_code != 200:
            frappe.throw("Meta API Error: {0}".format(response.text))

        result = response.json()
        templates.extend(result.get("data") or [])
        next_url = (result.get("paging") or {}).get("next")
        page += 1

    return templates


def build_template_payload(mobile, template_name, template_language,
    body_values=None, media_id=None, file_name=None, header_type=None,
    button_parameters=None):
    """Build a Meta template payload without performing an HTTP request."""
    components = []

    if header_type == "DOCUMENT" and media_id:
        components.append({
            "type": "header",
            "parameters": [{
                "type": "document",
                "document": {"id": media_id, "filename": file_name}
            }]
        })

    body_params = []
    for value in body_values or []:
        value = " ".join(str(value or "").replace("\n", " ").replace("\r", " ")
            .replace("\t", " ").split())
        body_params.append({"type": "text", "text": value})

    if body_params:
        components.append({"type": "body", "parameters": body_params})
    else:
        components.append({"type": "body"})

    for button in button_parameters or []:
        components.append({
            "type": "button",
            "sub_type": "url",
            "index": str(button.get("index", "0")),
            "parameters": [{"type": "text", "text": str(button.get("value") or "")}]
        })

    return {
        "messaging_product": "whatsapp",
        "to": mobile,
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": template_language or "en_US"},
            "components": components
        }
    }



# @frappe.whitelist()
# def send_whatsapp_template_with_pdf(mobile, docname, doctype):
#     frappe.enqueue(
#         method=_send_whatsapp_template_with_pdf_logic,
#         queue='default',
#         timeout=300,
#         mobile=mobile,
#         docname=docname,
#         doctype=doctype
#     )
#     frappe.msgprint("✅ WhatsApp message queued successfully.")


# import frappe
# import requests
# from frappe.utils.pdf import get_pdf


# def _send_whatsapp_template_with_pdf_logic(mobile, docname, doctype):

#     try:
#         # ==================================================
#         # 🔧 Load Settings
#         # ==================================================
#         settings = frappe.get_single("WhatsApp Settings")

#         if not settings.enabled:
#             frappe.logger().info("WhatsApp is disabled")
#             return

#         access_token = settings.access_token
#         phone_number_id = settings.phone_number_id
#         api_version = settings.api_version or "v25.0"
#         base_url = settings.base_url or "https://graph.facebook.com"
#         template_name = settings.default_template or "invoice"
#         country_code = settings.default_country_code or "973"

#         base_api = f"{base_url}/{api_version}/{phone_number_id}"

#         # ==================================================
#         # 📱 Format Mobile
#         # ==================================================
#         mobile = format_mobile_number(mobile, country_code)

#         # ==================================================
#         # 📄 Load Document (DYNAMIC)
#         # ==================================================
#         doc = frappe.get_doc(doctype, docname)
#         file_name = f"{docname}.pdf"

#         # ==================================================
#         # 🧾 CREATE LOG FIRST (Queued)
#         # ==================================================
#         log = frappe.get_doc({
#             "doctype": "WhatsApp Log",
#             "reference_doctype": doc.doctype,
#             "reference_name": doc.name,
#             "mobile": mobile,
#             "template": template_name,
#             "status": "Queued",
#             "sent_on": frappe.utils.now()
#         }).insert(ignore_permissions=True)

#         # ==================================================
#         # 📄 Generate PDF (DYNAMIC)
#         # ==================================================
#         print_format = settings.print_format

#         html = frappe.get_print(
#             doctype,
#             docname,
#             print_format if print_format else None,
#             doc=doc
#         )

#         if not html:
#             frappe.log_error("Print HTML failed", "WhatsApp PDF")

#             log.db_set({
#                 "status": "Failed",
#                 "error": "Print HTML failed"
#             })
#             return

#         pdf_data = get_pdf(html)

#         # ==================================================
#         # ☁️ Upload PDF to Meta
#         # ==================================================
#         media_id = upload_pdf_to_meta(pdf_data, file_name, access_token, base_api)

#         if not media_id:
#             log.db_set({
#                 "status": "Failed",
#                 "error": "Media upload failed"
#             })
#             return

#         # ==================================================
#         # 💬 Send Template
#         # ==================================================
#         success, message_id, response = send_template_message(
#             mobile,
#             template_name,
#             doc,
#             media_id,
#             file_name,
#             access_token,
#             base_api,
#             settings.debug_mode
#         )

#         # ==================================================
#         # ✅ SUCCESS
#         # ==================================================
#         if success:
#             log.db_set({
#                 "status": "Sent",
#                 "message_id": message_id,
#                 "media_id": media_id,
#                 "response": frappe.as_json(response)
#             })

#             doc.add_comment(
#                 "Comment",
#                 f"✅ WhatsApp sent to {mobile}<br>Message ID: {message_id}"
#             )

#         # ==================================================
#         # ❌ FAILURE
#         # ==================================================
#         else:
#             log.db_set({
#                 "status": "Failed",
#                 "response": frappe.as_json(response),
#                 "error": str(response)
#             })

#             doc.add_comment(
#                 "Comment",
#                 f"❌ WhatsApp failed for {mobile}<br>Check WhatsApp Log"
#             )

#     except Exception:
#         frappe.log_error(frappe.get_traceback(), "WhatsApp Send Failed")


# def format_mobile_number(mobile, country_code):
#     mobile = (mobile or "").strip()

#     mobile = mobile.replace("+", "").replace(" ", "").replace("-", "")

#     mobile = ''.join(filter(str.isdigit, mobile))

#     if mobile.startswith("0"):
#         mobile = mobile[1:]

#     if not mobile.startswith(country_code):
#         mobile = country_code + mobile

#     return mobile

# def upload_pdf_to_meta(pdf_data, file_name, access_token, base_api):

#     files = {
#         'file': (file_name, pdf_data, 'application/pdf'),
#         'type': (None, 'application/pdf'),
#         'messaging_product': (None, 'whatsapp')
#     }

#     response = requests.post(
#         f"{base_api}/media",
#         headers={"Authorization": f"Bearer {access_token}"},
#         files=files
#     )

#     result = response.json()

#     if "id" not in result:
#         frappe.log_error(result, "Meta Upload Failed")
#         return None

#     frappe.logger().info(f"📄 Media uploaded: {result['id']}")
#     return result["id"]


# def send_template_message(
#     mobile,
#     template_name,
#     doc,
#     media_id,
#     file_name,
#     access_token,
#     base_api,
#     debug=False
# ):

#     payload = {
#         "messaging_product": "whatsapp",
#         "to": mobile,
#         "type": "template",
#         "template": {
#             "name": template_name,
#             "language": { "code": "en_US" },
#             "components": [
#                 {
#                     "type": "header",
#                     "parameters": [
#                         {
#                             "type": "document",
#                             "document": {
#                                 "id": media_id,
#                                 "filename": file_name
#                             }
#                         }
#                     ]
#                 },
#                 {
#                     "type": "body",
#                     "parameters": [
#                         { "type": "text", "text": doc.customer_name or "Customer" },
#                         { "type": "text", "text": doc.name }
#                     ]
#                 }
#             ]
#         }
#     }

#     if debug:
#         frappe.logger().info(f"📤 Payload: {payload}")

#     response = requests.post(
#         f"{base_api}/messages",
#         headers={
#             "Authorization": f"Bearer {access_token}",
#             "Content-Type": "application/json"
#         },
#         json=payload
#     )

#     result = response.json()

#     frappe.logger().info(f"📩 Response: {result}")

#     # ✅ SUCCESS CHECK
#     if "messages" in result:
#         message_id = result["messages"][0].get("id")
#         return True, message_id, result

#     # ❌ FAILURE
#     return False, None, result


def handle_whatsapp_event(doc, method):

    try:
        # Global WhatsApp OFF
        settings = frappe.get_single("WhatsApp Settings")
        if not settings.enabled:
            return
        
        # Skip bulk import
        if frappe.flags.in_import:
            return
        
        # Skip system + internal doctypes
        skip_doctypes = [
            "Activity Log",
            "Version",
            "Comment",
            "Communication",
            "ToDo",
            "Email Queue",
            "Notification Log",
            "Error Log",
            "WhatsApp Log",
            "WhatsApp Notification"
        ]

        if doc.doctype in skip_doctypes:
            return

        # Skip child table doctypes
        if getattr(doc.meta, "istable", 0):
            return

        # Find matching configs before reading workflow fields
        configs = frappe.get_all(
            "WhatsApp Notification",
            filters={
                "enable": 1,
                "reference_doctype": doc.doctype,
                "trigger_event": method
            },
            fields=["name"]
        )

        if not configs:
            return

        # ==================================================
        # Workflow transition context
        # ==================================================
        previous_doc = None
        previous_state = None
        current_state = None

        if method == "on_update_after_submit":

            previous_doc = doc.get_doc_before_save()
            current_state = doc.get("workflow_state")
            if previous_doc:
                previous_state = previous_doc.get("workflow_state")

        # Debug log
        frappe.logger().info(f"WA Trigger → {doc.doctype} → {method}")

        for c in configs:

            # 🔍 Load notification
            notification = frappe.get_doc("WhatsApp Notification", c.name)

            # 🧠 Evaluate condition
            if notification.condition:

                try:
                    if not frappe.safe_eval(
                        notification.condition,
                        None,
                        {
                            "doc": doc,
                            "previous_doc": previous_doc,
                            "previous_state": previous_state,
                            "current_state": current_state
                        }
                    ):
                        continue

                except Exception:
                    frappe.log_error(
                        frappe.get_traceback(),
                        f"WhatsApp Condition Failed: {notification.name}"
                    )
                    continue

            # Prevent duplicate sends (Queued + Sent)
            existing = frappe.get_all(
                "WhatsApp Log",
                filters={
                    "reference_doctype": doc.doctype,
                    "reference_name": doc.name,
                    "template": c.name,
                    "status": ["in", ["Queued", "Sent"]]
                },
                limit=1
            )

            if existing:
                continue

            frappe.enqueue(
                method="worldshading.api.whatsapp._send_whatsapp_from_notification_logic",
                queue='default',
                timeout=300,
                enqueue_after_commit=True,
                notification_name=c.name,
                docname=doc.name,
                doctype=doc.doctype
            )

    except Exception:
        frappe.log_error(frappe.get_traceback(), "WhatsApp Event Handler Failed")




def _send_whatsapp_from_notification_logic(
    notification_name,
    docname,
    doctype,
    manual_mobile_no=None
):
    log = None

    try:
        #Load Config
        config = frappe.get_doc("WhatsApp Notification", notification_name)

        if not config.enable:
            return

        #Load Document
        doc = frappe.get_doc(doctype, docname)

        #Get Mobile
        if manual_mobile_no:
            mobile = manual_mobile_no

        # Fallback to notification config field
        else:
            mobile = doc.get(config.mobile_field)

        if not mobile:
            frappe.get_doc({
                "doctype": "WhatsApp Log",
                "reference_doctype": doc.doctype,
                "reference_name": doc.name,
                "mobile": "",
                "template": config.meta_template,
                "status": "Failed",
                "error": "Mobile not found"
            }).insert(ignore_permissions=True)
            return

        #Load Settings
        settings = frappe.get_single("WhatsApp Settings")

        access_token = settings.access_token
        phone_number_id = settings.phone_number_id
        api_version = settings.api_version or "v25.0"
        base_url = settings.base_url or "https://graph.facebook.com"
        country_code = get_whatsapp_country_code(
            doc,
            config.mobile_field,
            settings.default_country_code or "973"
        )

        base_api = f"{base_url}/{api_version}/{phone_number_id}"

        mobile = format_mobile_number(mobile, country_code)

        template_name = config.meta_template
        if not template_name:
            return

        file_name = f"{docname}.pdf"

        #CREATE LOG
        log = frappe.get_doc({
            "doctype": "WhatsApp Log",
            "reference_doctype": doc.doctype,
            "reference_name": doc.name,
            "mobile": mobile,
            "template": template_name,
            "status": "Queued",
            "sent_on": frappe.utils.now()
        }).insert(ignore_permissions=True)

        #Generate PDF
        media_id = None

        if config.header_type == "DOCUMENT":

            html = frappe.get_print(
                doc.doctype,
                doc.name,
                config.print_format,
                doc=doc
            )

            pdf_data = get_pdf(html)

            media_id = upload_pdf_to_meta(
                pdf_data,
                file_name,
                access_token,
                base_api
            )

            if not media_id:
                log.db_set({"status": "Failed", "error": "Media upload failed"})
                return

        #Build Variables
        variables = []

        for row in sorted(config.message_fields, key=lambda x: x.idx):
            value = doc.get(row.field_name) or ""
            variables.append(str(value))

        #Language
        language = config.template_language or "en_US"

        button_parameters = []
        if config.get("button_parameter_field"):
            button_value = doc.get(config.button_parameter_field)
            if button_value in (None, ""):
                frappe.throw(
                    "WhatsApp URL button field {0} is empty".format(
                        config.button_parameter_field))
            button_parameters.append({
                "index": config.get("button_index") or 0,
                "value": button_value
            })

        #Send Message
        success, message_id, response = send_dynamic_template_message(
            mobile,
            template_name,
            variables,
            media_id,
            file_name,
            access_token,
            base_api,
            settings.debug_mode,
            config.header_type,
            language,
            button_parameters
        )

        #SUCCESS
        if success:
            log.db_set({
                "status": "Sent",
                "message_id": message_id,
                "media_id": media_id,
                "response": frappe.as_json(response)
            })

            doc.add_comment(
                "Comment",
                f"✅ WhatsApp sent via {notification_name}<br>To: {mobile}"
            )

        else:
            log.db_set({
                "status": "Failed",
                "response": frappe.as_json(response)
            })

    except Exception:
        frappe.log_error(frappe.get_traceback(), "WhatsApp Send Failed")
        if log:
            log.db_set({
                "status": "Failed",
                "error": frappe.get_traceback()
            })


def send_dynamic_template_message(
    mobile,
    template_name,
    variables,
    media_id,
    file_name,
    access_token,
    base_api,
    debug,
    header_type,
    template_language,
    button_parameters=None
):
    payload = build_template_payload(
        mobile, template_name, template_language, variables, media_id,
        file_name, header_type, button_parameters)

    if debug:
        frappe.logger().info({
            "template": template_name,
            "mobile": mobile,
            "variables": variables
        })

    try:
        response = requests.post(
            f"{base_api}/messages",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json"
            },
            json=payload,
            timeout=15
        )

        if response.status_code != 200:
            return False, None, {
                "http_status": response.status_code,
                "error": response.text
            }

        result = response.json()

        if "messages" in result:
            return True, result["messages"][0].get("id"), result

        return False, None, result

    except Exception as e:
        return False, None, {"error": str(e)}
    



def get_whatsapp_country_code(doc, mobile_field, default_country_code):
    country_code_field = None

    if mobile_field == "whatsapp_no":
        country_code_field = "whatsapp_country_code"
    elif mobile_field in ("mobile_number", "mobile_no", "contact_mobile"):
        country_code_field = "mobile_country_code"

    if country_code_field:
        country_code = doc.get(country_code_field)
        if country_code:
            return country_code

    if doc.get("whatsapp_country_code"):
        return doc.get("whatsapp_country_code")

    if doc.get("mobile_country_code"):
        return doc.get("mobile_country_code")

    return default_country_code


def get_digits_only(value):
    digits = ""

    for ch in (value or ""):
        if ch.isdigit():
            digits = digits + ch

    return digits


def format_mobile_number(mobile, country_code):
    raw_mobile = (mobile or "").strip()
    explicit_international = raw_mobile.startswith("+") or raw_mobile.startswith("00")

    # Remove common symbols
    mobile = raw_mobile.replace("+", "").replace(" ", "").replace("-", "")

    # Keep only digits
    mobile = get_digits_only(mobile)

    # Remove leading 00 (international format)
    if mobile.startswith("00"):
        mobile = mobile[2:]

    if explicit_international:
        return mobile

    # Remove leading zero (local format)
    if mobile.startswith("0"):
        mobile = mobile[1:]

    known_country_codes = ["973", "966", "971", "965", "968", "974"]
    for known_country_code in known_country_codes:
        if mobile.startswith(known_country_code):
            return mobile

    country_code = get_digits_only(country_code)
    if not country_code:
        country_code = "973"

    # Add country code if missing
    if not mobile.startswith(country_code):
        mobile = country_code + mobile

    return mobile


def upload_pdf_to_meta(pdf_data, file_name, access_token, base_api):

    try:
        files = {
            'file': (file_name, pdf_data, 'application/pdf'),
            'type': (None, 'application/pdf'),
            'messaging_product': (None, 'whatsapp')
        }

        response = requests.post(
            f"{base_api}/media",
            headers={"Authorization": f"Bearer {access_token}"},
            files=files,
            timeout=15  
        )

        if response.status_code != 200:
            frappe.log_error(response.text, "Meta Upload Failed")
            return None

        result = response.json()

        if "id" not in result:
            frappe.log_error(frappe.as_json(result), "Meta Upload Failed")
            return None

        frappe.logger().info(f"📄 Media uploaded: {result['id']}")
        return result["id"]

    except Exception:
        frappe.log_error(frappe.get_traceback(), "Meta Upload Exception")
        return None




@frappe.whitelist()
def fetch_meta_templates():

    try:
        settings = frappe.get_single("WhatsApp Settings")

        if not settings.enabled:
            frappe.throw("WhatsApp is disabled")

        access_token = settings.access_token
        waba_id = settings.business_id
        api_version = settings.api_version or "v25.0"
        base_url = settings.base_url or "https://graph.facebook.com"

        url = f"{base_url}/{api_version}/{waba_id}/message_templates"

        headers = {
            "Authorization": f"Bearer {access_token}"
        }

        templates = []

        for t in get_meta_template_data(url, headers):

            # ✅ Only approved templates
            if t.get("status") != "APPROVED":
                continue

            name = t.get("name")

            # 🔹 Handle language safely
            language = t.get("language")
            if isinstance(language, dict):
                language = language.get("code")

            body_text = ""
            footer_text = ""      # 👈 NEW
            header_type = None
            buttons = []

            # 🔍 Extract components
            for comp in t.get("components", []):

                # BODY
                if comp.get("type") == "BODY":
                    body_text = comp.get("text", "")

                # HEADER
                if comp.get("type") == "HEADER":
                    header_type = comp.get("format")  # DOCUMENT / TEXT / IMAGE

                # FOOTER 
                if comp.get("type") == "FOOTER":
                    footer_text = comp.get("text", "")

            buttons = get_meta_url_buttons(t.get("components", []))

            templates.append({
                "name": name,
                "language": language,
                "body": body_text,
                "footer": footer_text,                    
                "header_type": header_type or "NONE",
                "buttons": buttons
            })

        return templates

    except Exception:
        frappe.log_error(frappe.get_traceback(), "Fetch Meta Templates Failed")
        return []
    




# Manual button to trigger WhatsApp from UI (for testing + one-off sends)
@frappe.whitelist()
def send_whatsapp_notification(
    notification_name,
    doctype,
    docname,
    mobile_no=None
):

    try:

        # 🚫 Global WhatsApp OFF
        settings = frappe.get_single("WhatsApp Settings")

        if not settings.enabled:
            frappe.throw("WhatsApp is disabled")

        # 🔍 Validate notification
        notification = frappe.get_doc(
            "WhatsApp Notification",
            notification_name
        )

        if not notification.enable:
            frappe.throw("WhatsApp Notification is disabled")

        # 🚫 Prevent duplicate sends
        # existing = frappe.get_all(
        #     "WhatsApp Log",
        #     filters={
        #         "reference_doctype": doctype,
        #         "reference_name": docname,
        #         "template": notification_name,
        #         "status": ["in", ["Queued", "Sent"]]
        #     },
        #     limit=1
        # )

        # if existing:
        #     frappe.msgprint("WhatsApp already queued/sent")
        #     return

        # 🚀 Queue SAME core engine
        frappe.enqueue(
            method="worldshading.api.whatsapp._send_whatsapp_from_notification_logic",
            queue='default',
            timeout=300,
            notification_name=notification_name,
            docname=docname,
            doctype=doctype,
            manual_mobile_no=mobile_no
        )

        return "Queued"

    except Exception:
        frappe.log_error(
            frappe.get_traceback(),
            "Manual WhatsApp Send Failed"
        )

        frappe.throw("Failed to queue WhatsApp")
