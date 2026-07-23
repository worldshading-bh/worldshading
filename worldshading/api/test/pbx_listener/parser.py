import re

import config


def parse_ami_message(raw):
    """Parse one AMI message block into a dictionary."""
    event = {}

    for line in (raw or "").splitlines():
        if ":" not in line:
            continue

        key, value = line.split(":", 1)
        event[key.strip()] = value.strip()

    return event


def get_linked_id(event):
    """Return the best call grouping key available in an AMI event."""
    return (
        event.get("Linkedid")
        or event.get("LinkedID")
        or event.get("Uniqueid")
        or event.get("UniqueID")
        or ""
    )


def is_internal_extension(value):
    """Return True for local 4-digit extension values such as 2000."""
    value = str(value or "").strip()
    return value.isdigit() and len(value) == config.INTERNAL_EXTENSION_LENGTH


def get_caller(event):
    """Return an external caller number candidate without using extensions."""
    candidates = (
        event.get("CallerIDNum"),
        event.get("CallerID"),
        event.get("Source"),
        event.get("Src"),
        event.get("AccountCode"),
    )

    for value in candidates:
        value = clean_number(value)
        if value and not is_internal_extension(value):
            return value

    return ""


def is_company_number(value):
    """Return True if value is one of World Shading's own PBX/trunk numbers."""
    digits = "".join([ch for ch in str(value or "") if ch.isdigit()])

    if not digits:
        return False

    variants = set([digits])

    if digits.startswith("00"):
        without_00 = digits[2:]
        variants.add(without_00)
        if without_00.startswith("973"):
            variants.add(without_00[-8:])

    if digits.startswith("973"):
        variants.add(digits[-8:])

    if len(digits) == 8:
        variants.add("973" + digits)
        variants.add("00973" + digits)

    for company_number in config.COMPANY_NUMBERS:
        company_digits = "".join([ch for ch in str(company_number or "") if ch.isdigit()])
        if company_digits in variants:
            return True

    return False


def clean_number(value):
    """Keep phone-number style characters, removing display-name wrappers."""
    value = str(value or "").strip()

    if "<" in value and ">" in value:
        value = value.split("<", 1)[1].split(">", 1)[0]

    return "".join([ch for ch in value if ch.isdigit() or ch == "+"])


def extract_extension(channel):
    """Extract an internal extension from channels like PJSIP/2001-000000aa."""
    channel = str(channel or "")
    prefix = config.EXTENSION_PREFIX

    if prefix not in channel:
        return ""

    after_prefix = channel.split(prefix, 1)[1]
    extension = after_prefix.split("-", 1)[0].split("/", 1)[0]
    extension = extension.strip()

    if is_internal_extension(extension):
        return extension

    return ""


def get_event_extensions(event):
    """Return internal extensions mentioned by actual PJSIP channel fields."""
    extensions = []

    for fieldname in ("DestChannel", "Channel"):
        value = event.get(fieldname)
        extension = extract_extension(value)

        if extension and extension not in extensions:
            extensions.append(extension)

    return extensions


def extract_queue_info(event):
    """Capture queue number/name from known Grandstream/Asterisk fields."""
    queue_number = ""
    queue_name = ""

    queue_value = event.get("Queue") or ""
    if queue_value:
        if str(queue_value).isdigit():
            queue_number = str(queue_value)
        else:
            queue_name = str(queue_value)

    last_data = event.get("LastData") or event.get("AppData") or ""
    first_arg = str(last_data).split(",", 1)[0].strip()

    if first_arg:
        if first_arg.isdigit() and not queue_number:
            queue_number = first_arg
        elif _looks_like_queue_name(first_arg) and not queue_name:
            queue_name = first_arg

    event_name = event.get("Event") or ""
    exten = str(event.get("Exten") or "").strip()
    context = str(event.get("Context") or "").lower()

    if exten and exten.isdigit() and not queue_number:
        if event_name.startswith("Queue") or "queue" in context:
            queue_number = exten

    # Some AMI variants include queue-like text inside interface/member names.
    # Keep this deliberately conservative to avoid false positives.
    for fieldname in ("QueueName", "Queue_name"):
        value = event.get(fieldname)
        if value and not queue_name:
            queue_name = str(value).strip()

    return queue_number, queue_name


def _looks_like_queue_name(value):
    value = str(value or "").strip()

    if not value:
        return False

    # Grandstream route variables can appear in CDR LastData/AppData. They are
    # useful raw details, but they are not queue names for the clean output.
    if "=" in value:
        return False

    # Examples seen from Grandstream dialplan/CDR data:
    #   0?GetCidName(""
    # These are expressions, not business queue names.
    for marker in ("?", "(", ")", '"'):
        if marker in value:
            return False

    if value.startswith("0"):
        return False

    if value.startswith("macro-"):
        return False

    if value.lower() in ("end", "s", "hangup", "user-callerid-after"):
        return False

    return True


def event_mentions_hangup(event):
    return (event.get("Event") or "") in ("Hangup", "QueueCallerAbandon")


def event_mentions_answer(event):
    event_name = event.get("Event") or ""
    dial_status = str(event.get("DialStatus") or "").upper()
    return event_name == "BridgeEnter" or dial_status in ("ANSWER", "ANSWERED")


def get_cdr_status(event):
    disposition = str(event.get("Disposition") or "").upper()
    if disposition:
        return disposition

    dial_status = str(event.get("DialStatus") or "").upper()
    if dial_status:
        return dial_status

    cause = str(event.get("Cause-txt") or event.get("Cause") or "").upper()
    if re.search("ANSWER|NORMAL", cause):
        return "ANSWERED"
    if re.search("NO ANSWER|CANCEL|ABANDON|MISSED", cause):
        return "MISSED"

    return ""
