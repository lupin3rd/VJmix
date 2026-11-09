"""OSC communication for VJmix (REFACTOR_LATEST.md commit 7/13).

The conversation with viOSC: the UDP receiver (server class + default
handler routing replies into the queues), the thumbnail decode worker and
the pure vimix-state queries. WORKER-SAFE: this module never imports dpg
(HIGH-1) — the server thread and the decode thread only touch queues.
UI status wiring (server/client buttons) and reply rendering stay in the
composition root until the ui commit.
"""

import contextlib
import contextvars
import io
import math
import time
from collections.abc import Iterator
from typing import Any

import numpy as np
from PIL import Image
from pythonosc import udp_client

from vjmixapp import cmdlink, dataplane, iomonitor, state
from vjmixapp.constants import (
    IO_MONITOR_DIRECTION_OUT,
    IO_MONITOR_KIND_DESTINATION,
    IO_MONITOR_KIND_MONITOR,
    IO_MONITOR_KIND_OSC,
    IO_MONITOR_KIND_OSC_SO,
    IO_MONITOR_KIND_STATE_PULL,
    IO_MONITOR_KIND_SYNC,
    IO_MONITOR_KIND_VIMIX,
    IO_MONITOR_KIND_VIOSC,
    IO_MONITOR_KIND_WATCH,
    MAPPING_OSC_MAX_PORT,
    MAPPING_SO_DEFAULT_TRANSPORT,
    MAPPING_SO_MIDI_CHANNEL,
    MAPPING_SO_MIDI_GATE_MAX_MS,
    MAPPING_SO_MIDI_GATE_MIN_MS,
    MAPPING_SO_MIDI_GATE_MS,
    MAPPING_SO_MIDI_NUMBER,
    MAX_THUMBNAIL_PIXELS,
    MIDI_KIND_CC,
    SECONDARY_OUTPUT_ARGS,
    SECONDARY_OUTPUT_TRANSPORTS,
    SO_MIDI_MESSAGES,
    STATE_PATH,
    STATE_PULL_MAX_FAILURES,
    STATE_PULL_STREAM_INTERVAL,
    THUMB_REQUESTS_PER_SOURCE,
    VIOSC_IP,
    VIOSC_PORT,
)
from vjmixapp.queues import log_error

# NOTE: the client is created at the END of the module, once observe_client
# exists (the wrapper is defined further down with the I/O Monitor plumbing).


ALL_PROPERTIES = [
    "index",
    "name",
    "lock",
    "failed",
    "play",
    "pause",
    "blending",
    "alpha",
    "transparency",
    "depth",
    "position",
    "size",
    "corner",
    "angle",
    "seek",
    "speed",
    "brightness",
    "contrast",
    "saturation",
    "hue",
    "threshold",
    "gamma",
    "color",
    "posterize",
    "invert",
    "uri",
    "type",
    # e82s05: the state tier of the mirror (e82s01/e82s02) — readable attributes
    # that used to be missing from the raw vocabulary.
    "correction",
    "id",
]


def raw_cell_text(prop: str, value: Any, asked: set[str]) -> str:
    """The raw table cell: `·` = never asked, `---` = asked with no value (e82s05).

    Before the tier most columns were drawn `---` simply because nobody had ever
    asked vimix; now those two states mean different things and the table must
    not blur them. `id` is an int64 and is never formatted as a float.
    """
    if value is None:
        return "---" if str(prop) in asked else "·"
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def thumbnail_decoder_worker() -> None:
    while True:
        name, idx, blob_bytes = state.blob_queue.get()
        try:
            image = Image.open(io.BytesIO(blob_bytes))
            width, height = image.size
            if width * height > MAX_THUMBNAIL_PIXELS:
                raise ValueError(f"thumbnail too large: {width}x{height} px")
            rgba = image.convert("RGBA")
            img_data = np.array(rgba, dtype=np.float32) / 255.0
            state.texture_queue.put((name, idx, img_data.flatten(), width, height))
        except Exception as e:
            print(f"[VJmix Decoder Error] Unable to decode '{name}': {e}")
        state.blob_queue.task_done()


