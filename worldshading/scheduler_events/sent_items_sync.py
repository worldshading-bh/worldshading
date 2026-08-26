# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import imaplib
import re
import time
from email.utils import parseaddr

import frappe
from frappe.email.queue import prepare_message
from frappe.utils import now_datetime


MAX_MESSAGES_PER_RUN = 100
ERROR_COOLDOWN_SECONDS = 3600


def sync_sent_items():
    """Copy successfully sent ERPNext emails to their mailbox Sent folder.

    SMTP delivery remains independent of this task. A failed IMAP copy is
    logged and retried on a later run. The original Message-ID is searched
    before APPEND so retries do not create duplicate Sent Items.
    """
    accounts = frappe.get_all(
        "Email Account",
        filters={
            "custom_sync_sent_items": 1,
            "enable_outgoing": 1,
            "awaiting_password": 0,
        },
        fields=["name"],
        order_by="name asc",
    )
    for row in accounts:
        _sync_account(row.name)


def _sync_account(account_name):
    client = None

    try:
        account = frappe.get_doc("Email Account", account_name)
        if not _account_is_ready(account):
            return

        if not account.custom_sent_items_last_sync:
            _set_checkpoint(account, now_datetime())
            return

        client = _connect(account)
        sent_folder = _resolve_sent_folder(
            client, account.custom_sent_items_folder
        )
        _select_sent_folder(client, sent_folder)
        _clear_error_throttle("account:{0}".format(account_name))

        queue_rows = frappe.get_all(
            "Email Queue",
            filters={
                "status": "Sent",
                "modified": (">", account.custom_sent_items_last_sync),
                "sender": ("like", "%{0}%".format(account.email_id)),
            },
            fields=["name", "sender", "message_id", "modified"],
            order_by="modified asc",
            limit_page_length=MAX_MESSAGES_PER_RUN,
        )

        for queue_row in queue_rows:
            sender_email = parseaddr(queue_row.sender or "")[1].lower()
            if sender_email != (account.email_id or "").lower():
                continue

            try:
                _append_queue_message(client, sent_folder, queue_row)
                _set_checkpoint(account, queue_row.modified)
                _clear_error_throttle("queue:{0}".format(queue_row.name))
            except Exception:
                _log_error_once(
                    "queue:{0}".format(queue_row.name),
                    "Sent Items Sync Failed: {0}".format(queue_row.name),
                )
                break

    except Exception:
        _log_error_once(
            "account:{0}".format(account_name),
            "Sent Items IMAP Connection Failed: {0}".format(account_name),
        )
    finally:
        if client:
            try:
                client.logout()
            except Exception:
                pass


def _account_is_ready(account):
    return bool(
        account.enable_outgoing
        and not account.awaiting_password
        and account.use_imap
        and account.email_server
        and account.email_id
        and account.custom_sync_sent_items
    )


def _connect(account):
    port = int(account.incoming_port or (993 if account.use_ssl else 143))
    login_id = account.login_id if account.login_id_is_different else account.email_id
    password = account.get_password()

    if account.use_ssl:
        client = imaplib.IMAP4_SSL(account.email_server, port)
    else:
        client = imaplib.IMAP4(account.email_server, port)

    status, response = client.login(login_id, password)
    if status != "OK":
        raise RuntimeError("IMAP login failed: {0}".format(response))

    return client


def _resolve_sent_folder(client, configured_folder=None):
    folders = _get_imap_folders(client)
    if not configured_folder:
        for folder in folders:
            if b"\\Sent" in folder["flags"]:
                return folder["name"]
        raise RuntimeError(
            "No IMAP folder marked as Sent was found. Set Sent Items Folder."
        )

    configured_folder = configured_folder.strip()
    existing_names = [folder["name"] for folder in folders]
    if configured_folder in existing_names:
        return configured_folder

    # A friendly name such as "ERPNext Sent" is stored in Email Account. On
    # servers whose personal namespace is under INBOX, resolve it to the real
    # IMAP path (for this server: INBOX.ERPNext Sent).
    inbox = next((folder for folder in folders
        if folder["name"].upper() == "INBOX"), None)
    if inbox and not configured_folder.upper().startswith("INBOX"):
        delimiter = inbox["delimiter"] or "."
        folder_name = "INBOX{0}{1}".format(delimiter, configured_folder)
    else:
        folder_name = configured_folder

    if folder_name not in existing_names:
        mailbox_arg = _imap_mailbox_arg(folder_name)
        status, response = client.create(mailbox_arg)
        already_exists = any(
            b"ALREADYEXISTS" in item.upper()
            for item in (response or []) if isinstance(item, bytes)
        )
        if status != "OK" and not already_exists:
            raise RuntimeError(
                "Unable to create IMAP folder {0}: {1}".format(
                    folder_name, response
                )
            )

        # Some clients show only subscribed folders. A server may subscribe
        # automatically, so subscription failure must not block email copies.
        try:
            client.subscribe(mailbox_arg)
        except Exception:
            pass

    return folder_name


