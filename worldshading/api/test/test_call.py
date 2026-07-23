# import telnetlib
# import time

# HOST = "109.63.116.44"
# PORT = 7777

# USERNAME = "erpnext_user"
# PASSWORD = "WorldShading*123#"

# EXTENSION = "3001"
# CUSTOMER_NUMBER = "3223 0069"  # replace with your mobile/test number

# tn = telnetlib.Telnet(HOST, PORT)

# print(tn.read_until(b"\n").decode())

# login = f"""Action: Login
# Username: {USERNAME}
# Secret: {PASSWORD}

# """
# tn.write(login.encode())
# print(tn.read_until(b"\r\n\r\n", timeout=5).decode())

# originate = f"""Action: Originate
# Channel: PJSIP/{EXTENSION}
# Context: from-internal
# Exten: {CUSTOMER_NUMBER}
# Priority: 1
# CallerID: World Shading <{EXTENSION}>
# Async: true

# """
# tn.write(originate.encode())

# time.sleep(2)
# print(tn.read_very_eager().decode(errors="ignore"))

# tn.write(b"Action: Logoff\r\n\r\n")
# tn.close()

import telnetlib
import time
import json
import logging
from datetime import datetime


HOST = "109.63.116.44"
PORT = 7777

USERNAME = "erpnext_user"
PASSWORD = "WorldShading*123#"

EXTENSION = "3001"
CUSTOMER_NUMBER = "32230069"  # no spaces

LISTEN_SECONDS = 90


logging.basicConfig(
    filename="ami_debug.log",
    level=logging.DEBUG,
    format="%(asctime)s %(levelname)s %(message)s"
)


def parse_ami_message(raw):
    data = {}

    for line in raw.splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            data[key.strip()] = value.strip()

    return data


def read_ami_message(tn, timeout=2):
    raw = tn.read_until(b"\r\n\r\n", timeout=timeout).decode(errors="ignore")

    if raw.strip():
        return raw, parse_ami_message(raw)

    return "", {}


def log_debug(title, data):
    logging.debug("%s\n%s", title, json.dumps(data, indent=2, default=str))