def fetch_one_thumbnail(name: str, index: int) -> bool:
    """Fetch one frame over the HTTP plane (e41s03, HTTP-only since e98s05).

    There is no second lane to fall back to: a daemon that does not answer is a
    daemon that is down (or too old, which the version gate refuses first). The
    tile shows "no thumbnail" and the next cycle retries — the honest behaviour,
    and the reason the failure counter and its demotion are gone.
    """
    host = state.dataplane_host
    port = state.dataplane_port
    blob, _answered = dataplane.fetch_thumbnail(host, port, name, index)
    if blob is None:
        return False
    state.blob_queue.put((name, str(index), blob))
    return True


def thumbnail_fetch_worker() -> None:
    """Drain the data-plane fetch queue, one thumbnail at a time (e41s03).

    The OSC lane's replies arrive on the OSC server thread; this worker is the
    data plane's equivalent source, and it feeds the SAME blob queue — so the
    decode worker and every texture consumer are untouched by the new transport.
    """
    while True:
        name, index = state.thumb_fetch_queue.get()
        try:
            fetch_one_thumbnail(name, index)
        except Exception as e:  # a worker thread must never die (Defensive Code)
            log_error("Thumbnail data plane", str(e))
        state.thumb_fetch_queue.task_done()


def poll_state_once() -> bool:
    """Read the state table once over the data plane (e41s04).

    Returns True when the table was ingested into ``ui_state_queue`` — the SAME
    queue the OSC push fills, so every consumer (Mediagrid, raw table, Mapping
    engine) is unchanged.

    Lane giving-up is asymmetric on purpose: a server that ANSWERS without a
    /state route is an older daemon, and a route set does not appear and
    disappear, so one answered failure is enough; a server that does not answer
    at all may simply be busy, so it takes STATE_PULL_MAX_FAILURES in a row.
    """
    etag = state.event_rev if state.event_rev > 0 else None
    text, answered, status = dataplane.fetch_state_ex(
        state.dataplane_host, state.dataplane_port, etag
    )
    iomonitor.record_http(
        IO_MONITOR_KIND_STATE_PULL,
        STATE_PATH,
        f"HTTP {status}" if status is not None else "no answer",
        f"{state.dataplane_host}:{state.dataplane_port}",
        status,
    )
    if answered and status == 304:
        # e82s04: the table did not change since the last revision: the answer IS
        # the freshness, and the round trip cost headers only.
        state.state_pull_failures = 0
        state.last_viosc_state_ts = time.monotonic()
        return True
    if text is not None:
        state.state_pull_failures = 0
        state.last_viosc_state_ts = time.monotonic()
        state.ui_state_queue.put(text)
        return True
    if answered and status == 401:
        # BUG-2026-09-13T231500: before the pairing prompt is answered the data
        # plane answers 401 — "pair first", not "broken": the worker retries every
        # interval and the poll succeeds as soon as the token exists.
        return False
    if answered:
        log_error("State data plane", "the endpoint answered without /state — update viOSC")
        return False
    state.state_pull_failures += 1
    if state.state_pull_failures >= STATE_PULL_MAX_FAILURES:
        log_error(
            "State data plane",
            f"{state.dataplane_host}:{state.dataplane_port} not answering",
        )
    return False


def state_poll_worker() -> None:
    """Read the state table at VISeq's own cadence (e41s04).

    The cadence is the whole point of the pull: the push fires whenever vimix
    changes a property, so the rate belongs to vimix; here VJmix asks only as
    often as it can afford, which is the backpressure the push cannot express.
    """
    while True:
        try:
            poll_state_once()
        except Exception as e:  # a worker thread must never die (Defensive Code)
            log_error("State data plane", str(e))
        # e82s04/e98s05: the snapshot only reconciles (churn, drift) — /events is
        # the live lane — so it steps back to the slow cadence, unconditionally.
        time.sleep(STATE_PULL_STREAM_INTERVAL)


def get_current_target_id() -> str | None:
    """Return the target id of the currently selected media (e10s06).

    The VJmix Mediagrid selection is primary; before the first click (or after
    the selected source is removed) it falls back to the vimix current source.
    """
    if state.vjmix_selected_source is not None:
        return state.vjmix_selected_source
    current_source = state.global_vimix_state.get("current_source")
    if current_source is None:
        return None
    for k, props in state.global_vimix_state.get("sources", {}).items():
        if str(k) == str(current_source):
            name = props.get("name")
            return str(name) if name else str(k)
    return None


def find_source_by_name(name: str) -> Any:
    for idx, props in state.global_vimix_state.get("sources", {}).items():
        if str(props.get("name")) == str(name):
            return idx, props
    return None, None


