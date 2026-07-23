import socket
import time

HOST = "109.63.116.44"
PORT = 7777

USERNAME = "erpnext_user"
SECRET = "WorldShading*123#"

# Put your own mobile number here exactly like users dial from office extension
# Try first without country code if office users dial that way, example: 3XXXXXXX
# If needed, try 9733XXXXXXX
NUMBER = "34567505"

CALLER_ID = "ERP Test <3001>"


def read_all(sock, wait=1.0):
    time.sleep(wait)
    sock.setblocking(False)
    data = b""
    while True:
        try:
            chunk = sock.recv(65535)
            if not chunk:
                break
            data += chunk
        except BlockingIOError:
            break
    sock.setblocking(True)
    return data.decode(errors="ignore")


def send_action(sock, action, wait=1.0):
    sock.sendall((action + "\r\n\r\n").encode())
    return read_all(sock, wait)


sock = socket.create_connection((HOST, PORT), timeout=10)

print(read_all(sock, 0.5))

print("========== LOGIN ==========")
print(send_action(sock, f"""Action: Login
Username: {USERNAME}
Secret: {SECRET}
Events: on"""))

print("========== DIRECT LOCAL ORIGINATE TEST ==========")

print(send_action(sock, f"""Action: Originate
Channel: Local/{NUMBER}@from-internal
Context: from-internal
Exten: {NUMBER}
Priority: 1
CallerID: {CALLER_ID}
Timeout: 30000
Async: true""", wait=3))

print("========== WAITING FOR EVENTS ==========")
print(read_all(sock, 15))

print("========== LOGOFF ==========")
print(send_action(sock, "Action: Logoff"))

sock.close()