def test_call_with_tracking():
    call_summary = {
        "extension": EXTENSION,
        "customer_number": CUSTOMER_NUMBER,
        "originate_sent": False,
        "originate_response": None,
        "customer_answered": False,
        "bridge_detected": False,
        "hangup_detected": False,
        "hangup_cause": None,
        "hangup_cause_txt": None,
        "start_time": datetime.now(),
        "answered_time": None,
        "end_time": None,
        "duration_seconds": 0,
        "billable_seconds": 0,
        "final_status": "Unknown",
        "events": []
    }

    tn = None

    try:
        tn = telnetlib.Telnet(HOST, PORT, timeout=10)

        banner = tn.read_until(b"\n", timeout=5).decode(errors="ignore")
        print(banner)

        login = f"""Action: Login
Username: {USERNAME}
Secret: {PASSWORD}
Events: on

"""
        tn.write(login.encode())

        raw, msg = read_ami_message(tn, timeout=5)
        print(raw)

        if msg.get("Response") != "Success":
            call_summary["final_status"] = "AMI Login Failed"
            log_debug("PBX AMI Login Failed", call_summary)
            return call_summary

        action_id = "WS-CALL-{}".format(int(time.time()))

        originate = f"""Action: Originate
ActionID: {action_id}
Channel: PJSIP/{EXTENSION}
Context: from-internal
Exten: {CUSTOMER_NUMBER}
Priority: 1
CallerID: World Shading <{EXTENSION}>
Async: true

"""
        tn.write(originate.encode())

        call_summary["originate_sent"] = True
        call_summary["action_id"] = action_id

        listen_until = time.time() + LISTEN_SECONDS

        while time.time() < listen_until:
            raw, event = read_ami_message(tn, timeout=2)

            if not event:
                continue

            event_name = event.get("Event") or event.get("Response") or "Unknown"

            event_data = {
                "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "event": event_name,
                "channel": event.get("Channel"),
                "dest_channel": event.get("DestChannel"),
                "caller_id_num": event.get("CallerIDNum"),
                "connected_line_num": event.get("ConnectedLineNum"),
                "dial_status": event.get("DialStatus"),
                "cause": event.get("Cause"),
                "cause_txt": event.get("Cause-txt"),
                "raw": raw
            }

            call_summary["events"].append(event_data)

            print("=" * 80)
            print(raw)

            if event.get("Response") in ("Success", "Error") and event.get("ActionID") == action_id:
                call_summary["originate_response"] = event

            if event_name == "OriginateResponse":
                call_summary["originate_response"] = event

                if event.get("Response") == "Failure":
                    call_summary["final_status"] = "Originate Failed"
                    call_summary["hangup_cause"] = event.get("Reason")

            if event_name in ("DialEnd", "Dial"):
                dial_status = event.get("DialStatus")

                if dial_status:
                    call_summary["last_dial_status"] = dial_status

                    if dial_status == "ANSWER":
                        call_summary["customer_answered"] = True

                        if not call_summary["answered_time"]:
                            call_summary["answered_time"] = datetime.now()

                    elif dial_status in (
                        "NOANSWER",
                        "BUSY",
                        "CANCEL",
                        "CHANUNAVAIL",
                        "CONGESTION"
                    ):
                        call_summary["final_status"] = dial_status

            if event_name in ("BridgeEnter", "BridgeCreate"):
                call_summary["bridge_detected"] = True
                call_summary["customer_answered"] = True

                if not call_summary["answered_time"]:
                    call_summary["answered_time"] = datetime.now()

            if event_name == "Hangup":
                call_summary["hangup_detected"] = True
                call_summary["hangup_cause"] = event.get("Cause")
                call_summary["hangup_cause_txt"] = event.get("Cause-txt")
                call_summary["end_time"] = datetime.now()

                time.sleep(3)

                while True:
                    raw2, event2 = read_ami_message(tn, timeout=1)

                    if not event2:
                        break

                    event_name2 = event2.get("Event") or event2.get("Response") or "Unknown"

                    call_summary["events"].append({
                        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "event": event_name2,
                        "channel": event2.get("Channel"),
                        "dest_channel": event2.get("DestChannel"),
                        "caller_id_num": event2.get("CallerIDNum"),
                        "connected_line_num": event2.get("ConnectedLineNum"),
                        "dial_status": event2.get("DialStatus"),
                        "cause": event2.get("Cause"),
                        "cause_txt": event2.get("Cause-txt"),
                        "raw": raw2
                    })

                    print("=" * 80)
                    print(raw2)

                break

        if not call_summary["end_time"]:
            call_summary["end_time"] = datetime.now()

        call_summary["duration_seconds"] = int(
            (call_summary["end_time"] - call_summary["start_time"]).total_seconds()
        )

        if call_summary["answered_time"]:
            call_summary["billable_seconds"] = int(
                (call_summary["end_time"] - call_summary["answered_time"]).total_seconds()
            )

        if call_summary["customer_answered"] or call_summary["bridge_detected"]:
            call_summary["final_status"] = "Answered"
        elif call_summary.get("last_dial_status"):
            call_summary["final_status"] = call_summary["last_dial_status"]
        elif call_summary["hangup_cause_txt"]:
            call_summary["final_status"] = call_summary["hangup_cause_txt"]
        elif (
            call_summary["originate_response"]
            and call_summary["originate_response"].get("Response") == "Failure"
        ):
            call_summary["final_status"] = "Originate Failed"
        else:
            call_summary["final_status"] = "No Answer / Unknown"

        log_debug("PBX AMI Call Debug Summary", call_summary)

        return call_summary

    except Exception as e:
        logging.exception("PBX AMI Call Debug Error")
        raise e

    finally:
        if tn:
            try:
                tn.write(b"Action: Logoff\r\n\r\n")
                tn.close()
            except Exception:
                pass


summary = test_call_with_tracking()

print("\nFINAL CALL SUMMARY")
print(json.dumps(summary, indent=2, default=str))