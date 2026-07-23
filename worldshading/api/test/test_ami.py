import telnetlib

HOST = "109.63.116.44"
PORT = 7777

USERNAME = "erpnext_user"
PASSWORD = "WorldShading*123#"

tn = telnetlib.Telnet(HOST, PORT)

print(tn.read_until(b"\n").decode())

login = f"""Action: Login
Username: {USERNAME}
Secret: {PASSWORD}

"""

tn.write(login.encode())

response = tn.read_until(b"\r\n\r\n", timeout=5)
print(response.decode())

tn.close()