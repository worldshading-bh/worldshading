import socket
import time

HOST = "109.63.116.44"
PORT = 7777

USERNAME = "erpnext_user"
SECRET = "WorldShading*123#"

IMPORTANT_EVENTS = {
    "DialBegin",
    "DialEnd",
    "BridgeEnter",
    "BridgeLeave",
    "Hangup",
    "QueueCallerJoin",
    "QueueCallerLeave",
    "QueueCallerAbandon",
    "Cdr",
}

def parse_ami_message(raw):
    event = {}
    for line in raw.splitlines():
        if ": " in line:
            key, value = line.split(": ", 1)
            event[key.strip()] = value.strip()
    return event

def is_extension_channel(channel):
    return channel and "PJSIP/" in channel

def clean_ext(channel):
    if not channel:
        return ""
    if "PJSIP/" in channel:
        return channel.split("PJSIP/")[1].split("-")[0]
    return ""

def connect_ami():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(10)
    s.connect((HOST, PORT))

    login = (
        f"Action: Login\r\n"
        f"Username: {USERNAME}\r\n"
        f"Secret: {SECRET}\r\n"
        f"Events: on\r\n\r\n"
    )
    s.send(login.encode())
    s.settimeout(None)
    return s

def run():
    while True:
        try:
            print("Connecting to AMI...")
            sock = connect_ami()
            print("Connected to AMI. Listening...")

            buffer = ""

            while True:
                data = sock.recv(4096).decode(errors="ignore")
                if not data:
                    raise ConnectionError("AMI disconnected")

                buffer += data

                while "\r\n\r\n" in buffer:
                    raw_msg, buffer = buffer.split("\r\n\r\n", 1)
                    event = parse_ami_message(raw_msg)

                    event_name = event.get("Event")
                    if event_name not in IMPORTANT_EVENTS:
                        continue

                    caller = event.get("CallerIDNum") or event.get("Source") or ""
                    linkedid = event.get("Linkedid") or event.get("LinkedID") or event.get("Uniqueid") or ""
                    channel = event.get("Channel", "")
                    dest_channel = event.get("DestChannel", "")
                    queue = event.get("Queue", "")
                    disposition = event.get("Disposition", "")
                    cause = event.get("Cause-txt", "")

                    ext = clean_ext(dest_channel) or clean_ext(channel)

                    # Only print useful clean info
                    if event_name == "DialBegin" and ext:
                        print("\n--- EXTENSION RINGING ---")
                        print(f"Caller     : {caller}")
                        print(f"Extension  : {ext}")
                        print(f"Queue      : {queue}")
                        print(f"LinkedID   : {linkedid}")

                    elif event_name in ["BridgeEnter", "DialEnd", "Hangup", "Cdr"]:
                        print(f"\n--- {event_name} ---")
                        print(f"Caller     : {caller}")
                        print(f"Extension  : {ext}")
                        print(f"Queue      : {queue}")
                        print(f"Status     : {disposition or cause}")
                        print(f"LinkedID   : {linkedid}")

        except Exception as e:
            print(f"Listener error: {e}")
            print("Reconnecting in 5 seconds...")
            time.sleep(5)

if __name__ == "__main__":
    run()