def next_thumb_frame_index(received: int, frames_at_last_request: int) -> int | None:
    """The next thumbnail frame index to ask for, or None to stop (e41s02).

    viOSC answers a digit index with ONE blob, so walking the indices keeps at
    most one thumbnail datagram in flight instead of the back-to-back burst an
    `all` request produces. The walk is bounded by the per-media frame budget and
    is progress-based:

    - nothing received yet -> keep asking frame 0, which keeps the e10s04
      retry/failure accounting exactly as it was;
    - the frame count grew since the last request -> ask for the next index;
    - it did NOT grow -> the daemon has no more frames for this source (an
      image), so stop instead of polling a non-existent index forever.
    """
    if received >= THUMB_REQUESTS_PER_SOURCE:
        return None
    if received == 0:
        return 0
    if received == frames_at_last_request:
        return None
    return received


# e40s03: OSC OUTPUT DESTINATIONS — an opt-in third-party egress.
# One cached SimpleUDPClient per (host, port) so a Mapping never recreates a socket
# per emission; a destination is validated before any send (address must be an
# OSC path, port in range, host non-empty). The viOSC client above is untouched:
# /vimix traffic never goes through here.

_mapping_clients: dict[tuple[str, int], Any] = {}


_OSC_KIND_BY_PREFIX: tuple[tuple[str, str], ...] = (
    ("/vimix/", IO_MONITOR_KIND_VIMIX),
    ("/viosc/watch/", IO_MONITOR_KIND_WATCH),
    ("/viosc/sync/", IO_MONITOR_KIND_SYNC),
    ("/viosc/monitor", IO_MONITOR_KIND_MONITOR),
    ("/viosc/", IO_MONITOR_KIND_VIOSC),
)


def kind_of(address: str) -> str:
    """The monitor kind of an outgoing OSC address (e39s05).

    The address says WHAT the message is; the kind says WHY it exists, so the
    chatty or instrumental senders (fade, sequencer, cue, a third-party
    Destination) pass their own kind explicitly instead of relying on this table.
    """
    for prefix, kind in _OSC_KIND_BY_PREFIX:
        if address.startswith(prefix):
            return kind
    return IO_MONITOR_KIND_OSC


def viosc_peer() -> str:
    """The 'host:port' of the viOSC client actually in use (the Monitor's Peer column)."""
    client = state.viosc_client or osc_client
    peer = getattr(client, "_peer", None)
    if peer:
        return str(peer)
    host = getattr(client, "_address", None) or VIOSC_IP
    port = getattr(client, "_port", None) or VIOSC_PORT
    return f"{host}:{port}"


# e39s05: the sender context — the chatty loops (fade, sequencer, cue) name
# themselves for the duration of a send, without changing any call signature:
# a fake client in the tests keeps working untouched.
_current_kind: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "osc_send_kind", default=None
)


@contextlib.contextmanager
def sent_by(kind: str) -> Iterator[None]:
    """Tag the OSC messages sent inside this block with a kind (e39s05).

    The address says WHAT a message is; the kind says WHY it exists. For the
    address-derived traffic the table in ``kind_of`` is enough, but a fade, a
    sequencer step and a cue row all write ``/vimix/...``: only the caller knows
    which one it is. Context-local, so the sequencer thread and the main-loop
    fade tick never leak into each other.
    """
    token = _current_kind.set(str(kind))
    try:
        yield
    finally:
        _current_kind.reset(token)


class ObservedClient:
    """A UDP client whose every send is reported to the I/O Monitor (e39s05).

    The wrapper is transparent: attribute access delegates to the wrapped client
    (so the tests' recording fakes keep exposing ``.messages``), and nothing on
    the wire changes — ``send_message`` forwards the arguments UNTOUCHED, so every
    message stays byte-identical. This is the one place an outgoing OSC message
    leaves VJmix, which is what makes the Monitor complete without touching the
    26 call sites.
    """

    def __init__(self, client: Any, peer: str) -> None:
        self._client = client
        self._peer = str(peer)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)

    def send_message(self, address: str, args: Any = None) -> None:
        """Send one OSC message and record it (the payload itself is not kept)."""
        self._client.send_message(address, args)
        iomonitor.record_osc(
            IO_MONITOR_DIRECTION_OUT,
            _current_kind.get() or kind_of(address),
            address,
            iomonitor.summarize_osc_args(args),
            self._peer,
        )


