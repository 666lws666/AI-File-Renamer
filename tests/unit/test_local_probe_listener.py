import socket
from hashlib import sha256

import pytest

from scripts.local_probe_listener import CONTROL_NONCE, ListenerError, OwnedControlListener


class Socket:
    def __init__(self, payload=CONTROL_NONCE):
        self.payload = payload
        self.calls = []
        self.closed = False
        self.address = ("127.0.0.1", 49152)

    def set_inheritable(self, value): self.calls.append(("inherit", value))
    def bind(self, address): self.calls.append(("bind", address))
    def getsockname(self): return self.address
    def listen(self, backlog): self.calls.append(("listen", backlog))
    def settimeout(self, timeout): self.calls.append(("timeout", timeout))
    def accept(self):
        peer = Socket(self.payload)
        peer.address = self.address
        return peer, ("127.0.0.1", 53000)
    def recv(self, size):
        chunk, self.payload = self.payload[:size], self.payload[size:]
        return chunk
    def close(self): self.closed = True


def test_exact_control_receipt_and_fixed_listener_setup():
    sock = Socket()
    listener = OwnedControlListener(socket_factory=lambda family, kind: sock)
    assert listener.port == 49152
    assert sock.calls[:3] == [("inherit", False), ("bind", ("127.0.0.1", 0)), ("listen", 1)]
    fact = listener.verify_control()
    assert fact.byte_count == 26 and fact.sha256 == sha256(CONTROL_NONCE).hexdigest()
    listener.close()
    assert sock.closed


@pytest.mark.parametrize("payload", [b"", CONTROL_NONCE[:-1], CONTROL_NONCE + b"x", b"wrong"])
def test_rejects_nonexact_control(payload):
    listener = OwnedControlListener(socket_factory=lambda family, kind: Socket(payload))
    with pytest.raises(ListenerError):
        listener.verify_control()
    listener.close()


@pytest.mark.parametrize("address", [("0.0.0.0", 49152), ("127.0.0.1", 0), ("127.0.0.1", 65536)])
def test_rejects_wrong_bound_address_or_port(address):
    sock = Socket()
    sock.address = address
    with pytest.raises(ListenerError):
        OwnedControlListener(socket_factory=lambda family, kind: sock)
    assert sock.closed


def test_accept_timeout_has_fixed_stage_and_listener_can_close():
    class TimedOut(Socket):
        def accept(self): raise TimeoutError("private payload")
    sock = TimedOut()
    listener = OwnedControlListener(socket_factory=lambda family, kind: sock)
    with pytest.raises(ListenerError) as caught:
        listener.verify_control()
    assert caught.value.stage == "control_timeout"
    listener.close()
    assert sock.closed


def test_wrong_peer_is_rejected_without_logging_bytes():
    class WrongPeer(Socket):
        def accept(self): return Socket(), ("192.0.2.1", 53000)
    listener = OwnedControlListener(socket_factory=lambda family, kind: WrongPeer())
    with pytest.raises(ListenerError) as caught:
        listener.verify_control()
    assert caught.value.stage == "control_peer"
    listener.close()


def test_failed_listener_close_keeps_owner_for_explicit_retry():
    class FailsOnce(Socket):
        def __init__(self):
            super().__init__()
            self.fail_close = True
        def close(self):
            if self.fail_close:
                self.fail_close = False
                raise OSError("injected")
            super().close()
    sock = FailsOnce()
    listener = OwnedControlListener(socket_factory=lambda family, kind: sock)
    with pytest.raises(ListenerError) as caught:
        listener.close()
    assert caught.value.owner is listener and not sock.closed
    listener.close()
    assert sock.closed
