"""The control-plane envelope between the tracker child and the app (e90s01).

The camera and the ONNX models move OUT of the process that runs the show
(e90s02/e90s03); this module is the only thing both sides must agree on. It is
PURE: no socket, no process, no camera, no dpg. The wire is a length-prefixed
body whose head is a JSON header and whose tail is the raw float32 landmark
payload plus an optional preview JPEG.

Size discipline: every field is bounded (``MAX_FRAME_BYTES``,
``MAX_PAYLOAD_BYTES``, ``MAX_PREVIEW_BYTES``, ``MAX_DIMENSION``) so a hostile or
corrupted stream cannot make the app allocate without limit. A malformed body
raises ``TrackPipeError`` with a ``reason``; the reader loop (e90s02) turns that
into a supervisor status, never into a crash.

Provenance: study ``specs/TRACKING_INSTRUMENT_STAGE_LATEST.md`` §3 (the control
plane) and §5 (why the seam sits at the landmarks, not at the mapped values).
"""

import json
import math
from dataclasses import dataclass
from typing import Any, Protocol

import numpy as np

ENGINE_HAND = "hand"
ENGINE_BODY = "body"
ENGINE_ZONES = "zones"
ENGINES: tuple[str, ...] = (ENGINE_HAND, ENGINE_BODY, ENGINE_ZONES)

KIND_FRAME = "frame"
KIND_BEAT = "beat"
KIND_HELLO = "hello"
KIND_CONFIG = "config"
KIND_SIGNALS = "signals"

PROTOCOL_VERSION = 1
LENGTH_BYTES = 4
FLOAT_BYTES = 4
HEADER_SEPARATOR = b"\n"
MAX_FRAME_BYTES = 2 * 1024 * 1024
MAX_PAYLOAD_BYTES = 256 * 1024
MAX_PREVIEW_BYTES = 512 * 1024
MAX_DIMENSION = 8192
MAX_TIMINGS = 4
MAX_SIGNAL_GROUPS = 64
MAX_SIGNAL_KEYS = 32
MAX_SIGNAL_VALUE = 1.0e6

REASON_TRUNCATED = "truncated"
REASON_HEADER = "header"
REASON_VERSION = "version"
REASON_TOKEN = "token"
REASON_KIND = "kind"
REASON_ENGINE = "engine"
REASON_SIZE = "size"
REASON_SHAPE = "shape"
REASON_VALUE = "value"
REASON_SEQUENCE = "sequence"


class TrackPipeError(ValueError):
    """A rejected message. ``reason`` is a stable code for the supervisor."""

    def __init__(self, reason: str, detail: str) -> None:
        self.reason = reason
        self.detail = detail
        super().__init__(f"track pipe {reason}: {detail}")


@dataclass(frozen=True)
class TrackingFrame:
    """One engine frame as landmarks: the child's output, the parent's input."""

    engine: str
    seq: int
    t_mono: float
    frame_w: int
    frame_h: int
    payload: Any  # np.ndarray float32, shape recorded in ``payload_shape``
    payload_shape: tuple[int, ...]
    score: float
    timings: tuple[float, ...]
    preview: bytes | None = None
    label: str = ""  # engine detail: the hand side, the body slot, a reason


@dataclass(frozen=True)
class Beat:
    """A liveness message: proves the child is running when no frame flows."""

    t_mono: float
    status: str = ""  # the child's own engine status (missing-deps, no-camera, live)


@dataclass(frozen=True)
class Handshake:
    """The child's first message: protocol version and the session token."""

    version: int
    token: str


@dataclass(frozen=True)
class Signals:
    """A processed snapshot already reduced to named values (zones, bodies).

    Not every engine measures landmarks: the zones engine measures motion and
    the body engine owns its continuity tracker, so what crosses the seam is the
    finished snapshot. The hand keeps the landmark envelope because that is
    where the operator tunes gates and the interaction box.
    """

    engine: str
    seq: int
    t_mono: float
    values: dict[str, dict[str, float]]
    timings: tuple[float, ...] = ()
    preview: bytes | None = None


