from parser import (
    event_mentions_answer,
    extract_queue_info,
    get_caller,
    get_cdr_status,
    get_event_extensions,
    get_linked_id,
    is_company_number,
)
from popup_engine import PopupEngine


class CallManager(object):
    """Convert noisy AMI events into a small set of business events."""

    def __init__(self):
        self.calls = {}
        self.ended_calls = set()
        self.uniqueid_map = {}
        self.popup_engine = PopupEngine()

    def process_event(self, event):
        linkedid = get_linked_id(event)
        if not linkedid:
            return []

        linkedid = self._resolve_linkedid(event, linkedid)
        if linkedid in self.ended_calls:
            return []

        call = self._get_or_create_call(linkedid)
        business_events = []

        caller = get_caller(event)
        if caller and is_company_number(caller):
            call["skip_popup"] = True

        if caller and not call.get("caller") and not call.get("skip_popup"):
            call["caller"] = caller

        queue_number, queue_name = extract_queue_info(event)
        if queue_number and not call.get("queue_number"):
            call["queue_number"] = queue_number
        if queue_name and not call.get("queue_name"):
            call["queue_name"] = queue_name

        if not call.get("created_sent") and call.get("caller"):
            call["created_sent"] = True
            business_events.append({
                "type": "CALL_CREATED",
                "linkedid": linkedid,
                "caller": call.get("caller"),
            })

        extensions = get_event_extensions(event)
        for extension in extensions:
            if extension not in call["ringing_extensions"]:
                call["ringing_extensions"].append(extension)

            if call.get("caller") and not call.get("skip_popup") and self._is_popup_candidate(event, extension):
                if self.popup_engine.should_send(linkedid, extension):
                    call["popup_sent"][extension] = True
                    business_events.append({
                        "type": "POPUP_CANDIDATE",
                        "linkedid": linkedid,
                        "caller": call.get("caller"),
                        "extension": extension,
                        "queue_number": call.get("queue_number"),
                        "queue_name": call.get("queue_name"),
                    })

        if event_mentions_answer(event):
            answered_extension = self._get_answered_extension(event, extensions)
            if answered_extension and not call.get("answered_extension"):
                call["answered_extension"] = answered_extension
                call["status"] = "ANSWERED"
                business_events.append({
                    "type": "CALL_ANSWERED",
                    "linkedid": linkedid,
                    "caller": call.get("caller"),
                    "answered_extension": answered_extension,
                })

        cdr_status = get_cdr_status(event)
        if cdr_status:
            if cdr_status in ("ANSWER", "ANSWERED"):
                call["status"] = "ANSWERED"
            elif call.get("status") != "ANSWERED":
                call["status"] = self._clean_end_status(cdr_status)

        if self._is_call_end(event):
            business_events.append(self._build_call_ended_event(linkedid, call))
            self.ended_calls.add(linkedid)
            self.popup_engine.clear_call(linkedid)
            self.calls.pop(linkedid, None)

        return business_events

    def _get_or_create_call(self, linkedid):
        if linkedid not in self.calls:
            self.calls[linkedid] = {
                "caller": "",
                "queue_number": "",
                "queue_name": "",
                "ringing_extensions": [],
                "answered_extension": "",
                "status": "RINGING",
                "popup_sent": {},
                "created_sent": False,
                "skip_popup": False,
            }

        return self.calls[linkedid]

    def _is_popup_candidate(self, event, extension):
        event_name = event.get("Event") or ""
        channel_state = str(event.get("ChannelStateDesc") or "").lower()

        if event_name in ("DialBegin", "Newchannel"):
            return True

        if event_name in ("Newstate", "Newexten") and channel_state == "ring":
            return True

        # Some Grandstream events show extension ringing only through Dial.
        if event_name == "Dial" and extension:
            return True

        return False

    def _get_answered_extension(self, event, extensions):
        event_name = event.get("Event") or ""

        if event_name == "BridgeEnter":
            return extensions[0] if extensions else ""

        dial_status = str(event.get("DialStatus") or "").upper()
        if dial_status in ("ANSWER", "ANSWERED") and extensions:
            return extensions[0]

        return ""

    def _is_call_end(self, event):
        event_name = event.get("Event") or ""

        if event_name == "QueueCallerAbandon":
            return True

        if event_name == "Cdr":
            return True

        if event_name == "Hangup":
            # Ring-all creates separate hangups for internal extension legs.
            # Do not end the whole call when only an extension leg hangs up.
            if get_event_extensions(event) and not get_caller(event):
                return False
            return True

        return False

    def _build_call_ended_event(self, linkedid, call):
        status = call.get("status") or "MISSED"

        if not call.get("answered_extension") and status in ("RINGING", "NOANSWER"):
            status = "MISSED"

        return {
            "type": "CALL_ENDED",
            "linkedid": linkedid,
            "caller": call.get("caller"),
            "queue_number": call.get("queue_number"),
            "queue_name": call.get("queue_name"),
            "ringing_extensions": list(call.get("ringing_extensions") or []),
            "answered_extension": call.get("answered_extension"),
            "status": status,
        }

    def _resolve_linkedid(self, event, fallback_linkedid):
        uniqueid = event.get("Uniqueid") or event.get("UniqueID") or ""
        linkedid = event.get("Linkedid") or event.get("LinkedID") or ""

        if linkedid:
            if uniqueid:
                self.uniqueid_map[uniqueid] = linkedid
            return linkedid

        if uniqueid and uniqueid in self.uniqueid_map:
            return self.uniqueid_map[uniqueid]

        return fallback_linkedid

    def _clean_end_status(self, status):
        status = str(status or "").upper()

        if status in ("NOANSWER", "NO ANSWER"):
            return "NO ANSWER"
        if status in ("ANSWER", "ANSWERED"):
            return "ANSWERED"
        if status in ("BUSY", "FAILED", "CANCEL", "CONGESTION"):
            return status

        return "MISSED"