def _get_imap_folders(client):
    status, folders = client.list()
    if status != "OK":
        raise RuntimeError("Unable to list IMAP folders: {0}".format(folders))

    parsed_folders = []
    for raw_folder in folders or []:
        flags = imaplib.ParseFlags(raw_folder)
        folder_text = raw_folder.decode("utf-8", "replace")
        match = re.match(
            r'^\([^)]*\)\s+(?:"([^"]*)"|NIL)\s+(.+)$',
            folder_text
        )
        if match:
            parsed_folders.append({
                "flags": flags,
                "delimiter": match.group(1),
                "name": match.group(2).strip('"'),
            })

    return parsed_folders


def _select_sent_folder(client, sent_folder):
    status, response = client.select(
        _imap_mailbox_arg(sent_folder), readonly=True
    )
    if status != "OK":
        raise RuntimeError(
            "Unable to select IMAP Sent folder {0}: {1}".format(
                sent_folder, response
            )
        )


def _append_queue_message(client, sent_folder, queue_row):
    message_id = (queue_row.message_id or "").strip(" <>")
    if not message_id:
        raise RuntimeError("Email Queue message has no Message-ID")

    if _message_exists(client, message_id):
        return

    queue_doc = frappe.get_doc("Email Queue", queue_row.name)
    # ERPNext/Frappe v12 stores this field as ``unsubscribe_param`` in the
    # DocType, while frappe.email.queue.prepare_message expects the plural
    # compatibility attribute used by its SQL-loaded queue row.
    queue_doc.unsubscribe_params = queue_doc.get("unsubscribe_param")
    recipients = frappe.get_all(
        "Email Queue Recipient",
        filters={"parent": queue_row.name},
        fields=["recipient", "status", "idx"],
        order_by="idx asc",
    )
    if not recipients:
        raise RuntimeError("Email Queue message has no recipients")

    raw_message = prepare_message(queue_doc, recipients[0].recipient, recipients)
    status, response = client.append(
        _imap_mailbox_arg(sent_folder),
        "(\\Seen)",
        imaplib.Time2Internaldate(time.time()),
        raw_message,
    )
    if status != "OK":
        raise RuntimeError("IMAP APPEND failed: {0}".format(response))


def _message_exists(client, message_id):
    safe_message_id = message_id.replace("\\", "\\\\").replace('"', '\\"')
    status, response = client.uid(
        "SEARCH",
        None,
        "HEADER",
        "Message-ID",
        '"<{0}>"'.format(safe_message_id),
    )
    if status != "OK":
        raise RuntimeError("IMAP Message-ID search failed: {0}".format(response))

    return bool(response and response[0] and response[0].strip())


def _imap_mailbox_arg(folder_name):
    """Return a safely quoted IMAP mailbox argument.

    Python 3.6 imaplib does not automatically quote mailbox names containing
    spaces. Without explicit quoting, ``INBOX.ERPNext Sent`` is interpreted as
    separate IMAP command arguments by this mail server.
    """
    escaped_name = folder_name.replace("\\", "\\\\").replace('"', '\\"')
    return '"{0}"'.format(escaped_name)


def _set_checkpoint(account, creation):
    frappe.db.set_value(
        "Email Account",
        account.name,
        "custom_sent_items_last_sync",
        creation,
        update_modified=False,
    )
    account.custom_sent_items_last_sync = creation


def _log_error_once(key_suffix, title):
    cache_key = "worldshading:sent-items-error:{0}".format(key_suffix)
    if frappe.cache().get_value(cache_key, expires=True):
        return

    frappe.log_error(frappe.get_traceback(), title)
    frappe.cache().set_value(
        cache_key, 1, expires_in_sec=ERROR_COOLDOWN_SECONDS
    )


def _clear_error_throttle(key_suffix):
    frappe.cache().delete_value(
        "worldshading:sent-items-error:{0}".format(key_suffix)
    )
