"""Ableton Link beat source engine (e75). DPG-FREE and OSC-free (HIGH-1).

Ableton Link is a SESSION the app joins itself (Link's multicast discovery on UDP
20808), NOT a vimix attribute: nothing here talks to viOSC or vimix.

`aalink` 0.2.3 must be created INSIDE a RUNNING asyncio loop (constructed outside
one it raises "no running event loop"; its `loop=` argument is deprecated), so the
engine owns ONE daemon thread whose whole job is to run that loop and publish a
few doubles. It is optional: a missing `aalink` leaves `state.link_available`
False and the UI degrades, never crashes.

Threading contract: this thread only WRITES `state.link_*` (plain floats/ints) and
never touches DearPyGui; the main thread reads those values, exactly as it already
reads `state.current_bpm` written by the audio worker.
"""

import asyncio
import threading
import time
from typing import Any

from vjmixapp import state
from vjmixapp.queues import log_error

LINK_DEFAULT_TEMPO = 120.0
LINK_POLL_SECONDS = 0.02  # 50 Hz: the tempo text and the LED need no more
LINK_THREAD_NAME = "vjmix-link"

_link_thread: threading.Thread | None = None


def link_interval(tempo: Any) -> float:
    """Seconds per beat for a Link tempo (pure; zero/negative/garbage falls back).

    The Linked tempo is the SHARED session tempo: every peer converges on it, so a
    sequencer on LINK follows the room instead of the analyser.
    """
    bpm = float(tempo) if tempo and float(tempo) > 0 else LINK_DEFAULT_TEMPO
    return 60.0 / bpm


def publish_link_state(link: Any) -> None:
    """Copy ONE Link sample into the shared state (called by the worker thread).

    Kept separate from the loop so it is testable with a fake Link: the worker's
    only other job is the asyncio plumbing `aalink` demands.
    """
    state.link_tempo = float(link.tempo)
    state.link_beat = float(link.beat)
    state.link_phase = float(link.phase)
    state.link_peers = int(link.num_peers)


def aalink_available() -> bool:
    """True when the optional `aalink` dependency can be imported."""
    try:
        import aalink  # noqa: F401
    except Exception:
        return False
    return True


async def _link_main(aalink_module: Any) -> None:
    """The Link loop: build the Link INSIDE the running loop, then publish at 50 Hz."""
    link = aalink_module.Link(LINK_DEFAULT_TEMPO)
    state.link_available = True
    while True:
        publish_link_state(link)
        await asyncio.sleep(LINK_POLL_SECONDS)


def _link_worker() -> None:
    """The daemon thread body: own loop, publish until it fails, then say so ONCE."""
    try:
        import aalink

        asyncio.run(_link_main(aalink))
    except Exception as e:  # a worker must never die silently (Defensive Code)
        state.link_available = False
        log_error("Ableton Link", str(e))


def start_link_thread() -> bool:
    """Start the Link worker; False when `aalink` is missing. Idempotent.

    The caller is the boot path, so a second call (a reload, a test) must not spawn a
    second Link session: the same thread keeps publishing.
    """
    global _link_thread
    if _link_thread is not None and _link_thread.is_alive():
        return state.link_available
    if not aalink_available():
        state.link_available = False
        return False
    _link_thread = threading.Thread(target=_link_worker, name=LINK_THREAD_NAME, daemon=True)
    _link_thread.start()
    # Give the worker a moment to build the Link before the caller reads availability.
    time.sleep(0.05)
    return state.link_available
