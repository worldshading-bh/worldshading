import socket
import time

import config
from parser import parse_ami_message


class AMIClient(object):
    """Small raw TCP AMI client for read-only event monitoring."""

    def __init__(self):
        self.sock = None
        self.buffer = ""

    def connect(self):
        self.close()
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.settimeout(config.SOCKET_TIMEOUT)
        self.sock.connect((config.HOST, config.PORT))

        # Read and discard the AMI banner.
        try:
            self.sock.recv(config.READ_SIZE)
        except socket.timeout:
            pass

        self.login()
        self.sock.settimeout(config.READ_TIMEOUT)

    def login(self):
        if not config.SECRET:
            raise RuntimeError(
                "PBX_AMI_SECRET is not set. Export it before running listener.py."
            )

        action = (
            "Action: Login\r\n"
            "Username: {0}\r\n"
            "Secret: {1}\r\n"
            "Events: on\r\n"
            "\r\n"
        ).format(config.USERNAME, config.SECRET)

        self.sock.sendall(action.encode("utf-8"))
        parsed = {}
        response = ""

        while parsed.get("Response") not in ("Success", "Error"):
            response = self._read_one_message(timeout=config.SOCKET_TIMEOUT)
            parsed = parse_ami_message(response)

        if parsed.get("Response") != "Success":
            raise RuntimeError(
                "AMI login failed: {0}".format(parsed.get("Message") or response)
            )

    def read_messages(self):
        """Yield complete raw AMI message blocks as they arrive."""
        last_ping = time.time()

        while True:
            try:
                data = self.sock.recv(config.READ_SIZE)
            except socket.timeout:
                if time.time() - last_ping >= config.PING_INTERVAL:
                    self.ping()
                    last_ping = time.time()
                continue

            if not data:
                raise ConnectionError("AMI socket disconnected")

            self.buffer += data.decode("utf-8", errors="ignore")

            while "\r\n\r\n" in self.buffer:
                raw, self.buffer = self.buffer.split("\r\n\r\n", 1)
                if raw.strip():
                    yield raw

    def ping(self):
        action = (
            "Action: Ping\r\n"
            "\r\n"
        )
        self.sock.sendall(action.encode("utf-8"))

    def _read_one_message(self, timeout):
        old_timeout = self.sock.gettimeout()
        self.sock.settimeout(timeout)

        try:
            while "\r\n\r\n" not in self.buffer:
                data = self.sock.recv(config.READ_SIZE)
                if not data:
                    raise ConnectionError("AMI socket disconnected during login")
                self.buffer += data.decode("utf-8", errors="ignore")

            raw, self.buffer = self.buffer.split("\r\n\r\n", 1)
            return raw
        finally:
            self.sock.settimeout(old_timeout)

    def close(self):
        if not self.sock:
            return

        try:
            self.sock.close()
        except Exception:
            pass

        self.sock = None
        self.buffer = ""
