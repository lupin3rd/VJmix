"""Central mutable state for VJmix (REFACTOR_LATEST.md commit 3/13).

Every module-level mutable global lives here — the single home for shared
state. Access rule (see specs/REFACTOR_LATEST.md): import the MODULE and
write/read as ``state.NAME``. Scalar names must never be imported by name
(rebinds would shadow the module attribute and go stale); container names
may be imported by name since they are mutated in place (same object).

Worker modules (osc/audio/sequencer/midi) read this state and push UI
mutations through ``state.ui_task_queue`` — they never import dpg.
"""

import copy
import queue
import threading
from collections.abc import Callable, MutableMapping
from typing import Any

import numpy as np

from vjmixapp.constants import (
    BEAT_SOURCE_ANALYSIS,
    DEFAULT_MANUAL_BPM,
    DEFAULT_PALETTE,
    NUM_STEPS,
    NUM_TRACKS,
    SEQ_MAX_COLS,
    SEQ_MAX_ROWS,
    SEQ_ZOOM_DEFAULT,
    SHADER_KIND_DEFAULT,
    SPECTRUM_BARS,
)
from vjmixapp.textplay import DEFAULT_REVEAL_MODE

viosc_client: Any = None


local_osc_server: Any = None


local_server_thread: threading.Thread | None = None


is_server_running: bool = False


midi_enabled: bool = False


midi_learn_mode: bool = False


midi_learn_pending: tuple[str, dict[str, Any]] | None = None


midi_learn_started_at: float = 0.0  # e14: learn-session start, for the safety timeout


midi_learn_armed_tag: str | None = None  # learn marker armed by the last click (its M turns amber)


midi_selected_port: str | None = None  # e14s03: port whose bindings the Bindings section shows


midi_clock_source: str | None = None  # e14s04: MIDI clock input (None = first available)


# e76: hover help is a display preference (config `ui.hover_help`), not project content.
hover_help: bool = True


# e81: the Logs window's own view state — a LEVEL filter (None = all) and PAUSE, which
# freezes the VIEW without losing lines (the history keeps filling).
log_level_filter: str | None = None
log_paused: bool = False


# e77: the per-mapping token of the momentary button flash — a newer press supersedes the
# timer of an older one, so a stale release can never turn off a fresh press.
mapper_button_flash_token: dict[int, int] = {}


_theme_color_bindings: dict[Any, str] = {}


_text_color_bindings: dict[Any, str] = {}


_draw_color_bindings: dict[Any, tuple[str, str]] = {}


active_palette: dict[str, list[int]] = copy.deepcopy(DEFAULT_PALETTE)


theme_global: Any = None


ui_state_queue: queue.Queue[Any] = queue.Queue()


blob_queue: queue.Queue[Any] = queue.Queue()


# e41s03: the HTTP data-plane lane for thumbnails. Items are (source name,
# frame index); the fetch worker drains it and feeds blob_queue, so the decode
# worker and every texture consumer stay untouched. thumb_http_supported is the
# runtime lane probe (None = not yet proven, True = proven, False = given up);
# thumb_http_failures counts consecutive fetches with NO answer at all.
# dataplane_host/port are the machine-A HTTP endpoint, set with the OSC client.
thumb_fetch_queue: queue.Queue[Any] = queue.Queue()
thumb_http_supported: bool | None = None
thumb_http_failures: int = 0
dataplane_host: str = ""
dataplane_port: int = 0

# e58s03: the last time ANY viOSC state arrived (either lane — the OSC push or
# the /state poll), as a monotonic timestamp. Drives the settings connection LED.
last_viosc_state_ts: float = 0.0

# e58s03: the effective viOSC config last loaded into the Settings > viOSC page
# (the diff base for the next save). Empty until the page is loaded.
viosc_config_values: dict[str, Any] = {}

# e42s02: the pairing prompt is shown once per run (main loop), so a boot with
# no display (tests, headless import) never opens a modal.
pairing_prompt_shown: bool = False