def observe_client(client: Any, peer: str) -> ObservedClient:
    """Wrap a UDP client so its sends reach the I/O Monitor (e39s05)."""
    if isinstance(client, ObservedClient):
        return client
    return ObservedClient(client, peer)


class VioscClientRouter:
    """The module-level client: routes each send to the client actually in use.

    BUG-2026-09-13T135000: every sender writes ``osc_client.send_message(...)``,
    while the endpoint the user configures lives in ``state.viosc_client`` (set by
    ``connect_osc_client`` from the persisted endpoints). The module client used
    to be bound to the VIOSC_IP/VIOSC_PORT constants forever, so on a rig with a
    non-default host/port the sequencer, the fades, the cue rows and the Mapper
    values went to the WRONG address while the e40 state lane (which reads
    ``state.viosc_client`` directly) worked — the most confusing symptom possible.

    The router resolves at CALL time, so no call site changes and the wired
    endpoint is a single source of truth. It is transparent: attribute access
    delegates to the active client (a test that reads ``osc_client.messages``
    follows whichever client is in use).
    """

    def __init__(self, default: Any) -> None:
        self._default = default

    def active(self) -> Any:
        """The client in use: the configured one when connected, else the default."""
        return state.viosc_client or self._default

    def __getattr__(self, name: str) -> Any:
        return getattr(self.active(), name)

    def send_message(self, address: str, args: Any = None) -> Any:
        return self.active().send_message(address, args)


# The module client: a constant-endpoint default for the case where the
# composition root has not connected a configured one yet.
# e98s04: with no link up, a send is absorbed and counted — there is no UDP lane
# to fall back to, and a lost command must never raise into a fade or the grid.
osc_client = VioscClientRouter(observe_client(cmdlink.OfflineLink(), f"{VIOSC_IP}:{VIOSC_PORT}"))


def validate_destination(spec: Any) -> str | None:
    """The problem with an OSC destination spec, or None when it is usable (e40s03)."""
    if not isinstance(spec, dict):
        return "missing OSC destination"
    host = str(spec.get("host") or "").strip()
    if not host:
        return "OSC host is empty"
    raw_port = spec.get("port")
    try:
        port = int(raw_port) if raw_port is not None else 0
    except (TypeError, ValueError):
        return f"OSC port {raw_port!r} is not a number"
    if not 1 <= port <= MAPPING_OSC_MAX_PORT:
        return f"OSC port {port} out of range 1..{MAPPING_OSC_MAX_PORT}"
    address = str(spec.get("address") or "").strip()
    if not address.startswith("/") or len(address) < 2:
        return f"OSC address {address!r} must start with '/'"
    return None


def _client_for(host: str, port: int) -> Any:
    """The cached UDP client of one (host, port) destination (e40s03)."""
    key = (str(host), int(port))
    client = _mapping_clients.get(key)
    if client is None:
        client = udp_client.SimpleUDPClient(key[0], key[1])
        _mapping_clients[key] = client
    return client


def send_mapping_osc(spec: Any, value: float) -> bool:
    """Send one value to a Mapping's OSC destination; False on an invalid spec (e40s03).

    Best-effort and never raising into the main loop: a bad spec or a failing
    send is logged and returns False (the viOSC client and the /vimix path are
    untouched).
    """
    error = validate_destination(spec)
    if error is not None:
        log_error("OSC", f"mapping destination: {error}")
        return False
    address = str(spec["address"])
    try:
        client = _client_for(str(spec["host"]), int(spec["port"]))
        if not isinstance(client, ObservedClient):
            client = observe_client(client, f"{spec['host']}:{spec['port']}")
            _mapping_clients[(str(spec["host"]), int(spec["port"]))] = client
        with sent_by(IO_MONITOR_KIND_DESTINATION):
            client.send_message(address, [float(value)])
        return True
    except Exception as e:
        log_error("OSC", f"mapping destination {address}: {e}")
        return False


