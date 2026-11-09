"""The viOSC command link (e98s01, e98s02). dpg-free by construction (HIGH-1).

One command stream: one long-lived ``POST /link`` with a chunked request body, one
JSON frame per chunk::

    {"address": "/vimix/<target>/<prop>", "args": [...]}      a command
    {"ping": true}                                            a keepalive

Why a stream and not a request per command: measured, one command costs 4.4 us as a
chunk in a live stream, 91 us as a whole HTTP request (and the request shape blocks
the sender for a round trip, i.e. it stalls the fade tick).

This module owns the transport only: the queue, the framing, the reconnect
discipline and the observable state. It never decides WHAT a command means, and it
never touches the UI — ``send_message`` is a push into a queue and returns at once,
so every existing call site (fade, sequencer, cue, mapper) is unchanged.
"""

import contextlib
import json
import socket
import threading
import time
from typing import Any

from vjmixapp import iomonitor, pairing
from vjmixapp.constants import (
    IO_MONITOR_KIND_COMMAND_STREAM,
    LINK_BACKOFF_MAX_S,
    LINK_BACKOFF_MIN_S,
    LINK_CONTENT_TYPE,
    LINK_PATH,
    LINK_PING_S,
    LINK_QUEUE_MAX,
    LINK_WRITE_TIMEOUT_S,
)

# The four observables the link reports, one value at a time (e98s03).
CONNECTING = "connecting"
CONNECTED = "connected"
RECONNECTING = "reconnecting"
INCOMPATIBLE = "incompatible"

# Addresses that are TRIGGERS: the count is the message, so they are never
# coalesced. A command with no argument is a trigger whatever its name.
# The last frames this app emitted, for debugging and the harness. Bounded in
# blocks (the I/O Monitor owns the history; this is a window, not a log).
LINK_RECORD_MAX = 1024

TRIGGER_PROPS = frozenset(
    {"next", "previous", "flag", "reset", "replay", "reload", "pause", "stop"}
)


def _as_items(args: Any) -> list[Any]:
    """python-osc accepts a scalar as one argument; so do we."""
    if args is None:
        return []
    if isinstance(args, (list, tuple)):
        return list(args)
    return [args]


def encode_frame(address: str, args: list[Any]) -> bytes:
    """One chunk: the length line, the JSON body, the CRLF (e98s01)."""
    body = json.dumps({"address": str(address), "args": list(args)}).encode("utf-8")
    return b"%x\r\n" % len(body) + body + b"\r\n"


def ping_frame() -> bytes:
    """The keepalive chunk — a frame the daemon never forwards."""
    body = b'{"ping":true}'
    return b"%x\r\n" % len(body) + body + b"\r\n"


def is_trigger(address: str, args: Any) -> bool:
    """True when the message's meaning is its COUNT, not its value (e98s02)."""
    if not args:
        return True
    if len(args) != 1:
        return True  # a vector or a ramp: never collapse it
    return str(address).rsplit("/", 1)[-1] in TRIGGER_PROPS


