import frappe
import requests


def generate_ai_reply(customer_message):

    try:

        # ==================================================
        # AI SETTINGS
        # ==================================================

        settings = frappe.get_single("AI Settings")

        if not settings.enable:
            return None

        # ==================================================
        # FETCH KNOWLEDGE BASE
        # ==================================================

        knowledge_records = frappe.get_all(
            "Company Knowledge Base",
            filters={
                "active": 1
            },
            fields=[
                "title",
                "category",
                "key_words",
                "content"
            ]
        )

        # ==================================================
        # BUILD KNOWLEDGE TEXT
        # ==================================================

        knowledge_text = ""

        for row in knowledge_records:

            knowledge_text += f"""

Title: {row.title}
Category: {row.category}
Keywords: {row.key_words}

Content:
{row.content}

"""

        # ==================================================
        # FINAL PROMPT
        # ==================================================

        final_prompt = f"""
You are the AI assistant for World Shading Bahrain.

STRICT RULES:
- Answer ONLY from the COMPANY KNOWLEDGE below
- NEVER invent information
- NEVER assume services or policies
- If information is missing, reply exactly:
Please contact our sales team for more information.
- Keep replies short and professional
- Reply in the same language as the customer

====================
COMPANY KNOWLEDGE
====================

{knowledge_text}

====================
CUSTOMER MESSAGE
====================

{customer_message}

====================
YOUR REPLY
====================
"""

        # ==================================================
        # HEADERS
        # ==================================================

        headers = {
            "Authorization": "Bearer " + settings.get_password("api_key"),
            "Content-Type": "application/json"
        }

        # ==================================================
        # PAYLOAD
        # ==================================================

        payload = {
            "model": settings.ai_model,
            "messages": [
                {
                    "role": "user",
                    "content": final_prompt
                }
            ],
            "temperature": settings.temperature,
            "max_tokens": settings.max_tokens
        }

        # ==================================================
        # API REQUEST
        # ==================================================

        response = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers=headers,
            json=payload
        )

        result = response.json()

        # ==================================================
        # OPTIONAL DEBUG
        # ==================================================

        if settings.debug_mode:

            frappe.log_error(
                title="AI Debug",
                message=str(result)
            )

        # ==================================================
        # EXTRACT REPLY
        # ==================================================

        reply = result["choices"][0]["message"]["content"]

        return reply.strip()

    except Exception:

        frappe.log_error(
            title="AI Reply Error",
            message=frappe.get_traceback()
        )

        return "Please contact our sales team for assistance."