# e92: the SO (Secondary Output) — a second, MIRRORED OSC egress. One spec shape
# serves Mappings (value = the primary's emitted value, optional scale) and
# sequencer steps (value = the fixed configured value). The sanitizer is the
# persistence gate; the sender is best-effort and never raises into a caller.
def _finite_number(value: Any) -> float | None:
    """A finite float, or None for a bool/str/garbage/NaN (e92)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _secondary_output_scale(raw: dict[str, Any]) -> tuple[float, float] | None:
    """The SO scale pair, None when absent; ValueError when half/invalid (e92)."""
    has_from = "from" in raw
    has_to = "to" in raw
    if not has_from and not has_to:
        return None
    if has_from != has_to:
        raise ValueError("half scale")
    start = _finite_number(raw["from"])
    end = _finite_number(raw["to"])
    if start is None or end is None:
        raise ValueError("non-finite scale")
    return (start, end)


def _int_in_range(value: Any, low: int, high: int) -> int | None:
    """An int (or an integral float from JSON) inside [low, high], else None (e95)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = int(value)
    if number != value or not low <= number <= high:
        return None
    return number


def _sanitize_osc_block(raw: dict[str, Any]) -> dict[str, Any] | None:
    """The OSC half of an SO spec, or None when it cannot be a valid egress (e95)."""
    if validate_destination(raw) is not None:
        return None
    arg = str(raw.get("arg") or "float")
    if arg not in SECONDARY_OUTPUT_ARGS:
        return None
    return {
        "host": str(raw["host"]).strip(),
        "port": int(raw["port"]),
        "address": str(raw["address"]).strip(),
        "arg": arg,
    }


def _sanitize_midi_block(raw: dict[str, Any]) -> dict[str, Any] | None:
    """The MIDI half of an SO spec, or None when it cannot address a device (e95)."""
    device = str(raw.get("device") or "").strip()
    if not device:
        return None
    channel = _int_in_range(raw.get("channel", MAPPING_SO_MIDI_CHANNEL), 0, 15)
    number = _int_in_range(raw.get("number", MAPPING_SO_MIDI_NUMBER), 0, 127)
    gate = _int_in_range(
        raw.get("gate", MAPPING_SO_MIDI_GATE_MS),
        MAPPING_SO_MIDI_GATE_MIN_MS,
        MAPPING_SO_MIDI_GATE_MAX_MS,
    )
    msg = str(raw.get("msg") or MIDI_KIND_CC)
    if channel is None or number is None or gate is None or msg not in SO_MIDI_MESSAGES:
        return None
    return {
        "device": device,
        "channel": channel,
        "msg": msg,
        "number": number,
        "gate": gate,
    }


def sanitize_secondary_output(raw: Any) -> dict[str, Any] | None:
    """Heal one stored SO spec, or None when it cannot be a valid egress (e92/e95).

    The normalized form is ``{enabled, transport, fixed}`` plus the blocks that
    validate: `host/port/address/arg` (OSC) and `device/channel/msg/number/gate`
    (MIDI), plus ``from``/``to`` when the scale is present. Only the ACTIVE
    transport's block must be valid; the inactive one is kept when it is valid so
    that switching tabs never loses the other side's settings. An invalid active
    block yields None, so a project load drops the SO rather than the Mapping or
    the cell that carries it.
    """
    if not isinstance(raw, dict):
        return None
    transport = str(raw.get("transport") or MAPPING_SO_DEFAULT_TRANSPORT).strip()
    if transport not in SECONDARY_OUTPUT_TRANSPORTS:
        return None
    fixed = _finite_number(raw.get("fixed", 0.0))
    if fixed is None:
        return None
    try:
        scale = _secondary_output_scale(raw)
    except ValueError:
        return None
    osc_block = _sanitize_osc_block(raw)
    midi_block = _sanitize_midi_block(raw)
    if transport == "osc" and osc_block is None:
        return None
    if transport == "midi" and midi_block is None:
        return None
    spec: dict[str, Any] = {
        "enabled": bool(raw.get("enabled", True)),
        "transport": transport,
    }
    if osc_block is not None:
        spec.update(osc_block)
    if midi_block is not None:
        spec.update(midi_block)
    spec["fixed"] = fixed
    if scale is not None:
        spec["from"], spec["to"] = scale
    return spec