@dataclass(frozen=True)
class Control:
    """The parent's configuration message: engines, device, options, preview."""

    config: dict[str, Any]


Envelope = TrackingFrame | Signals | Beat | Handshake | Control


class TrackerSource(Protocol):
    """What the rest of the app is allowed to know about a frame source."""

    def start(self) -> None: ...

    def stop(self) -> None: ...

    def alive(self) -> bool: ...

    def status(self) -> str: ...

    def latest(self, engine: str) -> TrackingFrame | None: ...


def _header(envelope: Envelope) -> dict[str, Any]:
    if isinstance(envelope, Handshake):
        return {"kind": KIND_HELLO, "version": envelope.version, "token": envelope.token}
    if isinstance(envelope, Beat):
        return {"kind": KIND_BEAT, "t": envelope.t_mono, "status": envelope.status}
    if isinstance(envelope, Control):
        return {"kind": KIND_CONFIG, "config": envelope.config}
    if isinstance(envelope, Signals):
        return {
            "kind": KIND_SIGNALS,
            "engine": envelope.engine,
            "seq": envelope.seq,
            "t": envelope.t_mono,
            "values": envelope.values,
            "timings": list(envelope.timings),
            "preview": len(envelope.preview or b""),
        }
    return {
        "kind": KIND_FRAME,
        "engine": envelope.engine,
        "seq": envelope.seq,
        "t": envelope.t_mono,
        "w": envelope.frame_w,
        "h": envelope.frame_h,
        "shape": list(envelope.payload_shape),
        "score": envelope.score,
        "timings": list(envelope.timings),
        "payload": int(np.asarray(envelope.payload).nbytes),
        "preview": len(envelope.preview or b""),
        "label": envelope.label,
    }


def _frame_bytes(header: dict[str, Any], payload: bytes, preview: bytes) -> bytes:
    body = json.dumps(header, separators=(",", ":")).encode() + HEADER_SEPARATOR + payload + preview
    if len(body) > MAX_FRAME_BYTES:
        raise TrackPipeError(REASON_SIZE, f"frame {len(body)} > {MAX_FRAME_BYTES}")
    return len(body).to_bytes(LENGTH_BYTES, "big") + body


def encode(envelope: Envelope) -> bytes:
    """Serialise one envelope with its 4-byte length prefix."""
    header = _header(envelope)
    payload = b""
    preview = b""
    if isinstance(envelope, Signals):
        return _frame_bytes(_header(envelope), b"", envelope.preview or b"")
    if isinstance(envelope, Control):
        return _frame_bytes(_header(envelope), b"", b"")
    if isinstance(envelope, TrackingFrame):
        payload = np.ascontiguousarray(envelope.payload, dtype=np.float32).tobytes()
        preview = envelope.preview or b""
        if len(preview) > MAX_PREVIEW_BYTES:
            raise TrackPipeError(REASON_SIZE, f"preview {len(preview)} > {MAX_PREVIEW_BYTES}")
    return _frame_bytes(header, payload, preview)


def _split(body: bytes) -> tuple[dict[str, Any], bytes, bytes]:
    cut = body.find(HEADER_SEPARATOR)
    if cut <= 0:
        raise TrackPipeError(REASON_HEADER, "no header separator")
    try:
        header = json.loads(body[:cut])
    except (ValueError, UnicodeDecodeError) as exc:
        raise TrackPipeError(REASON_HEADER, f"bad json: {exc}") from exc
    if not isinstance(header, dict):
        raise TrackPipeError(REASON_HEADER, f"header is {type(header).__name__}")
    tail = body[cut + 1 :]
    payload_len = _bounded_int(header.get("payload", 0), MAX_PAYLOAD_BYTES, "payload")
    preview_len = _bounded_int(header.get("preview", 0), MAX_PREVIEW_BYTES, "preview")
    if len(tail) != payload_len + preview_len:
        raise TrackPipeError(
            REASON_TRUNCATED,
            f"tail {len(tail)} != payload {payload_len} + preview {preview_len}",
        )
    payload = tail[:payload_len]
    preview = tail[payload_len:]
    return header, payload, preview