# e43s02: the File Manager window state — machine A's Media Roots, the current
# directory page, the selection and a single-flight flag (one /fs request at a
# time; navigation is user-paced, not polled).
fs_roots: list[Any] = []
fs_current_path: str = ""
fs_entries: list[Any] = []
fs_total: int = 0
fs_selected: str | None = None
fs_status: str = ""
fs_busy: bool = False
# e43s03: the browser's thumbnail requests — a worker drains this queue and
# feeds the EXISTING blob/decode pipeline under the `fs:` key prefix.
fs_thumb_queue: queue.Queue[Any] = queue.Queue()
fs_thumb_requested: set[str] = set()

# e43s05: Session Drafts — the application-level library (NOT project content),
# the selected draft, and the debounced-save bookkeeping.
drafts_library: dict[str, Any] = {
    "format": "vjmix-drafts",
    "version": 1,
    "counter": 0,
    "drafts": [],
}
drafts_path: str = ""
drafts_selected: int | None = None
drafts_dirty: bool = False
drafts_dirty_at: float = 0.0
# e43s07: what each draft last produced on machine A (id -> (path, files)), the
# last status line and the path awaiting the Load confirmation.
drafts_written: dict[int, tuple[str, tuple[str, ...]]] = {}
drafts_status: str = ""
drafts_pending_path: str | None = None

# e44s03: the existing sessions listed from machine A (GET /fs/sessions), the
# picker's selected file and its status line.
fs_sessions: list[dict[str, Any]] = []
fs_sessions_selected: str = ""
fs_sessions_status: str = ""
fs_sessions_busy: bool = False
# e45s02: the Send-time reassignment — the panel's captured bindings while the
# modal is open, and the chosen assignments armed at confirm.
remap_bindings_cache: list[dict[str, Any]] = []
send_remap_pending: list[dict[str, Any]] | None = None
send_remap_armed_at: float = 0.0
# e45s01: the sources list the last write returned for each draft (the Send-time
# reassignment panel consumes it, e45s02).
drafts_sources: dict[int, list[dict[str, Any]]] = {}

# e41s04: the state pull lane. state_pull_supported is the runtime lane probe
# (None = not yet tried, True = proven, False = given up for the session); while
# it is True the OSC /viosc/replydata push is DROPPED so the state is never
# ingested twice. state_pull_failures counts consecutive unanswered pulls.
state_pull_supported: bool | None = None
state_pull_failures: int = 0


texture_queue: queue.Queue[Any] = queue.Queue()


# e38: source video preview transport (vjmixapp/preview.py) — the worker
# pushes decoded RGBA float32 frames as (source_name, frame) tuples here;
# the main loop drains them into the preview texture (worker never imports
# dpg). preview_active names the source shown right now (UI-owned);
# preview_error carries the last fatal message for the panel.
preview_frames: queue.Queue[Any] = queue.Queue()
preview_active: str | None = None
preview_playing: bool = False  # transport running (play) vs paused — UI-owned
preview_error: str | None = None


log_queue: queue.Queue[str] = queue.Queue()


ui_task_queue: queue.Queue[Callable[[], None]] = (
    queue.Queue()
)  # UI mutations from worker threads, drained on the main thread


_media_cell_cache: dict[str, str | float] = {}


global_vimix_state: dict[str, Any] = {"current_source": None, "sources": {}}


# e36s01: per-target full-component vectors for anchored OSC sends
# (target_id -> property -> [component values]). Written by full-vector sends;
# nil-capable properties never consult it. Fed by live vimix state in e36s06.
source_anchors: dict[str, dict[str, list[float]]] = {}


vjmix_selected_source: str | None = None


last_ui_signature: str = ""


last_num_cols: int = 4


osc_log_history: list[str] = []


current_step: int = -1


# e66s01: the LIVE geometry, beside the scalars the codebase already keeps. 8 is both
# the cap and the default, so a fresh grid is the cap and `sanitize_geometry` has one
# value to heal to. They are scalars, not a record, because nothing today iterates a
# list of sequencers: e67 pluralises them when it needs N of them.
seq_rows: int = SEQ_MAX_ROWS


seq_cols: int = SEQ_MAX_COLS


# e66s03: the CELL size of the grid (px), one of `SEQ_ZOOM_LEVELS`. App-level, not project
# content: opening a project must not resize the operator's cells, so it lives here and in
# the config file, and never in the project document.
seq_zoom: int = SEQ_ZOOM_DEFAULT


is_playing: bool = False


phase_nudge: float = 0.0


sync_event_seq = threading.Event()


sync_event_led = threading.Event()


beat_source: str = BEAT_SOURCE_ANALYSIS  # default: current behavior (essentia BPM)


sync_event_beat = threading.Event()  # fired once per beat in band/MIDI modes


midi_pulses: int = 0  # running MIDI clock pulse count (worker thread)


tap_times: list[float] = []  # TAP timestamps for the manual BPM mode


band_prev_values: dict[int, float] = {1: 0.0, 2: 0.0, 3: 0.0, 4: 0.0, 5: 0.0}  # rising edges


copied_step_data: dict[str, Any] | None = None  # step config copied for paste (e08)


active_step: tuple[int, int] | None = None  # last touched step (keyboard shortcuts target)


copied_step_pos: tuple[int, int, int] | None = None  # (instance, row, col) of the highlight


def _pristine_step() -> dict[str, Any]:
    """A pristine runtime step cell: persisted defaults + zeroed runtime keys.

    Shared by boot and the New-project reset (e15s01) so both produce the
    identical shape; the last_rand_* keys are runtime-only and exist solely in
    live cells.
    """
    return {
        "active": False,
        "type": "NONE",
        "v1": 0.0,
        "v2": 1.0,
        "frames": 4,
        "msgs": 1,
        "color": [1.0, 1.0, 1.0],
        "last_rand_v1": 0.0,
        "last_rand_seek": 0.0,
        "last_rand_color": [0, 0, 0],
    }


def _pristine_track() -> dict[str, Any]:
    """A pristine runtime track: no clip, inactive fade, NUM_STEPS blank cells.

    Shared by boot and the New-project reset (e15s01); the New-project reset
    replaces each row wholesale, so pending fades and runtime random state
    disappear with it.
    """
    return {
        "target_id": None,
        "base_address": "",
        "active_fade": {"active": False},
        "steps": [_pristine_step() for _ in range(NUM_STEPS)],
    }


tracks_data: list[dict[str, Any]] = [_pristine_track() for _ in range(NUM_TRACKS)]

# ==============================================================================
# e67s01: THE PLURAL RUNTIME — up to TWO sequencers, behind ONE uniform record.
#
# Instance 0 IS the sequencer the app has always had, and its storage stays the module globals
# below (`current_step`, `is_playing`, `beat_source`, `tracks_data`, `seq_rows`, `seq_cols`,
# `seq_zoom`, `phase_nudge`): `sequencer(0)` is a LIVE VIEW over them, not a copy, so there is
# exactly ONE home per value and nothing can diverge — the trap REFACTOR_LATEST warns about.
# Instance 1 (the second sequencer, B) is a plain record created on demand.
#
# Why a view and not a migration of the 242 sites that read those globals: the uniform record is
# what a second sequencer NEEDS (one tick, one builder and one MIDI resolver serve both), and a
# view delivers it with no rewrite and no window in which the runtime is half-migrated. The cost
# is asymmetry — A lives in the module, B in a dict — and it is stated here rather than hidden.
# ==============================================================================
SECOND_SEQUENCER_INDEX = 1
SEQUENCER_RECORD_KEYS: tuple[str, ...] = (
    "rows",
    "cols",
    "zoom",
    "step",
    "playing",
    "beat_source",
    "tracks",
    "nudge",
    "bpm",
)
# The globals that ARE instance 0's storage, one entry per record key.
_INSTANCE_A_BY_KEY: dict[str, str] = {
    "rows": "seq_rows",
    "cols": "seq_cols",
    "zoom": "seq_zoom",
    "step": "current_step",
    "playing": "is_playing",
    "beat_source": "beat_source",
    "tracks": "tracks_data",
    "nudge": "phase_nudge",
    # e67: A's MANUAL bpm has always lived in `current_bpm` (the manual widget and the analyser
    # share it because there was one sequencer). The record names it `bpm` so B can have its own,
    # and `_sequencer_interval` reads it only in MANUAL mode — which stops B on Analysis from
    # being driven by the number A typed.
    "bpm": "current_bpm",
}


class _InstanceAView(MutableMapping):
    """Instance 0's record as a LIVE view over the module globals (e67s01).

    Reads and writes go straight to the globals, so `sequencer(0)["step"]` and
    `state.current_step` are the same value in the same place. A `MutableMapping` because the
    callers that serve both instances use one shape: subscript reads and writes.
    """

    def __getitem__(self, key: str) -> Any:
        return globals()[_INSTANCE_A_BY_KEY[key]]

    def __setitem__(self, key: str, value: Any) -> None:
        globals()[_INSTANCE_A_BY_KEY[key]] = value

    def __delitem__(self, key: str) -> None:
        raise TypeError("a sequencer record cannot drop a key: the app reads all of them")

    def __iter__(self):
        return iter(SEQUENCER_RECORD_KEYS)

    def __len__(self) -> int:
        return len(SEQUENCER_RECORD_KEYS)


_instances: list[Any] = []  # built lazily so the view sees the globals, not a snapshot of them


def _new_second_sequencer() -> dict[str, Any]:
    """The record of B, a fresh instrument: the cap geometry, the default level, no playhead."""
    return {
        "rows": SEQ_MAX_ROWS,
        "cols": SEQ_MAX_COLS,
        "zoom": SEQ_ZOOM_DEFAULT,
        "step": -1,
        "playing": False,
        "beat_source": BEAT_SOURCE_ANALYSIS,
        "tracks": [_pristine_track() for _ in range(NUM_TRACKS)],
        "nudge": 0.0,
        "bpm": DEFAULT_MANUAL_BPM,
    }


def sequencer(index: int = 0):
    """The record of ONE sequencer, the same shape for both (e67s01).

    At most two exist: index 0 is the app's original sequencer (a live view over the module
    globals) and index 1 is the second one, created on first use. Anything else is REFUSED — the
    product offers two, and a caller that asks for a third has a bug worth hearing about.
    """
    if index < 0 or index > SECOND_SEQUENCER_INDEX:
        raise ValueError(
            f"sequencer index {index!r}: this app holds at most "
            f"{SECOND_SEQUENCER_INDEX + 1} sequencers (0 and 1)"
        )
    while len(_instances) <= index:
        _instances.append(_InstanceAView() if not _instances else _new_second_sequencer())
    return _instances[index]


def sequencer_count() -> int:
    """How many sequencers exist: 1 until B is asked for is not the same as 1 slot used.

    The record list is built lazily, so this reports what has been ASKED for, which is what the
    delete path and the menu icons need: A always exists (the app boots into it), B only after
    `sequencer(1)` or `build_sequencer(..., index=1)`.
    """
    return max(1, len(_instances))


def drop_second_sequencer() -> None:
    """Forget B entirely (the in-window delete, e67s02). A cannot be dropped: the app needs one."""
    del _instances[1:]
    forget_sequencer_created(1)


# e67s05: which slots hold a sequencer the operator MADE — a project's record applied, or the
# creation dialog's Create. A's record VIEW always exists, so slot 0 needs this separate bit:
# without it there is no way to tell "A has never been made" from "A is the app's default 8x8".
_created_slots: set[int] = set()


def mark_sequencer_created(index: int) -> None:
    """Record that a slot's sequencer was CREATED (e67s05): a project's record or the dialog."""
    _created_slots.add(index)


def forget_sequencer_created(index: int) -> None:
    """That slot is empty again (the delete, e67s05)."""
    _created_slots.discard(index)


def sequencer_is_created(index: int) -> bool:
    """Whether that slot's sequencer was MADE — without creating anything (e67s05)."""
    return index in _created_slots


def needs_creation(index: int) -> bool:
    """True while that slot has no sequencer to open, so the FIRST opening must ask (e67s05).

    On an empty start BOTH slots are empty: A is no longer built by the boot, exactly as B never
    was. A project that carries a record, or the dialog's Create, is what fills a slot.
    """
    return not sequencer_is_created(index)


def sequencer_exists(index: int) -> bool:
    """Whether a sequencer occupies that slot — WITHOUT creating it (e67s02).

    A always exists (the app boots into it). Asking about B must not bring B into existence, or
    the menu's create-or-open icons could no longer tell an empty slot from a full one: the
    question itself would fill the slot.
    """
    if index == 0:
        return True
    if index != SECOND_SEQUENCER_INDEX:
        raise ValueError(f"sequencer slot {index!r}: this app offers slots 0 and 1")
    return len(_instances) > index


_pending_delete: int | None = None


def request_sequencer_delete(index: int) -> int | None:
    """FIRST half of the in-window delete: remember WHICH sequencer, and change NOTHING.

    The operator's decision is that the delete asks for confirmation, so this is the asking: it
    arms a pending deletion and the caller draws the dialog. It returns the armed slot, or None
    when there is nothing legitimate to delete — an empty slot has nothing to remove.

    e68: slot 0 is deletable too. The operator deletes A to recreate it at another shape (the
    shape is chosen at CREATION and then stays), and e66 already made ZERO a legal state.
    """
    global _pending_delete
    if not sequencer_exists(index):
        _pending_delete = None
        return None
    _pending_delete = index
    return index


def confirm_sequencer_delete(index: int) -> bool:
    """SECOND half: delete ONLY the armed slot, and only if it is still the armed one.

    The index is checked against the pending one, so a stale dialog (the operator opened the
    confirmation on B, went away, and the confirmation outlived its subject) cannot delete the
    wrong sequencer. A confirmation that arrives without a request does nothing at all: that is
    what makes the confirmation real rather than decorative.

    e68: deleting A empties its slots in place (its record IS the live view over the globals)
    and marks it uncreated, so the A icon asks for a new shape. Deleting B drops its record.
    """
    global _pending_delete
    if _pending_delete != index:
        return False
    _pending_delete = None
    if index == 0:
        forget_sequencer_created(0)
        for row in range(NUM_TRACKS):
            tracks_data[row] = _pristine_track()
        globals()["current_step"] = -1
        globals()["is_playing"] = False
    else:
        drop_second_sequencer()
    return True


def cancel_sequencer_delete() -> None:
    """The operator said no: forget the request and change nothing (e67s02)."""
    global _pending_delete
    _pending_delete = None


def pending_delete_slot() -> int | None:
    """Which slot is waiting for confirmation, or None (e67s02) — what the dialog reads."""
    return _pending_delete


samplerate = 44100


is_audio_analyzing: bool = False


is_beat_tracking: bool = False


lowpass_enabled: bool = True  # mirrors the "Use Low-Pass Filter" checkbox (read on worker threads)


audio_buffer: np.ndarray = np.zeros(
    samplerate * 6, dtype=np.float32
)  # preallocated ring buffer (L-2)


audio_buffer_head: int = 0  # next write position in audio_buffer (modulo its length)


current_bpm: float = DEFAULT_MANUAL_BPM


bpm_last_detected: float = 0.0


# e75: the Ableton Link session (written by the link worker thread, read everywhere).
# `link_available` is False until the worker builds its Link (and on any failure), so the
# UI degrades instead of pretending to follow a session that is not there.
link_available: bool = False
link_tempo: float = 120.0
link_beat: float = 0.0
link_phase: float = 0.0
link_peers: int = 0


beat_confidence: float = 0.0


spectrum_bars_cache: np.ndarray = np.zeros(SPECTRUM_BARS, dtype=np.float32)


spec_peak_hold: float = 0.0  # AGC running spectral peak (spectrum worker only, e10s09)


bands_enabled: dict[int, bool] = {1: False, 2: False, 3: False, 4: False, 5: False}


band1: float = 0.0


band2: float = 0.0


band3: float = 0.0


band4: float = 0.0


band5: float = 0.0


thumbnails_data: dict[str, list[str]] = {}


request_timestamps: dict[str, float] = {}


thumb_cycle_state: dict[str, tuple[int, float]] = {}


thumb_fail_count: dict[str, int] = {}


# e41s02: len(thumbnails_data[target]) observed when the last thumbnail request
# went out. The next index is asked only when that number GREW, so a source with
# fewer frames than the budget (an image) stops being polled instead of being
# asked for a non-existent index forever.
thumb_frames_at_last_request: dict[str, int] = {}


# e81: one I/O Monitor IGNORED row per (port, raw mido type) — tells "the app ignores
# this message type" apart from "the device sends nothing" without a Logs line.
_midi_ignored_types: set[tuple[str, str]] = set()  # (port, raw type) pairs


midi_controllers: list[dict[str, Any]] = []

# e52s01: MIDI modes — the additive active set (never persisted) and the
# registry of definitions (name + optional LED spec; the project persists these).
midi_modes: set[str] = set()
midi_mode_defs: list[dict[str, Any]] = []

# e52s08: the activation order (oldest first) of the ACTIVE modes; the set above
# stays the source of truth, this only answers "which was activated last".
midi_mode_order: list[str] = []

# e52s04: per-control rotation cursor — key -> (last CC value, residual). Owned
# by the single MIDI worker thread; cleared on mode activation and MIDI disable.
midi_step_last: dict[str, tuple[int, int]] = {}

# e54s01: per-control step-rate budget (token bucket) — key -> (last_at, tokens).
# Owned by the single MIDI worker thread; cleared with the rotation cursors.
midi_step_budget: dict[str, tuple[float, float]] = {}

# e53s02: per-LED flash generation. A `press` flash schedules its off; a `state`
# write (or a newer flash) bumps the token, so a stale timer cannot turn off an
# LED a state LED now owns. Key = "kind|channel|number". Main thread only.
midi_led_flash_token: dict[str, int] = {}


_controller_lock = threading.Lock()


_controller_profiles: dict[str, dict[str, Any]] = {}


# e26: Leap Motion engine state (worker-owned). leap_values is mutated IN
# PLACE (clear + update under leap_lock) so facade re-exports stay live; the
# worker writes it from its own thread, the UI reads copies on the main thread.
leap_enabled: bool = False


leap_status: str = "missing"  # missing | disconnected | connected | tracking


leap_values: dict[str, float] = {}


# e48: tracking frame rate (Hz) of the last TrackingEvent (worker-owned). It is a
# per-frame diagnostic rendered by the Leap window, not a per-hand signal.
leap_framerate: float = 0.0


# BUG-2026-09-18T212400: worker liveness + restart generation. leap_worker_tick is
# stamped by the worker loop on every pass (a dead or blocked worker stops
# ticking, which is the only way to see it); leap_generation is bumped by
# restart_leap_engine() and watched by the worker, so an explicit restart always
# rebuilds the connection.
leap_worker_tick: float = 0.0
leap_generation: int = 0


leap_lock = threading.Lock()


# e26s04: visualizer toggle mirror (main-thread flag; the worker watches it to
# manage the LeapC Images policy) + the poll-thread visualizer snapshot. The
# snapshot is written only on the library poll thread under leap_lock; the main
# thread swaps a reference (microseconds), never a deep copy of the arrays.
leap_visualizer: bool = False
leap_viz_ir: np.ndarray | None = None  # latest grayscale IR copy (240, 640)
leap_viz_hands: list[dict[str, Any]] | None = None  # latest hand-geometry dicts
leap_viz_frame: np.ndarray | None = None  # latest RGBA float32 composite (h, w, 4)
leap_viz_seq: int = 0  # incremented on every composite publish
leap_viz_last_render: float = 0.0  # poll-thread rate-gate timestamp
leap_viz_uploaded_seq: int = 0  # main-thread only: last seq uploaded to the texture
leap_viz_tex_created: bool = False  # main-thread only: raw texture built once


# e26s05: stall watchdog state (worker-owned, no new lock — same practice as
# leap_status). leap_last_frame is the epoch of the last tracking event (0 =
# never); leap_stall_count counts consecutive watchdog-forced reconnects.
leap_last_frame: float = 0.0
leap_stall_count: int = 0


# e26s02: leap window tag -> last rendered text (main-thread only, avoids
# re-writing unchanged monitor cells / the status line on every main tick).
leap_monitor_cache: dict[str, str] = {}


# e26s03: per-mapping drive bookkeeping (mapping id -> {last_raw, last_push}).
# Written by the leap worker listener thread when it pushes a mapped value.
leap_drive_state: dict[int, dict[str, Any]] = {}


# e16: Mapper state — OSC property mappings (see vjmixapp/mapper.py).
# Each entry: {id, target_id, property, control, value}; ids come from the
# monotonic counter (like the other UI element counters).
mapper_mappings: list[dict[str, Any]] = []


mapper_counter: int = 0


# e51s02: the Mapper clipboard — a captured Mapping snapshot (MAPPER_PERSISTED_KEYS
# minus the id) awaiting a Paste, mirroring `copied_step_data` for the sequencer.
mapper_clipboard: dict[str, Any] | None = None
# e74s11: when the clipboard was ARMED (a monotonic stamp set by copy/cut). The Paste
# buttons derive from `mapper_clipboard`; the tick expires it so they do not ride forever.
mapper_clipboard_at: float = 0.0


# e35s02: active cue runs — written by the cue engine (vjmixapp/cue.py) from
# the scheduler thread, read by the UI for running indicators (e35s03). Each
# entry: {mapping_id, target_id, plan, cursor} with plan entries of the shape
# (time_ms, action, payload) built by cue.build_cue_plan. Main thread only
# mutates through the queues; the engine mutates this list directly (it is
# dpg-free by construction).
cue_runs: list[dict[str, Any]] = []


# e35s05: which mapping's cue editor is open (main-thread only; None = closed).
# The window shows the mapping context, so a removed mapping must close it.
cue_editor_mapping_id: int | None = None


# e35s03: main-thread cache of the last relabel per cue-list card trigger
# (mapping id -> label). Written ONLY by tick_cue_triggers on the main thread;
# cleared by refresh_mapper_ui after a body rebuild. Worker threads never touch
# it (HIGH-1) — the engine reflects running state through cue_runs alone.
cue_trigger_label_cache: dict[int, str] = {}


# e35 UAT: last rendered progress text per cue-list card ('3 of 10'); written
# only by tick_cue_triggers on the main thread. The engine never touches it.
cue_progress_cache: dict[int, str] = {}


# e35 UAT: TWO shared button/trigger themes (OFF then ON) bound by tag. They are
# root-level theme items created once and rebuilt ONLY when the active palette
# changes — per-trigger theme churn caused DPG alias collisions (1000).
trigger_theme_tags: list[str | None] = [None, None]  # [0]=off, [1]=on
trigger_theme_signature: tuple[tuple[int, ...], ...] | None = None


# e17 / BUG-2026-09-01T194500: last focused workspace window. DPG's
# get_active_window() returns None while the viewport menu bar has focus, so
# the Windows-menu mark and the Ctrl+Tab anchor come from this tracking instead.
current_window: str | None = None


# e59: the Text window's live document, its OSC target and the last loaded file.
# Main-thread only (the editor callback writes the document); the project save/
# load flows in the composition root persist the three with the project. An
# empty target means "no source chosen yet".
text_document: str = ""
text_target: str = ""
text_source_path: str = ""
# e61: the Shader window's live document, its OSC target, the DECLARED kind of
# that target (effect | generator — the OSC state feed exposes no source type),
# the asset file the deploy sends the path of (D4': never inline), and the
# client-side uniform registry (vimix reports neither the code nor its uniform
# values back, so the registry is authoritative only for what we sent). The
# project save/load flows in the composition root persist all five; an empty
# target means "no source chosen yet".
shader_document: str = ""
shader_target: str = ""
shader_kind: str = SHADER_KIND_DEFAULT
# e65s06: the family the picker is narrowed to (the TOKEN a `// family:` line declares,
# `""` for no filter). A view preference, remembered with the kind because the shader
# section is what remembers the client-side state vimix cannot report back.
shader_family: str = ""
shader_path: str = ""
shader_uniforms: dict[str, dict[str, dict[str, float | None]]] = {}
# e61s04: the effect's bypass, client-side only — vimix reports no filter state,
# so this is what VJmix believes it set (and what the button shows).
shader_bypass: bool = False
# e59: the tracked caret (a shadow position — DearPyGui exposes none; see the
# Text window's infer_edit_caret). Runtime only, never persisted.
text_caret: int = 0
# e59s05: the LIVE ImGui input state captured through the private-ABI reader:
# the selected (lo, hi) range (None when the caret only) and the widget id that
# owns the single ImGui state slot (None until a read succeeds). Runtime only.
text_selection: tuple[int, int] | None = None
text_widget_id: int | None = None
# e59s08: the progressive-reveal cursor for the four send modes. Runtime only
# (never persisted): the selected mode and the index of the last sent step.
text_reveal_mode: str = DEFAULT_REVEAL_MODE
text_reveal_step: int = 0


# e37 (project-save-as-titlebar): the session's project identity — which .VJmix
# document the live content belongs to and whether the next Save would write
# something different. Main-thread only: the file flows and the title sync run
# on the main thread; worker modules never touch these fields.
current_project_path: str | None = None  # None = unnamed (new) project
project_dirty: bool = False  # live content differs from the last-saved baseline
saved_content_fingerprint: str = ""  # canonical JSON of the content at the last save/open/new


# e40s01: the Mapping engine's runtime memory — per-Mapping real-value bookkeeping for
# dead-reckoning (emission.mapping_raw_value) and the last emitted Destination
# value (the epsilon dedupe). Main-thread only; never persisted.
mapping_book: dict[int, dict[str, Any]] = {}
mapping_values: dict[int, float] = {}
# e40s01: the /viosc/monitor subscriptions the live mappings currently hold, so the
# tick only re-issues them when the desired set changes.
mapping_subscriptions: dict[str, list[str]] = {}
# e40s02: Mappings the orphan policy disabled (their source is gone); they are
# re-enabled automatically when the source comes back.
mapping_orphans: set[int] = set()


# BUG-2026-10-14T180544: Mapping ids whose `uniform:<slot>` has no live row on their
# own target (so the send fails soft and the log line is emitted ONCE, not every frame).
mapping_unresolved_uniforms: set[int] = set()
# BUG-2026-09-13T231500: every source NAME the state table has ever reported.
# A Mapping's target absent from a state update is only evidence of removal if
# the name was seen before — the first tables after boot/pairing can be empty or
# still carry another session, and pruning against them deleted user Mappings.
known_sources: set[str] = set()
# e40s06: the targeted watch lane — the /viosc/reply deltas land on this queue
# from the OSC server thread and are applied on the main thread; the plan last
# sent to viOSC and whether the lane is proven alive (None = unknown, still
# using the 2 s monitor fallback).
watch_state_queue: queue.Queue[tuple[str, list[Any]]] = queue.Queue()

# e82s04: the delta stream. The worker parses SSE frames and puts the event dicts
# here; the MAIN thread applies them to the table (worker modules never touch dpg).
event_queue: queue.Queue[dict[str, Any]] = queue.Queue()
# None = not probed yet, True = live, False = this daemon has no /events.
event_stream_supported: bool | None = None
# The last revision this app has applied (snapshot or event); it is the ETag of
# the snapshot and the gap detector of the stream.
event_rev: int = 0
# e83: the measured footprint of one Mediagrid cell (tile + cell padding), learned
# from the built table: the column count must follow the REAL width, or a column is
# dropped while there is still room (the scrollbar appearing too early).
media_cell_w: float = 0.0
# e82s09: the current source the grid was last PAINTED for. A current change only
# recolors a tile, so it must not enter the structural signature (that rebuilt the
# whole grid — the glitch the stream made visible).
last_current_source: Any = None
# e82s05: POST /interest lane. None = not probed, True = the daemon accepts it,
# False = an older daemon (fall back to /viosc/watch).
interest_supported: bool | None = None
# e82s05: the properties some consumer has asked for, so the raw table can render
# "never asked" differently from "asked, no value".
asked_props: set[str] = set()
mapping_watch_plan: dict[str, dict[str, Any]] = {}
osc_watch_supported: bool | None = None