def _validate_midi_block(spec: dict[str, Any]) -> str | None:
    """The problem with the MIDI half of an SO spec, or None (e95)."""
    if not str(spec.get("device") or "").strip():
        return "MIDI device is required"
    if _int_in_range(spec.get("channel", MAPPING_SO_MIDI_CHANNEL), 0, 15) is None:
        return f"MIDI channel must be 0..15, got {spec.get('channel')!r}"
    msg = str(spec.get("msg") or MIDI_KIND_CC)
    if msg not in SO_MIDI_MESSAGES:
        return f"MIDI message {msg!r} must be one of {SO_MIDI_MESSAGES}"
    if _int_in_range(spec.get("number", MAPPING_SO_MIDI_NUMBER), 0, 127) is None:
        return f"MIDI number must be 0..127, got {spec.get('number')!r}"
    if (
        _int_in_range(
            spec.get("gate", MAPPING_SO_MIDI_GATE_MS),
            MAPPING_SO_MIDI_GATE_MIN_MS,
            MAPPING_SO_MIDI_GATE_MAX_MS,
        )
        is None
    ):
        return (
            f"MIDI gate must be {MAPPING_SO_MIDI_GATE_MIN_MS}.."
            f"{MAPPING_SO_MIDI_GATE_MAX_MS} ms, got {spec.get('gate')!r}"
        )
    return None


def validate_secondary_output(spec: Any) -> str | None:
    """The problem with an SO spec, or None when it is usable (e92/e95, UI-facing)."""
    if not isinstance(spec, dict):
        return "secondary output must be an object"
    transport = str(spec.get("transport") or MAPPING_SO_DEFAULT_TRANSPORT)
    if transport not in SECONDARY_OUTPUT_TRANSPORTS:
        return f"transport {transport!r} must be one of {SECONDARY_OUTPUT_TRANSPORTS}"
    if transport == "midi":
        midi_error = _validate_midi_block(spec)
        if midi_error is not None:
            return midi_error
    else:
        error = validate_destination(spec)
        if error is not None:
            return error
        arg = str(spec.get("arg") or "float")
        if arg not in SECONDARY_OUTPUT_ARGS:
            return f"OSC argument {arg!r} must be one of {SECONDARY_OUTPUT_ARGS}"
    fixed = spec.get("fixed")
    if fixed is not None and _finite_number(fixed) is None:
        return "SO value must be a finite number"
    try:
        _secondary_output_scale(spec)
    except ValueError:
        return "SO scale must give both 'from' and 'to' as finite numbers"
    return None


def secondary_output_value(
    spec: Any,
    value: float,
    output_from: float | None = None,
    output_to: float | None = None,
) -> float:
    """The value the SO sends: the primary value scaled to the SO interval (e92).

    No scale (or no output interval) is the identity. A degenerate primary
    interval yields the SO scale's ``from``; a reversed interval maps naturally.
    """
    try:
        scale = _secondary_output_scale(spec) if isinstance(spec, dict) else None
    except ValueError:
        scale = None
    if scale is None or output_from is None or output_to is None:
        return float(value)
    start, end = scale
    low, high = float(output_from), float(output_to)
    if high == low:
        return float(start)
    unit = (float(value) - low) / (high - low)
    return float(start + unit * (end - start))


def compose_secondary_output_args(
    spec: Any,
    value: float,
    output_from: float | None = None,
    output_to: float | None = None,
) -> list[Any]:
    """The OSC argument list of one SO send (e92): float, int or no-arg trigger."""
    arg = str(spec.get("arg") or "float") if isinstance(spec, dict) else "float"
    if arg == "trigger":
        return []
    scaled = secondary_output_value(spec, value, output_from, output_to)
    if arg == "int":
        return [round(scaled)]
    return [float(scaled)]


def send_secondary_output(
    spec: Any,
    value: float,
    output_from: float | None = None,
    output_to: float | None = None,
) -> bool:
    """Send one value to an SO destination; False on an invalid spec (e92).

    Best-effort, like ``send_mapping_osc``: a bad spec or a failing send is
    logged and returns False. The message is the SO's own kind in the Monitor.
    """
    error = validate_secondary_output(spec)
    if error is not None:
        log_error("OSC", f"secondary output: {error}")
        return False
    address = str(spec["address"])
    args = compose_secondary_output_args(spec, float(value), output_from, output_to)
    try:
        client = _client_for(str(spec["host"]), int(spec["port"]))
        if not isinstance(client, ObservedClient):
            client = observe_client(client, f"{spec['host']}:{spec['port']}")
            _mapping_clients[(str(spec["host"]), int(spec["port"]))] = client
        with sent_by(IO_MONITOR_KIND_OSC_SO):
            client.send_message(address, args)
        return True
    except Exception as e:
        log_error("OSC", f"secondary output {address}: {e}")
        return False
