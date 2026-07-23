import base64
import json
from html.parser import HTMLParser

import frappe
import requests
from frappe.utils import nowdate


REPO = "worldshading-bh/worldshading_portfolio"
BRANCH = "main"

MAX_HTML_BYTES = 80 * 1024
MAX_TEXT_CHARS = 25000

BLOCKED_TAGS = {
    "script",
    "iframe",
    "object",
    "embed",
    "form",
    "input",
    "button",
    "textarea",
    "select",
    "style",
}

PAGE_MAP = {
    "terms-and-conditions": {
        "title": "Terms & Conditions",
        "path": "src/content/legal/terms-and-conditions.json",
    },
    "privacy-policy": {
        "title": "Privacy Policy",
        "path": "src/content/legal/privacy-policy.json",
    },
    "refund-policy": {
        "title": "Cancellation & Refund Policy",
        "path": "src/content/legal/refund-policy.json",
    },
    "delivery-policy": {
        "title": "Shipment & Delivery Policy",
        "path": "src/content/legal/delivery-policy.json",
    },
}


class PolicyHTMLValidator(HTMLParser):
    def __init__(self):
        super().__init__()
        self.blocked_tags_found = set()
        self.text_parts = []

    def handle_starttag(self, tag, attrs):
        tag_name = tag.lower()
        if tag_name in BLOCKED_TAGS:
            self.blocked_tags_found.add(tag_name)

    def handle_startendtag(self, tag, attrs):
        tag_name = tag.lower()
        if tag_name in BLOCKED_TAGS:
            self.blocked_tags_found.add(tag_name)

    def handle_data(self, data):
        self.text_parts.append(data)


def validate_policy_html(content_html):
    if not content_html or not content_html.strip():
        frappe.throw("Terms and Conditions content is empty.")

    html_size = len(content_html.encode("utf-8"))
    if html_size > MAX_HTML_BYTES:
        frappe.throw(
            f"Policy content is too large. Maximum allowed size is {MAX_HTML_BYTES // 1024} KB."
        )

    parser = PolicyHTMLValidator()
    parser.feed(content_html)

    if parser.blocked_tags_found:
        blocked = ", ".join(f"<{tag}>" for tag in sorted(parser.blocked_tags_found))
        frappe.throw(f"Policy content contains blocked HTML tags: {blocked}")

    plain_text = " ".join(part.strip() for part in parser.text_parts if part.strip())
    if len(plain_text) > MAX_TEXT_CHARS:
        frappe.throw(
            f"Policy text is too long. Maximum allowed length is {MAX_TEXT_CHARS} characters."
        )


def get_existing_github_json(existing_file_response):
    existing_data = existing_file_response.json()
    existing_content = existing_data.get("content")

    if not existing_content:
        return {}

    try:
        decoded = base64.b64decode(existing_content).decode("utf-8")
        return json.loads(decoded)
    except Exception:
        return {}


@frappe.whitelist()
def publish_terms_to_website(docname, page):
    if not frappe.has_role("System Manager"):
        frappe.throw("Only System Manager can publish website policies.")
    if not frappe.has_permission("Terms and Conditions", "write", docname):
        frappe.throw("You do not have permission to publish this document.")

    if page not in PAGE_MAP:
        frappe.throw("Invalid website page selected.")

    token = frappe.conf.get("github_website_token")
    if not token:
        frappe.throw("GitHub token is not configured in site_config.json.")

    doc = frappe.get_doc("Terms and Conditions", docname)

    content_html = doc.get("terms")
    validate_policy_html(content_html)

    page_info = PAGE_MAP[page]
    file_path = page_info["path"]

    website_json = {
        "title": page_info["title"],
        "slug": page,
        "last_updated": nowdate(),
        "content_html": content_html,
    }

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    file_url = f"https://api.github.com/repos/{REPO}/contents/{file_path}"

    existing_file = requests.get(
        file_url,
        headers=headers,
        params={"ref": BRANCH},
        timeout=30,
    )

    if existing_file.status_code != 200:
        frappe.log_error(existing_file.text, "Website Policy GitHub Read Failed")
        frappe.throw("Could not read the existing website policy file from GitHub.")

    existing_json = get_existing_github_json(existing_file)

    if existing_json.get("content_html") == content_html:
        return {
            "message": f"No changes detected. {page_info['title']} is already up to date.",
            "commit_sha": None,
        }

    encoded_content = base64.b64encode(
        json.dumps(website_json, ensure_ascii=False, indent=2).encode("utf-8")
    ).decode("utf-8")

    file_sha = existing_file.json().get("sha")

    update_payload = {
        "message": f"Update {page_info['title']} from ERPNext",
        "content": encoded_content,
        "sha": file_sha,
        "branch": BRANCH,
    }

    updated_file = requests.put(
        file_url,
        headers=headers,
        json=update_payload,
        timeout=30,
    )

    if updated_file.status_code not in (200, 201):
        frappe.log_error(updated_file.text, "Website Policy GitHub Update Failed")
        frappe.throw("Could not update the website policy file in GitHub.")

    commit_sha = updated_file.json().get("commit", {}).get("sha")

    return {
        "message": f"{page_info['title']} published successfully. Cloudflare should rebuild shortly.",
        "commit_sha": commit_sha,
    }