def _bounded_int(value: Any, maximum: int, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise TrackPipeError(REASON_SIZE, f"{name} is {value!r}")
    if value > maximum:
        raise TrackPipeError(REASON_SIZE, f"{name} {value} > {maximum}")
    return value


def _shape(header: dict[str, Any], payload_len: int) -> tuple[int, ...]:
    raw = header.get("shape")
    if not isinstance(raw, list) or not raw or len(raw) > 3:
        raise TrackPipeError(REASON_SHAPE, f"shape is {raw!r}")
    dims = tuple(_bounded_int(dimension, MAX_DIMENSION, "dim") for dimension in raw)
    if math.prod(dims) * FLOAT_BYTES != payload_len:
        raise TrackPipeError(
            REASON_SHAPE,
            f"shape {dims} needs {math.prod(dims) * FLOAT_BYTES} bytes, got {payload_len}",
        )
    return dims


def _finite(value: Any, name: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
        raise TrackPipeError(REASON_VALUE, f"{name} is {value!r}")
    return float(value)


def _frame(header: dict[str, Any], payload: bytes, preview: bytes) -> TrackingFrame:
    engine = header.get("engine")
    if engine not in ENGINES:
        raise TrackPipeError(REASON_ENGINE, f"engine is {engine!r}")
    shape = _shape(header, len(payload))
    timings = header.get("timings")
    if not isinstance(timings, list) or len(timings) > MAX_TIMINGS:
        raise TrackPipeError(REASON_VALUE, f"timings is {timings!r}")
    return TrackingFrame(
        engine=str(engine),
        seq=_bounded_int(header.get("seq"), 2**32 - 1, "seq"),
        t_mono=_finite(header.get("t"), "t"),
        frame_w=_bounded_int(header.get("w"), MAX_DIMENSION, "w"),
        frame_h=_bounded_int(header.get("h"), MAX_DIMENSION, "h"),
        payload=np.frombuffer(payload, dtype=np.float32).reshape(shape).copy(),
        payload_shape=shape,
        score=_finite(header.get("score"), "score"),
        timings=tuple(_finite(value, "timing") for value in timings),
        preview=preview or None,
        label=str(header.get("label") or ""),
    )


def decode(body: bytes) -> Envelope:
    """Parse one body. Raises ``TrackPipeError`` with a stable ``reason``."""
    header, payload, preview = _split(body)
    kind = header.get("kind")
    if kind == KIND_FRAME:
        return _frame(header, payload, preview)
    if kind == KIND_BEAT:
        return Beat(_finite(header.get("t"), "t"), str(header.get("status") or ""))
    if kind == KIND_HELLO:
        return _handshake(header)
    if kind == KIND_SIGNALS:
        return _signals(header, preview)
    if kind == KIND_CONFIG:
        config = header.get("config")
        if not isinstance(config, dict):
            raise TrackPipeError(REASON_VALUE, f"config is {type(config).__name__}")
        return Control(config)
    raise TrackPipeError(REASON_KIND, f"kind is {kind!r}")


def _signal_value(value: Any) -> float:
    number = _finite(value, "signal")
    if abs(number) > MAX_SIGNAL_VALUE:
        raise TrackPipeError(REASON_VALUE, f"signal {number} out of range")
    return number


def _signals(header: dict[str, Any], preview: bytes) -> Signals:
    engine = header.get("engine")
    if engine not in ENGINES:
        raise TrackPipeError(REASON_ENGINE, f"engine is {engine!r}")
    raw = header.get("values")
    if not isinstance(raw, dict) or len(raw) > MAX_SIGNAL_GROUPS:
        raise TrackPipeError(REASON_VALUE, f"values is {type(raw).__name__}")
    values: dict[str, dict[str, float]] = {}
    for group, row in raw.items():
        if not isinstance(group, str) or not isinstance(row, dict) or len(row) > MAX_SIGNAL_KEYS:
            raise TrackPipeError(REASON_VALUE, f"group {group!r} is malformed")
        values[group] = {str(key): _signal_value(value) for key, value in row.items()}
    timings = header.get("timings")
    if not isinstance(timings, list) or len(timings) > MAX_TIMINGS:
        raise TrackPipeError(REASON_VALUE, f"timings is {timings!r}")
    return Signals(
        engine=str(engine),
        seq=_bounded_int(header.get("seq"), 2**32 - 1, "seq"),
        t_mono=_finite(header.get("t"), "t"),
        values=values,
        timings=tuple(_finite(value, "timing") for value in timings),
        preview=preview or None,
    )


def _handshake(header: dict[str, Any]) -> Handshake:
    version = header.get("version")
    if version != PROTOCOL_VERSION:
        raise TrackPipeError(REASON_VERSION, f"version {version!r} != {PROTOCOL_VERSION}")
    token = header.get("token")
    if not isinstance(token, str) or not token:
        raise TrackPipeError(REASON_TOKEN, "token missing")
    return Handshake(version=PROTOCOL_VERSION, token=token)


def _read_exact(stream: Any, size: int) -> bytes:
    """Read exactly ``size`` bytes from a file object or a socket (short reads loop)."""
    reader = getattr(stream, "recv", None) or stream.read
    chunks: list[bytes] = []
    remaining = size
    while remaining > 0:
        chunk = reader(remaining)
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def read_body(stream: Any) -> bytes:
    """Read one length-prefixed body from a blocking binary stream or socket.

    Returns ``b""`` on a clean EOF. Raises ``TrackPipeError`` when the prefix is
    missing or the announced length is out of bounds.
    """
    prefix = _read_exact(stream, LENGTH_BYTES)
    if not prefix:
        return b""
    if len(prefix) != LENGTH_BYTES:
        raise TrackPipeError(REASON_TRUNCATED, f"prefix {len(prefix)} bytes")
    announced = int.from_bytes(prefix, "big")
    if announced > MAX_FRAME_BYTES:
        raise TrackPipeError(REASON_SIZE, f"announced {announced} > {MAX_FRAME_BYTES}")
    body = _read_exact(stream, announced)
    if len(body) != announced:
        raise TrackPipeError(REASON_TRUNCATED, f"body {len(body)} of {announced}")
    return body


class Sequenced(Protocol):
    """What the sequence guard needs: an engine name and a monotonic counter."""

    @property
    def engine(self) -> str: ...

    @property
    def seq(self) -> int: ...


class SequenceGuard:
    """Accepts only a strictly newer sequence per engine (stale frame = drop)."""

    def __init__(self) -> None:
        self._last: dict[str, int] = {}

    def accept(self, frame: Sequenced) -> bool:
        previous = self._last.get(frame.engine)
        if previous is not None and frame.seq <= previous:
            return False
        self._last[frame.engine] = frame.seq
        return True

    def reset(self) -> None:
        self._last.clear()


class InlineSource:
    """The reference ``TrackerSource``: today's in-process producer.

    It publishes exactly the envelopes the child would, so every consumer and
    every test can be written against the seam before a real child exists. The
    same fake frames through this class and through a recorded child stream must
    be byte-identical (the parity contract of e90s01).
    """

    STATUS_INLINE = "inline"

    def __init__(self, status: str = STATUS_INLINE) -> None:
        self._latest: dict[str, TrackingFrame] = {}
        self._status = status
        self._started = False

    def start(self) -> None:
        self._started = True

    def stop(self) -> None:
        self._started = False

    def alive(self) -> bool:
        return self._started

    def status(self) -> str:
        return self._status

    def publish(self, frame: TrackingFrame) -> None:
        self._latest[frame.engine] = frame

    def latest(self, engine: str) -> TrackingFrame | None:
        return self._latest.get(engine)

    def clear(self) -> None:
        self._latest.clear()
