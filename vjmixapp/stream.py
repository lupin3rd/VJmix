"""The viOSC delta stream client (e82s04). dpg-free (HIGH-1).

The state table used to arrive by polling (1 Hz) or by an OSC broadcast. `GET
/events` makes it a push over the SAME HTTP plane: Server-Sent Events, one frame
per applied change, each carrying the mirror's `rev`.

The revision is the contract. A gap, an `overflow` marker or a reconnect means
this client missed at least one change, so the only safe move is to refetch the
snapshot — the ordering guarantee UDP could never give. A duplicate is dropped:
an old value must never overwrite a newer one.

The worker is the only writer of `state.event_rev` besides the snapshot ingest;
the main thread drains `state.event_queue` and applies the events to the table.
"""

import contextlib
import json
import time
import urllib.error
import urllib.request
from typing import Any

from vjmixapp import dataplane, iomonitor, pairing, state
from vjmixapp.constants import (
    EVENTS_PATH,
    IO_MONITOR_KIND_EVENT_STREAM,
    STREAM_BACKOFF_MAX,
    STREAM_READ_TIMEOUT,
)
from vjmixapp.queues import log_error

EVENT_KIND_CHANGED = "changed"
EVENT_KIND_CURRENT = "current"
EVENT_KIND_OVERFLOW = "overflow"
# `added`/`removed` are a roster change: only the snapshot knows the full record.
EVENT_KINDS_NEEDING_SNAPSHOT = (EVENT_KIND_OVERFLOW, "added", "removed")
# The worker's OWN cursor: the last revision it enqueued. It must not use
# state.event_rev (the main thread applies later) or a backlog would look like a
# gap. Reset from state.event_rev at every connect, so a disconnect IS a gap.
_last_stream_rev = 0


def reset_cursor(rev: int) -> None:
    """Point the worker's cursor at what this app has already applied."""
    global _last_stream_rev
    _last_stream_rev = int(rev)


def stream_cursor() -> int:
    """The last revision the worker enqueued (a test/debug read)."""
    return _last_stream_rev


def events_url(host: str, port: int) -> str:
    """HTTP URL of the delta stream on the viOSC data plane."""
    return f"http://{host}:{port}{EVENTS_PATH}"


def parse_event(lines: list[str]) -> dict[str, Any] | None:
    """The `data:` payload of one SSE frame, or None (a comment, a malformed payload)."""
    for line in lines:
        if not line.startswith("data:"):
            continue
        try:
            payload = json.loads(line[len("data:") :].strip())
        except (ValueError, TypeError):
            return None
        return payload if isinstance(payload, dict) else None
    return None


def gap_after(last_rev: int, rev: int) -> bool:
    """True when `rev` skips at least one revision this client never applied."""
    return int(rev) > int(last_rev) + 1


def source_props(sources: dict[str, Any], name: Any) -> dict[str, Any] | None:
    """The table entry addressed by a source NAME (VJmix addresses by name)."""
    for props in sources.values():
        if isinstance(props, dict) and str(props.get("name")) == str(name):
            return props
    return None


def current_index(sources: dict[str, Any], name: Any) -> int | None:
    """The table key (vimix index) of a source name, or None."""
    for key, props in sources.items():
        if isinstance(props, dict) and str(props.get("name")) == str(name):
            with contextlib.suppress(TypeError, ValueError):
                return int(key)
    return None


def apply_change(sources: dict[str, Any], event: dict[str, Any]) -> bool:
    """Write one `changed` event into the table in place; False when it cannot apply."""
    if str(event.get("kind") or "") != EVENT_KIND_CHANGED:
        return False
    prop = event.get("prop")
    if not prop:
        return False
    props = source_props(sources, event.get("source"))
    if props is None:
        return False
    props[str(prop)] = event.get("value")
    return True


def resync_snapshot(host: str, port: int) -> bool:
    """Refetch the whole table after a hole; the snapshot carries its own `rev`."""
    text, _answered, _status = dataplane.fetch_state_ex(host, port)
    if text is None:
        return False
    with contextlib.suppress(ValueError, TypeError):
        payload = json.loads(text)
        revision = payload.get("rev") if isinstance(payload, dict) else None
        if isinstance(revision, int):
            state.event_rev = revision
            reset_cursor(revision)
    state.ui_state_queue.put(text)
    return True


def handle_frame(lines: list[str], host: str = "", port: int = 0) -> None:
    """Apply the unit of the stream: enqueue the event, or resync on a hole."""
    event = parse_event(lines)
    if event is None:
        return
    kind = str(event.get("kind") or "")
    if kind in EVENT_KINDS_NEEDING_SNAPSHOT:
        resync_snapshot(host or state.dataplane_host, port or state.dataplane_port)
        return
    rev = event.get("rev")
    if not isinstance(rev, int):
        return
    if rev <= _last_stream_rev:
        return  # a duplicate or an old revision: never let it win
    if gap_after(_last_stream_rev, rev):
        resync_snapshot(host or state.dataplane_host, port or state.dataplane_port)
        return
    state.event_queue.put(event)
    reset_cursor(rev)


def read_stream(host: str, port: int) -> None:
    """Read ONE `/events` session until the server closes it (never raises on EOF)."""
    request = urllib.request.Request(events_url(host, port), headers=pairing.http_headers())
    with urllib.request.urlopen(request, timeout=STREAM_READ_TIMEOUT) as response:
        if response.status != 200:
            raise ConnectionError(f"/events answered HTTP {response.status}")
        state.event_stream_supported = True
        iomonitor.record_http(
            IO_MONITOR_KIND_EVENT_STREAM, EVENTS_PATH, "open", f"{host}:{port}", 200
        )
        reset_cursor(state.event_rev)
        frame: list[str] = []
        while True:
            raw = response.readline()
            if not raw:
                return
            line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
            if not line:
                if frame:
                    handle_frame(frame, host, port)
                    frame = []
                continue
            if not line.startswith(":"):
                frame.append(line)


def stream_worker(host: str = "", port: int = 0) -> None:
    """Read the stream forever; a 404 gives the lane up for the session (HIGH-1 safe).

    An older daemon has no `/events` at all: one answered 404 is enough to stop
    probing (the route set does not appear later), and the 1 Hz `/state` pull keeps
    the table alive exactly as before. Any other failure retries with backoff, so a
    restarting viOSC is picked up by itself.
    """
    backoff = 1.0
    while True:
        host = host or state.dataplane_host
        port = port or state.dataplane_port
        if not host or not port:
            time.sleep(1.0)
            host, port = "", 0
            continue
        try:
            read_stream(host, port)
            backoff = 1.0
        except urllib.error.HTTPError as e:
            if e.code == 404:
                state.event_stream_supported = False
                log_error(
                    "State stream",
                    "the endpoint has no /events (older viOSC) — using the /state pull lane",
                )
                return
            log_error("State stream", f"HTTP {e.code}")
        except Exception as e:  # a worker thread must never die (Defensive Code)
            log_error("State stream", str(e))
        time.sleep(backoff)
        backoff = min(backoff * 2, STREAM_BACKOFF_MAX)
