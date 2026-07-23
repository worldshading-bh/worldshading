import socket
import time
from datetime import datetime

HOST = "109.63.116.44"
PORT = 7777

USERNAME = "erpnext_user"
SECRET = "WorldShading*123#"


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def read_events(sock):
    sock.settimeout(1)
    buffer = b""

    while True:
        try:
            chunk = sock.recv(65535)
            if not chunk:
                print("Connection closed by PBX")
                break

            buffer += chunk

            while b"\r\n\r\n" in buffer:
                raw_event, buffer = buffer.split(b"\r\n\r\n", 1)
                text = raw_event.decode(errors="ignore").strip()

                if text:
                    print("\n" + "=" * 100)
                    print(f"[{now()}]")
                    print(text)

        except socket.timeout:
            continue
        except KeyboardInterrupt:
            print("\nStopping monitor...")
            break


def send_action(sock, action):
    sock.sendall((action + "\r\n\r\n").encode())


sock = socket.create_connection((HOST, PORT), timeout=10)

print(sock.recv(4096).decode(errors="ignore"))

send_action(sock, f"""Action: Login
Username: {USERNAME}
Secret: {SECRET}
Events: on""")

print("Logged in. Now make an incoming call to your company number.")
print("Let IVR route it, ring extension, answer, then hang up.")
print("Press Ctrl+C to stop.\n")

read_events(sock)

send_action(sock, "Action: Logoff")
sock.close()