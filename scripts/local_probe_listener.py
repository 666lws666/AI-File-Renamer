"""Fixed owned loopback positive-control listener; no network I/O on import."""
from dataclasses import dataclass
from hashlib import sha256
import socket
from time import monotonic

CONTROL_NONCE = b"xuxia-loopback-control-v1\n"


class ListenerError(Exception):
    def __init__(self, stage, owner=None):
        self.stage, self.owner = stage, owner
        super().__init__(stage)


@dataclass(frozen=True)
class ControlReceipt:
    byte_count: int
    sha256: str


class OwnedControlListener:
    def __init__(self, *, socket_factory=None):
        self._listener = None
        self._accepted = None
        self._port = None
        factory = socket_factory or socket.socket
        try:
            self._listener = factory(socket.AF_INET, socket.SOCK_STREAM)
            self._listener.set_inheritable(False)
            self._listener.bind(("127.0.0.1", 0))
            address = self._listener.getsockname()
            if (type(address) is not tuple or len(address) < 2 or
                    address[0] != "127.0.0.1" or type(address[1]) is not int or
                    not 1 <= address[1] <= 65535):
                raise ListenerError("listener_address", self)
            self._port = address[1]
            self._listener.listen(1)
        except BaseException as exc:
            try:
                self.close()
            except ListenerError:
                raise ListenerError("listener_close", self) from None
            if isinstance(exc, ListenerError):
                raise
            raise ListenerError("listener_start", self) from None

    @property
    def port(self):
        return self._port

    def verify_control(self):
        if self._listener is None or self._accepted is not None:
            raise ListenerError("listener_state", self)
        deadline = monotonic() + 2.0
        try:
            self._listener.settimeout(max(0.0, deadline - monotonic()))
            accepted, peer = self._listener.accept()
            self._accepted = accepted
            accepted.set_inheritable(False)
            if (type(peer) is not tuple or len(peer) < 2 or
                    peer[0] != "127.0.0.1" or type(peer[1]) is not int or
                    not 1 <= peer[1] <= 65535):
                raise ListenerError("control_peer", self)
            payload = bytearray()
            while len(payload) <= len(CONTROL_NONCE):
                remaining = deadline - monotonic()
                if remaining <= 0:
                    raise ListenerError("control_timeout", self)
                accepted.settimeout(remaining)
                chunk = accepted.recv(len(CONTROL_NONCE) + 1 - len(payload))
                if type(chunk) is not bytes:
                    raise ListenerError("control_receipt", self)
                if not chunk:
                    break
                payload.extend(chunk)
            else:
                raise ListenerError("control_receipt", self)
            if bytes(payload) != CONTROL_NONCE:
                raise ListenerError("control_receipt", self)
            return ControlReceipt(len(payload), sha256(payload).hexdigest())
        except ListenerError:
            raise
        except TimeoutError:
            raise ListenerError("control_timeout", self) from None
        except Exception:
            raise ListenerError("control_accept", self) from None
        finally:
            if self._accepted is not None:
                try:
                    self._accepted.close()
                except Exception:
                    raise ListenerError("control_close", self) from None
                self._accepted = None

    def close(self):
        for name in ("_accepted", "_listener"):
            owned = getattr(self, name)
            if owned is not None:
                try:
                    owned.close()
                except Exception:
                    raise ListenerError("listener_close", self) from None
                setattr(self, name, None)