class CommandLink:
    """The writer thread and the ordered queue behind ``send_message``.

    ``send_message`` always succeeds and never blocks: the queue absorbs the burst
    and the writer thread drains it. While the stream is down the queue keeps the
    NEWEST value per address and every trigger — dropping a trigger silently would
    be a lie, so an overflow is logged with the dropped address.
    """

    def __init__(self, host: str, port: int, *, now=time.monotonic) -> None:
        self.host = str(host)
        self.port = int(port)
        self._now = now
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._pending: list[tuple[str, list[Any]]] = []
        self._stopping = False
        self._thread: threading.Thread | None = None
        self._sock: socket.socket | None = None
        self._state = CONNECTING
        self._error = ""
        self.sent = 0  # frames actually written (tests, Monitor)
        self.dropped = 0  # values coalesced away / triggers over the cap
        self.connects = 0
        self.messages: list[tuple[str, Any]] = []

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        """Start the writer thread (idempotent)."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stopping = False
        self._thread = threading.Thread(target=self._run, name="viosc-link", daemon=True)
        self._thread.start()

    def mark_incompatible(self, version: str) -> None:
        """Refuse to drive a daemon older than 1.0 (e98s03) — never start writing.

        UDP had no handshake, so an old daemon simply ignored addresses it did not
        know. A command stream would look healthy while nothing it sends means
        anything, which is worse: the state is `incompatible` and nothing is sent.
        """
        self._state = INCOMPATIBLE
        self._error = f"viOSC {version or '?'} is older than 1.0.0"

    def stop(self, timeout: float = 2.0) -> None:
        """Close the stream and stop the writer (the app is going away)."""
        self._stopping = True
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout)
        self._close_socket()

    # -- observables -------------------------------------------------------

    @property
    def state(self) -> str:
        """``connecting`` / ``connected`` / ``reconnecting`` / ``incompatible``."""
        return self._state

    @property
    def error(self) -> str:
        return self._error

    @property
    def backlog(self) -> int:
        with self._lock:
            return len(self._pending)

    def peer(self) -> str:
        return f"{self.host}:{self.port}"

    # -- the send funnel ---------------------------------------------------

    def send_message(self, address: str, args: Any = None) -> None:
        """Queue one command (python-osc's signature: the call sites do not move)."""
        self.send(address, args)

    def send(self, address: str, args: Any = None) -> None:
        if not str(address).startswith("/"):
            return
        items = _as_items(args)
        self._record(address, args)
        trigger = is_trigger(str(address), items)
        with self._lock:
            if trigger or len(self._pending) >= LINK_QUEUE_MAX:
                self._append_bounded_locked(str(address), items, trigger)
            else:
                self._coalesce_or_append_locked(str(address), items)
        self._wake.set()

    def _record(self, address: str, payload: Any) -> None:
        """Keep the payload AS GIVEN (a scalar stays a scalar: the harness reads it)."""
        self.messages.append((str(address), payload))
        if len(self.messages) > LINK_RECORD_MAX * 2:
            del self.messages[: len(self.messages) - LINK_RECORD_MAX]

    def _coalesce_or_append_locked(self, address: str, items: list[Any]) -> None:
        for index in range(len(self._pending) - 1, -1, -1):
            if self._pending[index][0] == address:
                self._pending[index] = (address, items)
                self.dropped += 1
                return
        self._pending.append((address, items))

    def _append_bounded_locked(self, address: str, items: list[Any], trigger: bool) -> None:
        if len(self._pending) < LINK_QUEUE_MAX:
            self._pending.append((address, items))
            return
        if trigger:
            # Make room by dropping the OLDEST value (it is superseded by design).
            for index, (queued, _args) in enumerate(self._pending):
                if not is_trigger(queued, _args):
                    del self._pending[index]
                    break
            self._pending.append((address, items))
            self.dropped += 1
            iomonitor.record_http(
                IO_MONITOR_KIND_COMMAND_STREAM,
                LINK_PATH,
                f"overflow: {address}",
                self.peer(),
            )
            return
        self.dropped += 1  # a value we can live without: the next one wins

    def _take(self, timeout: float) -> tuple[str, list[Any]] | None:
        """The next frame, or None after ``timeout`` (the ping cadence)."""
        self._wake.wait(timeout)
        with self._lock:
            if not self._pending:
                self._wake.clear()
                return None
            frame = self._pending.pop(0)
            if not self._pending:
                self._wake.clear()
            return frame

    # -- the writer --------------------------------------------------------

    def _run(self) -> None:
        backoff = LINK_BACKOFF_MIN_S
        while not self._stopping:
            try:
                sock = self._connect()
            except OSError as e:
                self._set(RECONNECTING, str(e))
                self._sleep(backoff)
                backoff = min(backoff * 2, LINK_BACKOFF_MAX_S)
                continue
            backoff = LINK_BACKOFF_MIN_S
            self._sock = sock
            self.connects += 1
            self._set(CONNECTED, "")
            iomonitor.record_http(IO_MONITOR_KIND_COMMAND_STREAM, LINK_PATH, "open", self.peer())
            try:
                self._pump(sock)
            except OSError as e:
                self._set(RECONNECTING, str(e))
                iomonitor.record_http(
                    IO_MONITOR_KIND_COMMAND_STREAM, LINK_PATH, "reconnect", self.peer()
                )
            finally:
                self._close_socket()

    def _pump(self, sock: socket.socket) -> None:
        last_write = self._now()
        while not self._stopping:
            frame = self._take(LINK_PING_S)
            if frame is None:
                if self._now() - last_write < LINK_PING_S:
                    continue
                sock.sendall(ping_frame())
                last_write = self._now()
                continue
            address, items = frame
            sock.sendall(encode_frame(address, items))
            last_write = self._now()
            self.sent += 1
        # A clean stop closes the stream properly: the zero chunk.
        with contextlib.suppress(OSError):
            sock.sendall(b"0\r\n\r\n")

    def _connect(self) -> socket.socket:
        sock = socket.create_connection((self.host, self.port), timeout=LINK_WRITE_TIMEOUT_S)
        sock.settimeout(LINK_WRITE_TIMEOUT_S)
        # Nagle would hold a small write behind an unacknowledged segment: a fade
        # is a stream of small writes, so this is not optional.
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        head = [
            f"POST {LINK_PATH} HTTP/1.1",
            f"Host: {self.host}:{self.port}",
            f"Content-Type: {LINK_CONTENT_TYPE}",
            "Transfer-Encoding: chunked",
        ]
        token = pairing.http_headers().get("Authorization")
        if token:
            head.append(f"Authorization: {token}")
        sock.sendall(("\r\n".join(head) + "\r\n\r\n").encode("ascii"))
        return sock

    def _close_socket(self) -> None:
        sock, self._sock = self._sock, None
        if sock is not None:
            with contextlib.suppress(OSError):
                sock.close()

    def _set(self, state: str, error: str) -> None:
        self._state = state
        self._error = error

    def _sleep(self, seconds: float) -> None:
        """Wait out the backoff, but wake at once when the app is stopping."""
        self._wake.wait(seconds)
        self._wake.clear()


class OfflineLink:
    """The client used before a link exists: accepts and counts, never blocks.

    A send before ``connect`` used to go to a UDP socket; there is no UDP lane any
    more, so the honest behaviour is to count the drop and let the UI say "no link".
    """

    def __init__(self) -> None:
        self.dropped = 0
        self.messages: list[tuple[str, Any]] = []

    def send_message(self, address: str, args: Any = None) -> None:
        self.dropped += 1
        self.messages.append((str(address), args))
        if len(self.messages) > LINK_RECORD_MAX * 2:
            del self.messages[: len(self.messages) - LINK_RECORD_MAX]
