import frappe
from frappe.utils.pdf import get_pdf
from frappe.utils.jinja import render_template
from frappe.www.printview import get_print_format


# worldshading/api/public_pdf.py

import frappe
import hashlib
import hmac
import urllib.parse

SECRET_KEY = frappe.conf.get("encryption_key") or "default_secret"  # you can hardcode or keep in site_config.json

@frappe.whitelist()
def generate_secure_link(doctype, name, print_format):
    # Create a secure token
    message = f"{doctype}|{name}|{print_format}"
    token = hmac.new(SECRET_KEY.encode(), message.encode(), hashlib.sha256).hexdigest()

    # Build secure URL
    base = frappe.utils.get_url()
    params = {
        "doctype": doctype,
        "name": name,
        "format": print_format,
        "token": token
    }
    link = f"{base}/api/method/worldshading.api.public_pdf.download_secure_pdf?{urllib.parse.urlencode(params)}"
    return link


@frappe.whitelist(allow_guest=True)
def download_secure_pdf(doctype, name, format=None, no_letterhead=0, token=None):

    # Verify token
    secret = frappe.conf.get("encryption_key") or "default_secret"
    message = f"{doctype}|{name}|{format}"
    expected_token = hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()
    
    if token != expected_token:
        frappe.throw("🔒 Invalid or expired link")

    # Render PDF
    doc = frappe.get_doc(doctype, name)
    html = frappe.get_print(doctype, name, print_format=format, no_letterhead=frappe.utils.cint(no_letterhead))
    pdf_content = get_pdf(html)

    frappe.local.response.filename = f"{name}.pdf"
    frappe.local.response.filecontent = pdf_content
    frappe.local.response.type = "download"
