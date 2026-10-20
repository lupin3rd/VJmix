"""Queue plumbing for VJmix (REFACTOR_LATEST.md commit 3/13).

The queue OBJECTS live in ``state``; these helpers are the only writers of
``state.ui_task_queue`` / ``state.log_queue``. Worker threads call ``ui_task``
to push UI mutations to the main thread (HIGH-1: no direct dpg calls) and
``append_log``/``log_error`` for the Logs window.
"""

import time
from collections.abc import Callable
from typing import Any

from vjmixapp import state


def ui_task(fn: Callable[[], None]) -> None:
    """Run a UI mutation on the main thread via the task queue."""
    state.ui_task_queue.put(fn)


# e81: the Logs window answers "what did the APP do, and what failed?" — never "what
# crossed the wire". OSC and MIDI traffic lives in the I/O Monitor, which records every
# send and receive with its resolution outcome (vjmixapp/iomonitor.py). A line pushed here
# carries a LEVEL so the window can filter; the text stays one copyable block.
LOG_LEVEL_INFO = "INFO"
LOG_LEVEL_WARN = "WARN"
LOG_LEVEL_ERROR = "ERROR"
LOG_LEVELS: tuple[str, ...] = (LOG_LEVEL_INFO, LOG_LEVEL_WARN, LOG_LEVEL_ERROR)


def log_event(level: str, context: str, message: str) -> None:
    """Push ONE application event to the Logs window (never traffic)."""
    t = time.strftime("%H:%M:%S")
    state.log_queue.put(f"[{t}] {level} {context}: {message}")


def log_error(context: str, message: str) -> None:
    """An error the operator must know about (a failure, not a trace)."""
    log_event(LOG_LEVEL_ERROR, context, message)


def log_warn(context: str, message: str) -> None:
    """Something looked wrong but the app carried on (stale binding, skipped send)."""
    log_event(LOG_LEVEL_WARN, context, message)


def append_log(context: str, message: str) -> None:
    """An informational application event (boot, link, mode, decision)."""
    log_event(LOG_LEVEL_INFO, context, message)


def enqueue_set_value(tag: str, value: Any) -> None:
    """Queue a dpg.set_value(tag, value) for the main thread, if the item exists.

    The toolkit is imported INSIDE the queued callable, not at module level: this
    module is shared by the worker threads (`osc`, `audio`, `sequencer`), so a
    module-level import loaded dearpygui into every worker's import chain and
    silently defeated the HIGH-1 source guard (BUG-2026-10-08T233000). The call
    itself still happens on the main thread, which is where dpg belongs.
    """

    def _set() -> None:
        import dearpygui.dearpygui as dpg

        if dpg.does_item_exist(tag):
            dpg.set_value(tag, value)

    ui_task(_set)
