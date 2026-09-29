"""Wire protocol: length-prefixed JSON messages.

Every message is a 4-byte big-endian length header followed by a UTF-8 JSON
object. JSON keeps it trivial to add new message types later without touching
any binary framing code.
"""

import json
import struct
import threading


def encode(msg: dict) -> bytes:
    data = json.dumps(msg, separators=(",", ":")).encode("utf-8")
    return struct.pack(">I", len(data)) + data


class MessageReader:
    """Buffered reader that yields one decoded message per read()."""

    def __init__(self, sock):
        self.sock = sock
        self.buf = b""

    def _recv_exact(self, n: int):
        while len(self.buf) < n:
            try:
                chunk = self.sock.recv(65536)
            except OSError:  # peer reset/aborted: treat as a normal disconnect
                return None
            if not chunk:
                return None
            self.buf += chunk
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def read(self):
        header = self._recv_exact(4)
        if header is None:
            return None
        (length,) = struct.unpack(">I", header)
        payload = self._recv_exact(length)
        if payload is None:
            return None
        return json.loads(payload.decode("utf-8"))


class Connection:
    """A socket wrapper with thread-safe sends and framed reads.

    send() is locked because both the input thread and the clipboard thread
    push messages down the same socket.
    """

    def __init__(self, sock):
        self.sock = sock
        self._reader = MessageReader(sock)
        self._lock = threading.Lock()

    def send(self, msg: dict):
        data = encode(msg)
        with self._lock:
            self.sock.sendall(data)

    def read(self):
        return self._reader.read()

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass
