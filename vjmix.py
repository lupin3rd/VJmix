import contextlib
import copy
import json
import os
import queue
import random  # noqa: F401 — module attribute (test harness patches vjmix.random)
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any

import dearpygui.dearpygui as dpg
import essentia
import numpy as np
import sounddevice as sd
from PIL import Image
from pythonosc import dispatcher, udp_client

import vjmixapp  # noqa: F401  scaffold hook (REFACTOR_LATEST.md commit 1): proves the package import path works at boot
from vjmixapp import (
    actions,
    caret,
    catalog,
    cue,
    dataplane,
    drafts,
    emission,
    fsclient,
    iomonitor,
    leap,
    mapper,
    osc,
    pairing,
    preview,
    seqlayout,
    shadercode,
    sourcekind,
    sourcestatus,
    state,
    textmarkup,
    textplay,
    viosccfg,
)
from vjmixapp import (
    help as helpprose,
)
from vjmixapp import (
    link as linkengine,  # e75: the Ableton Link engine (worker thread + pure interval)
)
from vjmixapp import (
    stream as streamlane,  # e82s04: the delta stream (SSE worker + pure helpers)
)
from vjmixapp.actions import STEP_ACTIONS
from vjmixapp.audio import (
    _set_band_variable,
    apply_spectrum_agc,
    audio_callback,
    band_rect_contains,
    band_rect_drag,
    band_rect_edge_segment,
    band_rect_hit_test,
    band_rect_local_pointer,
    band_rect_px,
    band_value_from_bars,
    compute_spectrum_bars,
    get_audio_snapshot,
    lowpass_filter,
    pulse_client_properties,
    rhythm_extractor,
)
from vjmixapp.config import (
    _sanitize_palette,
    load_config,
    sanitize_geometry,
    sanitize_seq_zoom,
    save_config,
    user_config_dir,
)
from vjmixapp.constants import (
    BAND_BEAT_THRESHOLD,
    BAND_EDGE_HIGHLIGHT_THICKNESS,
    BAND_SOURCES,
    BEAT_SOURCE_ANALYSIS,
    BEAT_SOURCE_BAND1,
    BEAT_SOURCE_LABELS,
    BEAT_SOURCE_LINK,
    BEAT_SOURCE_MANUAL,
    BEAT_SOURCE_MIDI,
    CLOCK_DEFAULT,
    CLOCK_SOURCES,
    DEFAULT_MANUAL_BPM,
    DEFAULT_PALETTE,
    DEST_MIDI,
    DEST_OSC,
    DESTINATIONS,
    DRAFTS_SAVE_DEBOUNCE_S,
    FRAME_SLEEP_ANIMATED,
    FRAME_SLEEP_IDLE,
    FS_THUMB_H,
    FS_THUMB_MAX_REQUESTS,
    FS_THUMB_PREFIX,
    FS_THUMB_W,
    HELP_BODY_TAG_SUFFIX,
    HELP_CARD_BG_SLOT,
    HELP_CARD_BORDER,
    HELP_CARD_BORDER_SLOT,
    HELP_CARD_GAP_X,
    HELP_CARD_GAP_Y,
    HELP_CARD_PAD_X,
    HELP_CARD_PAD_Y,
    HELP_HOVER_DELAY_S,
    HELP_LOGO_HEIGHT,
    HELP_LOGO_WIDTH,
    HELP_OPTION_COLUMN,
    HELP_TIP_TAG_SUFFIX,
    HELP_WINDOW_HEIGHT,
    HELP_WINDOW_WIDTH,
    HELP_WRAP_WIDTH,
    IO_MONITOR_DIRECTION_IN,
    IO_MONITOR_DIRECTION_OUT,
    IO_MONITOR_KIND_INTEREST,
    IO_MONITOR_KIND_SHADER,
    IO_MONITOR_OUTCOME_IGNORED,
    IO_MONITOR_OUTCOME_LEARN,
    IO_MONITOR_OUTCOME_MATCH,
    IO_MONITOR_OUTCOME_MUTED,
    IO_MONITOR_OUTCOME_NOBIND,
    IO_MONITOR_OUTCOME_NOMATCH,
    IO_MONITOR_OUTCOME_RECV,
    IO_MONITOR_OUTCOME_SENT,
    IO_MONITOR_REFRESH_INTERVAL,
    IO_MONITOR_TRANSPORT_HTTP,
    IO_MONITOR_TRANSPORT_MIDI,
    IO_MONITOR_TRANSPORT_OSC,
    LAYOUT_WINDOW_TAGS,
    LOG_HISTORY_LIMIT,
    MAP_ACTIONS_ROWS_TAG,
    MAP_ACTIONS_WINDOW_TAG,
    MAPPER_ADD_H,
    MAPPER_ADD_SLOT_W,
    MAPPER_ADD_W,
    MAPPER_BAND_DRAG_W,
    MAPPER_CB_W,
    MAPPER_CLIPBOARD_TTL_SECONDS,
    MAPPER_CTRL_H,
    MAPPER_DRAG_W,
    MAPPER_FILTER_ADD_GAP,
    MAPPER_INPUT_ALT_TOOLTIP,
    MAPPER_KIND_FONT_SIZE,
    MAPPER_KNOB_H,
    MAPPER_LEARN_SLOTS,
    MAPPER_LINE_NO_DIGIT_PX,
    MAPPER_LINE_NO_FONT_SIZE,
    MAPPER_LINE_NO_TEXT_H,
    MAPPER_LINE_NO_W,
    MAPPER_MARKER_H,
    MAPPER_MARKER_W,
    MAPPER_MAX_MAPPINGS,
    MAPPER_MINI_W,
    MAPPER_MOMENTARY_FLASH_S,
    MAPPER_PASTE_SLOT_W,
    MAPPER_PASTE_W,
    MAPPER_RESET_H,
    MAPPER_RESET_W,
    MAPPER_ROW_GAP,
    MAPPER_ROW_PAD_V,
    MAPPER_ROW_THUMB_H,
    MAPPER_ROW_THUMB_W,
    MAPPER_SCROLL_HEIGHT,
    MAPPER_SMALL_CHAR_PX,
    MAPPER_STATE_BOX_HEADER_H,
    MAPPER_STATE_BOX_ROW_H,
    MAPPER_TEXT_H,
    MAPPER_WINDOW_HEIGHT,
    MAPPER_WINDOW_WIDTH,
    MAPPER_X_H,
    MAPPER_X_W,
    MAPPING_CONST_VALUE_DEFAULT,
    MAPPING_CONST_VALUE_MAX,
    MAPPING_CONST_VALUE_MIN,
    MAPPING_DEFAULT_CADENCE_MS,
    MAPPING_DIRECTIONS,
    MAPPING_MIN_CADENCE_MS,
    MAPPING_OSC_DEFAULT_ADDRESS,
    MAPPING_OSC_DEFAULT_HOST,
    MAPPING_OSC_DEFAULT_PORT,
    MAPPING_STEPS_CONTINUOUS,
    MAPPING_TICK_INTERVAL_S,
    MARKER_GROUP_GAP,
    MEDIA_ALPHA_PARKED,
    MEDIA_ALPHA_SLIDER_H,
    MEDIA_ALPHA_SLIDER_W,
    MEDIA_ALPHA_STOP_H,
    MEDIA_BADGE_H,
    MEDIA_BADGE_W,
    MEDIA_GRID_MARGIN,
    MEDIA_TILE_H,
    MEDIA_TILE_NAME_CHARS,
    MEDIA_TILE_PAD,
    MEDIA_TILE_W_ESTIMATE,
    MEDIA_TITLE_CHAR_PX,
    MEDIA_TITLE_CHARS_PER_LINE,  # e83: the monospace char width of the tile font
    MEDIA_TITLE_ELLIPSIS,
    MEDIA_TITLE_FONT_SIZE,
    MEDIA_TITLE_GAP,
    MEDIA_TITLE_MAX_LINES,
    MEDIA_TITLE_WRAP,
    MIDI_ACTION_BEAT_SOURCE,
    MIDI_ACTION_DRAFT_LOAD,
    MIDI_ACTION_DRAFT_NEXT,
    MIDI_ACTION_DRAFT_PREV,
    MIDI_ACTION_DRAFT_SAVE,
    MIDI_ACTION_DRAFT_STEP,
    MIDI_ACTION_ENABLE_CORRECTION,
    MIDI_ACTION_FILE_MANAGER_TOGGLE,
    MIDI_ACTION_FILE_NEXT,
    MIDI_ACTION_FILE_PREV,
    MIDI_ACTION_FILE_STEP,
    MIDI_ACTION_IO_MONITOR_TOGGLE,
    MIDI_ACTION_MAPPER_BAND,
    MIDI_ACTION_MAPPER_CUE_OPEN,
    MIDI_ACTION_MAPPER_ENABLE,
    MIDI_ACTION_MAPPER_LINE,
    MIDI_ACTION_MAPPER_MAPPING,
    MIDI_ACTION_MAPPER_RESET,
    MIDI_ACTION_MAPPING_ADD,
    MIDI_ACTION_MAPPING_COPY,
    MIDI_ACTION_MAPPING_CUT,
    MIDI_ACTION_MAPPING_MOVE,
    MIDI_ACTION_MAPPING_PASTE,
    MIDI_ACTION_MAPPING_TOGGLE,
    MIDI_ACTION_MODE_TOGGLE,
    MIDI_ACTION_MODES_CLEAR,
    MIDI_ACTION_NUDGE_BACK,
    MIDI_ACTION_NUDGE_FORWARD,
    MIDI_ACTION_PAIRING_PROMPT,
    MIDI_ACTION_PROJECT_NEW,
    MIDI_ACTION_PROJECT_OPEN,
    MIDI_ACTION_PROJECT_SAVE,
    MIDI_ACTION_REGEN_SELECTED,
    MIDI_ACTION_SEQ_ROW_ASSIGN,
    MIDI_ACTION_SEQ_ROW_DISABLE,
    MIDI_ACTION_SEQ_ROW_ENABLE,
    MIDI_ACTION_SEQ_TOGGLE,
    MIDI_ACTION_SET_BLENDING,
    MIDI_ACTION_SET_CURRENT,
    MIDI_ACTION_SHADER_BYPASS,
    MIDI_ACTION_SHADER_LOAD,
    MIDI_ACTION_SHADER_SAVE,
    MIDI_ACTION_SHADER_SEND,
    MIDI_ACTION_SHADER_WINDOW_TOGGLE,
    MIDI_ACTION_SHOW_WINDOW,
    MIDI_ACTION_SOURCE_NEXT,
    MIDI_ACTION_SOURCE_PREV,
    MIDI_ACTION_SOURCE_STEP,
    MIDI_ACTION_SOURCES_DATA_REFRESH,
    MIDI_ACTION_TEXT_CLEAR,
    MIDI_ACTION_TEXT_LINE,
    MIDI_ACTION_TEXT_LINE_PLUS,
    MIDI_ACTION_TEXT_SEND,
    MIDI_ACTION_TEXT_WINDOW_TOGGLE,
    MIDI_ACTION_TEXT_WORD,
    MIDI_ACTION_TEXT_WORD_PLUS,
    MIDI_ACTION_TRACK_ASSIGN,
    MIDI_ACTION_TRANSPORT_PLAY,
    MIDI_ACTION_TRANSPORT_RESYNC,
    MIDI_ACTION_TRANSPORT_TAP,
    MIDI_CC_TRIGGER_THRESHOLD,
    MIDI_CLOCK_PULSES_PER_BEAT,
    MIDI_KIND_CC,
    MIDI_KIND_NOTE,
    MIDI_LEARN_RED_RGBA,
    MIDI_LEARN_TIMEOUT_SECONDS,
    MIDI_LED_BEHAVIOR_PRESS,
    MIDI_LED_BEHAVIOR_STATE,
    MIDI_MODE_LED_KINDS,
    MIDI_MODE_LED_OFF_DEFAULT,
    MIDI_MODE_LED_ON_DEFAULT,
    MIDI_OPEN_RETRY_COOLDOWN_SECONDS,
    MIDI_PORT_RESCAN_SECONDS,
    NON_THUMB_LABEL_CHARS,
    NUM_STEPS,
    NUM_TRACKS,
    ORIGIN_CLOCK,
    ORIGIN_CONST,
    ORIGIN_CONTROL,
    ORIGIN_STATE,
    PREVIEW_PORT,
    PREVIEW_SPEED_DEFAULT,
    PREVIEW_SPEED_MAX,
    PREVIEW_SPEED_MIN,
    PREVIEW_SPEED_STEP,
    PROJECT_FILE_EXTENSION,
    PROJECT_FORMAT,
    PROJECT_VERSION,
    PROJECT_VERSIONS_READABLE,
    RAW_FLASH_SECONDS,  # e82s08: how long a changed raw cell stays bright
    RECENT_PROJECTS_MAX,
    SEQ_BEAT_BOX_HEIGHT,
    SEQ_BEAT_BOX_PAD_Y,
    SEQ_BEAT_BOX_WIDTHS,
    SEQ_BEAT_LED_H,
    SEQ_BEAT_LED_W,
    SEQ_BEAT_TAP_HEIGHT,
    SEQ_GEOMETRY_CHOICES,
    SEQ_GRID_TABLE_ROW_PAD,
    SEQ_MAX_COLS,
    SEQ_MAX_ROWS,
    SEQ_MAX_SEQUENCERS,
    SEQ_NUDGE_STEP,
    SEQ_TAG_PREFIX,
    SEQ_ZOOM_DEFAULT,
    SEQ_ZOOM_LABELS,
    SEQ_ZOOM_LEVELS,
    SEQUENCER_TICK_POLL_SECONDS,
    # e61: the shader deployment constants (the `shader` project section and the
    # declared target kind).
    SHADER_ASSET_EXTENSION,
    SHADER_BYPASS_BUTTON_TAG,
    SHADER_EDITOR_HEIGHT,
    SHADER_EDITOR_TAG,
    SHADER_FAMILY_ANY,
    SHADER_FAMILY_COMBO_TAG,
    SHADER_KIND_COMBO_TAG,
    SHADER_KIND_DEFAULT,
    SHADER_KIND_GENERATOR,
    SHADER_KINDS,
    SHADER_LEARN_SLOT_TAG,
    SHADER_LIBRARY_INFO_TAG,
    SHADER_LOAD_DIALOG_TAG,
    SHADER_MAPPABLE_UNIFORM_SLOTS,
    SHADER_MAX_LOAD_BYTES,
    SHADER_MAX_SKIPS_NAMED,
    SHADER_SAVE_DIALOG_TAG,
    SHADER_SEND_BUTTON_TAG,
    SHADER_STATUS_TAG,
    SHADER_TARGET_COMBO_TAG,
    SHADER_TEMPLATE_COMBO_TAG,
    SHADER_UNIFORM_PANEL_HEIGHT,
    SHADER_UNIFORM_ROWS_TAG,
    SHADER_UNIFORM_SCAN_BUTTON_TAG,
    SHADER_UNIFORM_SLIDER_W,
    SHADER_VALIDATE_TAG,
    SHADER_WINDOW_HEIGHT,
    SHADER_WINDOW_PADDING,
    SHADER_WINDOW_TAG,
    SHADER_WINDOW_WIDTH,
    SOURCES_DATA_BUTTON_TAG,
    SOURCES_DATA_GROUP_TAG,
    SOURCES_DATA_LEARN_SLOT,
    SOURCES_DATA_REFRESH_TAG,
    SOURCES_DATA_STATUS_TAG,
    SOURCES_DATA_WINDOW_HEIGHT,
    SOURCES_DATA_WINDOW_TAG,
    SOURCES_DATA_WINDOW_WIDTH,
    SOURCES_TOOLBAR_NEXT_TAG,
    SOURCES_TOOLBAR_PREV_TAG,
    SOURCES_TOOLBAR_SET_TAG,
    SOURCES_TOOLBAR_TAG,
    SPEC_DRAWLIST_H,
    SPEC_DRAWLIST_W,
    SPECTRUM_BARS,
    SPECTRUM_FPS,
    SPECTRUM_MOUSE_REG,
    STATE_TIER_PROPS,  # e82s05: what the mirror keeps synchronised at 1 s
    STEP_PERSISTED_KEYS,
    STREAM_UI_REFRESH_MIN_S,  # e82s04: the stream's render ceiling
    TAP_MAX_TAPS,
    TAP_STALE_SECONDS,
    TEXT_COLOR_EDIT_WIDTH,
    TEXT_EDITOR_HEIGHT,
    TEXT_EDITOR_TAG,
    TEXT_LEARN_SLOT_TAG,
    TEXT_LIVE_VALIDATE_MAX_CHARS,
    TEXT_LOAD_DIALOG_TAG,
    TEXT_MAX_LOAD_BYTES,
    TEXT_MODE_LEARN_SLOT_TAG,
    TEXT_SAVE_DIALOG_TAG,
    TEXT_SOURCE_COMBO_TAG,
    TEXT_SOURCE_INDEX_PREFIX,
    TEXT_STATUS_TAG,
    TEXT_WINDOW_HEIGHT,
    TEXT_WINDOW_TAG,
    TEXT_WINDOW_WIDTH,
    TEXT_WRAP_CLIPBOARD_TAG,
    TEXT_WRAP_ROW_TAG,
    THEME_PRESET_LABELS,
    THEME_PRIMARY_LABELS,
    THEME_PRIMARY_SLOTS,
    THUMB_CYCLE_INTERVAL,
    THUMB_FAIL_LABEL,
    THUMB_FAIL_THRESHOLD,
    THUMB_REQUEST_INTERVAL,
    TILE_BLEND_BADGE_GAP,
    TILE_BLEND_BADGE_SIZE,
    TILE_BLEND_ICON_INSET,
    TILE_SEEK_BAR_H,
    TILE_STATUS_BADGES,
    TILE_STATUS_GAP,
    TILE_STATUS_TICK_S,
    TRANSPORT_BLOCK_GAP,
    TRANSPORT_BUTTON_H,
    TRANSPORT_NUDGE_W,
    TRANSPORT_PLAY_W,
    TRANSPORT_RESYNC_W,
    TRANSPORT_ROW_DEFAULT_WIDTH,
    TRANSPORT_ROW_MIN_WIDTH,
    TRANSPORT_ROW_SIDE_PAD,
    VIOSC_IP,
    VIOSC_LISTEN_PORT,
    VIOSC_PORT,
)
from vjmixapp.leap import (
    leap_init_from_config,
    normalize_tracking_event,
    restart_leap_engine,
    set_leap_enabled,
    set_leap_visualizer,
)
from vjmixapp.midi import (
    _clock_port_name,
    _close_midi_input,
    _parse_midi_msg,
    add_mode,
    apply_project_mapper_bindings,
    apply_project_mode_bindings,
    available_controller_ports,
    binding_led_behavior,
    binding_led_key,
    binding_mode,
    binding_source_from_message,
    capture_mode_defs,
    clear_all_modes,
    controller_connect,
    controller_disconnect,
    controller_profile_of,
    controller_profiles,
    ensure_mapping_output,
    find_controller_by_port,
    flash_binding_led,
    grid_controller,
    grid_flash_playhead,
    grid_mirror_step,
    grid_role,
    led_bindings_for_message,
    midi_init_from_config,
    midi_open_retry_due,
    mode_definition,
    mode_names,
    mode_usage,
    modes_for_mapping,
    most_recent_mode,
    project_mapper_bindings,
    project_mode_bindings,
    reapply_mode_leds,
    refresh_binding_leds,
    remove_mode,
    reregister_grid_bindings,
    reset_step_memory,
    resolve_binding_led,
    resolve_midi_message,  # noqa: F401 — facade re-export (REFACTOR_LATEST contract)
    resolve_midi_message_report,
    restore_mode_defs,
    role_sequencer_index,
    save_midi_controllers,
    scan_midi_inputs,
    selected_bindings,
    selected_controller,
    send_mapping_midi,
    send_mode_led,
    set_binding_mode,
    set_midi_enabled,
    set_mode_led,
    stale_ports,
    toggle_mode,
)
from vjmixapp.osc import (
    ALL_PROPERTIES,
    VjmixOSCUDPServer,
    find_source_by_name,
    get_current_target_id,
    incoming_osc_handler,
    next_thumb_frame_index,
    osc_client,
    request_thumbnail_over_osc,
    send_mapping_osc,
    size_receive_buffer,
    state_poll_worker,
    thumbnail_decoder_worker,
    thumbnail_fetch_worker,
)
from vjmixapp.osc import (
    validate_destination as validate_osc_destination,
)
from vjmixapp.palette import (
    _apply_theme_config,
    _preset_key,
    _set_media_cell,
    dpg_color_rgba,
    on_theme_color,
    on_theme_preset,
    palette_rgba,
    theme_color,
    themed_draw_rectangle,
    themed_text,
)
from vjmixapp.profiles import (
    match_controller_profile,
)
from vjmixapp.queues import (
    LOG_LEVEL_ERROR,
    LOG_LEVEL_INFO,
    LOG_LEVEL_WARN,
    append_log,
    enqueue_set_value,
    log_error,
    log_warn,
    ui_task,
)
from vjmixapp.sequencer import (
    _timed_bpm_live,
    advance_fade,
    beat_is_event_driven,  # noqa: F401 — facade re-export (the contract test pins it)
    fire_step,
    more_step_offerings,
    next_beat,
    parse_step_token,
    send_colorr_step,  # noqa: F401 — facade re-export (test harness drives these)
    send_colorv_step,  # noqa: F401 — facade re-export (test harness drives these)
    send_seekr_step,  # noqa: F401 — facade re-export (test harness drives these)
    step_modes_covered_by_legacy,
)
from vjmixapp.state import (
    _media_cell_cache,
    _midi_ignored_types,
    _pristine_track,
    _text_color_bindings,
    band_prev_values,
    bands_enabled,
    log_queue,
    midi_controllers,
    osc_log_history,
    request_timestamps,
    samplerate,
    sync_event_beat,
    sync_event_led,
    sync_event_seq,
    tap_times,
    texture_queue,
    thumb_cycle_state,
    thumb_fail_count,
    thumb_frames_at_last_request,
    thumbnails_data,
    tracks_data,
    ui_state_queue,
    ui_task_queue,
)

# --- HARD CAPS ON NETWORK-FED DATA (viOSC replies) ---
# Bound memory use and block PIL decompression bombs (audit MED-6).
Image.MAX_IMAGE_PIXELS = 25_000_000  # PIL's hard ceiling (~25 MP)

# Monitor player: compact graphical readout (e07)

# --- OSC CONFIGURATION ---
# VJmix talks exclusively to viOSC: /vimix/* messages are forwarded by viOSC
# to Vimix (port 7000), replies come back on viOSC's output port 6667.


# --- USER CONFIG + THEMING (e06) ---
# The per-user config lives under the XDG config dir (e21s01); the project
# files folder and the eager boot dirs are e21s01 task 5 (AppImage-safe: the
# app dir is read-only inside the bundle).

# VJmix application version — single source of truth (matches specs/release-plan.yaml, e08s02).
# e13s01: this is the first real release of VJmix (user decision).
# 1.1.0 — the viOSC link is HTTP (snapshot + delta stream, tile status strip), the shader
# pack grows to 60 assets with mappable uniform slots, two sequencers with their own
# geometry, five audio bands, Ableton Link as a beat source, and the UI pass (sources
# toolbar + Sources-data window, hover help, Logs vs I/O Monitor, Mapper momentary
# buttons, Launchpad grid input).
# e20s03: 0.2.0 — vjmixapp refactor + controller profiles + new project + Mapper family.
# 0.10.0 — the Text window (Pango markup + progressive reveal) and its four reveal modes as
# Step Sequencer step types; viOSC remote config + source-kind tiles; global MIDI-mappable
# actions (viOSC 0.6.0).
# 0.9.0 — audio band rectangles, Mapper toggle/clipboard/move, MIDI modes + LED feedback +
# rotation stepping, window layout/centering, tile "Set current".
# 0.8.0 — MIDI Learn as the toolbar's red icon, the Leap Motion signal expansion (four-column
# monitor, palm direction, finger curl + hand spread), the toolbar/window-cycle fixes and the Leap
# engine restart fix.
# 0.7.0 — link pairing gates the OSC and HTTP surfaces; File Manager + Session Drafts over the
# viOSC /fs data plane (thumbnails, video preview, .mix write/load with crossfade); session
# rename/overwrite/open+import; per-source alpha and the Send-time reassignment panel; the flat
# FontAwesome main toolbar replaces the dropdown menus (viOSC 0.5.0).
# 0.6.0 — the Mapper edits MAPPINGS (origin -> rescale -> destination): State/Clock/Constant
# origins driving MIDI and OSC destinations with dead-reckoning and the viOSC watch lane,
# one editor for create and modify, the I/O Monitor (MIDI+OSC, in+out, filters), the cue-row
# dialog fixes, and the monitor players removed (viOSC 0.4.0).
# 0.5.0 — source Preview (viOSC 0.3.0), cue lists, persistent MIDI-learn Mapper, Save as.
# 0.4.0 — Leap Motion mapper source, per-mapping reset, project save + OSC config persist,
# Mapper tile/row workflows (thumb assign, Add-to-Mapper submenu, line numbers).
# 0.3.0 — Mapper family (rows/rescale/enable/cycle), compact Vimix-sources grid, windows, XDG.
APP_VERSION: str = "1.1.0"

# The VJmix project repository, shown as a link in the Info window (e08s01; retargeted from the
# author's profile to the project by e08s03, user request).
GITHUB_URL: str = "https://github.com/lupin3rd/VJmix"
# e83: the Info window's donation link (the operator's own page).
DONATE_URL: str = "https://buymeacoffee.com/lupin3rd"

# Monospace font candidates for the pairing-code field (e55s02); the first existing
# path wins, and the bundled ProggyTiny is the guaranteed fallback.
_HELP_MONO_FONT_PATHS: tuple[str, ...] = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/usr/share/fonts/dejavu/DejaVuSansMono.ttf",
    "/usr/share/fonts/TTF/DejaVuSansMono.ttf",
)

# e08: the About-window brand mark, rasterised at 2x from logo.svg and packaged with the
# app (vjmixapp/assets is copied into the AppImage), so no vector renderer is needed.
_HELP_LOGO_PATH: str = str(
    Path(__file__).resolve().parent / "vjmixapp" / "assets" / "vjmix_logo.png"
)

# e46 amendment (2026-10-03, user request): the monochrome brand mark for the toolbar,
# rasterised at 2x from logo-flat.svg (white, so its tint takes the palette's text
# colour) and drawn at TOOLBAR_BRAND_W x TOOLBAR_BRAND_H.
_TOOLBAR_BRAND_PATH: str = str(
    Path(__file__).resolve().parent / "vjmixapp" / "assets" / "vjmix_brand.png"
)

# e83: vimix's own blending icons, one 8-cell strip (scripts/extract_blending_icons.py
# regenerates it from vimix's icons.dds, GPL-3.0 like this app). A missing asset
# leaves the badge empty and nothing else changes.
_BLENDING_ICONS_PATH: str = str(
    Path(__file__).resolve().parent / "vjmixapp" / "assets" / "blending_icons.png"
)
_BLENDING_ICONS_TEX_TAG = "blending_icons_texture"
_blending_icons_texture: Any = None

# Compact monospace font for the Mediagrid tile titles (ProggyTiny: the pixel-font
# family of DPG's default ProggyClean, but smaller; its line height equals the font
# size, so a two-line title stays tight). Bundled under vjmixapp/assets so packaged
# builds carry it; if missing the title falls back to the default 13 px font.
_TILE_TITLE_FONT_PATHS: tuple[str, ...] = (
    str(Path(__file__).resolve().parent / "vjmixapp" / "assets" / "ProggyTiny.ttf"),
    str(Path(__file__).resolve().parent / "assets" / "ProggyTiny.ttf"),
)
_tile_title_font: Any = None

# e71s02: a BOLD face for the band numbers drawn inside the Audio analyzer's rectangles
# (DejaVuSans-Bold, the pairing-code precedent: a system path, first hit wins). A missing
# file leaves None and the numbers keep the default font at the same coloured size.
_BAND_LABEL_FONT_PATHS: tuple[str, ...] = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
)
_band_label_font: Any = None

# e32s02: a larger ProggyTiny for the Mapper row line numbers (same guarded pattern;
# missing asset -> None -> the numbers fall back to the 10 px mapper font).
_mapper_line_no_font: Any = None

# e69s01: a SMALLER ProggyTiny for the TYPE line of a non-thumbnailable source in
# the Mapper row slot (same guarded pattern; missing asset -> None -> the type uses
# the 10 px mapper font, still dim).
_mapper_kind_font: Any = None

# --- e09: MIDI control engine (single mido stack; notes + CCs, user-configurable bindings) ---


# MIDI control runtime mirrors of cfg["midi"] (e09). The worker thread reads these; the
# main thread writes them. Bindings: [{device, channel, type("note"/"cc"/"pitch"), number,
# action, params}]. Learn flow state (e09s02): pending = (action, params) captured by a
# learnable widget click, awaiting the next incoming MIDI message.

# --- e09s03: Novation Launchpad adapter constants ---
# Three protocol classes (user's device: novlpd01 = original Launchpad MK1):
#  - MK1 (plain "Launchpad"/"Launchpad S"): grid notes 16*row+col (0-119 grid; official
#    Programmers Reference), palette velocity = 16*Green + Red + 12 (normal use): 12 off,
#    15 red full, 63 amber full, 62 yellow full, 60 green full — NO SysEx.
#  - MK2 family (MK2/Mini MK2/Pro): grid notes row*10+col, 128-color palette (manual:
#    0 off, 3 white, 5 red, 12 amber, 60 green) — native note mode.
#  - MK3 family (X/Mini MK3/Pro MK3): programmer mode first (SysEx setup), then the same
#    note grid as MK2. Payload WITHOUT the F0/F7 framing bytes — mido adds them when
#    sending a sysex message (verified: data must be 0-127; mido.bytes() yields
#    F0 00 20 29 02 0C 03 01 F7).
# e14s04: the LAUNCHPAD_* constants moved into the controller profile files
# (controllers/*.json); the runtime uses GRID_LED_* + profile fields.

# ==============================================================================
# CONTROLLER PROFILES (e14) — the profiles system moved to vjmixapp/profiles.py;
# VJmix re-exports its public names (port matcher, loader, note formula).


# Runtime bindings (tag -> palette slot) recorded at widget creation so apply_palette() can
# re-theme live. Theme color items are updated via set_value; text/draw items via
# configure_item (verified against DPG 2.3.1 in the e06 spike probes).


# Global chrome theme components (bind_theme) and their palette slots; only bound for
# non-Scuro themes, so Scuro keeps the exact DPG dark defaults (legacy look).

# --- COMMUNICATION QUEUES ---


# ==============================================================================
# THEMING (e06s02)
# ==============================================================================


# Per-cell cache for the Mediagrid value updates (perf e07 P0): a viOSC state push that
# does not change a cell's displayed string skips the set_value entirely. Cleared whenever
# the tables are rebuilt, so freshly created widgets are never wrongly skipped.


# ==============================================================================
# USER CONFIG + WINDOW LAYOUT (e06s01)
# ==============================================================================


# Windows already given a position this run: a saved project layout (apply) or
# the first-open centering below. Shared so a project layout always wins (e55).
_positioned_windows: set[str] = set()


def _existing_layout_window_tags() -> list[str]:
    """Tags of every layout-tracked window currently present in the UI."""
    tags = [t for t in LAYOUT_WINDOW_TAGS if dpg.does_item_exist(t)]
    return tags


def snapshot_window_layout() -> list[dict[str, Any]]:
    """Record shown/pos/size for every existing layout-tracked window (main thread only)."""
    records: list[dict[str, Any]] = []
    for tag in _existing_layout_window_tags():
        try:
            records.append(
                {
                    "tag": tag,
                    "shown": bool(dpg.is_item_shown(tag)),
                    "pos": list(dpg.get_item_pos(tag)),
                    "size": [
                        int(dpg.get_item_width(tag) or 0),
                        int(dpg.get_item_height(tag) or 0),
                    ],
                }
            )
        except Exception as e:
            log_error("Layout", f"skip {tag}: {e}")
    return records


def apply_window_layout(records: list[dict[str, Any]]) -> None:
    """Re-apply a saved layout to the workspace windows; unknown tags are skipped.

    Only LAYOUT_WINDOW_TAGS are honoured: an older project that still carries a
    config/diagnostic record (settings_window) must never move that window (e55s01).
    Applied tags join `_positioned_windows`, so first-open centering yields to the
    saved layout.
    """
    for rec in records:
        tag = rec.get("tag")
        if not tag or tag not in LAYOUT_WINDOW_TAGS or not dpg.does_item_exist(tag):
            continue
        try:
            pos = list(rec["pos"])
            pos[1] = max(int(pos[1]), TOOLBAR_BAR_H)  # never under the toolbar strip
            dpg.set_item_pos(tag, pos)
            dpg.set_item_width(tag, rec["size"][0])
            dpg.set_item_height(tag, rec["size"][1])
            if bool(rec.get("shown")):
                dpg.show_item(tag)
            else:
                dpg.hide_item(tag)
            _positioned_windows.add(tag)
        except Exception as e:
            log_error("Layout", f"apply {tag}: {e}")


# ==============================================================================
# PROJECT SAVE/LOAD (e11) — .vjmix files capture window layout + theme + every
# sequencer configuration; the VJmix menu (e11s03) drives the file dialogs.
# ==============================================================================
PROJECTS_DIR = os.path.join(user_config_dir(), "projects")
# Step fields that belong in a project file; the last_rand_* keys are runtime-only.


def ensure_user_dirs() -> None:
    """Create the XDG user dirs at boot (e21s01)."""
    os.makedirs(user_config_dir(), exist_ok=True)
    os.makedirs(PROJECTS_DIR, exist_ok=True)


def _step_persisted(step: dict[str, Any]) -> dict[str, Any]:
    """Reduce a runtime step dict to its persisted fields (e11s01)."""
    return {key: copy.deepcopy(step[key]) for key in STEP_PERSISTED_KEYS if key in step}


def _capture_audio_state() -> dict[str, Any]:
    """Snapshot the audio-analyzer section from its widgets (e11s01)."""
    bands: dict[str, dict[str, Any]] = {}
    for band_id in BAND_DEFAULT_RANGES:
        bands[str(band_id)] = {
            "enabled": bool(dpg.get_value(f"band{band_id}_enabled")),
            "start": float(dpg.get_value(f"band{band_id}_start")),
            "end": float(dpg.get_value(f"band{band_id}_end")),
            "min": float(dpg.get_value(f"band{band_id}_min")),
            "max": float(dpg.get_value(f"band{band_id}_max")),
        }
    return {
        "device": str(dpg.get_value("combo_devices")),
        "lowpass": bool(dpg.get_value("cb_lowpass")),
        "bands": bands,
        "spectrum": state.is_audio_analyzing,  # e28s03: analysis checkboxes
        "bpm": state.is_beat_tracking,
    }


def _capture_mapper_state() -> dict[str, Any]:
    """Project the live mapper into its persisted section (e28s01)."""
    return {
        "mappings": [mapper.capture_mapping(m) for m in state.mapper_mappings],
    }


def _sanitize_mapper_mappings(
    mappings: Any, registry: dict[str, dict[str, dict[str, float | None]]] | None = None
) -> list[dict[str, Any]]:
    """Heal the mapper mappings list: bounded, invalid rows dropped (e28s01).

    ``registry`` is the uniform registry the dynamic `uniform:<slot>` properties are
    resolved against; a project load passes the DOCUMENT's registry
    (BUG-2026-10-14T191248).
    """
    if not isinstance(mappings, list):
        return []
    clean: list[dict[str, Any]] = []
    for raw in mappings[:MAPPER_MAX_MAPPINGS]:
        healed = mapper.sanitize_mapping(raw, registry)
        if healed is not None:
            clean.append(healed)
    return clean


def _capture_sequencer_state() -> dict[str, Any]:
    """The live sequencer as ONE project record, geometry included (e66s01).

    `rows`/`cols` are the live geometry, and the tracks list is ALWAYS written at the
    full tag space (8 x 8) even when the grid shows fewer: the geometry is a DISPLAY
    state, so shrinking it must never destroy what it hides.
    """
    return {
        "rows": state.seq_rows,
        "cols": state.seq_cols,
        "zoom": state.seq_zoom,
        "beat_source": state.beat_source,
        "manual_bpm": float(dpg.get_value("manual_bpm_input")),
        "tracks": [
            {
                "target_id": track.get("target_id"),
                "base_address": track.get("base_address", ""),
                "steps": [_step_persisted(step) for step in track["steps"]],
            }
            for track in tracks_data
        ],
        "audio": _capture_audio_state(),
    }


def _project_sequencer_records(doc: dict[str, Any]) -> list[dict[str, Any]]:
    """The sequencer records of a document, in EITHER shape (e66s01).

    v2 carries `sequencers` (a list, and ZERO is legal: the sequencer can be deleted for
    good), v1 carried `sequencer` (a dict). One reader for both, so the migration lives in
    exactly one place instead of at every caller.
    """
    records = doc.get("sequencers")
    if isinstance(records, list):
        return [record for record in records if isinstance(record, dict)]
    legacy = doc.get("sequencer")
    if isinstance(legacy, dict):
        return [legacy]
    return []


def _healed_sequencer_record(raw: Any) -> dict[str, Any]:
    """One sequencer record, healed: geometry, zoom, beat source, tracks, audio (e66s03).

    The geometry AND the zoom are healed here, at the door, so a hand-edited `rows: 3` or
    `zoom: 999` cannot build a grid the product does not offer — and a v1 record (neither
    key) becomes exactly what a v1 project WAS: 8x8 at the level the look was designed at.
    """
    seq = raw if isinstance(raw, dict) else {}
    beat = seq.get("beat_source")
    return {
        "rows": sanitize_geometry(seq.get("rows")),
        "cols": sanitize_geometry(seq.get("cols")),
        "zoom": sanitize_seq_zoom(seq.get("zoom")),
        "beat_source": beat if beat in BEAT_SOURCE_LABELS else BEAT_SOURCE_ANALYSIS,
        "manual_bpm": _to_float(seq.get("manual_bpm"), DEFAULT_MANUAL_BPM),
        "tracks": _sanitize_tracks(seq.get("tracks")),
        "audio": _sanitize_audio_state(seq.get("audio")),
    }


def capture_project_state() -> dict[str, Any]:
    """Snapshot layout + theme + sequencer + mapper into a project dict (e11s01/e28s01)."""
    preset_label = str(dpg.get_value("theme_preset"))
    return {
        "layout": {"windows": snapshot_window_layout()},
        "theme": {
            "preset": _preset_key(preset_label),
            "colors": copy.deepcopy(state.active_palette),
        },
        # e66s01: a LIST of sequencer records. One element today; e67 appends the
        # second instead of forcing a third schema migration (a migration is the one
        # cost that must not be paid twice).
        "sequencers": [_capture_sequencer_state()],
        "text": {
            "document": state.text_document,
            "target": state.text_target,
            "path": state.text_source_path,
        },
        # e61: the shader asset, its declared target kind and the client-side
        # uniform registry (vimix reports neither the code nor its uniform
        # values back, so what we sent is what we remember).
        "shader": {
            "document": state.shader_document,
            "target": state.shader_target,
            "kind": state.shader_kind,
            "family": state.shader_family,
            "path": state.shader_path,
            "uniforms": copy.deepcopy(state.shader_uniforms),
        },
        "mapper": _capture_mapper_state(),
        # 2026-09-07: the project also carries the MIDI rows that drive ITS
        # Mapper mappings, so opening the project restores its MIDI routing.
        # e52s03: and its modes (definitions + LED) with their Binding rows.
        "midi": {
            "modes": capture_mode_defs(),
            "mapper_bindings": project_mapper_bindings(),
            "mode_bindings": project_mode_bindings(),
        },
    }


# --- e37: current-project identity + unsaved-changes marker (title bar) ---
# The app tracks which .vjmix document the live session belongs to and whether
# the next Save would write something different. Window layout is deliberately
# excluded from the content fingerprint: moving/resizing windows is workspace
# preference, not document content (user agreement 2026-09-07). The mapping
# 'value' fields are excluded too — band/MIDI/Leap drives rewrite them
# constantly during playback, so like the last_rand_* step keys they are
# runtime state, never a dirt source (they still ride along on every save).
UNSAVED_PROJECT_LABEL = "Untitled"
PROJECT_DIRTY_POLL_SECONDS = 0.5


def _project_content_fingerprint() -> str:
    """Canonical JSON of the live project CONTENT (layout + live values out, e37s03)."""
    content = capture_project_state()
    content.pop("layout", None)
    for mapping in content.get("mapper", {}).get("mappings", []):
        mapping.pop("value", None)
    return json.dumps(content, sort_keys=True, separators=(",", ":"))


def current_project_label() -> str:
    """Title-bar name of the current project: file basename or Untitled (e37)."""
    path = state.current_project_path
    if path:
        return os.path.basename(path)
    return UNSAVED_PROJECT_LABEL


def refresh_window_title() -> None:
    """Rewrite the X11 viewport title with the project name + dirty marker (e37s03)."""
    marker = " *" if state.project_dirty else ""
    dpg.set_viewport_title(f"VJmix - {current_project_label()}{marker}")


def _adopt_content_as_saved() -> None:
    """Record the live content as the saved baseline (save/open/new/boot, e37s01).

    The baseline is derived from the LIVE state after the flow ran — never by
    re-reading the file — so it matches exactly what the next Save would write.
    Does not touch dpg (boot calls it before the viewport exists).
    """
    state.project_dirty = False
    state.saved_content_fingerprint = _project_content_fingerprint()


def _sync_project_dirty() -> bool:
    """Poll the live content vs the saved baseline; True when the flag flipped."""
    dirty = _project_content_fingerprint() != state.saved_content_fingerprint
    if dirty == state.project_dirty:
        return False
    state.project_dirty = dirty
    refresh_window_title()
    return True


_last_project_dirty_poll = 0.0


def tick_project_dirty(now: float) -> None:
    """Main-loop cadence (~0.5 s): flip the dirty marker when content changed (e37s03)."""
    global _last_project_dirty_poll
    if now - _last_project_dirty_poll < PROJECT_DIRTY_POLL_SECONDS:
        return
    _last_project_dirty_poll = now
    _sync_project_dirty()


def _restore_step(row: int, col: int, step_data: dict[str, Any]) -> None:
    """Apply one persisted step onto the live cell and rebuild its UI (e11s01)."""
    step = tracks_data[row]["steps"][col]
    for key in STEP_PERSISTED_KEYS:
        if key in step_data:
            step[key] = copy.deepcopy(step_data[key])
    update_step_ui(row, col)


def _restore_track(row: int, track_data: dict[str, Any]) -> None:
    """Apply one persisted track (clip assignment + steps) and rebuild its UI (e11s01)."""
    target_id = track_data.get("target_id")
    tracks_data[row]["target_id"] = target_id
    tracks_data[row]["base_address"] = f"/vimix/{target_id}" if target_id else ""
    for col, step_data in enumerate(track_data.get("steps", [])):
        if col >= NUM_STEPS:
            break
        _restore_step(row, col, step_data)
    update_track_slot_ui(row)


def _apply_audio_state(audio: dict[str, Any]) -> None:
    """Re-apply the audio-analyzer section (device, low-pass, bands) (e11s01)."""
    if audio.get("device") in input_devices_list:
        dpg.set_value("combo_devices", audio["device"])
    state.lowpass_enabled = bool(audio.get("lowpass", True))
    if dpg.does_item_exist("cb_lowpass"):
        dpg.set_value("cb_lowpass", state.lowpass_enabled)
    bands = audio.get("bands", {})
    for band_id in BAND_DEFAULT_RANGES:
        band = bands.get(str(band_id), {})
        bands_enabled[band_id] = bool(band.get("enabled", False))
        if dpg.does_item_exist(f"band{band_id}_enabled"):
            dpg.set_value(f"band{band_id}_enabled", bands_enabled[band_id])
        for key in ("start", "end", "min", "max"):
            tag = f"band{band_id}_{key}"
            if key in band and dpg.does_item_exist(tag):
                dpg.set_value(tag, float(band[key]))
        if bands_enabled[band_id]:
            refresh_band_value(state.spectrum_bars_cache, band_id)
    # e28s03: analysis checkboxes restore last — the device combo above is set
    # first because opening the input stream reads the selected device.
    if "spectrum" in audio or "bpm" in audio:
        set_audio_analysis_flags(bool(audio.get("spectrum", False)), bool(audio.get("bpm", False)))


def _apply_sequencer_state(seq: dict[str, Any]) -> None:
    """Re-apply the geometry, beat source, manual BPM, tracks and audio section (e11s01).

    e67s05: the grid is BUILT here, at the record's own shape. The boot no longer invents A, so
    "a project carries the shape" is exactly this call — it is what turns an empty start into a
    sequencer. (Before this, a record's rows/cols/zoom were written to the live state while the
    grid stayed whatever the import had built at the defaults: a 4x4 project booted at 8x8.)
    """
    # e66s01: the LIVE geometry comes from the document. A v1 record carries neither key,
    # and `sanitize_geometry` heals a missing value to the cap — 8x8, exactly what a v1
    # project was. One sanitizer at the door means a hand-edited `rows: 3` cannot resize
    # the grid out of its choices either.
    state.seq_rows = sanitize_geometry(seq.get("rows"))
    state.seq_cols = sanitize_geometry(seq.get("cols"))
    state.seq_zoom = sanitize_seq_zoom(seq.get("zoom"))
    build_sequencer(state.seq_rows, state.seq_cols, state.seq_zoom, parent="seq_grid_host")
    mode = seq.get("beat_source")
    if mode not in BEAT_SOURCE_LABELS:
        mode = BEAT_SOURCE_ANALYSIS
    if "manual_bpm" in seq and dpg.does_item_exist("manual_bpm_input"):
        dpg.set_value("manual_bpm_input", float(seq["manual_bpm"]))
    midi_action_beat_source(mode)  # beat_source + checkboxes + manual-widget visibility
    for row, track_data in enumerate(seq.get("tracks", [])):
        if row >= NUM_TRACKS:
            break
        _restore_track(row, track_data)
    audio = seq.get("audio")
    if isinstance(audio, dict):
        _apply_audio_state(audio)


def apply_project_state(doc: dict[str, Any]) -> None:
    """Re-apply a project dict onto the live app (mapper, layout, theme, sequencer) (e11s01/e28s01).

    e28s01: the mapper state is restored BEFORE the window layout applies, so
    the Mapper body exists by the time a saved layout may show the window.
    """
    # BUG-2026-10-14T191248: the document's uniform registry is the authority while the
    # live one may still be empty — the mapper rows resolve their `uniform:<slot>` there.
    shader_section = doc.get("shader")
    document_registry = (
        shadercode.sanitize_uniform_registry(shader_section.get("uniforms"))
        if isinstance(shader_section, dict)
        else None
    )
    mapper_section = doc.get("mapper")
    if isinstance(mapper_section, dict):
        mapper.restore_mappings(mapper_section.get("mappings"), document_registry)
        refresh_mapper_ui()
    midi_section = doc.get("midi")
    if isinstance(midi_section, dict):  # 2026-09-07: restore the project's MIDI routing
        live_ids = {int(m["id"]) for m in state.mapper_mappings}
        apply_project_mapper_bindings(midi_section.get("mapper_bindings"), live_ids)
        if "modes" in midi_section:  # e52s03: the project's mode layer
            clear_all_modes()  # off LEDs while the OLD registry is still known
            restore_mode_defs(midi_section.get("modes"))
            apply_project_mode_bindings(midi_section.get("mode_bindings"), mode_names())
            refresh_midi_modes_ui()
            refresh_midi_mappings_ui()
            refresh_mode_chip()
    apply_window_layout(doc.get("layout", {}).get("windows", []))
    theme = doc.get("theme")
    if isinstance(theme, dict):
        _apply_theme_config(theme)
    records = _project_sequencer_records(doc)
    if records:
        _apply_sequencer_state(records[0])
    text_section = doc.get("text")
    if isinstance(text_section, dict):
        _apply_text_state(text_section)
    shader_section = doc.get("shader")
    if isinstance(shader_section, dict):
        _apply_shader_state(shader_section)


def pristine_project_state() -> dict[str, Any]:
    """The New-project document: blank sequencer, current layout + theme kept (e15s01).

    Layout and theme are app-level preferences — a fresh project never moves
    the windows or changes the colors; only the sequencer content resets.
    """
    pristine_tracks = [_pristine_track() for _ in range(NUM_TRACKS)]
    return {
        "layout": {"windows": snapshot_window_layout()},
        "theme": {
            "preset": _preset_key(str(dpg.get_value("theme_preset"))),
            "colors": copy.deepcopy(state.active_palette),
        },
        "sequencers": [
            {
                "rows": SEQ_MAX_ROWS,
                "cols": SEQ_MAX_COLS,
                "beat_source": BEAT_SOURCE_ANALYSIS,
                "manual_bpm": DEFAULT_MANUAL_BPM,
                "tracks": [
                    {
                        "target_id": track["target_id"],
                        "base_address": track["base_address"],
                        "steps": [_step_persisted(step) for step in track["steps"]],
                    }
                    for track in pristine_tracks
                ],
                "audio": {
                    "device": str(dpg.get_value("combo_devices")),
                    "lowpass": True,
                    "bands": {
                        str(band_id): {
                            "enabled": False,
                            "start": default_range[0],
                            "end": default_range[1],
                            "min": 0.0,
                            "max": 1.0,
                        }
                        for band_id, default_range in BAND_DEFAULT_RANGES.items()
                    },
                },
            }
        ],
        "text": {"document": "", "target": "", "path": ""},
        # e61: a fresh project has no shader asset and no registry, and the kind
        # default is the effect profile (the more common target).
        "shader": {
            "document": "",
            "target": "",
            "kind": SHADER_KIND_DEFAULT,
            "path": "",
            "uniforms": {},
        },
        "mapper": {"mappings": []},
    }


def apply_new_project() -> None:
    """Reset the live sequencer to pristine defaults and rebuild its UI (e15s01).

    Tracks are replaced wholesale (clearing pending fades and the runtime
    last_rand_* keys), then the project-apply path rebuilds every cell, slot,
    beat-source checkbox and audio widget. e28s01: the Mapper is project
    content, so New project clears its mappings too and refreshes the body.

    e68 (operator): a NEW project also CLOSES every workspace window — the operator builds the
    layout they want from the bar instead of inheriting the previous project's.
    """
    for row in range(NUM_TRACKS):
        tracks_data[row] = _pristine_track()
    _apply_sequencer_state(pristine_project_state()["sequencers"][0])
    mapper.restore_mappings([])
    refresh_mapper_ui()
    _apply_text_state({"document": "", "target": "", "path": ""})
    hide_all_workspace_windows()


def hide_all_workspace_windows() -> None:
    """Close every workspace window (e68): a fresh state starts with NOTHING open.

    A project that carries a layout still restores it (`apply_window_layout`), so this runs only
    for a NEW project and for a boot that restored none. The sequencer windows are hidden too: an
    empty slot asks for its shape when the operator opens it.
    """
    for tag in LAYOUT_WINDOW_TAGS:
        if dpg.does_item_exist(tag) and dpg.is_item_shown(tag):
            dpg.hide_item(tag)


def _project_document(state: dict[str, Any]) -> dict[str, Any]:
    """Wrap a state dict into a versioned project document (e11s01)."""
    return {"format": PROJECT_FORMAT, "version": PROJECT_VERSION, **state}


def save_project_to_file(path: str, state: dict[str, Any]) -> bool:
    """Atomically write a project document; False + logged reason on failure (e11s01)."""
    try:
        tmp = f"{path}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_project_document(state), f, indent=2)
        os.replace(tmp, path)
        return True
    except OSError as e:
        log_error("Project", f"cannot write {path}: {e}")
        return False


def load_project_file(path: str) -> dict[str, Any] | None:
    """Read + validate a project file, sanitized; None (logged) on any problem (e11s01)."""
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, ValueError) as e:
        log_error("Project", f"cannot read {path}: {e}")
        return None
    if not isinstance(raw, dict):
        log_error("Project", f"{path}: not a project document")
        return None
    if raw.get("format") != PROJECT_FORMAT or raw.get("version") not in PROJECT_VERSIONS_READABLE:
        log_error(
            "Project",
            f"{path}: unsupported format/version {raw.get('format')}/{raw.get('version')}",
        )
        return None
    return _sanitize_project_state(raw)


def _to_float(value: Any, default: float) -> float:
    """Coerce a stored value to float, falling back on garbage (e11s01)."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _default_step() -> dict[str, Any]:
    """A pristine step cell, the template for sanitize healing (e11s01)."""
    return {
        "active": False,
        "type": "NONE",
        "v1": 0.0,
        "v2": 1.0,
        "frames": 4,
        "msgs": 1,
        "color": [1.0, 1.0, 1.0],
    }


def _sanitize_step(step: Any) -> dict[str, Any]:
    """Heal one step: missing persisted keys get defaults, unknown keys drop (e11s01)."""
    base = _default_step()
    if isinstance(step, dict):
        for key in STEP_PERSISTED_KEYS:
            if key in step:
                base[key] = step[key]
    if base.get("type") == "FlagX":
        # e36s07: flag is a VALUE step now; the legacy fire token always meant
        # "next", which the value form preserves as -1.
        base["type"] = "FlagV"
        base["v1"] = -1.0
    return base


def _sanitize_tracks(tracks: Any) -> list[dict[str, Any]]:
    """Heal the track list: bounded to NUM_TRACKS, steps healed and capped (e11s01)."""
    clean: list[dict[str, Any]] = []
    if isinstance(tracks, list):
        for track in tracks[:NUM_TRACKS]:
            if not isinstance(track, dict):
                track = {}
            steps = track.get("steps", [])
            if not isinstance(steps, list):
                steps = []
            clean.append(
                {
                    "target_id": track.get("target_id"),
                    "base_address": track.get("base_address", ""),
                    "steps": [_sanitize_step(s) for s in steps[:NUM_STEPS]],
                }
            )
    return clean


def _sanitize_audio_state(audio: Any) -> dict[str, Any]:
    """Heal the audio section: band values clamped to their defaults (e11s01)."""
    if not isinstance(audio, dict):
        audio = {}
    raw_bands = audio.get("bands", {})
    if not isinstance(raw_bands, dict):
        raw_bands = {}
    bands: dict[str, dict[str, Any]] = {}
    for band_id, default_range in BAND_DEFAULT_RANGES.items():
        band = raw_bands.get(str(band_id), {})
        if not isinstance(band, dict):
            band = {}
        bands[str(band_id)] = {
            "enabled": bool(band.get("enabled", False)),
            "start": _to_float(band.get("start"), default_range[0]),
            "end": _to_float(band.get("end"), default_range[1]),
            "min": _to_float(band.get("min"), 0.0),
            "max": _to_float(band.get("max"), 1.0),
        }
    clean = {
        "device": str(audio.get("device", "")),
        "lowpass": bool(audio.get("lowpass", True)),
        "bands": bands,
    }
    # e28s03: analysis flags are only healed onto the document when the source
    # file carried them — a pre-e28 audio section leaves the live analysis alone.
    if "spectrum" in audio:
        clean["spectrum"] = bool(audio.get("spectrum"))
    if "bpm" in audio:
        clean["bpm"] = bool(audio.get("bpm"))
    return clean


def _sanitize_project_state(raw: dict[str, Any]) -> dict[str, Any]:
    """Coerce a loaded project document into the capture shape (e11s01/e28s01)."""
    theme = raw.get("theme")
    if not isinstance(theme, dict):
        theme = {"preset": "scuro", "colors": copy.deepcopy(DEFAULT_PALETTE)}
    else:
        preset = str(theme.get("preset", "scuro"))
        if preset not in THEME_PRESET_LABELS:
            preset = "scuro"
        palette = theme.get("colors")
        if not isinstance(palette, dict):
            palette = copy.deepcopy(DEFAULT_PALETTE)
        theme = {"preset": preset, "colors": _sanitize_palette(palette)}
    layout = raw.get("layout")
    if not isinstance(layout, dict) or not isinstance(layout.get("windows"), list):
        layout = {"windows": []}
    # e66s01: a v2 document carries `sequencers` (a list of records, and ZERO is legal) and a
    # v1 document carried `sequencer` (a dict); ONE reader serves both, so the migration lives
    # in a single place. The list is capped: the product offers at most `SEQ_MAX_SEQUENCERS`.
    records = _project_sequencer_records(raw)[:SEQ_MAX_SEQUENCERS]
    clean = {
        "layout": {"windows": layout["windows"]},
        "theme": theme,
        "sequencers": [_healed_sequencer_record(record) for record in records],
    }
    # e28s01: the mapper section is only present in the healed document when the
    # source file carried one — a pre-e28 project leaves the live mapper alone.
    # BUG-2026-10-14T191248: a dynamic `uniform:<slot>` property is healed against the
    # DOCUMENT's registry — the live one is still empty on a freshly opened app.
    document_shader = raw.get("shader")
    document_registry = (
        shadercode.sanitize_uniform_registry(document_shader.get("uniforms"))
        if isinstance(document_shader, dict)
        else None
    )
    raw_mapper = raw.get("mapper")
    if isinstance(raw_mapper, dict):
        clean["mapper"] = {
            "mappings": _sanitize_mapper_mappings(raw_mapper.get("mappings"), document_registry)
        }
    # 2026-09-07: project-scoped Midi rows pass through (bounded; missing/older
    # projects simply carry none and leave the global routing untouched).
    raw_midi = raw.get("midi")
    if isinstance(raw_midi, dict):
        clean_midi: dict[str, Any] = {}
        if isinstance(raw_midi.get("mapper_bindings"), list):
            rows = [r for r in raw_midi["mapper_bindings"] if isinstance(r, dict)]
            clean_midi["mapper_bindings"] = rows[: MAPPER_MAX_MAPPINGS * 8]
        # e52s03: the mode registry and its Binding rows, same bounds as the rows
        if isinstance(raw_midi.get("modes"), list):
            modes = [m for m in raw_midi["modes"] if isinstance(m, dict)]
            clean_midi["modes"] = modes[:MAPPER_MAX_MAPPINGS]
        if isinstance(raw_midi.get("mode_bindings"), list):
            rows = [r for r in raw_midi["mode_bindings"] if isinstance(r, dict)]
            clean_midi["mode_bindings"] = rows[: MAPPER_MAX_MAPPINGS * 8]
        if clean_midi:
            clean["midi"] = clean_midi
    # e59s03: the text section is only present when the loaded project carried
    # one — a pre-e59 document must leave the live document alone.
    raw_text = raw.get("text")
    if isinstance(raw_text, dict):
        clean["text"] = {
            "document": str(raw_text.get("document") or "")[:TEXT_MAX_LOAD_BYTES],
            "target": str(raw_text.get("target") or ""),
            "path": str(raw_text.get("path") or ""),
        }
    # e61: the shader section is only present when the loaded project carried one
    # (a pre-e61 document must leave the live shader state alone). A corrupt kind
    # coerces to the GENERATOR profile, the crash-safe direction: a wrong
    # 'generator' only disables /uniform, while a wrong 'effect' would let VJmix
    # send /uniform to a ShaderSource, which the rig showed kills vimix.
    raw_shader = raw.get("shader")
    if isinstance(raw_shader, dict):
        kind = str(raw_shader.get("kind") or "")
        clean["shader"] = {
            "document": str(raw_shader.get("document") or "")[:SHADER_MAX_LOAD_BYTES],
            "target": str(raw_shader.get("target") or ""),
            "kind": kind if kind in SHADER_KINDS else SHADER_KIND_GENERATOR,
            "path": str(raw_shader.get("path") or ""),
            "uniforms": shadercode.sanitize_uniform_registry(raw_shader.get("uniforms")),
        }
    return clean


def remember_recent_project(cfg: dict[str, Any], path: str) -> list[str]:
    """Insert a project path at the front of the recent list (dedupe + cap) (e11s02)."""
    recent = cfg.setdefault("projects", {}).setdefault("recent", [])
    if path in recent:
        recent.remove(path)
    recent.insert(0, path)
    del recent[RECENT_PROJECTS_MAX:]
    return recent


def recent_project_paths(cfg: dict[str, Any]) -> list[str]:
    """The recent project list with entries whose files no longer exist pruned (e11s02)."""
    return [p for p in cfg.get("projects", {}).get("recent", []) if os.path.exists(p)]


def should_restore_last_project_on_boot(cfg: dict[str, Any]) -> bool:
    """Whether boot should re-apply the most recent project (default True) (e11s02)."""
    return bool(cfg.get("projects", {}).get("restore_last_on_boot", True))


def on_restore_project_boot_toggle(
    sender: Any = None, app_data: Any = None, user_data: Any = None
) -> None:
    """Settings 'Restore last project at startup' checkbox: persist the flag (e11s02)."""
    cfg = load_config()
    cfg.setdefault("projects", {})["restore_last_on_boot"] = bool(app_data)
    save_config(cfg)


# --- e11s03: VJmix menu flows (Open / Last / Save / Exit + file dialogs) ---
def _ensure_project_extension(path: str) -> str:
    """Append the .vjmix extension when the chosen name has none (e11s03)."""
    if path.lower().endswith(PROJECT_FILE_EXTENSION):
        return path
    return f"{path}{PROJECT_FILE_EXTENSION}"


def save_project_file(path: str) -> bool:
    """Capture + write a project, adopt it as current; False + logged on failure (e11s03/e37s01)."""
    path = _ensure_project_extension(path)
    if not save_project_to_file(path, capture_project_state()):
        return False
    state.current_project_path = path
    _adopt_content_as_saved()
    refresh_window_title()
    cfg = load_config()
    remember_recent_project(cfg, path)
    save_config(cfg)
    return True


def open_project_file(path: str) -> bool:
    """Load + apply a project, adopt it as current, remember it (e11s03/e37s01)."""
    doc = load_project_file(path)
    if doc is None:
        return False
    apply_project_state(doc)
    state.current_project_path = path
    _adopt_content_as_saved()
    refresh_window_title()
    cfg = load_config()
    cfg["theme"] = doc["theme"]
    remember_recent_project(cfg, path)
    save_config(cfg)
    return True


def open_recent_project(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """Last-project submenu entry -> open that project file (e11s03)."""
    if isinstance(user_data, str):
        open_project_file(user_data)


def _recreate_project_dialog(tag: str, callback: Any, default_filename: str | None) -> None:
    """(Re)create one project file dialog with .vjmix/.* filters, then show it (e13s02).

    DPG's file dialog shows only directories when no extension filters exist;
    recreating on every show guarantees a fresh dialog whose default path was
    just created by the caller.
    """
    if dpg.does_item_exist(tag):
        dpg.delete_item(tag)
    kwargs: dict[str, Any] = {
        "tag": tag,
        "show": False,
        "width": 480,
        "height": 360,
        "callback": callback,
        "default_path": PROJECTS_DIR,
        "modal": True,
    }
    if default_filename:
        kwargs["default_filename"] = default_filename
    with dpg.file_dialog(**kwargs):
        dpg.add_file_extension(PROJECT_FILE_EXTENSION)
        dpg.add_file_extension(".*")
        dpg.add_file_extension("")  # #2080 defensive: some systems hide files with .* only
    dpg.show_item(tag)


def show_open_project_dialog() -> None:
    """Show the Open-project file dialog, defaulting to the projects folder (e11s03, e13s02)."""
    os.makedirs(PROJECTS_DIR, exist_ok=True)
    _recreate_project_dialog("open_project_dialog", on_open_project_picked, None)


def show_save_project_dialog() -> None:
    """Show the Save-as file dialog, prefilled with the current project name (e11s03/e37s02)."""
    os.makedirs(PROJECTS_DIR, exist_ok=True)
    default = (
        os.path.basename(state.current_project_path)
        if state.current_project_path
        else f"project{PROJECT_FILE_EXTENSION}"
    )
    _recreate_project_dialog("save_project_dialog", on_save_project_picked, default)


def on_open_project_picked(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """Open-dialog result -> open the chosen project file (e11s03)."""
    path = app_data.get("file_path_name") if isinstance(app_data, dict) else None
    if path:
        open_project_file(path)


def on_save_project_picked(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """Save-dialog result -> save a project, forcing the .vjmix extension (e11s03)."""
    path = app_data.get("file_path_name") if isinstance(app_data, dict) else None
    if path:
        save_project_file(path)


def save_current_project(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """VJmix > Save: write the current project; the first save opens Save as (e37s02)."""
    if state.current_project_path:
        save_project_file(state.current_project_path)
    else:
        show_save_project_dialog()


def exit_app(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """VJmix > Exit menu voice: the close request (e19/e37s04, always confirmed)."""
    request_exit()


# e19/e37s04, e40s11: exit confirmation — the modal is shared by VJmix > Exit and
# the OS main-window X (set_exit_callback + disable_close) and opens ALWAYS.
# VJmix is a live-performance tool: the window X sits next to the controls, so a
# stray click must never kill the session; the prompt names the dirty case.
# ``_exiting_app`` guards the shutdown-time re-invocation of the exit callback
# (destroy_context queues it again while tearing down, when no modal may exist).
EXIT_CONFIRM_TAG = "exit_confirm_modal"


_exiting_app = False


def request_exit(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """Close request (menu Exit or the OS window X): ALWAYS confirm first (e40s11).

    The dirty check is refreshed only to WORD the prompt: a clean session is
    confirmed too, because a live tool must never close on a stray click.
    """
    if _exiting_app:
        return  # already confirmed — destroy_context re-invokes the exit callback
    _sync_project_dirty()  # fresh dirt: the ~0.5 s cadence may lag a just-made edit
    show_exit_confirm()


def show_exit_confirm(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """Open the Exit-confirmation modal (menu Exit, the OS window X, e37s04/e40s11)."""
    if _exiting_app:
        return  # already confirmed — destroy_context re-invokes the exit callback
    if dpg.does_item_exist(EXIT_CONFIRM_TAG):
        dpg.delete_item(EXIT_CONFIRM_TAG)
    warning = (
        "Any unsaved changes will be lost."
        if state.project_dirty
        else "The current session will close."
    )
    with dpg.window(
        label="Exit VJmix",
        tag=EXIT_CONFIRM_TAG,
        modal=True,
        width=380,
        height=150,
        no_resize=True,
    ):
        themed_text("Close VJmix?", slot="text")
        themed_text(warning, slot="text_dim")
        dpg.add_separator()
        with dpg.group(horizontal=True):
            dpg.add_button(label="Cancel", callback=cancel_exit, width=140)
            dpg.add_button(label="Exit", callback=confirm_exit, width=140)
    show_centered_window(EXIT_CONFIRM_TAG)  # e55: dialogs open centered


def cancel_exit(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """Exit modal Cancel: close the prompt, the app keeps running (e19)."""
    if dpg.does_item_exist(EXIT_CONFIRM_TAG):
        dpg.delete_item(EXIT_CONFIRM_TAG)


def confirm_exit(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """Exit modal Exit: close the prompt and stop the app (normal cleanup runs)."""
    global _exiting_app
    _exiting_app = True
    if dpg.does_item_exist(EXIT_CONFIRM_TAG):
        dpg.delete_item(EXIT_CONFIRM_TAG)
    dpg.stop_dearpygui()


NEW_PROJECT_CONFIRM_TAG = "new_project_confirm"


def show_new_project_confirm(
    sender: Any = None, app_data: Any = None, user_data: Any = None
) -> None:
    """VJmix > New project: open the confirmation modal (e15s01).

    Never resets directly — wiping the sequencer is destructive, so the user
    must confirm first.
    """
    if dpg.does_item_exist(NEW_PROJECT_CONFIRM_TAG):
        dpg.delete_item(NEW_PROJECT_CONFIRM_TAG)
    with dpg.window(
        label="New project",
        tag=NEW_PROJECT_CONFIRM_TAG,
        modal=True,
        width=380,
        height=140,
        no_resize=True,
    ):
        dpg.add_text("Start a new project?", wrap=340)
        dpg.add_text("The sequencer (clips and steps) will be cleared.", wrap=340)
        dpg.add_separator()
        with dpg.group(horizontal=True):
            dpg.add_button(label="Cancel", callback=cancel_new_project, width=140)
            dpg.add_button(label="New project", callback=confirm_new_project, width=140)
    show_centered_window(NEW_PROJECT_CONFIRM_TAG)  # e55: dialogs open centered


def cancel_new_project(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """Modal Cancel: close the confirmation without touching the session (e15s01)."""
    if dpg.does_item_exist(NEW_PROJECT_CONFIRM_TAG):
        dpg.delete_item(NEW_PROJECT_CONFIRM_TAG)


def confirm_new_project(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """Modal New project: close the confirmation and reset the sequencer (e15s01).

    e37s01: a new project is unnamed — the reset also clears the current-path
    identity and records the pristine content as the saved baseline.
    """
    if dpg.does_item_exist(NEW_PROJECT_CONFIRM_TAG):
        dpg.delete_item(NEW_PROJECT_CONFIRM_TAG)
    apply_new_project()
    state.current_project_path = None
    _adopt_content_as_saved()
    refresh_window_title()


def request_new_project(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """VJmix > New project: reset immediately when clean; ask when dirty (e37s04)."""
    _sync_project_dirty()  # fresh dirt: the ~0.5 s cadence may lag a just-made edit
    if state.project_dirty:
        show_new_project_confirm()
    else:
        confirm_new_project()


def apply_boot_config() -> None:
    """Boot: apply the fallback theme, then restore the last project when flagged (e11s04)."""
    cfg = load_config()
    midi_init_from_config(cfg)  # e09: MIDI control mirrors (enabled, port, bindings)
    leap_init_from_config(cfg)  # e26: Leap Motion engine mirror (enabled flag)
    state.hover_help = hover_help_enabled(cfg)  # e76: display preference, not project content
    apply_hover_help(state.hover_help)  # drop the cards built at import when it is off
    if dpg.does_item_exist("help_hover_cb"):
        dpg.set_value("help_hover_cb", state.hover_help)
    linkengine.start_link_thread()  # e75: the Ableton Link session (optional dependency)
    if dpg.does_item_exist("midi_enable_cb"):
        # The MIDI window is built before the config loads, so the Enable checkbox
        # starts unchecked even when the engine is on — sync it (BUG-2026-08-29T102156).
        dpg.set_value("midi_enable_cb", state.midi_enabled)
    if dpg.does_item_exist("leap_enable_cb"):
        # e26: same boot-sync for the Leap Motion Enable checkbox (built before config).
        dpg.set_value("leap_enable_cb", state.leap_enabled)
    if dpg.does_item_exist("leap_viz_cb"):
        # e26s04: boot-sync the visualizer toggle (built before config) and fold
        # the panel when the persisted flag asks for it (engine must be on).
        dpg.set_value("leap_viz_cb", state.leap_visualizer)
        dpg.configure_item("leap_viz_cb", enabled=state.leap_enabled)
        if state.leap_enabled and state.leap_visualizer:
            _apply_leap_viz_layout(True)
    if dpg.does_item_exist("leap_restart_btn"):
        # BUG-2026-09-18T212400: recovery control, live only while the engine is on.
        dpg.configure_item("leap_restart_btn", enabled=state.leap_enabled)
    _apply_theme_config(cfg["theme"])
    if dpg.does_item_exist("cb_restore_project_boot"):
        dpg.set_value("cb_restore_project_boot", cfg["projects"]["restore_last_on_boot"])
    # e28s04: the Settings OSC fields prefill from the config (the Settings window
    # is built before the config loads, so the persisted endpoints land here).
    endpoints = _osc_endpoints_from_config(cfg)
    for tag, value in (
        ("viosc_ip", endpoints["client_ip"]),
        ("viosc_port", endpoints["client_port"]),
        ("listen_ip", endpoints["listen_ip"]),
        ("listen_port", endpoints["listen_port"]),
    ):
        if dpg.does_item_exist(tag):
            dpg.set_value(tag, value)
    restored = False
    if should_restore_last_project_on_boot(cfg):
        recent = recent_project_paths(cfg)
        if recent:
            project_state = load_project_file(recent[0])
            if project_state is not None:
                apply_project_state(project_state)
                state.current_project_path = recent[0]  # e37s01: boot-restored identity
                restored = True
    if not restored:
        # e68 (operator): a boot that restored NO project opens with NOTHING on screen — the
        # operator builds the workspace from the bar. (A restored project's own layout wins,
        # which is why this runs only when there was nothing to restore.)
        hide_all_workspace_windows()
    _adopt_content_as_saved()  # e37: the boot session (restored or pristine) is the clean baseline


def format_osc_log(history: list[str], level: str | None = None) -> str:
    """Render the Logs text newest-first, optionally filtered by LEVEL (e81).

    Every line is `[HH:MM:SS] LEVEL Context: text`, so the filter is a plain text
    predicate and the window stays ONE selectable block (a coloured item list could not be
    copied). Traffic is not logged at all: OSC/MIDI live in the I/O Monitor.
    """
    if level is None:
        return "\n".join(reversed(history))
    marker = f"] {level} "
    return "\n".join(line for line in reversed(history) if marker in line)


_LOG_LEVEL_LABELS: dict[str, str | None] = {
    "All levels": None,
    "Info": LOG_LEVEL_INFO,
    "Warnings": LOG_LEVEL_WARN,
    "Errors": LOG_LEVEL_ERROR,
}


def _refresh_log_text() -> None:
    """Write the Logs text under the active level filter (no-op while paused)."""
    if state.log_paused or not dpg.does_item_exist("osc_log_text"):
        return
    dpg.set_value("osc_log_text", format_osc_log(osc_log_history, state.log_level_filter))


def on_log_level(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """Level combo: show everything, or only warnings/errors (e81)."""
    state.log_level_filter = _LOG_LEVEL_LABELS.get(str(app_data or "All levels"))
    _refresh_log_text()


def toggle_log_pause(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """Freeze the VIEW; the history keeps filling and the button says which state it is in."""
    state.log_paused = not state.log_paused
    if dpg.does_item_exist("log_pause_btn"):
        dpg.set_item_label("log_pause_btn", "Resume" if state.log_paused else "Pause")
    if dpg.does_item_exist("log_status"):
        dpg.set_value("log_status", "paused" if state.log_paused else "")
    if not state.log_paused:
        _refresh_log_text()


def clear_logs(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """Empty the history and the view (the queue is drained by the main loop)."""
    osc_log_history.clear()
    if dpg.does_item_exist("osc_log_text"):
        dpg.set_value("osc_log_text", "")


def copy_logs(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """Put the visible (filtered) text on the clipboard."""
    dpg.set_clipboard_text(format_osc_log(osc_log_history, state.log_level_filter))


# --- GLOBAL VIMIX STATE ---
# e10s06: vjmix-side primary selection (target_id) — wins over the vimix current
# source for tile theming and for sequencer/monitor attachment.


# --- SEQUENCER STATE ---

# Beat/clock source selection (e05): the sequencer can follow the analyzed BPM, a band
# hitting 1.0, standard MIDI clock, or a manual BPM (numeric/TAP). Event-driven modes wake
# the sequencer on sync_event_beat instead of sleeping a fixed interval.
# One LED per beat source, shown next to its checkbox on the sequencer (e05)
BEAT_LED_TAGS = {
    BEAT_SOURCE_ANALYSIS: "led_analysis",
    BEAT_SOURCE_BAND1: "led_band1",
    BEAT_SOURCE_MIDI: "led_midi",
    BEAT_SOURCE_LINK: "led_link",  # e75
    BEAT_SOURCE_MANUAL: "led_manual",
}
BEAT_CHECKBOX_TAGS = {mode: f"cb_beat_{mode}" for mode in BEAT_SOURCE_LABELS}


# Sequencer data structure: one pristine track per row; the New-project reset
# (e15s01) reuses the same factories, so a fresh project equals a cold boot.

# --- AUDIO STATE ---
audio_stream: Any = None
# e10s08: timestamp of the last successful BPM detection — a stale/absent reading
# means current_bpm is not a real tempo (e.g. the manual value left over from a
# previous mode), so the sequencer must not advance on it.

# --- SPECTRUM ANALYZER (e04) ---
# 16 bars > 32: benchmarked lighter (~26% less compute per frame + half the draw calls);
# the FFT dominates either way, and 16 bars keep a clear view of the audible range.
# e10s09: perceptual spectrum — log-spaced bars over the musical range, level-
# independent AGC and peak-aware band values so every band responds to music.
# slow enough that quiet content between transients stays quiet (beat edges re-arm)
# A kick/bass transient lands around 0.6-0.9 after AGC+blend (measured); 0.6 fires
# on strong band transients while the edge semantics ignore sustained content.
BAND_RECT_COLORS = {
    1: ((255, 255, 0, 40), (255, 255, 0, 200)),  # yellow overlay
    2: ((0, 255, 255, 40), (0, 255, 255, 200)),  # cyan overlay
    3: ((255, 0, 255, 40), (255, 0, 255, 200)),  # magenta overlay
    4: ((0, 255, 128, 40), (0, 255, 128, 200)),  # green overlay (e71s01)
    5: ((255, 128, 0, 40), (255, 128, 0, 200)),  # orange overlay (e71s01)
}
# e71s02 (user request): each rectangle names itself — its number sits just inside the
# TOP-LEFT corner, in the band's edge colour and bold, so a colour never has to be
# translated back to a band by memory.
BAND_LABEL_PAD_PX = 2.0
BAND_LABEL_FONT_SIZE = 15
# e71s01: equal FIFTHS replace the equal thirds — the default of a NEW project only; a
# project saved with the thirds keeps its own ranges (they are persisted per project).
BAND_DEFAULT_RANGES = {
    1: (0.0, 0.2),
    2: (0.2, 0.4),
    3: (0.4, 0.6),
    4: (0.6, 0.8),
    5: (0.8, 1.0),
}

# Last computed spectrum bars + per-band state. All written on the main thread inside the
# queued spectrum task; future features read band1..band5 (0..1, 0 while disabled).

# e10s03: per-source list of texture tags (tex_<name>_<idx>)
# e10s04: per-source thumb cycle state {target_id: (current_index, last_switch_time)}
# e10s04: consecutive unanswered thumb requests per source -> failed tile state


def get_input_devices() -> list[str]:
    devices = sd.query_devices()
    inputs = [f"{i}: {d['name']}" for i, d in enumerate(devices) if d["max_input_channels"] > 0]
    return inputs if inputs else ["No input device found"]


def flash_led(tag: str) -> None:
    """Flash a beat LED green on the main thread, fading back after 100ms (HIGH-1)."""

    def _on():
        if dpg.does_item_exist(tag):
            dpg.configure_item(tag, fill=(80, 255, 120, 255))

    def _off():
        if dpg.does_item_exist(tag):
            dpg.configure_item(tag, fill=(50, 50, 50, 255))

    ui_task(_on)
    threading.Timer(0.1, lambda: ui_task(_off)).start()


def frame_sleep() -> float:
    """Main-loop sleep: full rate while animating, throttled while idle (perf e07 P1)."""
    if state.is_playing or state.is_audio_analyzing:
        return FRAME_SLEEP_ANIMATED
    if state.preview_active is not None and state.preview_playing:
        return FRAME_SLEEP_ANIMATED  # e38: a playing preview keeps full rate
    return FRAME_SLEEP_IDLE


# ==============================================================================
# SEQUENCER UI & CLIP ASSIGNMENT
# ==============================================================================


def assign_target_to_track(row: int, target_id: str | None, index: int = 0) -> None:
    """Point a sequencer row at a source; None is a no-op (e30s01, e67).

    The one assign choke point shared by the row clip-slot click / MIDI learn
    (via midi_action_track_assign, e10s06 selection-first) and the tile
    context-menu "Add to Step Sequencer" line items (the right-clicked
    source, e30s01): it writes the row's target id + OSC base address and
    swaps the clip-slot thumbnail.

    `index` says WHICH sequencer's row, and it defaults to A: applying a source to B's slot used to
    land on A's row, because the slot passed a bare row number (the operator's report, 2026-10-12).
    """
    if target_id is None:
        return
    tracks = state.sequencer(index)["tracks"]
    tracks[row]["target_id"] = target_id
    tracks[row]["base_address"] = f"/vimix/{target_id}"
    update_track_slot_ui(row, prefix=sequencer_prefix(index), index=index)


def midi_action_track_assign(row: int, index: int = 0) -> None:
    """Assign the currently selected media to a row of ONE sequencer (e10s06, e67)."""
    assign_target_to_track(row, get_current_target_id(), index)


def assign_clip_to_track(sender: Any, app_data: Any, user_data: Any) -> None:
    """The clip slot's own click: its user_data carries (index, row) (e67)."""
    index, row = int(user_data[0]), int(user_data[1])
    midi_action_track_assign(row, index)


def _bind_seq_zoom_fonts(index: int = 0, prefix: str = SEQ_TAG_PREFIX) -> None:
    """Bind the level's font to ONE instance's own labels (e66s03, e67s05).

    The cell's type label and the clip slot's button are the text a level resizes; nothing
    else in the grid carries one. A missing font (no asset on this machine) leaves them at
    the default, which is what the app did before there was a zoom at all.
    """
    font = _seq_zoom_fonts.get(state.sequencer(index)["zoom"])
    if font is None:
        return
    for row in range(NUM_TRACKS):
        slot_btn = f"{prefix}_slot_btn_{row}"
        if dpg.does_item_exist(slot_btn):
            dpg.bind_item_font(slot_btn, font)
        for col in range(NUM_STEPS):
            type_tag = f"{prefix}_type_{row}_{col}"
            if dpg.does_item_exist(type_tag):
                dpg.bind_item_font(type_tag, font)


def _slot_placeholder_label(target_id: str) -> str:
    """The Sequencer clip slot's label when the source has no texture (e69s01).

    A thumbnailable source with no frame yet keeps the waiting text (work in
    progress is not an impossibility). A source whose type can never produce a
    frame shows NAME + TYPE; with no `type` answer the NAME alone. The label is
    the ONLY change — the button keeps its tag, callback and MIDI assignment.
    """
    props = _source_props(target_id)
    if sourcekind.thumbnail_possible(props):
        return f"{target_id[:10]}\n(Waiting...)"
    name = _fit_non_thumb_line(target_id)
    kind = sourcekind.source_kind_of(props)
    return f"{name}\n{_fit_non_thumb_line(kind.label)}" if kind is not None else name


def update_track_slot_ui(row: int, prefix: str = SEQ_TAG_PREFIX, index: int = 0) -> None:
    layout = seqlayout.cell_layout(state.sequencer(index)["zoom"])  # e67s05: THIS instance's level
    slot_tag = f"{prefix}_slot_{row}"
    if not dpg.does_item_exist(slot_tag):
        return

    dpg.delete_item(slot_tag, children_only=True)
    target_id = state.sequencer(index)["tracks"][row].get("target_id")

    dpg.add_spacer(parent=slot_tag, height=layout.slot_button_top_spacer)
    if target_id:
        if target_id in thumbnails_data:
            tex_tag = thumbnails_data[target_id][0]
            dpg.add_image_button(
                texture_tag=tex_tag,
                width=layout.slot_button_width,
                height=layout.slot_button_height,
                indent=layout.slot_button_indent,
                tag=f"{prefix}_thumb_{row}",  # stable tag: the thumb cycle switches it (e10s05)
                callback=learnable(
                    assign_clip_to_track,
                    lambda ud: (MIDI_ACTION_TRACK_ASSIGN, {"row": ud[1], "seq": ud[0]}),
                ),
                user_data=(index, row),
                parent=slot_tag,
            )
        else:
            dpg.add_button(
                label=_slot_placeholder_label(target_id),
                width=layout.slot_button_width,
                height=layout.slot_button_height,
                indent=layout.slot_button_indent,
                tag=f"{prefix}_slot_btn_{row}",
                callback=learnable(
                    assign_clip_to_track,
                    lambda ud: (MIDI_ACTION_TRACK_ASSIGN, {"row": ud[1], "seq": ud[0]}),
                ),
                user_data=(index, row),
                parent=slot_tag,
            )
    else:
        dpg.add_button(
            label="ASSIGN\nCLIP",
            width=layout.slot_button_width,
            height=layout.slot_button_height,
            indent=layout.slot_button_indent,
            tag=f"{prefix}_slot_btn_{row}",
            callback=learnable(
                assign_clip_to_track,
                lambda ud: (MIDI_ACTION_TRACK_ASSIGN, {"row": ud[1], "seq": ud[0]}),
            ),
            user_data=(index, row),
            parent=slot_tag,
        )


def set_step_type(sender: Any, app_data: Any, user_data: Any) -> None:
    """Choose a step's type on ONE sequencer and rebuild THAT cell (e36s04, e67).

    The rebuild is the whole point of the visual: refreshing the wrong instance's cell is what made
    a choice made on B appear on A (the operator's report, 2026-10-12) — the WRITE was already going
    to the right track, the REBUILD was not.
    """
    index, row, col, step_type = user_data
    tracks = state.sequencer(index)["tracks"]
    tracks[row]["steps"][col]["type"] = step_type
    parsed = parse_step_token(step_type)
    if parsed is not None and parsed[0] == "flag":
        # e36s07: a new Flag step defaults to -1 (next)
        tracks[row]["steps"][col]["v1"] = -1.0
    update_step_ui(row, col, prefix=sequencer_prefix(index), index=index)


# e36s04: lazy 'More properties...' step picker (a modal built on demand, so
# the per-cell popups stay flat and the import-time menubar capture stays clean)
_STEP_PICKER_WIN = "step_picker_window"


def open_step_picker(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """Right-click a step cell > More properties...: pick any (property x mode)
    step of the catalog in a scrollable modal."""
    index, row, col = int(user_data[0]), int(user_data[1]), int(user_data[2])
    if dpg.does_item_exist(_STEP_PICKER_WIN):
        dpg.delete_item(_STEP_PICKER_WIN)
    with dpg.window(
        label="Step picker",
        tag=_STEP_PICKER_WIN,
        modal=True,
        width=320,
        height=420,
        no_resize=True,
    ):
        themed_text("More properties...", slot="text_dim")
        with dpg.child_window(height=330, border=True):
            for offering in more_step_offerings():
                for _mode, token, menu_label in offering["modes"]:
                    dpg.add_button(
                        label=f"{offering['label']} \u00b7 {menu_label}",
                        width=280,
                        callback=_step_picker_apply,
                        user_data=(index, row, col, token),
                    )
        with dpg.group(horizontal=True):
            dpg.add_button(label="Close", callback=_step_picker_close, width=280)
    show_centered_window(_STEP_PICKER_WIN)  # e55: dialogs open centered


def _step_picker_apply(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """Apply the picked step type and close the picker."""
    set_step_type(None, None, user_data)
    if dpg.does_item_exist(_STEP_PICKER_WIN):
        dpg.delete_item(_STEP_PICKER_WIN)


def _step_picker_close(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    if dpg.does_item_exist(_STEP_PICKER_WIN):
        dpg.delete_item(_STEP_PICKER_WIN)


def _highlight_copied_step(row: int, col: int, index: int = 0) -> None:
    """Show the copied-step highlight and clear any previous one, on ONE sequencer (e67).

    The position remembers the INSTANCE too: a single (row, col) could not tell A's cell from
    B's, so copying on B highlighted A's cell and the restore removed the wrong one.
    """
    if state.copied_step_pos is not None:
        previous_index, r, c = state.copied_step_pos
        update_step_theme(r, c, prefix=sequencer_prefix(previous_index), index=previous_index)
    state.copied_step_pos = (index, row, col)
    dpg.bind_item_theme(f"{sequencer_prefix(index)}_cell_{row}_{col}", theme_step_copied)


def copy_step(sender: Any, app_data: Any, user_data: Any) -> None:
    """Remember the full configuration of a step for later paste (e08)."""
    index, row, col = user_data
    state.active_step = (row, col)
    state.copied_step_data = copy.deepcopy(state.sequencer(index)["tracks"][row]["steps"][col])
    _highlight_copied_step(row, col, index)


def paste_step(sender: Any, app_data: Any, user_data: Any) -> None:
    """Apply the copied step configuration to the given step (e08)."""
    index, row, col = user_data
    state.active_step = (row, col)
    if state.copied_step_data is None:
        return
    tracks = state.sequencer(index)["tracks"]
    tracks[row]["steps"][col] = copy.deepcopy(state.copied_step_data)
    update_step_ui(row, col, prefix=sequencer_prefix(index), index=index)


def paste_step_to_row(sender: Any, app_data: Any, user_data: Any) -> None:
    """Apply the copied step configuration to every step of the sequencer row (e08)."""
    index, row = user_data[0], user_data[1]
    state.active_step = (row, 0)
    if state.copied_step_data is None:
        return
    tracks = state.sequencer(index)["tracks"]
    for c in range(NUM_STEPS):
        tracks[row]["steps"][c] = copy.deepcopy(state.copied_step_data)
        update_step_ui(row, c, prefix=sequencer_prefix(index), index=index)


def on_copy_shortcut(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """Ctrl+C: copy the last touched step (ignored while typing in an input)."""
    if _any_input_focused() or state.active_step is None:
        return
    # e67: `state.active_step` is A's cell (the shortcut target stays A's, e67s03), so the
    # instance is stated here rather than guessed by the callback.
    copy_step(None, None, (0, *state.active_step))


def on_paste_shortcut(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """Ctrl+V: paste into the last touched step (ignored while typing in an input)."""
    if _any_input_focused() or state.active_step is None:
        return
    paste_step(None, None, (0, *state.active_step))  # A's cell, as above


def _on_copy_key(sender: Any, app_data: Any, user_data: Any) -> None:
    """Key handler wrapper: DPG 2.3.1 handlers ignore modifiers, so gate on Ctrl here."""
    if dpg.is_key_down(dpg.mvKey_ModCtrl):
        on_copy_shortcut(sender, app_data, user_data)


def _on_paste_key(sender: Any, app_data: Any, user_data: Any) -> None:
    """Key handler wrapper: only paste when Ctrl is held."""
    if dpg.is_key_down(dpg.mvKey_ModCtrl):
        on_paste_shortcut(sender, app_data, user_data)


INPUT_WIDGET_TAGS = ("manual_bpm_input", "viosc_ip", "viosc_port", "listen_ip", "listen_port")


def _any_input_focused() -> bool:
    """True when a text/number input has focus, so Ctrl+C/V keeps working for typing."""
    return any(dpg.does_item_exist(tag) and dpg.is_item_focused(tag) for tag in INPUT_WIDGET_TAGS)


def _set_step_active(row: int, col: int, active: bool, index: int = 0) -> None:
    """Set a step's active state and refresh its visuals, on ONE sequencer (e67s03).

    Shared by the mouse and MIDI. `index` defaults to A, which is what keeps every binding learned
    before e67 addressing the sequencer it always addressed; the tag carries the instance's prefix,
    so a toggle on B touches B's cells and B's tracks and NOTHING of A.
    """
    prefix = sequencer_prefix(index)
    state.sequencer(index)["tracks"][row]["steps"][col]["active"] = active
    if index == 0:
        state.active_step = (row, col)  # the Ctrl+C/V target stays A's (e67: B has no shortcut yet)
    checkbox = f"{prefix}_cb_{row}_{col}"
    if dpg.does_item_exist(checkbox):
        dpg.set_value(checkbox, active)  # keep the cell checkbox in sync
    update_step_theme(row, col, prefix=prefix, index=index)
    refresh_binding_leds()  # e53s02


def set_step_row_active(row: int, active: bool, index: int = 0) -> None:
    """Enable/disable every step of one sequencer row (mouse + MIDI share this).

    e36s07: refreshes each cell's checkbox and theme in place; an out-of-range
    row is a no-op so a stale binding can never raise into the UI.
    """
    if row < 0 or row >= NUM_TRACKS:
        return
    prefix = sequencer_prefix(index)
    tracks = state.sequencer(index)["tracks"]
    for col in range(NUM_STEPS):
        tracks[row]["steps"][col]["active"] = bool(active)
        checkbox = f"{prefix}_cb_{row}_{col}"
        if dpg.does_item_exist(checkbox):
            dpg.set_value(checkbox, bool(active))
        update_step_theme(row, col, prefix=prefix, index=index)
    refresh_binding_leds()  # e53s02


def enable_step_row(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """Cell popup > Enable row: arm every step of the clicked row."""
    set_step_row_active(int(user_data[1]), True, int(user_data[0]))


def disable_step_row(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """Cell popup > Disable row: disarm every step of the clicked row."""
    set_step_row_active(int(user_data[1]), False, int(user_data[0]))


def toggle_step_active(sender: Any, app_data: Any, user_data: Any) -> None:
    index, row, col = user_data
    _set_step_active(row, col, bool(app_data), index)


def midi_action_seq_toggle(row: int, col: int, index: int = 0) -> None:
    """Toggle one step of ONE sequencer from a MIDI trigger (e09, e67s03).

    The instance defaults to A: a binding learned before e67 carries no `seq` param and must keep
    driving A. A pad on B's Launchpad names B and cannot reach an A step.
    """
    tracks = state.sequencer(index)["tracks"]
    _set_step_active(row, col, not tracks[row]["steps"][col]["active"], index)


def update_step_val(sender: Any, app_data: Any, user_data: Any) -> None:
    index, row, col, param_name = user_data
    tracks = state.sequencer(index)["tracks"]
    if param_name == "color":
        tracks[row]["steps"][col][param_name] = app_data[:3]
        # live-refresh the step square when a color is picked from the popup picker
        square_tag = f"{sequencer_prefix(index)}_color_square_{row}_{col}"
        if dpg.does_item_exist(square_tag):
            dpg.set_value(square_tag, dpg_color_rgba(app_data[:3]))
    else:
        tracks[row]["steps"][col][param_name] = app_data


def update_step_theme(
    row: int, col: int, is_head: bool = False, prefix: str = SEQ_TAG_PREFIX, index: int = 0
) -> None:
    # Runs on any thread: capture state here, apply the theme on the main thread.
    cell_tag = f"{prefix}_cell_{row}_{col}"
    is_active = state.sequencer(index)["tracks"][row]["steps"][col]["active"]
    grid_mirror_step(row, col, is_active, is_head, index)  # e14s02: LED mirror (thread-safe)
    ui_task(lambda: _apply_step_theme(cell_tag, is_active, is_head))


def _apply_step_theme(cell_tag: str, is_active: bool, is_head: bool) -> None:
    if not dpg.does_item_exist(cell_tag):
        return
    if is_head:
        dpg.bind_item_theme(cell_tag, theme_cell_play_on if is_active else theme_cell_play_off)
    else:
        dpg.bind_item_theme(cell_tag, theme_cell_on if is_active else theme_cell_off)


def _clear_step_cell(row: int, col: int, prefix: str = SEQ_TAG_PREFIX) -> None:
    """Delete a step cell's content so a rebuild cannot collide.

    DPG 2.3.1 quirk: ``delete_item(cell, children_only=True)`` does NOT release
    the aliases of items nested inside a ``dpg.popup`` — a second rebuild of
    the same cell then raises 'Alias already exists' (error 1000). Worse, the
    popup survives the deletion of its anchor group as an orphan, so it must be
    deleted EXPLICITLY by its own tag first; then every direct child item of
    the cell is removed.
    """
    cell_tag = f"{prefix}_cell_{row}_{col}"
    popup_tag = f"{prefix}_pop_{row}_{col}"
    if dpg.does_item_exist(popup_tag):
        dpg.delete_item(popup_tag)  # the orphaned popup keeps its aliases alive
    try:
        children = dpg.get_item_children(cell_tag, 1) or []
    except Exception:  # defensive: fall back to the container delete
        dpg.delete_item(cell_tag, children_only=True)
        return
    for child in children:
        if child is not None:
            dpg.delete_item(child)


def update_step_ui(row: int, col: int, prefix: str = SEQ_TAG_PREFIX, index: int = 0) -> None:
    layout = seqlayout.cell_layout(state.sequencer(index)["zoom"])  # e67s05: THIS instance's level
    cell_tag = f"{prefix}_cell_{row}_{col}"
    step_data = state.sequencer(index)["tracks"][row]["steps"][col]

    if not dpg.does_item_exist(cell_tag):
        return

    _clear_step_cell(row, col, prefix)

    with dpg.group(horizontal=True, parent=cell_tag):
        cb = dpg.add_checkbox(
            default_value=step_data["active"],
            tag=f"{prefix}_cb_{row}_{col}",
            callback=learnable(
                toggle_step_active,
                lambda ud: (MIDI_ACTION_SEQ_TOGGLE, {"row": ud[1], "col": ud[2], "seq": ud[0]}),
            ),
            user_data=(index, row, col),
        )
        display_type = step_data["type"] if step_data["type"] != "NONE" else ""
        dpg.add_text(
            textplay.step_label(display_type) if display_type else "",
            color=palette_rgba(state.active_palette["text"]),
            tag=f"{prefix}_type_{row}_{col}",
        )
        _text_color_bindings[f"{prefix}_type_{row}_{col}"] = "text"

        with dpg.popup(cb, mousebutton=dpg.mvMouseButton_Right, tag=f"{prefix}_pop_{row}_{col}"):
            dpg.add_menu_item(
                label="Empty", callback=set_step_type, user_data=(index, row, col, "NONE")
            )
            dpg.add_separator()
            dpg.add_menu_item(
                label="Alpha Value", callback=set_step_type, user_data=(index, row, col, "AlphaV")
            )
            dpg.add_menu_item(
                label="Alpha Random", callback=set_step_type, user_data=(index, row, col, "AlphaR")
            )
            dpg.add_menu_item(
                label="Alpha Fade", callback=set_step_type, user_data=(index, row, col, "AlphaF")
            )
            dpg.add_separator()
            dpg.add_menu_item(
                label="Color Value", callback=set_step_type, user_data=(index, row, col, "ColorV")
            )
            dpg.add_menu_item(
                label="Color Random", callback=set_step_type, user_data=(index, row, col, "ColorR")
            )
            dpg.add_separator()
            dpg.add_menu_item(
                label="Seek Random", callback=set_step_type, user_data=(index, row, col, "SeekR")
            )
            dpg.add_separator()
            # e60s01: the four progressive text reveal step types (the Text
            # window's modes) — one markup-aware /vimix/<target>/contents
            # fragment per firing, sent to the ROW's own source.
            for mode, label in textplay.REVEAL_MODES:
                dpg.add_menu_item(
                    label=f"Text: {label}",
                    callback=set_step_type,
                    user_data=(index, row, col, textplay.STEP_TOKEN_BY_MODE[mode]),
                )
            dpg.add_separator()
            # e36s04: the extended (property x mode) steps open in a lazy modal
            # picker — built on demand so the import-time menubar capture stays
            # clean (no nested menus inside the per-cell popups)
            dpg.add_menu_item(
                label="More properties...",
                callback=open_step_picker,
                user_data=(index, row, col),
            )
            dpg.add_separator()
            dpg.add_menu_item(label="Copy Step", callback=copy_step, user_data=(index, row, col))
            dpg.add_menu_item(label="Paste Step", callback=paste_step, user_data=(index, row, col))
            dpg.add_menu_item(
                label="Paste to Row", callback=paste_step_to_row, user_data=(index, row)
            )
            # e36s07: whole-row arm/disarm, kept at the bottom of the menu
            dpg.add_separator()
            dpg.add_menu_item(label="Enable row", callback=enable_step_row, user_data=(index, row))
            dpg.add_menu_item(
                label="Disable row", callback=disable_step_row, user_data=(index, row)
            )

    parsed_type = parse_step_token(step_data["type"])  # e36s04 (property, mode)
    if step_data["type"] == "AlphaV":
        dpg.add_spacer(parent=cell_tag, height=layout.spacer_mid)
        dpg.add_drag_float(
            parent=cell_tag,
            width=layout.drag_wide,
            default_value=step_data["v1"],
            min_value=0.0,
            max_value=1.0,
            speed=0.01,
            format="%.2f",
            callback=update_step_val,
            user_data=(index, row, col, "v1"),
        )

    elif step_data["type"] == "AlphaR":
        dpg.add_spacer(parent=cell_tag, height=layout.spacer_mid)
        dpg.add_text(
            f"{step_data['last_rand_v1']:.2f}",
            color=(150, 255, 150, 255),
            tag=f"{prefix}_rand_v1_{row}_{col}",
            parent=cell_tag,
            indent=layout.text_indent,
        )

    elif step_data["type"] == "AlphaF":
        dpg.add_spacer(parent=cell_tag, height=layout.spacer_short)
        # NEW UI: split into two compact rows to fit the intermediate messages
        with dpg.group(horizontal=True, parent=cell_tag):
            dpg.add_drag_float(
                width=layout.drag_narrow,
                default_value=step_data["v1"],
                min_value=0.0,
                max_value=1.0,
                speed=0.01,
                format="%.1f",
                callback=update_step_val,
                user_data=(index, row, col, "v1"),
            )
            dpg.add_drag_float(
                width=layout.drag_narrow,
                default_value=step_data["v2"],
                min_value=0.0,
                max_value=1.0,
                speed=0.01,
                format="%.1f",
                callback=update_step_val,
                user_data=(index, row, col, "v2"),
            )
        with dpg.group(horizontal=True, parent=cell_tag):
            dpg.add_drag_int(
                width=layout.drag_narrow,
                default_value=step_data["frames"],
                min_value=1,
                max_value=32,
                speed=1,
                format="%ds",
                callback=update_step_val,
                user_data=(index, row, col, "frames"),
            )
            dpg.add_drag_int(
                width=layout.drag_narrow,
                default_value=step_data["msgs"],
                min_value=1,
                max_value=32,
                speed=1,
                format="%dm",
                callback=update_step_val,
                user_data=(index, row, col, "msgs"),
            )

    elif step_data["type"] == "ColorV":
        dpg.add_spacer(parent=cell_tag, height=layout.spacer_tall)
        # color is stored normalized (0..1); color_button needs DPG-scale RGBA (0..255)
        btn_tag = f"{prefix}_color_square_{row}_{col}"
        dpg.add_color_button(
            parent=cell_tag,
            default_value=dpg_color_rgba(step_data["color"]),
            no_border=True,
            no_tooltip=True,
            width=layout.color_square,
            height=layout.color_square,
            indent=layout.color_square_indent,
            tag=btn_tag,
        )
        with dpg.popup(btn_tag, mousebutton=dpg.mvMouseButton_Left):
            dpg.add_color_picker(
                default_value=dpg_color_rgba(step_data["color"]),
                no_alpha=True,
                width=200,
                callback=update_step_val,
                user_data=(index, row, col, "color"),
            )

    elif step_data["type"] == "ColorR":
        dpg.add_spacer(parent=cell_tag, height=layout.spacer_tall)
        # last_rand_color is stored normalized (0..1); color_button needs DPG-scale RGBA
        dpg.add_color_button(
            parent=cell_tag,
            default_value=dpg_color_rgba(step_data["last_rand_color"]),
            no_border=True,
            no_tooltip=True,
            width=layout.color_square,
            height=layout.color_square,
            indent=layout.color_square_indent,
            tag=f"{prefix}_rand_color_{row}_{col}",
        )

    elif step_data["type"] == "SeekR":
        dpg.add_spacer(parent=cell_tag, height=layout.spacer_mid)
        dpg.add_text(
            f"{step_data.get('last_rand_seek', 0.0):.2f}",
            color=(150, 200, 255, 255),
            tag=f"{prefix}_rand_seek_{row}_{col}",
            parent=cell_tag,
            indent=layout.text_indent,
        )

    elif parsed_type is not None and not step_modes_covered_by_legacy(
        parsed_type[0], parsed_type[1]
    ):
        # e36s04: generic editor for the new (property, mode) steps
        prop, mode = parsed_type
        entry = _catalog_entry(prop)
        comp0 = entry["components"][0]
        lo, hi = float(comp0["min"]), float(comp0["max"])
        if mode == "value" and prop == "flag":
            # e36s07: Flag is a VALUE step carrying the target flag id
            # (-1 = next); ids are integers, so use an integer editor.
            dpg.add_spacer(parent=cell_tag, height=layout.spacer_mid)
            dpg.add_drag_int(
                parent=cell_tag,
                width=layout.drag_wide,
                default_value=int(step_data["v1"]),
                min_value=int(lo),
                max_value=int(hi),
                speed=1,
                format="%d",
                tag=f"{prefix}_flag_{row}_{col}",
                callback=update_step_val,
                user_data=(index, row, col, "v1"),
            )
        elif mode == "value" or (mode == "fire" and entry["family"] == catalog.FAMILY_TOGGLE):
            dpg.add_spacer(parent=cell_tag, height=layout.spacer_mid)
            dpg.add_drag_float(
                parent=cell_tag,
                width=layout.drag_wide,
                default_value=step_data["v1"],
                min_value=lo if mode == "value" else 0.0,
                max_value=hi if mode == "value" else 1.0,
                speed=0.01,
                format="%.2f",
                callback=update_step_val,
                user_data=(index, row, col, "v1"),
            )
        elif mode == "random":
            dpg.add_spacer(parent=cell_tag, height=layout.spacer_mid)
            dpg.add_text(
                f"{step_data.get('last_rand_v1', 0.0):.2f}",
                color=(150, 255, 150, 255),
                tag=f"{prefix}_rand_v1_{row}_{col}",
                parent=cell_tag,
                indent=layout.text_indent,
            )
        elif mode == "fade":
            dpg.add_spacer(parent=cell_tag, height=layout.spacer_short)
            with dpg.group(horizontal=True, parent=cell_tag):
                dpg.add_drag_float(
                    width=layout.drag_narrow,
                    default_value=step_data["v1"],
                    min_value=lo,
                    max_value=hi,
                    speed=0.01,
                    format="%.1f",
                    callback=update_step_val,
                    user_data=(index, row, col, "v1"),
                )
                dpg.add_drag_float(
                    width=layout.drag_narrow,
                    default_value=step_data["v2"],
                    min_value=lo,
                    max_value=hi,
                    speed=0.01,
                    format="%.1f",
                    callback=update_step_val,
                    user_data=(index, row, col, "v2"),
                )
            with dpg.group(horizontal=True, parent=cell_tag):
                dpg.add_drag_int(
                    width=layout.drag_narrow,
                    default_value=step_data["frames"],
                    min_value=1,
                    max_value=32,
                    speed=1,
                    format="%ds",
                    callback=update_step_val,
                    user_data=(index, row, col, "frames"),
                )
                dpg.add_drag_int(
                    width=layout.drag_narrow,
                    default_value=step_data["msgs"],
                    min_value=1,
                    max_value=32,
                    speed=1,
                    format="%dm",
                    callback=update_step_val,
                    user_data=(index, row, col, "msgs"),
                )
        elif mode == "cycle":
            dpg.add_spacer(parent=cell_tag, height=layout.spacer_mid)
            options = entry.get("options") or []
            raw = step_data.get("last_idx")
            text = "-"  # ASCII hyphen: a dash would render as a fallback glyph
            if raw is not None and 0 <= int(raw) < len(options):
                text = str(options[int(raw)])
            elif raw is not None:
                text = str(int(raw))
            dpg.add_text(
                text,
                color=(150, 200, 255, 255),
                tag=f"{prefix}_rand_v1_{row}_{col}",
                parent=cell_tag,
                indent=layout.text_indent,
            )
        else:  # mode == "fire" and trigger family: no value to edit
            dpg.add_spacer(parent=cell_tag, height=layout.spacer_mid)
            dpg.add_text(
                "fire",
                color=(200, 160, 120, 255),
                tag=f"{prefix}_rand_v1_{row}_{col}",
                parent=cell_tag,
                indent=layout.text_indent,
            )

    update_step_theme(row, col, is_head=(state.is_playing and state.current_step == col))


def on_tile_add_to_sequencer(
    sender: Any = None, app_data: Any = None, user_data: Any = None
) -> None:
    """Tile context menu > Add to Step Sequencer > line N (e30s01).

    Assigns the RIGHT-CLICKED tile source to the chosen row through the shared
    assign core — unlike the clip-slot click, no grid selection is needed: the
    menu carries the source explicitly (user_data = (target_id, row)).
    """
    target_id, row = user_data
    assign_target_to_track(int(row), target_id)


def on_tile_add_to_mapper_line(
    sender: Any = None, app_data: Any = None, user_data: Any = None
) -> None:
    """Add to Mapper > line N: re-point that mapper row onto the clicked source (e31s01).

    The row's CURRENT source is resolved at click time (mapper.row_targets(),
    first-appearance window order) — the popup can outlive mapper changes — and
    re-pointed onto the right-clicked source with the e29 retarget core; a stale
    index or a row already carrying the clicked source is a no-op (no refresh).
    """
    target_id, line_index = user_data
    rows = mapper.row_targets()
    if line_index >= len(rows):
        return
    if mapper.retarget_source(rows[line_index], target_id):
        refresh_mapper_ui()


# e74s13: the wiki's `blending` table (the catalog mirror), reused by the tile menu and
# the learn bar so the two can never drift; the index is the OSC argument the Mapper sends.
BLENDING_OPTIONS: tuple[str, ...] = tuple(catalog.PROPERTY_CATALOG["blending"]["options"])


def _add_tile_context_items(target_id: str) -> None:
    """The three right-click actions of a Mediagrid tile (e16, e30s01, e31s01).

    Must run inside a ``with dpg.window(popup=True, ...)`` block so the items
    are parented to that popup window. Every tile calls this — the actions
    must never drift apart. Menu: Regenerate Thumbnails, a separator, Add to
    Step Sequencer (a hover submenu with one 'line N' item per sequencer
    row), and Add to Mapper — a submenu whose FIRST item is 'new' (the
    classic mapping dialog) followed by one 'line N' item per mapper row that
    exists right now (window order; re-points the row onto this source).
    e33s04 (user rule): the popup carries NO learn markers — a binding must
    never anchor to a volatile source. The selection-relative actions live on
    the stable surfaces instead: mapper line markers on the Mapper rows and
    the regen marker in the sources-window learn bar. e47: the popup carries no
    MODE-arm item either — MIDI Learn is armed from the toolbar icon alone
    (ADR-midi-learn-entry-point).
    e38s03: the popup leads with "Preview..." for media sources that are not
    known images — a tile-anchored action like the others (no learn marker).
    """
    # e38s03: content preview of the source's file (video-only per user
    # decision; unknown-kind media classify on activation)
    props = _source_props(target_id)
    if _preview_offered(props):
        dpg.add_menu_item(label="Preview...", callback=start_source_preview, user_data=target_id)
        dpg.add_separator()
    if not props or props.get("media_kind") != "other":  # e57s02: nothing to regenerate
        dpg.add_menu_item(
            label="Regenerate Thumbnails",
            callback=regen_thumb_callback,
            user_data=target_id,
        )
        dpg.add_separator()
    with dpg.menu(label="Add to Step Sequencer"):
        for row in range(NUM_TRACKS):
            dpg.add_menu_item(
                label=f"line {row + 1}",  # 1-based human row label (e30s01)
                callback=on_tile_add_to_sequencer,
                user_data=(target_id, row),
            )
    with dpg.menu(label="Add to Mapper"):
        dpg.add_menu_item(
            label="new",
            callback=open_line_mapping_creator,
            user_data=target_id,
        )
        for line_index in range(len(mapper.row_targets())):
            dpg.add_menu_item(
                label=f"line {line_index + 1}",  # 1-based window row label (e31s01)
                callback=on_tile_add_to_mapper_line,
                user_data=(target_id, line_index),
            )
    # e33s04: after the three actions — a separator, then the per-source actions.
    dpg.add_separator()
    # e74s13: the blending mode of THIS source (the wiki's `blending` table, by index).
    # It leads the per-source block, before color correction, as the operator asked.
    current_blending = props.get("blending") if props else None
    try:
        current_blending_index = int(current_blending) if current_blending is not None else -1
    except (TypeError, ValueError):
        current_blending_index = -1
    with dpg.menu(label="Blending"):
        for mode_index, option in enumerate(BLENDING_OPTIONS):
            item = dpg.add_menu_item(
                label=option,
                check=True,
                callback=on_tile_set_blending,
                user_data=(target_id, mode_index),
            )
            if mode_index == current_blending_index:
                dpg.set_value(item, True)
    dpg.add_menu_item(
        label="Enable color correction",
        callback=on_tile_enable_color_correction,
        user_data=target_id,
    )
    # e56: Set current — make this source the active/current one in vimix
    dpg.add_menu_item(
        label="Set current",
        callback=on_tile_set_current,
        user_data=target_id,
    )


def on_tile_enable_color_correction(
    sender: Any = None, app_data: Any = None, user_data: Any = None
) -> None:
    """Tile context menu > Enable color correction: turn ON the source's CC block.

    The address /vimix/<target>/correction is the frozen-contract path the
    Mapper catalog already uses ('correction' 0..1, from the vimix wiki); the
    menu item arms it (1.0). The mouse path is tile-anchored; the MIDI twin is
    selection-relative (enable_correction) per the volatile-source rule.
    """
    target_id = user_data
    addr = f"/vimix/{target_id}/correction"
    osc_client.send_message(addr, 1.0)


def _current_target_for(name: Any) -> str:
    """The `/vimix/current/<x>` argument of a source: its INDEX when known, else the name.

    BUG-2026-10-16T233000: vimix's `/current` target resolves its attribute with
    `BaseToolkit::is_a_number` = `std::stoi`, which PARSES A LEADING NUMBER AND IGNORES
    THE REST, so `/vimix/current/07-Ritual-…` is taken as index 7 and selects a DIFFERENT
    source. The index vimix itself reported (the live table's value, see
    `_source_index_by_name`) has no such ambiguity.
    """
    return mapper.current_target_argument(str(name))


def on_tile_set_current(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """Tile context menu > Set current: make the source current in vimix.

    The address /vimix/<name> under the 'current' target is the no-arg trigger
    from the vimix wiki ("A source name : Set source by name as current"); the
    mouse path is tile-anchored, the MIDI twin is selection-relative
    (set_current) per the volatile-source rule.
    """
    target_id = user_data
    # BUG-2026-10-16T233000: the INDEX, never the raw name (a digit-leading name is read
    # by vimix as an index and selects a different source).
    addr = f"/vimix/current/{_current_target_for(target_id)}"
    osc_client.send_message(addr, [])


def on_tile_set_blending(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """Tile context menu > Blending > <mode>: set this source's blending (e74s13).

    `user_data` is `(target_id, index)`. The index form is the one the catalog and the
    Mapper already send (`/vimix/<target>/blending f <index>`), so the mouse and the
    Mapper use ONE representation of the wiki's `blending` table.
    """
    target_id, mode_index = user_data
    addr = f"/vimix/{target_id}/blending"
    osc_client.send_message(addr, float(mode_index))


def _tile_popup_tag(target_id: str) -> str:
    """Tag of the single right-click action popup window of a Mediagrid tile."""
    return f"tile_popup_{target_id}"


def _create_tile_popup(target_id: str) -> None:
    """One right-click action popup per tile, recreated on every grid rebuild.

    DPG binds ONE handler registry per item (bind_item_handler_registry replaces
    the previous one), so the old per-item ``dpg.popup`` registries were clobbered
    by the tile click registry on every rebuild and the right-click menu died.
    The fix: a single combined registry (left = select, right = show this popup
    window) — no registry conflict, the menu survives rebuilds.
    """
    popup_tag = _tile_popup_tag(target_id)
    if dpg.does_item_exist(popup_tag):
        dpg.delete_item(popup_tag)
    with dpg.window(popup=True, show=False, no_title_bar=True, autosize=True, tag=popup_tag):
        _add_tile_context_items(target_id)


def on_tile_context_click(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """Right-click on a Mediagrid tile: show the tile's action popup (e16).

    e32s01 (BUG-2026-09-04T180936): the popup is REBUILT at open time — its
    Add to Mapper submenu must list the mapper rows that exist right now, and
    mapper changes (add/delete/retarget) never rebuild the grid that used to
    own the popup. e27s02 (BUG-2026-09-03T175000): the rebuilt popup must be
    positioned at the cursor first — an unpositioned DPG popup window opens
    at the top-left of the viewport instead of under the tile. The
    client-space mouse (get_mouse_pos(local=False)) is the coordinate space
    set_item_pos uses.
    """
    target_id = user_data
    _create_tile_popup(target_id)  # fresh items: current mapper rows (e32s01)
    popup_tag = _tile_popup_tag(target_id)
    dpg.set_item_pos(popup_tag, dpg.get_mouse_pos(local=False))
    dpg.show_item(popup_tag)


def regen_thumb_callback(sender: Any, app_data: Any, user_data: Any) -> None:
    target_id = user_data
    if state.viosc_client:
        msg_addr = f"/viosc/regen_thumb/{target_id}"
        state.viosc_client.send_message(msg_addr, [])

    with dpg.mutex():
        tex_tags = thumbnails_data.pop(target_id, None)
        thumb_fail_count[target_id] = 0  # a manual retry clears the failure state (e10s04)
        thumb_frames_at_last_request[target_id] = 0  # e41s02: the walk restarts from frame 0
        if dpg.does_item_exist(f"img_{target_id}"):
            dpg.delete_item(f"img_{target_id}")
        for tex_tag in tex_tags or []:
            if dpg.does_item_exist(tex_tag):
                dpg.delete_item(tex_tag)

        container_tag = f"thumb_container_{target_id}"
        loading_tag = f"loading_txt_{target_id}"
        if dpg.does_item_exist(container_tag) and not dpg.does_item_exist(loading_tag):
            dpg.add_text(
                "  [ Rigenero... ]",
                color=(255, 200, 50, 255),
                tag=loading_tag,
                parent=container_tag,
            )
            click_reg_tag = media_tile_click_registry_tag(target_id)
            if dpg.does_item_exist(click_reg_tag):
                dpg.bind_item_handler_registry(loading_tag, click_reg_tag)


def apply_thumbnail_texture(name: str, idx: str, img_data: Any, w: int, h: int) -> None:
    """Apply one decoded thumbnail frame on the main thread (e10s03).

    Each reply index becomes its own static texture (tex_<name>_<idx>) and is
    appended to the per-source list in thumbnails_data. The FIRST texture of a
    source creates the tile image (and its regen popup); later indices only
    append to the list — no widget churn.
    """
    target_id = name
    tex_tag = f"tex_{target_id}_{idx}"
    img_tag = f"img_{target_id}"
    container_tag = f"thumb_container_{target_id}"
    loading_tag = f"loading_txt_{target_id}"

    if dpg.does_item_exist(tex_tag):
        dpg.delete_item(tex_tag)

    dpg.add_static_texture(
        width=w, height=h, default_value=img_data, tag=tex_tag, parent="texture_registry"
    )

    is_first = target_id not in thumbnails_data
    thumbs = thumbnails_data.setdefault(target_id, [])
    if tex_tag not in thumbs:
        thumbs.append(tex_tag)
    thumb_fail_count.pop(name, None)  # a reply clears the failure state (e10s04)

    # BUG-2026-09-03T212905: a Mapper row rendered before its source thumb
    # existed shows 'no thumb'; once the FIRST frame lands, rebuild the body
    # (like the sequencer slot below) so the image appears. Later frames only
    # append — the frame cycle animates them in place.
    if (
        is_first
        and dpg.does_item_exist(f"mapper_row_thumb_{target_id}")
        and not dpg.does_item_exist(f"mapper_row_img_{target_id}")
    ):
        refresh_mapper_ui()

    if is_first and not dpg.does_item_exist(img_tag) and dpg.does_item_exist(container_tag):
        if dpg.does_item_exist(loading_tag):
            dpg.delete_item(loading_tag)
        draw_tag = f"thumb_draw_{target_id}"
        badge_tag = f"tile_badge_bg_{target_id}"
        if dpg.does_item_exist(draw_tag):
            # the image goes BEHIND the index-badge overlay (before= insertion);
            # draw commands can't host handler registries, so the drawlist stays
            # the thumbnail's clickable surface (bound at tile build, e16).
            if dpg.does_item_exist(badge_tag):
                dpg.draw_image(
                    texture_tag=tex_tag,
                    pmin=(0, 0),
                    pmax=(115, 65),
                    parent=draw_tag,
                    before=badge_tag,
                    tag=img_tag,
                )
            else:
                dpg.draw_image(
                    texture_tag=tex_tag,
                    pmin=(0, 0),
                    pmax=(115, 65),
                    parent=draw_tag,
                    tag=img_tag,
                )
            click_reg_tag = media_tile_click_registry_tag(target_id)
            if dpg.does_item_exist(click_reg_tag):
                dpg.bind_item_handler_registry(draw_tag, click_reg_tag)

    for r, track in enumerate(tracks_data):
        if track.get("target_id") == target_id:
            update_track_slot_ui(r)


def advance_thumb_cycle(
    thumbs_count: int, now: float, state: tuple[int, float]
) -> tuple[int, float]:
    """Advance one source's thumb-cycle state on a fixed wall-clock cadence (pure).

    Returns the new (index, last_switch_time). Sources with fewer than two
    frames never cycle (images stay static); the anchor moves only when a
    switch actually happens, so time spent hidden does not fast-forward frames.
    """
    cur, last = state
    if thumbs_count < 2:
        return 0, last
    if now - last < THUMB_CYCLE_INTERVAL:
        return cur, last
    return (cur + 1) % thumbs_count, now


def _thumb_cycle_active() -> bool:
    """True while any thumbnail consumer window is visible (e10s05 gate).

    The Mediagrid, the sequencer and the Mapper each show per-source
    thumbnails; cycling runs while at least one of them is open so the animation
    follows the media wherever it is applied (e25s01: an open Mapper alone keeps
    the cycle running). The monitor player windows are gone (e40s04).
    """
    for tag in ("vimix_media_window", "sequencer_window", "mapper_window"):
        if dpg.does_item_exist(tag) and dpg.is_item_shown(tag):
            return True
    return False


def _apply_cycle_frame(target_id: str, tex_tag: str) -> None:
    """Switch every visible consumer of a source to the cycled frame (e10s05).

    The Mediagrid tile and every sequencer slot assigned to the source switch
    together on the same cadence; consumers whose widget is gone (window closed,
    slot unassigned) are skipped.
    """
    img_tag = f"img_{target_id}"
    if dpg.does_item_exist(img_tag):
        dpg.configure_item(img_tag, texture_tag=tex_tag)
    # e25s01: the Mapper row thumbnail cycles on the same cadence
    mapper_img_tag = f"mapper_row_img_{target_id}"
    if dpg.does_item_exist(mapper_img_tag):
        dpg.configure_item(mapper_img_tag, texture_tag=tex_tag)
    for r, track in enumerate(tracks_data):
        if track.get("target_id") == target_id:
            slot_tag = f"seq_thumb_{r}"
            if dpg.does_item_exist(slot_tag):
                dpg.configure_item(slot_tag, texture_tag=tex_tag)


def tick_thumb_cycle(now: float) -> None:
    """Advance thumb frames once per main-loop frame (e10s04 + e10s05).

    Gated: no cycling while every consumer window (Mediagrid, sequencer) is
    hidden or gone. Tiles with >=2 stored textures switch
    texture_tag via configure_item on the cadence; the switch reuses
    pre-loaded static textures (SPIKE-thumb-cycle: ~1.6 us per call).
    """
    if not _thumb_cycle_active():
        return
    for target_id, thumbs in list(thumbnails_data.items()):
        state = thumb_cycle_state.get(target_id, (0, now))
        new_state = advance_thumb_cycle(len(thumbs), now, state)
        thumb_cycle_state[target_id] = new_state
        if new_state[0] != state[0]:
            _apply_cycle_frame(target_id, thumbs[new_state[0]])


def _show_failed_tile_label(target_id: str) -> None:
    """Flip the tile's pending label to the failed state in place.

    The request loop runs on the main thread; when the unanswered-request
    counter crosses the threshold the existing "Loading..." draw-text label is
    re-worded and re-colored without waiting for a grid rebuild
    (BUG-2026-08-27T201742: the rebuild-only rendering kept the tile on
    "Loading..." forever).
    """
    loading_tag = f"loading_txt_{target_id}"
    if not dpg.does_item_exist(loading_tag):
        return  # no pending label (thumbnail already shown, or grid not built)
    dpg.configure_item(
        loading_tag,
        text=THUMB_FAIL_LABEL,
        color=palette_rgba(state.active_palette["warning"]),
    )


def _char_width_px() -> int:
    """Width of a single character in the live default font (e10s06, e20s01).

    The default font is monospace (ProggyClean, 7 px); measuring 'M' (the
    widest glyph) keeps the budget conservative if a proportional font is ever
    loaded. Falls back to a constant until the font atlas is built
    (get_text_size -> None). Used by the mapper caption alignment; the tile
    title uses its own fixed ProggyTiny budget (MEDIA_TITLE_CHARS_PER_LINE).
    """
    try:
        size = dpg.get_text_size("M")
        if size and size[0]:
            return max(1, int(size[0]))
    except Exception:
        pass
    return MEDIA_TITLE_CHAR_PX


def truncate_media_title(name: str) -> str:
    """Fit a media name into ONE Mediagrid title line, keeping BOTH ends (e79).

    The budget is the measured ProggyTiny capacity of the tile width
    (MEDIA_TITLE_CHARS_PER_LINE). A MIDDLE ellipsis keeps the prefix and the tail:
    source names usually share their head and differ at the end (`_001`, a take
    number, `.mp4`), which is exactly the part a head-only cut throws away —
    `07-Ritual-giardino_bidir_crf19_noaudio.mp4` reads `07-Ritual...audio.mp4`.

    The full name is never lost: the raw table, `target_id` and the title's hover
    card all carry it.
    """
    if not name:
        return name
    text = str(name)
    budget = MEDIA_TITLE_CHARS_PER_LINE * MEDIA_TITLE_MAX_LINES
    if len(text) <= budget:
        return text
    keep = max(0, budget - len(MEDIA_TITLE_ELLIPSIS))
    if keep == 0:
        return MEDIA_TITLE_ELLIPSIS
    head = keep - keep // 2
    tail = keep // 2
    return text[:head] + MEDIA_TITLE_ELLIPSIS + (text[-tail:] if tail else "")


def _fit_tile_line(text: str) -> str:
    """Cut a label to the tile's single line budget (DPG's draw_text is single-line)."""
    if not text:
        return text
    if len(text) <= MEDIA_TILE_NAME_CHARS:
        return text
    keep = max(0, MEDIA_TILE_NAME_CHARS - len(MEDIA_TITLE_ELLIPSIS))
    return text[:keep] + MEDIA_TITLE_ELLIPSIS


def _fit_non_thumb_line(text: str) -> str:
    """Cut a NAME/TYPE label to the non-thumbnailable slot budget (e69s01).

    Shared by the Mapper row slot and the Sequencer clip slot, so a long wiki type
    label ('Screen capture') cannot overflow either surface.
    """
    if not text:
        return text
    if len(text) <= NON_THUMB_LABEL_CHARS:
        return text
    keep = max(0, NON_THUMB_LABEL_CHARS - len(MEDIA_TITLE_ELLIPSIS))
    return text[:keep] + MEDIA_TITLE_ELLIPSIS


def _tile_placeholder_label(props: dict[str, Any], display_name: str) -> str:
    """A short single-line label for a tile without a thumbnail (e57s02, e68s01).

    e68s01: the source's OSC `type` answers WHAT it is, so the placeholder names the KIND
    ("Text", "Shader", "Clone", "Image sequence"…) instead of repeating the source name. An
    unknown type — an older viOSC or an older vimix — keeps the pre-e68 behaviour: the
    source name. vimix exposes no type before 0.9.2-41, which is why both paths exist.
    """
    kind = sourcekind.source_kind_of(props)
    return _fit_tile_line(kind.label if kind is not None else display_name)


def _tile_theme_for(idx: Any, target_id: str) -> Any:
    """Pick the Mediagrid tile theme (e10s06).

    The vjmix-side primary selection uses the green selection theme; the vimix
    current source alone uses the lighter non-green theme; everything else is
    plain. The VJmix selection wins when both point at the same source.
    """
    if target_id == state.vjmix_selected_source:
        return theme_selected_clip
    if str(idx) == str(state.global_vimix_state.get("current_source")):
        return theme_vimix_current_clip
    return theme_normal_clip


# e83: the compact tile status. The badge cache avoids re-colored rectangles (the
# only value that changes a badge is its own flag), and the seek cache keeps the
# last REAL answer so the bar can be dead-reckoned between the 1 s polls.
_tile_badge_state: dict[tuple[str, str], bool] = {}
_tile_blend_state: dict[str, int | None] = {}
_tile_spacer_state: dict[str, tuple[int, int]] = {}
_tile_seek_state: dict[str, dict[str, float]] = {}
_tile_status_tick_at = 0.0
# e83: a DPG call the installed build rejects must cost the NICETY, never the grid.
# One message per failing call kind (the operator's window went half-built once).
_tile_status_failures: set[str] = set()


def _tile_status_call(label: str, call: Callable[..., Any]) -> Any:
    """Run one optional tile-status DPG call; log the first failure of each kind."""
    try:
        return call()
    except Exception as e:
        if label not in _tile_status_failures:
            _tile_status_failures.add(label)
            log_error("Tile status", f"{label}: {e}")
        return None


def _add_tile_flag_text(prop: str, letter: str, target_id: str) -> None:
    """One P/C/L letter on the tile's status line (e83)."""
    tag = f"tile_badge_{prop}_{target_id}"
    dpg.add_text(letter, color=palette_rgba(state.active_palette["text_dim"]), tag=tag)
    if _tile_title_font is not None:
        dpg.bind_item_font(tag, _tile_title_font)


def _add_tile_status_text(tag: str) -> None:
    """One value text of the tile's status line (e83)."""
    themed_text("", slot="text_dim", tag=tag)
    if _tile_title_font is not None:
        dpg.bind_item_font(tag, _tile_title_font)


def tile_line_slack(depth_text: str, speed_text: str) -> tuple[int, int]:
    """The two spacer widths that SPREAD the status line across the tile (e83).

    The items are P C L, a spacer, the depth, a spacer and the speed. The tile font
    is monospace and the app already knows its capacity (MEDIA_TITLE_CHARS_PER_LINE
    inside MEDIA_TITLE_WRAP), so the widths are arithmetic, not measurement: a
    per-frame dpg.get_text_size would also answer only after the first frame.
    """
    char_w = MEDIA_TITLE_WRAP / MEDIA_TITLE_CHARS_PER_LINE
    items = 7  # 3 letters + 2 spacers + depth + speed
    gaps = (items - 1) * TILE_STATUS_GAP
    used = (3 + len(depth_text) + len(speed_text)) * char_w + gaps
    slack = max(0, int(MEDIA_TITLE_WRAP - used))
    return slack // 2, slack - slack // 2


def _tile_status_targets() -> list[str]:
    """The tile ids the status strip knows (pruned with the rest of the caches)."""
    return list(_tile_seek_state)


def _set_tile_status(target_id: str, props: dict[str, Any], now: float | None = None) -> None:
    """Badges, seek bar and the one-line strip of ONE tile (e83).

    Every write is cached (a source at rest costs no dpg call). The seek baseline
    moves ONLY on a real answer, so the bar advances on the dead-reckoned value
    between the state tier's 1 s refreshes.
    """
    clock = time.monotonic() if now is None else now
    seek = props.get("seek")
    if isinstance(seek, (int, float)) and not isinstance(seek, bool):
        state_entry = _tile_seek_state.get(target_id) or {}
        real = state_entry.get("real")
        if real is None or abs(float(seek) - real) > 1e-4:
            _tile_seek_state[target_id] = {
                "real": float(seek),
                "stamp": clock,
                "speed": float(props.get("speed") or 1.0),
                "play": 1.0 if sourcestatus.is_on(props.get("play")) else 0.0,
                # the clip length: seek is a FRACTION, so the dead reckoning needs
                # it. Unknown -> 0 -> the bar stays on the last real value.
                "duration": float(props.get("duration_s") or 0.0),
            }
    for prop, _letter in TILE_STATUS_BADGES:
        on = sourcestatus.is_on(props.get(prop))
        if _tile_badge_state.get((target_id, prop)) is on:
            continue
        _tile_badge_state[(target_id, prop)] = on
        tag = f"tile_badge_{prop}_{target_id}"
        if dpg.does_item_exist(tag):
            dpg.configure_item(
                tag, color=palette_rgba(state.active_palette["accent" if on else "text_dim"])
            )
    blend = sourcestatus.blending_index(props.get("blending"))
    if _tile_blend_state.get(target_id) != blend:
        _tile_blend_state[target_id] = blend
        uv = sourcestatus.blending_uv(blend)
        icon_tag = f"tile_blend_icon_{target_id}"
        if uv is not None and dpg.does_item_exist(icon_tag):
            _tile_status_call(
                "blend uv",
                lambda t=icon_tag, u=uv: dpg.configure_item(
                    t, uv_min=list(u[0]), uv_max=list(u[1])
                ),
            )
    _set_media_cell(f"tile_seek_bar_{target_id}", _tile_seek_fraction(target_id, clock))
    depth_text = sourcestatus.depth_text(props.get("depth")) or ""
    speed_text = sourcestatus.speed_text(props.get("speed")) or ""
    _set_media_cell(f"tile_status_depth_{target_id}", depth_text)
    _set_media_cell(f"tile_status_speed_{target_id}", speed_text)
    slack = tile_line_slack(depth_text, speed_text)
    if _tile_spacer_state.get(target_id) != slack:
        _tile_spacer_state[target_id] = slack
        _tile_status_call(
            "line spacers",
            lambda t=target_id, w=slack: (
                dpg.configure_item(f"tile_spacer_a_{t}", width=w[0]),
                dpg.configure_item(f"tile_spacer_b_{t}", width=w[1]),
            ),
        )


def _tile_seek_fraction(target_id: str, now: float) -> float:
    """The dead-reckoned seek fraction of one tile (e83)."""
    entry = _tile_seek_state.get(target_id)
    if not entry:
        return 0.0
    return sourcestatus.seek_now(
        entry.get("real"),
        entry.get("speed"),
        entry.get("play"),
        now - entry.get("stamp", now),
        entry.get("duration"),
    )


def tick_tile_status(now: float | None = None) -> None:
    """Advance the seek bars between UI passes (e83).

    The state tier answers seek once a second; only the BARS are rewritten here
    (the text and the badges change at the poll cadence), throttled at
    TILE_STATUS_TICK_S so a playing tile costs 10 set_value/s.
    """
    global _tile_status_tick_at
    clock = time.monotonic() if now is None else now
    if not _tile_seek_state or clock - _tile_status_tick_at < TILE_STATUS_TICK_S:
        return
    _tile_status_tick_at = clock
    for target_id in _tile_status_targets():
        tag = f"tile_seek_bar_{target_id}"
        if dpg.does_item_exist(tag):
            _set_media_cell(tag, _tile_seek_fraction(target_id, clock))


def refresh_tile_selection_themes() -> None:
    """Re-apply the selection themes to every Mediagrid tile without a rebuild.

    Called from the tile click handler: the VJmix selection changes without
    touching the grid signature, so the theme binding loop re-runs on the
    existing tiles instead of rebuilding them.
    """
    for idx, props in state.global_vimix_state.get("sources", {}).items():
        name = props.get("name")
        target_id = str(name) if name else str(idx)
        tile_tag = f"tile_{target_id}"
        if dpg.does_item_exist(tile_tag):
            dpg.bind_item_theme(tile_tag, _tile_theme_for(idx, target_id))


def on_media_tile_click(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """Select a media from the Mediagrid — the vjmix-side primary selection (e10s06)."""
    select_media_source(user_data)


def on_tile_alpha_slider(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """Drag a tile's thin vertical alpha slider: set the source alpha (0..1).

    The address /vimix/<target>/alpha is the same frozen-contract path the
    sequencer (AlphaV/R/F) and the mapper use — no new OSC surface. The next
    viOSC state push renders the new value back into the slider.
    """
    target_id = user_data
    alpha = float(app_data)
    addr = f"/vimix/{target_id}/alpha"
    osc_client.send_message(addr, alpha)


def on_tile_stop_click(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """e74s12: the tile STOP — park the source by sending a NEGATIVE alpha.

    vimix maps alpha<0 to a mixing distance |alpha|+1 and DEACTIVATES the source when
    that distance is not below the session's activationThreshold: the media player is
    disabled, so the video STOPS instead of playing invisibly at alpha 0. Dragging the
    slider back into 0..1 reactivates it.
    """
    target_id = user_data
    addr = f"/vimix/{target_id}/alpha"
    osc_client.send_message(addr, MEDIA_ALPHA_PARKED)
    # e74s12b: the slider drops to 0 AT ONCE (the state push would lag up to the viOSC
    # poll) and the STOP reads as armed straight away.
    _set_media_cell(f"tile_alpha_{target_id}", 0.0)
    _set_tile_stop_theme(target_id, True)


# e74s12: the last parked state bound per tile, so the STOP's theme is re-bound only on a
# real change (perf e07: a push that changes nothing issues no dpg call).
_tile_stop_parked: dict[str, bool] = {}


def _set_tile_stop_theme(target_id: str, parked: bool) -> None:
    """Bind the STOP's PARKED theme only when the parked state changed (e74s12)."""
    if _tile_stop_parked.get(target_id) == parked:
        return
    _tile_stop_parked[target_id] = parked
    tag = f"tile_stop_{target_id}"
    if dpg.does_item_exist(tag):
        dpg.bind_item_theme(tag, theme_stop_button_on if parked else theme_stop_button)


def request_missing_thumbnails(now: float) -> None:
    """Request the frame a source still lacks, ONE index at a time (e10s04, e41s02).

    Each sent-but-unanswered request bumps the source's fail counter; crossing
    the threshold fires ONE regen retry and the tile flips to the failed label
    (rendered by update_vimix_sources_ui). A successful reply clears the counter.

    e41s02: viOSC answers a digit index with ONE blob, so the frame indices are
    walked one per throttle cycle. Asking for `all` made the daemon emit three
    JPEG blobs back-to-back — a multi-fragment burst on a transport that never
    retransmits. ``next_thumb_frame_index`` bounds the walk and stops it once the
    daemon stops answering (an image source has a single frame).
    """
    if not state.viosc_client:
        return
    for idx, props in state.global_vimix_state.get("sources", {}).items():
        name = props.get("name")
        target_id = str(name) if name else str(idx)
        # e69s01: ONE predicate, shared with the Mapper/Sequencer labels, so the
        # request gate and the UI can never disagree about "no frame can arrive".
        if not sourcekind.thumbnail_possible(props):
            continue
        received = len(thumbnails_data.get(target_id, ()))
        frame_index = next_thumb_frame_index(
            received, thumb_frames_at_last_request.get(target_id, 0)
        )
        if frame_index is None:
            continue
        last_thumb = request_timestamps.get(f"thumb_{target_id}", 0)
        if now - last_thumb <= THUMB_REQUEST_INTERVAL:
            continue
        if state.thumb_http_supported is False:
            request_thumbnail_over_osc(target_id, frame_index)
        else:
            state.thumb_fetch_queue.put((target_id, frame_index))
        request_timestamps[f"thumb_{target_id}"] = now
        if received == 0:
            # nothing has arrived yet: keep the e10s04 retry/failure accounting
            thumb_fail_count[target_id] = thumb_fail_count.get(target_id, 0) + 1
            if thumb_fail_count[target_id] == THUMB_FAIL_THRESHOLD:
                regen_addr = f"/viosc/regen_thumb/{target_id}"
                state.viosc_client.send_message(regen_addr, [])
                _show_failed_tile_label(target_id)
        else:
            thumb_frames_at_last_request[target_id] = received


def _prune_state_consumers(live_ids: set[str], known_ids: set[str]) -> None:
    """Drop cached UI that belongs to sources which no longer exist (L-1).

    The caller MUST pass a NON-EMPTY ``live_ids``: an empty state table means
    "viOSC has not synced yet" (or, under pairing, "not authenticated yet"),
    never "every source was removed". ``known_ids`` is every name the table has
    ever reported, so a Mapping whose target was never seen is not pruned on a
    transient table (BUG-2026-09-13T231500).
    """
    for target_id in list(thumbnails_data):
        if target_id.startswith(FS_THUMB_PREFIX):
            continue  # e43s03: the File Manager's per-file textures are not sources
        if target_id not in live_ids:
            tex_tags = thumbnails_data.pop(target_id)
            for tex_tag in tex_tags:
                if dpg.does_item_exist(tex_tag):
                    dpg.delete_item(tex_tag)
            click_reg_tag = media_tile_click_registry_tag(target_id)
            if dpg.does_item_exist(click_reg_tag):
                dpg.delete_item(click_reg_tag)  # stale click registry must not linger
            popup_tag = _tile_popup_tag(target_id)
            if dpg.does_item_exist(popup_tag):
                dpg.delete_item(popup_tag)  # stale action popup must not linger (e16)
    for key in list(request_timestamps):
        if key.startswith("thumb_"):
            target_id = key[len("thumb_") :]
            if target_id not in live_ids:
                request_timestamps.pop(key)
    for target_id in list(thumb_fail_count):
        if target_id not in live_ids:
            thumb_fail_count.pop(target_id)
    for target_id in list(_tile_stop_parked):
        if target_id not in live_ids:
            _tile_stop_parked.pop(target_id)  # e74s12: the STOP theme cache follows churn
    for target_id in list(thumb_frames_at_last_request):
        if target_id not in live_ids:
            thumb_frames_at_last_request.pop(target_id)
    for target_id in list(_tile_seek_state):
        if target_id not in live_ids:
            _tile_seek_state.pop(target_id)  # e83: the seek bar follows the source away
    mapper.prune_anchors(live_ids)  # e36s06: the anchor cache follows source churn
    removed_mappings = mapper.prune_mappings(live_ids, known_ids)
    if removed_mappings:
        for removed in removed_mappings:
            _drop_mapping_editor_and_runs(int(removed["id"]))  # e35s05
        refresh_mapper_ui()  # a vanished source disables its Mappings (e45s02)
    if state.vjmix_selected_source is not None and state.vjmix_selected_source not in live_ids:
        state.vjmix_selected_source = None  # a pruned source can't stay selected (e10s06)
    if state.preview_active is not None and state.preview_active not in live_ids:
        close_source_preview()  # a pruned source can't keep a preview stream (e38s03)


def update_vimix_sources_ui(json_string: str) -> None:
    try:
        payload = json.loads(json_string)
        if not isinstance(payload, dict):
            raise ValueError("replydata payload is not a JSON object")
        sources = payload.get("sources", {})
        if sources is None:
            sources = {}
        if not isinstance(sources, dict):
            raise ValueError("replydata 'sources' is not an object")
        # Drop malformed entries so a single bad source can't crash the UI/main loop
        sources = {k: v for k, v in sources.items() if isinstance(v, dict)}
        state.global_vimix_state["current_source"] = payload.get("current_source")
        state.global_vimix_state["sources"] = sources
        revision = payload.get("rev")
        if isinstance(revision, int):
            state.event_rev = max(state.event_rev, revision)  # e82s04: the ETag/gap anchor
        refresh_text_source_options()  # e59s02: the picker follows the live table
        refresh_shader_source_options()  # e61s03: the Shader picker follows it too

        # e36s06: seed anchored vector caches (color/corner) from the live feed
        # so component mappings start from real values instead of neutral ones.
        mapper.seed_anchors_from_live_state(sources)

        # L-1: prune cached state for sources that no longer exist (main thread only),
        # so thumbnails_data / request_timestamps / registry textures do not grow across churn.
        live_ids = set()
        for k, props in sources.items():
            name = props.get("name")
            live_ids.add(str(name) if name else str(k))
        # BUG-2026-09-13T231500: an EMPTY state table is not evidence that every
        # source is gone (viOSC holds no sources until its first sync; under
        # pairing the table stays empty until the peer authenticates), and a
        # table that never listed a target is not evidence either — only a name
        # seen before and now absent removes a Mapping.
        if live_ids:
            _apply_pending_remap(live_ids)  # e45s02: before the orphan pass
            _prune_state_consumers(live_ids, state.known_sources)
            state.known_sources |= live_ids

        current_source = state.global_vimix_state["current_source"]
        data_dict = state.global_vimix_state["sources"]

        # grid display order = numeric source 'index' (fallback: dict key); the
        # shared key feeds both the grid build and the source-browsing cycle
        sorted_keys = sorted(data_dict.keys(), key=lambda k: _source_numeric_sort_key(data_dict, k))
        # e82s09: the CURRENT source is not structural. It changes one theme, and
        # rebuilding the grid to recolor two tiles was the visible glitch; a change
        # now rebinds the themes in place, the same path the VJmix click uses.
        if current_source != state.last_current_source:
            state.last_current_source = current_source
            refresh_tile_selection_themes()
        current_signature = grid_signature(data_dict, sorted_keys, state.last_num_cols)

        if current_signature != state.last_ui_signature:
            # every rebuild recreates the widgets from scratch (defaults): the per-cell
            # value cache must not skip writes for the freshly created cells (perf e07 P0)
            _media_cell_cache.clear()
            _RAW_TEXT_LAST.clear()  # e82s08: the rebuilt cells are all new
            _RAW_FLASH_UNTIL.clear()
            _tile_badge_state.clear()  # e83: the badges are new items too
            _tile_blend_state.clear()
            _tile_spacer_state.clear()
            if dpg.does_item_exist("vimix_table"):
                dpg.delete_item("vimix_table")
            if dpg.does_item_exist("media_grid"):
                dpg.delete_item("media_grid")

            t_raw = dpg.add_table(
                parent=SOURCES_DATA_GROUP_TAG,
                tag="vimix_table",
                header_row=True,
                borders_innerH=True,
                borders_innerV=True,
                row_background=True,
                # e74s01b: columns size to their CONTENT, so a long uri/name is never
                # clipped; scrollX then grows the bottom horizontal scrollbar.
                policy=dpg.mvTable_SizingFixedFit,
                scrollX=True,
                scrollY=True,
                freeze_columns=2,
                # e74s06: fit the window height so the bottom horizontal scrollbar is
                # always visible, whatever the window size.
                height=-1,
            )
            for prop in ALL_PROPERTIES:
                dpg.add_table_column(label=prop.capitalize(), parent=t_raw)

            for idx in sorted_keys:
                r_id = dpg.add_table_row(parent=t_raw)
                props_i = data_dict[idx]
                for prop in ALL_PROPERTIES:
                    tag_name = f"raw_{idx}_{prop}"
                    if dpg.does_item_exist(tag_name):
                        dpg.delete_item(tag_name)
                    if dpg.does_alias_exist(tag_name):
                        dpg.remove_alias(tag_name)
                    val = props_i.get(prop)
                    if prop == "index" and val is None:
                        val = idx
                    val_str = osc.raw_cell_text(prop, val, state.asked_props)
                    _note_raw_change(tag_name, val_str)
                    themed_text(val_str, slot="text", parent=r_id, tag=tag_name)

            num_cols = state.last_num_cols
            t_grid = dpg.add_table(
                parent="vimix_media_group",
                tag="media_grid",
                header_row=False,
                borders_innerH=False,
                borders_innerV=False,
                policy=dpg.mvTable_SizingFixedFit,
            )
            # e74s05: CellPadding 1,1 — the tiles sit next to each other, not apart.
            dpg.bind_item_theme("media_grid", theme_compact_table)
            for _ in range(num_cols):
                dpg.add_table_column(parent=t_grid)

            for i in range(0, len(sorted_keys), num_cols):
                row_indices = sorted_keys[i : i + num_cols]
                r_id = dpg.add_table_row(parent=t_grid)
                for idx in row_indices:
                    name = data_dict[idx].get("name")
                    target_id = str(name) if name else str(idx)
                    tile_tag = f"tile_{target_id}"

                    if dpg.does_item_exist(tile_tag):
                        dpg.delete_item(tile_tag)
                    cw = dpg.add_child_window(
                        parent=r_id,
                        width=135,
                        height=MEDIA_TILE_H,
                        border=True,
                        no_scrollbar=True,
                        tag=tile_tag,
                    )
                    click_reg_tag = media_tile_click_registry_tag(target_id)
                    if dpg.does_item_exist(click_reg_tag):
                        dpg.delete_item(click_reg_tag)  # a rebuild must not leak registries
                    with dpg.item_handler_registry(tag=click_reg_tag):
                        # DPG 2.3.1 calls item-handler callbacks with co_argcount
                        # args (Python 3.13 counts defaults -> 4 args, extras are
                        # None), so the target id must be captured, never received.
                        dpg.add_item_clicked_handler(
                            0,  # left click selects the media (e10s06)
                            callback=lambda *_, t=target_id: on_media_tile_click(None, None, t),
                        )
                        dpg.add_item_clicked_handler(
                            1,  # right click opens the tile action popup (e16)
                            callback=lambda *_, t=target_id: on_tile_context_click(None, None, t),
                        )
                    # e16: ONE popup window per tile, opened by the right-click
                    # handler above. The old per-item dpg.popup registries were
                    # replaced by the click registry on every rebuild (DPG binds a
                    # single registry per item) — the menu silently died. The
                    # combined registry + shared popup survives rebuilds.
                    _create_tile_popup(target_id)

                    # e79: ONE title line. The name is cut in the MIDDLE, and the FULL name
                    # rides a hover card, so nothing is lost when the cut happens.
                    display_name = str(name) if name else f"Idx: {idx}"
                    title_tag = f"tile_title_{target_id}"
                    if dpg.does_item_exist(title_tag):
                        dpg.delete_item(title_tag)
                    dpg.add_text(
                        "---",
                        parent=cw,
                        wrap=MEDIA_TITLE_WRAP,
                        color=palette_rgba(state.active_palette["text_bright"]),
                        tag=title_tag,
                    )
                    _text_color_bindings[title_tag] = "text_bright"
                    if _tile_title_font is not None:
                        dpg.bind_item_font(title_tag, _tile_title_font)
                    if truncate_media_title(display_name) != display_name:
                        help_tooltip(
                            title_tag,
                            "sources.tile_name",
                            card=helpprose.HelpEntry("Source name", display_name),
                        )
                    dpg.add_spacer(parent=cw, height=MEDIA_TITLE_GAP)
                    container_tag = f"thumb_container_{target_id}"
                    if dpg.does_item_exist(container_tag):
                        dpg.delete_item(container_tag)

                    # Compact media row: the thumbnail (with the index badge overlaid
                    # on its top-left corner) plus a thin vertical alpha slider, same
                    # height as the thumbnail — the badge+alpha line under the photo is
                    # gone, so the tile is shorter and the grid denser. horizontal_spacing=0
                    # keeps the slider flush against the image's right edge.
                    with dpg.group(horizontal=True, parent=cw, horizontal_spacing=0):
                        g_id = dpg.add_group(tag=container_tag)
                        draw_tag = f"thumb_draw_{target_id}"
                        img_tag = f"img_{target_id}"
                        loading_tag = None  # set only in the no-thumbs branch below
                        with dpg.drawlist(width=115, height=65, parent=g_id, tag=draw_tag):
                            if target_id in thumbnails_data:
                                tex_tag = thumbnails_data[target_id][0]
                                if dpg.does_item_exist(img_tag):
                                    dpg.delete_item(img_tag)
                                dpg.draw_image(
                                    texture_tag=tex_tag,
                                    pmin=(0, 0),
                                    pmax=(115, 65),
                                    parent=draw_tag,
                                    tag=img_tag,
                                )
                            # index badge overlay: top-left corner of the thumbnail (drawn
                            # after the image so it always sits on top)
                            index_tag = f"tile_index_{target_id}"
                            themed_draw_rectangle(
                                (2, 2),
                                (2 + MEDIA_BADGE_W, 2 + MEDIA_BADGE_H),
                                slot="badge_bg",
                                color=(0, 0, 0, 0),
                                rounding=2,
                                tag=f"tile_badge_bg_{target_id}",
                            )
                            idx_val = data_dict[idx].get("index")
                            idx_str = str(idx_val) if idx_val is not None else str(idx)
                            # e83: the badge is smaller (MEDIA_BADGE_W/H), so the number
                            # sits closer to its corner.
                            dpg.draw_text(
                                (2 + 4, 2 + 1),
                                idx_str,
                                color=palette_rgba(state.active_palette["text_bright"]),
                                size=13,
                                tag=index_tag,
                            )
                            _text_color_bindings[index_tag] = "text_bright"
                            # e83: the blending mode is an ICON (vimix's own glyph).
                            # P/C/L moved to the line under the seek bar (second pass),
                            # so the thumbnail keeps ONE badge and it can be bigger.
                            blend_x = 115 - TILE_BLEND_BADGE_GAP - TILE_BLEND_BADGE_SIZE
                            themed_draw_rectangle(
                                (blend_x, TILE_BLEND_BADGE_GAP),
                                (
                                    blend_x + TILE_BLEND_BADGE_SIZE,
                                    TILE_BLEND_BADGE_GAP + TILE_BLEND_BADGE_SIZE,
                                ),
                                slot="badge_bg",
                                color=(0, 0, 0, 0),
                                rounding=2,
                                tag=f"tile_badge_blend_{target_id}",
                            )
                            _blend_uv = sourcestatus.blending_uv(
                                data_dict[idx].get("blending")
                            ) or ((0.0, 0.0), (1.0 / sourcestatus.BLENDING_CELLS, 1.0))
                            if _blending_icons_texture is not None:
                                _tile_status_call(
                                    "blend icon",
                                    lambda t=target_id, uv=_blend_uv, bx=blend_x: dpg.draw_image(
                                        texture_tag=_blending_icons_texture,
                                        pmin=(
                                            bx + TILE_BLEND_ICON_INSET,
                                            TILE_BLEND_BADGE_GAP + TILE_BLEND_ICON_INSET,
                                        ),
                                        pmax=(
                                            bx + TILE_BLEND_BADGE_SIZE - TILE_BLEND_ICON_INSET,
                                            TILE_BLEND_BADGE_GAP
                                            + TILE_BLEND_BADGE_SIZE
                                            - TILE_BLEND_ICON_INSET,
                                        ),
                                        uv_min=list(uv[0]),
                                        uv_max=list(uv[1]),
                                        color=palette_rgba(state.active_palette["text_bright"]),
                                        tag=f"tile_blend_icon_{t}",
                                    ),
                                )
                            if target_id not in thumbnails_data:
                                if data_dict[idx].get("media_kind") == "other":
                                    # e57s02: no file behind the source — draw the name
                                    # instead of a loading / failed label (nothing will
                                    # ever arrive; the kind change rebuilds via the
                                    # grid signature).
                                    name_tag = f"other_txt_{target_id}"
                                    dpg.draw_text(
                                        (8, 26),
                                        _tile_placeholder_label(data_dict[idx], display_name),
                                        color=palette_rgba(state.active_palette["text_dim"]),
                                        size=13,
                                        tag=name_tag,
                                    )
                                    _text_color_bindings[name_tag] = "text_dim"
                                else:
                                    loading_tag = f"loading_txt_{target_id}"
                                    is_failed = (
                                        thumb_fail_count.get(target_id, 0) >= THUMB_FAIL_THRESHOLD
                                    )
                                    dpg.draw_text(
                                        (8, 26),
                                        THUMB_FAIL_LABEL if is_failed else " [ Loading... ]",
                                        color=palette_rgba(
                                            state.active_palette["warning"]
                                            if is_failed
                                            else state.active_palette["text_dim"]
                                        ),
                                        size=13,
                                        tag=loading_tag,
                                    )
                                    _text_color_bindings[loading_tag] = "text_dim"

                        # e74s12: the alpha COLUMN — the opacity slider (0..1) plus a small
                        # red STOP that parks the source (alpha < 0 makes vimix stop its
                        # media). The column keeps the slider's 65 px footprint: slider +
                        # 2 px gap + stop.
                        alpha_tag = f"tile_alpha_{target_id}"
                        stop_tag = f"tile_stop_{target_id}"
                        with dpg.group():
                            dpg.add_slider_float(
                                min_value=0.0,
                                max_value=1.0,
                                default_value=0.0,
                                vertical=True,
                                width=MEDIA_ALPHA_SLIDER_W,
                                height=MEDIA_ALPHA_SLIDER_H,
                                clamped=True,
                                format="",  # no readout: the slider position IS the value
                                callback=on_tile_alpha_slider,
                                user_data=target_id,
                                tag=alpha_tag,
                            )
                            dpg.bind_item_theme(alpha_tag, theme_alpha_slider)
                            help_tooltip(alpha_tag, "sources.alpha")
                            dpg.add_button(
                                label="x",
                                tag=stop_tag,
                                width=MEDIA_ALPHA_SLIDER_W,
                                height=MEDIA_ALPHA_STOP_H,
                                callback=on_tile_stop_click,
                                user_data=target_id,
                            )
                            dpg.bind_item_theme(stop_tag, theme_stop_button)
                            help_tooltip(stop_tag, "sources.stop")

                    # e83: the compact status — a 4 px seek bar and ONE 10 px line.
                    # Every call is GUARDED: a DPG build that dislikes one of these
                    # (the operator's window went half-built) must lose the nicety, not
                    # the grid.
                    _tile_status_call(
                        "seek bar",
                        lambda t=target_id, c=cw: dpg.add_progress_bar(
                            default_value=0.0,
                            width=MEDIA_TITLE_WRAP,
                            height=TILE_SEEK_BAR_H,
                            parent=c,
                            tag=f"tile_seek_bar_{t}",
                        ),
                    )
                    with dpg.group(horizontal=True, parent=cw):
                        # The flags sit at the LEFT of the line (second pass): letters,
                        # accent when ON and dim when OFF; the percentage is gone (the
                        # bar already shows the seek).
                        for prop, letter in TILE_STATUS_BADGES:
                            _tile_status_call(
                                "flag text",
                                lambda p=prop, ltr=letter, t=target_id: _add_tile_flag_text(
                                    p, ltr, t
                                ),
                            )
                        _tile_status_call(
                            "line spacer a",
                            lambda t=target_id: dpg.add_spacer(width=0, tag=f"tile_spacer_a_{t}"),
                        )
                        _tile_status_call(
                            "depth text",
                            lambda t=target_id: _add_tile_status_text(f"tile_status_depth_{t}"),
                        )
                        _tile_status_call(
                            "line spacer b",
                            lambda t=target_id: dpg.add_spacer(width=0, tag=f"tile_spacer_b_{t}"),
                        )
                        _tile_status_call(
                            "speed text",
                            lambda t=target_id: _add_tile_status_text(f"tile_status_speed_{t}"),
                        )

                    # e10s06: the tile's clickable children select the media on left
                    # click (child windows can't host clicked handlers in DPG 2.x). Draw
                    # commands can't host handler registries either, so the drawlist
                    # carries the thumbnail clicks; the alpha slider stays out — dragging
                    # it only sets alpha, it never steals the selection.
                    # e83 second pass: clicking ANYWHERE in the tile selects it. The
                    # child window itself cannot host a handler registry in DPG 2.x,
                    # so every non-interactive child joins the registry (the alpha
                    # slider keeps its own drag and the STOP its own click).
                    # The seek BAR is deliberately absent: DearPyGui REFUSES a click
                    # registry on an mvProgressBar ("Item Handler Registry includes
                    # inapplicable handler: mvClickedHandler"), and that exception used
                    # to abort the whole grid build after the first tile.
                    _bind_tile_click_targets(
                        click_reg_tag,
                        title_tag,
                        container_tag,
                        draw_tag,
                        f"tile_status_depth_{target_id}",
                        f"tile_status_speed_{target_id}",
                        *(f"tile_badge_{prop}_{target_id}" for prop, _letter in TILE_STATUS_BADGES),
                    )

                for _ in range(num_cols - len(row_indices)):
                    dpg.add_text("", parent=r_id)

            # Structural per-source updates: theme/title/index depend only on signature
            # fields (name/index/current_source/columns), so they run only on a real change
            # (perf e07 P0: an unchanged push used to re-write them every time). The
            # signature is committed AFTER the loop: a mid-loop failure must not lock the
            # grid to a half-built state (the next push retries the rebuild).
            for idx in sorted_keys:
                props = data_dict[idx]
                name = props.get("name")
                target_id = str(name) if name else str(idx)
                display_name = str(name) if name else f"Idx: {idx}"
                tile_tag = f"tile_{target_id}"

                if dpg.does_item_exist(tile_tag):
                    dpg.bind_item_theme(tile_tag, _tile_theme_for(idx, target_id))
                _set_media_cell(f"tile_title_{target_id}", truncate_media_title(display_name))
            state.last_ui_signature = current_signature

        # Value per-source updates: every cell write goes through the per-cell cache, so a
        # push that changes nothing performs zero dpg calls (perf e07 P0; measured ~20
        # calls/source/push before).
        for idx in sorted_keys:
            props = data_dict[idx]
            name = props.get("name")
            target_id = str(name) if name else str(idx)
            alpha_val = props.get("alpha")
            if isinstance(alpha_val, (int, float)):
                alpha_display = float(max(0.0, min(1.0, float(alpha_val))))
            else:
                alpha_display = 0.0
            _set_media_cell(f"tile_alpha_{target_id}", alpha_display)
            _set_tile_stop_theme(
                target_id, isinstance(alpha_val, (int, float)) and float(alpha_val) < 0
            )
            # e83: guarded — a status nicety never aborts the value pass.
            _tile_status_call("status update", lambda t=target_id, p=props: _set_tile_status(t, p))

            for prop in ALL_PROPERTIES:
                val = props.get(prop)
                if prop == "index" and val is None:
                    val = idx
                tag_name = f"raw_{idx}_{prop}"
                text = osc.raw_cell_text(prop, val, state.asked_props)
                _note_raw_change(tag_name, text)
                _set_media_cell(tag_name, text)

    except Exception as e:
        log_error("UI update", str(e))


# e38: SOURCE VIDEO PREVIEW — dedicated, resizable "Preview" window
# ==============================================================================
# 2026-09-07 (user, after rig UAT): the preview moved OUT of the "Vimix sources"
# window into its own top-level "Preview" window the user can position freely;
# resizing the window reflows the video + transport inside it. The transport
# (vjmixapp/preview.py) is dpg-free (HIGH-1); this block owns the window UI on
# the main thread: the "Preview..." tile action (media sources that are not
# known images), the per-frame raw-texture apply and the clean-stop paths
# (Close / X / source switch / source prune / worker error). The e33 rule is
# not triggered: the tile action is tile-anchored like Regenerate Thumbnails
# — not a MIDI binding target.

PREVIEW_WINDOW_TAG = "preview_window"
PREVIEW_RESIZE_REG_TAG = "preview_resize_reg"
PREVIEW_VIDEO_SLOT_TAG = "preview_video_slot"
PREVIEW_TEXTURE_TAG = "preview_tex"
PREVIEW_IMAGE_TAG = "preview_img"
PREVIEW_TIME_TAG = "preview_time"
PREVIEW_SEEK_TAG = "preview_seek"
PREVIEW_PLAYBTN_TAG = "preview_play_btn"
PREVIEW_SPEED_TAG = "preview_speed"
PREVIEW_SPEED_RESET_TAG = "preview_speed_reset"
PREVIEW_SPEED_LABEL_TAG = "preview_speed_label"
PREVIEW_CLOSE_TAG = "preview_close_btn"
PREVIEW_WAIT_TAG = "preview_wait_text"
PREVIEW_STATUS_TAG = "preview_status_text"
PREVIEW_MSG_TEXT_TAG = "preview_msg_text"
PREVIEW_TRANSPORT_TAG = "preview_transport"
PREVIEW_FLOW_ROW_TAGS = ("preview_flow_0", "preview_flow_1", "preview_flow_2")

# Transport layout (BUG-2026-09-12): the seek bar + controls never exceed the
# video width; the buttons flow onto new lines when the video gets narrow, and
# the window height hugs the content so no dead space is left below.
PREVIEW_H_PAD = 20  # px horizontal padding of the video + transport content
PREVIEW_H_SPACING = 8  # px horizontal spacing used by the button flow
# Heights measured on DearPyGui 2.3.1 with the default style (the Preview window
# binds no padding theme): window chrome (titlebar + padding) + the seek row +
# the status line + the two item gaps = 104 px for a one-row transport; every
# additional wrapped control row adds 23 px.
PREVIEW_CONTENT_CHROME_H = 104
PREVIEW_FLOW_ROW_STEP_H = 23
PREVIEW_SCREEN_MARGIN_H = 48  # keep the fitted window inside the viewport
PREVIEW_SEEK_MIN_W = 80
PREVIEW_BTN_PAUSE_W = 70
PREVIEW_TIME_RESERVE_W = 92  # px reserved for the timecode label
PREVIEW_SPEED_LABEL_W = 46  # px reserved for the "Speed" label
PREVIEW_SPEED_FIELD_W = 64
PREVIEW_BTN_RESET_W = 30
PREVIEW_BTN_CLOSE_W = 60

# The transport controls in reading order with their fixed widths; the flow
# packer uses this to decide where the lines break.
PREVIEW_TRANSPORT_CONTROLS: tuple[tuple[str, int], ...] = (
    (PREVIEW_PLAYBTN_TAG, PREVIEW_BTN_PAUSE_W),
    (PREVIEW_TIME_TAG, PREVIEW_TIME_RESERVE_W),
    (PREVIEW_SPEED_LABEL_TAG, PREVIEW_SPEED_LABEL_W),
    (PREVIEW_SPEED_TAG, PREVIEW_SPEED_FIELD_W),
    (PREVIEW_SPEED_RESET_TAG, PREVIEW_BTN_RESET_W),
    (PREVIEW_CLOSE_TAG, PREVIEW_BTN_CLOSE_W),
)

# Default window SIZE when no remembered rect exists yet (the position is
# centered on first open, e55; a session rect is remembered while the app runs
# and reused for the next preview).
PREVIEW_WIN_W = 560
PREVIEW_WIN_H = 440

_preview_player: Any = None  # composition-root-owned PreviewPlayer instance
_preview_tex_dims: tuple[int, int] | None = None
_preview_win_rect: tuple[int, int, int, int] | None = None
_preview_layout: tuple[int, int, int] | None = None  # last applied (disp_w, disp_h, content_w)
_preview_error_shown = False


def _preview_endpoints(cfg: dict[str, Any]) -> dict[str, Any]:
    """Effective preview endpoint: host follows the OSC client (the viOSC
    machine, machine A), port from cfg['preview'] (default PREVIEW_PORT)."""
    osc = _osc_endpoints_from_config(cfg)
    raw = cfg.get("preview")
    pcfg = raw if isinstance(raw, dict) else {}
    return {"host": osc["client_ip"], "port": int(pcfg.get("port") or PREVIEW_PORT)}


def _source_props(target_id: str) -> dict[str, Any] | None:
    for props in state.global_vimix_state.get("sources", {}).values():
        if str(props.get("name")) == str(target_id):
            return props
    return None


def _preview_offered(props: dict[str, Any] | None) -> bool:
    """Preview popup gating: a video source only (e68s02).

    The TYPE answers when it is known (`video` capability: 10/11), so a ShaderSource or a Clip
    is refused before any probe; an unknown type keeps the pre-e68 `media_kind` decision
    (images and 'other' excluded, a still-unclassified media source classifies on activation).
    """
    if not props or not props.get("uri"):
        return False
    typed = sourcekind.is_previewable(props)
    if typed is not None:
        return typed
    kind = props.get("media_kind")
    return kind not in ("image", "other")  # e57s02: only a video source previews


def _preview_reason(target_id: str, props: dict[str, Any] | None, meta_provider: Any) -> str:
    """Why a preview can start ('ok') or the explicit message. Images, non-media
    sources and 'other' media (no video stream) never start a transport — the
    reason is surfaced instead."""
    if not props or not props.get("uri"):
        return f"'{target_id}' is not a media source"
    kind = props.get("media_kind")
    typed = sourcekind.is_previewable(props)
    if typed is False:
        found = sourcekind.source_kind_of(props)
        named = found.label if found else "non-video"
        return f"'{target_id}' is a {named} source: preview is video-only"
    if typed is None:
        if kind == "other":
            return f"'{target_id}' is not a video source"
        if kind == "image":
            return f"'{target_id}' is an image source: preview is video-only"
        if kind is None:
            meta = meta_provider()
            if meta is None:
                return f"'{target_id}': preview unavailable (no video metadata)"
            if meta.get("kind") != "video":
                return f"'{target_id}' is not a video source"
    return "ok"


def _fmt_preview_time(secs: float) -> str:
    s = max(0, int(secs))
    return f"{s // 60}:{s % 60:02d}"


def _preview_status(message: str) -> None:
    """Surface a preview message (state + log + status line) — the explicit
    error surface: never a silent no-op, never a fake transport."""
    state.preview_error = message
    log_warn("PREVIEW", message)  # e81: the error surface, with the level that says so
    if dpg.does_item_exist(PREVIEW_STATUS_TAG):
        dpg.set_value(PREVIEW_STATUS_TAG, message)


def _preview_remember_rect() -> None:
    """Keep the last window geometry for the next preview session."""
    global _preview_win_rect
    if not dpg.does_item_exist(PREVIEW_WINDOW_TAG):
        return
    w = int(dpg.get_item_width(PREVIEW_WINDOW_TAG) or 0)
    h = int(dpg.get_item_height(PREVIEW_WINDOW_TAG) or 0)
    if w < 200 or h < 120:
        return
    x, y = dpg.get_item_pos(PREVIEW_WINDOW_TAG)
    _preview_win_rect = (int(x), int(y), w, h)


def _pack_preview_controls(max_w: int) -> list[list[str]]:
    """Greedily pack the transport controls into rows no wider than ``max_w``.

    Pure (no dpg): a control that does not fit flows onto the next line, so the
    transport never exceeds the video width (BUG-2026-09-12).
    """
    rows: list[list[str]] = [[] for _ in PREVIEW_FLOW_ROW_TAGS]
    row = 0
    used = 0
    for tag, width in PREVIEW_TRANSPORT_CONTROLS:
        if rows[row] and used + PREVIEW_H_SPACING + width > max_w and row + 1 < len(rows):
            row += 1
            used = 0
        if rows[row]:
            used += PREVIEW_H_SPACING
        rows[row].append(tag)
        used += width
    return rows


def _layout_preview_transport(content_w: int) -> None:
    """Reflow the seek bar + transport controls to ``content_w`` (the video
    width): the slider spans the width, the buttons wrap onto new lines."""
    if dpg.does_item_exist(PREVIEW_SEEK_TAG):
        dpg.configure_item(PREVIEW_SEEK_TAG, width=max(PREVIEW_SEEK_MIN_W, content_w))
    rows = _pack_preview_controls(content_w)
    for row_tag, tags in zip(PREVIEW_FLOW_ROW_TAGS, rows, strict=True):
        for tag in tags:
            if dpg.does_item_exist(tag):
                dpg.move_item(tag, parent=row_tag)
        if dpg.does_item_exist(row_tag):
            dpg.configure_item(row_tag, show=bool(tags))


def _preview_available_h() -> int:
    """Usable window height inside the viewport; 0 when it cannot be read."""
    try:
        total = int(dpg.get_viewport_client_height())
    except (TypeError, ValueError, AttributeError):
        return 0
    return max(0, total - PREVIEW_SCREEN_MARGIN_H)


def _layout_preview_content() -> None:
    """Reflow the video + transport to the current window size.

    The video fills the window width and keeps its aspect; the transport never
    exceeds the video width (the seek bar spans it, the buttons wrap); the
    window height then HUGS the content, so no dead space is left below the
    transport. The applied geometry is cached so a per-frame call never reflows
    (and never disturbs a slider drag); the height is re-fit only when it moved.
    """
    global _preview_layout
    if not dpg.does_item_exist(PREVIEW_WINDOW_TAG):
        return
    w = max(260, int(dpg.get_item_width(PREVIEW_WINDOW_TAG) or 0) or PREVIEW_WIN_W)
    if _preview_tex_dims is None:
        content_w = max(200, w - PREVIEW_H_PAD)
        if (0, 0, content_w) != _preview_layout:
            _preview_layout = (0, 0, content_w)
            _layout_preview_transport(content_w)
        return
    tex_w, tex_h = _preview_tex_dims
    disp_w = max(200, w - PREVIEW_H_PAD)
    disp_h = int(disp_w * tex_h / tex_w)
    rows = 1
    window_h = 0
    avail = _preview_available_h()
    for _ in range(3):
        rows = sum(1 for r in _pack_preview_controls(disp_w) if r)
        window_h = disp_h + PREVIEW_CONTENT_CHROME_H + (rows - 1) * PREVIEW_FLOW_ROW_STEP_H
        if not avail or window_h <= avail:
            break
        # taller than the screen: shrink the video (letterbox on the sides)
        video_avail = max(
            120, avail - PREVIEW_CONTENT_CHROME_H - (rows - 1) * PREVIEW_FLOW_ROW_STEP_H
        )
        if video_avail >= disp_h:
            break
        disp_h = video_avail
        disp_w = max(200, int(disp_h * tex_w / tex_h))
    if (disp_w, disp_h, disp_w) != _preview_layout:
        _preview_layout = (disp_w, disp_h, disp_w)
        if dpg.does_item_exist(PREVIEW_IMAGE_TAG):
            dpg.configure_item(PREVIEW_IMAGE_TAG, width=disp_w, height=disp_h)
        _layout_preview_transport(disp_w)
        if dpg.does_item_exist(PREVIEW_STATUS_TAG):
            dpg.configure_item(PREVIEW_STATUS_TAG, wrap=max(200, disp_w))
    h_now = int(dpg.get_item_height(PREVIEW_WINDOW_TAG) or 0)
    if h_now and window_h and window_h != h_now:
        dpg.configure_item(PREVIEW_WINDOW_TAG, height=window_h)


def _on_preview_window_resize(
    sender: Any = None, app_data: Any = None, user_data: Any = None
) -> None:
    """Window resized: reflow the inner video + transport (main thread)."""
    _preview_remember_rect()
    _layout_preview_content()


def _open_preview_window(target_id: str, message: str | None = None) -> None:
    """Create (fresh) the dedicated Preview window with its content.

    ``message`` given: an error window (no transport) so a refused preview is
    visible and closable, never a silent no-op.
    """
    global _preview_layout
    _preview_layout = None  # a fresh window must be laid out once
    if _preview_win_rect is not None:
        x, y, w, h = _preview_win_rect
    else:
        # e55: first open -> centered on the viewport; later opens reuse the rect.
        w, h = PREVIEW_WIN_W, PREVIEW_WIN_H
        x, y = first_open_pos(w, h)
    if message is not None:
        title = "Preview"
        with dpg.window(label=title, tag=PREVIEW_WINDOW_TAG, width=420, height=120, pos=(x, y)):
            themed_text(message, slot="warning", tag=PREVIEW_MSG_TEXT_TAG, wrap=380)
            dpg.add_button(label="Close", width=90, callback=close_source_preview)
    else:
        with dpg.window(
            # ASCII separator: window titles use the default font, which has no glyph for "—"
            label=f"Preview - {target_id}",
            tag=PREVIEW_WINDOW_TAG,
            width=w,
            height=h,
            pos=(x, y),
            no_scrollbar=True,  # the height hugs the content: nothing ever scrolls
        ):
            with dpg.group(tag=PREVIEW_VIDEO_SLOT_TAG):
                dpg.add_text("Connecting...", tag=PREVIEW_WAIT_TAG)
            with dpg.group(tag=PREVIEW_TRANSPORT_TAG):
                dpg.add_slider_float(
                    default_value=0.0,
                    min_value=0.0,
                    max_value=1.0,
                    width=max(PREVIEW_SEEK_MIN_W, w - PREVIEW_H_PAD),
                    tag=PREVIEW_SEEK_TAG,
                    callback=on_preview_seek,
                )
                # controls live in the first flow row; _layout_preview_content
                # moves them onto the next row when they no longer fit the video
                with dpg.group(horizontal=True, tag=PREVIEW_FLOW_ROW_TAGS[0]):
                    dpg.add_button(
                        label="Pause",
                        width=PREVIEW_BTN_PAUSE_W,
                        tag=PREVIEW_PLAYBTN_TAG,
                        callback=on_preview_play_button,
                    )
                    themed_text("0:00 / 0:00", slot="text", tag=PREVIEW_TIME_TAG)
                    themed_text("Speed", slot="text_dim", tag=PREVIEW_SPEED_LABEL_TAG)
                    dpg.add_drag_float(
                        default_value=PREVIEW_SPEED_DEFAULT,
                        min_value=PREVIEW_SPEED_MIN,
                        max_value=PREVIEW_SPEED_MAX,
                        speed=PREVIEW_SPEED_STEP,
                        format="%.2fx",
                        width=PREVIEW_SPEED_FIELD_W,
                        tag=PREVIEW_SPEED_TAG,
                        callback=on_preview_speed,
                    )
                    dpg.add_button(
                        label="1x",
                        width=PREVIEW_BTN_RESET_W,
                        tag=PREVIEW_SPEED_RESET_TAG,
                        callback=on_preview_speed_reset,
                    )
                    dpg.add_button(
                        label="Close",
                        width=PREVIEW_BTN_CLOSE_W,
                        tag=PREVIEW_CLOSE_TAG,
                        callback=close_source_preview,
                    )
                for row_tag in PREVIEW_FLOW_ROW_TAGS[1:]:
                    dpg.add_group(horizontal=True, tag=row_tag)
            themed_text("", slot="text_dim", tag=PREVIEW_STATUS_TAG)
        # first reflow to the intended geometry (the window may not report its
        # size yet); the first decoded frame refines it to the video width
        _layout_preview_content()
    # window resize handler: inner content follows the window size
    if dpg.does_item_exist(PREVIEW_RESIZE_REG_TAG):
        dpg.delete_item(PREVIEW_RESIZE_REG_TAG)
    with dpg.item_handler_registry(tag=PREVIEW_RESIZE_REG_TAG):
        dpg.add_item_resize_handler(callback=_on_preview_window_resize)
    dpg.bind_item_handler_registry(PREVIEW_WINDOW_TAG, PREVIEW_RESIZE_REG_TAG)


def _preview_apply_frame(rgba: Any) -> None:
    """Apply one decoded frame (RGBA float32, h x w x 4) to the raw texture. The
    texture is created once per (session, size); later frames set_value only."""
    global _preview_tex_dims
    height, width = rgba.shape[0], rgba.shape[1]
    dims = (width, height)
    tex_tag = PREVIEW_TEXTURE_TAG
    if _preview_tex_dims != dims or not dpg.does_item_exist(tex_tag):
        for stale in (PREVIEW_IMAGE_TAG, tex_tag):
            if dpg.does_item_exist(stale):
                dpg.delete_item(stale)
        dpg.add_raw_texture(
            width=width,
            height=height,
            default_value=rgba.reshape(-1),
            tag=tex_tag,
            parent="texture_registry",
        )
        dpg.add_image(
            tex_tag,
            tag=PREVIEW_IMAGE_TAG,
            parent=PREVIEW_VIDEO_SLOT_TAG,
            width=max(200, PREVIEW_WIN_W - 20),
            height=180,
        )
        if dpg.does_item_exist(PREVIEW_WAIT_TAG):
            dpg.delete_item(PREVIEW_WAIT_TAG)
        _preview_tex_dims = dims
    else:
        dpg.set_value(tex_tag, rgba.reshape(-1))
    _layout_preview_content()


def close_source_preview(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """Clean stop: remember the geometry, close the worker, drop the window."""
    global _preview_player, _preview_tex_dims, _preview_layout
    _preview_remember_rect()
    player = _preview_player
    _preview_player = None
    if player is not None:
        player.close()
    if dpg.does_item_exist(PREVIEW_RESIZE_REG_TAG):
        dpg.delete_item(PREVIEW_RESIZE_REG_TAG)
    if dpg.does_item_exist(PREVIEW_WINDOW_TAG):
        dpg.delete_item(PREVIEW_WINDOW_TAG)  # drops the texture/image children too
    _preview_tex_dims = None
    _preview_layout = None
    state.preview_active = None
    state.preview_playing = False
    state.preview_error = None
    while True:  # drop frames still queued for the closed session
        try:
            state.preview_frames.get_nowait()
        except queue.Empty:
            break


def start_source_preview(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """Open the dedicated Preview window for a source (tile 'Preview...' action).
    One preview at a time; images/non-media show an explicit message window,
    never a transport; unknown-kind media classify via the meta endpoint first."""
    global _preview_player, _preview_error_shown
    target_id = str(user_data)
    props = _source_props(target_id)
    endpoints = _preview_endpoints(load_config())

    def classify() -> Any:
        return preview.fetch_media_meta(endpoints["host"], endpoints["port"], target_id)

    reason = _preview_reason(target_id, props, classify)
    if reason != "ok":
        close_source_preview()
        _preview_status(reason)
        _open_preview_window(target_id, message=reason)
        return
    close_source_preview()
    _preview_error_shown = False
    state.preview_error = None
    state.preview_active = target_id
    state.preview_playing = True
    _open_preview_window(target_id)
    player = preview.PreviewPlayer(target_id, host=endpoints["host"], port=endpoints["port"])
    _preview_player = player
    player.start()


def on_preview_play_button(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """Play/Pause toggle of the preview transport (main thread)."""
    if _preview_player is None:
        return
    if state.preview_playing:
        _preview_player.pause()
        state.preview_playing = False
        if dpg.does_item_exist(PREVIEW_PLAYBTN_TAG):
            dpg.set_item_label(PREVIEW_PLAYBTN_TAG, "Play")
    else:
        _preview_player.resume()
        state.preview_playing = True
        if dpg.does_item_exist(PREVIEW_PLAYBTN_TAG):
            dpg.set_item_label(PREVIEW_PLAYBTN_TAG, "Pause")


def on_preview_speed(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """Speed field changed (e38 BUG-2026-09-12): clamp, drive the transport,
    and reflect the clamped value back into the widget."""
    rate = preview.clamp_preview_speed(app_data)
    if _preview_player is not None:
        _preview_player.set_speed(rate)
    if dpg.does_item_exist(PREVIEW_SPEED_TAG):
        dpg.set_value(PREVIEW_SPEED_TAG, rate)


def on_preview_speed_reset(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """One-click reset of the playback rate to real time (the default)."""
    if _preview_player is not None:
        _preview_player.set_speed(PREVIEW_SPEED_DEFAULT)
    if dpg.does_item_exist(PREVIEW_SPEED_TAG):
        dpg.set_value(PREVIEW_SPEED_TAG, PREVIEW_SPEED_DEFAULT)


def on_preview_seek(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """Scrub: seek the transport to a fraction of the playable duration."""
    if _preview_player is not None:
        _preview_player.seek(float(app_data))


def tick_source_preview(_now: float) -> None:
    """Main-loop tick: drain preview frames onto the texture, keep the transport
    in sync, surface worker errors once, stop when the window is X-closed
    (main thread only, HIGH-1)."""
    if state.preview_active is not None and not dpg.does_item_exist(PREVIEW_WINDOW_TAG):
        close_source_preview()  # the user X-closed the window: stop the stream
        return
    if state.preview_active is None:
        while True:
            try:
                state.preview_frames.get_nowait()
            except queue.Empty:
                break
        return
    global _preview_error_shown
    player = _preview_player
    if player is None:
        return
    newest = None
    while True:
        try:
            name, frame = state.preview_frames.get_nowait()
        except queue.Empty:
            break
        if str(name) == str(state.preview_active):
            newest = frame
    if newest is not None:
        _preview_apply_frame(newest)
    if player.done and player.error and not _preview_error_shown:
        _preview_error_shown = True
        _preview_status(player.error)
    if state.preview_playing and not dpg.is_item_active(PREVIEW_SEEK_TAG):
        duration = player.duration
        if duration > 0:
            fraction = max(0.0, min(1.0, player.position() / duration))
            if dpg.does_item_exist(PREVIEW_SEEK_TAG):
                dpg.set_value(PREVIEW_SEEK_TAG, fraction)
    if dpg.does_item_exist(PREVIEW_TIME_TAG):
        dpg.set_value(
            PREVIEW_TIME_TAG,
            f"{_fmt_preview_time(player.position())} / {_fmt_preview_time(player.duration)}",
        )


def start_osc_server(ip: str, port: int) -> bool:
    """Start the local OSC listening server (main thread); True when it is up."""
    if state.is_server_running:
        return True
    try:
        disp = dispatcher.Dispatcher()
        disp.set_default_handler(incoming_osc_handler)
        state.local_osc_server = VjmixOSCUDPServer((ip, port), disp)
        size_receive_buffer(getattr(state.local_osc_server, "socket", None))
        state.local_server_thread = threading.Thread(
            target=state.local_osc_server.serve_forever, daemon=True
        )
        state.local_server_thread.start()
        state.is_server_running = True
        dpg.set_item_label("btn_server_toggle", "Stop Server")
        dpg.set_value("server_status", f"Server Status: Listening on {ip}:{port}")
        return True
    except Exception as e:
        dpg.set_value("server_status", f"Server Status: ERROR ({e})")
        return False


def _osc_endpoints_from_config(cfg: dict[str, Any]) -> dict[str, Any]:
    """The effective OSC endpoints: cfg['osc'] merged over the constants (e28s04)."""
    raw = cfg.get("osc")
    osc_cfg = raw if isinstance(raw, dict) else {}
    return {
        "client_ip": str(osc_cfg.get("client_ip") or VIOSC_IP),
        "client_port": int(osc_cfg.get("client_port") or VIOSC_PORT),
        "listen_ip": str(osc_cfg.get("listen_ip") or VIOSC_IP),
        "listen_port": int(osc_cfg.get("listen_port") or VIOSC_LISTEN_PORT),
    }


def persist_osc_endpoints(
    client_ip: str | None = None,
    client_port: int | None = None,
    listen_ip: str | None = None,
    listen_port: int | None = None,
) -> None:
    """Persist OSC endpoint fields into cfg['osc'] (e28s04); None leaves a field."""
    cfg = load_config()
    osc = cfg["osc"]
    if client_ip is not None:
        osc["client_ip"] = client_ip
    if client_port is not None:
        osc["client_port"] = client_port
    if listen_ip is not None:
        osc["listen_ip"] = listen_ip
    if listen_port is not None:
        osc["listen_port"] = listen_port
    save_config(cfg)


def toggle_local_server() -> None:
    if state.is_server_running:
        if state.local_osc_server and state.local_server_thread is not None:
            state.local_osc_server.shutdown()
            state.local_server_thread.join(timeout=1.0)
            state.local_osc_server = None
        state.is_server_running = False
        dpg.set_item_label("btn_server_toggle", "Start Server")
        dpg.set_value("server_status", "Server Status: Stopped")
    else:
        ip = str(dpg.get_value("listen_ip"))
        port = int(dpg.get_value("listen_port"))
        if start_osc_server(ip, port):
            persist_osc_endpoints(listen_ip=ip, listen_port=port)  # e28s04


def connect_osc_client(ip: str, port: int) -> bool:
    """Create the viOSC client (main thread); True when ready."""
    try:
        state.viosc_client = osc.observe_client(
            udp_client.SimpleUDPClient(ip, port), f"{ip}:{port}"
        )
        # e41s03: the HTTP data plane lives on the SAME machine as viOSC, so its
        # host follows the OSC client and its port comes from the preview config
        # (the e38 server the thumbnails now use). Refreshed whenever the client
        # is (re)connected, which is the only place the endpoint can change.
        state.dataplane_host = str(ip)
        state.dataplane_port = int(_preview_endpoints(load_config())["port"])
        dpg.set_value("viosc_status", f"Client Status: Ready on {ip}:{port}")
        return True
    except Exception:
        dpg.set_value("viosc_status", "Client Status: Initialization error")
        return False


def connect_to_viosc() -> None:
    """Connect the OSC client from the viOSC panel inputs (button callback)."""
    ip = str(dpg.get_value("viosc_ip"))
    port = int(dpg.get_value("viosc_port"))
    if connect_osc_client(ip, port):
        persist_osc_endpoints(client_ip=ip, client_port=port)  # e28s04


def autostart_osc() -> None:
    """Boot wiring: auto-connect the viOSC client and start the listening server
    on the persisted endpoints (e28s04); constants when the config has none."""
    endpoints = _osc_endpoints_from_config(load_config())
    connect_osc_client(endpoints["client_ip"], endpoints["client_port"])
    start_osc_server(endpoints["listen_ip"], endpoints["listen_port"])


# --- e58s03: viOSC REMOTE CONFIG PAGE ---
# viOSC is the backend of VJmix: its settings are edited here, over the machine-A
# HTTP /config surface (e58s01). The link (ui_ip/reply_port) is DERIVED from
# VJmix's own listen endpoint on save, so the two sides cannot drift — the
# single-source link collapse.
VIOSC_CFG_FIELDS_TAG = "viosc_cfg_fields"
VIOSC_CFG_STATUS_TAG = "viosc_cfg_status"
VIOSC_CFG_INPUT_PREFIX = "viosc_cfg_"

# e58s03: the settings-window connection LED — green while viOSC state flows,
# red when the link is silent.
VIOSC_LED_TAG = "viosc_conn_led"
VIOSC_LED_OK_RGBA = (60, 200, 60, 255)
VIOSC_LED_DOWN_RGBA = (200, 60, 60, 255)
VIOSC_LED_STALE_SECONDS = 5.0


def _viosc_dataplane_endpoint() -> tuple[str, int]:
    """The machine-A HTTP endpoint (set with the OSC client)."""
    return str(state.dataplane_host or ""), int(state.dataplane_port or 0)


def _rebuild_viosc_config_fields(payload: dict[str, Any]) -> None:
    """(Re)build the editable widgets for the remote-editable fields (e58s03)."""
    if dpg.does_item_exist(VIOSC_CFG_FIELDS_TAG):
        dpg.delete_item(VIOSC_CFG_FIELDS_TAG, children_only=True)
    else:
        dpg.add_group(tag=VIOSC_CFG_FIELDS_TAG, parent="settings_window")
    values = payload.get("values") or {}
    for key in payload.get("editable") or []:
        with dpg.group(horizontal=True, parent=VIOSC_CFG_FIELDS_TAG):
            dpg.add_text(key)
            dpg.add_input_text(
                default_value=viosccfg.format_value(values.get(key)),
                tag=f"{VIOSC_CFG_INPUT_PREFIX}{key}",
                width=220,
            )


def _set_viosc_cfg_status(message: str = "") -> None:
    """Show the viOSC configuration status ONLY when there is something to say (e58s03).

    Success is silent (no "Loaded from viOSC" / "Saved" noise); errors and the
    per-field report still appear, and the line is hidden when empty.
    """
    if not dpg.does_item_exist(VIOSC_CFG_STATUS_TAG):
        return
    dpg.set_value(VIOSC_CFG_STATUS_TAG, message)
    dpg.configure_item(VIOSC_CFG_STATUS_TAG, show=bool(message))


def load_viosc_config() -> None:
    """Fetch the viOSC config and populate the page (e58s03)."""
    host, port = _viosc_dataplane_endpoint()
    payload, err = viosccfg.fetch_config(host, port)
    if err or payload is None:
        _set_viosc_cfg_status(f"viOSC unreachable: {err or 'no data'}")
        return
    state.viosc_config_values = dict(payload.get("values") or {})
    _rebuild_viosc_config_fields(payload)
    _set_viosc_cfg_status()


def save_viosc_config() -> None:
    """Post the changed fields (link derived) and show the report (e58s03)."""
    host, port = _viosc_dataplane_endpoint()
    original = dict(state.viosc_config_values or {})
    if not original:
        _set_viosc_cfg_status("Load the viOSC settings first")
        return
    edited: dict[str, Any] = {}
    for key, current in original.items():
        tag = f"{VIOSC_CFG_INPUT_PREFIX}{key}"
        if dpg.does_item_exist(tag):
            try:
                edited[key] = viosccfg.parse_field(str(dpg.get_value(tag)), current)
            except (ValueError, TypeError):
                _set_viosc_cfg_status(f"{key}: invalid input")
                return
    endpoints = _osc_endpoints_from_config(load_config())
    edited.update(viosccfg.link_fields(endpoints["listen_ip"], endpoints["listen_port"]))
    report, err = viosccfg.apply_config(host, port, viosccfg.config_diff(original, edited))
    if err or report is None:
        _set_viosc_cfg_status(f"viOSC error: {err or 'no report'}")
        return
    lines = viosccfg.report_lines(report)
    _set_viosc_cfg_status(" | ".join(lines))


def restart_viosc() -> None:
    """Trigger a viOSC restart over HTTP (e58s03)."""
    host, port = _viosc_dataplane_endpoint()
    ok, err = viosccfg.trigger_restart(host, port)
    _set_viosc_cfg_status("" if ok else f"Restart failed: {err}")


def change_osc_endpoint(viosc_listen_ip: str, viosc_listen_port: int) -> str:
    """Two-sided OSC bind change: tell viOSC, persist our side, reconnect (e58s04).

    viOSC's OSC input bind and VJmix's client endpoint are two sides of the same
    link: changing one without the other points the control plane at a dead port.
    The order is: tell viOSC the new bind -> persist our matching endpoint ->
    restart viOSC -> reconnect and verify. HTTP stays reachable throughout (its
    bind is local-only, e58s02), so a failure never locks the operator out — the
    repair path is this page.
    """
    host, port = _viosc_dataplane_endpoint()
    if not host or not port:
        return "viOSC endpoint not configured"
    report, err = viosccfg.apply_config(
        host, port, {"listen_ip": viosc_listen_ip, "listen_port": viosc_listen_port}
    )
    if err or report is None:
        return f"viOSC unreachable: {err or 'no report'}"
    if viosccfg.has_problems(report):
        return " | ".join(viosccfg.report_lines(report))
    persist_osc_endpoints(client_ip=viosc_listen_ip, client_port=viosc_listen_port)
    ok, rerr = viosccfg.trigger_restart(host, port)
    if not ok:
        return f"restart failed: {rerr} — repair the bind from this page"
    if not connect_osc_client(viosc_listen_ip, viosc_listen_port):
        return "reconnect failed — repair the bind from this page"
    return f"viOSC OSC bind moved to {viosc_listen_ip}:{viosc_listen_port}"


def tick_viosc_led() -> None:
    """Colour the viOSC connection LED (e58s03).

    Green when the OSC client is connected AND state has arrived recently (either
    lane), red otherwise — a client object alone does not mean viOSC answers.
    """
    if not dpg.does_item_exist(VIOSC_LED_TAG):
        return
    alive = (
        state.viosc_client is not None
        and (time.monotonic() - state.last_viosc_state_ts) < VIOSC_LED_STALE_SECONDS
    )
    dpg.configure_item(VIOSC_LED_TAG, fill=VIOSC_LED_OK_RGBA if alive else VIOSC_LED_DOWN_RGBA)


# e42s02: PAIRING PROMPT — viOSC is paired by default (a code shown on machine
# A), so VJmix asks once per run, exchanges the code on a worker (no dpg there),
# and keeps the token in memory for every data-plane request.
PAIRING_PROMPT_TAG = "pairing_prompt_modal"
PAIRING_CODE_INPUT_TAG = "pairing_code_input"
PAIRING_STATUS_TAG = "pairing_status_text"
PAIRING_PROMPT_WIDTH = 440
PAIRING_PROMPT_HEIGHT = 240
# e55s02: the code field is as wide as four big monospace digits plus padding.
PAIRING_CODE_INPUT_WIDTH = 140
PAIRING_CODE_FONT_SIZE = 30
# First existing path wins; the bundled ProggyTiny is the guaranteed fallback.
_PAIRING_CODE_FONT_PATHS: tuple[str, ...] = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
    *_HELP_MONO_FONT_PATHS,
    str(Path(__file__).resolve().parent / "vjmixapp" / "assets" / "ProggyTiny.ttf"),
)
_pairing_code_font: Any = None


def sanitize_pairing_code(value: Any) -> str:
    """The first four ASCII digits of a typed pairing code (e55s02).

    Non-digits (letters, spaces, punctuation) and anything past the fourth digit
    are dropped, so the value that reaches `/auth` is always at most four digits.
    """
    return "".join(ch for ch in str(value or "") if ch in "0123456789")[:4]


def _on_pairing_code_edit(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """Input change: keep only the first four digits (e55s02).

    Rewrites the value ONLY when it differs, so the cursor is not fought while
    the digits are already clean.
    """
    code = sanitize_pairing_code(app_data)
    if code != str(app_data or ""):
        dpg.set_value(PAIRING_CODE_INPUT_TAG, code)


def _on_pairing_code_enter(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """Global Enter handler: submit ONLY while the pairing prompt is up (e55s02).

    The digit filter owns the input callback, so Enter is routed here; the
    existence guard keeps Enter inert in every other window.
    """
    if dpg.does_item_exist(PAIRING_PROMPT_TAG):
        _pairing_connect()


def _pairing_endpoint() -> tuple[str, int]:
    """The machine-A data-plane endpoint the code exchange goes to."""
    return str(state.dataplane_host or ""), int(state.dataplane_port or 0)


def show_pairing_prompt(*_args: Any) -> None:
    """Open the pairing modal (shown once at boot, centered, e42s02/e55s02)."""
    if dpg.does_item_exist(PAIRING_PROMPT_TAG):
        dpg.delete_item(PAIRING_PROMPT_TAG)
    with dpg.window(
        label="Pair with viOSC",
        tag=PAIRING_PROMPT_TAG,
        modal=True,
        width=PAIRING_PROMPT_WIDTH,
        height=PAIRING_PROMPT_HEIGHT,
        no_resize=True,
    ):
        dpg.add_text(
            "Enter the pairing code shown on the viOSC machine.",
            wrap=PAIRING_PROMPT_WIDTH - 40,
        )
        dpg.add_input_text(
            tag=PAIRING_CODE_INPUT_TAG,
            hint="4 digits",
            width=PAIRING_CODE_INPUT_WIDTH,
            decimal=True,
            auto_select_all=True,
            callback=_on_pairing_code_edit,
        )
        if _pairing_code_font is not None:
            dpg.bind_item_font(PAIRING_CODE_INPUT_TAG, _pairing_code_font)
        dpg.add_text("", tag=PAIRING_STATUS_TAG, wrap=PAIRING_PROMPT_WIDTH - 40)
        dpg.add_separator()
        with dpg.group(horizontal=True):
            dpg.add_button(label="Skip", width=120, callback=hide_pairing_prompt)
            dpg.add_button(label="Connect", width=140, callback=_pairing_connect)
    _apply_help_targets()  # e76: this modal is built on demand, not at import
    show_centered_window(PAIRING_PROMPT_TAG)


def hide_pairing_prompt(*_args: Any) -> None:
    """Close the pairing prompt (Skip, or a successful exchange)."""
    if dpg.does_item_exist(PAIRING_PROMPT_TAG):
        dpg.delete_item(PAIRING_PROMPT_TAG)


def _pairing_connect(*_args: Any) -> None:
    """Connect button / Enter: exchange the code on a worker (HIGH-1)."""
    host, port = _pairing_endpoint()
    code = sanitize_pairing_code(dpg.get_value(PAIRING_CODE_INPUT_TAG))
    if not host or not port:
        dpg.set_value(PAIRING_STATUS_TAG, "viOSC endpoint not configured.")
        return
    if not code:
        dpg.set_value(PAIRING_STATUS_TAG, "Enter the code first.")
        return
    dpg.set_value(PAIRING_STATUS_TAG, "Connecting...")
    threading.Thread(target=_pairing_worker, args=(host, port, code), daemon=True).start()


def _pairing_worker(host: str, port: int, code: str) -> None:
    """Worker: exchange the code, then report on the main thread (HIGH-1)."""
    token = pairing.authenticate(host, port, code)
    state.ui_task_queue.put(lambda: _pairing_result(token))


def _on_pairing_succeeded() -> None:
    """Re-establish the transport after a successful pairing (e42s02).

    BUG-2026-09-13T231500: VJmix boots and starts talking BEFORE the code is
    entered, so viOSC drops the boot-time OSC — but the memoization records the
    watch/monitor plan as sent, and the state pull reads the boot 401 as an old
    daemon. Forget all of it so the next sync re-issues the whole plan and both
    lanes retry now that a token and a bound peer exist.
    """
    state.mapping_watch_plan = {}
    state.mapping_subscriptions = {}
    state.osc_watch_supported = None
    state.state_pull_supported = None
    state.state_pull_failures = 0
    state.thumb_http_supported = None
    state.thumb_http_failures = 0
    _sync_mapping_subscriptions()


def _pairing_result(token: str | None) -> None:
    """Main thread: close on success, explain the failure otherwise."""
    if token:
        hide_pairing_prompt()
        _on_pairing_succeeded()
        return
    if dpg.does_item_exist(PAIRING_STATUS_TAG):
        dpg.set_value(
            PAIRING_STATUS_TAG,
            "Pairing failed. Check the code shown on viOSC and that machine A is reachable.",
        )


# e43s02: FILE MANAGER WINDOW — browse machine A's Media Roots through the /fs
# data plane (e43s01). The window rebuilds a plain entry list per navigation; a
# dpg-free worker does the HTTP call and hands the result to the main thread
# (HIGH-1). Layout is persisted (LAYOUT_WINDOW_TAGS) and the toggle is mappable
# per the e33 rule.
FILE_MANAGER_TAG = "file_manager_window"
FILE_MANAGER_ROOTS_TAG = "fs_roots_combo"
FILE_MANAGER_BREADCRUMB_TAG = "fs_breadcrumb"
FILE_MANAGER_ENTRIES_TAG = "fs_entries_group"
FILE_MANAGER_STATUS_TAG = "fs_status_line"
FILE_MANAGER_LEARN_SLOT = "fs_learn_slot"
FILE_MANAGER_WIDTH = 660
FILE_MANAGER_HEIGHT = 640
FILE_MANAGER_LIST_HEIGHT = 300
FS_ENTRIES_COLUMNS = 2
FS_ENTRY_LABEL_WIDTH = 220
# e46s01: the compact toolbar strip at the top of the viewport; the workspace
# windows start below it so the borderless toolbar is never covered.
TOOLBAR_BAR_H = 34
TOOLBAR_BAR_POS = (2, 4)


def show_file_manager_window(*_args: Any) -> None:
    """Windows menu / e33 action: show the File Manager (load the roots once)."""
    dpg.show_item(FILE_MANAGER_TAG)
    dpg.focus_item(FILE_MANAGER_TAG)
    if not state.fs_roots and not state.fs_busy:
        fs_refresh()


def toggle_file_manager_window(*_args: Any) -> None:
    """e33 action: show the window, or hide it when it is already open."""
    # BUG-2026-09-19T002150: the same existence-before-shown guard as the
    # toolbar dispatcher (the shown query raises for a tag with no item).
    if dpg.does_item_exist(FILE_MANAGER_TAG) and dpg.is_item_shown(FILE_MANAGER_TAG):
        dpg.hide_item(FILE_MANAGER_TAG)
        return
    show_file_manager_window()


def _fs_endpoint() -> tuple[str, int]:
    """The machine-A data-plane endpoint the /fs requests go to."""
    return str(state.dataplane_host or ""), int(state.dataplane_port or 0)


def _fs_error_text(status: int | None) -> str:
    """A short, honest state line for a failed /fs request."""
    if status == 401:
        return "Not paired with viOSC: use Settings > Pair with viOSC..."
    if status == 403:
        return "Outside the allowed roots: check fs_roots in viOSC."
    if status is None:
        return "viOSC unreachable."
    return f"Error ({status})."


def fs_refresh(*_args: Any) -> None:
    """Reload the roots (first time) and the current directory."""
    if not state.fs_roots:
        _fs_request_roots()
    if state.fs_current_path:
        fs_navigate(state.fs_current_path)


def _fs_request_roots() -> None:
    if state.fs_busy:
        return
    host, port = _fs_endpoint()
    state.fs_busy = True
    state.fs_status = "Loading Media Roots..."
    dpg.set_value(FILE_MANAGER_STATUS_TAG, state.fs_status)
    threading.Thread(target=_fs_roots_worker, args=(host, port), daemon=True).start()


def _fs_roots_worker(host: str, port: int) -> None:
    """Worker: fetch the Media Roots, report on the main thread (HIGH-1)."""
    roots, status = fsclient.fetch_roots(host, port)
    state.ui_task_queue.put(lambda: _fs_apply_roots(roots, status))


def _fs_apply_roots(roots: list | None, status: int | None) -> None:
    """Main thread: fill the roots combo (and open the first root)."""
    state.fs_busy = False
    if not roots:
        state.fs_status = _fs_error_text(status)
        dpg.set_value(FILE_MANAGER_STATUS_TAG, state.fs_status)
        return
    state.fs_roots = roots
    paths = [str(r.get("path")) for r in roots]
    dpg.configure_item(FILE_MANAGER_ROOTS_TAG, items=paths)
    fs_navigate(paths[0])


def fs_navigate(path: str, *_args: Any) -> None:
    """Load one directory page (single-flight: a busy request wins)."""
    if state.fs_busy:
        return
    host, port = _fs_endpoint()
    if not host or not port:
        state.fs_status = "viOSC endpoint not configured."
        dpg.set_value(FILE_MANAGER_STATUS_TAG, state.fs_status)
        return
    state.fs_busy = True
    state.fs_status = "Loading..."
    dpg.set_value(FILE_MANAGER_STATUS_TAG, state.fs_status)
    threading.Thread(target=_fs_list_worker, args=(host, port, str(path)), daemon=True).start()


def _fs_list_worker(host: str, port: int, path: str) -> None:
    """Worker: fetch one directory page, report on the main thread (HIGH-1)."""
    payload, status = fsclient.fetch_listing(host, port, path)
    state.ui_task_queue.put(lambda: _fs_apply_listing(path, payload, status))


def _fs_apply_listing(path: str, payload: dict | None, status: int | None) -> None:
    """Main thread: store the page, update the chrome and rebuild the list."""
    state.fs_busy = False
    if payload is None:
        state.fs_status = _fs_error_text(status)
        dpg.set_value(FILE_MANAGER_STATUS_TAG, state.fs_status)
        return
    state.fs_current_path = str(payload.get("path") or path)
    state.fs_entries = list(payload.get("entries") or [])
    state.fs_total = int(payload.get("total") or len(state.fs_entries))
    state.fs_selected = None
    state.fs_status = f"{state.fs_total} entries"
    dpg.set_value(FILE_MANAGER_BREADCRUMB_TAG, state.fs_current_path)
    dpg.set_value(FILE_MANAGER_STATUS_TAG, state.fs_status)
    _fs_render_entries()
    _fs_request_thumbnails(state.fs_entries)


def _fs_entry_label(entry: dict[str, Any]) -> str:
    """A plain, readable row label: folders first, media kinds spelled out."""
    name = str(entry.get("name") or "")
    if entry.get("kind") == "dir":
        return f"[dir] {name}"
    kind = entry.get("media_kind")
    return f"{name}  ({kind})" if kind and kind != "other" else name


def _fs_render_entries() -> None:
    """Rebuild the entry list from ``state.fs_entries`` (main thread).

    Two entries per row (e44s04) keeps the window short; every cell keeps its
    own thumbnail, selectable and context-menu binding.
    """
    if not dpg.does_item_exist(FILE_MANAGER_ENTRIES_TAG):
        return
    dpg.delete_item(FILE_MANAGER_ENTRIES_TAG, children_only=True)
    total = len(state.fs_entries)
    for start in range(0, total, FS_ENTRIES_COLUMNS):
        row = dpg.add_group(horizontal=True, parent=FILE_MANAGER_ENTRIES_TAG)
        for index in range(start, min(start + FS_ENTRIES_COLUMNS, total)):
            entry = state.fs_entries[index]
            cell = dpg.add_group(horizontal=True, parent=row)
            thumb_tag = f"fs_thumb_{index}"
            _fs_entry_thumb(entry, parent=cell, thumb_tag=thumb_tag)
            item_tag = f"fs_entry_{index}"
            dpg.add_selectable(
                label=_fs_entry_label(entry),
                parent=cell,
                tag=item_tag,
                width=FS_ENTRY_LABEL_WIDTH,
                callback=_on_fs_entry_click,
                user_data=entry,
            )
            _fs_bind_row_menu(item_tag, thumb_tag, entry)


FS_ROW_POPUP_TAG = "fs_row_popup"


def _fs_bind_row_menu(item_tag: str, thumb_tag: str, entry: dict[str, Any]) -> None:
    """Bind the row's right-click menu to the name AND the thumbnail (e44s05)."""
    registry = f"fs_row_reg_{item_tag}"
    if dpg.does_item_exist(registry):
        dpg.delete_item(registry)
    with dpg.item_handler_registry(tag=registry):
        dpg.add_item_clicked_handler(button=1, callback=_on_fs_entry_right_click, user_data=entry)
    dpg.bind_item_handler_registry(item_tag, registry)
    dpg.bind_item_handler_registry(thumb_tag, registry)


def _on_fs_entry_right_click(
    sender: Any = None, app_data: Any = None, user_data: Any = None
) -> None:
    """Right-click a file row: Add to session, plus Preview... for videos (e44s05)."""
    entry = user_data if isinstance(user_data, dict) else {}
    if entry.get("kind") != "file" or entry.get("media_kind") not in ("video", "image"):
        return
    path = os.path.join(state.fs_current_path, str(entry.get("name") or ""))
    if dpg.does_item_exist(FS_ROW_POPUP_TAG):
        dpg.delete_item(FS_ROW_POPUP_TAG)
    position = dpg.get_mouse_pos(local=False)
    with dpg.window(
        tag=FS_ROW_POPUP_TAG,
        popup=True,
        no_title_bar=True,
        pos=position,
        min_size=(200, 10),
    ):
        dpg.add_text(os.path.basename(path))
        dpg.add_button(label="Add to session", user_data=path, callback=_on_fs_add_to_session_click)
        if entry.get("media_kind") == "video":
            dpg.add_button(label="Preview...", user_data=path, callback=_on_fs_preview_click)
    dpg.show_item(FS_ROW_POPUP_TAG)


def _on_fs_add_to_session_click(
    sender: Any = None, app_data: Any = None, user_data: Any = None
) -> None:
    """The row popup's Add to session item: append the clicked file (e44s05)."""
    if dpg.does_item_exist(FS_ROW_POPUP_TAG):
        dpg.delete_item(FS_ROW_POPUP_TAG)
    fs_add_path_to_draft(str(user_data or ""))


def _on_fs_preview_click(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """The row popup's Preview... item: open the file preview (e43s04)."""
    if dpg.does_item_exist(FS_ROW_POPUP_TAG):
        dpg.delete_item(FS_ROW_POPUP_TAG)
    start_file_preview(str(user_data))


def start_file_preview(path: str, *_args: Any) -> None:
    """Preview a video FILE from the File Manager over /fs/raw (e43s04).

    Reuses the e38 Preview window and player (one preview at a time); nothing is
    ever sent to vimix, so watching a clip cannot disturb the live session.
    """
    global _preview_player, _preview_error_shown
    host, port = _fs_endpoint()
    label = os.path.basename(str(path))
    if not host or not port:
        _preview_status("viOSC endpoint not configured.")
        _open_preview_window(label, message="viOSC endpoint not configured.")
        return
    close_source_preview()  # one preview at a time (e38 rule)
    _preview_error_shown = False
    state.preview_error = None
    state.preview_active = f"{FS_THUMB_PREFIX}{path}"
    state.preview_playing = True
    _open_preview_window(label)
    player = preview.PreviewPlayer(state.preview_active, url=fsclient.raw_url(host, port, path))
    _preview_player = player
    player.start()


def _fs_thumb_texture_tag(path: str) -> str:
    """The texture tag the shared decoder creates for one file's thumbnail."""
    return f"tex_{FS_THUMB_PREFIX}{path}_0"


def _fs_media_path(entry: dict[str, Any]) -> str | None:
    """The absolute path of a media entry on the current page, else None."""
    if entry.get("kind") != "file" or entry.get("media_kind") not in ("video", "image"):
        return None
    return os.path.join(state.fs_current_path, str(entry.get("name") or ""))


def _fs_entry_thumb(entry: dict[str, Any], parent: Any, thumb_tag: str) -> None:
    """The row's 64x36 preview when its texture exists, else a placeholder.

    ``thumb_tag`` is the widget tag the row menu binds to (e44s05), so a
    right-click on the thumbnail opens the same menu as the name.
    """
    path = _fs_media_path(entry)
    if path is not None and dpg.does_item_exist(_fs_thumb_texture_tag(path)):
        dpg.add_image(
            _fs_thumb_texture_tag(path),
            parent=parent,
            tag=thumb_tag,
            width=FS_THUMB_W,
            height=FS_THUMB_H,
        )
        return
    dpg.add_text("  ", parent=parent, tag=thumb_tag)


def _fs_request_thumbnails(entries: list[dict[str, Any]]) -> None:
    """Ask for the current page's media thumbnails, lazily and bounded (e43s03).

    Only video/image files are requested, entries whose texture already exists
    are skipped, and the page contributes at most FS_THUMB_MAX_REQUESTS paths.
    Stale work is DROPPED first: a navigation invalidates the previous page's
    queue, which is the debounce (no timer needed — the user paces navigation).
    """
    while not state.fs_thumb_queue.empty():
        with contextlib.suppress(queue.Empty):
            state.fs_thumb_queue.get_nowait()
            state.fs_thumb_queue.task_done()
    state.fs_thumb_requested.clear()
    requested = 0
    for entry in entries:
        if requested >= FS_THUMB_MAX_REQUESTS:
            break
        path = _fs_media_path(entry)
        if path is None or dpg.does_item_exist(_fs_thumb_texture_tag(path)):
            continue
        state.fs_thumb_requested.add(path)
        state.fs_thumb_queue.put(path)
        requested += 1


def _fs_on_thumb_texture(name: str) -> None:
    """Repaint the browser when one of ITS thumbnails lands (e43s03)."""
    if not name.startswith(FS_THUMB_PREFIX):
        return
    path = name[len(FS_THUMB_PREFIX) :]
    if state.fs_current_path and os.path.dirname(path) == state.fs_current_path:
        _fs_render_entries()


def _on_fs_entry_click(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """A directory enters it; a file becomes the selection (e43s02 tracer)."""
    entry = user_data if isinstance(user_data, dict) else {}
    if entry.get("kind") == "dir":
        fs_navigate(os.path.join(state.fs_current_path, str(entry.get("name") or "")))
        return
    state.fs_selected = str(entry.get("name") or "")


def fs_file_step(delta: int, *_args: Any) -> None:
    """Select the next/previous entry of the File Manager listing (wrap) (e54s02).

    The walk follows `state.fs_entries` in list order (directories included); an
    absent/unknown selection starts at the first entry going forward and the last
    one going backward; an empty listing is a no-op. The selection is reflected
    on the entry selectables so a rotary step is visible like a click.
    """
    names = [str(entry.get("name") or "") for entry in state.fs_entries]
    names = [name for name in names if name]
    if not names:
        return
    if state.fs_selected in names:
        index = (names.index(state.fs_selected) + int(delta)) % len(names)
    else:
        index = 0 if int(delta) >= 0 else len(names) - 1
    state.fs_selected = names[index]
    _highlight_fs_selection()


def _highlight_fs_selection() -> None:
    """Reflect `state.fs_selected` on the File Manager entry selectables (e54s02)."""
    for index, entry in enumerate(state.fs_entries):
        tag = f"fs_entry_{index}"
        if dpg.does_item_exist(tag):
            dpg.set_value(tag, str(entry.get("name") or "") == state.fs_selected)


def fs_go_up(*_args: Any) -> None:
    """Up one level, but never above the configured roots."""
    current = state.fs_current_path
    if not current:
        return
    roots = [str(r.get("path")) for r in state.fs_roots]
    parent = os.path.dirname(current.rstrip("/")) or "/"
    inside = any(parent == r or parent.startswith(r.rstrip("/") + "/") for r in roots)
    if current in roots or not inside:
        return
    fs_navigate(parent)


def _on_fs_root_selected(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """Roots combo: navigate to the chosen Media Root."""
    if app_data:
        fs_navigate(str(app_data))


def _exec_file_manager_toggle(params: dict[str, Any], value: int) -> None:
    """e43s02: a momentary press shows or hides the File Manager window."""
    if value < MIDI_CC_TRIGGER_THRESHOLD:
        return
    toggle_file_manager_window()


# e43s05: SESSION DRAFTS — named, ordered file sets edited here and written as a
# vimix .mix only on commit (e43s06/s07). The library is application-level (it
# survives project changes) and is saved on a debounce after any mutation.
FS_DRAFTS_GROUP = "fs_drafts_group"
FS_DRAFT_FILES_GROUP = "fs_draft_files_group"


def _drafts_load() -> None:
    """Load the application-level draft library (boot + an explicit reload)."""
    if not state.drafts_path:
        state.drafts_path = drafts.default_path()
    state.drafts_library = drafts.load_library(state.drafts_path)
    state.drafts_selected = None
    state.drafts_dirty = False


def _drafts_mark_dirty(now: float | None = None) -> None:
    """Record that the library changed (the tick persists it after the debounce)."""
    state.drafts_dirty = True
    state.drafts_dirty_at = time.monotonic() if now is None else now


def tick_drafts(now: float | None = None) -> None:
    """Main-loop tick: persist the draft library once the debounce elapses."""
    if not state.drafts_dirty:
        return
    stamp = time.monotonic() if now is None else now
    if stamp - state.drafts_dirty_at < DRAFTS_SAVE_DEBOUNCE_S:
        return
    if drafts.save_library(state.drafts_path, state.drafts_library):
        state.drafts_dirty = False


def refresh_drafts_ui(*_args: Any) -> None:
    """Rebuild the drafts list and the selected draft's file list (main thread)."""
    if not dpg.does_item_exist(FS_DRAFTS_GROUP):
        return
    dpg.delete_item(FS_DRAFTS_GROUP, children_only=True)
    library_drafts = list(state.drafts_library.get("drafts", []))
    for start in range(0, len(library_drafts), FS_ENTRIES_COLUMNS):
        row = dpg.add_group(horizontal=True, parent=FS_DRAFTS_GROUP)
        for draft in library_drafts[start : start + FS_ENTRIES_COLUMNS]:
            marked = "* " if draft.get("id") == state.drafts_selected else ""
            dpg.add_selectable(
                label=f"{marked}{draft.get('name')} ({len(draft.get('files', []))})",
                parent=row,
                tag=f"fs_draft_{draft.get('id')}",
                width=FS_DRAFT_LABEL_WIDTH,
                callback=fs_select_draft,
                user_data={"id": draft.get("id")},
            )
    if not dpg.does_item_exist(FS_DRAFT_FILES_GROUP):
        return
    dpg.delete_item(FS_DRAFT_FILES_GROUP, children_only=True)
    current = (
        drafts.find_draft(state.drafts_library, state.drafts_selected)
        if state.drafts_selected is not None
        else None
    )
    if current is None:
        return
    for index, path in enumerate(current.get("files", [])):
        row = dpg.add_group(horizontal=True, parent=FS_DRAFT_FILES_GROUP)
        dpg.add_text(f"{index + 1}.", parent=row)
        dpg.add_text(os.path.basename(str(path)), parent=row)
        dpg.add_input_float(
            default_value=drafts.file_alpha(current, str(path)),
            width=FS_DRAFT_ALPHA_WIDTH,
            step=FS_DRAFT_ALPHA_STEP,
            format="%.2f",
            parent=row,
            tag=f"{FS_DRAFT_ALPHA_TAG}_{index}",
            callback=fs_draft_set_alpha,
            user_data=str(path),
        )
        dpg.add_button(
            label="^",
            width=24,
            parent=row,
            callback=fs_draft_file_move,
            user_data={"path": path, "delta": -1},
        )
        dpg.add_button(
            label="v",
            width=24,
            parent=row,
            callback=fs_draft_file_move,
            user_data={"path": path, "delta": 1},
        )
        dpg.add_button(
            label="x", width=24, parent=row, callback=fs_draft_file_remove, user_data=path
        )


def fs_new_draft(*_args: Any) -> None:
    """Create, select and persist a fresh draft."""
    draft = drafts.create_draft(state.drafts_library)
    state.drafts_selected = int(draft["id"])
    _drafts_mark_dirty()
    refresh_drafts_ui()


def fs_select_draft(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """Select a draft in the list."""
    payload = user_data if isinstance(user_data, dict) else {}
    if payload.get("id") is not None:
        state.drafts_selected = int(payload["id"])
        refresh_drafts_ui()


def fs_delete_selected_draft(*_args: Any) -> None:
    """Delete the selected draft (never touches a file on machine A)."""
    if state.drafts_selected is None:
        return
    if drafts.delete_draft(state.drafts_library, state.drafts_selected):
        state.drafts_selected = None
        _drafts_mark_dirty()
        refresh_drafts_ui()


def fs_add_path_to_draft(path: str) -> None:
    """Add one path to the selected draft, creating a draft when needed (e44s05)."""
    if not str(path).strip():
        return
    if state.drafts_selected is None:
        fs_new_draft()
    if state.drafts_selected is None:
        return
    if drafts.add_files(state.drafts_library, state.drafts_selected, [str(path)]):
        _drafts_mark_dirty()
        refresh_drafts_ui()


def fs_draft_file_move(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """Move one file up/down inside the selected draft."""
    payload = user_data if isinstance(user_data, dict) else {}
    if state.drafts_selected is None:
        return
    moved = drafts.move_file(
        state.drafts_library,
        state.drafts_selected,
        str(payload.get("path") or ""),
        int(payload.get("delta") or 0),
    )
    if moved:
        _drafts_mark_dirty()
        refresh_drafts_ui()


def fs_draft_file_remove(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """Remove one file from the selected draft."""
    if state.drafts_selected is None:
        return
    if drafts.remove_file(state.drafts_library, state.drafts_selected, str(user_data or "")):
        _drafts_mark_dirty()
        refresh_drafts_ui()


def fs_draft_set_alpha(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """Store the alpha typed on one draft source row (e45s01).

    The value arrives in ``app_data``: it is never read back from the widget, so
    a widget that has already been rebuilt can never corrupt it.
    """
    if state.drafts_selected is None:
        return
    if drafts.set_file_alpha(
        state.drafts_library, state.drafts_selected, str(user_data or ""), app_data
    ):
        _drafts_mark_dirty()


# e43s07: WRITE / LOAD — Write generates the .mix on machine A (never touching
# the live session); Load always asks for confirmation, offers an optional
# transition and sends /vimix/session/open through the existing OSC client.
FS_DRAFT_STATUS_TAG = "fs_draft_status"
FS_DRAFT_TRANSITION_TAG = "fs_draft_transition"
FS_DRAFT_CONFIRM_TAG = "fs_draft_load_confirm"
FS_DRAFT_LEARN_SLOT = "fs_drafts_learn_slot"
FS_DRAFT_RENAME_TAG = "fs_draft_rename_confirm"
FS_DRAFT_RENAME_INPUT_TAG = "fs_draft_rename_input"
FS_DRAFTS_SEPARATOR_TAG = "fs_drafts_separator"
FS_DRAFT_LABEL_WIDTH = 220
FS_DRAFT_ALPHA_TAG = "fs_draft_alpha"
FS_DRAFT_ALPHA_WIDTH = 70
FS_DRAFT_ALPHA_STEP = 0.1
# e45s02: the Send-time reassignment panel.
REMAP_NONE = "\u2014"
REMAP_TIMEOUT_S = 60.0
FS_REMAP_GROUP_TAG = "fs_remap_group"
REMAP_ROW_HEIGHT = 28
FS_REMAP_MIN_HEIGHT = 56
FS_REMAP_MAX_HEIGHT = 300
REMAP_PANEL_CHROME = 66  # panel title + the Posizionale button + spacing
FS_SESSION_PICKER_TAG = "fs_session_picker"
FS_SESSION_LIST_TAG = "fs_session_list"
FS_SESSION_DETAIL_TAG = "fs_session_detail"
FS_SESSION_STATUS_TAG = "fs_session_status"
DRAFT_CONFIRM_WIDTH = 560
DRAFT_CONFIRM_HEIGHT = 200
DRAFT_CONFIRM_MIN_WIDTH = 420
DRAFT_CONFIRM_MIN_HEIGHT = 170
DRAFT_RENAME_WIDTH = 380
DRAFT_RENAME_HEIGHT = 150
DRAFT_PICKER_WIDTH = 620
DRAFT_PICKER_HEIGHT = 480
DRAFT_PICKER_LIST_HEIGHT = 200


def _drafts_status(text: str) -> None:
    """Show the last Write/Load outcome in the drafts pane."""
    state.drafts_status = str(text)
    if dpg.does_item_exist(FS_DRAFT_STATUS_TAG):
        dpg.set_value(FS_DRAFT_STATUS_TAG, state.drafts_status)


def _selected_draft() -> dict[str, Any] | None:
    """The currently selected draft, or None."""
    if state.drafts_selected is None:
        return None
    return drafts.find_draft(state.drafts_library, state.drafts_selected)


def fs_open_rename_draft(*_args: Any) -> None:
    """Open the Rename modal for the selected draft (e44s01)."""
    draft = _selected_draft()
    if draft is None:
        _drafts_status("Select a draft first.")
        return
    if dpg.does_item_exist(FS_DRAFT_RENAME_TAG):
        dpg.delete_item(FS_DRAFT_RENAME_TAG)
    with dpg.window(
        label="Rename session",
        tag=FS_DRAFT_RENAME_TAG,
        modal=True,
        width=DRAFT_RENAME_WIDTH,
        height=DRAFT_RENAME_HEIGHT,
        no_resize=True,
    ):
        dpg.add_input_text(
            tag=FS_DRAFT_RENAME_INPUT_TAG,
            default_value=str(draft.get("name") or ""),
            width=DRAFT_RENAME_WIDTH - 40,
        )
        dpg.add_separator()
        with dpg.group(horizontal=True):
            dpg.add_button(label="Cancel", width=130, callback=cancel_draft_rename)
            dpg.add_button(label="Rename", width=130, callback=confirm_draft_rename)
    show_centered_window(FS_DRAFT_RENAME_TAG)  # e55: dialogs open centered


def cancel_draft_rename(*_args: Any) -> None:
    """Rename modal Cancel: nothing changes."""
    if dpg.does_item_exist(FS_DRAFT_RENAME_TAG):
        dpg.delete_item(FS_DRAFT_RENAME_TAG)


def confirm_draft_rename(*_args: Any) -> None:
    """Rename modal confirm: validate, apply and persist.

    The input is read BEFORE the modal is deleted: DearPyGui returns None for a
    deleted item, so a post-close read would silently discard the name
    (BUG-2026-09-15T162441).
    """
    name = str(dpg.get_value(FS_DRAFT_RENAME_INPUT_TAG) or "")
    if dpg.does_item_exist(FS_DRAFT_RENAME_TAG):
        dpg.delete_item(FS_DRAFT_RENAME_TAG)
    if state.drafts_selected is None:
        return
    if drafts.rename_draft(state.drafts_library, state.drafts_selected, name):
        _drafts_mark_dirty()
        refresh_drafts_ui()
        _drafts_status(f"Renamed: {name.strip()}")
    else:
        _drafts_status("Enter a non-empty name not already used.")


def fs_open_sessions(*_args: Any) -> None:
    """Open the existing-sessions picker and load the list from A (e44s03)."""
    if dpg.does_item_exist(FS_SESSION_PICKER_TAG):
        dpg.delete_item(FS_SESSION_PICKER_TAG)
    with dpg.window(
        label="Open session",
        tag=FS_SESSION_PICKER_TAG,
        modal=True,
        width=DRAFT_PICKER_WIDTH,
        height=DRAFT_PICKER_HEIGHT,
        no_resize=True,
    ):
        themed_text("", slot="text_dim", tag=FS_SESSION_STATUS_TAG)
        with dpg.child_window(
            height=DRAFT_PICKER_LIST_HEIGHT, border=False, tag="fs_session_scroll"
        ):
            pass
        with dpg.group(parent="fs_session_scroll", tag=FS_SESSION_LIST_TAG):
            pass
        with dpg.group(tag=FS_SESSION_DETAIL_TAG):
            pass
        dpg.add_separator()
        with dpg.group(horizontal=True):
            dpg.add_button(label="Close", width=130, callback=close_session_picker)
            dpg.add_button(label="Import as draft", width=170, callback=import_selected_session)
    show_centered_window(FS_SESSION_PICKER_TAG)  # e55: dialogs open centered
    _fs_request_sessions()


def close_session_picker(*_args: Any) -> None:
    """Close the sessions picker without side effects."""
    if dpg.does_item_exist(FS_SESSION_PICKER_TAG):
        dpg.delete_item(FS_SESSION_PICKER_TAG)


def _fs_request_sessions() -> None:
    """Fetch the written sessions from A (single-flight, HIGH-1)."""
    if state.fs_sessions_busy:
        return
    host, port = _fs_endpoint()
    if not host or not port:
        state.fs_sessions_status = "viOSC endpoint not configured."
        _set_session_status(state.fs_sessions_status)
        return
    state.fs_sessions_busy = True
    state.fs_sessions_status = "Loading sessions..."
    _set_session_status(state.fs_sessions_status)
    threading.Thread(target=_fs_sessions_worker, args=(host, port), daemon=True).start()


def _fs_sessions_worker(host: str, port: int) -> None:
    """Worker: list the sessions on machine A, report on the main thread."""
    sessions, status = fsclient.fetch_sessions(host, port)
    state.ui_task_queue.put(lambda: _fs_apply_sessions(sessions, status))


def _set_session_status(text: str) -> None:
    """Push the picker's status line when the picker is open."""
    if dpg.does_item_exist(FS_SESSION_STATUS_TAG):
        dpg.set_value(FS_SESSION_STATUS_TAG, text)


def _fs_apply_sessions(sessions: list | None, status: int | None) -> None:
    """Main thread: store the sessions on A and render the picker."""
    state.fs_sessions_busy = False
    if sessions is None:
        state.fs_sessions_status = _fs_error_text(status)
        _set_session_status(state.fs_sessions_status)
        return
    state.fs_sessions = [item for item in sessions if isinstance(item, dict)]
    state.fs_sessions_status = f"{len(state.fs_sessions)} sessions"
    _set_session_status(state.fs_sessions_status)
    _render_sessions()


def _selected_session() -> dict[str, Any] | None:
    """The picker's selected session entry, or None."""
    for session in state.fs_sessions:
        if str(session.get("file") or "") == state.fs_sessions_selected:
            return session
    return None


def _session_sources(session: dict[str, Any]) -> list[dict[str, Any]]:
    """The valid source entries of one session."""
    return [item for item in (session.get("sources") or []) if isinstance(item, dict)]


def _render_sessions() -> None:
    """Rebuild the picker's session list and the selected session's videos."""
    if dpg.does_item_exist(FS_SESSION_LIST_TAG):
        dpg.delete_item(FS_SESSION_LIST_TAG, children_only=True)
        for session in state.fs_sessions:
            path = str(session.get("file") or "")
            marked = "* " if path == state.fs_sessions_selected else ""
            count = len(_session_sources(session))
            dpg.add_selectable(
                label=f"{marked}{session.get('name')} ({count} videos)",
                parent=FS_SESSION_LIST_TAG,
                callback=fs_select_session,
                user_data=path,
            )
    if not dpg.does_item_exist(FS_SESSION_DETAIL_TAG):
        return
    dpg.delete_item(FS_SESSION_DETAIL_TAG, children_only=True)
    current = _selected_session()
    if current is None:
        return
    sources = _session_sources(current)
    if not sources:
        themed_text(
            "No videos found in this session.", slot="text_dim", parent=FS_SESSION_DETAIL_TAG
        )
        return
    for source in sources:
        dpg.add_text(f"{source.get('name')}  -  {source.get('uri')}", parent=FS_SESSION_DETAIL_TAG)


def fs_select_session(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """Select one session in the picker."""
    state.fs_sessions_selected = str(user_data or "")
    _render_sessions()


def import_selected_session(*_args: Any) -> None:
    """Import the selected session as a NEW editable draft (the .mix is untouched)."""
    current = _selected_session()
    if current is None:
        state.fs_sessions_status = "Select a session first."
        _set_session_status(state.fs_sessions_status)
        return
    name = str(current.get("name") or "Session")
    draft = drafts.create_draft(state.drafts_library, name)
    files = [
        str(source.get("uri"))
        for source in _session_sources(current)
        if str(source.get("uri") or "").strip()
    ]
    drafts.add_files(state.drafts_library, int(draft["id"]), files)
    state.drafts_selected = int(draft["id"])
    _drafts_mark_dirty()
    refresh_drafts_ui()
    _drafts_status(f"Imported '{draft.get('name')}' ({len(files)} files)")
    close_session_picker()


def _draft_needs_write(draft: dict[str, Any]) -> bool:
    """True when the draft was never written or its files changed since."""
    recorded = state.drafts_written.get(int(draft["id"]))
    files = tuple(str(path) for path in draft.get("files", []))
    return recorded is None or recorded[1] != files


def _draft_error_text(status: int | None, tag: str | None) -> str:
    """A short, honest message for a rejected session write."""
    if status == 401:
        return "Not paired with viOSC: use Settings > Pair with viOSC..."
    if status is None:
        return "viOSC unreachable."
    if tag == "missing_file":
        return "A file in the draft no longer exists on machine A."
    if tag == "no_files":
        return "The draft is empty."
    if tag == "bad_name":
        return "That draft name cannot be used as a file name."
    if tag == "unwritable":
        return "viOSC could not write the session file."
    return f"Write failed ({status})."


def fs_write_draft(*_args: Any) -> None:
    """Write the selected draft as a .mix on machine A (never loads it)."""
    draft = _selected_draft()
    if draft is None:
        _drafts_status("Select a draft first.")
        return
    if not draft.get("files"):
        _drafts_status("The draft is empty.")
        return
    host, port = _fs_endpoint()
    if not host or not port:
        _drafts_status("viOSC endpoint not configured.")
        return
    _drafts_status("Writing...")
    threading.Thread(
        target=_fs_write_worker,
        args=(
            host,
            port,
            int(draft["id"]),
            str(draft["name"]),
            [str(p) for p in draft["files"]],
        ),
        kwargs={"alphas": drafts.draft_alphas(draft)},
        daemon=True,
    ).start()


def _fs_write_worker(
    host: str,
    port: int,
    draft_id: int,
    name: str,
    files: list[str],
    *,
    then_load: bool = False,
    alphas: dict[str, float] | None = None,
) -> None:
    """Worker: write the draft, report on the main thread (HIGH-1)."""
    result, status = fsclient.write_session(host, port, name, files, overwrite=True, alphas=alphas)
    state.ui_task_queue.put(
        lambda: _fs_apply_write(draft_id, files, result, status, then_load=then_load)
    )


def _fs_apply_write(
    draft_id: int,
    files: list[str],
    result: dict | None,
    status: int | None,
    *,
    then_load: bool = False,
) -> None:
    """Main thread: record the written path (or word the rejection)."""
    if not isinstance(result, dict) or status != 200:
        tag = result.get("error") if isinstance(result, dict) else None
        _drafts_status(_draft_error_text(status, tag))
        return
    path = str(result.get("file") or "")
    state.drafts_written[int(draft_id)] = (path, tuple(str(p) for p in files))
    state.drafts_sources[int(draft_id)] = [
        item for item in (result.get("sources") or []) if isinstance(item, dict)
    ]
    _drafts_status(f"Written: {path}")
    if then_load and path:
        _show_draft_load_confirm(path)


def fs_load_draft(*_args: Any) -> None:
    """Load the selected draft, writing it first when it changed.

    The `.mix` is only a preparation: nothing reaches vimix until the user
    confirms the modal, so a stray click can never replace the live session.
    """
    draft = _selected_draft()
    if draft is None or not draft.get("files"):
        _drafts_status("Select a non-empty draft first.")
        return
    recorded = state.drafts_written.get(int(draft["id"]))
    if not _draft_needs_write(draft) and recorded is not None:
        _show_draft_load_confirm(recorded[0])
        return
    host, port = _fs_endpoint()
    if not host or not port:
        _drafts_status("viOSC endpoint not configured.")
        return
    _drafts_status("Writing...")
    threading.Thread(
        target=_fs_write_worker,
        args=(
            host,
            port,
            int(draft["id"]),
            str(draft["name"]),
            [str(p) for p in draft["files"]],
        ),
        kwargs={"then_load": True, "alphas": drafts.draft_alphas(draft)},
        daemon=True,
    ).start()


def draft_visibility_warning(draft: dict[str, Any] | None) -> str:
    """The Send warning when no source of the draft would be visible (e45s01)."""
    if draft is None:
        return ""
    if any(alpha > 0 for alpha in drafts.draft_alphas(draft).values()):
        return ""
    return "Warning: no source has alpha > 0 - the session will load with nothing visible."


def _source_index_by_name() -> dict[str, int]:
    """The live sources' name -> vimix index (the positional pre-selection)."""
    by_name: dict[str, int] = {}
    sources = state.global_vimix_state.get("sources") or {}
    for key, props in sources.items():
        if not isinstance(props, dict):
            continue
        name = str(props.get("name") or key)
        raw_index = props.get("index")
        try:
            index = int(raw_index) if raw_index is not None else int(key)
        except (TypeError, ValueError):
            continue
        by_name[name] = index
    return by_name


def remap_bindings() -> list[dict[str, Any]]:
    """The bound Mapper rows and Sequencer tracks for the Send panel (e45s02)."""
    index_by_name = _source_index_by_name()
    bindings: list[dict[str, Any]] = []
    for position, target in enumerate(mapper.row_targets()):
        bindings.append(
            {
                "kind": "mapper",
                "key": str(target),
                "label": f"Mapper {position + 1}",
                "index": index_by_name.get(str(target)),
            }
        )
    for row, track in enumerate(state.tracks_data):
        track_target = track.get("target_id")
        if track_target:
            bindings.append(
                {
                    "kind": "seq",
                    "key": int(row),
                    "label": f"Seq {row + 1}",
                    "index": index_by_name.get(str(track_target)),
                }
            )
    return bindings


def remap_options(sources: list[dict[str, Any]]) -> list[str]:
    """The select items: ``-`` plus ``N. name`` per new-session source."""
    return [REMAP_NONE] + [
        f"{position + 1}. {source.get('name')}" for position, source in enumerate(sources)
    ]


def remap_preselection(options: list[str], index: int | None) -> str:
    """The positional default for a binding whose old source sat at ``index``."""
    if index is None or index < 0 or index + 1 >= len(options):
        return REMAP_NONE
    return options[index + 1]


def _remap_row_tag(kind: str, key: Any) -> str:
    return f"fs_remap_{kind}_{key}"


def remap_fill_positional(*_args: Any) -> None:
    """The panel's 'Posizionale' fill: every select back to its positional default."""
    for binding in state.remap_bindings_cache:
        tag = str(binding.get("tag") or "")
        if dpg.does_item_exist(tag):
            dpg.set_value(tag, str(binding.get("preselected") or REMAP_NONE))


def _collect_remap_assignments() -> list[dict[str, Any]]:
    """Read the panel's selects into assignments (while the modal is open)."""
    assignments: list[dict[str, Any]] = []
    for binding in state.remap_bindings_cache:
        tag = str(binding.get("tag") or "")
        options = binding.get("options") or []
        sources = binding.get("sources") or []
        label = str(dpg.get_value(tag) or "") if dpg.does_item_exist(tag) else REMAP_NONE
        if label == REMAP_NONE or label not in options:
            continue
        position = options.index(label) - 1
        if not 0 <= position < len(sources):
            continue
        target = str(sources[position].get("name") or "")
        if target:
            assignments.append({"kind": binding["kind"], "key": binding["key"], "target": target})
    return assignments


def remap_panel_height(count: int) -> int:
    """The remap child height for ``count`` rows: fits the content, capped (scroll)."""
    return max(FS_REMAP_MIN_HEIGHT, min(FS_REMAP_MAX_HEIGHT, max(0, count) * REMAP_ROW_HEIGHT))


def _build_remap_panel(
    bindings: list[dict[str, Any]], sources: list[dict[str, Any]], panel_height: int
) -> None:
    """Render the reassignment selects for the bound rows (e45s02)."""
    state.remap_bindings_cache = []
    options = remap_options(sources)
    themed_text("Reassign to the new session", slot="text_dim")
    with dpg.child_window(height=panel_height, border=False, tag="fs_remap_scroll"):
        pass
    with dpg.group(parent="fs_remap_scroll", tag=FS_REMAP_GROUP_TAG):
        for binding in bindings:
            tag = _remap_row_tag(str(binding["kind"]), binding["key"])
            preselected = remap_preselection(options, binding.get("index"))
            dpg.add_combo(
                label=str(binding["label"]),
                items=options,
                default_value=preselected,
                width=300,
                tag=tag,
            )
            state.remap_bindings_cache.append(
                {
                    **binding,
                    "tag": tag,
                    "options": options,
                    "sources": sources,
                    "preselected": preselected,
                }
            )
    dpg.add_button(label="Posizionale", callback=remap_fill_positional)


def tick_send_remap(now: float | None = None) -> None:
    """Main-loop tick: drop a reassignment whose new session never appeared."""
    if not state.send_remap_pending:
        return
    stamp = time.monotonic() if now is None else now
    if stamp - state.send_remap_armed_at < REMAP_TIMEOUT_S:
        return
    state.send_remap_pending = None
    _drafts_status("Reassignment skipped: the new session did not appear.")


def _apply_pending_remap(live_ids: set[str]) -> None:
    """Apply the chosen reassignment once the new sources are live (e45s02)."""
    pending = state.send_remap_pending
    if not pending:
        return
    if not {str(item["target"]) for item in pending} <= live_ids:
        return  # wait for the whole new session
    moved = 0
    for item in pending:
        target = str(item["target"])
        if item["kind"] == "mapper":
            old = str(item["key"])
            moved += mapper.retarget_source(old, target)
            if old in state.source_anchors:
                state.source_anchors[target] = state.source_anchors.pop(old)
        else:
            assign_target_to_track(int(item["key"]), target)
            moved += 1
    state.send_remap_pending = None
    refresh_mapper_ui()
    _drafts_status(f"Reassigned {moved} bindings to the new session.")


def _show_draft_load_confirm(path: str) -> None:
    """Open the Load confirmation (replaces the live session, always asked).

    The window is sized from its content (the e45s02 panel follows the number of
    bound rows) and stays resizable (BUG-2026-09-15T201625).
    """
    state.drafts_pending_path = str(path)
    if dpg.does_item_exist(FS_DRAFT_CONFIRM_TAG):
        dpg.delete_item(FS_DRAFT_CONFIRM_TAG)
    draft = _selected_draft()
    sources = list(state.drafts_sources.get(int(draft["id"])) or []) if draft else []
    bindings = remap_bindings()
    show_panel = bool(sources and bindings)
    panel_height = remap_panel_height(len(bindings)) if show_panel else 0
    height = DRAFT_CONFIRM_HEIGHT + (panel_height + REMAP_PANEL_CHROME if show_panel else 0)
    warning = draft_visibility_warning(draft)
    with dpg.window(
        label="Send session to vimix",
        tag=FS_DRAFT_CONFIRM_TAG,
        modal=True,
        width=DRAFT_CONFIRM_WIDTH,
        height=height,
        no_resize=False,
        min_size=(DRAFT_CONFIRM_MIN_WIDTH, DRAFT_CONFIRM_MIN_HEIGHT),
    ):
        dpg.add_text("This REPLACES the live vimix session.", wrap=DRAFT_CONFIRM_WIDTH - 40)
        dpg.add_text(os.path.basename(str(path)), wrap=DRAFT_CONFIRM_WIDTH - 40)
        if warning:
            dpg.add_text(warning, wrap=DRAFT_CONFIRM_WIDTH - 40)
        if show_panel:
            _build_remap_panel(bindings, sources, panel_height)
        dpg.add_input_float(
            label="Transition (s)",
            tag=FS_DRAFT_TRANSITION_TAG,
            default_value=0.0,
            width=120,
            step=0,
            format="%.1f",
        )
        dpg.add_separator()
        with dpg.group(horizontal=True):
            dpg.add_button(label="Cancel", width=130, callback=cancel_draft_load)
            dpg.add_button(label="Send", width=130, callback=confirm_draft_load)
    show_centered_window(FS_DRAFT_CONFIRM_TAG)  # e55: dialogs open centered


def cancel_draft_load(*_args: Any) -> None:
    """Confirmation Cancel: nothing is sent."""
    state.drafts_pending_path = None
    if dpg.does_item_exist(FS_DRAFT_CONFIRM_TAG):
        dpg.delete_item(FS_DRAFT_CONFIRM_TAG)


def _draft_transition_seconds() -> float:
    """The optional crossfade duration, clamped to a sane non-negative value."""
    try:
        return max(0.0, float(dpg.get_value(FS_DRAFT_TRANSITION_TAG) or 0.0))
    except (TypeError, ValueError):
        return 0.0


def confirm_draft_load(*_args: Any) -> None:
    """Confirmation Load: `/vimix/session/open s <path> [f <seconds>]`."""
    path = str(state.drafts_pending_path or "")
    # Read the transition while the modal still owns its input: on a deleted
    # item DearPyGui returns None, so reading after the close silently dropped
    # the crossfade argument (BUG-2026-09-15T162441).
    seconds = _draft_transition_seconds()
    assignments = _collect_remap_assignments()
    state.remap_bindings_cache = []
    if dpg.does_item_exist(FS_DRAFT_CONFIRM_TAG):
        dpg.delete_item(FS_DRAFT_CONFIRM_TAG)
    state.drafts_pending_path = None
    if not path:
        return
    args: list[Any] = [path]
    if seconds > 0:
        args.append(seconds)
    osc_client.send_message("/vimix/session/open", args)
    state.send_remap_pending = assignments or None
    state.send_remap_armed_at = time.monotonic()
    _drafts_status(f"Sent to vimix: {os.path.basename(path)}")


def fs_draft_step(delta: int, *_args: Any) -> None:
    """Select the next/previous draft (wrapping)."""
    ordered = [int(d.get("id")) for d in state.drafts_library.get("drafts", [])]
    if not ordered:
        return
    if state.drafts_selected in ordered:
        index = (ordered.index(state.drafts_selected) + int(delta)) % len(ordered)
    else:
        index = 0
    state.drafts_selected = ordered[index]
    refresh_drafts_ui()


def fs_draft_next(*_args: Any) -> None:
    """Select the next draft."""
    fs_draft_step(1)


def fs_draft_prev(*_args: Any) -> None:
    """Select the previous draft."""
    fs_draft_step(-1)


def _exec_draft_load(params: dict[str, Any], value: int) -> None:
    """e43s07: a momentary press asks to load the selected draft (with confirm)."""
    if value < MIDI_CC_TRIGGER_THRESHOLD:
        return
    fs_load_draft()


def _exec_draft_save(params: dict[str, Any], value: int) -> None:
    """e44s02: a momentary press saves the selected draft."""
    if value < MIDI_CC_TRIGGER_THRESHOLD:
        return
    fs_write_draft()


def _exec_draft_step(delta: int) -> Callable[[dict[str, Any], int], None]:
    """Build the next/previous draft executors."""

    def run(params: dict[str, Any], value: int) -> None:
        if value < MIDI_CC_TRIGGER_THRESHOLD:
            return
        fs_draft_step(delta)

    return run


def _sync_drafts_learn_markers() -> None:
    """(Re)render the drafts pane learn markers (e33 rule)."""
    if not dpg.does_item_exist(FS_DRAFT_LEARN_SLOT):
        return
    dpg.delete_item(FS_DRAFT_LEARN_SLOT, children_only=True)
    if not state.midi_learn_mode:
        return
    for action_id, tag in (
        (MIDI_ACTION_DRAFT_LOAD, "fs_mk_draft_load"),
        (MIDI_ACTION_DRAFT_SAVE, "fs_mk_draft_save"),
        (MIDI_ACTION_DRAFT_NEXT, "fs_mk_draft_next"),
        (MIDI_ACTION_DRAFT_PREV, "fs_mk_draft_prev"),
        (MIDI_ACTION_DRAFT_STEP, "fs_mk_draft_step"),
    ):
        learn_marker(
            action_id,
            {},
            parent=FS_DRAFT_LEARN_SLOT,
            tag=tag,
            tooltip=f"Map: {actions.action_label(action_id)}",
        )


def _sync_file_manager_learn_marker() -> None:
    """(Re)render the File Manager toggle's learn marker (e33 rule)."""
    if not dpg.does_item_exist(FILE_MANAGER_LEARN_SLOT):
        return
    dpg.delete_item(FILE_MANAGER_LEARN_SLOT, children_only=True)
    if state.midi_learn_mode:
        for action_id, tag in (
            (MIDI_ACTION_FILE_MANAGER_TOGGLE, "fs_mk_toggle"),
            (MIDI_ACTION_FILE_STEP, "fs_mk_file_step"),
            (MIDI_ACTION_FILE_NEXT, "fs_mk_file_next"),
            (MIDI_ACTION_FILE_PREV, "fs_mk_file_prev"),
        ):
            learn_marker(
                action_id,
                {},
                parent=FILE_MANAGER_LEARN_SLOT,
                tag=tag,
                tooltip=f"Map: {actions.action_label(action_id)}",
            )


def midi_action_beat_source(mode: str) -> None:
    """Select A's beat source — shared by A's mouse row and MIDI (e09).

    A keeps this door because it is the instance-0 write plus A's own widget sync; the
    per-instance door is `on_sequencer_beat_source` (e67s04).
    """
    state.beat_source = mode
    for m in BEAT_SOURCE_LABELS:
        dpg.set_value(f"cb_beat_{m}", m == state.beat_source)
    # e74s07: the Manual tools are ALWAYS visible; only the value they drive is
    # mode-dependent (a sequencer on Analyse must keep following the analyser).
    is_manual = state.beat_source == BEAT_SOURCE_MANUAL
    if is_manual:
        state.current_bpm = float(dpg.get_value("manual_bpm_input"))
        # e74s09: the value alone — the box already says what it is, and the prefix was
        # clipped ('BPM: 120.(…') in the narrowest box.
        dpg.set_value("testo_bpm", f"{state.current_bpm:.1f}")
        dpg.set_value("manual_bpm_text", f"{state.current_bpm:.0f}")


def on_sequencer_beat_source(sender: Any, app_data: Any, user_data: Any) -> None:
    """A beat-source checkbox of ONE sequencer (e67s04).

    `(index, source)` travels in `user_data` — never in a default argument, which DearPyGui's
    third positional overwrites with None (BUG-2026-10-12T230000).
    """
    index, source = user_data
    if source not in BEAT_SOURCE_LABELS:
        return
    if not app_data:
        dpg.set_value(sender, True)  # a beat source must remain selected
        return
    set_beat_source(index, source)
    for mode in BEAT_SOURCE_LABELS:
        tag = beat_checkbox_tag(index, mode)
        if dpg.does_item_exist(tag):
            dpg.set_value(tag, mode == source)


def on_beat_source(sender: Any, app_data: Any, user_data: Any) -> None:
    """A's beat-source checkbox (the wrapper the existing callers and tests address)."""
    on_sequencer_beat_source(sender, app_data, (0, user_data))


def on_sequencer_manual_bpm(sender: Any, app_data: Any, user_data: Any) -> None:
    """The manual BPM box of ONE sequencer (e67s04): the number belongs to its instance."""
    index = user_data if isinstance(user_data, int) else 0
    state.sequencer(index)["bpm"] = float(app_data)
    refresh_sequencer_bpm_readouts(index)


def on_manual_bpm(sender: Any, app_data: Any, user_data: Any) -> None:
    """A's manual BPM box (the wrapper the existing callers and tests address)."""
    on_sequencer_manual_bpm(sender, app_data, 0)


def refresh_sequencer_bpm_readouts(index: int) -> None:
    """Mirror ONE instance's manual BPM onto its own box and readouts (e67s04)."""
    bpm = float(state.sequencer(index)["bpm"])
    link_text = f"{state.link_tempo:.1f}" if state.link_available else "n/a"
    for base, text in (
        ("testo_bpm", f"{bpm:.1f}"),
        ("manual_bpm_text", f"{bpm:.0f}"),
        ("link_tempo_text", link_text),  # e75
    ):
        tag = sequencer_transport_tag(index, base)
        if dpg.does_item_exist(tag):
            dpg.set_value(tag, text)
    box = sequencer_transport_tag(index, "manual_bpm_input")
    if dpg.does_item_exist(box):
        dpg.set_value(box, round(bpm))


_last_link_readout: tuple[float, bool] | None = None


def tick_link_readout() -> None:
    """Mirror the Link tempo onto every Link readout when it changes (e75).

    The Link worker writes `state.link_tempo`; this is the main-thread half, and the
    signature gate keeps it idle-cheap (the value changes at most a few times a second).
    """
    global _last_link_readout
    signature = (round(float(state.link_tempo), 1), bool(state.link_available))
    if signature == _last_link_readout:
        return
    _last_link_readout = signature
    for index in range(state.sequencer_count()):
        refresh_sequencer_bpm_readouts(index)


# TAP's timestamps live per instance: index 0 is the list the app has always had, so A's
# behaviour is unchanged; B gets its own, so tapping B never touches A's tempo (e67s04).
_tap_times_by_index: dict[int, list[float]] = {0: tap_times}


def midi_action_transport_tap_index(index: int = 0) -> None:
    """Register a TAP for ONE sequencer and average THAT instance's last taps (e67s04)."""
    now = time.time()
    taps = _tap_times_by_index.setdefault(index, [])
    if taps and now - taps[-1] > TAP_STALE_SECONDS:
        taps.clear()  # stale tap starts a new sequence
    taps.append(now)
    del taps[:-TAP_MAX_TAPS]  # keep the most recent taps
    if len(taps) >= 2:
        intervals = [taps[i + 1] - taps[i] for i in range(len(taps) - 1)]
        state.sequencer(index)["bpm"] = round(60.0 / (sum(intervals) / len(intervals)), 2)
        refresh_sequencer_bpm_readouts(index)


def midi_action_transport_tap() -> None:
    """A's TAP (the MIDI executor and the existing tests address it)."""
    midi_action_transport_tap_index(0)


def tap_bpm(sender: Any, app_data: Any, user_data: Any) -> None:
    """The TAP button's callback: its instance rides in `user_data` (e67s04)."""
    index = user_data if isinstance(user_data, int) else 0
    midi_action_transport_tap_index(index)


def midi_beats_from_pulses(pulses: int) -> int:
    """Whole quarter-note beats contained in a MIDI clock pulse count (24 pulses/beat)."""
    return pulses // MIDI_CLOCK_PULSES_PER_BEAT


# ---------- e09: MIDI control engine ----------

# e33s02: momentary Mapper actions trigger at CC value >= MIDI_CC_TRIGGER_THRESHOLD
# (the shared threshold convention; lower values are a deliberate no-op).


def _log_stale_midi_target(action: str, detail: str) -> None:
    """Throttled diagnostic: a binding referenced an entity that no longer exists.

    A captured binding can outlive its target (the mapping was deleted, the
    mapper row vanished): the dispatch must be a logged no-op, never a crash.
    One line per second per action+detail pair, so different stale reasons
    under the same action still surface while a repeated press cannot flood.
    """
    now = time.time()
    key = f"{action}:{detail}"
    if now - _last_unknown_action_log.get(key, 0.0) < 1.0:
        return
    _last_unknown_action_log[key] = now
    append_log("MIDI", f"{action}: {detail}")


def _exec_mapper_enable(params: dict[str, Any], value: int) -> None:
    """e33s02: toggle a mapping's armed flag (note / CC >= 64); stale id no-op."""
    mid = int(params.get("mapping_id", -1))
    mapping = mapper.find_mapping(mid)
    if mapping is None:
        _log_stale_midi_target(MIDI_ACTION_MAPPER_ENABLE, f"no mapping {mid}")
        return
    if value < MIDI_CC_TRIGGER_THRESHOLD:
        return
    enabled = not bool(mapping["enabled"])
    mapper.set_mapping_enabled(mid, enabled)
    if dpg.does_item_exist(f"mapper_enable_{mid}"):
        dpg.set_value(f"mapper_enable_{mid}", enabled)  # the card checkbox follows in place
    refresh_binding_leds()  # e53s02


def _exec_mapper_reset(params: dict[str, Any], value: int) -> None:
    """e33s02: reset a mapping to its neutral default (same core as the R button)."""
    mid = int(params.get("mapping_id", -1))
    if mapper.find_mapping(mid) is None:
        _log_stale_midi_target(MIDI_ACTION_MAPPER_RESET, f"no mapping {mid}")
        return
    if value < MIDI_CC_TRIGGER_THRESHOLD:
        return
    reset_mapping(None, None, mid)  # neutral + widget re-sync, mouse-path identical


def _exec_mapping_copy(params: dict[str, Any], value: int) -> None:
    """e51s02: snapshot a Mapping into the clipboard (momentary marker)."""
    mid = int(params.get("mapping_id", -1))
    if mapper.find_mapping(mid) is None:
        _log_stale_midi_target(MIDI_ACTION_MAPPING_COPY, f"no mapping {mid}")
        return
    if value < MIDI_CC_TRIGGER_THRESHOLD:
        return
    copy_mapper_mapping(None, None, mid)


def _exec_mapping_cut(params: dict[str, Any], value: int) -> None:
    """e51s02: snapshot a Mapping into the clipboard and remove it."""
    mid = int(params.get("mapping_id", -1))
    if mapper.find_mapping(mid) is None:
        _log_stale_midi_target(MIDI_ACTION_MAPPING_CUT, f"no mapping {mid}")
        return
    if value < MIDI_CC_TRIGGER_THRESHOLD:
        return
    cut_mapper_mapping(None, None, mid)


def _exec_mapping_move(params: dict[str, Any], value: int) -> None:
    """e51s02: shift a Mapping by ``delta`` slots inside its own line."""
    mid = int(params.get("mapping_id", -1))
    delta = int(params.get("delta", 0))
    if mapper.find_mapping(mid) is None:
        _log_stale_midi_target(MIDI_ACTION_MAPPING_MOVE, f"no mapping {mid}")
        return
    if value < MIDI_CC_TRIGGER_THRESHOLD:
        return
    move_mapper_mapping(None, None, (mid, delta))


def _exec_mapping_paste(params: dict[str, Any], value: int) -> None:
    """e51s02: append the clipboard to the line resolved at trigger time.

    Variant B (same rule as _exec_mapper_line): the LINE is bound, the target
    source is read from mapper.row_targets() at trigger time; a stale line index
    is a logged no-op, an empty clipboard is a silent no-op. A Global marker
    (``{"global": True}``) pastes onto the source-less line instead.
    """
    if params.get("global"):
        if value < MIDI_CC_TRIGGER_THRESHOLD:
            return
        paste_mapper_mapping(None, None, None)
        return
    line = int(params.get("line", -1))
    rows = mapper.row_targets()
    if line < 0 or line >= len(rows):
        _log_stale_midi_target(MIDI_ACTION_MAPPING_PASTE, f"no line {line}")
        return
    if value < MIDI_CC_TRIGGER_THRESHOLD:
        return
    paste_mapper_mapping(None, None, rows[line])


def _exec_mapper_line(params: dict[str, Any], value: int) -> None:
    """e33s03: assign the media selected in the Mediagrid to the mapper row (line).

    Variant B (user-confirmed): the LINE is bound, the SOURCE is read at
    trigger time — the row resolves via mapper.row_targets() and re-targets
    onto state.vjmix_selected_source, mirroring the e29 row-thumb click rules:
    no selection, same-source row or a stale line index are no-ops (a stale
    line is logged).
    """
    line = int(params.get("line", -1))
    rows = mapper.row_targets()
    if line < 0 or line >= len(rows):
        _log_stale_midi_target(MIDI_ACTION_MAPPER_LINE, f"no line {line}")
        return
    if value < MIDI_CC_TRIGGER_THRESHOLD:
        return
    target = rows[line]
    selected = state.vjmix_selected_source
    if selected is None or selected == target:
        return
    if mapper.retarget_source(target, selected):
        refresh_mapper_ui()


def _exec_mapper_band(params: dict[str, Any], value: int) -> None:
    """e33s03: bind a mapping to an audio band (same core as the card menu)."""
    mid = int(params.get("mapping_id", -1))
    if mapper.find_mapping(mid) is None:
        _log_stale_midi_target(MIDI_ACTION_MAPPER_BAND, f"no mapping {mid}")
        return
    if value < MIDI_CC_TRIGGER_THRESHOLD:
        return
    set_mapping_band(None, None, (mid, int(params.get("band", 0))))  # mouse-path identical


def _exec_mapper_cue_open(params: dict[str, Any], value: int) -> None:
    """e34s05: open a cue-list mapping's window (same core as the card button).

    The e33 rule: the new cue-list control ships MIDI-mappable — a momentary
    press (CC >= 64) opens the mapping's cue-list window; a stale mapping id is
    a logged no-op.
    """
    mid = int(params.get("mapping_id", -1))
    if mapper.find_mapping(mid) is None:
        _log_stale_midi_target(MIDI_ACTION_MAPPER_CUE_OPEN, f"no mapping {mid}")
        return
    if value < MIDI_CC_TRIGGER_THRESHOLD:
        return
    open_cue_list_window(None, None, mid)


def media_columns(available_w: float, cell_w: float | None = None) -> int:
    """How many tiles fit the available width (e83 fix).

    The footprint is the MEASURED cell (tile + the table's cell padding) once one
    build has happened, and MEDIA_TILE_W_ESTIMATE before that. The old constant
    145 px per tile over-estimated, so a column was dropped while the grid still
    had room and the window grew a scrollbar too early.
    """
    cell = float(cell_w) if cell_w and float(cell_w) > 0 else float(MEDIA_TILE_W_ESTIMATE)
    return max(1, int(float(available_w) // cell))


def measure_media_cell(current_cols: int) -> None:
    """Learn the real cell footprint from the built table (e83).

    The grid is `mvTable_SizingFixedFit`, so its rect width is exactly
    cols x cell: dividing by the column count gives the footprint whatever the
    window size is. Before the first frame the rect is 0 and nothing is learned.
    """
    if current_cols < 1 or not dpg.does_item_exist("media_grid"):
        return
    try:
        table_width = float(dpg.get_item_rect_size("media_grid")[0])
    except Exception:
        return
    if table_width > 0.0:
        state.media_cell_w = table_width / float(current_cols)


def media_available_width(window_width: int) -> float:
    """The grid's usable width (e83).

    A CONSTANT margin, never the live content rect: the scrollbar changes that
    rect, and counting from it would feed back (a column fits -> no scrollbar ->
    the width grows -> a column fits...). The margin therefore always assumes the
    scrollbar is there.
    """
    return max(1.0, float(window_width) - MEDIA_GRID_MARGIN)


def grid_signature(data_dict: dict[str, Any], sorted_keys: list[Any], num_cols: int) -> str:
    """The STRUCTURAL signature of the Mediagrid (e82s09).

    Columns plus each source's identity and label inputs. The CURRENT source is
    deliberately absent: it changes a tile THEME only, and a rebuild (delete and
    recreate every widget) is a visible flash — the delta stream delivers a
    current change in ~100 ms, so the glitch showed on every click in vimix.
    """
    return f"cols:{num_cols}_" + str(
        [
            (
                key,
                data_dict[key].get("name"),
                data_dict[key].get("index"),
                data_dict[key].get("media_kind"),
                data_dict[key].get("type"),
            )
            for key in sorted_keys
        ]
    )


def _source_numeric_sort_key(data: dict[str, Any], key: str) -> int:
    """Numeric sort key of a vimix source (its 'index' field, else the dict key).

    Shared by the Mediagrid rebuild and the source-browsing cycle so the two
    can never disagree on the grid order (e33s04). Malformed values sort last.
    """
    idx = data[key].get("index")
    if idx is not None:
        with contextlib.suppress(TypeError, ValueError):
            return int(idx)
    with contextlib.suppress(TypeError, ValueError):
        return int(key)
    return 0


def _source_target_ids_in_grid_order() -> list[str]:
    """Mediagrid source ids in the display order (numeric index/key, e33s04)."""
    data = state.global_vimix_state.get("sources") or {}
    ids = []
    for key in sorted(data, key=lambda k: _source_numeric_sort_key(data, k)):
        name = data[key].get("name")
        ids.append(str(name) if name else str(key))
    return ids


def select_media_source(target_id: str | None) -> None:
    """Make a source the vjmix-side primary selection (same path as a tile click).

    e33s04: the shared core for on_media_tile_click and the source-browsing
    actions — set the selection and re-apply the tile themes in place.
    """
    if target_id is None or target_id == state.vjmix_selected_source:
        return
    state.vjmix_selected_source = target_id
    refresh_tile_selection_themes()


def _exec_source_next(params: dict[str, Any], value: int) -> None:
    """e33s04: move the Mediagrid selection to the next source (grid order, wrap)."""
    if value < MIDI_CC_TRIGGER_THRESHOLD:
        return
    _cycle_media_selection(+1)


def _exec_source_prev(params: dict[str, Any], value: int) -> None:
    """e33s04: move the Mediagrid selection to the previous source (grid order, wrap)."""
    if value < MIDI_CC_TRIGGER_THRESHOLD:
        return
    _cycle_media_selection(-1)


def _exec_step(step_action: str, params: dict[str, Any], value: int) -> None:
    """e54s02: fire a step action's next/prev pair by the resolver's detent count.

    ONE dispatcher for every rotary target: the pair comes from the step table
    (source browsing, Session Drafts, the File Manager), the signed count from
    `params["steps"]`. `steps` is never forwarded to the target, a zero count or
    an unknown step action is a no-op, and the fired value clears the momentary
    executors' trigger gate.
    """
    steps = int(params.get("steps") or 0)
    if steps == 0:
        return
    pair = STEP_ACTIONS.get(step_action)
    if pair is None:
        return
    target = pair[0] if steps > 0 else pair[1]
    forwarded = {key: item for key, item in params.items() if key != "steps"}
    for _ in range(abs(steps)):
        midi_execute(target, forwarded, MIDI_CC_TRIGGER_THRESHOLD)


def _exec_file_step(params: dict[str, Any], value: int, delta: int) -> None:
    """e54s02: a momentary press steps the File Manager selection (threshold-gated)."""
    if value < MIDI_CC_TRIGGER_THRESHOLD:
        return
    fs_file_step(delta)


def _cycle_media_selection(direction: int) -> None:
    """Step the Mediagrid selection by one in the grid order (e33s04).

    Wraps around the ends; with no current selection, next picks the first and
    prev the last; zero or one source is a no-op. The CC >= threshold gate is
    applied by the momentary dispatch helpers.
    """
    ids = _source_target_ids_in_grid_order()
    if len(ids) < 2:
        return
    current = state.vjmix_selected_source
    if current is None or current not in ids:
        select_media_source(ids[0] if direction > 0 else ids[-1])
        return
    index = ids.index(current)
    select_media_source(ids[(index + direction) % len(ids)])


def on_sources_browse_prev(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """e74s02: the Vimix-sources `<` button — the SAME executor the MIDI binding runs."""
    _exec_source_prev({}, MIDI_CC_TRIGGER_THRESHOLD)


def on_sources_browse_next(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """e74s02: the Vimix-sources `>` button — the SAME executor the MIDI binding runs."""
    _exec_source_next({}, MIDI_CC_TRIGGER_THRESHOLD)


def on_sources_set_current(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """e74s10: the Vimix-sources `Set` button — the SAME executor the MIDI binding runs.

    Selection-relative like the `set_current` action (the volatile-source rule): the button
    acts on the source the `<`/`>` buttons just selected.
    """
    _exec_set_current({}, MIDI_CC_TRIGGER_THRESHOLD)


def _exec_regen_selected(params: dict[str, Any], value: int) -> None:
    """e33s04: regenerate the thumbnails of the SELECTED source at trigger time.

    The binding never anchors to a source (the user swaps sources constantly):
    the action applies to state.vjmix_selected_source when the button fires.
    """
    if value < MIDI_CC_TRIGGER_THRESHOLD:
        return
    selected = state.vjmix_selected_source
    if selected is None:
        _log_stale_midi_target(MIDI_ACTION_REGEN_SELECTED, "no selection")
        return
    regen_thumb_callback(None, None, selected)


def _exec_seq_row_assign(params: dict[str, Any], value: int) -> None:
    """e33s04: assign the SELECTED source to a sequencer row (slot binding).

    The row is a stable slot (1..8), the source comes from the Mediagrid
    selection at trigger time — never anchored to a volatile source.
    """
    if value < MIDI_CC_TRIGGER_THRESHOLD:
        return
    row = int(params.get("row", -1))
    if row < 0 or row >= NUM_TRACKS:
        _log_stale_midi_target(MIDI_ACTION_SEQ_ROW_ASSIGN, f"no track {row}")
        return
    selected = state.vjmix_selected_source
    if selected is None:
        _log_stale_midi_target(MIDI_ACTION_SEQ_ROW_ASSIGN, "no selection")
        return
    # e67: the binding names WHICH sequencer's row, defaulting to A like every other sequencer param
    assign_target_to_track(row, selected, int(params.get("seq", 0)))


def _exec_seq_row_active_true(params: dict[str, Any], value: int) -> None:
    """e36s07: MIDI enable of a whole sequencer row ({row} slot param)."""
    _exec_seq_row_active(params, value, True)


def _exec_seq_row_active_false(params: dict[str, Any], value: int) -> None:
    """e36s07: MIDI disable of a whole sequencer row ({row} slot param)."""
    _exec_seq_row_active(params, value, False)


def _exec_seq_row_active(params: dict[str, Any], value: int, active: bool) -> None:
    """Shared MIDI body: the row is a stable slot; low CC and stale rows no-op."""
    if value < MIDI_CC_TRIGGER_THRESHOLD:
        return
    row = int(params.get("row", -1))
    if row < 0 or row >= NUM_TRACKS:
        _log_stale_midi_target(
            MIDI_ACTION_SEQ_ROW_ENABLE if active else MIDI_ACTION_SEQ_ROW_DISABLE,
            f"no track {row}",
        )
        return
    set_step_row_active(row, active, int(params.get("seq", 0)))


def _exec_enable_correction(params: dict[str, Any], value: int) -> None:
    """e33s04: arm the color-correction block of the SELECTED source (1.0).

    The mouse twin (tile menu) is tile-anchored; the MIDI action is

    selection-relative per the volatile-source rule.

    """
    if value < MIDI_CC_TRIGGER_THRESHOLD:
        return
    selected = state.vjmix_selected_source
    if selected is None:
        _log_stale_midi_target(MIDI_ACTION_ENABLE_CORRECTION, "no selection")
        return
    addr = f"/vimix/{selected}/correction"
    osc_client.send_message(addr, 1.0)


def _exec_set_current(params: dict[str, Any], value: int) -> None:
    """Make the SELECTED source current in vimix (no-arg /vimix/current/<name>).

    The mouse twin (tile menu) is tile-anchored; the MIDI action is
    selection-relative per the volatile-source rule.
    """
    if value < MIDI_CC_TRIGGER_THRESHOLD:
        return
    selected = state.vjmix_selected_source
    if selected is None:
        _log_stale_midi_target(MIDI_ACTION_SET_CURRENT, "no selection")
        return
    # BUG-2026-10-16T233000: the INDEX, never the raw name (a digit-leading name is read
    # by vimix as an index and selects a different source).
    addr = f"/vimix/current/{_current_target_for(selected)}"
    osc_client.send_message(addr, [])


def _exec_set_blending(params: dict[str, Any], value: int) -> None:
    """Set the SELECTED source's blending by enum index (the wiki's `blending` table).

    `/vimix/<target>/blending f <index>` — the index form the wiki documents as the
    alternative to the name; the catalog's `options` tuple IS that table, so index N is
    `catalog.PROPERTY_CATALOG['blending']['options'][N]`. Selection-relative per the
    volatile-source rule (the tile menu is the tile-anchored twin).
    """
    if value < MIDI_CC_TRIGGER_THRESHOLD:
        return
    selected = state.vjmix_selected_source
    if selected is None:
        _log_stale_midi_target(MIDI_ACTION_SET_BLENDING, "no selection")
        return
    index = int(params.get("blending", 0))
    addr = f"/vimix/{selected}/blending"
    osc_client.send_message(addr, float(index))


# e33s01: one dispatcher per registered action (vjmixapp/actions.py owns the
# metadata). Lambdas close over the module helpers, which resolve at call time.


def _exec_mode_toggle(params: dict[str, Any], value: int) -> None:
    """A MIDI note (always) or a CC at the trigger threshold toggles a mode (e52s01)."""
    source_type = str(params.get("source_type") or "")
    if source_type != "note" and value < MIDI_CC_TRIGGER_THRESHOLD:
        return
    mode = str(params.get("mode") or "")
    active = toggle_mode(mode)
    if active is None:
        _log_stale_midi_target(MIDI_ACTION_MODE_TOGGLE, f"no mode {mode!r}")
        return
    if active:
        reset_step_memory(mode)  # e52s04: a knob moved while the mode was off must not burst
    send_mode_led(mode, active)
    refresh_midi_modes_ui()
    refresh_mode_chip()
    refresh_binding_leds()  # e53s02


def _exec_modes_clear(params: dict[str, Any], value: int) -> None:
    """Turn every active mode off, LEDs included (e52s01)."""
    clear_all_modes()
    refresh_midi_modes_ui()
    refresh_mode_chip()
    refresh_binding_leds()  # e53s02


_MIDI_EXECUTORS: dict[str, Callable[[dict[str, Any], int], None]] = {
    MIDI_ACTION_SEQ_TOGGLE: lambda p, v: midi_action_seq_toggle(
        int(p.get("row", 0)), int(p.get("col", 0)), int(p.get("seq", 0))
    ),
    # e66s02/e66s03: the geometry and cell-size ACTIONS are gone with the live selectors: a
    # sequencer's shape is chosen at CREATION (the dialog), never changed on a running one.
    MIDI_ACTION_TRANSPORT_PLAY: lambda p, v: toggle_play(None, None, int(p.get("seq", 0))),
    MIDI_ACTION_TRANSPORT_RESYNC: lambda p, v: resync_sequencer(int(p.get("seq", 0))),
    MIDI_ACTION_TRANSPORT_TAP: lambda p, v: midi_action_transport_tap_index(int(p.get("seq", 0))),
    MIDI_ACTION_NUDGE_BACK: lambda p, v: nudge_sequencer(int(p.get("seq", 0)), SEQ_NUDGE_STEP),
    MIDI_ACTION_NUDGE_FORWARD: lambda p, v: nudge_sequencer(int(p.get("seq", 0)), -SEQ_NUDGE_STEP),
    MIDI_ACTION_BEAT_SOURCE: lambda p, v: on_sequencer_beat_source(
        None, True, (int(p.get("seq", 0)), str(p.get("mode", "")))
    ),
    MIDI_ACTION_TRACK_ASSIGN: lambda p, v: midi_action_track_assign(
        int(p.get("row", 0)), int(p.get("seq", 0))
    ),
    # e18: a learned MIDI control drives a Mapper mapping (raw 0..127 value)
    MIDI_ACTION_MAPPER_MAPPING: lambda p, v: midi_mapping_value(int(p.get("mapping_id", 0)), v),
    # e33s02: card caption learn markers (armed flag, reset)
    MIDI_ACTION_MAPPER_ENABLE: _exec_mapper_enable,
    MIDI_ACTION_MAPPER_RESET: _exec_mapper_reset,
    # e33s03: row line assign (variant B) + audio-band source
    MIDI_ACTION_MAPPER_LINE: _exec_mapper_line,
    MIDI_ACTION_MAPPER_BAND: _exec_mapper_band,
    MIDI_ACTION_MAPPER_CUE_OPEN: _exec_mapper_cue_open,
    # e33s04: source browsing (Mediagrid selection cycle)
    MIDI_ACTION_SOURCE_NEXT: _exec_source_next,
    MIDI_ACTION_SOURCE_PREV: _exec_source_prev,
    # e52s04 / e54s02: rotation stepping — ONE generic dispatcher over the step table
    MIDI_ACTION_SOURCE_STEP: lambda p, v: _exec_step(MIDI_ACTION_SOURCE_STEP, p, v),
    MIDI_ACTION_DRAFT_STEP: lambda p, v: _exec_step(MIDI_ACTION_DRAFT_STEP, p, v),
    MIDI_ACTION_FILE_STEP: lambda p, v: _exec_step(MIDI_ACTION_FILE_STEP, p, v),
    # e33s04: selection-relative actions — never anchored to a volatile source
    MIDI_ACTION_REGEN_SELECTED: _exec_regen_selected,
    MIDI_ACTION_SEQ_ROW_ASSIGN: _exec_seq_row_assign,
    MIDI_ACTION_SEQ_ROW_ENABLE: _exec_seq_row_active_true,
    MIDI_ACTION_SEQ_ROW_DISABLE: _exec_seq_row_active_false,
    MIDI_ACTION_ENABLE_CORRECTION: _exec_enable_correction,
    MIDI_ACTION_SET_CURRENT: _exec_set_current,
    MIDI_ACTION_SET_BLENDING: _exec_set_blending,
    MIDI_ACTION_SOURCES_DATA_REFRESH: lambda p, v: _exec_sources_data_refresh(p, v),
    # e39s01: the I/O Monitor window toggle (mappable per the e33 rule)
    MIDI_ACTION_IO_MONITOR_TOGGLE: lambda p, v: _exec_monitor_toggle(p, v),
    # e40s01: arm/disarm a Mapping's Enabled gate
    MIDI_ACTION_MAPPING_TOGGLE: lambda p, v: _exec_mapping_toggle(p, v),
    # e40s08: create a State Mapping on a source line (the State box '+')
    MIDI_ACTION_MAPPING_ADD: lambda p, v: _exec_mapping_add(p, v),
    # e51s02: clipboard + in-line moves (MIDI-mappable per the e33 rule)
    MIDI_ACTION_MAPPING_COPY: _exec_mapping_copy,
    MIDI_ACTION_MAPPING_CUT: _exec_mapping_cut,
    MIDI_ACTION_MAPPING_MOVE: _exec_mapping_move,
    MIDI_ACTION_MAPPING_PASTE: _exec_mapping_paste,
    # e52s01: MIDI modes — toggle ONE named mode / clear every mode
    MIDI_ACTION_MODE_TOGGLE: _exec_mode_toggle,
    MIDI_ACTION_MODES_CLEAR: _exec_modes_clear,
    # e42s02: re-open the pairing prompt (viOSC restarted -> new code)
    MIDI_ACTION_PAIRING_PROMPT: lambda p, v: _exec_pairing_prompt(p, v),
    # e43s02: show/hide the File Manager window
    MIDI_ACTION_FILE_MANAGER_TOGGLE: lambda p, v: _exec_file_manager_toggle(p, v),
    # e59s02: the Text window (e33 rule) — toggle the window, send the document
    MIDI_ACTION_SHADER_WINDOW_TOGGLE: lambda p, v: _exec_shader_window_toggle(p, v),
    MIDI_ACTION_SHADER_BYPASS: lambda p, v: _exec_shader_bypass(p, v),
    MIDI_ACTION_SHADER_SEND: lambda p, v: _exec_shader_send(p, v),
    MIDI_ACTION_SHADER_LOAD: lambda p, v: _exec_shader_load(p, v),
    MIDI_ACTION_SHADER_SAVE: lambda p, v: _exec_shader_save(p, v),
    MIDI_ACTION_TEXT_WINDOW_TOGGLE: lambda p, v: _exec_text_window_toggle(p, v),
    MIDI_ACTION_TEXT_SEND: lambda p, v: _exec_text_send(p, v),
    MIDI_ACTION_TEXT_CLEAR: lambda p, v: _exec_text_clear(p, v),
    # e59s08: the four progressive reveal modes (momentary)
    MIDI_ACTION_TEXT_WORD: lambda p, v: _exec_text_reveal(textplay.MODE_WORD, p, v),
    MIDI_ACTION_TEXT_WORD_PLUS: lambda p, v: _exec_text_reveal(textplay.MODE_WORD_PLUS, p, v),
    MIDI_ACTION_TEXT_LINE: lambda p, v: _exec_text_reveal(textplay.MODE_LINE, p, v),
    MIDI_ACTION_TEXT_LINE_PLUS: lambda p, v: _exec_text_reveal(textplay.MODE_LINE_PLUS, p, v),
    # e33s05: global actions (window show + project new/open/save)
    MIDI_ACTION_SHOW_WINDOW: lambda p, v: _exec_show_window(p, v),
    MIDI_ACTION_PROJECT_NEW: lambda p, v: _exec_project_new(p, v),
    MIDI_ACTION_PROJECT_OPEN: lambda p, v: _exec_project_open(p, v),
    MIDI_ACTION_PROJECT_SAVE: lambda p, v: _exec_project_save(p, v),
    # e43s07: Session Draft actions (Load always asks for the confirmation)
    MIDI_ACTION_DRAFT_LOAD: lambda p, v: _exec_draft_load(p, v),
    MIDI_ACTION_DRAFT_SAVE: _exec_draft_save,
    MIDI_ACTION_DRAFT_NEXT: _exec_draft_step(1),
    MIDI_ACTION_DRAFT_PREV: _exec_draft_step(-1),
    # e54s02: the File Manager selection by rotation or by a button
    MIDI_ACTION_FILE_NEXT: lambda p, v: _exec_file_step(p, v, 1),
    MIDI_ACTION_FILE_PREV: lambda p, v: _exec_file_step(p, v, -1),
}

_last_unknown_action_log: dict[str, float] = {}  # action id -> last log time (throttle)


def _log_unknown_midi_action(action: str) -> None:
    """Throttled diagnostic: a binding referenced an action the registry does not know.

    A stale binding (its action removed from the catalog, or a config edited by
    hand) must be visible in the Logs window without flooding it — one line per
    second per action id, same pattern as _log_unmatched_midi.
    """
    now = time.time()
    if now - _last_unknown_action_log.get(action, 0.0) < 1.0:
        return
    _last_unknown_action_log[action] = now
    log_warn("MIDI", f"unknown action {action} (stale binding)")


def midi_execute(action: str, params: dict[str, Any], value: int) -> None:
    """Execute a resolved MIDI action on the main thread (called via ui_task_queue, e09).

    e33s01: the action vocabulary lives in the registry (vjmixapp/actions.py) and
    the dispatch in the _MIDI_EXECUTORS map — adding an action is one spec plus
    one entry here, never a new if/elif branch. An id the registry does not know
    (stale binding) is a logged no-op.
    """
    action = actions.canonical_action(action)  # e40s09: a Route-era id still resolves
    executor = _MIDI_EXECUTORS.get(action)
    if executor is None:
        _log_unknown_midi_action(action)
        return
    executor(params, value)


def _midi_enqueue_execute(action: str, params: dict[str, Any], value: int) -> None:
    """Push one resolved MIDI action execution to the main thread (ui_task_queue)."""
    ui_task(lambda: midi_execute(action, params, value))


def _record_ignored_midi(msg: Any, port_name: str, channel: int) -> None:
    """Report a MIDI type the app does not use, ONCE per (port, type), in the Monitor (e81).

    A release is not an ignored type — it is half of every press — so note_off and
    note_on velocity 0 are skipped. The once-per-type rule keeps a stream of sysex or
    clock from filling the pane; the first one is the diagnostic.
    """
    kind = str(getattr(msg, "type", "?"))
    if kind == "note_off" or (kind == "note_on" and int(getattr(msg, "velocity", 1)) == 0):
        return
    key = (port_name, kind)
    if key in _midi_ignored_types:
        return
    _midi_ignored_types.add(key)
    iomonitor.record_ignored(port_name, kind, channel, "message type not used by the app")


def _monitor_outcome_for(action: str, params: dict[str, Any], value: int) -> tuple[str, str]:
    """The I/O Monitor's (outcome, detail) for one resolved binding (e39s01).

    A Mapper value binding reports the mapping-level result through the pure
    preview (SENT / HOLD / MUTED) WITHOUT sending OSC; every other action
    reports MATCH with its id and raw value.
    """
    if action == MIDI_ACTION_MAPPER_MAPPING:
        mapping_id = int(params.get("mapping_id", 0))
        mapping = mapper.find_mapping(mapping_id)
        if mapping is not None:
            effective, tag = mapper.preview_mapping_value(mapping, float(value))
            prop = str(mapping.get("property", "?"))
            return tag, f"mapping #{mapping_id} {prop} -> {effective:.2f}"
    return IO_MONITOR_OUTCOME_MATCH, f"{action} v={value}"


def _record_monitor_rx(
    port_name: str,
    msg_type: str | None,
    channel: int,
    number: int,
    value: int,
    outcome: str,
    detail: str,
) -> None:
    """Report one parsed message to the I/O Monitor (e39s01) — observation only.

    Release edges (note_off / note_on velocity 0) parse to msg_type None and are
    not messages: they are skipped.
    """
    if msg_type is None:
        return
    iomonitor.record_rx(
        port_name, str(msg_type), int(channel), int(number), float(value), outcome, detail
    )


def _fire_binding_leds(controller: dict[str, Any], msg: Any, port_name: str) -> None:
    """Flash the press LEDs of the eligible Bindings for one incoming message (e53s01).

    A `state` Binding is left to the state oracle (e53s02), and a Binding
    suppressed by an inactive mode never lights (the same gate the resolver
    uses), so the LEDs cannot disagree with the dispatch.
    """
    bindings = list(controller.get("bindings") or []) + list(controller.get("auto_bindings") or [])
    profile = controller_profile_of(controller)
    resolved: list[tuple[dict[str, Any], dict[str, Any]]] = []
    state_targets: set[str] = set()
    for binding in led_bindings_for_message(msg, port_name, bindings):
        led = resolve_binding_led(binding, profile)
        if led is None:
            continue
        resolved.append((binding, led))
        if binding_led_behavior(binding) == MIDI_LED_BEHAVIOR_STATE:
            state_targets.add(binding_led_key(led))
    for binding, led in resolved:
        if binding_led_behavior(binding) == MIDI_LED_BEHAVIOR_STATE:
            continue  # e53s02 owns the state behaviour
        if binding_led_key(led) in state_targets:
            continue  # a state LED governs this target: a flash would fight it
        flash_binding_led(controller, led)


def handle_midi_message(msg: Any, port_name: str) -> None:
    """Mapping one incoming message (main thread): learn capture first, then dispatch.

    e39s01: every parsed message is also reported to the I/O Monitor with its
    resolution outcome — observation only, the dispatch below is unchanged.
    """
    msg_type, number, raw = _parse_midi_msg(msg)
    channel = int(getattr(msg, "channel", 0))
    if state.midi_learn_pending is not None:
        source = binding_source_from_message(msg, port_name)
        if source is not None:
            _record_monitor_rx(
                port_name, msg_type, channel, number, raw, IO_MONITOR_OUTCOME_LEARN, "captured"
            )
            ui_task(lambda: midi_learn_complete(source, port_name))
            return
    controller = find_controller_by_port(port_name)
    if controller is not None:
        bindings: list[dict[str, Any]] | None = list(controller.get("bindings") or []) + list(
            controller.get("auto_bindings") or []
        )
    else:
        # BUG-2026-09-18T194700: no controller owns this port, so there is nothing
        # to dispatch through (the worker only listens on configured controllers).
        # The message is reported as NOBIND by the I/O Monitor; no bindings exist.
        bindings = None
    outcome = IO_MONITOR_OUTCOME_NOBIND if bindings is None else IO_MONITOR_OUTCOME_NOMATCH
    details: list[str] = []
    muted_modes: set[str] = set()
    if bindings is not None:
        resolved, muted_modes = resolve_midi_message_report(msg, port_name, bindings)
        if controller is not None:
            _fire_binding_leds(controller, msg, port_name)  # e53s01
    else:
        resolved = []
    for action, params, value in resolved:
        _midi_enqueue_execute(action, params, value)
        outcome, detail = _monitor_outcome_for(action, params, value)
        details.append(detail)
    if not details and muted_modes:  # e52s02: an active mode gate swallowed everything
        outcome = IO_MONITOR_OUTCOME_MUTED
        details = [f"mode {', '.join(sorted(muted_modes))}"]
    if not details and bindings is not None and msg_type is not None:
        # e81: the unanswered message is an I/O Monitor NOMATCH row (recorded below); the
        # Logs window no longer repeats it.
        pass
    if msg_type is None:
        _record_ignored_midi(msg, port_name, channel)
    _record_monitor_rx(port_name, msg_type, channel, number, raw, outcome, "; ".join(details))


def _exit_midi_learn() -> None:
    """Turn MIDI Learn off and restore the button/status (cancel, complete, disable)."""
    state.midi_learn_mode = False
    state.midi_learn_pending = None
    if state.midi_learn_armed_tag:  # an armed M returns to red before the surfaces drop it
        _style_learn_marker(state.midi_learn_armed_tag, False)
    state.midi_learn_armed_tag = None
    if dpg.does_item_exist("midi_learn_btn"):
        dpg.set_item_label("midi_learn_btn", "Learn mapping...")
    if dpg.does_item_exist("midi_learn_status"):
        dpg.set_value("midi_learn_status", "MIDI Learn off")
    _refresh_learn_surfaces()
    refresh_toolbar_learn_icon()  # e47: the bar follows the mode (incl. the timeout)


def _refresh_learn_surfaces() -> None:
    """Rebuild the surfaces whose learn markers are conditional on the mode (e33s02).

    Markers are rendered only while state.midi_learn_mode is on, so entering or
    leaving learn mode must rebuild the Mapper body (its refresh already guards
    on the body existing), create/drop the Mediagrid learn bar (e33s04) and the
    sequencer transport learn strip.
    """
    if dpg.does_item_exist("mapper_mappings_group"):
        refresh_mapper_ui()
    refresh_midi_modes_ui()  # e52s01: the Modes list's red-M markers follow the mode
    _sync_media_learn_bar()
    for sequencer_index in range(state.sequencer_count()):
        _sync_sequencer_learn_strip(sequencer_index)
    _sync_seq_row_learn_strip()
    _sync_monitor_learn_marker()
    _sync_filter_learn_marker()
    _sync_settings_pairing_learn_marker()
    _sync_file_manager_learn_marker()
    _sync_drafts_learn_markers()
    _sync_text_learn_markers()  # e59s02
    _sync_shader_learn_markers()  # e61s03
    _sync_text_mode_learn_markers()  # e59s08
    _sync_sources_data_learn_marker()  # e82s08
    _sync_map_actions_panel()  # e33s05


# --- e76s01: hover help -------------------------------------------------------------
HELP_THEME_TOOLTIP = "theme_help_tooltip"


@dataclass
class HelpAttachment:
    """One card: what to delete, which item it belongs to, what to rebuild, whether built.

    ``card`` is kept (not just the key) because some cards are RENDERED variants of a
    registry entry — the Type and Destination lists are cut down to what the current
    editor offers — so a rebuild after a switch-off must reproduce that same card.

    ``built`` is explicit instead of inferred from ``does_item_exist`` so the switch is
    deterministic on both sides (DearPyGui forgets a deleted tag; the test harness does
    not, and the switch must not depend on that difference).
    """

    tip_tag: str
    parent_tag: str
    key: str
    card: helpprose.HelpEntry
    built: bool = True


_HELP_ATTACHMENTS: list[HelpAttachment] = []


def help_tip_tag(item: Any) -> str:
    """The tooltip tag of one card: derived, so the switch can delete it later."""
    return f"{item}{HELP_TIP_TAG_SUFFIX}"


def help_body_tag(item: Any) -> str:
    """The LIVE body text of one card; the option table never changes at runtime."""
    return f"{item}{HELP_BODY_TAG_SUFFIX}"


def _build_help_theme() -> None:
    """The ONE tooltip theme: a raised, readable CARD, built after create_context() (e76).

    The operator found the card hard to read (2026-10-16): a tooltip is a popup and had
    inherited `window_bg`, so the dim body sat on the window colour with no edge. It now
    paints its own surface (`panel_bg`) with a palette border and real padding, so a card
    reads on the dark, the light and any custom palette — `theme_color` registers each
    colour, so a theme change moves the card with the UI.

    It is built HERE, right after the context, because the windows (and the toolbar, whose
    icon tooltips share this theme) are constructed at import time and bind this tag.
    """
    with dpg.theme(tag=HELP_THEME_TOOLTIP), dpg.theme_component(dpg.mvThemeCat_Core):
        # A tooltip is drawn as a popup: PopupBg is the colour ImGui actually uses, and
        # WindowBg/ChildBg keep a nested group from falling back to the global theme.
        theme_color(dpg.mvThemeCol_PopupBg, HELP_CARD_BG_SLOT)
        theme_color(dpg.mvThemeCol_WindowBg, HELP_CARD_BG_SLOT)
        theme_color(dpg.mvThemeCol_ChildBg, HELP_CARD_BG_SLOT)
        theme_color(dpg.mvThemeCol_Border, HELP_CARD_BORDER_SLOT)
        theme_color(dpg.mvThemeCol_BorderShadow, HELP_CARD_BG_SLOT)
        dpg.add_theme_style(dpg.mvStyleVar_WindowBorderSize, HELP_CARD_BORDER)
        dpg.add_theme_style(dpg.mvStyleVar_WindowRounding, 0)
        dpg.add_theme_style(dpg.mvStyleVar_WindowPadding, HELP_CARD_PAD_X, HELP_CARD_PAD_Y)
        dpg.add_theme_style(dpg.mvStyleVar_ItemSpacing, HELP_CARD_GAP_X, HELP_CARD_GAP_Y)


def help_tooltip(
    item: Any,
    key: str,
    wrap: int = HELP_WRAP_WIDTH,
    card: helpprose.HelpEntry | None = None,
) -> str:
    """Attach the card for `key` to `item`; '' when hover help is switched off.

    The card is three blocks: the title, ONE body text (always created, empty when the
    entry has no prose) and the option table. The body carries a derived tag so a LIVE
    card can be rewritten from the control's own callback (``_refresh_help_text``) — no
    per-frame work and no hover callback, which DearPyGui does not offer.

    DearPyGui fires a tooltip for the HOVERED item, and a label is a separate item from
    its control, so callers attach one card to each (``help_label`` does the label).
    """
    if not state.hover_help:
        return ""
    shown = card if card is not None else helpprose.entry(key)
    tip_tag = help_tip_tag(item)
    if dpg.does_item_exist(tip_tag):
        dpg.delete_item(tip_tag)  # a rebuilt widget re-attaches the same derived tag
    with dpg.tooltip(parent=item, tag=tip_tag, delay=HELP_HOVER_DELAY_S):
        themed_text(shown.title, slot="text_bright")
        themed_text(shown.body, slot="text", wrap=wrap, tag=help_body_tag(item))
        for value, meaning in shown.options:
            # Two items, not one padded string: a long meaning must not wrap under
            # the value column, and tooltips auto-size to the longest line. The VALUE is
            # the brighter half so the eye finds the option names first (e76 readability).
            with dpg.group(horizontal=True):
                themed_text(f"{value:<{HELP_OPTION_COLUMN}}", slot="text_bright")
                themed_text(meaning, slot="text")
    dpg.bind_item_theme(tip_tag, HELP_THEME_TOOLTIP)
    for existing in _HELP_ATTACHMENTS:
        if existing.tip_tag == tip_tag:  # a rebuilt modal re-attaches the same card
            existing.key = key
            existing.card = shown
            existing.built = True
            return tip_tag
    _HELP_ATTACHMENTS.append(HelpAttachment(tip_tag, str(item), key, shown))
    return tip_tag


def help_label(
    text: str,
    key: str,
    slot: str = "text_dim",
    card: helpprose.HelpEntry | None = None,
    **kwargs: Any,
) -> Any:
    """A palette text that ALSO carries the card, so hovering the WORD explains it.

    This is the operator's own case (2026-10-16): the cursor goes to the word "Type",
    not to the combo below it.
    """
    tag = themed_text(text, slot=slot, **kwargs)
    # An explicit tag wins: the harness stub returns a synthetic one, and a LIVE card
    # must be addressable by the tag the caller (and the refresh below) knows.
    help_tooltip(kwargs.get("tag", tag), key, card=card)
    return tag


def replace_help_card(
    item: Any, key: str, card: helpprose.HelpEntry, wrap: int = HELP_WRAP_WIDTH
) -> None:
    """Rebuild ONE card in place, because its OPTIONS changed (a live enum).

    The body alone is not enough for a card that enumerates: changing the Origin
    changes which Destinations are even offered, and a stale list would be worse
    than no card.
    """
    if not dpg.does_item_exist(item):
        return  # the editor closed between the callback and the rebuild
    tip_tag = help_tip_tag(item)
    if dpg.does_item_exist(tip_tag):
        dpg.delete_item(tip_tag)
    _HELP_ATTACHMENTS[:] = [a for a in _HELP_ATTACHMENTS if a.tip_tag != tip_tag]
    help_tooltip(item, key, wrap=wrap, card=card)


def _refresh_help_text(item: Any, text: str) -> None:
    """Rewrite a LIVE card's body (a long enum explains its CURRENT value)."""
    tag = help_body_tag(item)
    if dpg.does_item_exist(tag):
        dpg.set_value(tag, text)


def apply_hover_help(enabled: bool) -> None:
    """Delete or rebuild every built card — the Info window's switch (e76s01).

    The registry is DECLARATIVE and survives a switch-off: a record is (parent, key),
    so the cards can be rebuilt without reopening a window, and the parent that no
    longer exists (a modal that closed) is skipped, never dereferenced. Re-attaching
    an already registered card is a no-op, so toggling cannot grow the registry.
    """
    state.hover_help = bool(enabled)
    for attachment in list(_HELP_ATTACHMENTS):
        if enabled:
            if not attachment.built and dpg.does_item_exist(attachment.parent_tag):
                help_tooltip(attachment.parent_tag, attachment.key, card=attachment.card)
        elif attachment.built:
            if dpg.does_item_exist(attachment.tip_tag):
                dpg.delete_item(attachment.tip_tag)
            attachment.built = False
    if state.hover_help:
        # A window opened WHILE help was off recorded nothing, so the table is re-applied
        # (idempotent: an existing tip is deleted and rebuilt, a record is reused).
        _apply_help_targets()


def hover_help_enabled(cfg: dict[str, Any]) -> bool:
    """The persisted switch: ON unless the config says otherwise."""
    return bool(cfg.get("ui", {}).get("hover_help", True))


def on_toggle_hover_help(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """The Info window's 'Show hover help' checkbox: apply now, persist for the next run."""
    apply_hover_help(bool(app_data))
    cfg = load_config()
    cfg.setdefault("ui", {})["hover_help"] = state.hover_help
    save_config(cfg)


def learn_marker(
    action_id: str,
    params: dict[str, Any],
    parent: Any,
    tag: str | None = None,
    tooltip: str | None = None,
) -> str:
    """Add ONE uniform learn marker button (e33s02): click captures the action.

    The marker is a small button labeled by a dot whose tooltip names the action
    (registry label); its click stores (action_id, params) as the pending learn
    capture instead of executing anything. Callers render markers ONLY while
    state.midi_learn_mode is on — the surfaces rebuild on learn transitions via
    _refresh_learn_surfaces, so markers never need show/hide juggling. The
    parent is EXPLICIT: a parentless add_button outside a with-block hangs the
    render thread in real DearPyGui (reproduced 2026-09-05). The tooltip may be
    overridden when the params distinguish slots (e.g. 'Mapper line 3').
    """
    marker_kwargs: dict[str, Any] = {
        "label": "M",
        "width": MAPPER_MARKER_W,
        "height": MAPPER_MARKER_H,
        "callback": on_learn_marker_click,
        "user_data": (action_id, params),
        "parent": parent,
    }
    if tag is not None:
        marker_kwargs["tag"] = tag  # tag=None would raise 'Must be int' in real DPG
    marker_tag = dpg.add_button(**marker_kwargs)
    dpg.bind_item_theme(marker_tag, theme_learn_marker)  # red 'M' (e33)
    tooltip_text = tooltip or f"Map: {actions.action_label(action_id)}"
    with dpg.tooltip(parent=marker_tag, delay=HELP_HOVER_DELAY_S) as tip_tag:
        dpg.add_text(tooltip_text)
    dpg.bind_item_theme(tip_tag, HELP_THEME_TOOLTIP)
    return marker_tag


def _style_learn_marker(tag: str | None, armed: bool) -> None:
    """Point one learn marker at the red (idle) or amber (armed) theme (2026-09-07)."""
    if not tag or not dpg.does_item_exist(tag):
        return
    dpg.bind_item_theme(tag, theme_learn_marker_armed if armed else theme_learn_marker)


def on_learn_marker_click(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """A learn marker was clicked: capture its (action_id, params) as the pending binding.

    The mouse behavior of the mapped control itself is never hijacked — markers
    are separate buttons; this handler only records what the next MIDI message
    will bind. Outside learn mode a stray click captures nothing.
    """
    if not state.midi_learn_mode:
        return
    action_id, params = user_data
    state.midi_learn_pending = (action_id, params)
    state.midi_learn_started_at = time.time()
    # The clicked M turns AMBER so the user sees which control the next MIDI
    # message binds; the previously armed M returns to red (user, 2026-09-07).
    if state.midi_learn_armed_tag and state.midi_learn_armed_tag != sender:
        _style_learn_marker(state.midi_learn_armed_tag, False)
    state.midi_learn_armed_tag = sender
    _style_learn_marker(sender, True)
    if dpg.does_item_exist("midi_learn_status"):
        dpg.set_value("midi_learn_status", "Now press your MIDI button")


def _sync_media_learn_bar() -> None:
    """Create or drop the Mediagrid source-browsing learn bar (e33s04).

    While MIDI Learn is on, the sources window shows a marker bar
    above the grid — fixed slots with separators: the generic markers
    (next/prev/step/regen/correction/set-current/window), a dash, the
    8 step-sequencer slots, a dash, the 4 Mapper slots; a SECOND row carries
    the 8 blending modes (e74s13). Slot bindings are selection-relative and
    pre-bindable even when fewer rows exist (a missing line is a logged no-op).
    Leaving learn mode removes the bar; rebuilt from scratch each time.
    """
    bar_tag = "media_learn_bar"
    if dpg.does_item_exist(bar_tag):
        dpg.delete_item(bar_tag)
    if not state.midi_learn_mode:
        return
    if not dpg.does_item_exist("vimix_media_group"):
        return
    bar_kwargs: dict[str, Any] = {
        "parent": "vimix_media_group",
        "tag": bar_tag,
    }
    if dpg.does_item_exist("media_grid"):
        bar_kwargs["before"] = "media_grid"  # stay above the tiles
    # e74s13: the bar is a COLUMN of rows — the blending modes (8) would overflow a single
    # row, so they get a row of their own under the browsing/slot markers.
    with dpg.group(**bar_kwargs):
        with dpg.group(horizontal=True) as row1:
            learn_marker(MIDI_ACTION_SOURCE_NEXT, {}, parent=row1, tag="media_mk_next")
            learn_marker(MIDI_ACTION_SOURCE_PREV, {}, parent=row1, tag="media_mk_prev")
            learn_marker(
                MIDI_ACTION_SOURCE_STEP,
                {},
                parent=row1,
                tag="media_mk_step",
                tooltip="Map: step sources by rotation",
            )
            learn_marker(MIDI_ACTION_REGEN_SELECTED, {}, parent=row1, tag="media_mk_regen")
            learn_marker(MIDI_ACTION_ENABLE_CORRECTION, {}, parent=row1, tag="media_mk_cc")
            learn_marker(MIDI_ACTION_SET_CURRENT, {}, parent=row1, tag="media_mk_setcurrent")
            # e74s03: the Sources-data window joins the media learn bar (the new surface's
            # red-M marker), so the window is MIDI-openable from the same bar.
            learn_marker(
                MIDI_ACTION_SHOW_WINDOW,
                {"window": SOURCES_DATA_WINDOW_TAG},
                parent=row1,
                tag="media_mk_sources_data",
                tooltip="Map: Sources data window",
            )
            _learn_group_gap(row1)
            for slot in range(1, NUM_TRACKS + 1):
                learn_marker(
                    MIDI_ACTION_SEQ_ROW_ASSIGN,
                    {"row": slot - 1},
                    parent=row1,
                    tag=f"media_mk_seq_{slot}",
                    tooltip=f"Map: sequencer line {slot} (selected source)",
                )
            _learn_group_gap(row1)
            for slot in range(1, MAPPER_LEARN_SLOTS + 1):
                learn_marker(
                    MIDI_ACTION_MAPPER_LINE,
                    {"line": slot - 1},
                    parent=row1,
                    tag=f"media_mk_map_{slot}",
                    tooltip=f"Map: mapper line {slot} (selected source)",
                )
        # e74s13: the 8 blending modes on their own row (the tile menu's mouse twin).
        with dpg.group(horizontal=True) as row2:
            for mode_index, option in enumerate(BLENDING_OPTIONS):
                learn_marker(
                    MIDI_ACTION_SET_BLENDING,
                    {"blending": mode_index},
                    parent=row2,
                    tag=f"media_mk_blend_{mode_index}",
                    tooltip=f"Map: blending {option} (selected source)",
                )


def _learn_group_gap(parent: Any) -> None:
    """A wider gap BETWEEN the learn-bar groups (e33s04)."""
    dpg.add_spacer(width=MARKER_GROUP_GAP, parent=parent)


def _sync_sequencer_learn_strip(index: int = 0) -> None:
    """Create or drop ONE sequencer's transport learn strip (e33s04, e67s04).

    While MIDI Learn is on, a strip below that instance's transport row offers one red-M marker
    per control of ITS row (Play, Resync, the nudges, Tap, the four beat sources). A keeps the
    strip it has always had — bare tags and no `seq` param, which defaults to A; B's strip
    carries its namespace and NAMES its instance, so a marker learned there addresses B. The
    geometry/cell-size markers stay A's, because B's row has no such controls. Leaving learn
    mode removes the strip.
    """
    prefix = sequencer_prefix(index)
    strip_tag = f"{prefix}_transport_learn"
    window_tag = "sequencer_window" if index == 0 else SEQUENCER_B_WINDOW_TAG
    anchor = "seq_grid_host" if index == 0 else "seq_b_grid_host"
    if dpg.does_item_exist(strip_tag):
        dpg.delete_item(strip_tag)
    if not state.midi_learn_mode:
        return
    if not dpg.does_item_exist(f"{prefix}_table") or not dpg.does_item_exist(window_tag):
        return
    own = {} if index == 0 else {"seq": index}
    with dpg.group(
        parent=window_tag,
        horizontal=True,
        tag=strip_tag,
        before=anchor,
    ) as strip:
        _strip_marker(strip, MIDI_ACTION_TRANSPORT_PLAY, dict(own), f"{prefix}_mk_play")
        _strip_marker(strip, MIDI_ACTION_TRANSPORT_RESYNC, dict(own), f"{prefix}_mk_resync")
        _strip_marker(strip, MIDI_ACTION_NUDGE_BACK, dict(own), f"{prefix}_mk_nudge_back")
        _strip_marker(strip, MIDI_ACTION_NUDGE_FORWARD, dict(own), f"{prefix}_mk_nudge_forward")
        _strip_marker(strip, MIDI_ACTION_TRANSPORT_TAP, dict(own), f"{prefix}_mk_tap")
        _learn_group_gap(strip)
        for mode in (
            BEAT_SOURCE_ANALYSIS,
            BEAT_SOURCE_BAND1,
            BEAT_SOURCE_MIDI,
            BEAT_SOURCE_LINK,
            BEAT_SOURCE_MANUAL,
        ):
            label = BEAT_SOURCE_LABELS.get(mode, mode)
            learn_marker(
                MIDI_ACTION_BEAT_SOURCE,
                {**own, "mode": mode},
                parent=strip,
                tag=f"{prefix}_mk_beat_{mode}",
                tooltip=f"Map: beat source ({label})",
            )


def _strip_marker(strip: Any, action_id: str, params: dict[str, Any], tag: str) -> None:
    """One transport learn marker inside the sequencer strip."""
    learn_marker(action_id, params, parent=strip, tag=tag)


def _sync_seq_row_learn_strip() -> None:
    """Create or drop the sequencer ROW learn strip (e36s07).

    While MIDI Learn is on, a strip below the transport markers offers one red-M
    marker per row for Enable row and one for Disable row (params carry the
    stable row slot), so the e33 rule holds for the new context actions. Leaving
    learn mode removes the strip.
    """
    strip_tag = "seq_row_learn"
    if dpg.does_item_exist(strip_tag):
        dpg.delete_item(strip_tag)
    if not state.midi_learn_mode:
        return
    if not dpg.does_item_exist("seq_table"):
        return
    with dpg.group(
        parent="sequencer_window",
        horizontal=True,
        tag=strip_tag,
        before="seq_table",
    ) as strip:
        for slot in range(1, NUM_TRACKS + 1):
            learn_marker(
                MIDI_ACTION_SEQ_ROW_ENABLE,
                {"row": slot - 1},
                parent=strip,
                tag=f"seq_row_mk_en_{slot}",
                tooltip=f"Map: enable sequencer line {slot}",
            )
        _learn_group_gap(strip)
        for slot in range(1, NUM_TRACKS + 1):
            learn_marker(
                MIDI_ACTION_SEQ_ROW_DISABLE,
                {"row": slot - 1},
                parent=strip,
                tag=f"seq_row_mk_dis_{slot}",
                tooltip=f"Map: disable sequencer line {slot}",
            )


def midi_learn_complete(binding: dict[str, Any], port_name: str | None = None) -> None:
    """Main thread: merge the captured source with the pending action and store the binding
    on the controller that owns the port.

    One-shot (e14 bug fix): learn mode exits after the capture, so the learnable
    sequencer controls (PLAY, beat sources, step cells) are never left hijacked.
    BUG-2026-09-18T194700: with no owning controller the capture is REFUSED with a
    log line and the mapping is left unbound — a binding stored nowhere used to be
    lost on restart while a Mapper mapping still claimed its MIDI source.
    """
    if state.midi_learn_pending is None:
        return
    action, params = state.midi_learn_pending
    binding["action"] = action
    binding["params"] = params
    # e52s08: the learned Binding also takes the mode that is active right now
    # (the most recently activated one); a MODE_TOGGLE never gates itself.
    learned_mode = "" if action == MIDI_ACTION_MODE_TOGGLE else (most_recent_mode() or "")
    if learned_mode:
        set_binding_mode(binding, learned_mode)
    controller = find_controller_by_port(port_name) if port_name else None
    if controller is None:
        # Unreachable from the app (the worker listens only on configured
        # controllers): refuse loudly rather than sink it into a lost list.
        state.midi_learn_pending = None
        _exit_midi_learn()
        log_error(
            "MIDI Learn",
            f"no controller owns port {port_name!r} — add it in the MIDI window first",
        )
        if dpg.does_item_exist("midi_learn_status"):
            dpg.set_value("midi_learn_status", "No controller owns that port")
        return
    controller.setdefault("bindings", []).append(binding)
    save_midi_controllers()  # 2026-09-07: a learned mapping persists immediately
    state.midi_learn_pending = None
    _exit_midi_learn()
    refresh_midi_mappings_ui()
    if action == MIDI_ACTION_MAPPER_MAPPING:  # e18: bind the learned control to the mapping
        mapper.set_mapping_midi(int(params.get("mapping_id", 0)), binding)
        refresh_mapper_ui()  # show the input-range line of the bound source
    if dpg.does_item_exist("midi_learn_btn"):
        dpg.set_item_label("midi_learn_btn", "Learn mapping...")
    if dpg.does_item_exist("midi_learn_status"):
        mode_suffix = f" [mode {learned_mode}]" if learned_mode else ""
        dpg.set_value(
            "midi_learn_status",
            "Bound: "
            f"{actions.action_label(action)} <- "
            f"{binding['device']} {binding['type']} {binding['number']}{mode_suffix}",
        )


def learnable(callback: Any, action_builder: Callable[[Any], tuple[str, dict[str, Any]]]) -> Any:
    """Wrap a widget callback so MIDI Learn captures its action instead of executing it.

    In learn mode the wrapper stores (action, params) from action_builder(user_data) into
    midi_learn_pending and skips the real callback; otherwise it delegates unchanged, so a
    mouse click and a MIDI trigger share the exact same callback path (e09s02). A stale
    learn session (past MIDI_LEARN_TIMEOUT_SECONDS) expires and delegates, so the MIDI
    logic can never permanently disable the sequencer controls (e14 bug fix).
    """

    def wrapper(sender: Any, app_data: Any, user_data: Any) -> None:
        if state.midi_learn_mode:
            if time.time() - state.midi_learn_started_at > MIDI_LEARN_TIMEOUT_SECONDS:
                _exit_midi_learn()
                callback(sender, app_data, user_data)
                return
            state.midi_learn_pending = action_builder(user_data)
            if dpg.does_item_exist("midi_learn_status"):
                dpg.set_value("midi_learn_status", "Now press your MIDI button")
            return
        callback(sender, app_data, user_data)

    return wrapper


def toggle_midi_learn(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """Toggle MIDI Learn mode from the MIDI window; the button doubles as Cancel (e09s02)."""
    if state.midi_learn_mode:
        _exit_midi_learn()
        return
    if not state.midi_enabled:
        if dpg.does_item_exist("midi_learn_status"):
            dpg.set_value("midi_learn_status", "Enable MIDI first (tick Enable MIDI above)")
        return
    state.midi_learn_mode = True
    state.midi_learn_pending = None
    state.midi_learn_started_at = time.time()
    if dpg.does_item_exist("midi_learn_btn"):
        dpg.set_item_label("midi_learn_btn", "Cancel learn")
    if dpg.does_item_exist("midi_learn_status"):
        dpg.set_value("midi_learn_status", "MIDI Learn: click a VJmix control")
    _refresh_learn_surfaces()  # e33s02: show the learn markers on the Mapper body
    refresh_toolbar_learn_icon()  # e47: the bar shows the mode


def on_midi_enable(sender: Any, app_data: Any, user_data: Any) -> None:
    """MIDI window Enable checkbox: persist and apply the engine toggle (e09s02)."""
    set_midi_enabled(bool(app_data))
    if not app_data and state.midi_learn_mode:  # disabling cancels an in-flight learn
        _exit_midi_learn()
    refresh_toolbar_learn_icon()  # e47: grey the Learn icon while the engine is off


def _midi_binding_label(binding: dict[str, Any]) -> str:
    """Human-readable row label for one mapping (e09s02; e52s02 adds the mode tag)."""
    params = binding.get("params") or {}
    suffix = f" {params}" if params else ""
    tag = binding_mode(binding)
    mode_suffix = f" [mode {tag}]" if tag else ""
    return (
        f"{binding.get('device', '?')} {binding.get('type', '?')} "
        f"{binding.get('number', '?')} -> "
        f"{actions.action_label(str(binding.get('action', '?')))}{suffix}{mode_suffix}"
    )


MIDI_MODE_BASE_CHOICE = "(base)"  # the "no gate tag" choice of the per-Binding combo


def on_binding_mode_change(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """Bindings list > Mode: write the gate tag on that Binding and persist (e52s02)."""
    idx = int(user_data)
    bindings = selected_bindings()
    if not (0 <= idx < len(bindings)):
        return
    chosen = "" if app_data in (None, MIDI_MODE_BASE_CHOICE) else str(app_data)
    set_binding_mode(bindings[idx], chosen)
    save_midi_controllers()
    refresh_midi_mappings_ui()
    refresh_mapper_ui()


MIDI_LED_BEHAVIOR_NONE = "-"
MIDI_LED_BEHAVIOR_CHOICES: tuple[str, ...] = (
    MIDI_LED_BEHAVIOR_NONE,
    MIDI_LED_BEHAVIOR_PRESS,
    MIDI_LED_BEHAVIOR_STATE,
)
MIDI_LED_BINDING_FIELDS: tuple[str, ...] = ("number", "on_value", "off_value")


def on_binding_led_behavior_change(
    sender: Any = None, app_data: Any = None, user_data: Any = None
) -> None:
    """Bindings list > Behavior: set (or clear) that Binding's LED behaviour (e53s03)."""
    idx = int(user_data)
    bindings = selected_bindings()
    if not (0 <= idx < len(bindings)):
        return
    chosen = None if app_data in (None, MIDI_LED_BEHAVIOR_NONE) else str(app_data)
    bindings[idx]["led_behavior"] = chosen
    save_midi_controllers()


def _binding_effective_led(binding: dict[str, Any]) -> dict[str, Any] | None:
    """The LED actually sent for a Binding: explicit spec, else the profile mirror (e53)."""
    controller = selected_controller()
    profile = controller_profile_of(controller) if controller is not None else None
    return resolve_binding_led(binding, profile)


def on_binding_led_change(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """Bindings list > LED editor: merge one field into that Binding's LED spec (e53s03)."""
    idx, field = user_data
    bindings = selected_bindings()
    if not (0 <= int(idx) < len(bindings)):
        return
    binding = bindings[int(idx)]
    led = dict(_binding_effective_led(binding) or {})
    led.setdefault("controller_port", str(binding.get("device") or ""))
    led.setdefault("kind", MIDI_MODE_LED_KINDS[0])
    for key, default in MIDI_MODE_LED_FIELD_DEFAULTS.items():
        led.setdefault(key, default)
    led[field] = str(app_data) if field == "kind" else int(app_data or 0)
    binding["led"] = led
    save_midi_controllers()


def _midi_binding_led_editor(idx: int, binding: dict[str, Any]) -> None:
    """One Binding's compact LED editor: behavior, kind, number, on, off (e53s03).

    The controller port is implicit (the row belongs to the selected controller),
    so the editor omits the port combo the e52 mode editor needs.
    """
    raw_led = binding.get("led")
    led: dict[str, Any] = (
        raw_led if isinstance(raw_led, dict) else (_binding_effective_led(binding) or {})
    )
    dpg.add_combo(
        items=list(MIDI_LED_BEHAVIOR_CHOICES),
        default_value=binding_led_behavior(binding),
        width=66,
        callback=on_binding_led_behavior_change,
        user_data=idx,
    )
    dpg.add_combo(
        items=list(MIDI_MODE_LED_KINDS),
        default_value=str(led.get("kind") or MIDI_MODE_LED_KINDS[0]),
        width=54,
        callback=on_binding_led_change,
        user_data=(idx, "kind"),
    )
    for field in MIDI_LED_BINDING_FIELDS:
        dpg.add_drag_int(
            default_value=int(led.get(field) or MIDI_MODE_LED_FIELD_DEFAULTS[field]),
            width=50,
            callback=on_binding_led_change,
            user_data=(idx, field),
        )


def _midi_binding_row_label(binding: dict[str, Any]) -> str:
    """Compact Bindings-list label: the device is redundant on the selected controller's list."""
    params = binding.get("params") or {}
    suffix = f" {params}" if params else ""
    tag = binding_mode(binding)
    mode_suffix = f" [mode {tag}]" if tag else ""
    return (
        f"{binding.get('type', '?')} {binding.get('number', '?')} -> "
        f"{actions.action_label(str(binding.get('action', '?')))}{suffix}{mode_suffix}"
    )


def refresh_midi_mappings_ui() -> None:
    """Rebuild the Bindings list for the selected controller (main thread) (e14s03).

    e52s02: each row carries a Mode combo (base + the registered modes), so ANY
    Binding — not just a Mapper one — can be tagged. e53: the Mode + LED controls
    live on a SECOND line, because one line (the long label plus six widgets)
    overflows the 520 px window and the LED fields become unclickable.
    """
    if not dpg.does_item_exist("midi_mappings_group"):
        return
    dpg.delete_item("midi_mappings_group", children_only=True)
    choices = [MIDI_MODE_BASE_CHOICE, *mode_names()]
    for idx, binding in enumerate(selected_bindings()):
        with dpg.group(parent="midi_mappings_group"):
            dpg.add_text(_midi_binding_row_label(binding))
            with dpg.group(horizontal=True):
                dpg.add_combo(
                    items=choices,
                    default_value=binding_mode(binding) or MIDI_MODE_BASE_CHOICE,
                    width=110,
                    callback=on_binding_mode_change,
                    user_data=idx,
                )
                _midi_binding_led_editor(idx, binding)
                dpg.add_button(label="Delete", callback=delete_midi_binding, user_data=idx)
            dpg.add_spacer(height=2)


def delete_midi_binding(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """Remove a binding by list index from the selected controller and refresh (e14s03)."""
    idx = int(user_data)
    bindings = selected_bindings()
    if 0 <= idx < len(bindings):
        del bindings[idx]
        save_midi_controllers()  # 2026-09-07: deletions persist immediately
    refresh_midi_mappings_ui()


# ---------- e52s01: MIDI modes — registry UI, toggle executors, toolbar chip ----------
# The registry lives in vjmixapp/midi.py (dpg-free); this block is only widget
# wiring per REFACTOR_LATEST.md. Markers follow the e33 rule: rendered only while
# state.midi_learn_mode is on (refresh_midi_modes_ui is rebuilt by
# _refresh_learn_surfaces on every learn transition).

MIDI_MODE_NAME_INPUT_TAG = "midi_mode_name_input"
MIDI_MODE_ADD_BUTTON_TAG = "midi_mode_add_btn"

# --- e76s03..e76s08: the cards of the surfaces that build ONCE at import -----------------
# One table instead of one call per widget: these tags are already the app's own addresses
# (layout, learn markers, project round-trip), so the explanation rides on them and a
# renamed control cannot keep a stale card. A dialog built on OPEN is wired at its own
# builder instead, because its tag does not exist yet when this table is applied.
HELP_TARGETS: dict[str, str] = {
    # audio analyser
    "combo_devices": "audio.device",
    "cb_spectrum_analysis": "audio.spectrum",
    "cb_bpm_analysis": "audio.bpm",
    "cb_lowpass": "audio.lowpass",
    # settings
    "cb_restore_project_boot": "settings.restore_project",
    "theme_preset": "settings.theme_preset",
    "viosc_ip": "settings.client_ip",
    "viosc_port": "settings.client_port",
    "listen_ip": "settings.listen_ip",
    "listen_port": "settings.listen_port",
    "btn_server_toggle": "settings.server",
    PAIRING_CODE_INPUT_TAG: "pairing.code",
    # MIDI
    "midi_enable_cb": "midi.enable",
    "midi_add_combo": "midi.add_controller",
    MIDI_MODE_NAME_INPUT_TAG: "midi.mode_name",
    MIDI_MODE_ADD_BUTTON_TAG: "midi.mode_add",
    "midi_learn_btn": "midi.learn",
    "midi_mappings_scroll": "midi.bindings",
    # I/O monitor
    "io_monitor_pause": "io.pause",
    "io_monitor_port": "io.peer",
    "io_monitor_direction": "io.direction",
    "io_monitor_transport": "io.transport",
    "io_monitor_control_combo": "io.control",
    "io_monitor_mapping_combo": "io.mapping",
    # Leap Motion
    "leap_enable_cb": "leap.enable",
    "leap_restart_btn": "leap.restart",
    "leap_viz_cb": "leap.viz",
    # Text
    TEXT_SOURCE_COMBO_TAG: "text.source",
    "text_size_keyword": "text.size_keyword",
    "text_fg_color": "text.foreground",
    "text_bg_color": "text.background",
    TEXT_WRAP_CLIPBOARD_TAG: "text.wrap_clipboard",
    TEXT_EDITOR_TAG: "text.editor",
    # Shader
    SHADER_KIND_COMBO_TAG: "shader.kind",
    SHADER_FAMILY_COMBO_TAG: "shader.family",
    SHADER_TEMPLATE_COMBO_TAG: "shader.template",
    SHADER_TARGET_COMBO_TAG: "shader.target",
    SHADER_SEND_BUTTON_TAG: "shader.send",
    SHADER_UNIFORM_SCAN_BUTTON_TAG: "shader.rescan",
    SHADER_BYPASS_BUTTON_TAG: "shader.bypass",
    SHADER_EDITOR_TAG: "shader.editor",
    # Mapper window (the editor has its own cards)
    "mapper_filter_control": "mapper.filter_control",
    "mapper_filter_get": "mapper.filter_state",
    "mapper_filter_global": "mapper.filter_global",
    "mapper_filter_add": "mapper.new",
    # Logs window (e81): the system window's own controls
    "log_level_combo": "logs.level",
    "log_pause_btn": "logs.pause",
    "log_clear_btn": "logs.clear",
    "log_copy_btn": "logs.copy",
    # I/O Monitor (e81): the outcome filter
    "io_monitor_outcome": "io.outcome",
    # sessions manager
    FILE_MANAGER_ROOTS_TAG: "sessions.roots",
}


# Both slots, not `state.sequencer_count()`: a window's row exists as soon as the WINDOW is
# built (B's is built on demand, before its sequencer state does), and the applier skips the
# tags that do not exist yet.
SEQUENCER_HELP_INSTANCES: tuple[int, ...] = (0, 1)


def _sequencer_help_targets() -> list[tuple[str, str]]:
    """The transport row's tags, generated per instance (A and B share the builder)."""
    bases = (
        ("btn_play", "sequencer.play"),
        ("btn_nudge_back", "sequencer.nudge_back"),
        ("btn_resync", "sequencer.resync"),
        ("btn_nudge_forward", "sequencer.nudge_forward"),
        ("btn_delete", "sequencer.delete"),
        ("manual_bpm_input", "sequencer.manual_bpm"),
        ("btn_tap", "sequencer.tap"),
    )
    targets = [
        (sequencer_transport_tag(index, base), key)
        for index in SEQUENCER_HELP_INSTANCES
        for base, key in bases
    ]
    targets += [
        (beat_checkbox_tag(index, mode), "sequencer.beat_source")
        for index in SEQUENCER_HELP_INSTANCES
        for mode in BEAT_SOURCE_LABELS
    ]
    return targets


def _apply_help_targets() -> None:
    """Attach every e76 card whose control already exists (e76s03..e76s08)."""
    for tag, key in list(HELP_TARGETS.items()) + _sequencer_help_targets():
        if dpg.does_item_exist(tag):
            help_tooltip(tag, key)


MIDI_MODE_STATUS_TAG = "midi_mode_status"
MIDI_MODES_SCROLL_TAG = "midi_modes_scroll"
MIDI_MODES_GROUP_TAG = "midi_modes_group"
MIDI_MODE_DELETE_CONFIRM_TAG = "midi_mode_delete_confirm"
MIDI_MODE_LED_FIELDS: tuple[str, ...] = ("number", "on_value", "off_value")
MIDI_MODE_LED_FIELD_DEFAULTS: dict[str, int] = {
    "number": 0,
    "on_value": MIDI_MODE_LED_ON_DEFAULT,
    "off_value": MIDI_MODE_LED_OFF_DEFAULT,
}
MODE_BADGE_GROUP_TAG = "mode_badges"
MODE_BADGE_ABBREV_CHARS = 3
MODE_BADGE_W = 26
MODE_BADGE_H = 18
MODE_BADGE_TIP = "Mode {name} - click to turn it off"
# e52s06 (rig feedback 2026-09-20): the strip is a SEPARATE window, decoupled
# from the toolbar. Coupling it to the bar's width broke the bar itself (the
# whole icon row vanished when no mode was active), so the bar is back to its
# e46 shape and the badges live in their own small always-on-top window at the
# top-left, hidden while no mode is active.
MODE_BADGES_WINDOW_TAG = "mode_badges_window"
MODE_BADGES_POS = (2, 4)  # the bar's original top-left slot, far from the icons

# BUG-2026-09-20T mode chip: the boot project load runs BELOW this point but the
# badges window is built further down, so the paint needs an explicit "is the
# strip built yet" flag instead of a dpg query.
MODE_BADGES_READY = False


def on_add_midi_mode(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """Modes > Add: register the typed name, or say why it was refused (e52s01)."""
    typed = ""
    if dpg.does_item_exist(MIDI_MODE_NAME_INPUT_TAG):
        typed = str(dpg.get_value(MIDI_MODE_NAME_INPUT_TAG) or "")
    added = add_mode(typed)
    if dpg.does_item_exist(MIDI_MODE_STATUS_TAG):
        message = f"Mode '{added}' added" if added else "Enter a unique, non-empty mode name"
        dpg.set_value(MIDI_MODE_STATUS_TAG, message)
    if added and dpg.does_item_exist(MIDI_MODE_NAME_INPUT_TAG):
        dpg.set_value(MIDI_MODE_NAME_INPUT_TAG, "")
    refresh_midi_modes_ui()


def on_delete_midi_mode(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """Modes > Delete: open the counted confirmation (e52s01; e52s03 counts it)."""
    show_midi_mode_delete_confirm(str(user_data or ""))


def show_midi_mode_delete_confirm(name: str) -> None:
    """Open the delete-a-mode modal, stating what the delete would touch (e52s03)."""
    if dpg.does_item_exist(MIDI_MODE_DELETE_CONFIRM_TAG):
        dpg.delete_item(MIDI_MODE_DELETE_CONFIRM_TAG)
    counts = mode_usage(name)
    with dpg.window(
        label="Delete mode",
        tag=MIDI_MODE_DELETE_CONFIRM_TAG,
        modal=True,
        width=420,
        height=150,
        no_resize=True,
    ):
        themed_text(f"Delete mode '{name}'?", slot="text")
        themed_text(
            f"{counts['bindings_untagged']} binding(s) return to base, "
            f"{counts['toggle_rows_dropped']} toggle binding(s) removed.",
            slot="text_dim",
        )
        dpg.add_separator()
        with dpg.group(horizontal=True):
            dpg.add_button(label="Cancel", callback=cancel_midi_mode_delete, width=140)
            dpg.add_button(
                label="Delete",
                callback=confirm_midi_mode_delete,
                user_data=name,
                width=140,
            )
    show_centered_window(MIDI_MODE_DELETE_CONFIRM_TAG)  # e55: dialogs open centered


def cancel_midi_mode_delete(
    sender: Any = None, app_data: Any = None, user_data: Any = None
) -> None:
    """Delete-mode modal Cancel: close it, nothing changes (e52s03)."""
    if dpg.does_item_exist(MIDI_MODE_DELETE_CONFIRM_TAG):
        dpg.delete_item(MIDI_MODE_DELETE_CONFIRM_TAG)


def confirm_midi_mode_delete(
    sender: Any = None, app_data: Any = None, user_data: Any = None
) -> None:
    """Delete-mode modal Delete: clear the tags, drop the toggle rows, rebuild (e52s03)."""
    name = str(user_data or "")
    cancel_midi_mode_delete()
    counts = remove_mode(name)
    if dpg.does_item_exist(MIDI_MODE_STATUS_TAG):
        dpg.set_value(
            MIDI_MODE_STATUS_TAG,
            f"Mode '{name}' deleted ({counts['bindings_untagged']} binding(s) back to base)",
        )
    refresh_midi_modes_ui()
    refresh_midi_mappings_ui()
    refresh_mapper_ui()


def on_midi_mode_led_change(
    sender: Any = None, app_data: Any = None, user_data: Any = None
) -> None:
    """A mode's LED editor changed: merge the field into the mode's LED spec (e52s01)."""
    name, field = user_data
    definition = mode_definition(name)
    led = dict(definition.get("led") or {}) if definition is not None else {}
    led.setdefault("controller_port", "")
    led.setdefault("kind", MIDI_MODE_LED_KINDS[0])
    for key, default in MIDI_MODE_LED_FIELD_DEFAULTS.items():
        led.setdefault(key, default)
    value = app_data
    led[field] = str(value) if field in ("controller_port", "kind") else int(value or 0)
    set_mode_led(name, led)


def _midi_mode_led_editor(name: str) -> None:
    """One mode's compact LED editor: controller, kind, number, on, off (e52s01)."""
    definition = mode_definition(name)
    led = definition.get("led") if isinstance(definition, dict) else None
    led = led if isinstance(led, dict) else {}
    ports = [str(controller.get("port") or "") for controller in midi_controllers]
    port = str(led.get("controller_port") or (ports[0] if ports else ""))
    with dpg.group(horizontal=True):
        dpg.add_combo(
            items=ports,
            default_value=port,
            width=130,
            tag=f"midi_mode_led_port_{name}",
            callback=on_midi_mode_led_change,
            user_data=(name, "controller_port"),
        )
        dpg.add_combo(
            items=list(MIDI_MODE_LED_KINDS),
            default_value=str(led.get("kind") or MIDI_MODE_LED_KINDS[0]),
            width=64,
            callback=on_midi_mode_led_change,
            user_data=(name, "kind"),
        )
        for field in MIDI_MODE_LED_FIELDS:
            dpg.add_drag_int(
                default_value=int(led.get(field) or MIDI_MODE_LED_FIELD_DEFAULTS[field]),
                width=52,
                callback=on_midi_mode_led_change,
                user_data=(name, field),
            )


def refresh_midi_modes_ui() -> None:
    """Rebuild the Modes list of the MIDI window (e52s01)."""
    if not dpg.does_item_exist(MIDI_MODES_GROUP_TAG):
        return
    dpg.delete_item(MIDI_MODES_GROUP_TAG, children_only=True)
    for name in mode_names():
        with dpg.group(horizontal=True, parent=MIDI_MODES_GROUP_TAG) as row:
            dpg.add_text(name)
            _midi_mode_led_editor(name)
            if state.midi_learn_mode:
                learn_marker(
                    MIDI_ACTION_MODE_TOGGLE,
                    {"mode": name},
                    parent=row,
                    tag=f"midi_mode_mk_{name}",
                    tooltip=f"Map: toggle mode {name}",
                )
            dpg.add_button(label="Delete", callback=on_delete_midi_mode, user_data=name)
    refresh_mode_chip()


def mode_badge_tag(index: int) -> str:
    """Tag of one badge in the strip (index-based: a mode name is free text) (e52s06)."""
    return f"mode_badge_{index}"


def mode_badge_label(name: str) -> str:
    """The compact badge caption: the first few characters, uppercased (e52s06)."""
    return str(name).strip()[:MODE_BADGE_ABBREV_CHARS].upper()


def active_modes_in_order() -> list[str]:
    """The active mode names, activation order first (e52s06; extras sorted)."""
    ordered = [name for name in state.midi_mode_order if name in state.midi_modes]
    extras = sorted(name for name in state.midi_modes if name not in ordered)
    return ordered + extras


def mode_badges_width() -> int:
    """Width the badge strip window needs, 0 with no active mode (e52s06)."""
    count = len(state.midi_modes)
    if count == 0:
        return 0
    return count * (MODE_BADGE_W + TOOLBAR_ITEM_SPACING)


def _build_mode_badges_window() -> None:
    """The SEPARATE active-mode strip, independent of the toolbar (e52s06).

    Built closed (`with dpg.group(...): pass`) because DearPyGui discards a bare
    group (BUG-2026-09-20T). Hidden until a mode is active; never part of the
    bar's width or position, so it cannot hide the icon row again.
    """
    with (
        dpg.window(
            label="Modes",
            tag=MODE_BADGES_WINDOW_TAG,
            no_title_bar=True,
            no_resize=True,
            no_move=True,
            no_scrollbar=True,
            no_collapse=True,
            no_background=True,
            no_bring_to_front_on_focus=True,
            no_saved_settings=True,
            no_scroll_with_mouse=True,
            width=mode_badges_width() or MODE_BADGE_W,
            height=TOOLBAR_BAR_H,
            pos=MODE_BADGES_POS,
            show=False,
        ),
        dpg.group(tag=MODE_BADGE_GROUP_TAG, horizontal=True),
    ):
        pass
    dpg.bind_item_theme(MODE_BADGES_WINDOW_TAG, TOOLBAR_THEME_PLAIN)
    global MODE_BADGES_READY
    MODE_BADGES_READY = True


def refresh_mode_chip() -> None:
    """Rebuild the active-mode badge strip, in its OWN window (e52s01/e52s06).

    One small badge per active mode, in activation order; the tooltip carries the
    full name and a click turns THAT mode off. The strip window hugs the count
    and is hidden while nothing is active. Decoupled from the toolbar on purpose:
    nothing here touches the bar's width or position.
    """
    if not MODE_BADGES_READY:
        # BUG-2026-09-20: the boot project load reaches this from
        # apply_project_state BEFORE the strip window is built, so there is
        # nothing to paint yet. The flag (not a dpg query) makes it explicit.
        return
    dpg.delete_item(MODE_BADGE_GROUP_TAG, children_only=True)
    names = active_modes_in_order()
    for index, name in enumerate(names):
        tag = mode_badge_tag(index)
        dpg.add_button(
            label=mode_badge_label(name),
            tag=tag,
            parent=MODE_BADGE_GROUP_TAG,
            width=MODE_BADGE_W,
            height=MODE_BADGE_H,
            callback=on_mode_badge_click,
            user_data=name,
        )
        dpg.bind_item_theme(tag, TOOLBAR_THEME_LEARN)
        with dpg.tooltip(tag, delay=HELP_HOVER_DELAY_S) as tip_tag:
            dpg.add_text(MODE_BADGE_TIP.format(name=name))
        dpg.bind_item_theme(tip_tag, HELP_THEME_TOOLTIP)
    if not names:
        dpg.hide_item(MODE_BADGES_WINDOW_TAG)
        return
    dpg.configure_item(MODE_BADGES_WINDOW_TAG, width=mode_badges_width())
    dpg.show_item(MODE_BADGES_WINDOW_TAG)


def on_mode_badge_click(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """A toolbar badge click turns THAT mode off, LEDs included (e52s06)."""
    name = str(user_data or "")
    if toggle_mode(name) is False:
        send_mode_led(name, False)
    refresh_midi_modes_ui()  # its tail re-paints the strip too


def refresh_midi_devices(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """Re-scan MIDI inputs, update the Controllers Add combo and the port-status
    line (e14s03; BUG-2026-09-07 — a failed scan is shown, never silently empty)."""
    names, error = scan_midi_inputs()
    if dpg.does_item_exist("midi_add_combo"):
        used = {c["port"] for c in midi_controllers}
        dpg.configure_item("midi_add_combo", items=[n for n in names if n not in used])
    _update_midi_ports_status(names, error)


def _update_midi_ports_status(names: list[str], error: str | None) -> None:
    """Write the input-scan outcome to the MIDI window status line (BUG-2026-09-07)."""
    if not dpg.does_item_exist("midi_ports_status"):
        return
    text = f"Port scan failed: {error}" if error else f"{len(names)} MIDI input(s) available"
    dpg.set_value("midi_ports_status", text)


def add_controller_from_port(port_name: str) -> None:
    """Add a MIDI input port as a controller (profile auto-detected) and persist (e14s03)."""
    if not port_name or find_controller_by_port(port_name) is not None:
        return
    profile = match_controller_profile(port_name, controller_profiles())
    has_grid = bool(profile and profile.get("features", {}).get("grid"))
    controller: dict[str, Any] = {
        "port": port_name,
        "profile_id": profile["id"] if profile else "",
        "role": grid_role(0) if has_grid and grid_controller() is None else None,
        "bindings": [],
        "output": None,
        "auto_bindings": [],
    }
    midi_controllers.append(controller)
    save_midi_controllers()
    render_controllers_ui()


def remove_controller(port_name: str) -> None:
    """Remove a controller (closes its output) and persist (e14s03)."""
    controller = find_controller_by_port(port_name)
    if controller is not None:
        controller_disconnect(controller)
        midi_controllers.remove(controller)
    save_midi_controllers()
    render_controllers_ui()


def assign_grid_role(port_name: str, index: int = 0) -> None:
    """Designate a controller as ONE sequencer's grid; exclusive PER SLOT (e14s03/e67s06).

    The role is one string, so a controller holds at most ONE grid: assigning slot B to a
    controller that held slot A MOVES it. A slot holds at most one controller, and a legacy
    `grid` resolves to A, so assigning slot A heals it. Assigning the same pair twice changes
    nothing, which is what makes the roster's two buttons safe to press again.
    """
    wanted = grid_role(index)
    for controller in midi_controllers:
        if controller["port"] == port_name:
            controller["role"] = wanted
        elif role_sequencer_index(controller.get("role")) == index:
            controller["role"] = None
    save_midi_controllers()
    # BUG-2026-10-16: the auto bindings are a PROJECTION of (role, profile, geometry), and
    # only a reconnect used to rebuild them. The roster therefore left the pads unarmed: the
    # LED mirror lit them (it needs the role, not the bindings) while every press resolved to
    # nothing. Rebuild here, clear the device that lost the slot, and light the truth.
    rebound = reregister_grid_bindings()
    refresh_binding_leds()
    assigned = find_controller_by_port(port_name)
    pads = len(assigned.get("auto_bindings") or []) if assigned is not None else 0
    append_log(
        "MIDI",
        f"{port_name}: grid {'A' if index == 0 else 'B'} - {pads} pads"
        + ("" if rebound else " (no grid profile)"),
    )
    render_controllers_ui()


def _on_assign_grid_role(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """A roster button: `user_data` carries `(port, index)` (e67s06)."""
    port, index = user_data
    assign_grid_role(str(port), int(index))


def on_select_controller(port_name: str) -> None:
    """Pick which controller's Bindings the MIDI window edits (e53 rig fix)."""
    state.midi_selected_port = str(port_name)
    render_controllers_ui()  # also refreshes the Bindings list


def render_controllers_ui() -> None:
    """Rebuild the Controllers list rows (main thread; call after any change) (e14s03)."""
    if not dpg.does_item_exist("midi_controllers_group"):
        return
    dpg.delete_item("midi_controllers_group", children_only=True)
    current = selected_controller()
    current_port = str(current.get("port") or "") if current is not None else ""
    for controller in midi_controllers:
        profile = controller_profile_of(controller)
        profile_name = profile.get("name", "Generic") if profile else "Generic"
        role_index = role_sequencer_index(controller.get("role"))
        role_mark = ""
        if role_index is not None:
            role_mark = f" [grid {'A' if role_index == 0 else 'B'}]"
        picked = " [selected]" if str(controller["port"]) == current_port else ""
        with dpg.group(horizontal=True, parent="midi_controllers_group"):
            dpg.add_text(f"{controller['port']} - {profile_name}{role_mark}{picked}")
            port = controller["port"]
            dpg.add_button(
                label="Select",
                callback=lambda s, a, p=port: on_select_controller(p),
                user_data=port,
            )
            if profile and profile.get("features", {}).get("grid"):
                # e67s06: ONE slot per button, and the slot it already holds is not offered.
                for slot, slot_name in ((0, "A"), (1, "B")):
                    if role_index == slot:
                        continue
                    dpg.add_button(
                        label=f"Set as grid {slot_name}",
                        callback=_on_assign_grid_role,
                        user_data=(port, slot),
                    )
            dpg.add_button(
                label="Remove",
                callback=lambda s, a, p=port: remove_controller(p),
                user_data=port,
            )
    # BUG-2026-09-07: combo + port-status line follow the scan
    refresh_midi_devices()
    refresh_midi_mappings_ui()


def show_midi_window(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """Open the MIDI window from the menubar, with a fresh device list, controller
    list and the selected controller's mappings (render_controllers_ui refreshes
    the mappings too)."""
    refresh_midi_devices()
    render_controllers_ui()
    dpg.show_item("midi_window")
    dpg.focus_item("midi_window")  # e17: a shown window must come to the front


# --- MIDI MONITOR (e39s01) ---------------------------------------------------
# Diagnostic window: the incoming MIDI stream WITH the resolution outcome plus a
# per-control calibration table. NOT in LAYOUT_WINDOW_TAGS — a saved layout must
# never pop a debug window at boot; geometry is session-only.
IO_MONITOR_WINDOW_WIDTH = 980
IO_MONITOR_WINDOW_HEIGHT = 620
IO_MONITOR_TEXT_HEIGHT = 250
IO_MONITOR_ALL_PORTS = "All ports"

_io_monitor_paused = False
_io_monitor_port: str | None = None
_io_monitor_ports: list[str] = []
# e39s05: the direction filter — None = both, else IO_MONITOR_DIRECTION_IN/OUT.
_io_monitor_direction: str | None = None
# e39s05: the transport filter — None = both, else IO_MONITOR_TRANSPORT_MIDI/OSC.
_io_monitor_transport: str | None = None
# e81: an OUTCOME filter — the stream already knows what the app made of each message.
_io_monitor_outcome: str | None = None
_IO_MONITOR_OUTCOME_LABELS: dict[str, str | None] = {
    "All outcomes": None,
    "Sent": IO_MONITOR_OUTCOME_SENT,
    "Received": IO_MONITOR_OUTCOME_RECV,
    "Matched": IO_MONITOR_OUTCOME_MATCH,
    "No match": IO_MONITOR_OUTCOME_NOMATCH,
    "No binding": IO_MONITOR_OUTCOME_NOBIND,
    "Learn": IO_MONITOR_OUTCOME_LEARN,
    "Muted": IO_MONITOR_OUTCOME_MUTED,
    "Ignored": IO_MONITOR_OUTCOME_IGNORED,
}
_io_monitor_transports: list[str] = []
_io_monitor_filter_control: tuple[str, str, int, int, str] | None = None
_io_monitor_control_items: dict[str, tuple[str, str, int, int, str]] = {}
_io_monitor_mapping_items: dict[str, int] = {}
_io_monitor_last_revision = -1
_io_monitor_last_refresh = 0.0


IO_MONITOR_DIRECTION_BOTH = "In + Out"
_IO_MONITOR_DIRECTION_LABELS: dict[str, str | None] = {
    IO_MONITOR_DIRECTION_BOTH: None,
    "In only": IO_MONITOR_DIRECTION_IN,
    "Out only": IO_MONITOR_DIRECTION_OUT,
}


def _io_monitor_direction_label() -> str:
    """The combo label of the active direction filter (e39s05)."""
    for label, value in _IO_MONITOR_DIRECTION_LABELS.items():
        if value == _io_monitor_direction:
            return label
    return IO_MONITOR_DIRECTION_BOTH


def on_io_monitor_direction(
    sender: Any = None, app_data: Any = None, user_data: Any = None
) -> None:
    """Direction combo: narrow the stream to what VJmix receives or sends (e39s05)."""
    global _io_monitor_direction
    _io_monitor_direction = _IO_MONITOR_DIRECTION_LABELS.get(
        str(app_data or IO_MONITOR_DIRECTION_BOTH)
    )
    refresh_io_monitor()


# e83: the third transport is the data plane (state_pull / event_stream / interest,
# e82s05), so the filter must be able to isolate it and the "all" label must not
# claim it is only MIDI + OSC.
IO_MONITOR_TRANSPORT_ALL = "All transports"
_IO_MONITOR_TRANSPORT_LABELS: dict[str, str | None] = {
    IO_MONITOR_TRANSPORT_ALL: None,
    "MIDI only": IO_MONITOR_TRANSPORT_MIDI,
    "OSC only": IO_MONITOR_TRANSPORT_OSC,
    "HTTP only": IO_MONITOR_TRANSPORT_HTTP,
}


def on_io_monitor_outcome(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """Outcome combo: narrow the stream to what the app made of the message (e81)."""
    global _io_monitor_outcome
    _io_monitor_outcome = _IO_MONITOR_OUTCOME_LABELS.get(str(app_data or "All outcomes"))
    refresh_io_monitor()


def on_io_monitor_transport(
    sender: Any = None, app_data: Any = None, user_data: Any = None
) -> None:
    """Transport combo: MIDI, OSC or both in the stream (e39s05)."""
    global _io_monitor_transport
    _io_monitor_transport = _IO_MONITOR_TRANSPORT_LABELS.get(
        str(app_data or IO_MONITOR_TRANSPORT_ALL)
    )
    refresh_io_monitor()


def _io_monitor_port_options() -> list[str]:
    """The Peer-filter options: 'All peers' plus every peer seen or configured.

    e39s05: it lists the MIDI ports AND the OSC peers (host:port) seen in the
    stream, so the filter covers both transports.
    """
    ports = {str(row["port"]) for row in iomonitor.snapshot_controls()}
    ports.update(iomonitor.peers())
    ports.update(str(c.get("port", "")) for c in midi_controllers if c.get("port"))
    return [IO_MONITOR_ALL_PORTS, *sorted(p for p in ports if p)]


def _monitor_sync_ports() -> None:
    """Keep the port combo in sync with the ports seen/configured (e39s01).

    Tracks the last rendered option list in a module global instead of reading
    the widget: a reconfigure happens only when the set actually changed.
    """
    global _io_monitor_ports
    options = _io_monitor_port_options()
    if options == _io_monitor_ports:
        return
    _io_monitor_ports = options
    if dpg.does_item_exist("io_monitor_port"):
        dpg.configure_item("io_monitor_port", items=options)


def _control_label(control: tuple[str, str, int, int, str]) -> str:
    """Picker label of one control: 'cc ch0 #7 @port'."""
    port, msg_type, channel, number, _direction = control
    return f"{msg_type} ch{int(channel)} #{int(number)} @{port}"


def _mapping_label(mapping: dict[str, Any]) -> str:
    """Picker label of one Mapper mapping: '#3 speed (clipA)'."""
    return f"#{int(mapping['id'])} {mapping.get('property', '?')} ({mapping.get('target_id', '?')})"


def _monitor_sync_controls() -> None:
    """Keep the control + mapping pickers in sync (e39s03).

    Tracks the last rendered items in module globals and reconfigures only when
    the sets changed, so a selected value is never reset per refresh.
    """
    global _io_monitor_control_items, _io_monitor_mapping_items
    controls = {
        _control_label(tuple(row["key"])): tuple(row["key"])
        for row in iomonitor.snapshot_controls()
    }
    if controls != _io_monitor_control_items:
        _io_monitor_control_items = controls
        if dpg.does_item_exist("io_monitor_control_combo"):
            dpg.configure_item("io_monitor_control_combo", items=list(controls))
    mappings = {_mapping_label(m): int(m["id"]) for m in state.mapper_mappings}
    if mappings != _io_monitor_mapping_items:
        _io_monitor_mapping_items = mappings
        if dpg.does_item_exist("io_monitor_mapping_combo"):
            dpg.configure_item("io_monitor_mapping_combo", items=list(mappings))


def show_io_monitor(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """Open (or raise) the I/O Monitor diagnostic window (e39s01)."""
    if dpg.does_item_exist("io_monitor_window"):
        dpg.show_item("io_monitor_window")
        dpg.focus_item("io_monitor_window")
        return
    _build_io_monitor_window()


def _build_io_monitor_window() -> None:
    """Build the monitor window (toolbar + stream/controls panes, e39s01)."""
    with dpg.window(
        label="I/O Monitor",
        tag="io_monitor_window",
        width=IO_MONITOR_WINDOW_WIDTH,
        height=IO_MONITOR_WINDOW_HEIGHT,
        show=False,
    ):
        with dpg.group(horizontal=True):
            dpg.add_button(label="Pause", tag="io_monitor_pause", callback=toggle_io_monitor_pause)
            dpg.add_button(label="Clear", callback=clear_io_monitor)
            dpg.add_button(label="Reset stats", callback=reset_io_monitor_stats)
            dpg.add_button(label="Copy report", callback=copy_io_monitor_report)
            themed_text("Peer", slot="text_dim")
            dpg.add_combo(
                items=_io_monitor_port_options(),
                default_value=IO_MONITOR_ALL_PORTS,
                width=220,
                tag="io_monitor_port",
                callback=on_io_monitor_port,
            )
            # e39s05: in / out / both — the stream sees both directions now.
            themed_text("Direction", slot="text_dim")
            dpg.add_combo(
                items=list(_IO_MONITOR_DIRECTION_LABELS),
                default_value=IO_MONITOR_DIRECTION_BOTH,
                width=110,
                tag="io_monitor_direction",
                callback=on_io_monitor_direction,
            )
            themed_text("Transport", slot="text_dim")
            dpg.add_combo(
                items=list(_IO_MONITOR_TRANSPORT_LABELS),
                default_value=IO_MONITOR_TRANSPORT_ALL,
                width=130,
                tag="io_monitor_transport",
                callback=on_io_monitor_transport,
            )
            themed_text("Outcome", slot="text_dim")
            dpg.add_combo(
                items=list(_IO_MONITOR_OUTCOME_LABELS),
                default_value="All outcomes",
                width=130,
                tag="io_monitor_outcome",
                callback=on_io_monitor_outcome,
            )
            dpg.add_group(tag="io_monitor_learn_slot", horizontal=True)
        themed_text(
            "Every OSC and MIDI message, in and out, with what the app made of it. "
            "Application events are in Logs.",
            slot="text_dim",
            wrap=IO_MONITOR_WINDOW_WIDTH - 40,
            tag="io_monitor_legend",
        )
        with dpg.group(horizontal=True):
            themed_text("Control", slot="text_dim")
            dpg.add_combo(items=[], width=240, tag="io_monitor_control_combo")
            dpg.add_button(label="Filter", callback=filter_io_monitor_control)
            dpg.add_button(label="Copy id", callback=copy_io_monitor_control_id)
            themed_text("Mapping", slot="text_dim")
            dpg.add_combo(items=[], width=240, tag="io_monitor_mapping_combo")
            dpg.add_button(label="Assign", callback=assign_io_monitor_control)
        themed_text("Stream (newest first, in + out)", slot="text_dim")
        dpg.add_input_text(
            tag="io_monitor_stream_text",
            multiline=True,
            readonly=True,
            width=-1,
            height=IO_MONITOR_TEXT_HEIGHT,
            default_value="No traffic yet.",
        )
        themed_text("Controls", slot="text_dim")
        dpg.add_input_text(
            tag="io_monitor_controls_text",
            multiline=True,
            readonly=True,
            width=-1,
            height=IO_MONITOR_TEXT_HEIGHT,
            default_value="No control seen yet.",
        )
    _apply_help_targets()  # e76: this window is built on demand, not at import
    show_centered_window("io_monitor_window")  # e55: the diagnostic opens centered
    _sync_monitor_learn_marker()
    refresh_io_monitor()


def toggle_io_monitor_window(
    sender: Any = None, app_data: Any = None, user_data: Any = None
) -> None:
    """Show / close the I/O Monitor window (IO_MONITOR_TOGGLE executor, e39s01)."""
    if dpg.does_item_exist("io_monitor_window"):
        dpg.delete_item("io_monitor_window")
        return
    show_io_monitor()


def _exec_monitor_toggle(params: dict[str, Any], value: int) -> None:
    """e39s01: a momentary press (CC >= 64 / note) shows or closes the monitor."""
    if value < MIDI_CC_TRIGGER_THRESHOLD:
        return
    toggle_io_monitor_window()


def _exec_pairing_prompt(params: dict[str, Any], value: int) -> None:
    """e42s02: a momentary press re-opens the pairing prompt (re-pair).

    Needed because viOSC rotates its code on every start: after a daemon restart
    VJmix's token is stale and this is the way back without restarting vjmix.
    """
    if value < MIDI_CC_TRIGGER_THRESHOLD:
        return
    show_pairing_prompt()


def _exec_mapping_toggle(params: dict[str, Any], value: int) -> None:
    """e40s01: a momentary press arms/disarms a Mapping (its Enabled gate).

    The arm checkbox follows in place when its row is on screen; a stale
    mapping id is a logged no-op.
    """
    if value < MIDI_CC_TRIGGER_THRESHOLD:
        return
    mapping = mapper.find_mapping(int(params.get("mapping_id", 0)))
    if mapping is None:
        _log_stale_midi_target(MIDI_ACTION_MAPPING_TOGGLE, f"no mapping {params.get('mapping_id')}")
        return
    enabled = not bool(mapping.get("enabled", False))
    mapper.set_mapping_enabled(int(mapping["id"]), enabled)
    if dpg.does_item_exist(f"mapping_enable_{mapping['id']}"):
        dpg.set_value(f"mapping_enable_{mapping['id']}", enabled)
    refresh_binding_leds()  # e53s02


def _exec_mapping_add(params: dict[str, Any], value: int) -> None:
    """e40s08/e40s10: a momentary press opens the Mapping creator.

    ``{"line": n}`` anchors it to that Source line (resolved through
    mapper.row_targets() at TRIGGER time — a binding never captures a volatile
    source id), ``{"source_less": true}`` is the Clock+Constant creator and no
    param is the general creator. A stale line index is a logged no-op.
    """
    if value < MIDI_CC_TRIGGER_THRESHOLD:
        return
    if "line" in params:
        line = int(params.get("line", -1))
        rows = mapper.row_targets()
        if line < 0 or line >= len(rows):
            _log_stale_midi_target(MIDI_ACTION_MAPPING_ADD, f"no line {line}")
            return
        open_line_mapping_creator(user_data=rows[line])
        return
    if params.get("source_less"):
        open_source_less_mapping_creator()
        return
    open_mapping_creator()


def _sync_sources_data_learn_marker() -> None:
    """(Re)render the Sources-data toolbar's learn marker (e82s08, the e33 rule).

    The toolbar is built once at boot, so its marker cannot be emitted at render
    time; this slot is re-rendered on every learn transition.
    """
    if not dpg.does_item_exist(SOURCES_DATA_LEARN_SLOT):
        return
    dpg.delete_item(SOURCES_DATA_LEARN_SLOT, children_only=True)
    if state.midi_learn_mode:
        learn_marker(
            MIDI_ACTION_SOURCES_DATA_REFRESH,
            {},
            parent=SOURCES_DATA_LEARN_SLOT,
            tag="sources_data_mk_refresh",
        )


def _sync_filter_learn_marker() -> None:
    """(Re)render the filter bar's create-action learn marker (e40s11, e33 rule).

    The filter bar is built once at boot, so its marker cannot be emitted
    conditionally at render time like the body's; this slot is re-rendered on
    every learn transition, next to the general '+'.
    """
    if not dpg.does_item_exist("mapper_filter_learn_slot"):
        return
    dpg.delete_item("mapper_filter_learn_slot", children_only=True)
    if state.midi_learn_mode:
        learn_marker(
            MIDI_ACTION_MAPPING_ADD,
            {},
            parent="mapper_filter_learn_slot",
            tag="mapper_mk_filter",
        )


def _sync_monitor_learn_marker() -> None:
    """(Re)render the monitor toggle's learn marker (e39s01, e33 rule).

    Markers exist only while learn mode is on; _refresh_learn_surfaces calls
    this on every learn transition (the slot lives in the window toolbar).
    """
    if not dpg.does_item_exist("io_monitor_learn_slot"):
        return
    dpg.delete_item("io_monitor_learn_slot", children_only=True)
    if state.midi_learn_mode:
        learn_marker(
            MIDI_ACTION_IO_MONITOR_TOGGLE,
            {},
            parent="io_monitor_learn_slot",
            tag="io_monitor_mk_toggle",
            tooltip="Map: I/O Monitor window",
        )


def _sync_settings_pairing_learn_marker() -> None:
    """(Re)render the pairing action's learn marker (e42s02, e33 rule).

    The Settings window is built once at boot, so its marker slot is re-rendered
    on every learn transition, next to the 'Pair with viOSC...' button.
    """
    if not dpg.does_item_exist("settings_pairing_learn_slot"):
        return
    dpg.delete_item("settings_pairing_learn_slot", children_only=True)
    if state.midi_learn_mode:
        learn_marker(
            MIDI_ACTION_PAIRING_PROMPT,
            {},
            parent="settings_pairing_learn_slot",
            tag="settings_pairing_mk",
            tooltip="Map: Pair with viOSC",
        )


def on_io_monitor_port(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """Port-filter combo: 'All ports' clears the filter, any port narrows both panes."""
    global _io_monitor_port
    value = str(app_data or IO_MONITOR_ALL_PORTS)
    _io_monitor_port = None if value == IO_MONITOR_ALL_PORTS else value
    refresh_io_monitor()


def toggle_io_monitor_pause(
    sender: Any = None, app_data: Any = None, user_data: Any = None
) -> None:
    """Pause freezes the view (recording continues); resume repaints at once."""
    global _io_monitor_paused
    _io_monitor_paused = not _io_monitor_paused
    if dpg.does_item_exist("io_monitor_pause"):
        dpg.set_item_label("io_monitor_pause", "Resume" if _io_monitor_paused else "Pause")
    if not _io_monitor_paused:
        refresh_io_monitor()


def clear_io_monitor(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """Drop both panes' data (Clear button, e39s01)."""
    iomonitor.clear()
    refresh_io_monitor()


def reset_io_monitor_stats(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """Zero the per-control envelopes/counters but keep the rows (e39s02)."""
    iomonitor.reset_controls()
    refresh_io_monitor()


def _io_monitor_texts() -> tuple[str, str]:
    """The current (stream, controls) pane texts under the active filters."""
    port = _io_monitor_port
    stream = iomonitor.format_stream(
        iomonitor.snapshot_stream(
            port=port,
            control=_io_monitor_filter_control,
            direction=_io_monitor_direction,
            transport=_io_monitor_transport,
            outcome=_io_monitor_outcome,
        )
    )
    return stream, iomonitor.format_controls(iomonitor.snapshot_controls(port=port))


def refresh_io_monitor() -> None:
    """Write both pane texts and remember the engine revision (e39s01)."""
    global _io_monitor_last_revision, _io_monitor_last_refresh
    if not dpg.does_item_exist("io_monitor_window"):
        return
    _io_monitor_last_revision = iomonitor.revision()
    _io_monitor_last_refresh = time.monotonic()
    _monitor_sync_ports()
    _monitor_sync_controls()
    stream_text, controls_text = _io_monitor_texts()
    dpg.set_value("io_monitor_stream_text", stream_text)
    dpg.set_value("io_monitor_controls_text", controls_text)


def copy_io_monitor_report(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """Put the stream + controls snapshot on the clipboard (Copy report)."""
    stream_text, controls_text = _io_monitor_texts()
    dpg.set_clipboard_text(iomonitor.format_report(stream_text, controls_text))


def _io_monitor_selected_control() -> tuple[str, str, int, int, str] | None:
    """The control picked in the picker (None when nothing is selected)."""
    return _io_monitor_control_items.get(str(dpg.get_value("io_monitor_control_combo")))


def filter_io_monitor_control(
    sender: Any = None, app_data: Any = None, user_data: Any = None
) -> None:
    """Toggle the stream filter onto the picked control (e39s03)."""
    global _io_monitor_filter_control
    control = _io_monitor_selected_control()
    if control is None:
        return
    _io_monitor_filter_control = None if control == _io_monitor_filter_control else control
    refresh_io_monitor()


def copy_io_monitor_control_id(
    sender: Any = None, app_data: Any = None, user_data: Any = None
) -> None:
    """Put the picked control's id on the clipboard (e39s03)."""
    control = _io_monitor_selected_control()
    if control is None:
        return
    dpg.set_clipboard_text(iomonitor.control_id(control))


def assign_io_monitor_control(
    sender: Any = None, app_data: Any = None, user_data: Any = None
) -> None:
    """Bind the picked control to the picked Mapper mapping (e39s03)."""
    control = _io_monitor_selected_control()
    mapping_id = _io_monitor_mapping_items.get(str(dpg.get_value("io_monitor_mapping_combo")))
    if control is None or mapping_id is None:
        return
    assign_control_to_mapping(control, mapping_id)


def assign_control_to_mapping(control: tuple[str, str, int, int, str], mapping_id: int) -> bool:
    """Bind an already-seen control to a Mapper mapping immediately (e39s03).

    The reverse of a learn session: the monitor already knows the source
    (device/channel/type/number), so the dispatch binding lands on the controller
    that owns the port and the mapping's stored MIDI source plus its 0..127 input
    range are set at once. An unknown mapping id is a logged no-op; so is a port
    no controller owns (BUG-2026-09-18T194700: the mapping must not claim a source
    that can never fire).
    """
    port, msg_type, channel, number, _direction = control
    if mapper.find_mapping(mapping_id) is None:
        log_error("I/O Monitor", f"no mapping {mapping_id}")
        return False
    controller = find_controller_by_port(port)
    if controller is None:
        log_error(
            "I/O Monitor",
            f"no controller owns port {port!r} — add it in the MIDI window first",
        )
        return False
    source: dict[str, Any] = {
        "device": port,
        "channel": int(channel),
        "type": msg_type,
        "number": int(number),
    }
    binding = {**source, "action": MIDI_ACTION_MAPPER_MAPPING, "params": {"mapping_id": mapping_id}}
    controller.setdefault("bindings", []).append(binding)
    save_midi_controllers()
    mapper.set_mapping_midi(mapping_id, binding)
    refresh_midi_mappings_ui()
    refresh_mapper_ui()
    return True


def tick_io_monitor() -> None:
    """Refresh the I/O Monitor panes at the capped cadence (e39s01).

    Cheap no-op when the window is closed or the engine revision is unchanged;
    a spinning wheel coalesces to at most one repaint per
    IO_MONITOR_REFRESH_INTERVAL.
    """
    if not dpg.does_item_exist("io_monitor_window") or _io_monitor_paused:
        return
    if iomonitor.revision() == _io_monitor_last_revision:
        return
    if time.monotonic() - _io_monitor_last_refresh < IO_MONITOR_REFRESH_INTERVAL:
        return
    refresh_io_monitor()


# --- MAPPINGS (e40s01) ---------------------------------------------------------
# The main-loop emission tick: refresh the enabled State Mappings, rescale and emit
# their Destination values with an epsilon dedupe. The Vimix Destination is
# driven by its own control path; the OSC Destination arrives in e40s03.

_mappings_last_tick = 0.0


def _mapping_props_lookup(target_id: str) -> dict[str, Any] | None:
    """The live properties of a Mapping's source (the viOSC state table)."""
    _, props = find_source_by_name(target_id)
    return props


_sources_data_wanted = False


def _post_interest(target: str, spec: dict[str, Any]) -> bool:
    """Declare (or release, with no props) ONE target over HTTP (e82s05).

    Returns False when the daemon has no /interest (an older viOSC), which makes
    the caller fall back to the OSC watch lane for the rest of the session.
    """
    if state.interest_supported is False:
        return False
    _report, status = dataplane.post_interest(
        state.dataplane_host,
        state.dataplane_port,
        target,
        [str(prop) for prop in spec.get("props") or []],
        int(spec.get("cadence_ms") or 1000),
        bool(spec.get("once")),
    )
    iomonitor.record_http(
        IO_MONITOR_KIND_INTEREST,
        f"/interest {target}",
        f"HTTP {status}" if status is not None else "no answer",
        f"{state.dataplane_host}:{state.dataplane_port}",
        status,
    )
    if status == 404:
        state.interest_supported = False
        log_error(
            "Interest lane", "no /interest on the endpoint (older viOSC) — using /viosc/watch"
        )
        return False
    if status == 200:
        state.interest_supported = True
        return True
    return False


def _refresh_asked_props() -> None:
    """The properties some consumer asks for: the raw table's honesty (e82s05)."""
    wanted = set(STATE_TIER_PROPS)
    for spec in emission.state_watch_plan(state.mapper_mappings).values():
        wanted.update(str(prop) for prop in spec.get("props") or [])
    state.asked_props = wanted


def _refresh_all_sources_data() -> bool:
    """One-shot sweep of every readable property (e82s08).

    The raw table is NOT swept automatically on open any more: the tier's props are
    already live, and pulling the rest is a cost the operator asks for. ``once``
    makes viOSC sweep the mirror a single time and fall back to the tier.
    """
    ok = _post_interest("*", {"props": ["*"], "cadence_ms": 1000, "once": True})
    state.asked_props = state.asked_props | set(ALL_PROPERTIES)
    if dpg.does_item_exist(SOURCES_DATA_STATUS_TAG):
        dpg.set_value(
            SOURCES_DATA_STATUS_TAG,
            "Refreshing every property..." if ok else "viOSC has no /interest (older daemon)",
        )
    return ok


def on_sources_data_refresh(*_args: Any) -> None:
    """Sources data > Refresh all: the explicit full sweep (e82s08)."""
    _refresh_all_sources_data()


def _exec_sources_data_refresh(params: dict[str, Any], value: int) -> None:
    """MIDI twin of the Refresh all button (e33 rule: the action is mappable)."""
    if value < MIDI_CC_TRIGGER_THRESHOLD:
        return
    _refresh_all_sources_data()


# e82s08: the raw window's change feedback. The pixel font has ONE weight, so the
# emphasis is the bright palette colour for RAW_FLASH_SECONDS; the FIRST render of
# a cell is not a change, and a table rebuild clears both maps (its cells are new).
_RAW_TEXT_LAST: dict[str, str] = {}
_RAW_FLASH_UNTIL: dict[str, float] = {}


def _note_raw_change(tag: str, text: str) -> None:
    """Emphasise one raw cell whose displayed value just changed (e82s08)."""
    previous = _RAW_TEXT_LAST.get(tag)
    _RAW_TEXT_LAST[tag] = text
    if previous is None or previous == text:
        return
    _RAW_FLASH_UNTIL[tag] = time.monotonic() + RAW_FLASH_SECONDS
    if dpg.does_item_exist(tag):
        dpg.configure_item(tag, color=palette_rgba(state.active_palette["text_bright"]))


def tick_raw_flash() -> None:
    """Return the flashed raw cells to the normal text colour (e82s08)."""
    if not _RAW_FLASH_UNTIL:
        return
    now = time.monotonic()
    for tag, deadline in list(_RAW_FLASH_UNTIL.items()):
        if now < deadline:
            continue
        _RAW_FLASH_UNTIL.pop(tag, None)
        if dpg.does_item_exist(tag):
            dpg.configure_item(tag, color=palette_rgba(state.active_palette["text"]))


def _sync_mapping_subscriptions() -> None:
    """Hold the State Mappings' transport subscriptions (e40s01 + e40s06).

    Two lanes, coalesced per (source) — ADR-mapping-model decision 2:
    - the FAST lane: `/viosc/watch/<source> <cadence_ms> <props...>` (e40s06),
      answered with targeted `/viosc/reply/<source> <prop> <value>` deltas;
    - the FALLBACK: the 2 s `/viosc/monitor` subscription (e40s01), kept while
      the fast lane is unproven (an older daemon ignores the watch address).
      The first reply proves the lane, then the fallback stops for good.
    Only re-issues what changed; the tick runs this every frame.
    """
    plan = emission.state_watch_plan(state.mapper_mappings)
    if plan != state.mapping_watch_plan:
        for target, spec in plan.items():
            if _post_interest(target, spec):
                continue
            osc_client.send_message(
                f"/viosc/watch/{target}", [int(spec["cadence_ms"]), *spec["props"]]
            )
        for target in set(state.mapping_watch_plan) - set(plan):
            released_over_http = _post_interest(target, {"props": [], "cadence_ms": 1000})
            if not released_over_http:
                osc_client.send_message(f"/viosc/watch/{target}", [])
        state.mapping_watch_plan = plan
    _refresh_asked_props()
    desired = (
        {}
        if state.osc_watch_supported or state.interest_supported
        else {target: list(spec["props"]) for target, spec in plan.items()}
    )
    if desired == state.mapping_subscriptions:
        return
    for target, props in desired.items():
        addr = f"/viosc/monitor/{target}"
        osc_client.send_message(addr, list(props))
    for target in set(state.mapping_subscriptions) - set(desired):
        addr = f"/viosc/monitor/{target}"
        osc_client.send_message(addr, [])
    state.mapping_subscriptions = desired


def _apply_watch_reply(name: str, args: list[Any]) -> None:
    """Apply one targeted /viosc/reply delta to the state table (e40s06, main thread).

    The reply carries (property, value) pairs; the state table is the same one
    the Mapping engine and the raw view read, so the fast lane needs no other
    plumbing. The first reply proves the lane and drops the 2 s fallback.
    """
    _, props = find_source_by_name(name)
    if props is None:
        return
    for i in range(0, len(args) - 1, 2):
        props[str(args[i])] = args[i + 1]
    if state.osc_watch_supported is not True:
        state.osc_watch_supported = True
        _sync_mapping_subscriptions()


_stream_refresh_at = 0.0
_stream_pending = False


def _apply_event(event: dict[str, Any]) -> bool:
    """Apply ONE stream event to the state table (main thread, e82s04).

    Ordering and gaps are the worker's job (it refetches the snapshot on a hole);
    here the event is either the current marker or a property change. An unknown
    source is ignored: a stale event must not invent a table row.
    """
    sources = state.global_vimix_state.get("sources") or {}
    if str(event.get("kind") or "") == "current":
        index = streamlane.current_index(sources, event.get("source"))
        if index is None:
            return False
        state.global_vimix_state["current_source"] = index
        return True
    return streamlane.apply_change(sources, event)


def _refresh_after_stream() -> None:
    """Re-render the table after stream deltas, at most STREAM_UI_REFRESH_MIN_S.

    A beat-fade emits ~100 events/s: the tiles need 10 Hz, not 100. The pending
    flag makes sure the LAST event of a burst is still rendered.
    """
    global _stream_refresh_at, _stream_pending
    now = time.monotonic()
    if now - _stream_refresh_at < STREAM_UI_REFRESH_MIN_S:
        _stream_pending = True
        return
    _stream_refresh_at = now
    _stream_pending = False
    update_vimix_sources_ui(json.dumps(state.global_vimix_state))


def _emit_mapping(mapping: dict[str, Any], value: float) -> None:
    """Send one Mapping's Destination value (e40s01 MIDI, e40s03 OSC)."""
    destination = mapper.destination_of(mapping)
    spec = mapping.get("destination_spec") or {}
    if destination == DEST_OSC:
        send_mapping_osc(spec, value)
        return
    if destination != DEST_MIDI:
        return
    controller = find_controller_by_port(str(spec.get("controller_port") or ""))
    if controller is None or not ensure_mapping_output(controller):
        return
    send_mapping_midi(
        controller,
        str(spec.get("type") or MIDI_KIND_CC),
        int(spec.get("channel", 0)),
        int(spec.get("number", 0)),
        round(value),
        detail=f"mapping #{mapping['id']} {mapping.get('property', '?')}",
    )


def _mapping_clock_lookup(kind: str) -> float | None:
    """The live transport/app value of a Clock Origin (e40s02)."""
    if kind == "bpm":
        return float(state.current_bpm)
    if kind == "step":
        return float(state.current_step) if state.current_step >= 0 else None
    if kind == "playing":
        return 1.0 if state.is_playing else 0.0
    return None


def tick_mappings(now: float | None = None) -> None:
    """Emit the changed Mapping values, capped at MAPPING_TICK_INTERVAL_S (e40s01)."""
    global _mappings_last_tick
    if now is None:
        now = time.monotonic()
    if now - _mappings_last_tick < MAPPING_TICK_INTERVAL_S:
        return
    _mappings_last_tick = now
    _sync_mapping_subscriptions()
    live_ids = {int(m["id"]) for m in state.mapper_mappings}
    emission.prune_book(state.mapping_book, state.mapping_values, live_ids)
    for mapping, value in emission.plan_emissions(
        state.mapper_mappings,
        _mapping_props_lookup,
        state.mapping_book,
        state.mapping_values,
        now,
        clock_lookup=_mapping_clock_lookup,
    ):
        _emit_mapping(mapping, value)


def tick_mapper_clipboard(now: float | None = None) -> None:
    """Expire the Mapper clipboard so its Paste buttons do not ride forever (e74s11).

    Copy/cut ARM the clipboard; after `MAPPER_CLIPBOARD_TTL_SECONDS` the snapshot is
    dropped and the body rebuilds, which removes every per-line Paste button. A fresh
    copy re-arms the whole thing.
    """
    if state.mapper_clipboard is None or not state.mapper_clipboard_at:
        return
    stamp = time.monotonic() if now is None else now
    if stamp - state.mapper_clipboard_at <= MAPPER_CLIPBOARD_TTL_SECONDS:
        return
    mapper.clear_clipboard()
    refresh_mapper_ui()


def show_leap_window(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """Open the Leap Motion window from Settings > Leap Motion (e26s01)."""
    dpg.show_item("leap_window")
    dpg.focus_item("leap_window")  # e17: a shown window must come to the front


def on_leap_enable(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """Leap window Enable checkbox: persist and apply the engine toggle (e26s01).

    The worker loop reacts to state.leap_enabled on its own cadence. Disabling
    also folds the visualizer (no engine -> no frames); re-enabling restores it
    when the visualizer flag is still on (e26s04).
    """
    enabled = bool(app_data)
    set_leap_enabled(enabled)
    if dpg.does_item_exist("leap_viz_cb"):
        dpg.configure_item("leap_viz_cb", enabled=enabled)
    if dpg.does_item_exist("leap_restart_btn"):
        dpg.configure_item("leap_restart_btn", enabled=enabled)
    if not enabled:
        _apply_leap_viz_layout(False)
    elif state.leap_visualizer:
        _apply_leap_viz_layout(True)


def on_leap_restart(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """Rebuild the Leap engine from scratch (BUG-2026-09-18T212400).

    Recovery path when the engine looks stuck: the worker watches
    state.leap_generation, leaves its keep-alive loop and opens a fresh
    connection. Nothing touches the device here (the worker owns the connection).
    """
    restart_leap_engine()
    append_log("Leap", "restart requested from the window")


def on_leap_visualizer(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """Visualizer toggle (e26s04): persist + fold/unfold the panel in place.

    The worker watches state.leap_visualizer and sets/clears the LeapC Images
    policy on its own cadence; no connection work happens here.
    """
    set_leap_visualizer(bool(app_data))
    _apply_leap_viz_layout(bool(app_data))


def _apply_leap_viz_layout(shown: bool) -> None:
    """Fold/unfold the visualizer panel (e26s04, simplified by e48s02).

    The monitor is no longer its own scroll box: the four-column body lives in
    the window, so the WINDOW's scrollbar absorbs the extra 158 px and nothing
    has to be resized here.
    """
    if shown:
        dpg.show_item("leap_viz_panel")
    else:
        dpg.hide_item("leap_viz_panel")


def _leap_monitor_set_text(tag: str, text: str) -> None:
    """Update one leap-window text tag only when its rendered text changed (e26s02)."""
    if state.leap_monitor_cache.get(tag) != text:
        state.leap_monitor_cache[tag] = text
        if dpg.does_item_exist(tag):
            dpg.set_value(tag, text)


def tick_leap_visualizer() -> None:
    """Upload the latest visualizer frame on the main loop (e26s04).

    No-op while the window is missing/hidden or the engine/visualizer is off.
    The poll thread publishes frames (state.leap_viz_frame + seq) only while
    enabled; this tick lazily creates ONE raw texture on the first frame and
    set_value only when a NEW frame arrived — a still feed costs nothing.
    """
    if not dpg.does_item_exist("leap_window"):
        return
    if not dpg.is_item_shown("leap_window"):
        return
    if not (state.leap_enabled and state.leap_visualizer):
        return
    with state.leap_lock:
        seq = state.leap_viz_seq
        frame = state.leap_viz_frame
    if frame is None or seq == state.leap_viz_uploaded_seq:
        return
    _leap_viz_ensure_texture(frame)
    dpg.set_value("leap_viz_tex", frame.reshape(-1))
    state.leap_viz_uploaded_seq = seq
    if dpg.does_item_exist("leap_viz_wait_text"):
        dpg.hide_item("leap_viz_wait_text")


def _leap_viz_ensure_texture(frame: Any) -> None:
    """Create the raw texture + image ONCE, on the first published frame (e26s04).

    Texture format follows the thumbnail pipeline (RGBA float32 0..1); unlike
    thumbnails this texture is created once and updated via set_value (raw
    texture), never deleted/recreated per frame. The one-shot guard is a state
    flag (does_item_exist reads true in the headless stub), main-thread only.
    """
    if state.leap_viz_tex_created:
        return
    h, w = int(frame.shape[0]), int(frame.shape[1])
    dpg.add_raw_texture(
        width=w,
        height=h,
        default_value=frame.reshape(-1),
        tag="leap_viz_tex",
        parent="texture_registry",
    )
    dpg.add_image("leap_viz_tex", tag="leap_viz_img", parent="leap_viz_panel")
    state.leap_viz_tex_created = True


def tick_leap_monitor() -> None:
    """Refresh the Leap Motion window on the main loop (e26s02): status line +
    live two-hand values from the worker snapshot, writing only on change.

    No-op while the window does not exist or is hidden. Values are read under
    state.leap_lock (shallow copy) and rendered via leap.format_value; an
    absent hand or a disabled engine shows the placeholder (cache-gated, so a
    still hand or an idle window costs nothing).
    """
    if not dpg.does_item_exist("leap_window"):
        return
    if not dpg.is_item_shown("leap_window"):
        return
    enabled = state.leap_enabled
    stalled = enabled and leap.leap_engine_stalled(time.time(), state.leap_worker_tick)
    _leap_monitor_set_text(
        "leap_status_text", leap.leap_status_label(enabled, state.leap_status, stalled=stalled)
    )
    # e48: frame rate is a per-frame diagnostic, not a per-hand signal.
    _leap_monitor_set_text(
        "leap_fps_text", leap.format_framerate(state.leap_framerate if enabled else 0.0)
    )
    if enabled:
        with state.leap_lock:
            snapshot = dict(state.leap_values)
    else:
        snapshot = {}
    for hand in leap.LEAP_HANDS:
        for field in leap.LEAP_FIELDS:
            raw = snapshot.get(f"{hand}.{field}") if enabled else None
            text = leap.LEAP_MONITOR_PLACEHOLDER if raw is None else leap.format_value(field, raw)
            _leap_monitor_set_text(f"leap_mon_{hand}_{field}", text)


# ---------- e16/e22: Mapper (OSC property mappings -> per-source rows) ----------
# e22s01: the body is one horizontal row per SOURCE — the source thumbnail at
# the sequencer slot size, then that source's mapping mini-cards to the right.


def _mapper_font() -> Any:
    """The small ProggyTiny font the Mapper texts/controls use (e23 compact).

    Same 10 px font as the Vimix-sources tile titles; None when the bundled
    asset is missing (then the default font is used and the compact geometry
    still fits — labels are the widest at ~7 px/char)."""
    return _tile_title_font


def _bind_mapper_font(tag: str) -> None:
    """Bind the compact mapper font to an item tag when it exists."""
    font = _mapper_font()
    if font is not None and dpg.does_item_exist(tag):
        dpg.bind_item_font(tag, font)


def _mapper_caption_spacer(
    label: str, spec: dict[str, Any], has_reset: bool = True, extra_px: int = 0
) -> int:
    """Spacer width that right-aligns the enable checkbox + X on a caption (e24).

    The caption is ONE row: label + spacer + enable checkbox + X. Labels render
    in the 10 px ProggyTiny mapper font (MAPPER_SMALL_CHAR_PX = 6 px/char), so
    the budget uses that advance and subtracts the checkbox + X blocks + item
    gaps: every catalog property label fits on a single caption row. A
    cue-list card drops the R button (UAT e35) — the spacer must not reserve
    its width, or its enable + X would sit left of the right edge. e52s02:
    `extra_px` reserves the mode badge when the card carries a gate tag.
    """
    return max(
        2,
        MAPPER_MINI_W
        - 24
        - MAPPER_SMALL_CHAR_PX * len(label)
        - (MAPPER_RESET_W if has_reset else 0)
        - MAPPER_CB_W
        - MAPPER_X_W
        - extra_px,
    )


def _mapper_caption_budget(has_reset: bool, extra_px: int = 0) -> int:
    """How many 6 px chars fit in a caption row once the buttons are reserved.

    BUG-2026-10-14T181712b: the spacer used to floor at 2 px without shrinking a
    long label, so the R/enable/X buttons were pushed out of the card. This is the
    SAME arithmetic, exposed as a char budget for the label itself.
    """
    reserved = (
        MAPPER_MINI_W
        - 24
        - (MAPPER_RESET_W if has_reset else 0)
        - MAPPER_CB_W
        - MAPPER_X_W
        - extra_px
        - 2
    )
    return max(1, reserved // MAPPER_SMALL_CHAR_PX)


def _fit_mapper_caption(text: str, has_reset: bool, extra_px: int = 0) -> str:
    """Cut a card caption to the room the buttons leave (BUG-2026-10-14T181712b)."""
    budget = _mapper_caption_budget(has_reset, extra_px)
    if len(text) <= budget:
        return text
    keep = max(0, budget - len(MEDIA_TITLE_ELLIPSIS))
    return text[:keep] + MEDIA_TITLE_ELLIPSIS


def _mapper_row_height(mappings: list[dict[str, Any]]) -> int:
    """Compact uniform height for one source row (e23 bugfix, e34s02 model).

    Fits the tallest mini-card in the row over the models that are present:
    the legacy vertical anatomy (caption + 17 px slider + the 'output' line +
    the 'input' line when a source is bound — sliders, answer A) and the
    compact band anatomy (caption + the 44 px knob/button band, its readouts
    INSIDE the band). A row mixing both takes the taller model; the card rows
    are height-constant across learn transitions — the card markers render in
    dedicated strip lines UNDER each card line (e34s03), outside the cards.
    Measured on DPG 2.3.1 with the compact mapper theme (10 px ProggyTiny
    font, WindowPadding 4, FramePadding y 2, ItemSpacing y 2).
    """
    pad, x_h, gap, text = (
        MAPPER_ROW_PAD_V,
        MAPPER_X_H,
        MAPPER_ROW_GAP,
        MAPPER_TEXT_H,
    )
    any_source = any(
        m.get("band") is not None or m.get("midi") is not None or m.get("leap") is not None
        for m in mappings
    )
    height = MAPPER_ROW_THUMB_H + 2  # the row always fits the 70 px thumbnail
    if any(m["control"] in ("knob", "button", "cue list") for m in mappings):
        height = max(height, pad + x_h + gap + MAPPER_KNOB_H)  # compact band
    if any(m["control"] == "cue list" for m in mappings):
        # UAT e35: the cue readout column also hosts the 'N of Total' progress
        # text UNDER the 'Cue list...' button — the card needs one extra line.
        height = max(height, pad + x_h + gap + MAPPER_KNOB_H + text)
    if any(m["control"] == "slider" for m in mappings):
        slider_h = pad + x_h + gap + MAPPER_CTRL_H + gap + text
        if any_source:
            slider_h += gap + text
        height = max(height, slider_h)
    return height


def _mapper_line_number(row_no: int, target_id: str, parent: Any, height: int) -> None:
    """Small 1-based row number left of the row thumbnail (e32s02).

    A narrow borderless slot as tall as the row whose ProggyTiny digit is
    vertically centered — the same spacer technique the thumbnail slot uses —
    and horizontally centered in the narrow column, so every row reads
    ' 1  [thumb] cards' with the digit balanced between the row edge and the
    thumbnail (the number matches the tile menu's "Add to Mapper > line N";
    both number mapper.row_targets() order).
    """
    digits = len(str(row_no))
    # monospace ProggyTiny digits: center the digit(s) in the fixed column;
    # two digits fill it flush (e32s02 tuning)
    indent = max(0, (MAPPER_LINE_NO_W - digits * MAPPER_LINE_NO_DIGIT_PX) // 2)
    with dpg.child_window(
        parent=parent,
        width=MAPPER_LINE_NO_W,
        height=height,
        border=False,
        no_scrollbar=True,
        tag=f"mapper_line_no_{target_id}",
    ):
        dpg.add_spacer(height=max(0, (height - MAPPER_LINE_NO_TEXT_H) // 2))
        themed_text(
            str(row_no),
            slot="text_dim",
            indent=indent,
            tag=f"mapper_line_no_txt_{target_id}",
        )
    font = _mapper_line_no_font or _mapper_font()
    if font is not None and dpg.does_item_exist(f"mapper_line_no_txt_{target_id}"):
        dpg.bind_item_font(f"mapper_line_no_txt_{target_id}", font)


def _mapper_row_thumb(target_id: str, parent: Any, height: int) -> None:
    """The source thumbnail slot at the start of a mapper row (e22s01).

    A fixed-width slot as tall as the row with the sequencer-size thumbnail
    (110x70) vertically centered inside, so the image aligns with the mini-card
    content next to it; when no texture exists yet the slot shows a "no thumb"
    placeholder (same footprint, rows stay aligned). e29s01: the slot is a
    sequencer-style apply box — a left click on its inner items (child windows
    cannot host clicked handlers on DPG 2.3.1) re-targets the row onto the
    media selected in the grid; the "no thumb" placeholder is clickable too.
    """
    with dpg.child_window(
        parent=parent,
        width=MAPPER_ROW_THUMB_W,
        height=height,
        border=False,
        no_scrollbar=True,
        tag=f"mapper_row_thumb_{target_id}",
    ):
        dpg.add_spacer(height=max(0, (height - MAPPER_ROW_THUMB_H) // 2))
        click_reg_tag = f"mapper_row_click_reg_{target_id}"
        if dpg.does_item_exist(click_reg_tag):
            dpg.delete_item(click_reg_tag)  # a rebuild must not leak registries
        with dpg.item_handler_registry(tag=click_reg_tag):
            dpg.add_item_clicked_handler(
                0,  # left click applies the selected source (e29s01)
                callback=lambda *_, t=target_id: on_mapper_row_thumb_click(None, None, t),
            )
        tex_tags = thumbnails_data.get(target_id)
        if tex_tags:
            tex_tag = tex_tags[0]
            if dpg.does_item_exist(tex_tag):
                dpg.add_image(
                    texture_tag=tex_tag,
                    width=MAPPER_ROW_THUMB_W,
                    height=MAPPER_ROW_THUMB_H,
                    tag=f"mapper_row_img_{target_id}",  # e25: stable tag for the frame cycle
                )
                dpg.bind_item_handler_registry(f"mapper_row_img_{target_id}", click_reg_tag)
                return
        props = _source_props(target_id)
        kind = sourcekind.source_kind_of(props)
        if kind is not None and not sourcekind.thumbnail_possible(props):
            # e69s01: a type that can never have a frame is NAMED, not left waiting
            # — the source NAME (bright) and its wiki TYPE (dim, smaller font). The
            # slot stays the e29s01 apply surface, so every line is clickable.
            name_tag = f"mapper_row_label_{target_id}"
            kind_tag = f"mapper_row_kind_{target_id}"
            themed_text(target_id, slot="text_bright", tag=name_tag)
            themed_text(kind.label, slot="text_dim", tag=kind_tag)
            if _mapper_kind_font is not None:
                dpg.bind_item_font(kind_tag, _mapper_kind_font)
            for tag in (name_tag, kind_tag):
                dpg.bind_item_handler_registry(tag, click_reg_tag)
            return
        if not sourcekind.thumbnail_possible(props):
            # no type answer and nothing to decode (older viOSC/vimix): the NAME alone
            name_tag = f"mapper_row_label_{target_id}"
            themed_text(target_id, slot="text_dim", tag=name_tag)
            dpg.bind_item_handler_registry(name_tag, click_reg_tag)
            return
        no_tag = f"mapper_row_nothumb_{target_id}"  # e29s01: stable tag, clickable placeholder
        themed_text("no thumb", slot="text_dim", tag=no_tag)
        dpg.bind_item_handler_registry(no_tag, click_reg_tag)


def on_mapper_row_thumb_click(
    sender: Any = None, app_data: Any = None, user_data: Any = None
) -> None:
    """Row-thumb click: apply the selected media to the whole row (e29s01).

    Mirrors the sequencer clip-slot click: the media selected in the Vimix
    sources grid (state.vjmix_selected_source) becomes the row's source —
    every mapping of the row re-targets onto it and the Mapper body rebuilds
    (rows regroup by first appearance; an existing row of the new source
    merges). A click with NO grid selection, or on a row already targeting
    the selection, is a no-op: deliberately NOT the sequencer's
    get_current_target_id() vimix-current fallback (user-confirmed) — the
    source of a mapper row is a deliberate choice.
    """
    target_id = user_data
    selected = state.vjmix_selected_source
    if selected is None or selected == target_id:
        return
    if mapper.retarget_source(target_id, selected):
        refresh_mapper_ui()


def _mapper_add_slot_width() -> int:
    """Width of a line's trailing '+' slot (e51s02 follow-up).

    Wider while a Paste button rides the slot, so the label fits; the reflow
    maths reads the SAME width, so the wider slot wraps like any other element.
    """
    return MAPPER_PASTE_SLOT_W if state.mapper_clipboard is not None else MAPPER_ADD_SLOT_W


def _mapper_row_add(target_id: str, parent: Any, height: int, line_index: int) -> None:
    """The per-row '+' at the end of a Mapper line (e34s01, e40s10).

    A NARROW borderless slot (MAPPER_ADD_SLOT_W, not the card pitch — the 2026-09-05
    rework: the '+' no longer wraps like a 150 px card on resize) as tall as the
    row, holding a small centered '+' button; a click opens the ONE Mapping
    editor in create mode with this line's source preselected. While learn mode
    is on the slot carries the e33 learn marker of the create action. e51s02:
    while the clipboard is full the slot widens and carries a Paste button
    under the '+'.
    """
    with dpg.child_window(
        parent=parent,
        width=_mapper_add_slot_width(),
        height=height,
        border=False,
        no_scrollbar=True,
        tag=f"mapper_add_{target_id}",
    ):
        dpg.add_spacer(height=max(0, (height - MAPPER_ADD_H) // 2))
        dpg.add_button(
            label="+",
            width=MAPPER_ADD_W,
            height=MAPPER_ADD_H,
            callback=open_line_mapping_creator,
            user_data=target_id,
            tag=f"mapper_add_btn_{target_id}",
        )
        if state.mapper_clipboard is not None:
            # e51s02: paste the clipboard at the end of THIS line (mouse surface).
            dpg.add_button(
                label="Paste",
                width=MAPPER_PASTE_W,
                height=MAPPER_ADD_H,
                callback=paste_mapper_mapping,
                user_data=target_id,
                tag=f"mapper_paste_{target_id}",
            )
            _bind_mapper_font(f"mapper_paste_{target_id}")
        if state.midi_learn_mode:  # e33 rule: the line creator is mappable
            learn_marker(
                MIDI_ACTION_MAPPING_ADD,
                {"line": line_index},
                parent=f"mapper_add_{target_id}",
                tag=f"mapper_mk_add_{target_id}",
            )
            learn_marker(
                MIDI_ACTION_MAPPING_PASTE,
                {"line": line_index},
                parent=f"mapper_add_{target_id}",
                tag=f"mapper_mk_paste_{target_id}",
            )
    with dpg.tooltip(parent=f"mapper_add_btn_{target_id}", delay=HELP_HOVER_DELAY_S) as tip_tag:
        dpg.add_text("Add a Mapping to this line")
    dpg.bind_item_theme(tip_tag, HELP_THEME_TOOLTIP)


def _mapper_marker_slot(mapping: dict[str, Any], parent: Any) -> None:
    """One card's markers in the under-card strip line (e34s03, answer D).

    The enable/reset/value M markers of one mapper card, centred on the card
    slot (MAPPER_MINI_W wide) so the strip rows stay aligned under the cards;
    the markers render OUTSIDE the bordered card (the card never hosts them).
    e34s05: a cue-list card also gets its dedicated window-action marker
    (mapper_mk_cue_open_<id> — the e33 rule). Captures and tags are unchanged
    so the learn capture path and existing bindings are untouched.
    """
    mid = mapping["id"]
    has_cue_open = mapping["control"] == "cue list"
    marker_count = 4 if has_cue_open else 3
    cluster_w = marker_count * MAPPER_MARKER_W  # the M buttons + item gaps
    indent = max(0, (MAPPER_MINI_W - cluster_w) // 2)
    slot_tag = f"mapper_mk_slot_{mid}"
    dpg.add_group(horizontal=True, parent=parent, tag=slot_tag)
    dpg.add_spacer(width=indent, parent=slot_tag)
    learn_marker(
        MIDI_ACTION_MAPPER_ENABLE,
        {"mapping_id": mid},
        parent=slot_tag,
        tag=f"mapper_mk_enable_{mid}",
    )
    learn_marker(
        MIDI_ACTION_MAPPER_RESET,
        {"mapping_id": mid},
        parent=slot_tag,
        tag=f"mapper_mk_reset_{mid}",
    )
    learn_marker(
        MIDI_ACTION_MAPPER_MAPPING,  # e33s03: the control value (e18 semantics)
        {"mapping_id": mid},
        parent=slot_tag,
        tag=f"mapper_mk_value_{mid}",
    )
    if has_cue_open:  # e34s05: open this mapping's cue-list window
        learn_marker(
            MIDI_ACTION_MAPPER_CUE_OPEN,
            {"mapping_id": mid},
            parent=slot_tag,
            tag=f"mapper_mk_cue_open_{mid}",
        )
    dpg.add_spacer(width=max(0, MAPPER_MINI_W - indent - cluster_w), parent=slot_tag)


def _mapper_edit_marker_slot(mapping: dict[str, Any], parent: Any) -> None:
    """One card's clipboard/move markers in a SECOND strip line (e51s02).

    The existing strip has no horizontal room for four more markers (the card is
    MAPPER_MINI_W wide), so Copy/Cut/Move left/Move right render on their own
    line under the card, aligned on the same slot. Uniform red-M markers, the
    e33 rule, only while learn mode is on.
    """
    mid = mapping["id"]
    marker_count = 4
    cluster_w = marker_count * MAPPER_MARKER_W
    indent = max(0, (MAPPER_MINI_W - cluster_w) // 2)
    slot_tag = f"mapper_mk_edit_slot_{mid}"
    dpg.add_group(horizontal=True, parent=parent, tag=slot_tag)
    dpg.add_spacer(width=indent, parent=slot_tag)
    learn_marker(
        MIDI_ACTION_MAPPING_COPY,
        {"mapping_id": mid},
        parent=slot_tag,
        tag=f"mapper_mk_copy_{mid}",
    )
    learn_marker(
        MIDI_ACTION_MAPPING_CUT,
        {"mapping_id": mid},
        parent=slot_tag,
        tag=f"mapper_mk_cut_{mid}",
    )
    learn_marker(
        MIDI_ACTION_MAPPING_MOVE,
        {"mapping_id": mid, "delta": -1},
        parent=slot_tag,
        tag=f"mapper_mk_moveleft_{mid}",
    )
    learn_marker(
        MIDI_ACTION_MAPPING_MOVE,
        {"mapping_id": mid, "delta": 1},
        parent=slot_tag,
        tag=f"mapper_mk_moveright_{mid}",
    )
    dpg.add_spacer(width=max(0, MAPPER_MINI_W - indent - cluster_w), parent=slot_tag)


def _mapper_card_has_source(mapping: dict[str, Any]) -> bool:
    """True when a mapping is bound to a band/MIDI/leap source (its Inp row shows).

    The one source-of-truth the readout/row-height decisions share (e34s02).
    """
    return (
        mapping.get("band") is not None
        or mapping.get("midi") is not None
        or mapping.get("leap") is not None
    )


def _mapper_readout_line(
    label: str,
    mid: int,
    kind: str,
    from_value: float,
    to_value: float,
    width: int,
) -> None:
    """One from/to readout row: a short label + two drag boxes (e34s02).

    Shared by the legacy slider lines (label 'output'/'input', wide boxes)
    and the compact out/inp column beside the band control (label 'out'/'inp',
    MAPPER_BAND_DRAG_W boxes). Tags and handler wire-up stay the same for both
    so on_mapper_output/input and the card right-click registry keep working.
    """
    callback = on_mapper_output if kind == "out" else on_mapper_input
    with dpg.group(horizontal=True):
        themed_text(label, slot="text_dim", tag=f"mapper_{kind}_lbl_{mid}")
        dpg.add_drag_float(
            default_value=from_value,
            width=width,
            format="%.2f",
            speed=0.01,
            callback=callback,
            user_data=(mid, "from"),
            tag=f"mapper_{kind}_from_{mid}",
        )
        dpg.add_drag_float(
            default_value=to_value,
            width=width,
            format="%.2f",
            speed=0.01,
            callback=callback,
            user_data=(mid, "to"),
            tag=f"mapper_{kind}_to_{mid}",
        )
    _bind_mapper_font(f"mapper_{kind}_lbl_{mid}")
    _bind_mapper_font(f"mapper_{kind}_from_{mid}")
    _bind_mapper_font(f"mapper_{kind}_to_{mid}")


def _mapper_band_control(mapping: dict[str, Any], mid: int) -> None:
    """Compact control band of a knob/button/cue-list card (e34s02, e34s04).

    ONE row as tall as the 44 px control: the control on the LEFT, and on the
    right the readout — knob/button: the 'out' line (always) with the 'inp'
    line under it when a band/MIDI/leap source is bound; cue list: a
    'Cue list...' button that opens the mapping's cue-list window instead of
    the out/inp fields (e34s04, answer E). The readout no longer stacks BELOW
    the control, so the rows shrink; the trigger becomes a 44 px square
    showing the value; the caption row above keeps the property label.
    """
    control = mapping["control"]
    kind = mapper.control_tag_kind(control)
    out_from = mapping["output_from"]
    out_to = mapping["output_to"]
    with dpg.group(horizontal=True):
        if control == "knob":
            dpg.add_knob_float(
                min_value=out_from,
                max_value=out_to,
                default_value=mapping["value"],
                width=MAPPER_KNOB_H,
                callback=on_mapper_control,
                user_data=mid,
                tag=f"mapper_{kind}_{mid}",
            )
        else:  # button / cue list: a 44 px square trigger labelled with the value
            dpg.add_button(
                label=_trigger_label(mapping),
                width=MAPPER_KNOB_H,
                height=MAPPER_KNOB_H,
                callback=on_mapper_button,
                user_data=mid,
                tag=f"mapper_{kind}_{mid}",
            )
        _bind_mapper_font(f"mapper_{kind}_{mid}")
        if control in ("button", "cue list"):
            # UAT e35: the trigger shows its state — accent fill when ON/RUN
            _style_trigger_theme(f"mapper_{kind}_{mid}", _trigger_is_on(mapping))
        if str(mapping["property"]) == catalog.SET_CURRENT_PROPERTY:
            # e83: no value exists, so no readout: the row says what SET does.
            themed_text("-> current", slot="text_dim", tag=f"mapper_setc_hint_{mid}")
        elif control == "cue list":
            # e34s04/e35 UAT: the right readout column hosts the window opener
            # and, UNDER it, the 'N of Total' progress readout of the cue.
            with dpg.group():
                dpg.add_button(
                    label="Cue list...",
                    width=MAPPER_MINI_W - 8 - MAPPER_KNOB_H - 2,
                    callback=open_cue_list_window,
                    user_data=mid,
                    tag=f"mapper_cue_open_{mid}",
                )
                themed_text(
                    _cue_progress_label(mapping),
                    slot="text_dim",
                    tag=f"mapper_cue_prog_{mid}",
                )
            _bind_mapper_font(f"mapper_cue_open_{mid}")
            _bind_mapper_font(f"mapper_cue_prog_{mid}")
        else:
            with dpg.group():
                _mapper_readout_line("out", mid, "out", out_from, out_to, MAPPER_BAND_DRAG_W)
                if _mapper_card_has_source(mapping):
                    in_from = mapping.get("input_from")
                    in_to = mapping.get("input_to")
                    _mapper_readout_line(
                        "inp",
                        mid,
                        "in",
                        in_from if in_from is not None else 0.0,
                        in_to if in_to is not None else 1.0,
                        MAPPER_BAND_DRAG_W,
                    )
                    if mapper.toggle_on_press(mapping):
                        # e51 follow-up: the row label is always 'inp' (uniform);
                        # the alternate behaviour is explained on hover instead.
                        with dpg.tooltip(
                            parent=f"mapper_in_lbl_{mid}", delay=HELP_HOVER_DELAY_S
                        ) as tip_tag:
                            dpg.add_text(MAPPER_INPUT_ALT_TOOLTIP)
                        dpg.bind_item_theme(tip_tag, HELP_THEME_TOOLTIP)


def _render_mapper_card(mapping: dict[str, Any], parent: Any, height: int) -> None:
    """One bordered mapping mini-card inside a source row (e22s01, e23s01).

    Anatomy (e34s02): the caption row — dim property label left, X delete
    button right (NO value text: the control shows the value) — then the
    control. e34s02 (answers A/B): slider cards keep the vertical anatomy —
    slider spanning the content width, then the 'output' from/to line and
    (when a band/MIDI/leap source is bound) the 'input' line BELOW. Knob and
    button cards collapse into ONE band as tall as the 44 px control: the
    control LEFT, the 'out' (always) and 'inp' (bound source only) readouts
    RIGHT (see _mapper_band_control). The card height is the row height
    (per-content, see _mapper_row_height). Tags are unchanged so the band/MIDI
    drive and delete keep working; the right-click source menu lives on the
    CARD (buttons cannot host DPG handler registries).
    """
    mid = mapping["id"]
    full_caption = _mapper_card_caption(mapping)
    has_reset = mapping["control"] != "cue list" and (
        str(mapping["property"]) != catalog.SET_CURRENT_PROPERTY
    )
    mode_tag = modes_for_mapping(mid)
    badge = f"[{mode_tag}]" if mode_tag else ""
    badge_px = MAPPER_SMALL_CHAR_PX * len(badge)
    # BUG-2026-10-14T181712b: the caption is truncated to the room the buttons leave,
    # so R/enable/X can never be pushed out of the card; the full text is on hover.
    caption = _fit_mapper_caption(full_caption, has_reset, extra_px=badge_px)
    out_from = mapping["output_from"]
    out_to = mapping["output_to"]
    content_w = MAPPER_MINI_W - 8  # 4 px card padding each side
    with dpg.child_window(
        parent=parent,
        width=MAPPER_MINI_W,
        height=height,
        border=True,
        no_scrollbar=True,
        tag=f"mapper_card_{mid}",
    ):
        with dpg.group(horizontal=True):
            themed_text(caption, slot="text_dim", tag=f"mapper_prop_{mid}")
            if caption != full_caption:
                with dpg.tooltip(parent=f"mapper_prop_{mid}", delay=HELP_HOVER_DELAY_S) as tip_tag:
                    dpg.add_text(full_caption)
                dpg.bind_item_theme(tip_tag, HELP_THEME_TOOLTIP)
            # e52s02: the gate tag rides next to the caption, so a layered
            # Mapping is recognisable without opening the menu.
            if badge:
                themed_text(badge, slot="text", tag=f"mapper_mode_badge_{mid}")
            dpg.add_spacer(
                width=_mapper_caption_spacer(caption, {}, has_reset=has_reset, extra_px=badge_px)
            )
            # e27s01: the reset button sits LEFT of the enable checkbox — it
            # returns the control to its neutral default (mapper.reset_mapping_value).
            # UAT e35: a cue-list trigger has no value to reset (it RUNS the cue,
            # stopped by the window 'Stop') — no R on cue-list cards.
            if mapping["control"] != "cue list":
                dpg.add_button(
                    label="R",
                    width=MAPPER_RESET_W,
                    height=MAPPER_RESET_H,
                    callback=reset_mapping,
                    user_data=mid,
                    tag=f"mapper_reset_{mid}",
                )
                dpg.bind_item_theme(f"mapper_reset_{mid}", theme_mapper_micro)
            dpg.add_checkbox(
                default_value=mapping.get("enabled", False),
                callback=on_mapping_enable,
                user_data=mid,
                tag=f"mapper_enable_{mid}",
            )
            dpg.add_button(
                label="X",
                width=MAPPER_X_W,
                height=MAPPER_X_H,
                callback=delete_mapping,
                user_data=mid,
                tag=f"mapper_del_{mid}",
            )
            dpg.bind_item_theme(f"mapper_del_{mid}", theme_mapper_micro)
        # e34s03: the card markers moved OUT of the card — while MIDI Learn is
        # on they render in a dedicated strip line UNDER each card line (see
        # refresh_mapper_ui + _mapper_marker_slot); the card itself stays clean.
        _bind_mapper_font(f"mapper_prop_{mid}")
        if mapping["control"] == "slider":
            # e34s02 (answer A): the slider keeps the vertical anatomy — control
            # spanning the content width, then the legacy readout lines BELOW.
            dpg.add_slider_float(
                min_value=out_from,
                max_value=out_to,
                default_value=mapping["value"],
                width=content_w,
                callback=on_mapper_control,
                user_data=mid,
                tag=f"mapper_slider_{mid}",
            )
            _bind_mapper_font(f"mapper_slider_{mid}")
            _mapper_readout_line("output", mid, "out", out_from, out_to, MAPPER_DRAG_W)
            if _mapper_card_has_source(mapping):
                in_from = mapping.get("input_from")
                in_to = mapping.get("input_to")
                _mapper_readout_line(
                    "input",
                    mid,
                    "in",
                    in_from if in_from is not None else 0.0,
                    in_to if in_to is not None else 1.0,
                    MAPPER_DRAG_W,
                )
        else:
            # knob / button: the compact band (e34s02)
            _mapper_band_control(mapping, mid)
        _render_mapper_source_menu(mapping)


def _mapper_card_caption(mapping: dict[str, Any]) -> str:
    """Caption of one mapping card (e36s03).

    A multi-value property card shows the property + its component (Position X,
    Color R, Corner B.y…); a trigger-family card shows the action name (its
    value is meaningless); a cue-list card is titled by its TYPE — its stored
    property is inert (UAT e35). Everything else shows the catalog label
    (unchanged for the legacy scalar properties).
    """
    control = str(mapping.get("control") or "")
    if control == "cue list":
        return "cue list"
    prop = str(mapping["property"])
    slot = catalog.parse_uniform_slot(prop)
    if slot is not None:
        # e70s02 / BUG-2026-10-14T181712b: the card names the slot AND the parameter
        # it drives, in a COMPACT form — the full `uniformN = name` does not fit a
        # 150 px caption row next to R/enable/X. `_fit_mapper_caption` truncates anyway.
        resolved = shadercode.resolve_uniform(
            state.shader_uniforms, str(mapping.get("target_id") or ""), prop
        )
        return f"u{slot} {resolved[0]}" if resolved is not None else f"u{slot}"
    entry = _maybe_catalog_entry(prop)
    if entry is None:
        # e61s05: a mapping can point at a property the current source no longer
        # declares. A stale mapping is a project fact, so the row shows the raw key
        # instead of crashing the window.
        return prop
    if entry["family"] == catalog.FAMILY_TRIGGER:
        return prop.upper()
    label = str(entry["label"])
    component = mapping.get("component")
    if component is not None:
        for comp in entry["components"]:
            if comp["key"] == component:
                return f"{label} {comp['label']}"
    return label


def _render_mapper_source_menu(mapping: dict[str, Any]) -> None:
    """Right-click source menu on a mini-card (e18, e23 bugfix).

    DearPyGui's dpg.popup() cannot attach to a BUTTON control (buttons cannot
    host the handler registry popup builds -> 1005 at refresh, which aborts the
    whole body and hides every card after it) and child windows reject its
    clicked handler (1000). So, like the Mediagrid tiles, the menu is a popup
    WINDOW shown by a per-card item-handler registry bound to every card
    child (all item types host an item-clicked registry on DPG 2.3.1):
    right-clicking anywhere on the bordered card opens the source menu. The
    ACTIVE source is marked with a checkmark; band and MIDI sources are
    mutually exclusive (see mapper.set_mapping_band). e33s03: while MIDI
    Learn is on the menu rows become uniform label + learn-marker rows (the
    marker captures mapper_band); the Leap picker row and Clear source are
    never marker targets (picker/destructive exclusion). The e18 'MIDI
    Learn...' modal item is gone — the card control marker captures the
    value binding instead. e47: the menu no longer arms or cancels the learn
    mode — the toolbar icon does (ADR-midi-learn-entry-point) — while the
    marker rows below stay the capture affordance.
    """
    mid = mapping["id"]
    # the control tag comes from the shared control->kind map (e34s04):
    # mapper_slider_N / mapper_knob_N / mapper_btn_N / mapper_cue_N — the map
    # keeps the e23 'btn' quirk in ONE place (building it from the control
    # name would look for the nonexistent mapper_button_N and abort).
    control_kind = mapper.control_tag_kind(mapping["control"])
    menu_tag = f"mapper_menu_{mid}"
    reg_tag = f"mapper_menu_reg_{mid}"
    for stale in (menu_tag, reg_tag):
        if dpg.does_item_exist(stale):
            dpg.delete_item(stale)
    with dpg.window(popup=True, show=False, no_title_bar=True, autosize=True, tag=menu_tag):
        if state.midi_learn_mode:
            # e33s03: uniform label + learn-marker rows while learning — the
            # marker captures the band action, the label keeps its click behavior
            for band_id in BAND_SOURCES:
                with dpg.group(horizontal=True) as band_row:
                    dpg.add_button(
                        label=f"Map Band {band_id}",
                        callback=set_mapping_band,
                        user_data=(mid, band_id),
                    )
                    learn_marker(
                        MIDI_ACTION_MAPPER_BAND,
                        {"mapping_id": mid, "band": band_id},
                        parent=band_row,
                        tag=f"mapper_mk_band{band_id}_{mid}",
                    )
            with dpg.group(horizontal=True):
                dpg.add_button(
                    label="Leap Motion...",
                    callback=open_mapper_leap_picker,
                    user_data=mid,
                )
            with dpg.group(horizontal=True):
                dpg.add_button(
                    label="Clear source",
                    callback=clear_mapping_source,
                    user_data=mid,
                )
        else:
            # e71s01: one entry per mappable band (2..5 via BAND_SOURCES); band 1 stays
            # the sequencer's beat source and is never a Mapper source (e10s07).
            for band_id in BAND_SOURCES:
                dpg.add_menu_item(
                    label=f"Map Band {band_id}",
                    check=True,
                    default_value=(mapping.get("band") == band_id),
                    callback=set_mapping_band,
                    user_data=(mid, band_id),
                )
            # e47: no MODE-arm item here any more — the toolbar icon arms the
            # mode; capture still happens on the markers once the mode is on.
            dpg.add_menu_item(
                label="Leap Motion...",
                check=True,
                default_value=(mapping.get("leap") is not None),
                callback=open_mapper_leap_picker,
                user_data=mid,
            )
            dpg.add_separator()
            dpg.add_menu_item(label="Clear source", callback=clear_mapping_source, user_data=mid)
        # e52s02: the gate tag of the Binding(s) that drive this Mapping — the
        # user's flow: right-click the card and pick the mode it needs.
        current_mode = modes_for_mapping(mid)
        bound = isinstance(mapping.get("midi"), dict)
        with dpg.menu(label="Mode", enabled=bound, tag=f"mapper_mode_menu_{mid}"):
            dpg.add_menu_item(
                label=MIDI_MODE_BASE_CHOICE,
                check=True,
                default_value=current_mode is None,
                callback=on_mapper_mode_menu,
                user_data=(mid, ""),
            )
            for mode_name in mode_names():
                dpg.add_menu_item(
                    label=mode_name,
                    check=True,
                    default_value=(current_mode == mode_name),
                    callback=on_mapper_mode_menu,
                    user_data=(mid, mode_name),
                )
        # e51s02: copy/cut/move the Mapping itself (mouse surface of the clipboard
        # actions; the MIDI-mappable markers live on the card strip).
        dpg.add_separator()
        dpg.add_menu_item(label="Copy mapping", callback=copy_mapper_mapping, user_data=mid)
        dpg.add_menu_item(label="Cut mapping", callback=cut_mapper_mapping, user_data=mid)
        dpg.add_menu_item(label="Move left", callback=move_mapper_mapping, user_data=(mid, -1))
        dpg.add_menu_item(label="Move right", callback=move_mapper_mapping, user_data=(mid, 1))
    with dpg.item_handler_registry(tag=reg_tag):
        dpg.add_item_clicked_handler(1, callback=lambda *_, m=mid: _show_mapper_menu(m))
    for tag in (
        f"mapper_prop_{mid}",
        f"mapper_reset_{mid}",
        f"mapper_enable_{mid}",
        f"mapper_del_{mid}",
        f"mapper_{control_kind}_{mid}",
        f"mapper_out_lbl_{mid}",
        f"mapper_out_from_{mid}",
        f"mapper_out_to_{mid}",
        f"mapper_in_lbl_{mid}",
        f"mapper_in_from_{mid}",
        f"mapper_in_to_{mid}",
    ):
        if dpg.does_item_exist(tag):
            dpg.bind_item_handler_registry(tag, reg_tag)


def _show_mapper_menu(mid: int) -> None:
    """Open the right-click source menu of a mini-card at the cursor (e18).

    e27s02 (BUG-2026-09-03T175000): the popup must be placed at
    get_mouse_pos(local=False) — DPG's stable per-frame ImGui CLIENT mouse
    position, the same coordinate space window positions (set_item_pos) live
    in. The default get_mouse_pos() is not usable here: DPG overwrites it
    while drawing with coordinates LOCAL TO the focused window/child under the
    cursor (over a card that is card-local, e.g. (37, 14)), so subtracting the
    viewport position from it opened the menu at the top of the viewport
    instead of at the cursor.
    """
    menu_tag = f"mapper_menu_{mid}"
    if not dpg.does_item_exist(menu_tag):
        return
    dpg.set_item_pos(menu_tag, dpg.get_mouse_pos(local=False))
    dpg.show_item(menu_tag)


def set_mapping_band(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """Mapper control menu: bind the control to an audio band (e18)."""
    mapping_id, band_id = user_data
    mapper.set_mapping_band(mapping_id, band_id)
    refresh_mapper_ui()


def clear_mapping_source(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """Mapper control menu: drop the band/MIDI source, manual control resumes (e18)."""
    mapper.clear_mapping_source(int(user_data))
    refresh_mapper_ui()


def on_mapper_mode_menu(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """Mapper card > Mode: tag the Binding(s) that drive the card (e52s02)."""
    mapping_id, name = user_data
    set_mapper_mapping_mode(int(mapping_id), str(name))


def set_mapper_mapping_mode(mapping_id: int, name: str) -> None:
    """Write (or clear) the gate tag on every Binding that drives one Mapping (e52s02)."""
    for controller in midi_controllers:
        for binding in controller.get("bindings") or []:
            params = binding.get("params")
            if isinstance(params, dict) and int(params.get("mapping_id") or 0) == mapping_id:
                set_binding_mode(binding, name)
    save_midi_controllers()
    refresh_mapper_ui()
    refresh_midi_mappings_ui()


def _set_mapper_control_value(mapping_id: int, value: float) -> None:
    """Move a mapping's control widget from an external source (band/MIDI, e18).

    e23s01: the value caption is gone — the control's own readout shows the
    output value, so only the widget values are set here.
    """
    for kind in ("slider", "knob"):
        tag = f"mapper_{kind}_{mapping_id}"
        if dpg.does_item_exist(tag):
            dpg.set_value(tag, value)


def drive_mapper_band(band_id: int, level: float) -> None:
    """Push an audio-band level into every control mapped to that band (e18).

    Called by refresh_band_value (main thread, ~30 fps while the band is
    enabled). e23s02: the raw level (0..1) is rescaleped through each mapping's
    input range (default 0..1), then through its output range.
    """
    for m in state.mapper_mappings:
        if m.get("band") == band_id:
            try:
                value = mapper.apply_input_value(m["id"], level)
            except Exception as exc:  # BUG-2026-10-14T180544: one bad Mapping must not
                log_error("Mapper band", f"mapping {m.get('id')}: {exc!r}")  # starve the rest
                continue
            _set_mapper_control_value(m["id"], value)


def drive_leap_mappings(snapshot: dict[str, float], now: float | None = None) -> None:
    """Push a fresh leap snapshot into every leap-bound mapping (e26s03).

    Called by the leap worker listener on tracking frames. Per-mapping rate
    cap (~30 Hz) and the change epsilon (input span / 1000) come from the
    pure drive_ready gate; an absent hand/key HOLDS the mapping's last value.
    OSC sends happen inside mapper.apply_input_value (worker-safe, HIGH-1) and
    the card widget moves on the main thread via ui_task.
    """
    if now is None:
        now = time.monotonic()
    snapshot = snapshot or {}
    for m in list(state.mapper_mappings):
        key = m.get("leap")
        if not key:
            continue
        raw = snapshot.get(key)
        if raw is None:
            continue  # absent hand: hold the mapping's last value
        in_from, in_to = m.get("input_from"), m.get("input_to")
        if in_from is None or in_to is None:
            parts = leap.binding_parts(key)
            if parts is not None:
                in_from, in_to = leap.signal_default_range(parts[1]) or (0.0, 1.0)
            else:
                in_from, in_to = 0.0, 1.0
        book = state.leap_drive_state.setdefault(m["id"], {"last_raw": None, "last_push": 0.0})
        if not leap.drive_ready(
            now,
            float(book["last_push"]),
            leap.LEAP_DRIVE_INTERVAL,
            book["last_raw"],
            float(raw),
            float(in_from),
            float(in_to),
        ):
            continue
        book["last_raw"] = float(raw)
        book["last_push"] = now
        try:
            value = mapper.apply_input_value(m["id"], float(raw))
        except Exception as exc:  # BUG-2026-10-14T180544: isolate each Mapping
            log_error("Mapper leap", f"mapping {m.get('id')}: {exc!r}")
            continue

        def _move_widget(mid: int = m["id"], v: float = value) -> None:
            _set_mapper_control_value(mid, v)

        ui_task(_move_widget)


def open_mapper_leap_picker(
    sender: Any = None, app_data: Any = None, user_data: Any = None
) -> None:
    """Mapper card menu > Leap Motion...: hand/signal picker modal (e26s03).

    Unlike MIDI there is nothing to LEARN — the signal IS the address, so the
    user picks a hand (Left/Right) and a curated signal from the catalog. The
    picker is a small modal (same shape the e18 MIDI learn modal had before
    e33s03 replaced it with the uniform control marker).
    """
    mapping_id = int(user_data)
    if dpg.does_item_exist("mapper_leap_window"):
        dpg.delete_item("mapper_leap_window")
    mapping = mapper.find_mapping(mapping_id)
    signal_items = [leap.leap_field(f)["label"] for f in leap.bindable_signals()]
    hand_default = "Left"
    signal_default = signal_items[0]
    if mapping is not None:
        parts = leap.binding_parts(mapping.get("leap") or "")
        if parts is not None:
            hand_default = "Left" if parts[0] == "left" else "Right"
            label = leap.leap_field(parts[1])["label"]
            if label in signal_items:
                signal_default = label
    with dpg.window(
        label="Leap Motion",
        tag="mapper_leap_window",
        modal=True,
        width=340,
        height=200,
        no_resize=True,
    ):
        themed_text("Bind this control to a hand signal:", slot="text")
        dpg.add_spacer(height=6)
        with dpg.group(horizontal=True):
            themed_text("Hand", slot="text_dim")
            dpg.add_combo(
                items=["Left", "Right"],
                default_value=hand_default,
                width=110,
                tag="mapper_leap_hand_cb",
            )
        dpg.add_spacer(height=4)
        with dpg.group(horizontal=True):
            themed_text("Signal", slot="text_dim")
            dpg.add_combo(
                items=signal_items,
                default_value=signal_default,
                width=210,
                tag="mapper_leap_signal_cb",
            )
        dpg.add_spacer(height=10)
        with dpg.group(horizontal=True):
            dpg.add_button(
                label="Bind", callback=mapper_leap_confirm, user_data=mapping_id, width=90
            )
            dpg.add_button(label="Cancel", callback=mapper_leap_cancel, width=90)
    show_centered_window("mapper_leap_window")  # e55: dialogs open centered


def mapper_leap_confirm(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """Bind the picked hand/signal to the mapping, close the modal, refresh (e26s03)."""
    mapping_id = int(user_data)
    hand = str(dpg.get_value("mapper_leap_hand_cb")).lower()
    label = str(dpg.get_value("mapper_leap_signal_cb"))
    field = next((f for f in leap.bindable_signals() if leap.leap_field(f)["label"] == label), None)
    if field is None or hand not in leap.LEAP_HANDS:
        return
    mapper.set_mapping_leap(mapping_id, leap.binding_key(hand, field))
    if dpg.does_item_exist("mapper_leap_window"):
        dpg.delete_item("mapper_leap_window")
    refresh_mapper_ui()


def mapper_leap_cancel(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """Close the leap picker modal without binding (e26s03)."""
    if dpg.does_item_exist("mapper_leap_window"):
        dpg.delete_item("mapper_leap_window")


def midi_mapping_value(mapping_id: int, midi_value: int) -> None:
    """Drive a mapper control from a learned MIDI value (e23s02).

    The raw 0..127 value is rescaleped through the mapping's input range
    (default 0..127), then through its output range, and the control widget
    follows. Cue list (e35s03): the value marker IS the trigger — a value >= 64
    runs/restarts the cue, anything below is ignored.
    """
    mapping = mapper.find_mapping(mapping_id)
    if mapping is not None and mapping.get("control") == "cue list":
        if midi_value >= 64:
            cue.cue_start(mapping_id, allow_restart=True)
            tick_cue_triggers()
        return
    if mapping is not None and str(mapping.get("property")) == catalog.SET_CURRENT_PROPERTY:
        # e83: an ACTION row, not a value: only the press edge fires it (a CC sweep
        # would otherwise send one command per step).
        if midi_value >= 64:
            mapper.send_button_mapping(mapping_id)
            _after_button_press(mapper.find_mapping(mapping_id) or mapping)
        return
    value = mapper.apply_input_value(mapping_id, midi_value)
    _set_mapper_control_value(mapping_id, value)
    if mapping is not None and mapping.get("control") == "button":
        # BUG-2026-09-07: the square trigger must follow the driven value too
        _after_button_press(mapping)


def tick_midi_learn_timeout() -> None:
    """Expire a stale MIDI Learn session (marker captures included) past the timeout."""
    if state.midi_learn_mode and (
        time.time() - state.midi_learn_started_at > MIDI_LEARN_TIMEOUT_SECONDS
    ):
        _exit_midi_learn()


def _mapper_row_lead_px() -> int:
    """Width of the row lead consumed before the first card of a mapper line.

    The lead is the line-number column + its spacing + the thumbnail slot; while
    MIDI Learn is on it also includes the e33s03 row line-marker column. The
    trailing group spacing is excluded (the horizontal line adds it), matching
    the e32s02 continuation spacer that aligns cards across wrapped lines.
    """
    lead = MAPPER_LINE_NO_W + 4 + MAPPER_ROW_THUMB_W
    if state.midi_learn_mode:  # e33s03: the row line-marker column
        lead += 4 + MAPPER_MARKER_W
    return lead


def _mapper_cards_per_line() -> int:
    """How many mapping mini-cards fit one source line at the live window width.

    e24s02: the Mapper wraps instead of overflowing — the capacity derives from
    the current mapper window width minus the row lead (the e32s02 line-number
    column + the 110 px thumbnail block + their item spacings, and the e33s03
    line-marker column while learn mode is on), over the card pitch
    (MAPPER_MINI_W + the 4 px horizontal item spacing).
    """
    width = dpg.get_item_width("mapper_window")
    if not width:
        width = MAPPER_WINDOW_WIDTH
    available = width - 8  # window content padding
    pitch = MAPPER_MINI_W + 4
    lead = _mapper_row_lead_px() + 4  # row lead + trailing group spacing
    return max(1, int((available - lead) // pitch))


# --- MAPPINGS IN THE MAPPER (e40s01) -------------------------------------------
# Each source is one line with a Control band (the input-mapping cards) and a State
# band (the Mappings reading that source); source-less Mappings (Clock/Constant) live
# in a Global line on top. Three chips hide a band/line.

_mapper_show_control = True
_mapper_show_get = True
_mapper_show_global = True


def on_mapper_filter(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """Section chips: apply the visibility flags and rebuild the body (e40s01)."""
    global _mapper_show_control, _mapper_show_get, _mapper_show_global
    _mapper_show_control = bool(dpg.get_value("mapper_filter_control"))
    _mapper_show_get = bool(dpg.get_value("mapper_filter_get"))
    _mapper_show_global = bool(dpg.get_value("mapper_filter_global"))
    refresh_mapper_ui()


def _mapping_destination_label(mapping: dict[str, Any]) -> str:
    """Short Destination summary of a Mapping row readout (e40s01)."""
    destination = mapper.destination_of(mapping)
    spec = mapping.get("destination_spec") or {}
    if destination == DEST_MIDI:
        kind = "note" if str(spec.get("type")) == MIDI_KIND_NOTE else "cc"
        return f"MIDI {spec.get('controller_port', '?')} {kind} {spec.get('number', 0)}"
    if destination == DEST_OSC:
        return f"OSC {spec.get('host', '?')}:{spec.get('port', '?')} {spec.get('address', '?')}"
    return "Vimix"


def _mapping_origin_label(mapping: dict[str, Any]) -> str:
    """Short Origin summary of a Mapping row readout (e40s01).

    e40s08: a State Mapping renders inside its Source's band, so the Source name
    is redundant there — the row names only the Property.
    """
    origin = mapper.origin_of(mapping)
    if origin == ORIGIN_STATE:
        return str(mapping["property"])
    if origin == ORIGIN_CLOCK:
        return f"clock {mapping.get('origin_spec', {}).get('clock', 'beat')}"
    if origin == ORIGIN_CONST:
        return f"const {mapping.get('origin_spec', {}).get('value', 0.0)}"
    return str(mapping["property"])


def _render_mapping_row(mapping: dict[str, Any], parent: Any) -> None:
    """One State/Global row: Origin -> Destination + arm/edit/delete + learn marker.

    e40s08: the buttons carry an explicit height (MAPPER_STATE_BOX_ROW_H) so the
    row matches the checkbox-driven 17 px and the State box can compute its own
    height. The checkbox does NOT: DearPyGui 2.3.1 add_checkbox rejects a height
    kwarg (SystemError, verified against the real binding) and its own 17 px is
    what the row settles at anyway.

    e40s14: the arm checkbox carries NO caption — inside a row it can only mean
    'enable this Mapping', exactly as the Control mini-cards leave theirs
    unlabelled (the caption was 'Enable state'/'Enable clock'/'Enable constant').
    """
    rid = int(mapping["id"])
    tag = f"mapping_row_{rid}"
    in_from = float(mapping.get("input_from") or 0.0)
    in_to = float(mapping.get("input_to") or 0.0)
    out_from = float(mapping["output_from"])
    out_to = float(mapping["output_to"])
    cadence = f" {int(mapping['cadence'])}ms" if mapping.get("cadence") else ""
    with dpg.group(horizontal=True, parent=parent, tag=tag):
        themed_text(
            f"{_mapping_origin_label(mapping)} -> {_mapping_destination_label(mapping)}",
            slot="text_dim",
        )
        themed_text(
            f"In {in_from:.2f}..{in_to:.2f} Out {out_from:.0f}..{out_to:.0f}{cadence}",
            slot="text_dim",
        )
        dpg.add_checkbox(
            tag=f"mapping_enable_{rid}",
            default_value=bool(mapping.get("enabled", False)),
            callback=on_mapping_enable,
            user_data=rid,
        )
        dpg.add_button(
            label="Edit",
            height=MAPPER_STATE_BOX_ROW_H,
            callback=open_mapping_editor,
            user_data=rid,
        )
        dpg.add_button(
            label="X",
            height=MAPPER_STATE_BOX_ROW_H,
            callback=delete_mapping,
            user_data=rid,
        )
        if state.midi_learn_mode:  # e33 rule: the arm toggle is MIDI-mappable
            learn_marker(
                MIDI_ACTION_MAPPING_TOGGLE,
                {"mapping_id": rid},
                parent=tag,
                tag=f"mapping_mk_{rid}",
            )


def _mapping_box_height(mapping_count: int) -> int:
    """Fixed height of one Mapping box (e40s08, e40s11).

    A bordered child_window (WindowPadding 4 per side = MAPPER_ROW_PAD_V of air)
    holding the header row and one row per Mapping, separated by
    MAPPER_ROW_GAP. Rows are height-constant (MAPPER_STATE_BOX_ROW_H), so the
    box never needs scrolling. Measured against real DPG 2.3.1 on the rig: the
    formula is exact (content == box minus the padding) at every row count.
    """
    rows = max(0, int(mapping_count))
    return (
        MAPPER_ROW_PAD_V
        + MAPPER_STATE_BOX_HEADER_H
        + rows * (MAPPER_STATE_BOX_ROW_H + MAPPER_ROW_GAP)
    )


def _render_mapping_box(
    box_tag: str,
    head_tag: str,
    label: str,
    mappings: list[dict[str, Any]],
    parent: Any,
    head_extra: Callable[[], None],
) -> None:
    """A bordered box holding Mappings under a header (e40s08, e40s11).

    Every Mapping family renders in the SAME box shape — the per-source State
    band and the source-less Clock+Constant line — so the Mapper reads as one
    surface. ``head_extra`` adds the header's buttons/markers inside the header
    row (it must parent them to ``head_tag``).
    """
    with dpg.child_window(
        parent=parent,
        width=0,
        height=_mapping_box_height(len(mappings)),
        border=True,
        no_scrollbar=True,
        tag=box_tag,
    ):
        with dpg.group(horizontal=True, tag=head_tag):
            themed_text(label, slot="text_dim")
            head_extra()
        for mapping in mappings:
            _render_mapping_row(mapping, parent=box_tag)


def _render_state_box(
    target_id: str, mappings: list[dict[str, Any]], parent: Any, line_index: int
) -> None:
    """The per-source State band: a bordered box on the source line's own sub-line.

    e40s08: a State Origin always has a Source, so its Mappings belong to that
    Source's block instead of floating under the Control cards. The box carries
    NO line number — line numbering stays 1:1 with sources, so the tile menu
    'Add to Mapper > line N' and MIDI_ACTION_MAPPER_LINE keep resolving. Its
    header '+' adds a State Mapping to THIS source. An orphan Mapping (its source is
    gone) stays here, disabled, and resumes when the source returns.
    """
    head_tag = f"mapper_state_head_{target_id}"

    def head() -> None:
        dpg.add_button(
            label="+",
            width=MAPPER_X_W,
            height=MAPPER_X_H,
            callback=open_line_mapping_creator,
            user_data=target_id,
            tag=f"mapper_state_add_{target_id}",
        )
        if state.midi_learn_mode:  # e33 rule: the add action is MIDI-mappable
            learn_marker(
                MIDI_ACTION_MAPPING_ADD,
                {"line": line_index},
                parent=head_tag,
                tag=f"mapper_state_mk_{target_id}",
            )

    _render_mapping_box(f"mapper_state_box_{target_id}", head_tag, "State", mappings, parent, head)


def on_mapping_enable(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """Arm checkbox of a Mapping (mini-card OR row): flip the Enabled gate.

    e40s10: the card and the row are two renderings of the same Mapping, so they
    share ONE handler (an arm is an arm, no body refresh — e24).
    """
    mapper.set_mapping_enabled(int(user_data), bool(app_data))
    refresh_binding_leds()  # e53s02: the LED follows the arm from the mouse too


def copy_mapper_mapping(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """Card menu / MIDI: snapshot the Mapping into the clipboard (e51s02).

    The body rebuild is what makes the per-line Paste buttons appear.
    """
    if mapper.copy_mapping(int(user_data)) is None:
        return
    refresh_mapper_ui()


def cut_mapper_mapping(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """Card menu / MIDI: snapshot the Mapping and remove it (e51s02)."""
    mid = int(user_data)
    if mapper.cut_mapping(mid) is None:
        return
    _drop_mapping_editor_and_runs(mid)
    live_ids = {int(m["id"]) for m in state.mapper_mappings}
    emission.prune_book(state.mapping_book, state.mapping_values, live_ids)
    refresh_mapper_ui()


def paste_mapper_mapping(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """Line Paste button / MIDI: append the clipboard to that line (e51s02).

    ``user_data`` is the line's source id (None on the Global line, which keeps
    the snapshot's own target).
    """
    if mapper.paste_mapping(user_data) is None:
        return
    refresh_mapper_ui()


def move_mapper_mapping(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """Card menu / MIDI: shift the Mapping one slot inside its own line (e51s02)."""
    mid, delta = user_data
    if mapper.move_mapping_in_row(int(mid), int(delta)):
        refresh_mapper_ui()


def delete_mapping(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """X of a Mapping (mini-card OR row): remove it and its runtime memory (e40s10).

    One path for both renderings: the Mapping leaves the list, its cue run stops
    and its open editor closes (`_drop_mapping_editor_and_runs`), and the engine's
    per-Mapping bookkeeping is pruned.
    """
    mid = int(user_data)
    mapper.remove_mapping(mid)
    _drop_mapping_editor_and_runs(mid)
    live_ids = {int(m["id"]) for m in state.mapper_mappings}
    emission.prune_book(state.mapping_book, state.mapping_values, live_ids)
    refresh_mapper_ui()


# --- e40s10: the ONE Mapping editor (create + modify) -------------------------
# A Mapping is one object: the mini-card and the row are two renderings of it,
# and create/modify share one modal. Creation lives ONLY on the "+" buttons: the
# Global line's "+" is the general entry (every Type, asking for the Source when
# the Type is source-bound — also the only way to start a NEW Source line), a
# line's "+" fixes the Source. Clock/Constant Mappings have no Source, so they
# are created from the Global "+" only.
MAPPER_EDITOR_TAG = "mapper_mapping_window"
MAPPER_SOURCE_BOUND_ORIGINS: tuple[str, ...] = (ORIGIN_CONTROL, ORIGIN_STATE)
MAPPER_SOURCE_LESS_ORIGINS: tuple[str, ...] = (ORIGIN_CLOCK, ORIGIN_CONST)
MAPPER_ALL_ORIGINS: tuple[str, ...] = (
    ORIGIN_CONTROL,
    ORIGIN_STATE,
    ORIGIN_CLOCK,
    ORIGIN_CONST,
)
MAPPER_CONTROL_KINDS: tuple[str, ...] = tuple(
    c for c in mapper.MAPPER_CONTROLS if c != mapper.MAPPER_CONTROL_MAPPING
)


def open_line_mapping_creator(
    sender: Any = None, app_data: Any = None, user_data: Any = None
) -> None:
    """A line's '+' (and the tile menu): create a Mapping on THAT Source (e40s10).

    Only the source-bound Types are offered — a Clock/Constant Mapping has no
    Source and is created from the Global '+'.
    """
    target_id = str(user_data or "")
    if not target_id:
        return
    _open_mapping_editor(None, target_id=target_id, origins=MAPPER_SOURCE_BOUND_ORIGINS)


def open_mapping_creator(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """The filter bar's '+': the GENERAL creator for every Type (e40s10, e40s11).

    It sits next to the Show chips and is the only truly general entry: any
    Type, the Source asked when the Type is source-bound.
    """
    _open_mapping_editor(None, target_id=None, origins=MAPPER_ALL_ORIGINS)


def open_source_less_mapping_creator(
    sender: Any = None, app_data: Any = None, user_data: Any = None
) -> None:
    """The Clock+Constant box '+': only the source-less Types (e40s11)."""
    _open_mapping_editor(None, target_id=None, origins=MAPPER_SOURCE_LESS_ORIGINS)


def open_mapping_editor(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """'Edit' on a Mapping row: open the editor in modify mode (e40s01)."""
    _open_mapping_editor(int(user_data))


def _sync_mapping_component_picker(prop: str) -> None:
    """Populate + reveal the component picker for a vector property (e36s03)."""
    entry = _maybe_catalog_entry(prop)
    keys = (
        [c["key"] for c in entry["components"]]
        if entry is not None and len(entry["components"]) > 1
        else []
    )
    if keys:
        dpg.configure_item("mapping_component_combo", items=keys)
        dpg.set_value("mapping_component_combo", keys[0])
    dpg.configure_item("mapping_comp_group", show=bool(keys))
    # e76s02: the Component card follows the property (its components and ranges).
    component_help = helpprose.component_card(prop)
    replace_help_card("mapping_component_combo", "mapper.component", component_help)
    replace_help_card("mapping_component_label", "mapper.component", component_help)


def on_mapping_prop_change(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """Property combo: reveal the component picker for a vector property and
    suggest the right control kind for the toggle/trigger families (e36s03)."""
    prop = str(app_data)
    # e76s02: the LIVE Property card follows the selection, uniforms included.
    property_text = helpprose.property_card(prop).body
    _refresh_help_text("mapping_property_combo", property_text)
    _refresh_help_text("mapping_property_label", property_text)
    _sync_button_mode_row()  # e77: a trigger property hides the mode choice
    entry = _maybe_catalog_entry(prop)
    if entry is None:
        return
    family = str(entry["family"])
    suggests_button = (
        family in (catalog.FAMILY_TOGGLE, catalog.FAMILY_TRIGGER)
        and dpg.does_item_exist("mapping_control_combo")
        and str(dpg.get_value("mapping_control_combo")) != "cue list"
    )
    if suggests_button:
        dpg.set_value("mapping_control_combo", "button")
    _sync_mapping_component_picker(prop)


def _sync_button_mode_row() -> None:
    """Show 'Button mode' only for a GUI button that is not already a trigger (e77).

    A trigger property (replay/reset/reload/flag) is one-shot by definition, so it
    gets a one-line hint instead of a choice that would not change anything.
    """
    if not dpg.does_item_exist("mapping_button_mode_group"):
        return
    control = str(dpg.get_value("mapping_control_combo"))
    entry = _maybe_catalog_entry(str(dpg.get_value("mapping_property_combo")))
    is_trigger = entry is not None and entry["family"] == catalog.FAMILY_TRIGGER
    is_button = control == "button"
    dpg.configure_item("mapping_button_mode_group", show=is_button and not is_trigger)
    dpg.configure_item("mapping_button_mode_hint", show=is_button and is_trigger)


def on_mapping_control_kind_change(
    sender: Any = None, app_data: Any = None, user_data: Any = None
) -> None:
    """Control-kind combo: a 'cue list' needs no property (its trigger runs an
    editable OSC macro), so hide the property row and pin it to the inert
    'play' — the card caption only (e35s04, e36s03)."""
    is_cue = str(app_data) == "cue list"
    if is_cue:
        dpg.set_value("mapping_property_combo", "play")
    dpg.configure_item("mapping_property_group", show=not is_cue)
    dpg.configure_item("mapping_cue_hint", show=is_cue)
    if not is_cue:
        _sync_mapping_component_picker(str(dpg.get_value("mapping_property_combo")))
    _sync_button_mode_row()  # e77


def on_mapping_destination_change(
    sender: Any = None, app_data: Any = None, user_data: Any = None
) -> None:
    """Destination combo: reveal only its own fields (e40s03)."""
    destination = str(app_data or DEST_MIDI)
    dpg.configure_item("mapping_midi_fields", show=destination == DEST_MIDI)
    dpg.configure_item("mapping_osc_fields", show=destination == DEST_OSC)


def on_mapping_origin_change(
    sender: Any = None, app_data: Any = None, user_data: Any = None
) -> None:
    """Type combo: reveal the chosen Type's fields and re-filter the Destination
    list from MAPPING_DIRECTIONS (e40s02, e40s10)."""
    origin = str(app_data or ORIGIN_STATE)
    options = [d for d in DESTINATIONS if d in MAPPING_DIRECTIONS[origin]]
    destination = str(dpg.get_value("mapping_destination_combo"))
    if destination not in options:
        destination = options[0]
    dpg.configure_item("mapping_destination_combo", items=options)
    dpg.set_value("mapping_destination_combo", destination)
    on_mapping_destination_change(None, destination)
    # e76s02: the Destination card ENUMERATES, so a new option list is a new card.
    destination_help = helpprose.destination_card(options)
    replace_help_card("mapping_destination_combo", "mapper.destination", destination_help)
    replace_help_card("mapping_destination_label", "mapper.destination", destination_help)
    _apply_mapping_editor_visibility(origin)


def _apply_mapping_editor_visibility(origin: str) -> None:
    """Show exactly the fields of one Origin type (e40s10).

    The Destination-dependent fields are handled by on_mapping_destination_change;
    the Destination itself is hidden for a Control Mapping, whose Destination is
    Vimix by the v1 direction matrix — the hint says so instead of showing an
    impossible choice.
    """
    is_control = origin == ORIGIN_CONTROL
    is_cue = is_control and str(dpg.get_value("mapping_control_combo")) == "cue list"
    dpg.configure_item("mapping_source_group", show=origin in MAPPER_SOURCE_BOUND_ORIGINS)
    dpg.configure_item("mapping_control_kind_group", show=is_control)
    dpg.configure_item(
        "mapping_property_group", show=origin in MAPPER_SOURCE_BOUND_ORIGINS and not is_cue
    )
    dpg.configure_item("mapping_cue_hint", show=is_cue)
    dpg.configure_item("mapping_state_group", show=origin == ORIGIN_STATE)
    dpg.configure_item("mapping_clock_fields", show=origin == ORIGIN_CLOCK)
    dpg.configure_item("mapping_const_fields", show=origin == ORIGIN_CONST)
    dpg.configure_item("mapping_destination_group", show=not is_control)
    dpg.configure_item("mapping_vimix_hint", show=is_control)
    dpg.configure_item("mapping_steps_group", show=not is_control)
    if not is_cue:
        _sync_mapping_component_picker(str(dpg.get_value("mapping_property_combo")))
    _sync_button_mode_row()  # e77


def _mapping_creator_sources() -> list[str]:
    """The Source picker of the general creator: the LIVE sources (e40s10).

    BUG-2026-10-14T160827: the picker used to list ``mapper.row_targets()`` — the
    sources that already have a line — so the first Mapping of a new source could
    not be created from inside the Mapper. Grid order matches the Mediagrid and
    the Text/Shader pickers. When the live table is still empty (boot, pairing),
    fall back to the existing lines so the picker is not a dead end.
    """
    live = _source_target_ids_in_grid_order()
    return live or list(mapper.row_targets())


def _mapping_creator_default_source(items: list[str]) -> str:
    """The Source the general creator preselects: the media-grid selection.

    A DEFAULT, not a fixed source (the line '+' fixes its own): the picker stays
    visible, and an absent or non-live selection leaves it empty.
    """
    selected = state.vjmix_selected_source
    return selected if selected in items else ""


def _open_mapping_editor(
    mapping_id: int | None = None,
    *,
    target_id: str | None = None,
    origins: tuple[str, ...] = MAPPER_ALL_ORIGINS,
) -> None:
    """The ONE Mapping editor: CREATE (``mapping_id`` None) or MODIFY (e40s10).

    Create mode builds NO Mapping until OK, so a cancel leaves nothing behind.
    Modify mode never offers the Source as an editable field: re-pointing a Line
    onto another Source is the row thumbnail's job (``mapper.retarget_source``),
    never a side effect of editing a Mapping. A Control Mapping is not edited
    here — its mini-card carries the live control. The whole window is rebuilt on
    every open, so the mode is fixed at build time.
    """
    mapping: dict[str, Any] = {}
    if mapping_id is None:
        origin = origins[0]
    else:
        found = mapper.find_mapping(int(mapping_id))
        if found is None or mapper.origin_of(found) == ORIGIN_CONTROL:
            return
        mapping = found
        origin = mapper.origin_of(mapping)
    creating = mapping_id is None
    if dpg.does_item_exist(MAPPER_EDITOR_TAG):
        dpg.delete_item(MAPPER_EDITOR_TAG)
    destination = (
        mapper.DEST_VIMIX
        if origin == ORIGIN_CONTROL
        else (mapper.destination_of(mapping) if not creating else DEST_MIDI)
    )
    spec = dict(mapping.get("destination_spec") or {})
    ports = [str(c.get("port", "")) for c in midi_controllers if c.get("port")]
    default_prop = {ORIGIN_CONTROL: "brightness", ORIGIN_STATE: "seek"}.get(origin, "alpha")
    prop = default_prop if creating else str(mapping["property"])
    clock = str((mapping.get("origin_spec") or {}).get("clock") or CLOCK_DEFAULT)
    const = float((mapping.get("origin_spec") or {}).get("value", MAPPING_CONST_VALUE_DEFAULT))
    cadence = int(mapping.get("cadence") or MAPPING_DEFAULT_CADENCE_MS)
    steps = int(mapping.get("steps", MAPPING_STEPS_CONTINUOUS))
    with dpg.window(
        label="New Mapping" if creating else "Edit Mapping",
        tag=MAPPER_EDITOR_TAG,
        modal=True,
        width=460,
        height=540,
        no_resize=True,
    ):
        type_card = helpprose.type_card(origins)  # e76s02: only the offered origins
        help_label("Type", "mapper.type", tag="mapping_type_label", card=type_card)
        dpg.add_combo(
            items=list(origins),
            default_value=origin,
            width=280,
            tag="mapping_origin_combo",
            callback=on_mapping_origin_change,
        )
        help_tooltip("mapping_origin_combo", "mapper.type", card=type_card)
        with dpg.group(tag="mapping_source_group"):
            help_label("Source", "mapper.source", tag="mapping_source_label")
            # A line's '+' already knows the Source (e40s10 / e45): only the
            # GENERAL creator (no target_id) asks for it. The hidden combo keeps
            # the value, so the confirm can never pick an empty source
            # (BUG-2026-09-15T202915). BUG-2026-10-14T160827: the general creator
            # offers the LIVE sources, and a grid selection is only a default —
            # the picker stays visible so it can still be changed.
            source_items = _mapping_creator_sources()
            source_value = str(target_id or "") if creating else str(mapping.get("target_id") or "")
            has_source = bool(source_value)
            if creating and not has_source:
                source_value = _mapping_creator_default_source(source_items)
            dpg.add_combo(
                items=source_items,
                default_value=source_value,
                width=280,
                show=not has_source,
                tag="mapping_source_combo",
            )
            if has_source:
                themed_text(
                    source_value
                    if creating
                    else f"{source_value} (use the row thumbnail to re-point)",
                    slot="text_dim",
                    tag="mapping_source_text",
                )
        with dpg.group(tag="mapping_control_kind_group"):
            help_label("Control", "mapper.control", tag="mapping_control_label")
            dpg.add_combo(
                items=list(MAPPER_CONTROL_KINDS),
                default_value="slider" if creating else str(mapping.get("control") or "slider"),
                width=200,
                tag="mapping_control_combo",
                callback=on_mapping_control_kind_change,
            )
            help_tooltip("mapping_control_combo", "mapper.control")
            with dpg.group(tag="mapping_button_mode_group"):
                help_label("Button mode", "mapper.button_mode", tag="mapping_button_mode_label")
                dpg.add_combo(
                    items=list(mapper.MAPPER_BUTTON_MODES),
                    default_value=mapper.sanitize_button_mode(mapping.get("button_mode")),
                    width=200,
                    tag="mapping_button_mode_combo",
                )
                help_tooltip("mapping_button_mode_combo", "mapper.button_mode")
        themed_text(
            "A trigger property already fires once per press.",
            slot="text_dim",
            tag="mapping_button_mode_hint",
            wrap=420,
        )
        with dpg.group(tag="mapping_property_group"):
            property_help = helpprose.property_card(prop)  # e76s02: LIVE, follows the combo
            help_label(
                "Property", "mapper.property", tag="mapping_property_label", card=property_help
            )
            dpg.add_combo(
                items=mapper.mapper_properties(),  # e83: + the Mapper-only action
                default_value=prop,
                width=280,
                tag="mapping_property_combo",
                callback=on_mapping_prop_change,
            )
            help_tooltip("mapping_property_combo", "mapper.property", card=property_help)
            with dpg.group(tag="mapping_comp_group", show=False):
                component_help = helpprose.component_card(prop)
                help_label(
                    "Component",
                    "mapper.component",
                    tag="mapping_component_label",
                    card=component_help,
                )
                dpg.add_combo(items=[], default_value="", width=280, tag="mapping_component_combo")
                help_tooltip("mapping_component_combo", "mapper.component", card=component_help)
        themed_text(
            "The trigger runs the mapping's OSC macro (cue list) — no property needed.",
            slot="text_dim",
            tag="mapping_cue_hint",
            wrap=420,
        )
        with dpg.group(tag="mapping_state_group"):
            help_label("Cadence (ms)", "mapper.cadence", tag="mapping_cadence_label")
            dpg.add_drag_int(
                default_value=cadence,
                min_value=MAPPING_MIN_CADENCE_MS,
                max_value=60_000,
                width=160,
                tag="mapping_cadence",
            )
        with dpg.group(tag="mapping_clock_fields"):
            help_label("Clock", "mapper.clock", tag="mapping_clock_label")
            dpg.add_combo(
                items=list(CLOCK_SOURCES), default_value=clock, width=200, tag="mapping_clock_combo"
            )
            help_tooltip("mapping_clock_combo", "mapper.clock")
        with dpg.group(tag="mapping_const_fields"):
            help_label("Value", "mapper.value", tag="mapping_value_label")
            dpg.add_drag_float(
                default_value=const,
                min_value=MAPPING_CONST_VALUE_MIN,
                max_value=MAPPING_CONST_VALUE_MAX,
                width=160,
                format="%.3f",
                speed=0.01,
                tag="mapping_const_value",
            )
        with dpg.group(tag="mapping_destination_group"):
            destination_options = [d for d in DESTINATIONS if d in MAPPING_DIRECTIONS[origin]]
            destination_help = helpprose.destination_card(destination_options)  # e76s02: live
            help_label(
                "Destination",
                "mapper.destination",
                tag="mapping_destination_label",
                card=destination_help,
            )
            dpg.add_combo(
                items=destination_options,
                default_value=destination,
                width=280,
                tag="mapping_destination_combo",
                callback=on_mapping_destination_change,
            )
            help_tooltip("mapping_destination_combo", "mapper.destination", card=destination_help)
        themed_text(
            "A Control Mapping always writes Vimix (its card holds the control).",
            slot="text_dim",
            tag="mapping_vimix_hint",
            wrap=420,
        )
        with dpg.group(tag="mapping_midi_fields"):
            help_label("Controller", "mapper.controller", tag="mapping_controller_label")
            dpg.add_combo(
                items=ports,
                default_value=str(spec.get("controller_port") or (ports[0] if ports else "")),
                width=280,
                tag="mapping_controller_combo",
            )
        with dpg.group(horizontal=True, tag="mapping_midi_row"):
            help_label("Channel", "mapper.channel", tag="mapping_channel_label")
            dpg.add_drag_int(
                default_value=int(spec.get("channel", 0)),
                min_value=0,
                max_value=15,
                width=70,
                tag="mapping_channel",
            )
            help_label("Message", "mapper.message", tag="mapping_message_label")
            dpg.add_combo(
                items=[MIDI_KIND_CC, MIDI_KIND_NOTE],
                default_value=str(spec.get("type") or MIDI_KIND_CC),
                width=90,
                tag="mapping_message_combo",
            )
            help_label("Number", "mapper.number", tag="mapping_number_label")
            dpg.add_drag_int(
                default_value=int(spec.get("number", 0)),
                min_value=0,
                max_value=127,
                width=70,
                tag="mapping_number",
            )
        with dpg.group(tag="mapping_osc_fields"):
            help_label("Host", "mapper.host", tag="mapping_host_label")
            dpg.add_input_text(
                default_value=str(spec.get("host") or MAPPING_OSC_DEFAULT_HOST),
                width=280,
                tag="mapping_osc_host",
            )
            help_label("Port", "mapper.port", tag="mapping_port_label")
            dpg.add_input_int(
                default_value=int(spec.get("port") or MAPPING_OSC_DEFAULT_PORT),
                width=160,
                tag="mapping_osc_port",
            )
            help_label("Address", "mapper.address", tag="mapping_address_label")
            dpg.add_input_text(
                default_value=str(spec.get("address") or MAPPING_OSC_DEFAULT_ADDRESS),
                width=280,
                tag="mapping_osc_address",
            )
        with dpg.group(tag="mapping_steps_group"):
            help_label("Steps (1 = continuous)", "mapper.steps", tag="mapping_steps_label")
            dpg.add_drag_int(
                default_value=steps,
                min_value=1,
                max_value=64,
                width=160,
                tag="mapping_steps",
            )
        # e76s02: the controls themselves — the labels above carry their own card.
        help_tooltip("mapping_source_combo", "mapper.source")
        help_tooltip("mapping_cadence", "mapper.cadence")
        help_tooltip("mapping_const_value", "mapper.value")
        help_tooltip("mapping_controller_combo", "mapper.controller")
        help_tooltip("mapping_channel", "mapper.channel")
        help_tooltip("mapping_message_combo", "mapper.message")
        help_tooltip("mapping_number", "mapper.number")
        help_tooltip("mapping_osc_host", "mapper.host")
        help_tooltip("mapping_osc_port", "mapper.port")
        help_tooltip("mapping_osc_address", "mapper.address")
        help_tooltip("mapping_steps", "mapper.steps")
        if has_source:
            help_tooltip("mapping_source_text", "mapper.source")
        dpg.add_separator()
        with dpg.group(horizontal=True):
            dpg.add_button(
                label="OK",
                width=120,
                callback=mapping_editor_confirm,
                user_data=0 if mapping_id is None else int(mapping_id),
            )
            dpg.add_button(
                label="Cancel",
                width=120,
                callback=lambda s, a: dpg.delete_item(MAPPER_EDITOR_TAG),
            )
    on_mapping_destination_change(None, destination)
    _apply_mapping_editor_visibility(origin)
    _sync_button_mode_row()  # e77
    show_centered_window(MAPPER_EDITOR_TAG)  # e55: dialogs open centered


def _mapping_editor_values(mapping: dict[str, Any], *, creating: bool) -> dict[str, Any]:
    """Read the editor widgets into a plain dict (ONE reader for both modes).

    The Source is read ONLY where it is editable (create, or a source-less
    Mapping being turned into a State one): on a plain modify it stays whatever
    the Mapping already had, so the editor can never re-point a Line.
    """
    origin = str(dpg.get_value("mapping_origin_combo"))
    destination = str(dpg.get_value("mapping_destination_combo"))
    source_editable = origin in MAPPER_SOURCE_BOUND_ORIGINS and (
        creating or not mapping.get("target_id")
    )
    values: dict[str, Any] = {
        "origin": origin,
        "destination": destination,
        "component": None,
        "target_id": (str(dpg.get_value("mapping_source_combo")) or None)
        if source_editable
        else None,
        "property": str(dpg.get_value("mapping_property_combo")),
    }
    if origin == ORIGIN_CONTROL:
        values["control"] = str(dpg.get_value("mapping_control_combo"))
        if values["control"] == "button":
            values["button_mode"] = mapper.sanitize_button_mode(
                str(dpg.get_value("mapping_button_mode_combo"))
            )
    if origin == ORIGIN_STATE:
        values["cadence"] = max(MAPPING_MIN_CADENCE_MS, int(dpg.get_value("mapping_cadence")))
    if origin == ORIGIN_CLOCK:
        values["clock"] = str(dpg.get_value("mapping_clock_combo"))
    if origin == ORIGIN_CONST:
        values["value"] = float(dpg.get_value("mapping_const_value"))
    if origin != ORIGIN_CONTROL:
        values["steps"] = max(MAPPING_STEPS_CONTINUOUS, int(dpg.get_value("mapping_steps")))
    if destination == DEST_MIDI:
        values["destination_spec"] = {
            "controller_port": str(dpg.get_value("mapping_controller_combo")),
            "channel": int(dpg.get_value("mapping_channel")),
            "type": str(dpg.get_value("mapping_message_combo")),
            "number": int(dpg.get_value("mapping_number")),
        }
    elif destination == DEST_OSC:
        values["destination_spec"] = {
            "host": str(dpg.get_value("mapping_osc_host")),
            "port": int(dpg.get_value("mapping_osc_port")),
            "address": str(dpg.get_value("mapping_osc_address")),
        }
    entry = _maybe_catalog_entry(values["property"])
    if entry is not None and len(entry["components"]) > 1 and values.get("control") != "cue list":
        keys = [c["key"] for c in entry["components"]]
        candidate = str(dpg.get_value("mapping_component_combo"))
        values["component"] = candidate if candidate in keys else keys[0]
    return values


def _validate_mapping_editor(values: dict[str, Any], mapping: dict[str, Any]) -> str | None:
    """The editor's error message for a pair that cannot become a Mapping."""
    origin = values["origin"]
    destination = values["destination"]
    if destination not in MAPPING_DIRECTIONS[origin]:
        return f"destination {destination!r} is not allowed for type {origin!r}"
    known_source = bool(values.get("target_id") or mapping.get("target_id"))
    if origin in MAPPER_SOURCE_BOUND_ORIGINS and not known_source:
        return f"a {origin} mapping needs a source"
    if destination == DEST_OSC:
        return validate_osc_destination(values["destination_spec"])
    return None


def _create_mapping_from_editor(values: dict[str, Any]) -> None:
    """Create the Mapping with the single mapper factory (e40s10)."""
    origin = values["origin"]
    if origin == ORIGIN_CONTROL:
        mapper.add_mapping(
            values["target_id"],
            values["property"],
            values["control"],
            component=values["component"],
            button_mode=values.get("button_mode", mapper.MAPPER_BUTTON_MODE_TOGGLE),
        )
        return
    origin_spec: dict[str, Any] = {}
    if origin == ORIGIN_CLOCK:
        origin_spec = {"clock": values["clock"]}
    elif origin == ORIGIN_CONST:
        origin_spec = {"value": values["value"]}
    mapper.add_mapping(
        values["target_id"],
        values["property"],
        origin=origin,
        destination=values["destination"],
        destination_spec=values["destination_spec"],
        origin_spec=origin_spec,
        cadence=values.get("cadence"),
        steps=values.get("steps", MAPPING_STEPS_CONTINUOUS),
    )


def _update_mapping_from_editor(mapping: dict[str, Any], values: dict[str, Any]) -> None:
    """Store the edited fields, reseeding the Origin window (e40s02)."""
    origin = values["origin"]
    destination = values["destination"]
    previous_destination = mapper.destination_of(mapping)
    mapping["origin"] = origin
    mapping["destination"] = destination
    mapping["cadence"] = None
    if origin in MAPPER_SOURCE_BOUND_ORIGINS:
        if values.get("target_id"):
            mapping["target_id"] = values["target_id"]
        entry = _maybe_catalog_entry(values["property"])
        in_from, in_to = 0.0, 1.0
        if entry is not None:
            mapping["property"] = values["property"]
            comp = entry["components"][0]
            mapping["component"] = comp["key"] if len(entry["components"]) > 1 else None
            in_from, in_to = float(comp["min"]), float(comp["max"])
        mapping["control"] = values.get("control") or mapper.MAPPER_CONTROL_MAPPING
        mapping["origin_spec"] = {}
        if origin == ORIGIN_STATE:
            mapping["control"] = mapper.MAPPER_CONTROL_MAPPING
            mapping["cadence"] = values["cadence"]
    elif origin == ORIGIN_CLOCK:
        mapping["origin_spec"] = {"clock": values["clock"]}
        mapping["target_id"] = None
        mapping["control"] = mapper.MAPPER_CONTROL_MAPPING
        in_from, in_to = CLOCK_SOURCES.get(values["clock"], (0.0, 1.0))
    else:
        mapping["origin_spec"] = {"value": values["value"]}
        mapping["target_id"] = None
        mapping["control"] = mapper.MAPPER_CONTROL_MAPPING
        in_from, in_to = 0.0, 1.0
    if "button_mode" in values:  # e77: only a button carries the choice
        mapping["button_mode"] = values["button_mode"]
    mapper.set_mapping_input(mapping["id"], float(in_from), float(in_to))
    mapping["steps"] = values.get("steps", MAPPING_STEPS_CONTINUOUS)
    mapping["destination_spec"] = values["destination_spec"]
    if destination != previous_destination:
        out_from, out_to = mapper.default_output_range(
            destination, str(mapping["property"]), mapping.get("component")
        )
        mapper.set_mapping_output(mapping["id"], out_from, out_to)


def mapping_editor_confirm(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """OK of the ONE Mapping editor: CREATE (user_data 0) or MODIFY (e40s10).

    The widget values are read BEFORE the window is deleted — real dpg get_value
    on a deleted widget returns None (BUG-2026-09-08T120000).
    """
    mapping_id = int(user_data or 0)
    creating = mapping_id == 0
    mapping = {} if creating else mapper.find_mapping(mapping_id)
    if mapping is None:
        return
    values = _mapping_editor_values(mapping, creating=creating)
    error = _validate_mapping_editor(values, mapping)
    if error is not None:
        log_error("Mapper", f"mapping editor: {error}")
        return  # keep the editor open so the user can fix the input
    if creating:
        _create_mapping_from_editor(values)
    else:
        _update_mapping_from_editor(mapping, values)
    dpg.delete_item(MAPPER_EDITOR_TAG)
    refresh_mapper_ui()
    dpg.show_item("mapper_window")


def _render_global_block(global_mappings: list[dict[str, Any]]) -> None:
    """The source-less (Clock/Constant) Mappings in their own box (e40s01, e40s11).

    Rendered even when empty so its '+' is always reachable: that '+' offers
    ONLY Clock and Constant (the general creator lives in the filter bar). The
    box is the same shape as the per-source State band, for a uniform surface.
    """
    head_tag = "mapper_global_head"

    def head() -> None:
        dpg.add_button(
            label="+",
            width=MAPPER_X_W,
            height=MAPPER_X_H,
            callback=open_source_less_mapping_creator,
            tag="mapper_global_add",
        )
        if state.mapper_clipboard is not None:  # e51s02: paste onto the Global line
            dpg.add_button(
                label="Paste",
                width=MAPPER_PASTE_W,
                height=MAPPER_X_H,
                callback=paste_mapper_mapping,
                user_data=None,
                tag="mapper_paste_global",
            )
            _bind_mapper_font("mapper_paste_global")
        if state.midi_learn_mode:  # e33 rule: the source-less creator is mappable
            learn_marker(
                MIDI_ACTION_MAPPING_ADD,
                {"source_less": True},
                parent=head_tag,
                tag="mapper_mk_global",
            )
            learn_marker(
                MIDI_ACTION_MAPPING_PASTE,
                {"global": True},
                parent=head_tag,
                tag="mapper_mk_paste_global",
            )

    _render_mapping_box(
        "mapper_global_block",
        head_tag,
        "Clock+Constant",
        global_mappings,
        "mapper_mappings_group",
        head,
    )


def refresh_mapper_ui() -> None:
    """Rebuild the Mapper window body from state.mapper_mappings (main thread).

    e22s01/e24s02: the body is a vertical stack of SOURCE BLOCKS. Rows derive
    from the flat mapping list at every rebuild — one block per distinct
    target_id in first-appearance order, mappings inside in list (creation)
    order. Each block wraps its mappings onto as many aligned LINES as the
    live window width fits: the source thumbnail slot leads the FIRST line
    only, later lines start with an empty spacer the width of the thumbnail
    slot so the cards align under the first line's cards. A source whose last
    mapping was deleted produces no block, so it disappears on the redraw;
    a window resize re-runs this rebuild (see the mapper_resize registry).
    """
    if not dpg.does_item_exist("mapper_mappings_group"):
        return
    dpg.delete_item("mapper_mappings_group", children_only=True)
    if not state.mapper_mappings:
        # explicit parent: at runtime (menu callback) DPG cannot deduce the
        # implicit container, so a parentless add_text would raise 1011
        themed_text(
            "No mappings yet — right-click a source in Vimix sources.",
            slot="text_dim",
            wrap=MAPPER_WINDOW_WIDTH - 40,
            parent="mapper_mappings_group",
        )
        if _mapper_show_global:
            # e40s10: the Global '+' is the general creator, so a source-less
            # Mapping (Clock/Constant) is creatable even from an empty Mapper
            _render_global_block([])
        return
    # e40s01: split the flat list into Control Origins (the card bands, grouped
    # by source) and the other Mappings (the State bands + the source-less Global
    # line). Row order stays mapper.row_targets() (e31s01).
    targets = list(mapper.row_targets())
    rows: dict[str, list[dict[str, Any]]] = {target: [] for target in targets}
    mapping_rows: dict[str, list[dict[str, Any]]] = {target: [] for target in targets}
    global_mappings: list[dict[str, Any]] = []
    for mapping in state.mapper_mappings:
        if mapper.origin_of(mapping) == ORIGIN_CONTROL:
            target = mapping["target_id"]
            if target in rows:
                rows[target].append(mapping)
        elif str(mapping.get("target_id") or "") in mapping_rows:
            mapping_rows[str(mapping["target_id"])].append(mapping)
        else:
            global_mappings.append(mapping)
    if _mapper_show_global:
        _render_global_block(global_mappings)
    per_line = _mapper_cards_per_line()
    width = dpg.get_item_width("mapper_window") or MAPPER_WINDOW_WIDTH
    card_area = width - 8 - (_mapper_row_lead_px() + 4)
    pitch = MAPPER_MINI_W + 4
    for row_no, (target_id, control_mappings) in enumerate(rows.items(), start=1):
        value_mappings = mapping_rows.get(target_id, [])
        # e40s08: the State box shows its Mappings, and stays in learn mode so its
        # '+' learn marker has a home on every source.
        show_state_box = _mapper_show_get and (bool(value_mappings) or state.midi_learn_mode)
        if not (_mapper_show_control and control_mappings) and not show_state_box:
            continue
        block = dpg.add_group(parent="mapper_mappings_group")
        if control_mappings and _mapper_show_control:
            row_height = _mapper_row_height(control_mappings)
            # e34s01 (2026-09-05 rework): the per-row '+' is a SMALL trailing
            # button, not a card slot — it rides the row's last card line when the
            # pixel room fits it (mapper.add_fits_last_line) and only moves to its
            # own narrow line when a very narrow window leaves no room.
            add_inline = mapper.add_fits_last_line(
                len(control_mappings), per_line, card_area, pitch, _mapper_add_slot_width()
            )
            lines = mapper.row_slots(len(control_mappings), per_line)
            for line_no, slot_line in enumerate(lines):
                line = dpg.add_group(horizontal=True, parent=block)
                if line_no == 0:
                    # e32s02: the row number leads the line (1-based window order,
                    # matches the tile menu "Add to Mapper > line N")
                    _mapper_line_number(row_no, target_id, parent=line, height=row_height)
                    _mapper_row_thumb(target_id, parent=line, height=row_height)
                    if state.midi_learn_mode:  # e33s03: map this row's line-assign action
                        learn_marker(
                            MIDI_ACTION_MAPPER_LINE,
                            {"line": row_no - 1},
                            parent=line,
                            tag=f"mapper_mk_line_{target_id}",
                        )
                else:
                    # alignment slot: continuation lines start where the cards of
                    # the first line start (row lead, e32s02/e33s03)
                    dpg.add_spacer(
                        width=_mapper_row_lead_px(),
                        parent=line,
                    )
                for slot in slot_line:
                    if slot < len(control_mappings):
                        try:
                            _render_mapper_card(
                                control_mappings[slot], parent=line, height=row_height
                            )
                        except Exception as exc:  # one bad card must not kill the body
                            log_error(
                                "Mapper card",
                                f"mapping {control_mappings[slot].get('id')}: {exc!r}",
                            )
                # e34s01: the small '+' rides the last card line when it fits
                if add_inline and line_no == len(lines) - 1:
                    _mapper_row_add(
                        target_id, parent=line, height=row_height, line_index=row_no - 1
                    )
                # e34s03 (answer D): while learn mode is on every card LINE gets a
                # marker strip line directly UNDER it — the cards' markers live
                # outside the bordered cards, aligned under each card slot. The
                # add-only slot lines carry no markers.
                if state.midi_learn_mode and any(
                    slot < len(control_mappings) for slot in slot_line
                ):
                    strip = dpg.add_group(
                        horizontal=True,
                        parent=block,
                        tag=f"mapper_mk_strip_{row_no}_{line_no}",
                    )
                    dpg.add_spacer(width=_mapper_row_lead_px(), parent=strip)
                    for slot in slot_line:
                        if slot < len(control_mappings):
                            _mapper_marker_slot(control_mappings[slot], parent=strip)
                    # e51s02: a SECOND strip line for the clipboard/move markers
                    edit_strip = dpg.add_group(
                        horizontal=True,
                        parent=block,
                        tag=f"mapper_mk_edit_strip_{row_no}_{line_no}",
                    )
                    dpg.add_spacer(width=_mapper_row_lead_px(), parent=edit_strip)
                    for slot in slot_line:
                        if slot < len(control_mappings):
                            _mapper_edit_marker_slot(control_mappings[slot], parent=edit_strip)
            if not add_inline:
                # a very narrow window: the '+' gets its own narrow line under the
                # cards (aligned with them) instead of overflowing the edge
                line = dpg.add_group(horizontal=True, parent=block)
                dpg.add_spacer(width=_mapper_row_lead_px(), parent=line)
                _mapper_row_add(target_id, parent=line, height=row_height, line_index=row_no - 1)
        else:
            # A State-only line — or a line whose Control band the filter hides —
            # keeps its identity lead (number + thumbnail) without cards. The lead
            # must fit the 70 px thumbnail: MAPPER_CTRL_H (14) clipped it to a
            # sliver of image, which read as a graphical defect (e40s12).
            lead_height = MAPPER_ROW_THUMB_H + 2
            line = dpg.add_group(horizontal=True, parent=block)
            _mapper_line_number(row_no, target_id, parent=line, height=lead_height)
            _mapper_row_thumb(target_id, parent=line, height=lead_height)
            if state.midi_learn_mode:
                learn_marker(
                    MIDI_ACTION_MAPPER_LINE,
                    {"line": row_no - 1},
                    parent=line,
                    tag=f"mapper_mk_line_{target_id}",
                )
        if show_state_box:
            # e40s08: the box starts where the cards start — after the row lead
            # (line number + thumbnail), so the Control cards and the State band
            # share the same left edge.
            state_line = dpg.add_group(
                horizontal=True, parent=block, tag=f"mapper_state_line_{target_id}"
            )
            dpg.add_spacer(width=_mapper_row_lead_px(), parent=state_line)
            _render_state_box(target_id, value_mappings, parent=state_line, line_index=row_no - 1)
    # e35s03/UAT: rebuilt cards relabel their running triggers and progress
    # readouts (the caches are stale after the body rebuild — re-seed in one pass)
    state.cue_trigger_label_cache.clear()
    state.cue_progress_cache.clear()
    tick_cue_triggers()


def show_mapper_window(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """Windows menu: open the Mapper window with a fresh mappings body (e16)."""
    refresh_mapper_ui()
    dpg.show_item("mapper_window")
    dpg.focus_item("mapper_window")  # e17: a shown window must come to the front


def on_mapper_control(sender: Any, app_data: Any, user_data: Any) -> None:
    """Slider/knob change: send the clamped OUTPUT value (e23s01)."""
    mid = int(user_data)
    mapper.send_mapping_value(mid, float(app_data))


def _sync_mapper_button_state(mapping: dict[str, Any]) -> None:
    """Restyle a square trigger (button) from the mapping's current value.

    BUG-2026-09-07T154112: the mouse click AND the MIDI value drive are two
    drivers of the same control — both must refresh label + theme, or a
    MIDI-mapped button stays visually OFF while state and OSC change.
    """
    kind = mapper.control_tag_kind(mapping["control"])
    tag = f"mapper_{kind}_{mapping['id']}"
    if not dpg.does_item_exist(tag):
        return
    dpg.configure_item(tag, label=_trigger_label(mapping))
    _style_trigger_theme(tag, _trigger_is_on(mapping))


def _after_button_press(mapping: dict[str, Any]) -> None:
    """Repaint a button card; a MOMENTARY one hands its OFF to a timer (e77)."""
    _sync_mapper_button_state(mapping)
    if mapper.is_momentary_button(mapping):
        _schedule_momentary_release(int(mapping["id"]))


def _schedule_momentary_release(mid: int) -> None:
    """Queue the automatic OFF of a momentary button after the fixed flash (e77).

    HIGH-1: the timer holds no dpg; it only enqueues the repaint (`ui_task`), the
    same recipe `flash_led` uses. The token makes a SECOND press supersede the
    first press's timer instead of being switched off by it.
    """
    token = state.mapper_button_flash_token.get(mid, 0) + 1
    state.mapper_button_flash_token[mid] = token
    threading.Timer(
        MAPPER_MOMENTARY_FLASH_S,
        lambda: ui_task(lambda: _release_momentary_button(mid, token)),
    ).start()


def _release_momentary_button(mid: int, token: int) -> None:
    """End a momentary press: back to the OFF end, repaint, and send NOTHING (e77).

    The operator asked for the GUI behaviour only: the action already happened on
    the press, and re-sending `output_from` would re-fire a trigger or switch a
    latch property off.
    """
    if state.mapper_button_flash_token.get(mid, 0) != token:
        return  # a newer press owns the square now
    mapping = mapper.find_mapping(mid)
    if mapping is None or not mapper.is_momentary_button(mapping):
        return
    mapping["value"] = float(mapping["output_from"])
    _sync_mapper_button_state(mapping)


def on_mapper_button(sender: Any, app_data: Any, user_data: Any) -> None:
    """Button/cue-list press.

    Button: toggle output_from (OFF) / output_to (ON), send OSC, refresh the
    label. Cue list (e35s03/UAT): the trigger RUNS the mapping's cue — a press
    while the cue runs RESTARTS it, an empty/disabled cue is an engine no-op;
    the trigger reads ON while the cue runs and OFF when it finishes.
    """
    mid = int(user_data)
    mapping = mapper.find_mapping(mid)
    if mapping is None:
        return
    if mapping["control"] == "cue list":
        cue.cue_start(mid, allow_restart=True)
        tick_cue_triggers()
        return
    mapper.send_button_mapping(mid)
    mapping = mapper.find_mapping(mid)
    if mapping is None:
        return
    _after_button_press(mapping)


def _trigger_is_on(mapping: dict[str, Any]) -> bool:
    """A button-like trigger is visually ON when its value sits at the output_to end."""
    return float(mapping["value"]) == float(mapping["output_to"])


def _trigger_label(mapping: dict[str, Any]) -> str:
    """Square trigger text: a mapper button and a cue-list trigger read ON/OFF
    (UAT e35): the cue square is a momentary RUN trigger — ON while the cue is
    executing, OFF again when it finishes. No raw value ever shows inside.
    e36s03: a TRIGGER-family button (replay/reset/reload/flag) shows its action
    name instead — its value has no ON/OFF meaning and every press fires."""
    if str(mapping["property"]) == catalog.SET_CURRENT_PROPERTY:
        return "SET"  # e83: an action square, not an ON/OFF value
    if mapping["control"] == "button":
        if catalog.family_of(str(mapping["property"])) == catalog.FAMILY_TRIGGER:
            return str(mapping["property"]).upper()
        return "ON" if _trigger_is_on(mapping) else "OFF"
    return "ON" if cue.cue_is_running(int(mapping["id"])) else "OFF"


def _trigger_theme_signature() -> tuple[tuple[int, ...], ...]:
    """The palette colors the trigger themes depend on (rebuild trigger)."""
    pal = state.active_palette
    return tuple(tuple(pal[slot]) for slot in ("play_on_bg", "badge_bg", "text_bright", "text_dim"))


def _ensure_trigger_themes() -> None:
    """Create (or rebuild on palette change) the two SHARED trigger themes.

    e35 UAT (errors 1000/1005): per-trigger themes recreated on every refresh
    collided — DPG aliases must be unique. Two root themes (OFF index 0, ON
    index 1) are bound by many triggers; they are deleted and rebuilt only when
    the palette colors change.
    """
    signature = _trigger_theme_signature()
    tags = state.trigger_theme_tags
    if signature == state.trigger_theme_signature and all(
        t is not None and dpg.does_item_exist(t) for t in tags
    ):
        return
    for old in tags:
        if old is not None and dpg.does_item_exist(old):
            dpg.delete_item(old)
    rebuilt: list[str | None] = []
    for on in (False, True):
        if on:
            bg = state.active_palette["play_on_bg"]
            label_color = state.active_palette["text_bright"]
        else:
            bg = state.active_palette["badge_bg"]
            label_color = state.active_palette["text_dim"]
        theme_tag = f"th_trig_{'on' if on else 'off'}"
        with dpg.theme(tag=theme_tag), dpg.theme_component(dpg.mvThemeCat_Core):
            dpg.add_theme_color(dpg.mvThemeCol_Button, palette_rgba(bg))
            dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, palette_rgba(bg))
            dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, palette_rgba(bg))
            dpg.add_theme_color(dpg.mvThemeCol_Text, palette_rgba(label_color))
        rebuilt.append(theme_tag)
    state.trigger_theme_tags = rebuilt
    state.trigger_theme_signature = signature


def _style_trigger_theme(tag: str, on: bool) -> None:
    """Point a square trigger at the shared ON/OFF theme (UAT e35)."""
    if not dpg.does_item_exist(tag):
        return
    _ensure_trigger_themes()
    theme_tag = state.trigger_theme_tags[1 if on else 0]
    if theme_tag is not None:
        dpg.bind_item_theme(tag, theme_tag)


def _cue_progress_label(mapping: dict[str, Any]) -> str:
    """The card readout under 'Cue list...': '3 of 10' — executed actions over
    the cue total (waits are pacing, not actions). Empty cue -> blank (UAT e35)."""
    executed, total = cue.cue_progress(int(mapping["id"]))
    if total <= 0:
        return ""
    return f"{executed} of {total}"


def tick_cue_triggers() -> None:
    """Refresh every cue-list card trigger + progress readout (main thread).

    e35s03/UAT: cheap per-frame call — it only relabels triggers whose label
    left the cache (run started/finished), updates the 'N of Total' progress
    text while actions dispatch, or after a Mapper rebuild cleared the caches.
    Idle frames cost one dict loop over the cue-list mappings.
    """
    changed_labels: dict[int, str] = {}
    changed_progress: dict[int, str] = {}
    for mapping in state.mapper_mappings:
        if mapping.get("control") != "cue list":
            continue
        mid = int(mapping["id"])
        label = _trigger_label(mapping)
        if state.cue_trigger_label_cache.get(mid) != label:
            changed_labels[mid] = label
        progress = _cue_progress_label(mapping)
        if state.cue_progress_cache.get(mid) != progress:
            changed_progress[mid] = progress
    for mid, label in changed_labels.items():
        tag = f"mapper_cue_{mid}"
        if dpg.does_item_exist(tag):
            dpg.configure_item(tag, label=label)
            _style_trigger_theme(tag, label == "ON")
    for mid, progress in changed_progress.items():
        tag = f"mapper_cue_prog_{mid}"
        if dpg.does_item_exist(tag):
            dpg.set_value(tag, progress)
    state.cue_trigger_label_cache.update(changed_labels)
    state.cue_progress_cache.update(changed_progress)


def cue_tick_loop() -> None:
    """e35s03: drive the cue engine on the monotonic clock (fade_tick_loop pattern).

    The thread only works while a cue is running; UI reflection happens on the
    main thread (tick_cue_triggers), never here (HIGH-1).
    """
    while True:
        if state.cue_runs:
            cue.tick(time.monotonic() * 1000.0)
        time.sleep(0.01)  # 100 FPS cap, same cadence as the fade loop


def _sync_mapper_control(mid: int) -> None:
    """Reconfigure a mapping's control widget to its current output range (e23s01).

    Called after an output-box edit so the control min/max follow the new
    (possibly reversed) output range and the stored value stays inside it.
    """
    mapping = mapper.find_mapping(mid)
    if mapping is None:
        return
    kind = mapper.control_tag_kind(mapping["control"])  # e34s04: slider/knob/btn/cue
    tag = f"mapper_{kind}_{mid}"
    if not dpg.does_item_exist(tag):
        return
    out_from = mapping["output_from"]
    out_to = mapping["output_to"]
    if kind in ("slider", "knob"):
        dpg.configure_item(tag, min_value=out_from, max_value=out_to)
        dpg.set_value(tag, mapping["value"])
    else:  # button-like trigger: ON/OFF (button) or the value label (cue list)
        dpg.configure_item(tag, label=_trigger_label(mapping))
        _style_trigger_theme(tag, _trigger_is_on(mapping))


def on_mapper_output(sender: Any, app_data: Any, user_data: Any) -> None:
    """Drag an output from/to box: store the new output range and re-fit the control.

    Reads BOTH boxes (the edited one via the sender, the other via get_value)
    so the pair is always consistent; the control is reconfigured in place —
    no full body rebuild (a refresh mid-drag would kill the drag).
    """
    mid, _edge = user_data
    from_tag = f"mapper_out_from_{mid}"
    to_tag = f"mapper_out_to_{mid}"
    out_from = float(dpg.get_value(from_tag))
    out_to = float(dpg.get_value(to_tag))
    mapper.set_mapping_output(mid, out_from, out_to)
    _sync_mapper_control(mid)


def on_mapper_input(sender: Any, app_data: Any, user_data: Any) -> None:
    """Drag an input from/to box: store the new input range of the bound source.

    Reads BOTH boxes (edited via the sender, the other via get_value) so the
    pair is consistent; no body rebuild (a refresh mid-drag would kill it).
    """
    mid, _edge = user_data
    from_tag = f"mapper_in_from_{mid}"
    to_tag = f"mapper_in_to_{mid}"
    mapper.set_mapping_input(mid, float(dpg.get_value(from_tag)), float(dpg.get_value(to_tag)))


def reset_mapping(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """R on a mapping card: reset the control to its neutral default (e27s01).

    The core stores the neutral (catalog midpoint for slider/knob, the OFF
    end for buttons), clamps it into the mapping's output interval and sends
    it through the e24 gate; the widget moves in place via _sync_mapper_control
    — no body rebuild, so a live band/MIDI drive is never interrupted.
    """
    mid = int(user_data)
    # e77: a pending momentary release must not undo the reset a moment later.
    state.mapper_button_flash_token[mid] = state.mapper_button_flash_token.get(mid, 0) + 1
    mapping = mapper.find_mapping(mid)
    if mapping is not None and mapping.get("control") == "cue list":
        # e35s03: reset STOPS a running cue — no OSC, no value toggle (the cue
        # owns the trigger now, not the single property value)
        cue.cue_stop(mid)
        tick_cue_triggers()
        return
    mapper.reset_mapping_value(mid)
    _sync_mapper_control(mid)


def _cue_row_label(mapping: dict[str, Any], row: dict[str, Any]) -> str:
    """Human row text: 'alpha = 0.80', 'color (0.20, 0.90, 0.70)',
    'burst turn 0.50 for 500 ms', 'wait 500 ms', 'mapper #7: clipA lock'
    (e35s04 + e36s05 typed payloads)."""
    kind = row.get("kind")
    payload = row.get("payload", {})
    if kind in ("property", "burst"):
        prop = str(payload.get("property") or "")
        if isinstance(payload.get("values"), list):
            text = f"{prop} ({', '.join(f'{float(v):.2f}' for v in payload['values'])})"
        else:
            text = f"{prop} = {float(payload.get('value', 0.0)):.2f}"
        ms = payload.get("ms")
        if kind == "burst":
            text = "burst " + text + f" for {float(ms or 0.0):.0f} ms"
        elif ms:
            text += f" over {float(ms):.0f} ms"
        return text
    if kind == "wait":
        return f"wait {float(payload.get('ms', 0.0)):.0f} ms"
    ref = int(payload.get("mapping_id", 0))
    target = mapper.find_mapping(ref)
    if target is None:
        return f"mapper #{ref} (missing)"
    return f"mapper #{ref}: {target['target_id']} {target['property']}"


def _cue_mapper_option(mapping_id: int) -> str:
    """One mapper-picker item: '<id>: <target> <property>' (id parsed back in the dialog)."""
    target = mapper.find_mapping(mapping_id)
    if target is None:
        return f"{mapping_id}: missing"
    return f"{mapping_id}: {target['target_id']} {target['property']}"


# e35 UAT: horizontal pixels per indent level in the cue editor row list — a
# level-1 row starts visibly to the right of a level-0 row (like code indent).
CUE_ROW_INDENT_PX = 22


def _render_cue_row(mid: int, index: int, row: dict[str, Any]) -> None:
    """One row band: wave level, action label and the +/←/→/X commands (e35s04).

    UAT e35: the whole band is indented by ``level * CUE_ROW_INDENT_PX`` so the
    wave structure reads visually, not just through the level number.
    """
    mapping = mapper.find_mapping(mid)
    if mapping is None:
        return
    level = int(row["level"])
    with dpg.group(horizontal=True, tag=f"cue_row_{mid}_{index}"):
        if level:
            dpg.add_spacer(width=level * CUE_ROW_INDENT_PX)
        themed_text(str(level), slot="text_dim", tag=f"cue_lvl_{mid}_{index}")
        text_tag = f"cue_txt_{mid}_{index}"
        themed_text(_cue_row_label(mapping, row), slot="text", tag=text_tag)
        dpg.add_button(
            label="+",
            width=22,
            callback=cue_row_add_dialog,
            user_data=(mid, index),
            tag=f"cue_add_{mid}_{index}",
        )
        dpg.add_button(
            label="<-",
            width=26,
            callback=cue_row_shift,
            user_data=(mid, index, -1),
            tag=f"cue_left_{mid}_{index}",
        )
        dpg.add_button(
            label="->",
            width=26,
            callback=cue_row_shift,
            user_data=(mid, index, +1),
            tag=f"cue_right_{mid}_{index}",
        )
        dpg.add_button(
            label="X",
            width=22,
            callback=cue_row_delete,
            user_data=(mid, index),
            tag=f"cue_del_{mid}_{index}",
        )
    # double-click the action label to edit the row (e35s04)
    reg_tag = f"cue_dbl_reg_{mid}_{index}"
    if dpg.does_item_exist(reg_tag):
        dpg.delete_item(reg_tag)  # a rebuild must not leak registries
    with dpg.item_handler_registry(tag=reg_tag):
        dpg.add_item_double_clicked_handler(
            0,
            callback=lambda *_, m=mid, i=index: cue_row_edit_dialog(None, None, (m, i)),
        )
    if dpg.does_item_exist(text_tag):
        dpg.bind_item_handler_registry(text_tag, reg_tag)


def _render_cue_rows(mid: int) -> None:
    """Render the row bands (or the empty hint) into the cue_rows_group child."""
    mapping = mapper.find_mapping(mid)
    if mapping is None:
        return
    rows = (mapping.get("cue") or mapper.fresh_cue()).get("rows", [])
    if not rows:
        themed_text("Add rows with +", slot="text_dim")
        return
    for index, row in enumerate(rows):
        _render_cue_row(mid, index, row)


def _refresh_cue_rows(mid: int) -> None:
    """Rebuild the row list of the open cue window after a model change (e35s04).

    The rows live inside the ``cue_rows_group`` child, so the child must be
    PUSHED onto the container stack while rendering (a callback runs with an
    empty stack — parentless items would raise 1011/1009, the UAT bug).
    """
    if not dpg.does_item_exist("cue_rows_group"):
        return
    dpg.delete_item("cue_rows_group", children_only=True)
    dpg.push_container_stack("cue_rows_group")
    try:
        _render_cue_rows(mid)
    finally:
        dpg.pop_container_stack()


def _safe_refresh_cue_rows(mid: int) -> None:
    """Rebuild with errors surfaced in the Logs window (never a silent no-op)."""
    try:
        _refresh_cue_rows(mid)
    except Exception as e:  # worker/UI defensive posture: log, keep the app alive
        log_error("cue window", f"row refresh failed: {e}")


def on_cue_gap_change(sender: Any, app_data: Any, user_data: Any) -> None:
    """Level-gap drag box: store the cue's ms between levels (clamped >= 0, e35s04)."""
    mapping = mapper.find_mapping(int(user_data))
    if mapping is not None:
        cue = mapping.get("cue")
        if isinstance(cue, dict):
            cue["gap_ms"] = max(0.0, float(app_data))


def cue_window_run(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """'Run' in the cue window: start the mapping's cue (same path as the card trigger)."""
    cue.cue_start(int(user_data), allow_restart=True)
    tick_cue_triggers()


def cue_window_stop(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """'Stop' in the cue window: stop the run without OSC (e35s03/e35s04)."""
    cue.cue_stop(int(user_data))
    tick_cue_triggers()


def cue_row_add_dialog(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """'+' on a row: open the add dialog; the new row lands BELOW this one."""
    mid, index = user_data
    _open_cue_row_dialog(mid, insert_after=index)


def cue_window_add_dialog(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """'Add row' on an empty cue: append at the end."""
    _open_cue_row_dialog(int(user_data), insert_after=-1)


def cue_row_edit_dialog(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """Double-click on a row: open the edit dialog prefilled with the row (e35s04)."""
    mid, index = user_data
    _open_cue_row_dialog(mid, edit_index=index)


def cue_row_shift(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """'<-' / '->': move the row one wave level (model clamps at 0, e35s04)."""
    mid, index, delta = user_data
    mapping = mapper.find_mapping(mid)
    if mapping is None:
        return
    cue = mapping.get("cue") or mapper.fresh_cue()
    if mapper.shift_cue_row_level(cue, index, delta) is not None:
        _safe_refresh_cue_rows(mid)


def cue_row_delete(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """'X': delete the row and rebuild the list (e35s04)."""
    mid, index = user_data
    mapping = mapper.find_mapping(mid)
    if mapping is None:
        return
    cue = mapping.get("cue") or mapper.fresh_cue()
    mapper.remove_cue_row(cue, index)
    _safe_refresh_cue_rows(mid)


# Cue row dialog geometry (BUG-2026-09-12T191000): the window must FIT its
# editors — corner renders 8 components + ms (9 rows) and overflowed the old
# fixed 470 px height, hiding the OK/Cancel row.
CUE_DLG_DEFAULT_HEIGHT = 470
CUE_DLG_BASE_HEIGHT = 150  # kind + property pickers, separator, OK/Cancel
CUE_DLG_EDITOR_ROW_HEIGHT = 45  # one labelled drag row
CUE_DLG_MAX_HEIGHT = 640  # cap; taller content scrolls
# A no-argument trigger fires without a value, so the row dialog shows a hint
# instead of an editor whose content compose_send_args would discard.
CUE_DLG_FIRE_HINT = "Fire (no value: this message takes no argument)"
# The property and burst groups SHARE these fixed editor tags, so only the
# active kind may hold them (BUG-2026-09-12T191000: a cleanup loop that reused
# the renderer's ``container`` parameter sent every editor to the hidden burst
# group, so the property kind never showed its value editors).
CUE_DLG_VALUE_CONTAINERS = ("cue_prop_values", "cue_burst_values")


def on_cue_kind_change(sender: Any, app_data: Any, user_data: Any = None) -> None:
    """Row-dialog kind combo: reveal ONLY the fields of the chosen kind
    (e35s04 + e36s05: a 'burst' kind runs one bounded rate message).

    e36s06 real-DPG fix: the property/burst containers share the fixed editor
    tags (cue_dlg_value / cue_dlg_v0.. / cue_dlg_ms), so switching kind must
    re-render the ACTIVE value kind (or clear the shared containers when
    leaving them) — otherwise the burst area stays empty (no row can be added)
    and the previous kind's tags linger and duplicate (duplicate tags raise in
    real DPG 2.3.1).
    """
    kind = str(app_data)
    dpg.configure_item("cue_prop_fields", show=kind == "property")
    dpg.configure_item("cue_wait_fields", show=kind == "wait")
    dpg.configure_item("cue_mapper_fields", show=kind == "mapper")
    dpg.configure_item("cue_burst_fields", show=kind == "burst")
    _cue_dlg_render_kind_editors(kind)


def _cue_dlg_render_kind_editors(kind: str) -> None:
    """(Re)render the value editors of the row dialog's ACTIVE kind (e36s06).

    The property and burst containers share the fixed editor tags, so only one
    kind may hold them: entering a value kind renders one fresh set, leaving
    one clears both. Burst normalizes its property combo onto a legal rate
    when it still holds the previous kind's property.
    """
    if kind == "property":
        prop = str(dpg.get_value("cue_dlg_prop_combo"))
        if _maybe_catalog_entry(prop) is None:
            prop = "alpha"
            dpg.set_value("cue_dlg_prop_combo", prop)
        _cue_dlg_render_values("cue_prop_values", prop)
    elif kind == "burst":
        prop = str(dpg.get_value("cue_dlg_burst_combo"))
        rates = _cue_row_rate_candidates()
        if prop not in rates:
            prop = rates[0] if rates else "turn"
            dpg.set_value("cue_dlg_burst_combo", prop)
        _cue_dlg_render_values("cue_burst_values", prop)
    else:
        _cue_dlg_clear_editors()
        _cue_dlg_fit_height(None)


def _cue_dlg_clear_editors() -> None:
    """Drop the shared editor widgets so the next kind renders clean tags."""
    for shared_tag in CUE_DLG_VALUE_CONTAINERS:
        if dpg.does_item_exist(shared_tag):
            dpg.delete_item(shared_tag, children_only=True)


def _cue_dlg_fit_height(prop: str | None) -> None:
    """Fit the row dialog to the active property's editors (BUG-2026-09-12T191000).

    corner renders 8 components + ms = 9 editor rows, which the fixed 470 px
    window pushed below the visible area; a small property keeps the default
    height and a named cap keeps the modal sane (taller content scrolls).
    """
    rows = 0
    if prop is not None:
        entry = _catalog_entry(prop)
        rows = len(entry["components"]) + (1 if entry["ms"] else 0)
    height = CUE_DLG_BASE_HEIGHT + rows * CUE_DLG_EDITOR_ROW_HEIGHT
    height = max(CUE_DLG_DEFAULT_HEIGHT, min(height, CUE_DLG_MAX_HEIGHT))
    if dpg.does_item_exist("cue_dialog"):
        dpg.configure_item("cue_dialog", height=height)


def _dlg_float(tag: str, default: float) -> float:
    """Robust float read from a dialog widget (falls back on garbage, e35s04)."""
    try:
        return float(dpg.get_value(tag))
    except (TypeError, ValueError):
        return default


def _cue_row_prop_candidates() -> list[str]:
    """Property rows target every catalog property except the rate family."""
    return list(mapper.mappable_properties())


def _cue_row_rate_candidates() -> list[str]:
    """Burst rows target the rate family only (loom/turn/grab/resize/ffwd)."""
    return [p for p, e in catalog.PROPERTY_CATALOG.items() if e["family"] == catalog.FAMILY_RATE]


def _cue_dlg_render_values(
    container: str, prop: str, prefilled: list[float] | None = None, ms_value: float = 0.0
) -> None:
    """Render the value/component + optional ms editors of a row property into
    the given container (e36s05): one editor for a single-value property (tag
    cue_dlg_value), one labelled drag per component for multi-value properties
    (tags cue_dlg_v0..), plus an 'Animate (ms)' drag on ms-capable properties.

    The shared editor tags mean both containers are cleared first and the
    labels use themed_text (raw dpg.add_text has no ``slot`` keyword, e36s06).
    BUG-2026-09-12T191000: the cleanup loop must NOT reuse this function's
    ``container`` parameter — doing so parented every editor to the hidden
    burst group, so the property kind never showed its value. Family-aware
    editors: an enum offers its named options, a no-argument trigger shows a
    'fire' hint, everything else a drag.
    """
    _cue_dlg_clear_editors()
    entry = _catalog_entry(prop)
    comps = entry["components"]
    pre = prefilled or [float(c["neutral"]) for c in comps]
    if entry["family"] == catalog.FAMILY_TRIGGER and not catalog.trigger_carries_value(prop):
        themed_text(CUE_DLG_FIRE_HINT, slot="text_dim", parent=container)
    elif entry["family"] == catalog.FAMILY_ENUM:
        _cue_dlg_add_enum_editor(container, entry, pre)
    else:
        _cue_dlg_add_component_editors(container, comps, pre)
    if entry["ms"]:
        _cue_dlg_add_ms_editor(container, ms_value)
    _cue_dlg_fit_height(prop)


def _cue_dlg_add_component_editors(
    container: str, comps: list[dict[str, Any]], pre: list[float]
) -> None:
    """One labelled drag per component under the fixed editor tags."""
    if len(comps) == 1:
        comp = comps[0]
        themed_text("Value", slot="text_dim", parent=container)
        dpg.add_drag_float(
            parent=container,
            default_value=pre[0],
            min_value=float(comp["min"]),
            max_value=float(comp["max"]),
            width=140,
            format="%.2f",
            speed=0.01,
            tag="cue_dlg_value",
        )
        return
    for i, comp in enumerate(comps):
        themed_text(str(comp["label"]), slot="text_dim", parent=container)
        dpg.add_drag_float(
            parent=container,
            default_value=pre[i] if i < len(pre) else float(comp["neutral"]),
            min_value=float(comp["min"]),
            max_value=float(comp["max"]),
            width=140,
            format="%.2f",
            speed=0.01,
            tag=f"cue_dlg_v{i}",
        )


def _cue_dlg_add_enum_editor(container: str, entry: dict[str, Any], pre: list[float]) -> None:
    """An enum row picks its named option; the payload stores the index."""
    options = [str(o) for o in entry["options"] or []]
    index = max(0, min(round(pre[0]), len(options) - 1)) if options else 0
    themed_text("Value", slot="text_dim", parent=container)
    dpg.add_combo(
        items=options,
        default_value=options[index] if options else "",
        width=140,
        tag="cue_dlg_value",
        parent=container,
    )


def _cue_dlg_add_ms_editor(container: str, ms_value: float) -> None:
    """The optional native-animation duration of an ms-capable property."""
    themed_text("Animate (ms)", slot="text_dim", parent=container)
    dpg.add_drag_float(
        parent=container,
        default_value=ms_value if ms_value > 0 else 0.0,
        width=140,
        format="%.0f",
        speed=10.0,
        min_value=0.0,
        max_value=60_000.0,
        tag="cue_dlg_ms",
    )


def _cue_dlg_read_payload(prop: str) -> dict[str, Any]:
    """Read the value/ms fields rendered by _cue_dlg_render_values into the
    model payload shape {property, value|values, ms?} (e36s05). A no-argument
    trigger carries no value: compose_send_args fires [] regardless."""
    entry = _catalog_entry(prop)
    payload: dict[str, Any] = {"property": prop}
    if entry["family"] == catalog.FAMILY_TRIGGER and not catalog.trigger_carries_value(prop):
        return payload
    if len(entry["components"]) > 1:
        payload["values"] = [
            _dlg_float(f"cue_dlg_v{i}", float(c["neutral"]))
            for i, c in enumerate(entry["components"])
        ]
    else:
        payload["value"] = _cue_dlg_read_single_value(entry)
    ms = _dlg_float("cue_dlg_ms", 0.0)
    if ms > 0 and entry["ms"]:
        payload["ms"] = ms
    return payload


def _cue_dlg_read_single_value(entry: dict[str, Any]) -> float:
    """The single-value editor: an enum combo maps its option label to the index."""
    options = [str(o) for o in entry["options"] or []]
    if entry["family"] == catalog.FAMILY_ENUM and options:
        label = str(dpg.get_value("cue_dlg_value"))
        return float(options.index(label)) if label in options else 0.0
    return _dlg_float("cue_dlg_value", 0.0)


def _open_cue_row_dialog(mid: int, insert_after: int = -1, edit_index: int | None = None) -> None:
    """One add/edit dialog for a cue row (property / wait / mapper, e35s04).

    Add mode: ``insert_after`` is the row index the new row lands below
    (-1 appends at the end). Edit mode: ``edit_index`` prefills the fields and
    the confirm replaces that row in place, keeping its level. The dialog is
    kind-first: choosing a kind reveals only its fields.
    """
    mapping = mapper.find_mapping(mid)
    if mapping is None:
        return
    cue = mapping.get("cue") or mapper.fresh_cue()
    editing = edit_index is not None and 0 <= edit_index < len(cue["rows"])
    row = cue["rows"][edit_index] if editing else None
    kind = str((row or {}).get("kind", "property"))
    payload = (row or {}).get("payload") or {}
    prop = str(payload.get("property", "alpha"))
    value = float(payload.get("value", 0.0))
    values = payload.get("values")
    wait_ms = float(payload.get("ms", 500.0)) if kind == "wait" else 0.0
    prop_ms = float(payload.get("ms", 0.0)) if kind == "property" else 0.0
    ref = int(payload.get("mapping_id", 0))
    if dpg.does_item_exist("cue_dialog"):
        dpg.delete_item("cue_dialog")
    with dpg.window(
        label="Edit cue row" if editing else "Add cue row",
        tag="cue_dialog",
        modal=True,
        width=360,
        height=CUE_DLG_DEFAULT_HEIGHT,
        no_resize=True,
    ):
        help_label("Kind", "cue.kind", tag="cue_dlg_kind_label")
        dpg.add_combo(
            items=list(mapper.CUE_ROW_KINDS),
            default_value=kind,
            width=220,
            tag="cue_dlg_kind_combo",
            callback=on_cue_kind_change,
        )
        help_tooltip("cue_dlg_kind_combo", "cue.kind")
        with dpg.group(tag="cue_prop_fields", show=kind == "property"):
            help_label("Property", "cue.property", tag="cue_dlg_prop_label")
            dpg.add_combo(
                items=_cue_row_prop_candidates(),
                default_value=prop if _maybe_catalog_entry(prop) is not None else "alpha",
                width=260,
                tag="cue_dlg_prop_combo",
                callback=lambda s2, a2: _cue_dlg_render_values("cue_prop_values", str(a2)),
            )
            dpg.add_group(tag="cue_prop_values")
        with dpg.group(tag="cue_burst_fields", show=kind == "burst"):
            help_label("Rate burst", "cue.rate_burst", tag="cue_dlg_burst_label")
            dpg.add_combo(
                items=_cue_row_rate_candidates(),
                default_value=prop if _maybe_catalog_entry(prop) is not None else "turn",
                width=260,
                tag="cue_dlg_burst_combo",
                callback=lambda s2, a2: _cue_dlg_render_values(
                    "cue_burst_values", str(a2), ms_value=_dlg_float("cue_dlg_ms", 0.0)
                ),
            )
            dpg.add_group(tag="cue_burst_values")
        with dpg.group(tag="cue_wait_fields", show=kind == "wait"):
            help_label("Wait ms", "cue.wait", tag="cue_dlg_wait_label")
            help_tooltip(
                dpg.add_drag_float(
                    default_value=wait_ms,
                    width=140,
                    format="%.0f",
                    speed=10.0,
                    min_value=0.0,
                    max_value=60_000.0,
                    tag="cue_dlg_wait",
                ),
                "cue.wait",
            )
        with dpg.group(tag="cue_mapper_fields", show=kind == "mapper"):
            help_label("Mapper (button / cue list)", "cue.mapper", tag="cue_dlg_mapper_label")
            options = [
                _cue_mapper_option(int(m["id"]))
                for m in state.mapper_mappings
                if m.get("control") in ("button", "cue list")
            ]
            default_option = ""
            if options:
                if ref:
                    wanted = _cue_mapper_option(ref)
                    default_option = wanted if wanted in options else options[0]
                else:
                    default_option = options[0]
            dpg.add_combo(
                items=options,
                default_value=default_option,
                width=280,
                tag="cue_dlg_mapper_combo",
            )
            if not options:
                themed_text(
                    "No button / cue list mapping exists yet — add one in the Mapper first.",
                    slot="text_dim",
                    wrap=280,
                )
        dpg.add_separator()
        with dpg.group(horizontal=True):
            dpg.add_button(
                label="OK",
                width=120,
                callback=cue_dialog_confirm,
                user_data=(mid, insert_after, edit_index),
            )
            dpg.add_button(
                label="Cancel",
                width=120,
                callback=cue_dialog_cancel,
            )
    if kind == "property":
        prefill = values if isinstance(values, list) else [value]
        _cue_dlg_render_values("cue_prop_values", prop, prefill, ms_value=prop_ms)
    elif kind == "burst":
        prefill = values if isinstance(values, list) else [value]
        _cue_dlg_render_values("cue_burst_values", prop, prefill, ms_value=prop_ms)
    show_centered_window("cue_dialog")  # e55: dialogs open centered


def cue_dialog_confirm(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """Dialog OK: add a row below / replace the edited row through the model.

    Reads the widgets of the chosen kind (the dialog reveals only that kind's
    fields), keeps the level on edit, clamps through the model helpers and
    rebuilds the list. On invalid input the dialog STAYS open and the problem
    is logged to the Logs window — never a silent no-op.
    """
    mid, insert_after, edit_index = user_data
    mapping = mapper.find_mapping(mid)
    if mapping is None:
        return
    cue = mapping.get("cue") or mapper.fresh_cue()
    try:
        kind = str(dpg.get_value("cue_dlg_kind_combo"))
        if kind == "property":
            prop = str(dpg.get_value("cue_dlg_prop_combo"))
            if _maybe_catalog_entry(prop) is None:
                raise ValueError(f"unknown property {prop!r}")
            payload = _cue_dlg_read_payload(prop)  # e36s05: scalar/vector + ms
        elif kind == "wait":
            payload = {"ms": max(0.0, _dlg_float("cue_dlg_wait", 0.0))}
        elif kind == "burst":
            prop = str(dpg.get_value("cue_dlg_burst_combo"))
            if _maybe_catalog_entry(prop) is None:
                raise ValueError(f"unknown rate {prop!r}")
            payload = _cue_dlg_read_payload(prop)
            if float(payload.get("ms", 0.0)) <= 0.0:
                raise ValueError("burst rows need a duration (ms)")
        elif kind == "mapper":
            option = str(dpg.get_value("cue_dlg_mapper_combo"))
            mapping_id = int(option.split(":", 1)[0])
            if mapping_id < 1:
                raise ValueError(f"bad mapper reference {option!r}")
            payload = {"mapping_id": mapping_id}
        else:
            raise ValueError(f"unknown kind {kind!r}")
    except (TypeError, ValueError) as e:
        log_error("cue row dialog", f"nothing added: {e}")
        return  # keep the dialog open so the user can fix the input
    if edit_index is not None and 0 <= edit_index < len(cue["rows"]):
        level = int(cue["rows"][edit_index]["level"])
        row = mapper.add_cue_row(mapper.fresh_cue(), kind, payload, level=level)
        if row is None:
            log_error("cue row dialog", f"row rejected: {kind} {payload}")
            return
        cue["rows"][edit_index] = row
    else:
        position = insert_after if insert_after is not None else -1
        row = mapper.add_cue_row(mapper.fresh_cue(), kind, payload, level=0)
        if row is None:
            log_error("cue row dialog", f"row rejected: {kind} {payload}")
            return
        at = position + 1 if position >= 0 else len(cue["rows"])
        cue["rows"].insert(at, row)
    if dpg.does_item_exist("cue_dialog"):
        dpg.delete_item("cue_dialog")
    _safe_refresh_cue_rows(mid)


def cue_dialog_cancel(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """Dialog Cancel: close without touching the cue."""
    if dpg.does_item_exist("cue_dialog"):
        dpg.delete_item("cue_dialog")


def cue_editor_close(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """Close the cue-list editor (Close button / mapping removal, e35s05)."""
    mid = int(user_data or 0)
    if dpg.does_item_exist("cue_list_window"):
        dpg.delete_item("cue_list_window")
    if state.cue_editor_mapping_id == mid:
        state.cue_editor_mapping_id = None


def _drop_mapping_editor_and_runs(mapping_id: int) -> None:
    """e35s05: a removed mapping stops its cue run and closes its open editor."""
    cue.cue_stop(mapping_id)
    if state.cue_editor_mapping_id == mapping_id:
        cue_editor_close(None, None, mapping_id)


def _mapper_line_of(mapping: dict[str, Any]) -> int:
    """1-based Mapper line of a mapping's source (UAT e35): the window title
    names the line the cue belongs to, like the other mappings of that row."""
    targets = mapper.row_targets()
    try:
        return targets.index(str(mapping["target_id"])) + 1
    except ValueError:
        return 1


def open_cue_list_window(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """'Cue list...' on a cue-list card: open the mapping's cue-list editor (e35s04).

    The window edits the mapping's own cue (per-mapping, answer 2). UAT e35: it
    is titled 'Cue list mapper <N>' after the Mapper LINE the mapping belongs to
    — the cue always applies to that line's current source, so no Source/context
    header is shown: the level-gap box and the Run/Stop/Add-row buttons come
    first. Created on demand, non-modal. Unknown mapping ids are a no-op.
    """
    mid = int(user_data)
    mapping = mapper.find_mapping(mid)
    if mapping is None:
        return
    if dpg.does_item_exist("cue_list_window"):
        dpg.delete_item("cue_list_window")
    state.cue_editor_mapping_id = mid  # e35s05: which mapping this editor edits
    line_no = _mapper_line_of(mapping)
    cue = mapping.get("cue") or mapper.fresh_cue()
    with dpg.window(
        label=f"Cue list mapper {line_no}",
        tag="cue_list_window",
        width=520,
        height=420,
        show=False,
    ):
        with dpg.group(horizontal=True):
            themed_text("Level gap (ms)", slot="text_dim")
            help_tooltip(
                dpg.add_drag_float(
                    default_value=float(cue.get("gap_ms") or 0.0),
                    width=90,
                    format="%.0f",
                    speed=1.0,
                    min_value=0.0,
                    callback=on_cue_gap_change,
                    user_data=mid,
                    tag=f"cue_gap_{mid}",
                ),
                "cue.gap",
            )
        with dpg.group(horizontal=True):
            help_tooltip(
                dpg.add_button(
                    label="Run", callback=cue_window_run, user_data=mid, tag=f"cue_run_{mid}"
                ),
                "cue.run",
            )
            help_tooltip(
                dpg.add_button(
                    label="Stop", callback=cue_window_stop, user_data=mid, tag=f"cue_stop_{mid}"
                ),
                "cue.stop",
            )
            help_tooltip(
                dpg.add_button(
                    label="Add row",
                    callback=cue_window_add_dialog,
                    user_data=mid,
                    tag=f"cue_add_row_{mid}",
                ),
                "cue.add_row",
            )
            dpg.add_button(
                label="Close",
                width=90,
                callback=cue_editor_close,
                user_data=mid,
            )
        dpg.add_separator()
        with dpg.child_window(tag="cue_rows_group", width=0, height=180, border=True):
            _render_cue_rows(mid)
    show_centered_window("cue_list_window")  # e55: the cue editor opens centered


def _reapply_leds_after_controller_connect() -> None:
    """A (re)connected controller shows the active modes and state LEDs (e53).

    The MIDI worker re-runs `controller_connect` (which re-sends the LED handshake
    SysEx) when a controller reappears after a power cycle; this puts the current
    LED truth back on the device. Runs on the main thread (it reads `state`).
    """
    reapply_mode_leds()
    refresh_binding_leds()


def midi_control_loop() -> None:
    """MIDI control worker (e14s02): poll every controller input port, mapping messages,
    push executions to the main thread via ui_task_queue (HIGH-1 — no direct dpg calls).

    BUG-2026-10-16b: the body used to run bare inside the loop. One uncaught exception
    (the UI thread resizing the controller list while this thread iterated it) killed the
    worker FOR GOOD, and a thread dying is invisible in the app: MIDI INPUT stops, while
    the LED output — opened on the main thread — keeps working. The operator then sees a
    device that lights up and answers nothing, and the I/O Monitor shows NOTHING because
    no message is ever read. Every pass is now guarded and logged.
    """
    try:
        import mido
    except ImportError:
        return
    open_ports: dict[str, Any] = {}
    # BUG-2026-09-07: last-failure timestamps per port gate the open retry — a
    # failing open can leak an ALSA sequencer client, so a dead ALSA is never
    # hammered every tick (that saturation silently killed controller detection).
    open_fail_at: dict[str, float] = {}
    last_rescan = 0.0
    while True:
        if not state.midi_enabled:
            time.sleep(0.2)
            continue
        try:
            last_rescan = _midi_control_tick(mido, open_ports, open_fail_at, last_rescan)
        except Exception as e:  # a worker thread must never die (BLE001, per-file ignore)
            log_error("MIDI", f"control loop: {e}")
            time.sleep(MIDI_OPEN_RETRY_COOLDOWN_SECONDS)
        time.sleep(0.002)


def _midi_control_tick(
    mido: Any,
    open_ports: dict[str, Any],
    open_fail_at: dict[str, float],
    last_rescan: float,
) -> float:
    """ONE pass of the MIDI input worker; returns the new rescan stamp (e78).

    The controller list is SNAPSHOTTED: the MIDI window appends/removes controllers on
    the main thread, and iterating the live list raised "list changed size during
    iteration" — the exception that used to kill the loop (see `midi_control_loop`).
    """
    now = time.monotonic()
    # e53: a powered-off controller can leave a stale open port (`iter_pending`
    # returns nothing instead of raising), so the LED handshake would never be
    # re-sent until a VJmix restart. Drop the ports that are gone; the loop
    # below reopens them (and re-runs controller_connect) when they return.
    if now - last_rescan >= MIDI_PORT_RESCAN_SECONDS:
        last_rescan = now
        try:
            live: set[str] | None = set(mido.get_input_names())
        except Exception as e:
            live = None
            log_error("MIDI", f"port rescan: {e}")
        if live is not None:
            for stale in stale_ports(list(open_ports), live):
                _close_midi_input(open_ports.pop(stale, None))
                controller = find_controller_by_port(stale)
                if controller is not None:
                    controller_disconnect(controller)
    controllers = list(midi_controllers)  # snapshot: the UI thread mutates this list
    wanted = {str(c["port"]) for c in controllers if c.get("port")}
    for port_name in [p for p in open_ports if p not in wanted]:
        _close_midi_input(open_ports.pop(port_name))
    for controller in controllers:
        port_name = str(controller.get("port") or "")
        if not port_name:
            continue
        if port_name not in open_ports:
            if not midi_open_retry_due(open_fail_at.get(port_name), now):
                continue  # cooldown: stay quiet on a failing port
            try:
                open_ports[port_name] = mido.open_input(port_name)
                open_fail_at.pop(port_name, None)
                controller_connect(controller, mido)  # e14s02: LED output + grid bindings
                ui_task(_reapply_leds_after_controller_connect)  # e53: LEDs show the truth
                append_log("MIDI", f"Control listening on {port_name}")
            except Exception as e:
                open_fail_at[port_name] = time.monotonic()
                log_error("MIDI", str(e))
                continue
        try:
            for msg in open_ports[port_name].iter_pending():
                handle_midi_message(msg, port_name)
        except Exception as e:
            open_fail_at[port_name] = time.monotonic()
            log_error("MIDI", str(e))
            _close_midi_input(open_ports.pop(port_name, None))
    return last_rescan


# ---------- e09s03: Novation Launchpad adapter ----------
# MULTI-CONTROLLER RUNTIME (e14s02) — profile-driven controllers, one designated
# sequencer grid; the legacy launchpad_* path stays until e14s04 removes it.
# ==============================================================================
# Persisted shape: {port, profile_id, role ("grid"|None), bindings} + runtime
# fields output (mido out port) and auto_bindings (grid bindings, never persisted).
# Semantic grid-LED names (mirror/flash call sites) mapped per profile palette.


def midi_clock_loop() -> None:
    """Listen for MIDI clock (0xF8, 24 pulses/beat) and fire the sequencer beat in MIDI mode.

    The clock listens on cfg clock_source when set, else the first available input;
    without any port it logs once and idles so the app keeps running.
    """
    try:
        import mido
    except ImportError:
        return
    while True:
        port_name = _clock_port_name()
        if not port_name:
            # BUG-2026-09-07: a no-input idle loop must not re-enumerate every few
            # seconds — each scan on a failing ALSA can leak a sequencer client.
            time.sleep(MIDI_OPEN_RETRY_COOLDOWN_SECONDS)
            continue
        try:
            with mido.open_input(port_name) as port:
                append_log("MIDI", f"Clock listening on {port_name}")
                while True:
                    for msg in port.iter_pending():
                        if msg.type == "clock":
                            state.midi_pulses += 1
                            if state.midi_pulses >= MIDI_CLOCK_PULSES_PER_BEAT:
                                state.midi_pulses = 0
                                flash_led("led_midi")
                                if state.beat_source == BEAT_SOURCE_MIDI and state.is_playing:
                                    sync_event_beat.set()
                                    deliver_event_beat()
                    time.sleep(0.001)
        except Exception as e:
            log_error("MIDI", str(e))
            time.sleep(MIDI_OPEN_RETRY_COOLDOWN_SECONDS)


# ---------- e26: Leap Motion worker ----------
# The library's OWN auto-poll thread (auto_poll=True + a Listener) owns the LeapC
# handshake and event loop — the official example pattern. This daemon thread
# only manages the lifecycle: lazy-import the external 'leap' package (absolute
# import — the suite/CI may not have it), open/keep/reconnect the connection
# while state.leap_enabled, close when disabled. Missing library or service
# degrades to status 'missing'/'disconnected' with slow retries and never
# crashes the app (CONVENTIONS § Defensive Code). Tracking frames normalize
# into state.leap_values under state.leap_lock; UI/status updates go through
# the queues (HIGH-1: no dpg from any thread here).


# BUG-2026-09-18T212400: worker-loop timings (named constants, L-6). The idle and
# retry sleeps are short; the stale limit in vjmixapp/leap.py must cover the
# longest of them (the missing-library retry).
LEAP_IDLE_SLEEP_S: float = 0.2
LEAP_MISSING_SLEEP_S: float = 5.0
LEAP_RETRY_SLEEP_S: float = 2.0
LEAP_KEEPALIVE_SLEEP_S: float = 0.5
LEAP_WORKER_GUARD_SLEEP_S: float = 1.0


def _leap_detach(connection: Any) -> None:
    """Tear a LeapC connection down OFF the worker thread (BUG-2026-09-18T212400).

    The library's `disconnect()` joins its poll thread with NO timeout, and that
    thread sits inside a native `LeapPollConnection` call: on a wedged service the
    join would block this worker forever, which is one of the ways the engine used
    to become unrecoverable. The teardown therefore runs in a throwaway daemon
    thread and the caller moves on; the binding destroys the native connection in
    `__del__` once the reference is dropped.
    """
    if connection is None:
        return

    def _close() -> None:
        with contextlib.suppress(Exception):
            connection.disconnect()

    threading.Thread(target=_close, name="leap-detach", daemon=True).start()


def _leap_lib() -> Any:
    """The external leap package, imported lazily; None when unavailable (e26s01)."""
    try:
        import leap  # type: ignore[import-not-found]

        return leap
    except Exception:
        return None


def _leap_viz_capture_geometry(event: Any) -> list[dict[str, Any]]:
    """Hand-geometry dicts for one tracking event (e26s04, poll thread).

    Called synchronously while the hand data is valid; an empty list means no
    hand is in view (the skeleton panel shows its waiting label).
    """
    return [leap.viz_hand_geometry(h) for h in event.hands or []]


def _leap_viz_copy_ir(img: Any) -> Any:
    """Synchronous grayscale copy of one IR image (e26s04, poll thread).

    The C buffer behind the Image wrapper is only valid until the next poll, so
    the copy happens inside the event callback (reference example's UAF note).
    leapc_cffi is imported lazily here: rig-only, the suite never runs this.
    """
    props = img.c_data.properties
    w, h, bpp = int(props.width), int(props.height), int(props.bpp)
    if w == 0 or h == 0 or bpp != 1:
        raise ValueError(f"unsupported IR image {w}x{h} bpp={bpp}")
    import leapc_cffi  # type: ignore[import-not-found]

    ptr = leapc_cffi.ffi.cast("uint8_t*", img.c_data.data) + img.c_data.offset
    buf = leapc_cffi.ffi.buffer(ptr, w * h * bpp)
    return np.frombuffer(buf, dtype=np.uint8).reshape((h, w)).copy()


def _leap_viz_publish_if_due(now: float) -> None:
    """Compose + publish one visualizer frame at the rate cap (e26s04, poll thread).

    Reads the latest IR copy + hand geometry by reference swap (both are only
    ever replaced, never mutated), composes OUTSIDE the lock, then publishes
    under state.leap_lock (frame swap + seq bump + render timestamp). A compose
    failure degrades to a log line and a cleared frame — never a crash.
    """
    if not (state.leap_enabled and state.leap_visualizer):
        return
    with state.leap_lock:
        last = state.leap_viz_last_render
    if not leap.viz_render_due(now, last):
        return
    with state.leap_lock:
        ir = state.leap_viz_ir
        hands = state.leap_viz_hands
    try:
        frame = leap.compose_viz_frame(ir, hands)
    except Exception as e:
        log_error("Leap", f"viz compose: {e}")
        with state.leap_lock:
            state.leap_viz_frame = None
            state.leap_viz_ir = None
            state.leap_viz_hands = None
        return
    with state.leap_lock:
        state.leap_viz_frame = frame
        state.leap_viz_seq += 1
        state.leap_viz_last_render = now


def _leap_set_images_policy(connection: Any, lib: Any, on: bool) -> None:
    """Set/clear the LeapC Images policy on the LIVE connection (e26s04).

    Off = the device does not stream IR, so the disabled visualizer costs
    nothing. set_policy_flags is a blocking call-and-wait whose Policy event is
    delivered by the library's auto-poll thread; a failure degrades to a log
    line, never a crash (BLE001 posture).
    """
    try:
        # The binding exposes PolicyFlag under leap.enums (not the package root
        # — live-verified 2026-09-03: lib.PolicyFlag raises AttributeError and
        # the IR stream silently never starts).
        images = lib.enums.PolicyFlag.Images
        if on:
            connection.set_policy_flags(flags_to_set=[images])
            append_log("Leap", "visualizer on (IR stream requested)")
        else:
            connection.set_policy_flags(flags_to_clear=[images])
            append_log("Leap", "visualizer off (IR stream stopped)")
    except Exception as e:
        log_error("Leap", f"images policy: {e}")


def _leap_listener(lib: Any) -> Any:
    """A Listener whose callbacks run on the library's auto-poll thread.

    The callbacks only touch state (under leap_lock) and the log queues — no
    dpg (HIGH-1). Poll errors arrive via on_error (the library reports timeouts
    and handshake noise the same way); only real failures flip the status.
    """

    class _LeapTrackingListener(lib.Listener):
        def on_tracking_event(self, event):  # type: ignore[no-untyped-def]
            snapshot = normalize_tracking_event(event)
            with state.leap_lock:
                state.leap_values.clear()
                state.leap_values.update(snapshot)
            state.leap_status = "tracking"
            state.leap_framerate = float(event.framerate)  # e48: diagnostics line
            state.leap_last_frame = time.time()  # e26s05: watchdog heartbeat
            if state.leap_stall_count:
                # e26s05: a frame after an escalation = the stream is back.
                state.leap_stall_count = 0
            drive_leap_mappings(snapshot)  # e26s03: push leap-bound mappings
            # e26s04: while the visualizer is on, capture the hand geometry and
            # publish one rate-capped composite (the poll thread is the only
            # writer of the visualizer snapshot; the main tick only uploads the
            # finished texture).
            if state.leap_visualizer:
                hands = _leap_viz_capture_geometry(event)
                with state.leap_lock:
                    state.leap_viz_hands = hands
                _leap_viz_publish_if_due(time.time())

        def on_image_event(self, event):  # type: ignore[no-untyped-def]
            # IR frames arrive ONLY while the Images policy is set, i.e. while
            # the visualizer is on — the copy must happen synchronously (the C
            # buffer is valid only until the next poll, same UAF as tracking).
            if not state.leap_visualizer:
                return
            try:
                ir = _leap_viz_copy_ir(event.image[0])
            except Exception as e:
                log_error("Leap", f"viz image: {e}")
                return
            with state.leap_lock:
                state.leap_viz_ir = ir
            _leap_viz_publish_if_due(time.time())

        def on_connection_lost_event(self, event):  # type: ignore[no-untyped-def]
            state.leap_status = "disconnected"

        def on_device_lost_event(self, event):  # type: ignore[no-untyped-def]
            state.leap_status = "disconnected"

        def on_error(self, error):  # type: ignore[no-untyped-def]
            if type(error).__name__ in ("LeapTimeoutError", "LeapNotConnectedError"):
                return  # idle poll / handshake in progress: not failures
            state.leap_status = "disconnected"
            log_error("Leap", f"poll: {error}")

    return _LeapTrackingListener()


def _leap_backoff_sleep(seconds: float) -> None:
    """Interruptible backoff after a stall-forced reconnect (e26s05).

    Sleeps in short steps so an engine-off during the backoff reacts within a
    second instead of after the full escalated wait.
    """
    deadline = time.time() + seconds
    while state.leap_enabled and time.time() < deadline:
        time.sleep(min(1.0, deadline - time.time()))


def _leap_worker_iteration() -> None:
    """One Leap-worker lifecycle pass (BUG-2026-09-18T212400).

    Extracted from leap_control_loop so the loop can guard it: this body may
    raise (a missing library, a wedged service, a library bug) and the guard keeps
    the thread alive. The library's own poll thread (auto_poll=True) owns the
    LeapC handshake and event loop — the official example pattern; our listener
    normalizes tracking frames into state.leap_values.
    """
    state.leap_worker_tick = time.time()  # liveness heartbeat for the window
    if not state.leap_enabled:
        time.sleep(LEAP_IDLE_SLEEP_S)
        return
    lib = _leap_lib()
    if lib is None:
        if state.leap_status != "missing":
            append_log("Leap", "library/service not available (leapc-python-api + Gemini)")
        state.leap_status = "missing"
        time.sleep(LEAP_MISSING_SLEEP_S)
        return
    # The generation captured BEFORE the connect: a restart clicked while this
    # connection is being built is honoured on the next pass (the counter moved).
    generation = state.leap_generation
    connection: Any = None
    try:
        connection = lib.Connection()
        connection.add_listener(_leap_listener(lib))
        # NOTE: connection.open() is a @contextmanager — calling it without
        # `with` is a silent no-op. connect() is the plain-method equivalent
        # that keeps the connection open for this worker's keep-alive loop.
        connection.connect(auto_poll=True, timeout=3)
        connection.set_tracking_mode(lib.TrackingMode.Desktop)
        state.leap_status = "connected"
        state.leap_last_frame = time.time()  # e26s05: silence window starts fresh
        state.leap_worker_tick = time.time()
        append_log("Leap", "connected")
        # e26s04: a persisted visualizer toggle asks for IR as soon as the
        # (re)connection is up; afterwards the keep-alive below follows it.
        if state.leap_visualizer:
            _leap_set_images_policy(connection, lib, True)
    except Exception as e:
        log_error("Leap", f"connect: {e}")
        _leap_detach(connection)
        state.leap_status = "disconnected"
        time.sleep(LEAP_RETRY_SLEEP_S)
        return
    # Keep the connection open while enabled; a lost service/device flips the
    # status to disconnected (listener) so this loop exits and reconnects.
    # The keep-alive also watches the visualizer toggle and sets/clears the
    # LeapC Images policy on the live connection (no reconnect needed), the
    # e26s05 watchdog (the service can wedge silently — evaluator frozen while the
    # process + USB stay alive — with NO events arriving, so after
    # LEAP_STALL_TIMEOUT of tracking silence this loop forces a reconnect) and the
    # BUG-2026-09-18T212400 restart request (a generation bump).
    viz_policy = bool(state.leap_visualizer)
    stall_exit = False
    while state.leap_enabled and state.leap_status != "disconnected":
        state.leap_worker_tick = time.time()
        if state.leap_generation != generation:
            append_log("Leap", "restart requested - rebuilding the connection")
            break
        if leap.stall_detected(time.time(), state.leap_last_frame):
            stall_exit = True
            state.leap_stall_count += 1
            state.leap_status = "disconnected"
            if state.leap_stall_count == leap.LEAP_STALL_ESCALATION_COUNT:
                append_log(
                    "Leap",
                    "tracking keeps stalling - press Restart engine, or restart "
                    "the hand-tracking service / replug the device",
                )
            elif state.leap_stall_count < leap.LEAP_STALL_ESCALATION_COUNT:
                append_log(
                    "Leap",
                    "tracking stalled (no frames for "
                    f"{leap.LEAP_STALL_TIMEOUT:.0f}s) - reconnecting "
                    f"(attempt {state.leap_stall_count})",
                )
            break
        viz_now = bool(state.leap_visualizer)
        if viz_now != viz_policy:
            viz_policy = viz_now
            _leap_set_images_policy(connection, lib, viz_now)
        time.sleep(LEAP_KEEPALIVE_SLEEP_S)
    _leap_detach(connection)
    if stall_exit:
        # a wedged service is not hot-looped: back off (fast, then slow),
        # interruptibly so an engine-off during the backoff reacts quickly.
        _leap_backoff_sleep(leap.stall_retry_wait(state.leap_stall_count))


def leap_control_loop() -> None:
    """Leap Motion worker (e26s01): keep one auto-polling connection while enabled.

    BUG-2026-09-18T212400: the WHOLE lifecycle lives behind this guard. The body
    used to run unguarded, so any exception outside the connect block killed the
    thread silently — and because the Enable toggle only flips state.leap_enabled,
    nobody was left to read it and the engine could never come back without an app
    restart. A worker thread must never die (CONVENTIONS, defensive posture).
    """
    while True:
        try:
            _leap_worker_iteration()
        except Exception as e:
            log_error("Leap", f"worker: {e}")
            state.leap_worker_tick = time.time()
            time.sleep(LEAP_WORKER_GUARD_SLEEP_S)


def show_settings_window(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """Open the general settings window (it hosts ALL of viOSC too, e58s03)."""
    dpg.show_item("settings_window")
    dpg.focus_item("settings_window")  # e17: a shown window must come to the front
    load_viosc_config()  # populate the OSC Configuration section on open


def show_logs_window(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """Open the OSC logs window from the top menubar (Show > Logs).

    The multiline log follows the window size when shown (e38 UAT request:
    selectable/copyable log).
    """
    dpg.show_item("logs_window")
    dpg.focus_item("logs_window")  # e17: a shown window must come to the front
    if dpg.does_item_exist("osc_log_text"):
        w = max(300, dpg.get_item_width("logs_window") - 20)
        h = max(100, dpg.get_item_height("logs_window") - 42)
        dpg.configure_item("osc_log_text", width=w, height=h)


def centered_window_pos(
    viewport_w: int, viewport_h: int, window_w: int, window_h: int
) -> tuple[int, int]:
    """Top-left position centering a window of the given size on a viewport.

    Pure math (no dpg): each axis is (viewport - window) // 2, clamped at >= 0 so a window
    larger than the viewport never gets a negative offset.
    """
    return (max(0, (viewport_w - window_w) // 2), max(0, (viewport_h - window_h) // 2))


# e55: the import-time WORKSPACE windows. They center once, when they first
# become visible (a project layout, applied earlier, or the user's own move wins).
FIRST_OPEN_CENTERED_WINDOWS: tuple[str, ...] = (
    "sequencer_window",
    "audio_window",
    "vimix_media_window",
    "logs_window",
    "text_window",
    "mapper_window",
    "file_manager_window",
    SOURCES_DATA_WINDOW_TAG,  # e74s03: the raw viOSC table window
)

# Config panels: no workspace meaning, re-centered on EVERY open so a viewport
# resize is always honoured (the live size is read at open time, never a stale
# boot size). Transient dialogs center through `show_centered_window`.
ALWAYS_CENTERED_WINDOWS: tuple[str, ...] = (
    "settings_window",
    "midi_window",
    "leap_window",
    MAP_ACTIONS_WINDOW_TAG,
)


def first_open_pos(width: int, height: int) -> tuple[int, int]:
    """Top-left that centers a window of the given size on the viewport (e55).

    The top is clamped below the toolbar strip, like `apply_window_layout`.
    """
    x, y = centered_window_pos(
        int(dpg.get_viewport_client_width() or 0),
        int(dpg.get_viewport_client_height() or 0),
        int(width),
        int(height),
    )
    return (x, max(y, TOOLBAR_BAR_H))


def center_window_on_viewport(tag: str, *, force: bool = False) -> None:
    """Center an OPEN window on the CURRENT viewport size (e55).

    No-op when the window does not exist, its geometry is not measurable yet, or
    (unless ``force``) it was already positioned by a project layout or an earlier
    centering. The live viewport size is read here, so a resize is honoured.
    """
    if not force and tag in _positioned_windows:
        return
    if not dpg.does_item_exist(tag):
        return
    width = int(dpg.get_item_width(tag) or 0)
    height = int(dpg.get_item_height(tag) or 0)
    viewport_w = int(dpg.get_viewport_client_width() or 0)
    viewport_h = int(dpg.get_viewport_client_height() or 0)
    if width <= 0 or height <= 0 or viewport_w <= 0 or viewport_h <= 0:
        return
    dpg.set_item_pos(tag, first_open_pos(width, height))
    _positioned_windows.add(tag)


def show_centered_window(tag: str) -> None:
    """Show a freshly (re)created window centered on the current viewport (e55).

    A rebuilt item reuses its tag, so centering is forced: a dialog that opens a
    second time centers again, on the viewport size of that moment.
    """
    _positioned_windows.discard(tag)
    center_window_on_viewport(tag, force=True)
    dpg.show_item(tag)


# Shown state of the previous frame, so centering fires on the hidden -> shown
# transition and reads the live viewport size then (BUG rig UAT: a stale boot
# size left a window at the old center after a resize).
_window_was_shown: dict[str, bool] = {}


def _center_window_on_open(tag: str, *, force: bool) -> None:
    """Center a window on its hidden -> shown transition (once, or every time)."""
    shown = bool(dpg.does_item_exist(tag) and dpg.is_item_shown(tag))
    was = _window_was_shown.get(tag, False)
    _window_was_shown[tag] = shown
    if shown and not was:
        center_window_on_viewport(tag, force=force)


def tick_first_open_centering() -> None:
    """Center a window when it opens, using the CURRENT viewport size (e55).

    Workspace windows center once (a project layout or the user's own move wins);
    config panels re-center on every open. A window that has never been visible
    keeps its centering pending, so a resize before its first open is honoured.
    """
    for tag in FIRST_OPEN_CENTERED_WINDOWS:
        if tag not in _positioned_windows:  # once: a layout or an earlier center wins
            _center_window_on_open(tag, force=False)
    for tag in ALWAYS_CENTERED_WINDOWS:
        _center_window_on_open(tag, force=True)


def show_help_window(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """Open the About window from the menubar, re-centered on the viewport."""
    dpg.set_item_pos(
        "help_window",
        centered_window_pos(
            dpg.get_viewport_width(),
            dpg.get_viewport_height(),
            dpg.get_item_width("help_window"),
            dpg.get_item_height("help_window"),
        ),
    )
    dpg.show_item("help_window")
    dpg.focus_item("help_window")  # e17: a shown window must come to the front


# ---------- e17: window switching (Windows-menu list + Ctrl+Tab) ----------
def _window_menu_entries() -> list[tuple[str, str]]:
    """Windows in Ctrl+Tab switching order: (tag, label).

    Every window icon in the bar is a switching target, in the bar's own order
    (user decision 2026-09-19), so adding an icon adds it to the cycle without
    touching this list. The transient preview joins while it is active. Only the
    OPEN windows are actually cycled (the shown filter lives in on_cycle_window).

    `_toolbar_window_items` is defined later in the module; this forward
    reference is resolved at call time, never at import.
    """
    entries = [
        (target, label) for _kind, target, _glyph, label, _shortcut in _toolbar_window_items()
    ]
    if state.preview_active is not None:  # the preview window exists while a preview is active
        entries.append((PREVIEW_WINDOW_TAG, "Preview"))
    return entries


# The app's windows (BUG-2026-09-01T194500). Opening a menu makes DPG report the
# menu itself as the active window (mvContainers.cpp: menu draw sets
# GContext->activeWindow), so the focus track must accept ONLY real windows.
_FOCUS_TRACKED_WINDOWS: tuple[str, ...] = (
    "sequencer_window",
    "sequencer_b_window",  # e68: a toolbar toggle target, so Ctrl+Tab reaches it once it exists
    "audio_window",
    "vimix_media_window",
    "logs_window",
    "text_window",
    "shader_window",  # e61s03
    "mapper_window",
    # BUG-2026-09-19T003052: both icon windows were missing here, so focusing
    # them left the previously focused icon wearing the full accent.
    "io_monitor_window",
    "file_manager_window",
    "settings_window",
    "midi_window",
    "leap_window",
    "help_window",
)


def _is_tracked_window(tag: Any) -> bool:
    """True when the active item is one of the app's windows, not a menu/popup."""
    s = str(tag)
    return s in _FOCUS_TRACKED_WINDOWS


def _active_window_tag(tag: Any) -> str | None:
    """Resolve the active item to its app window (BUG-2026-09-01T194500).

    DPG reports arbitrary widgets as the active window (verified live: clicking
    a step pad makes get_active_window() return the pad tag, e.g. 'seq_cell_2_4')
    and the open menu itself while a menu is shown. Walk up the item tree to the
    first tracked window; return None for menus/popups/unknowns.
    """
    item = tag
    for _ in range(64):  # bounded parent walk
        if item is None:
            return None
        s = str(item)
        if _is_tracked_window(s):
            return s
        # Real DPG raises get_item_info on stale/unknown ids (boot returns 0)
        # — bail out before the walk instead of crashing.
        if not dpg.does_item_exist(item):
            return None
        parent = dpg.get_item_parent(item)
        if parent is None or str(parent) == s:
            return None
        item = parent
    return None


_window_menu_sig: tuple[Any, ...] | None = None  # last (active, monitor tags) seen

# BUG-2026-09-19T005453: Dear ImGui's built-in Ctrl+Tab panel lists every
# visible root window and renders an unlabeled one as "(Untitled)". The bar is
# the app's only unlabeled root window, so it showed up in that panel and could
# be selected. ImGui's own filter is ImGuiWindowFlags_NoNavFocus, which
# DearPyGui 2.3.1 does not expose (add_window/configure_item reject it, verified),
# so while the panel is up the bar is simply NOT SUBMITTED — ImGui drops a window
# absent from the previous frame (verified on a real display: a show=False window
# is never listed) — and it is restored the moment Ctrl is released. The hide
# waits just under ImGui's own 0.15 s panel delay, so a quick Ctrl+Tab tap never
# blinks the bar.
TOOLBAR_CTRL_TAB_HIDE_DELAY_SECONDS = 0.12
_toolbar_ctrl_tab_held_since: float | None = None
_toolbar_ctrl_tab_hidden = False


def _keep_toolbar_out_of_window_switch(now: float | None = None) -> None:
    """Keep the bar out of ImGui's Ctrl+Tab panel (BUG-2026-09-19T005453).

    The bar is hidden while the panel is up and restored on Ctrl release. `now`
    is injectable for the tests; production calls it with no argument.
    """
    global _toolbar_ctrl_tab_held_since, _toolbar_ctrl_tab_hidden
    if not dpg.is_key_down(dpg.mvKey_ModCtrl):
        _toolbar_ctrl_tab_held_since = None
        if _toolbar_ctrl_tab_hidden:
            _toolbar_ctrl_tab_hidden = False
            if dpg.does_item_exist(TOOLBAR_BAR_TAG):
                dpg.show_item(TOOLBAR_BAR_TAG)
                reposition_toolbar()
            refresh_mode_chip()  # e52s06: the strip restores its own visibility
        return
    if not dpg.is_key_down(dpg.mvKey_Tab):
        return  # Ctrl held on its own: no window switching
    moment = time.monotonic() if now is None else now
    if _toolbar_ctrl_tab_held_since is None:
        _toolbar_ctrl_tab_held_since = moment
        return
    if _toolbar_ctrl_tab_hidden:
        return
    if moment - _toolbar_ctrl_tab_held_since < TOOLBAR_CTRL_TAB_HIDE_DELAY_SECONDS:
        return
    if dpg.does_item_exist(TOOLBAR_BAR_TAG):
        dpg.hide_item(TOOLBAR_BAR_TAG)
        _toolbar_ctrl_tab_hidden = True
    if dpg.does_item_exist(MODE_BADGES_WINDOW_TAG):  # e52s06: keep the strip out too
        dpg.hide_item(MODE_BADGES_WINDOW_TAG)


def tick_toolbar() -> None:
    """Per-frame gate: repaint the toolbar highlight only when the state changed.

    The signature is (tracked current window, shown window tags of the BAR's
    window items — BUG-2026-09-19T003052: the Ctrl+Tab list is a subset, so using
    it left 6 icons stale); anything else the bar shows is static. We remember the
    last focused window: get_active_window()
    reports arbitrary widgets (step pads, combos) and the open menu itself, so
    the track resolves the active item up to its app window and never clears on
    a menu/popup/None result (BUG-2026-09-01T194500).
    """
    global _window_menu_sig
    _keep_toolbar_out_of_window_switch()
    active = dpg.get_active_window()
    window = _active_window_tag(active)
    if window is not None:
        state.current_window = window
    sig = (state.current_window, _toolbar_shown_signature(), tuple(_toolbar_color("text", 255)))
    if sig != _window_menu_sig:
        _window_menu_sig = sig
        refresh_toolbar_icons()
    # e46s01: keep the toolbar anchored to the top-right on resize / width changes.
    global _toolbar_geom_sig
    geometry = (
        int(dpg.get_item_width(TOOLBAR_BAR_TAG) or 0),
        int(dpg.get_viewport_client_width() or 0),
    )
    if geometry != _toolbar_geom_sig:
        _toolbar_geom_sig = geometry
        reposition_toolbar()


def switch_to_window(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """Show + focus a window (Windows-menu list click, Ctrl+Tab target)."""
    tag = user_data
    if dpg.does_item_exist(tag):
        dpg.show_item(tag)
        dpg.focus_item(tag)
        state.current_window = tag


def on_cycle_window(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """Ctrl+Tab / Ctrl+Shift+Tab: cycle through the OPEN windows, in bar order.

    Every window icon is a stop (user decision 2026-09-19) and a hidden window
    is skipped, so the cycle visits exactly the windows that are open. DPG 2.3.1
    key handlers have no modifier support, so the wrapper checks the modifier
    keys itself; Tab keeps its normal role while an input is focused. The anchor
    is the tracked current window (not DPG get_active_window, which is None while
    the menu bar has focus — BUG-2026-09-01T194500).
    """
    if not dpg.is_key_down(dpg.mvKey_ModCtrl) or _any_input_focused():
        return
    forward = not dpg.is_key_down(dpg.mvKey_ModShift)
    entries = _window_menu_entries()
    if not entries:
        return
    active = state.current_window
    try:
        idx = next(i for i, (tag, _) in enumerate(entries) if str(tag) == str(active))
    except StopIteration:
        idx = -1
    step = 1 if forward else -1
    for _ in range(len(entries)):
        idx = (idx + step) % len(entries)
        tag, _ = entries[idx]
        if dpg.does_item_exist(tag) and dpg.is_item_shown(tag):
            switch_to_window(None, None, tag)
            return


def open_github(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """Open the VJmix project repository in the default browser (Info window link)."""
    _open_in_browser(GITHUB_URL)


def open_donation(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """Open the donation page in the default browser (Info window, e83)."""
    _open_in_browser(DONATE_URL)


def _open_in_browser(url: str) -> None:
    """One place that opens an external URL; a failure is logged, never raised."""
    try:
        import webbrowser

        webbrowser.open(url)
    except Exception as e:
        log_error("Help", str(e))


def callback_resync(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    resync_sequencer(0)


def nudge_sequencer(index: int, delta: float) -> None:
    """Nudge ONE sequencer's next beat (e67s04): its own `nudge`, consumed by its own interval."""
    state.sequencer(index)["nudge"] += delta


def callback_nudge_backward(
    sender: Any = None, app_data: Any = None, user_data: Any = None
) -> None:
    nudge_sequencer(0, SEQ_NUDGE_STEP)


def callback_nudge_forward(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    nudge_sequencer(0, -SEQ_NUDGE_STEP)


def on_sequencer_nudge(sender: Any, app_data: Any, user_data: Any) -> None:
    """A transport nudge of ONE instance: `user_data` carries `(index, delta)` (e67s04)."""
    index, delta = user_data
    nudge_sequencer(index, delta)


def on_sequencer_resync(sender: Any, app_data: Any, user_data: Any) -> None:
    """RESYNC of ONE instance (e67s04): its own playhead and its own deadline reset."""
    index = user_data if isinstance(user_data, int) else 0
    resync_sequencer(index)


def _show_band_overlay(
    band_id: int, f_start: float, f_end: float, l_min: float, l_max: float
) -> None:
    """Show one band's rectangle and its number at the rect's top-left inside corner."""
    x0 = f_start * SPEC_DRAWLIST_W
    y0 = (1 - l_max) * SPEC_DRAWLIST_H
    dpg.configure_item(
        f"band{band_id}_rect",
        pmin=(x0, y0),
        pmax=(f_end * SPEC_DRAWLIST_W, (1 - l_min) * SPEC_DRAWLIST_H),
        show=True,
    )
    dpg.configure_item(
        f"band{band_id}_label",
        pos=(x0 + BAND_LABEL_PAD_PX, y0 + BAND_LABEL_PAD_PX),
        show=True,
    )


def refresh_band_value(bars: np.ndarray, band_id: int) -> None:
    """Recompute one band's level from its sliders; update text and overlay (main thread)."""
    if not bands_enabled[band_id]:
        return
    f_start = float(dpg.get_value(f"band{band_id}_start"))
    f_end = float(dpg.get_value(f"band{band_id}_end"))
    l_min = float(dpg.get_value(f"band{band_id}_min"))
    l_max = float(dpg.get_value(f"band{band_id}_max"))
    value = band_value_from_bars(bars, f_start, f_end, l_min, l_max, agg="blend")
    _set_band_variable(band_id, value)
    drive_mapper_band(band_id, value)  # e18: mapped controls follow the band
    # Beat trigger: any band rising to the threshold flashes its LED; only band 1 can
    # drive the sequencer beat (edge only) — bands 2/3 stay spectrum-only (e10s07)
    if value >= BAND_BEAT_THRESHOLD and band_prev_values[band_id] < BAND_BEAT_THRESHOLD:
        flash_led(f"led_band{band_id}")
        if band_id == 1 and state.beat_source == BEAT_SOURCE_BAND1:
            sync_event_beat.set()
            deliver_event_beat()
    band_prev_values[band_id] = value
    dpg.set_value(f"band{band_id}_value_text", f"{value:.2f}")
    _show_band_overlay(band_id, f_start, f_end, l_min, l_max)


def refresh_bands(bars: np.ndarray) -> None:
    """Refresh every enabled band (disabled bands stay 0 and hidden)."""
    for band_id in bands_enabled:
        if bands_enabled[band_id]:
            refresh_band_value(bars, band_id)


def update_spectrum_ui(bars: np.ndarray) -> None:
    """Redraw the spectrum bars and refresh the enabled bands (main thread)."""
    n = len(bars)
    bw = SPEC_DRAWLIST_W / n
    for i, level in enumerate(bars):
        h = level * (SPEC_DRAWLIST_H - 4)
        dpg.configure_item(
            f"spec_bar_{i}",
            pmin=(i * bw + 1, SPEC_DRAWLIST_H - h),
            pmax=((i + 1) * bw - 1, SPEC_DRAWLIST_H - 2),
        )
    state.spectrum_bars_cache = bars
    refresh_bands(bars)


def on_band_enable(sender: Any, app_data: Any, user_data: Any) -> None:
    """Show/hide a band's overlay and (re)compute it when the checkbox toggles."""
    band_id = int(user_data)
    bands_enabled[band_id] = bool(app_data)
    if bands_enabled[band_id]:
        refresh_band_value(state.spectrum_bars_cache, band_id)
    else:
        _set_band_variable(band_id, 0.0)
        dpg.set_value(f"band{band_id}_value_text", "—")
        dpg.configure_item(f"band{band_id}_rect", show=False)
        dpg.configure_item(f"band{band_id}_label", show=False)  # e71s02: the number goes with it
        dpg.configure_item(f"band{band_id}_edge_hl", show=False)  # e50s01: no grab highlight
        if _band_drag["band_id"] == band_id:
            _end_band_drag()


def on_band_change(sender: Any, app_data: Any, user_data: Any) -> None:
    """Refresh a band when its selection sliders move."""
    refresh_band_value(state.spectrum_bars_cache, int(user_data))


def _build_band_rows() -> None:
    """One Audio-window control row per registered band (e50s02, e71s01).

    Extracted from the import-time window build so a test can drive it and assert the
    rows; the loop derives from BAND_DEFAULT_RANGES, the count's single source.
    """
    for band_id, (start_default, end_default) in BAND_DEFAULT_RANGES.items():
        with dpg.group(horizontal=True):
            dpg.add_checkbox(
                label=f"Band {band_id}",
                tag=f"band{band_id}_enabled",
                callback=on_band_enable,
                user_data=band_id,
            )
            themed_text("F", slot="text")
            dpg.add_drag_float(
                default_value=start_default,
                min_value=0.0,
                max_value=0.99,
                speed=0.005,
                format="%.2f",
                width=44,
                tag=f"band{band_id}_start",
                callback=on_band_change,
                user_data=band_id,
            )
            dpg.add_drag_float(
                default_value=end_default,
                min_value=0.01,
                max_value=1.0,
                speed=0.005,
                format="%.2f",
                width=44,
                tag=f"band{band_id}_end",
                callback=on_band_change,
                user_data=band_id,
            )
            themed_text("L", slot="text")
            dpg.add_drag_float(
                default_value=0.0,
                min_value=0.0,
                max_value=1.0,
                speed=0.005,
                format="%.2f",
                width=44,
                tag=f"band{band_id}_min",
                callback=on_band_change,
                user_data=band_id,
            )
            dpg.add_drag_float(
                default_value=1.0,
                min_value=0.0,
                max_value=1.0,
                speed=0.005,
                format="%.2f",
                width=44,
                tag=f"band{band_id}_max",
                callback=on_band_change,
                user_data=band_id,
            )
            dpg.add_text("-", tag=f"band{band_id}_value_text", color=(230, 230, 120, 255))


def _build_band_labels() -> None:
    """One in-rectangle number per band, coloured like the band (e71s02).

    Extracted like `_build_band_rows` so a test can drive it and assert the labels;
    `refresh_band_value` moves each label onto its rectangle's top-left inside corner.
    """
    for band_id, (_fill, edge) in BAND_RECT_COLORS.items():
        label_tag = f"band{band_id}_label"
        dpg.draw_text(
            (BAND_LABEL_PAD_PX, BAND_LABEL_PAD_PX),
            str(band_id),
            color=edge,
            size=BAND_LABEL_FONT_SIZE,
            tag=label_tag,
            show=False,
        )
        if _band_label_font is not None:
            dpg.bind_item_font(label_tag, _band_label_font)


# --- e50s01: mouse-editable band rectangles -----------------------------------
# The drawlist is the clickable surface (draw commands cannot host handler
# registries, like the media tiles). The pointer is derived in the CLIENT space
# because `get_mouse_pos(local=False)` is DPG's stable per-frame client mouse and
# `get_item_rect_min` reports the item in that same space, so any padding cancels;
# the L7145 note documents why the local mouse is draw-order dependent.
_band_drag: dict[str, Any] = {"band_id": None, "edge": None, "x": 0.0, "y": 0.0}


def _band_rect_pointer() -> tuple[float, float]:
    """Pointer in drawlist-local pixels (e50s01)."""
    return band_rect_local_pointer(
        dpg.get_mouse_pos(local=False), dpg.get_item_rect_min("spec_drawlist")
    )


def _band_rect_hovered() -> bool:
    """Is the pointer over the spectrum drawlist?

    DPG 2.x accepts `mouse_*` handlers ONLY in a global handler registry (an
    item_handler_registry takes just the `item_*` handlers — the real library
    raises [1003] otherwise), so the seam gates on the item's client rectangle
    itself. A drawlist that is not laid out (its window hidden or collapsed, or
    the very first frame) reports rect_min and rect_size as (0, 0): it must NOT
    be hovered, or the top-left corner of the client area would become a phantom
    drag surface (verified against the real library).
    """
    size = dpg.get_item_rect_size("spec_drawlist")
    if not float(size[0]) or not float(size[1]):
        return False
    origin = dpg.get_item_rect_min("spec_drawlist")
    rect = (
        float(origin[0]),
        float(origin[1]),
        float(origin[0]) + float(size[0]),
        float(origin[1]) + float(size[1]),
    )
    return band_rect_contains(rect, dpg.get_mouse_pos(local=False))


def _band_window(band_id: int) -> tuple[float, float, float, float]:
    """One band's (start, end, min_level, max_level) from its four widgets (e50s01)."""
    return (
        float(dpg.get_value(f"band{band_id}_start")),
        float(dpg.get_value(f"band{band_id}_end")),
        float(dpg.get_value(f"band{band_id}_min")),
        float(dpg.get_value(f"band{band_id}_max")),
    )


def enabled_band_rects_px() -> list[tuple[int, tuple[float, float, float, float]]]:
    """The ENABLED bands' pixel rectangles, highest id first (hit priority, e50s01)."""
    rects: list[tuple[int, tuple[float, float, float, float]]] = []
    for band_id in sorted(bands_enabled, reverse=True):
        if not bands_enabled[band_id]:
            continue
        rects.append(
            (band_id, band_rect_px(_band_window(band_id), SPEC_DRAWLIST_W, SPEC_DRAWLIST_H))
        )
    return rects


def _hide_band_edge_highlights() -> None:
    """Hide every band's grab highlight (e50s01)."""
    for band_id in bands_enabled:
        tag = f"band{band_id}_edge_hl"
        if dpg.does_item_exist(tag):
            dpg.configure_item(tag, show=False)


def _set_band_edge_highlight(band_id: int, edge: str) -> None:
    """Move one band's highlight onto the armed edge, hiding the others (e50s01)."""
    _hide_band_edge_highlights()
    rects = dict(enabled_band_rects_px())
    rect = rects.get(band_id)
    tag = f"band{band_id}_edge_hl"
    if rect is None or not dpg.does_item_exist(tag):
        return
    segment = band_rect_edge_segment(rect, edge)
    if segment is None:
        return  # a body drag has no single edge (e50s02)
    dpg.configure_item(tag, p1=segment[0], p2=segment[1], show=True)


def _end_band_drag() -> None:
    """Forget the grabbed band edge (e50s01)."""
    _band_drag["band_id"] = None
    _band_drag["edge"] = None


def _band_rect_mouse_down(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """Grab the edge nearest the pointer on button down (e50s01).

    DPG 2.3.1 re-fires this handler on EVERY frame while the button is held
    (real-rig proof: three identical events per pointer position, each carrying
    the current position). A repeat event must be ignored: re-arming there moves
    the drag anchor to the current pointer every frame, so every delta reads
    (0, 0) and the band never moves. The global release handler clears the grab,
    which is what lets the next press arm a fresh drag.
    """
    if _band_drag["band_id"] is not None:
        return
    if not _band_rect_hovered():
        return
    hit = band_rect_hit_test(_band_rect_pointer(), enabled_band_rects_px())
    if hit is None:
        _hide_band_edge_highlights()
        return
    band_id, edge = hit
    _band_drag["band_id"] = band_id
    _band_drag["edge"] = edge
    _band_drag["x"], _band_drag["y"] = _band_rect_pointer()
    _set_band_edge_highlight(band_id, edge)


def _band_rect_mouse_drag(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """Apply the grabbed edge's pixel delta to its band values (e50s01)."""
    band_id = _band_drag["band_id"]
    edge = _band_drag["edge"]
    if band_id is None or edge is None:
        return
    if not dpg.is_mouse_button_down(dpg.mvMouseButton_Left):
        # Second line of defence: the global release handler is the primary end of
        # a drag, but should the button come up without it (focus loss, a missed
        # event), the first post-release frame must not keep dragging
        _end_band_drag()
        _hide_band_edge_highlights()
        return
    pointer = _band_rect_pointer()
    delta_x = pointer[0] - float(_band_drag["x"])
    delta_y = pointer[1] - float(_band_drag["y"])
    _band_drag["x"], _band_drag["y"] = pointer[0], pointer[1]
    window = _band_window(band_id)
    dragged = band_rect_drag(window, edge, delta_x, delta_y, SPEC_DRAWLIST_W, SPEC_DRAWLIST_H)
    if dragged == window:
        return
    for name, value in zip(("start", "end", "min", "max"), dragged, strict=True):
        dpg.set_value(f"band{band_id}_{name}", value)
    refresh_band_value(state.spectrum_bars_cache, band_id)
    _set_band_edge_highlight(band_id, edge)


def _band_rect_mouse_release(
    sender: Any = None, app_data: Any = None, user_data: Any = None
) -> None:
    """End the drag and clear the highlight (e50s01)."""
    _end_band_drag()
    _hide_band_edge_highlights()


def _band_rect_mouse_move(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """Hover feedback: highlight the edge the pointer would grab (e50s01)."""
    if _band_drag["band_id"] is not None:
        if not dpg.is_mouse_button_down(dpg.mvMouseButton_Left):
            _end_band_drag()
            _hide_band_edge_highlights()
        return
    if not _band_rect_hovered():
        _hide_band_edge_highlights()
        return
    hit = band_rect_hit_test(_band_rect_pointer(), enabled_band_rects_px())
    if hit is None:
        _hide_band_edge_highlights()
    else:
        _set_band_edge_highlight(*hit)


def spectrum_analyzer_loop() -> None:
    """Compute the spectrum ~30x/s, AGC-normalize it, enqueue the redraw (HIGH-1)."""
    while True:
        if state.is_audio_analyzing:
            try:
                bars = compute_spectrum_bars(get_audio_snapshot())
                bars, state.spec_peak_hold = apply_spectrum_agc(bars, state.spec_peak_hold)
                ui_task(partial(update_spectrum_ui, bars))
            except Exception as e:
                log_error("Spectrum", str(e))
        time.sleep(1.0 / SPECTRUM_FPS)


def essentia_analyzer_loop() -> None:
    last_error = ""
    while True:
        if state.is_beat_tracking and state.beat_source == BEAT_SOURCE_ANALYSIS:
            try:
                audio_slice = essentia.array(get_audio_snapshot())
                if np.max(np.abs(audio_slice)) > 0.005:
                    if state.lowpass_enabled:
                        audio_slice = lowpass_filter(audio_slice)
                    bpm, _, confidence, _, _ = rhythm_extractor(audio_slice)
                    if confidence > 0.2 or state.beat_confidence == 0.0:
                        state.current_bpm = float(bpm)
                        state.beat_confidence = float(confidence)
                        state.bpm_last_detected = time.time()  # a real reading, not stale (e10s08)
                        enqueue_set_value(
                            "testo_bpm",
                            f"{state.current_bpm:.0f}",  # no confidence, value only (e10s08)
                        )
            except Exception as e:
                # Log each distinct failure once, not every second
                err = f"{type(e).__name__}: {e}"
                if err != last_error:
                    last_error = err
                    log_error("BPM analysis", err)
        time.sleep(1.0)


def link_metronome_active() -> bool:
    """True when the FREE-RUNNING metronome should flash for LINK (e75).

    Only with at least one PEER connected: with zero peers the session has a local tempo
    but nothing is actually synced, and an operator activating Link saw the LED blink for
    no reason. While the sequencer PLAYS the LED still flashes on every beat it advances
    (that is the step indicator, not this metronome).
    """
    return state.beat_source == BEAT_SOURCE_LINK and state.link_available and state.link_peers > 0


def visual_metronome_loop() -> None:
    while True:
        link_source = link_metronome_active()
        analysis_source = state.is_beat_tracking and state.current_bpm > 0
        if not state.is_playing and (link_source or analysis_source):
            if link_source:
                base_sleep = linkengine.link_interval(state.link_tempo)  # e75
            else:
                if not _timed_bpm_live():
                    time.sleep(0.05)
                    continue  # no live tempo: don't flash a stale BPM (e10s08)
                base_sleep = 60.0 / state.current_bpm
            actual_sleep = max(0.0, base_sleep + state.phase_nudge)
            led_tag = BEAT_LED_TAGS.get(state.beat_source)
            if led_tag:
                flash_led(led_tag)
            sync_event_led.wait(actual_sleep)
            if sync_event_led.is_set():
                sync_event_led.clear()
            state.phase_nudge = 0.0
        else:
            time.sleep(0.1)


# ==============================================================================
# NEW ASYNC THREAD FOR HIGH-RESOLUTION FADES
# ==============================================================================
def fade_tick_loop() -> None:
    """Advance the active beat-fades at 100 Hz (e41s02: coalesced emission).

    The per-track work lives in ``sequencer.advance_fade`` (dpg-free, unit
    tested): this loop owns only the cadence and the worker-thread survival
    guarantee — a failing send must never kill the thread (HIGH-1 / Defensive
    Code).
    """
    while True:
        if state.is_playing:
            current_time = time.time()
            for track in tracks_data:
                with contextlib.suppress(Exception):
                    advance_fade(track.get("active_fade", {}), current_time)
        time.sleep(0.01)  # 100 FPS check loop for smooth fades


def sequencer_prefix(index: int) -> str:
    """The tag namespace of one sequencer (e67s02): A keeps the shape it has always had."""
    return SEQ_TAG_PREFIX if index == 0 else f"{SEQ_TAG_PREFIX}_b"


def sequencer_transport_tag(index: int, base: str) -> str:
    """The tag of ONE transport control (e67s04): A keeps the bare names it has always had
    (`btn_play`, `cb_beat_…`), B's carry its namespace (`seq_b_btn_play`).

    ONE builder serves both rows, so the names must come from ONE place: hand-written names
    are how the two rows drifted apart — and how B's checkbox bug could exist on one row only
    (BUG-2026-10-12T230000).
    """
    if index == 0:
        return base
    return f"{sequencer_prefix(index)}_{base}"


def beat_checkbox_tag(index: int, mode: str) -> str:
    """The beat-source checkbox tag of ONE instance."""
    return sequencer_transport_tag(index, BEAT_CHECKBOX_TAGS[mode])


def beat_led_tag(index: int, mode: str) -> str:
    """The beat-source LED tag of ONE instance."""
    return sequencer_transport_tag(index, BEAT_LED_TAGS[mode])


def beat_box_tag(index: int, mode: str) -> str:
    """The bordered box enclosing ONE beat-source option and its tools (e74s07)."""
    return sequencer_transport_tag(index, f"beat_box_{mode}")


def advance_one_sequencer(index: int, beat_seconds: float | None = None) -> int:
    """Advance ONE sequencer by one beat, using ITS OWN record (e67s01, main-loop thread).

    The tick's per-beat body, parameterised by the instance — which is what makes two sequencers
    two INSTRUMENTS instead of two views of one: the playhead wraps at THAT instance's columns,
    the themes address ITS namespace, and the firing gets ITS OWN tracks (`fire_step`).

    One thread, two clocks: the caller owns the cadence and advances each playing instance; this
    owns what one beat of one instance MEANS. Returns the column that just fired (-1 if the
    instance has no playhead yet).

    e67s06: the MIDI mirror is per instance too — the beat flashes the playhead on the device
    that wears THIS sequencer's role, so B's beat never lights A's Launchpad.
    """
    record = state.sequencer(index)
    previous = record["step"]
    column, rows_in_play = next_beat(record["step"], record["rows"], record["cols"])
    record["step"] = column
    grid_flash_playhead(index)  # e67s06: the beat flashes THAT instance's own device
    prefix = sequencer_prefix(index)
    for row in rows_in_play:
        if previous != -1:
            update_step_theme(row, previous, is_head=False, prefix=prefix, index=index)
        update_step_theme(row, column, is_head=True, prefix=prefix, index=index)
        fire_step(record["tracks"], row, column, beat_seconds, prefix)
    return column


SEQUENCER_B_WINDOW_TAG = "sequencer_b_window"


def toggle_sequencer_play(index: int = 0) -> None:
    """PLAY/STOP of ONE sequencer (e67s01): its own transport, its own playhead (e67s02).

    A stopped sequencer resets its playhead and cancels its pending fades, exactly as A's STOP does;
    B's has its own label. `state.is_playing` IS instance 0's field, so A's behaviour is unchanged.

    The FLAG is what the tick reads. B does not SOUND until `sequencer_tick` polls
    `advance_due_sequencers` — the two clocks are written and tested, and the rewiring changes A's
    beat path, so it is the one step that waits for the rig.
    """
    record = state.sequencer(index)
    record["playing"] = not record["playing"]
    button = sequencer_transport_tag(index, "btn_play")
    if not record["playing"]:
        for r in range(NUM_TRACKS):
            for c in range(NUM_STEPS):
                update_step_theme(r, c, is_head=False, prefix=sequencer_prefix(index), index=index)
            record["tracks"][r]["active_fade"]["active"] = False
        record["step"] = -1
        dpg.set_item_label(button, "PLAY")
    else:
        dpg.set_item_label(button, "STOP")
        if index == 0:
            sync_event_seq.set()
    refresh_binding_leds()  # e53s02


def set_beat_source(index: int, source: str) -> None:
    """Choose ONE sequencer's beat source (e67s03), defaulting A's widget state to match.

    A's checkboxes keep driving `state.beat_source` through `midi_action_beat_source`; this is
    the door for the OTHER instances, and for A it is the same write, so they cannot disagree.
    """
    if source not in BEAT_SOURCE_LABELS:
        return
    state.sequencer(index)["beat_source"] = source
    if index == 0:
        midi_action_beat_source(source)


def resync_sequencer(index: int = 0) -> None:
    """Reset ONE sequencer's playhead and cancel its pending fades (e67s02)."""
    record = state.sequencer(index)
    record["step"] = -1
    _sequencer_deadlines[index] = 0.0  # the next beat fires at once, which is what RESYNC means
    for track in record["tracks"]:
        track["active_fade"]["active"] = False
    if index == 0:
        sync_event_seq.set()
        sync_event_led.set()


def _build_sequencer_b_body() -> None:
    """B's window contents: its TRANSPORT (the shared builder, with the delete `X`) and grid host.

    e67s04: B's row is `build_sequencer_transport(1, …)` — the SAME builder A's window calls, so
    the two rows cannot diverge again (the defect class of BUG-2026-10-12T230000).
    """
    build_sequencer_transport(1, SEQUENCER_B_WINDOW_TAG)
    with dpg.group(tag="seq_b_grid_host"):
        pass


def show_or_create_sequencer(index: int) -> str:
    """The A/B toolbar icons: ASK for the shape the FIRST time, SHOW it afterwards (e67s05).

    Returns "asked" or "shown" so a caller and a test can tell WHICH happened. The question goes
    through `needs_creation`, NEVER through `state.sequencer(1)`: that accessor CREATES B, and a
    question that fills the slot would destroy the distinction this function exists to make.
    """
    if state.needs_creation(index):
        open_creation_dialog(index)
        return "asked"
    _show_sequencer_window(index)
    return "shown"


def _show_sequencer_window(index: int) -> None:
    """Show ONE existing sequencer's window (e67s05)."""
    tag = "sequencer_window" if index == 0 else SEQUENCER_B_WINDOW_TAG
    if dpg.does_item_exist(tag):
        dpg.configure_item(tag, show=True)


def _build_second_sequencer_window() -> None:
    """B's window and body, WITHOUT its grid (e67s05): the dialog's Create fills the grid."""
    with dpg.window(
        label="Step Sequencer B",
        tag=SEQUENCER_B_WINDOW_TAG,
        width=1050,
        height=800,
        pos=(10, TOOLBAR_BAR_H),
    ):
        _build_sequencer_b_body()
    _apply_help_targets()  # e76: B's window is built on demand, so its row gets cards here


# e67s05: the FIRST opening of an empty slot asks its shape. The dialog is built ON DEMAND
# (never at import), like the step picker and the delete confirmation; fixed tags let a test
# set the choices and press Create the way the operator does.
_SEQ_CREATE_WINDOW_TAG = "seq_create_window"
_SEQ_CREATE_ROWS_TAG = "seq_create_rows"
_SEQ_CREATE_COLS_TAG = "seq_create_cols"
_SEQ_CREATE_ZOOM_TAG = "seq_create_zoom"


def open_creation_dialog(index: int) -> None:
    """Ask the shape of an empty slot BEFORE it is built (e67s05).

    Rows (4/8), columns (4/8) and Small/Medium/Large over the three levels; Create builds THAT
    shape through the one builder and shows the window. The dialog is A's first-open path as
    well: the operator asked for it explicitly ("even sequencer A, when I open it for the first
    time, you ask me how to make it").
    """
    if dpg.does_item_exist(_SEQ_CREATE_WINDOW_TAG):
        dpg.delete_item(_SEQ_CREATE_WINDOW_TAG)
    label = "A" if index == 0 else "B"
    with dpg.window(
        label=f"New sequencer {label}",
        tag=_SEQ_CREATE_WINDOW_TAG,
        modal=True,
        no_resize=True,
        width=300,
        height=170,
    ):
        for base, tag, default in (
            ("Rows", _SEQ_CREATE_ROWS_TAG, SEQ_MAX_ROWS),
            ("Columns", _SEQ_CREATE_COLS_TAG, SEQ_MAX_COLS),
        ):
            with dpg.group(horizontal=True):
                help_label(
                    base,
                    "sequencer.rows" if base == "Rows" else "sequencer.columns",
                    tag=f"{tag}_label",
                )
                help_tooltip(
                    dpg.add_combo(
                        items=[str(size) for size in SEQ_GEOMETRY_CHOICES],
                        default_value=str(default),
                        width=70,
                        tag=tag,
                    ),
                    "sequencer.rows" if base == "Rows" else "sequencer.columns",
                )
        with dpg.group(horizontal=True):
            help_label("Size", "sequencer.size", tag=f"{_SEQ_CREATE_ZOOM_TAG}_label")
            help_tooltip(
                dpg.add_combo(
                    items=list(SEQ_ZOOM_LABELS),
                    default_value="Medium",
                    width=110,
                    tag=_SEQ_CREATE_ZOOM_TAG,
                ),
                "sequencer.size",
            )
        with dpg.group(horizontal=True):
            dpg.add_button(
                label="Create",
                tag="seq_create_confirm",
                callback=lambda *_: create_sequencer_from_dialog(index),
            )
            dpg.add_button(
                label="Cancel",
                tag="seq_create_cancel",
                callback=lambda *_: cancel_creation_dialog(),
            )
    show_centered_window(_SEQ_CREATE_WINDOW_TAG)  # e68: dialogs open centered (e55)


def cancel_creation_dialog() -> None:
    """The dialog's Cancel: nothing is built, the slot stays empty (e67s05)."""
    if dpg.does_item_exist(_SEQ_CREATE_WINDOW_TAG):
        dpg.delete_item(_SEQ_CREATE_WINDOW_TAG)


def create_sequencer_from_dialog(index: int) -> None:
    """The dialog's Create: build THAT shape and show the window (e67s05)."""
    rows = _creation_dialog_size(_SEQ_CREATE_ROWS_TAG, SEQ_MAX_ROWS)
    cols = _creation_dialog_size(_SEQ_CREATE_COLS_TAG, SEQ_MAX_COLS)
    level = SEQ_ZOOM_LABELS.get(str(dpg.get_value(_SEQ_CREATE_ZOOM_TAG)), SEQ_ZOOM_DEFAULT)
    cancel_creation_dialog()
    if index != 0:
        # B's window is born WITH its creation: an empty slot has no window, and a re-create
        # after a delete finds the old one gone. Deleting first makes a stale tag impossible.
        if dpg.does_item_exist(SEQUENCER_B_WINDOW_TAG):
            dpg.delete_item(SEQUENCER_B_WINDOW_TAG)
        _build_second_sequencer_window()
    parent = "seq_grid_host" if index == 0 else "seq_b_grid_host"
    # THE instance: without it the cells carried B's tags and A's user_data, so every click on
    # B wrote to A (the operator's report, 2026-10-12).
    build_sequencer(rows, cols, level, prefix=sequencer_prefix(index), parent=parent, index=index)
    _show_sequencer_window(index)


def _creation_dialog_size(tag: str, default: int) -> int:
    """A dialog combo's chosen size as an int, or the default when it is gone or unreadable."""
    if not dpg.does_item_exist(tag):
        return default
    text = str(dpg.get_value(tag)).strip()
    return int(text) if text.isdigit() else default


def open_sequencer_delete_confirm(index: int) -> bool:
    """Draw the confirmation for the slot being deleted, refusing when nothing is armed (e67s02).

    The dialog deletes nothing itself: it calls the two halves of the TESTED state machine. It
    refuses when `request_sequencer_delete` arms nothing, which is what makes a confirmation
    without a subject harmless.
    """
    if state.request_sequencer_delete(index) is None:
        return False
    with dpg.window(
        label="Delete sequencer?",
        tag="seq_delete_confirm_window",
        modal=True,
        no_resize=True,
        width=430,
        height=110,
    ):
        dpg.add_text(f"Delete sequencer {'A' if index == 0 else 'B'} and its steps?")
        with dpg.group(horizontal=True):
            dpg.add_button(
                label="Delete",
                tag="seq_delete_confirm_yes",
                callback=lambda *_: _finish_delete(index, True),
            )
            dpg.add_button(
                label="Cancel",
                tag="seq_delete_confirm_no",
                callback=lambda *_: _finish_delete(index, False),
            )
    show_centered_window("seq_delete_confirm_window")  # e68: dialogs open centered (e55)
    return True


def on_sequencer_delete_click(
    sender: Any = None, app_data: Any = None, user_data: Any = None
) -> None:
    """e74s07: the transport row's `X` — open the delete confirmation for THAT instance.

    The index travels in `user_data`, never in a default argument: DearPyGui's third
    positional overwrites one (BUG-2026-10-12T230000).
    """
    index = user_data if isinstance(user_data, int) else 0
    open_sequencer_delete_confirm(index)


def _finish_delete(index: int, confirmed: bool) -> None:
    """The dialog's two answers: the state machine decides, this only reports the outcome."""
    if confirmed and state.confirm_sequencer_delete(index):
        if index == 0:
            # e68: A's window is the app's main one — HIDE it (its transport row stays) and let
            # the grid go. The A icon asks for a new shape on the next open.
            if dpg.does_item_exist("sequencer_window"):
                dpg.configure_item("sequencer_window", show=False)
        elif dpg.does_item_exist(SEQUENCER_B_WINDOW_TAG):
            dpg.delete_item(SEQUENCER_B_WINDOW_TAG)
        destroy_sequencer_grid(sequencer_prefix(index))
    else:
        state.cancel_sequencer_delete()
    if dpg.does_item_exist("seq_delete_confirm_window"):
        dpg.delete_item("seq_delete_confirm_window")


# e67s01/e67s02: THE TWO CLOCKS. The timing lives in a pure decision that takes the clock as a
# PARAMETER, exactly as `tick_mappings(now)` and `advance_fade(fade, now)` do: a thread's timing
# cannot be verified headlessly, but "which sequencer is due at `now`" can, and there the two
# clocks can go wrong.
_sequencer_deadlines: dict[int, float] = {}
_sequencer_beat_pending: dict[int, bool] = {}


def note_sequencer_beat(index: int) -> None:
    """An EVENT source (band 1 peak, MIDI clock) says this sequencer's beat has arrived (e67s01).

    The event is recorded PER INSTANCE, so two sequencers on the same source both see the beat while
    a sequencer on a timed source ignores it entirely.
    """
    _sequencer_beat_pending[index] = True


def _sequencer_interval(index: int) -> float:
    """The timed beat of one sequencer, in seconds (its OWN nudge included, then consumed).

    MANUAL mode uses THAT instance's own `bpm` — the number the operator typed for IT — and
    every other timed mode uses the analyser's reading (`current_bpm`). The distinction keeps
    two sequencers apart: with one shared value, a sequencer on Analysis would be driven by
    whatever was typed for a sequencer on Manual.
    """
    record = state.sequencer(index)
    source = record["beat_source"]
    if source == BEAT_SOURCE_MANUAL:
        raw = record["bpm"]
    elif source == BEAT_SOURCE_LINK:
        raw = state.link_tempo  # e75: the shared Link session tempo
    else:
        raw = state.current_bpm
    bpm = float(raw) if raw and float(raw) > 0 else 120.0
    interval = 60.0 / bpm
    nudge = float(record.get("nudge") or 0.0)
    if nudge:
        record["nudge"] = 0.0  # consumed, so a nudge is a one-beat correction and not a drift
    return max(0.01, interval + nudge)


def advance_due_sequencers(now: float) -> list[int]:
    """Advance every PLAYING sequencer whose OWN deadline has passed, and say which (e67s01/e67s02).

    ONE thread, TWO clocks: each instance keeps its own deadline (timed sources) or its own pending
    event (band/MIDI), so advancing A cannot move B and neither can lose the other's beat. The
    caller owns the cadence (a poll) and passes `now`: that is what makes this testable.

    An ABSENT deadline is what a FRESH start looks like: a PLAY (nothing stored yet) or a resume
    after a STOP (the stop FORGOT it). The first beat then fires on the next poll, which is what A
    has always done on PLAY — its `sync_event_seq` was already set, so its wait returned at once.
    Every later beat waits its own interval. A STOPPED instance is skipped and its deadline
    forgotten, so resuming starts from the resume, not from the beats it missed while stopped.
    """
    advanced: list[int] = []
    for index in range(state.sequencer_count()):
        record = state.sequencer(index)
        if not record["playing"]:
            _sequencer_deadlines.pop(index, None)
            _sequencer_beat_pending.pop(index, None)
            continue
        event_driven = record["beat_source"] in (BEAT_SOURCE_BAND1, BEAT_SOURCE_MIDI)
        if event_driven:
            if not _sequencer_beat_pending.pop(index, False):
                continue  # its own source said nothing: another sequencer's beat is not its beat
            beat_seconds: float | None = None
        else:
            interval = _sequencer_interval(index)
            if record["beat_source"] == BEAT_SOURCE_ANALYSIS and not _timed_bpm_live():
                continue  # a stale detection never advances (e10s08), exactly as A's loop did
            deadline = _sequencer_deadlines.get(index)
            if deadline is None:
                # NO stored deadline means a FRESH start (a PLAY, or a resume after a STOP
                # forgot it): the first beat fires on this poll, which is A's behaviour on PLAY,
                # and every later beat waits its interval (the branch below).
                # e75: a LINK start waits only the REMAINDER of the current Link beat, so its
                # first beat lands ON a Link beat instead of a phase-offset later.
                startup = interval
                if record["beat_source"] == BEAT_SOURCE_LINK and state.link_available:
                    phase = min(max(float(state.link_phase), 0.0), 0.999)
                    startup = interval * (1.0 - phase)
                _sequencer_deadlines[index] = now + startup
            elif now < deadline:
                continue
            else:
                _sequencer_deadlines[index] = now + interval
            beat_seconds = interval
        advance_one_sequencer(index, beat_seconds)
        advanced.append(index)
    return advanced


def any_sequencer_playing() -> bool:
    """True when ANY existing sequencer is playing — WITHOUT creating B to ask (e67).

    `state.sequencer(1)` creates B, so the question must go through `sequencer_count()` first:
    asking whether an empty slot plays must not fill it, or the create-or-open icons could not
    tell an empty slot from a full one.
    """
    if state.is_playing:
        return True
    return state.sequencer_count() > 1 and bool(state.sequencer(1)["playing"])


def deliver_event_beat() -> None:
    """An event beat arrived (band 1 peak / MIDI pulse): hand it to every event-driven one.

    One shared Event was enough for one sequencer; with two, each has its own pending flag, and
    a beat meant for a BAND sequencer must not move a TIMED one.
    """
    for index in range(state.sequencer_count()):
        record = state.sequencer(index)
        if record["playing"] and record["beat_source"] in (BEAT_SOURCE_BAND1, BEAT_SOURCE_MIDI):
            note_sequencer_beat(index)


def sequencer_tick() -> None:
    """The sequencer clock: ONE thread, TWO sequencers (e09, e67s01/e67s02).

    The loop POLLS and asks `advance_due_sequencers(now)` which instance is due, so each
    sequencer advances on its own beat source: timed ones on their own deadline (with their own
    when their own beat was delivered. The poll is bounded for the same reason the old loop polled
    the event with a 0.1 s timeout (BUG-2026-08-27T213000): a beat-source switch, a STOP or a NEW
    sequencer must break through, and an unbounded wait strands the thread.

    A's first beat still fires ON PLAY: `first_tick` arms each timed instance at `now`, not an
    interval later, which is what the old code did (its `sync_event_seq` was already set, so its
    wait returned at once). A STALE BPM never advances: the analysis source is gated by
    `_timed_bpm_live` (e10s08).
    """
    while True:
        if not any_sequencer_playing():
            time.sleep(0.1)
            continue
        advanced = advance_due_sequencers(time.time())
        for index in advanced:
            led_tag = BEAT_LED_TAGS.get(state.sequencer(index)["beat_source"])
            if led_tag and index == 0:
                flash_led(led_tag)  # e14s02: A's beat LED; per-instance LEDs are e67s03
        if not advanced:
            time.sleep(SEQUENCER_TICK_POLL_SECONDS)


def on_lowpass_toggle(sender: Any, app_data: Any, user_data: Any) -> None:
    state.lowpass_enabled = bool(app_data)


def _sync_analysis_widgets() -> None:
    """Mirror the analysis flags onto their checkboxes (e28s03)."""
    for tag, flag in (
        ("cb_spectrum_analysis", state.is_audio_analyzing),
        ("cb_bpm_analysis", state.is_beat_tracking),
    ):
        if dpg.does_item_exist(tag):
            dpg.set_value(tag, bool(flag))


def _sync_audio_stream() -> bool:
    """Open/close the shared input stream to match the analysis flags (e28s03).

    Returns False when the requested stream could not be opened (no input
    device or a device failure); the callers flip the flags back off and sync
    the widgets — the same bounce a failed manual click produces.
    """
    global audio_stream
    needs_stream = state.is_audio_analyzing or state.is_beat_tracking
    if needs_stream and audio_stream is None:
        device_string = str(dpg.get_value("combo_devices"))
        if "No input device" in device_string:
            return False
        device_id = int(device_string.split(":")[0])
        # 2026-10-14: name the capture client in PulseAudio/PipeWire (the ALSA plugin would
        # show `ALSA plug-in [python3.13]`); libpulse reads PULSE_PROP at connect.
        os.environ["PULSE_PROP"] = pulse_client_properties(os.environ.get("PULSE_PROP"))
        try:
            audio_stream = sd.InputStream(
                device=device_id,
                channels=1,
                samplerate=samplerate,
                dtype=np.float32,
                callback=audio_callback,
            )
            audio_stream.start()
        except Exception:
            audio_stream = None
            return False
    elif not needs_stream and audio_stream is not None:
        audio_stream.stop()
        audio_stream.close()
        audio_stream = None
        dpg.set_value("testo_bpm", "---")
    return True


def set_audio_analysis_flags(spectrum: bool, bpm: bool) -> None:
    """Restore the analysis checkboxes from a project (e28s03, main thread).

    Sets both flags + widgets, then opens the input stream when any flag is on
    (the device combo is restored before this call). On a failed open the flags
    bounce back off with a log, exactly like a failed manual click — a rig
    without capture never hangs with a phantom analysis flag.
    """
    state.is_audio_analyzing = bool(spectrum)
    state.is_beat_tracking = bool(bpm)
    _sync_analysis_widgets()
    if not _sync_audio_stream():
        state.is_audio_analyzing = False
        state.is_beat_tracking = False
        _sync_analysis_widgets()
        log_error("Audio", "analysis disabled: no usable input device")


def toggle_audio_stream(sender: Any, app_data: Any, user_data: Any) -> None:
    """Checkbox clicks: flip one analysis flag, sync the widgets and the stream.

    e28s03: the failure bounce (set_value(sender, False)) is now the flag +
    widget sync — a failed open flips the clicked flag back off.
    """
    if user_data == "vu_meter":
        state.is_audio_analyzing = bool(app_data)
    elif user_data == "beat_tracking":
        state.is_beat_tracking = bool(app_data)
    else:
        return
    _sync_analysis_widgets()
    if not _sync_audio_stream():
        if user_data == "vu_meter":
            state.is_audio_analyzing = False
        else:
            state.is_beat_tracking = False
        _sync_analysis_widgets()


def toggle_play(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """PLAY/STOP of ONE sequencer — the transport row's callback (e67s04).

    The instance rides in `user_data`, so ONE builder serves both rows; the default is A, so the
    MIDI executor and every existing caller keep their meaning. `toggle_sequencer_play` owns the
    per-instance work.
    """
    index = user_data if isinstance(user_data, int) else 0
    toggle_sequencer_play(index)


dpg.create_context()

# e76s01: the hover-help cards' theme. It is built here, right after the context, because
# every window below is constructed at import time and a card binds this tag the moment
# it is created (`_build_help_theme` is defined above with the renderer).
_build_help_theme()

# e08: the About-window brand mark is a static texture loaded once at boot, inside the
# texture registry. Guarded: a missing or corrupt asset leaves _help_logo_texture None and
# the About window falls back to a text line rather than failing the boot.
_HELP_LOGO_TEXTURE_TAG = "help_logo_texture"
_help_logo_texture: str | None = None
_TOOLBAR_BRAND_TEX_TAG = "toolbar_brand_texture"
_toolbar_brand_texture: str | None = None

with dpg.texture_registry(tag="texture_registry"):
    try:
        _logo_w, _logo_h, _logo_channels, _logo_pixels = dpg.load_image(_HELP_LOGO_PATH)
        dpg.add_static_texture(
            width=_logo_w,
            height=_logo_h,
            default_value=_logo_pixels,
            tag=_HELP_LOGO_TEXTURE_TAG,
        )
        _help_logo_texture = _HELP_LOGO_TEXTURE_TAG
    except Exception:
        _help_logo_texture = None  # missing asset: the About window falls back to text
    try:
        _brand_w, _brand_h, _brand_channels, _brand_pixels = dpg.load_image(_TOOLBAR_BRAND_PATH)
        dpg.add_static_texture(
            width=_brand_w,
            height=_brand_h,
            default_value=_brand_pixels,
            tag=_TOOLBAR_BRAND_TEX_TAG,
        )
        _toolbar_brand_texture = _TOOLBAR_BRAND_TEX_TAG
    except Exception:
        _toolbar_brand_texture = None  # missing asset: the bar keeps the Info icon
    try:
        _blend_w, _blend_h, _blend_channels, _blend_pixels = dpg.load_image(_BLENDING_ICONS_PATH)
        dpg.add_static_texture(
            width=_blend_w,
            height=_blend_h,
            default_value=_blend_pixels,
            tag=_BLENDING_ICONS_TEX_TAG,
        )
        _blending_icons_texture = _BLENDING_ICONS_TEX_TAG
    except Exception:
        _blending_icons_texture = None  # missing asset: the badge stays an empty square

# Compact ProggyTiny font for the Mediagrid tile titles (same guarded pattern; a missing
# asset leaves _tile_title_font None and the titles use the default 13 px font).
for _tile_title_font_path in _TILE_TITLE_FONT_PATHS:
    if os.path.exists(_tile_title_font_path):
        with dpg.font_registry():
            _tile_title_font = dpg.add_font(_tile_title_font_path, size=MEDIA_TITLE_FONT_SIZE)
        break

# e66s03: ONE font per zoom level, built here and never again. A level is a PAIR (pixels + a
# font), and creating a font per level change would be the one cost a zoom should not carry.
# A missing asset leaves the map empty and the cells keep the default font.
_seq_zoom_fonts: dict[int, Any] = {}
for _seq_font_path in _TILE_TITLE_FONT_PATHS:
    if os.path.exists(_seq_font_path):
        with dpg.font_registry():
            _seq_zoom_fonts = {
                _level: dpg.add_font(_seq_font_path, size=seqlayout.cell_layout(_level).font_size)
                for _level in SEQ_ZOOM_LEVELS
            }
        break

# e32s02: larger ProggyTiny for the Mapper row line numbers (one step above the
# 10 px mapper font, so the numbers stay compact but readable).
for _mapper_line_no_font_path in _TILE_TITLE_FONT_PATHS:
    if os.path.exists(_mapper_line_no_font_path):
        with dpg.font_registry():
            _mapper_line_no_font = dpg.add_font(
                _mapper_line_no_font_path, size=MAPPER_LINE_NO_FONT_SIZE
            )
        break

# e69s01: a SMALLER ProggyTiny for the TYPE line under a non-thumbnailable source's
# name in the Mapper row slot (same guarded pattern; a missing asset leaves None and
# the type uses the 10 px mapper font, still dim).
for _mapper_kind_font_path in _TILE_TITLE_FONT_PATHS:
    if os.path.exists(_mapper_kind_font_path):
        with dpg.font_registry():
            _mapper_kind_font = dpg.add_font(_mapper_kind_font_path, size=MAPPER_KIND_FONT_SIZE)
        break

# e55s02: a LARGE monospace font for the pairing code digits (DejaVuSansMono, or
# the bundled ProggyTiny; a missing file leaves None -> the default font).
for _pairing_code_font_path in _PAIRING_CODE_FONT_PATHS:
    if os.path.exists(_pairing_code_font_path):
        with dpg.font_registry():
            _pairing_code_font = dpg.add_font(_pairing_code_font_path, size=PAIRING_CODE_FONT_SIZE)
        break

# e71s02: the bold face bound to the band-number labels (same guarded pattern; a missing
# file leaves None and the numbers keep the default font, still in the band colour).
for _band_label_font_path in _BAND_LABEL_FONT_PATHS:
    if os.path.exists(_band_label_font_path):
        with dpg.font_registry():
            _band_label_font = dpg.add_font(_band_label_font_path, size=BAND_LABEL_FONT_SIZE)
        break


def _project_flow_ui_blocked() -> bool:
    """True while a project dialog or a confirmation modal is shown (e37s02).

    Save shortcuts must stay inert while the user types a filename in a file
    dialog or answers the Exit / New-project prompt.
    """
    tags = ("open_project_dialog", "save_project_dialog", EXIT_CONFIRM_TAG, NEW_PROJECT_CONFIRM_TAG)
    return any(dpg.does_item_exist(t) and dpg.is_item_shown(t) for t in tags)


def _on_save_key(sender: Any, app_data: Any, user_data: Any) -> None:
    """Key wrapper: DPG 2.3.1 handlers ignore modifiers — gate on Ctrl/Shift (e37s02)."""
    if not dpg.is_key_down(dpg.mvKey_ModCtrl) or _project_flow_ui_blocked():
        return
    if dpg.is_key_down(dpg.mvKey_ModShift):
        show_save_project_dialog()  # Ctrl+Shift+S = Save as...
    else:
        save_current_project()  # Ctrl+S = Save


with dpg.handler_registry():
    # DPG 2.3.1 key handlers have no modifier support: the wrapper checks Ctrl itself
    dpg.add_key_press_handler(dpg.mvKey_C, callback=_on_copy_key)
    dpg.add_key_press_handler(dpg.mvKey_V, callback=_on_paste_key)
    # e17: Ctrl+Tab / Ctrl+Shift+Tab cycle the workspace windows (the callback
    # checks the modifiers and the input-focus guard itself).
    dpg.add_key_press_handler(dpg.mvKey_Tab, callback=on_cycle_window)
    # e37s02: Ctrl+S / Ctrl+Shift+S save / save-as (the wrapper checks modifiers).
    dpg.add_key_press_handler(dpg.mvKey_S, callback=_on_save_key)
    # e55s02: Enter submits the pairing prompt while it is up (the digit filter
    # owns the input callback, so Enter is routed through the global handler).
    dpg.add_key_press_handler(dpg.mvKey_Return, callback=_on_pairing_code_enter)


# e10s06: one click-handler registry per Mediagrid tile. DPG 2.x item handlers
# live in an item_handler_registry bound to the item(s) they watch; child windows
# cannot host a clicked handler (verified against 2.3.1), so the registry is bound
# to the tile's clickable children (title, thumbnail, badge, alpha).
def media_tile_click_registry_tag(target_id: str) -> str:
    return f"click_reg_{target_id}"


def _bind_tile_click_targets(click_reg_tag: str, *item_tags: str | None) -> None:
    """Bind one tile's click registry to every clickable child that exists.

    Each binding is guarded (e83): DPG refuses some items and a refused nicety must
    never abort the tile build.
    """
    for item_tag in item_tags:
        if not item_tag or not dpg.does_item_exist(item_tag):
            continue
        _tile_status_call(
            "bind click",
            lambda t=item_tag: dpg.bind_item_handler_registry(t, click_reg_tag),
        )


with dpg.theme() as theme_selected_clip, dpg.theme_component(dpg.mvChildWindow):
    theme_color(dpg.mvThemeCol_Border, "border_active")
    theme_color(dpg.mvThemeCol_ChildBg, "accent_bg")
    dpg.add_theme_style(dpg.mvStyleVar_ChildRounding, 0)  # e74s05: square chrome
    dpg.add_theme_style(dpg.mvStyleVar_WindowPadding, MEDIA_TILE_PAD, MEDIA_TILE_PAD)
    dpg.add_theme_style(dpg.mvStyleVar_ItemSpacing, 2, 2)

with dpg.theme() as theme_normal_clip, dpg.theme_component(dpg.mvChildWindow):
    theme_color(dpg.mvThemeCol_Border, "border")
    theme_color(dpg.mvThemeCol_ChildBg, "panel_bg")
    dpg.add_theme_style(dpg.mvStyleVar_ChildRounding, 0)  # e74s05: square chrome
    dpg.add_theme_style(dpg.mvStyleVar_WindowPadding, MEDIA_TILE_PAD, MEDIA_TILE_PAD)
    dpg.add_theme_style(dpg.mvStyleVar_ItemSpacing, 2, 2)

with dpg.theme() as theme_vimix_current_clip, dpg.theme_component(dpg.mvChildWindow):
    # Vimix's current source in a lighter, non-green border (e10s06): clearly
    # distinct from the green VJmix primary selection and the plain tile.
    theme_color(dpg.mvThemeCol_Border, "text_dim")
    theme_color(dpg.mvThemeCol_ChildBg, "panel_bg")
    dpg.add_theme_style(dpg.mvStyleVar_ChildRounding, 0)  # e74s05: square chrome
    dpg.add_theme_style(dpg.mvStyleVar_WindowPadding, MEDIA_TILE_PAD, MEDIA_TILE_PAD)
    dpg.add_theme_style(dpg.mvStyleVar_ItemSpacing, 2, 2)

with dpg.theme() as theme_compact_table, dpg.theme_component(dpg.mvTable):
    dpg.add_theme_style(dpg.mvStyleVar_CellPadding, 1, 1)

with dpg.theme() as theme_cell_off, dpg.theme_component(dpg.mvChildWindow):
    theme_color(dpg.mvThemeCol_Border, "border")
    theme_color(dpg.mvThemeCol_ChildBg, "panel_bg")
    dpg.add_theme_style(dpg.mvStyleVar_ChildRounding, 0)  # e74s05: square like B

with dpg.theme() as theme_cell_on, dpg.theme_component(dpg.mvChildWindow):
    theme_color(dpg.mvThemeCol_Border, "border_active")
    theme_color(dpg.mvThemeCol_ChildBg, "accent_bg")
    dpg.add_theme_style(dpg.mvStyleVar_ChildRounding, 0)  # e74s05: square like B

with dpg.theme() as theme_cell_play_off, dpg.theme_component(dpg.mvChildWindow):
    theme_color(dpg.mvThemeCol_Border, "text_bright")
    theme_color(dpg.mvThemeCol_ChildBg, "play_bg")
    dpg.add_theme_style(dpg.mvStyleVar_ChildRounding, 0)  # e74s05: square like B

with dpg.theme() as theme_cell_play_on, dpg.theme_component(dpg.mvChildWindow):
    theme_color(dpg.mvThemeCol_Border, "text_bright")
    theme_color(dpg.mvThemeCol_ChildBg, "play_on_bg")
    dpg.add_theme_style(dpg.mvStyleVar_ChildRounding, 0)  # e74s05: square like B

with dpg.theme() as theme_slot_clear, dpg.theme_component(dpg.mvChildWindow):
    # borderless clip slot: no frame, no background (border=False + transparent ChildBg)
    dpg.add_theme_color(dpg.mvThemeCol_ChildBg, (0, 0, 0, 0))

with dpg.theme() as theme_alpha_slider, dpg.theme_component(dpg.mvSliderFloat):
    # Thin vertical alpha slider on a Mediagrid tile: subtle rail + accent grabber.
    # The rail uses the border slot (palette-driven); the grabber matches the app
    # accent so the value reads at a glance on the dark tile.
    theme_color(dpg.mvThemeCol_FrameBg, "border")
    theme_color(dpg.mvThemeCol_FrameBgHovered, "border")
    theme_color(dpg.mvThemeCol_FrameBgActive, "border")
    theme_color(dpg.mvThemeCol_SliderGrab, "accent")
    theme_color(dpg.mvThemeCol_SliderGrabActive, "accent")
    dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 2)
    dpg.add_theme_style(dpg.mvStyleVar_GrabRounding, 2)

with dpg.theme() as theme_stop_button, dpg.theme_component(dpg.mvButton):
    # e74s12: the small red STOP under the alpha slider. FramePadding 0 is what lets a
    # 10 px-wide button carry its one-character label at all (a padded button has no room).
    dpg.add_theme_color(dpg.mvThemeCol_Button, (150, 40, 40, 255))
    dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, (200, 60, 60, 255))
    dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, (235, 90, 90, 255))
    dpg.add_theme_color(dpg.mvThemeCol_Text, (255, 220, 220, 255))
    dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 0, 0)
    dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 0)

with dpg.theme() as theme_stop_button_on, dpg.theme_component(dpg.mvButton):
    # PARKED (alpha < 0): the source is stopped, so the STOP reads as pressed/armed.
    dpg.add_theme_color(dpg.mvThemeCol_Button, (235, 90, 90, 255))
    dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, (255, 120, 120, 255))
    dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, (255, 150, 150, 255))
    dpg.add_theme_color(dpg.mvThemeCol_Text, (255, 255, 255, 255))
    dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 0, 0)
    dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 0)

with dpg.theme() as theme_mapper_compact, dpg.theme_component(dpg.mvAll):
    # e23: compact Mapper — tight paddings/frames so the source rows and the
    # mini-cards shrink (the texts/controls also use the 10 px ProggyTiny
    # font). Measured against DPG 2.3.1: rows become ~60 px and the mini-cards
    # 150 px wide.
    theme_color(dpg.mvThemeCol_FrameBg, "border")
    theme_color(dpg.mvThemeCol_FrameBgHovered, "border")
    theme_color(dpg.mvThemeCol_FrameBgActive, "border")
    theme_color(dpg.mvThemeCol_SliderGrab, "accent")
    theme_color(dpg.mvThemeCol_SliderGrabActive, "accent")
    dpg.add_theme_style(dpg.mvStyleVar_WindowPadding, 4, 4)
    dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 6, 2)
    dpg.add_theme_style(dpg.mvStyleVar_ItemSpacing, 4, 2)
    dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 3)
    dpg.add_theme_style(dpg.mvStyleVar_GrabRounding, 2)

with dpg.theme() as theme_mapper_micro, dpg.theme_component(dpg.mvButton):
    # BUG-2026-10-16T220000: the caption-row R and X are 16x16 with the card
    # theme's FramePadding (6,2), which leaves 4x12 px for the glyph — ImGui clips
    # the label and it reads as "not centred". The SIZE is right (operator), so the
    # fix is the padding: with 0 the glyph is centred in the whole button. Bound to
    # the micro buttons only; every other colour comes from the card theme.
    dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 0, 0)
    dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 3)

with dpg.theme() as theme_learn_marker, dpg.theme_component(dpg.mvButton):
    # e33: the red 'M' learn markers — the red text signals "bind this to MIDI"
    # and stands out from the dim card captions (fixed accent red on every
    # palette; the markers only appear during a MIDI Learn session). e47: the
    # value comes from MIDI_LEARN_RED, shared with the toolbar's ON state.
    dpg.add_theme_color(dpg.mvThemeCol_Text, MIDI_LEARN_RED_RGBA)
    dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 0, 0)

with dpg.theme() as theme_learn_marker_armed, dpg.theme_component(dpg.mvButton):
    # ARMED 'M' (user 2026-09-07): the marker clicked last turns amber while it
    # waits for its MIDI message, so the user sees exactly which control the
    # next binding lands on. Palette-driven via theme_color (warning slot), so
    # it re-themes with the active palette like the other semantic colors.
    theme_color(dpg.mvThemeCol_Text, "warning")
    theme_color(dpg.mvThemeCol_ButtonHovered, "accent_bg")
    dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 0, 0)

with dpg.theme() as theme_seq_row_compact, dpg.theme_component(dpg.mvAll):
    # Tighter item spacing for the sequencer transport/beat-source row (e10s08):
    # the default 8 px between ~19 items pushed the row past the window width.
    dpg.add_theme_style(dpg.mvStyleVar_ItemSpacing, 4, 4)

with dpg.theme() as theme_beat_box, dpg.theme_component(dpg.mvChildWindow):
    # e74s07: one bordered box per beat option. The tight vertical padding is what keeps
    # the row (and its LED) INSIDE the box instead of clipping it: the box content height
    # is SEQ_BEAT_BOX_HEIGHT - 2 * SEQ_BEAT_BOX_PAD_Y, which must hold the tallest item.
    dpg.add_theme_style(dpg.mvStyleVar_ChildRounding, 0)
    dpg.add_theme_style(dpg.mvStyleVar_WindowPadding, 4, SEQ_BEAT_BOX_PAD_Y)
    dpg.add_theme_style(dpg.mvStyleVar_ItemSpacing, 4, 2)

with dpg.theme() as theme_step_copied, dpg.theme_component(dpg.mvChildWindow):
    # copied-step highlight: warm border on the source cell (e08); the bg stays dark in
    # every theme because the flash state must stand out on both light and dark panels
    theme_color(dpg.mvThemeCol_Border, "warning")
    dpg.add_theme_color(dpg.mvThemeCol_ChildBg, (40, 40, 30, 255))
    dpg.add_theme_style(dpg.mvStyleVar_ChildRounding, 0)  # e74s05: square like B


# ==============================================================================
# e59: TEXT WINDOW — author Pango markup and push it to a vimix Text source with
# the frozen-contract message /vimix/<target>/contents (one string argument).
# The markup toolkit (escape/validate/templates) is dpg-free in
# vjmixapp/textmarkup.py; this section is main-thread widget wiring only (HIGH-1).
# Verified: vimix's OSC wiki "contents: Set text contents: Text source only";
# vimix TextSource renders via GStreamer textoverlay -> pango_layout_set_markup.
# ==============================================================================
_text_source_options_cache: list[str] = []
# e59s05: the private-ABI caret reader, built lazily on the main thread; the
# `ready` flag stops a failing environment (no symbols / off Linux) from being
# probed again on every tick.
_text_caret_reader: caret.CaretReader | None = None
_text_caret_reader_ready = False
# e59s08: the reveal-steps cache (document + mode -> the ordered strings); the
# key recomputes it on an editor change or a mode switch.
_text_reveal_key: tuple[str, str] | None = None
_text_reveal_cache: list[str] = []


def text_source_targets(sources: dict[str, Any]) -> list[str]:
    """OSC targets of the TEXT sources, in grid order (e59s02, e68s03).

    A named source is addressed by its exact name (vimix: case sensitive); an unnamed one by
    '#<index>' (ControlManager accepts the '#' form). e68s03: the source's OSC `type` says which
    sources ARE Text (27), so the picker offers those and the rest are simply not listed —
    vimix silently ignores `contents` for a non-text source, and offering one was the pre-e68
    guess. When NO live source carries a type (an older viOSC or vimix), it falls back to
    offering every source by name rather than showing an empty picker.
    """
    ordered = sorted(sources, key=lambda key: _source_numeric_sort_key(sources, key))

    def _target(key: Any) -> str:
        name = (sources.get(key) or {}).get("name")
        return str(name) if name else f"{TEXT_SOURCE_INDEX_PREFIX}{key}"

    kinds = {key: sourcekind.source_kind_of(sources.get(key)) for key in ordered}
    if any(kind is not None for kind in kinds.values()):
        text_targets: list[str] = []
        for key in ordered:
            kind = kinds[key]
            if kind is not None and kind.text:
                text_targets.append(_target(key))
        return text_targets
    return [_target(key) for key in ordered]


def refresh_text_source_options(*_args: Any, force: bool = False) -> None:
    """Rebuild the source combo from the live state table (e59s02).

    Called on window open, on the Refresh button and on every state push; the
    cached list short-circuits a steady state so no widget is touched needlessly.
    """
    global _text_source_options_cache
    if not dpg.does_item_exist(TEXT_SOURCE_COMBO_TAG):
        return
    options = text_source_targets(state.global_vimix_state.get("sources") or {})
    if options == _text_source_options_cache and not force:
        return
    _text_source_options_cache = options
    selected = str(dpg.get_value(TEXT_SOURCE_COMBO_TAG) or "")
    if selected not in options:
        selected = state.text_target if state.text_target in options else ""
    if not selected and options:
        selected = options[0]
    dpg.configure_item(TEXT_SOURCE_COMBO_TAG, items=options)
    if selected:
        dpg.set_value(TEXT_SOURCE_COMBO_TAG, selected)
    state.text_target = selected


def on_text_target_changed(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """The source combo changed: remember the OSC target."""
    state.text_target = str(app_data or "")


def _set_text_status(message: str) -> None:
    """Write the Text window's one status line (markup validity or action result)."""
    if dpg.does_item_exist(TEXT_STATUS_TAG):
        dpg.set_value(TEXT_STATUS_TAG, message)


def update_text_markup_status() -> None:
    """Validate the live document and report it in the status line (e59s01)."""
    issue = textmarkup.validate_pango_markup(state.text_document)
    _set_text_status("Markup OK" if issue is None else textmarkup.format_markup_issue(issue))


def sync_text_editor_from_state() -> None:
    """Push state.text_document into the editor (main thread only)."""
    if dpg.does_item_exist(TEXT_EDITOR_TAG):
        dpg.set_value(TEXT_EDITOR_TAG, state.text_document)
    update_text_markup_status()


def on_text_editor_changed(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """Editor edit: sync state, track the caret and refresh the validity line.

    DearPyGui exposes no caret, so the shadow caret is inferred from the value
    change (`infer_edit_caret`); the structural check parses the whole document,
    so a large one is validated on demand (rate-limit category).
    """
    if isinstance(app_data, str):
        caret = textmarkup.infer_edit_caret(state.text_document, app_data)
        if caret is not None:
            state.text_caret = caret
        state.text_document = app_data
    if len(state.text_document) > TEXT_LIVE_VALIDATE_MAX_CHARS:
        _set_text_status("Large document: press Validate")
        return
    update_text_markup_status()


def _text_document_to_editor(document: str, status: str, caret: int | None = None) -> None:
    """Adopt a transformed document into both state and the editor."""
    state.text_document = document
    if caret is not None:
        state.text_caret = max(0, min(int(caret), len(document)))
    sync_text_editor_from_state()
    _set_text_status(status)


def _insert_markup_snippet(snippet: str, status: str) -> None:
    """Insert a snippet at the tracked caret, or append it when the caret is unknown.

    `state.text_caret == 0` on a non-empty document means "never typed here"
    (a fresh load / project open), so the template goes on its own line at the
    end; a mid-document caret inserts exactly there.
    """
    caret_position = state.text_caret
    if 0 < caret_position < len(state.text_document):
        document = textmarkup.insert_at(state.text_document, caret_position, snippet)
        _text_document_to_editor(document, status, caret_position + len(snippet))
        return
    document = textmarkup.append_snippet(state.text_document, snippet)
    _text_document_to_editor(document, status, len(document))


def _text_wrap_clipboard_enabled() -> bool:
    """True when the palette should wrap the clipboard instead of inserting."""
    return bool(dpg.get_value(TEXT_WRAP_CLIPBOARD_TAG))


def _wrap_clipboard_text(open_tag: str, close_tag: str, label: str) -> None:
    """Wrap the clipboard text in a tag pair and put it back on the clipboard.

    Selection-accurate markup without a selection API (upstream #1650): the
    operator cuts the text (Ctrl+X), clicks the tag, and pastes it back (Ctrl+V).
    The clipboard is the only channel the editor and this window share.
    """
    clipboard = str(dpg.get_clipboard_text() or "")
    if not clipboard:
        _set_text_status("Clipboard is empty")
        return
    dpg.set_clipboard_text(textmarkup.wrap_markup(clipboard, open_tag, close_tag))
    _set_text_status(f"{label}: clipboard wrapped - paste with Ctrl+V")


def _text_caret_reader_instance() -> caret.CaretReader | None:
    """The lazily-built live-caret reader, or None when unavailable (e59s05)."""
    global _text_caret_reader, _text_caret_reader_ready
    if not _text_caret_reader_ready:
        try:
            backend = caret.CtypesImGuiBackend.from_environment()
        except Exception as exc:
            log_error("Text caret", str(exc))
            backend = None
        _text_caret_reader = caret.CaretReader(backend) if backend is not None else None
        _text_caret_reader_ready = True
    return _text_caret_reader


def _text_caret_reader_available() -> bool:
    """True when the private-ABI caret reader could be built (e59s07)."""
    return _text_caret_reader_instance() is not None


def _sync_text_wrap_row() -> None:
    """Show the wrap-clipboard row ONLY when the caret reader is unavailable.

    With the reader working the row is dead UI (the palette wraps the real
    selection); it stays as the graceful-degradation fallback (e59s07, option A).
    """
    if dpg.does_item_exist(TEXT_WRAP_ROW_TAG):
        dpg.configure_item(TEXT_WRAP_ROW_TAG, show=not _text_caret_reader_available())


def tick_text_caret() -> None:
    """Capture the live caret/selection while the editor owns the ImGui input (e59s05).

    The ImGui state slot is single-slot: it survives blur (so a palette click can
    still read it) but is reused by any other InputText, so the captured widget id
    is validated on every later read and a mismatch keeps the last values.
    """
    if not dpg.does_item_exist(TEXT_EDITOR_TAG):
        return
    if not (dpg.is_item_active(TEXT_EDITOR_TAG) or dpg.is_item_focused(TEXT_EDITOR_TAG)):
        return
    reader = _text_caret_reader_instance()
    if reader is None:
        return
    captured = reader.read(state.text_widget_id)
    if captured is None:
        return
    state.text_widget_id = captured.widget_id
    state.text_caret = captured.cursor
    state.text_selection = captured.selection


def _wrap_text_selection(open_tag: str, close_tag: str, label: str) -> bool:
    """Wrap the captured selection in place (e59s05); False when there is none."""
    selection = state.text_selection
    if selection is None:
        return False
    document = _resolved_text_document()
    edit = textmarkup.wrap_range(document, selection, open_tag, close_tag)
    state.text_selection = None
    _text_document_to_editor(edit.document, f"Wrapped selection: {label}", edit.caret)
    return True


def _insert_at_live_caret(open_tag: str, close_tag: str, label: str) -> bool:
    """Insert a template at the real caret (e59s05); False when never captured."""
    if state.text_widget_id is None:
        return False
    document = _resolved_text_document()
    snippet = textmarkup.wrap_markup(textmarkup.MARKUP_SAMPLE_TEXT, open_tag, close_tag)
    caret = state.text_caret
    _text_document_to_editor(
        textmarkup.insert_at(document, caret, snippet), f"Inserted {label}", caret + len(snippet)
    )
    return True


def _apply_markup(open_tag: str, close_tag: str, label: str) -> None:
    """Route a palette tag: selection, then the live caret, then the fallbacks."""
    if _wrap_text_selection(open_tag, close_tag, label):
        return
    if _insert_at_live_caret(open_tag, close_tag, label):
        return
    # The clipboard wrap is the fallback for a missing reader only (e59s07).
    if not _text_caret_reader_available() and _text_wrap_clipboard_enabled():
        _wrap_clipboard_text(open_tag, close_tag, label)
        return
    snippet = textmarkup.wrap_markup(textmarkup.MARKUP_SAMPLE_TEXT, open_tag, close_tag)
    _insert_markup_snippet(snippet, f"Inserted {label}")


def on_text_insert_template(
    sender: Any = None, app_data: Any = None, user_data: Any = None
) -> None:
    """Palette: apply a template (insert at the caret, or wrap the clipboard)."""
    template = user_data
    if not isinstance(template, textmarkup.MarkupTemplate):
        return
    _apply_markup(template.open_tag, template.close_tag, template.label)


def _pango_color_from_edit(tag: str) -> str:
    """The '#' colour of a DPG colour edit (0..255 channels; white when unreadable)."""
    value = dpg.get_value(tag)
    if not isinstance(value, (list, tuple)) or len(value) < 3:
        return textmarkup.pango_color(255, 255, 255)
    red, green, blue = (round(float(channel)) for channel in list(value)[:3])
    return textmarkup.pango_color(red, green, blue)


def on_text_insert_foreground(
    sender: Any = None, app_data: Any = None, user_data: Any = None
) -> None:
    """Palette: apply a foreground-coloured span."""
    open_tag, close_tag = textmarkup.span_tag("foreground", _pango_color_from_edit("text_fg_color"))
    _apply_markup(open_tag, close_tag, "Foreground")


def on_text_insert_background(
    sender: Any = None, app_data: Any = None, user_data: Any = None
) -> None:
    """Palette: apply a background-coloured span."""
    open_tag, close_tag = textmarkup.span_tag("background", _pango_color_from_edit("text_bg_color"))
    _apply_markup(open_tag, close_tag, "Background")


def on_text_insert_size(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """Palette: apply a size span with the chosen Pango keyword."""
    keyword = str(dpg.get_value("text_size_keyword") or "medium")
    open_tag, close_tag = textmarkup.span_tag("size", keyword)
    _apply_markup(open_tag, close_tag, f"Size {keyword}")


def on_text_escape(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """Escape the WHOLE document so plain &, <, > render literally."""
    _text_document_to_editor(
        textmarkup.escape_pango_text(state.text_document), "Escaped plain text"
    )


def on_text_unescape(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """Reverse the whole-document escaping."""
    _text_document_to_editor(textmarkup.unescape_pango_text(state.text_document), "Unescaped text")


def on_text_validate(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """Run the structural markup check and report it."""
    update_text_markup_status()


def on_text_clear(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """Empty the document (state + editor) after the user's Clear click."""
    _text_document_to_editor("", "Cleared", 0)


def load_text_file(path: str) -> bool:
    """Read a UTF-8 text file into the editor; False + status on any problem."""
    try:
        size = os.path.getsize(path)
    except OSError as exc:
        log_error("Text", f"cannot stat {path}: {exc}")
        _set_text_status(f"Cannot read {path}")
        return False
    if size > TEXT_MAX_LOAD_BYTES:
        _set_text_status(f"File too large ({size} bytes > {TEXT_MAX_LOAD_BYTES})")
        return False
    try:
        with open(path, encoding="utf-8") as handle:
            document = handle.read()
    except (OSError, UnicodeDecodeError) as exc:
        log_error("Text", f"cannot read {path}: {exc}")
        _set_text_status(f"Cannot read {path}")
        return False
    state.text_source_path = path
    _text_document_to_editor(
        document, f"Loaded {len(document)} chars from {os.path.basename(path)}", len(document)
    )
    return True


def on_text_file_picked(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """Load-dialog result -> read the chosen file into the editor."""
    path = app_data.get("file_path_name") if isinstance(app_data, dict) else None
    if path:
        load_text_file(str(path))


def show_text_load_dialog(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """Open the Load-from-file dialog (.txt/.srt/any), fresh each time."""
    if dpg.does_item_exist(TEXT_LOAD_DIALOG_TAG):
        dpg.delete_item(TEXT_LOAD_DIALOG_TAG)
    default_path = os.path.dirname(state.text_source_path) or os.path.expanduser("~")
    with dpg.file_dialog(
        tag=TEXT_LOAD_DIALOG_TAG,
        show=True,
        width=520,
        height=380,
        callback=on_text_file_picked,
        default_path=default_path,
        modal=True,
    ):
        dpg.add_file_extension(".txt")
        dpg.add_file_extension(".srt")
        dpg.add_file_extension(".*")
        dpg.add_file_extension("")


def save_text_file(path: str) -> bool:
    """Write the current document as UTF-8; False + status on any problem (e59s06)."""
    document = _resolved_text_document()
    try:
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(document)
    except OSError as exc:
        log_error("Text", f"cannot write {path}: {exc}")
        _set_text_status(f"Cannot write {path}")
        return False
    state.text_source_path = path
    _set_text_status(f"Saved {len(document)} chars to {os.path.basename(path)}")
    return True


def on_text_file_saved(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """Save-dialog result -> write the chosen file."""
    path = app_data.get("file_path_name") if isinstance(app_data, dict) else None
    if path:
        save_text_file(str(path))


def show_text_save_dialog(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """Open the Save-to-file dialog (.txt/any), prefilled with the current name."""
    if dpg.does_item_exist(TEXT_SAVE_DIALOG_TAG):
        dpg.delete_item(TEXT_SAVE_DIALOG_TAG)
    default_path = os.path.dirname(state.text_source_path) or os.path.expanduser("~")
    default_name = os.path.basename(state.text_source_path) or "text.txt"
    with dpg.file_dialog(
        tag=TEXT_SAVE_DIALOG_TAG,
        show=True,
        width=520,
        height=380,
        callback=on_text_file_saved,
        default_path=default_path,
        default_filename=default_name,
        modal=True,
    ):
        dpg.add_file_extension(".txt")
        dpg.add_file_extension(".*")
        dpg.add_file_extension("")


def _resolved_text_document() -> str:
    """The document to send: the live editor value when readable, else state."""
    if dpg.does_item_exist(TEXT_EDITOR_TAG):
        widget_value = dpg.get_value(TEXT_EDITOR_TAG)
        if isinstance(widget_value, str):
            state.text_document = widget_value
    return state.text_document


def _resolved_text_target() -> str:
    """The OSC target to send to: the live combo value when readable, else state."""
    if dpg.does_item_exist(TEXT_SOURCE_COMBO_TAG):
        widget_value = dpg.get_value(TEXT_SOURCE_COMBO_TAG)
        if isinstance(widget_value, str):
            state.text_target = widget_value
    return state.text_target


def _send_contents(target: str, document: str, status: str, log_detail: str) -> None:
    """Send ONE `/vimix/<target>/contents` message (the frozen contract).

    Shared by Send (the document) and Clear (an empty string): refuses without a
    target or a client, reporting in the status line and never raising.
    """
    if not target:
        _set_text_status("Select a source first")
        return
    if osc_client is None:
        log_error("Text", f"cannot send contents: no OSC client ({status})")
        _set_text_status("OSC client not connected")
        return
    address = f"/vimix/{target}/contents"
    osc_client.send_message(address, document)
    _set_text_status(status)


def send_text_contents(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """Send the whole document to the selected source (e59s02).

    The only message is the frozen-contract `/vimix/<target>/contents` with one
    string argument; vimix ignores it for a non-text source. Empty text is legal
    (it clears the source). Refusals report in the status line and never raise.
    """
    target = _resolved_text_target()
    document = _resolved_text_document()
    _send_contents(
        target, document, f"Sent {len(document)} chars to {target}", f"{len(document)} chars"
    )


def clear_text_source(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """Send an EMPTY contents, blanking the vimix Text source (e59s06).

    This clears the SOURCE, never the local document (`on_text_clear` does that).
    """
    target = _resolved_text_target()
    _send_contents(target, "", f"Cleared {target}", "clear")


def show_text_window(*_args: Any) -> None:
    """Open the Text window: fresh source list + validity line (e59s02)."""
    _sync_text_wrap_row()  # e59s07: the fallback row follows the reader
    dpg.show_item(TEXT_WINDOW_TAG)
    dpg.focus_item(TEXT_WINDOW_TAG)
    refresh_text_source_options(force=True)
    sync_text_editor_from_state()
    _sync_text_learn_markers()
    _sync_text_mode_learn_markers()


def toggle_text_window(*_args: Any) -> None:
    """Show the Text window, or hide it when it is already open."""
    if dpg.does_item_exist(TEXT_WINDOW_TAG) and dpg.is_item_shown(TEXT_WINDOW_TAG):
        dpg.hide_item(TEXT_WINDOW_TAG)
        return
    show_text_window()


def show_sources_data_window(*_args: Any) -> None:
    """Open the Sources-data window: the raw viOSC state table (e74s03).

    The table itself is built by ``update_vimix_sources_ui`` under
    ``SOURCES_DATA_GROUP_TAG``; this only shows and focuses the frame.
    """
    dpg.show_item(SOURCES_DATA_WINDOW_TAG)
    dpg.focus_item(SOURCES_DATA_WINDOW_TAG)


def toggle_sources_data_window(*_args: Any) -> None:
    """Show the Sources-data window, or hide it when it is already open (e74s03)."""
    if dpg.does_item_exist(SOURCES_DATA_WINDOW_TAG) and dpg.is_item_shown(SOURCES_DATA_WINDOW_TAG):
        dpg.hide_item(SOURCES_DATA_WINDOW_TAG)
        return
    show_sources_data_window()


def _exec_text_window_toggle(params: dict[str, Any], value: int) -> None:
    """e59s02: a momentary press shows or hides the Text window."""
    if value < MIDI_CC_TRIGGER_THRESHOLD:
        return
    toggle_text_window()


def _exec_text_send(params: dict[str, Any], value: int) -> None:
    """e59s02: a momentary press sends the document to the selected source."""
    if value < MIDI_CC_TRIGGER_THRESHOLD:
        return
    send_text_contents()


def _exec_text_clear(params: dict[str, Any], value: int) -> None:
    """e59s06: a momentary press clears (empty contents) the selected source."""
    if value < MIDI_CC_TRIGGER_THRESHOLD:
        return
    clear_text_source()


def _text_reveal_steps() -> list[str]:
    """The cached reveal steps for the live document and mode (e59s08)."""
    global _text_reveal_key, _text_reveal_cache
    document = _resolved_text_document()
    key = (document, state.text_reveal_mode)
    if key != _text_reveal_key:
        _text_reveal_key = key
        _text_reveal_cache = textplay.steps(document, state.text_reveal_mode)
    return _text_reveal_cache


def _reveal_status(mode: str, step: int, total: int, fragment: str) -> str:
    """The one-line readout for a reveal step (mode, k/n, a short preview)."""
    label = textplay.REVEAL_LABELS.get(mode, mode)
    preview = fragment.replace("\n", "\\n")
    if len(preview) > 48:
        preview = f"{preview[:45]}..."
    return f"{label} - {step + 1}/{total} - {preview!r}"


def on_text_mode(mode: str) -> None:
    """A reveal mode press: select + first step, or advance (e59s08).

    The buttons are momentary: pressing a DIFFERENT mode selects it and sends
    step 1; pressing the SAME mode advances one step. Past the end it reports and
    holds the last step. The document itself is never modified.
    """
    if mode not in textplay.REVEAL_LABELS:
        return
    if not _resolved_text_target():
        _set_text_status("Select a source first")
        return
    if osc_client is None:
        _set_text_status("OSC client not connected")
        return
    if state.text_reveal_mode != mode:
        state.text_reveal_mode = mode
        state.text_reveal_step = 0
    else:
        state.text_reveal_step += 1
    steps = _text_reveal_steps()
    if not steps:
        _set_text_status(f"{textplay.REVEAL_LABELS[mode]}: empty document")
        return
    if state.text_reveal_step >= len(steps):
        state.text_reveal_step = len(steps) - 1
        _set_text_status(f"{textplay.REVEAL_LABELS[mode]}: end of text ({len(steps)} steps)")
        return
    fragment = steps[state.text_reveal_step]
    _send_contents(
        _resolved_text_target(),
        fragment,
        _reveal_status(mode, state.text_reveal_step, len(steps), fragment),
        f"{textplay.REVEAL_LABELS[mode]} {state.text_reveal_step + 1}/{len(steps)}",
    )


def on_text_mode_button(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """The reveal-row button callback: user_data is the mode id (e59s08)."""
    if isinstance(user_data, str):
        on_text_mode(user_data)


def _exec_text_reveal(mode: str, params: dict[str, Any], value: int) -> None:
    """e59s08: a momentary press runs one reveal mode (threshold-gated)."""
    if value < MIDI_CC_TRIGGER_THRESHOLD:
        return
    on_text_mode(mode)


def _sync_text_mode_learn_markers() -> None:
    """(Re)render the reveal row's learn markers (e33 rule)."""
    if not dpg.does_item_exist(TEXT_MODE_LEARN_SLOT_TAG):
        return
    dpg.delete_item(TEXT_MODE_LEARN_SLOT_TAG, children_only=True)
    if not state.midi_learn_mode:
        return
    for action_id, tag in (
        (MIDI_ACTION_TEXT_WORD, "text_mk_word"),
        (MIDI_ACTION_TEXT_WORD_PLUS, "text_mk_word_plus"),
        (MIDI_ACTION_TEXT_LINE, "text_mk_line"),
        (MIDI_ACTION_TEXT_LINE_PLUS, "text_mk_line_plus"),
    ):
        learn_marker(
            action_id,
            {},
            parent=TEXT_MODE_LEARN_SLOT_TAG,
            tag=tag,
            tooltip=f"Map: {actions.action_label(action_id)}",
        )


def _sync_text_learn_markers() -> None:
    """(Re)render the Text window's learn markers (e33 rule)."""
    if not dpg.does_item_exist(TEXT_LEARN_SLOT_TAG):
        return
    dpg.delete_item(TEXT_LEARN_SLOT_TAG, children_only=True)
    if not state.midi_learn_mode:
        return
    for action_id, tag in (
        (MIDI_ACTION_TEXT_WINDOW_TOGGLE, "text_mk_toggle"),
        (MIDI_ACTION_TEXT_SEND, "text_mk_send"),
        (MIDI_ACTION_TEXT_CLEAR, "text_mk_clear"),
    ):
        learn_marker(
            action_id,
            {},
            parent=TEXT_LEARN_SLOT_TAG,
            tag=tag,
            tooltip=f"Map: {actions.action_label(action_id)}",
        )


def _apply_text_state(section: dict[str, Any]) -> None:
    """Re-apply a project's `text` section onto the live app (e59s03)."""
    state.text_document = str(section.get("document") or "")
    state.text_target = str(section.get("target") or "")
    state.text_source_path = str(section.get("path") or "")
    state.text_caret = len(state.text_document)
    if dpg.does_item_exist(TEXT_SOURCE_COMBO_TAG) and state.text_target:
        dpg.set_value(TEXT_SOURCE_COMBO_TAG, state.text_target)
    sync_text_editor_from_state()


def _apply_shader_state(section: dict[str, Any]) -> None:
    """Re-apply a project's `shader` section onto the live app (e61s02).

    The registry is re-sanitized here rather than trusted: this entry point is
    also reachable from a document a human edited (the same reason e36 heals a
    mapping on load).
    """
    state.shader_document = str(section.get("document") or "")
    state.shader_target = str(section.get("target") or "")
    kind = str(section.get("kind") or "")
    state.shader_kind = kind if kind in SHADER_KINDS else SHADER_KIND_DEFAULT
    # e64s01: the generator-uniform declaration is NOT project content any more (it
    # is a rig setting in the user config): a project written by e63 carrying
    # `generator_uniforms: true` is ignored here, so an old file can never re-arm a
    # crash path. The direction is deliberate — a disabled uniform is an inert
    # slider, an enabled one is a dead vimix and a lost session.
    state.shader_path = str(section.get("path") or "")
    state.shader_family = str(section.get("family") or "")
    state.shader_uniforms = shadercode.sanitize_uniform_registry(section.get("uniforms"))
    if dpg.does_item_exist(SHADER_EDITOR_TAG):
        dpg.set_value(SHADER_EDITOR_TAG, state.shader_document)
    if dpg.does_item_exist(SHADER_TARGET_COMBO_TAG) and state.shader_target:
        dpg.set_value(SHADER_TARGET_COMBO_TAG, state.shader_target)
    if dpg.does_item_exist(SHADER_KIND_COMBO_TAG):
        dpg.set_value(SHADER_KIND_COMBO_TAG, state.shader_kind)
    if dpg.does_item_exist(SHADER_FAMILY_COMBO_TAG):
        dpg.set_value(SHADER_FAMILY_COMBO_TAG, state.shader_family or SHADER_FAMILY_ANY)
    _refresh_shader_validation()


# ==============================================================================
# e33s05: GLOBAL ACTIONS — the window-show and project actions become mappable
# through ONE "Map actions" panel (ADR-midi-learn-global-actions). One row per
# action with the uniform red-M marker while MIDI Learn is on; the toolbar stays
# clean (e47) and there is no native menu anymore (e46).
# ==============================================================================
_MAP_ACTION_WINDOW_LABELS: dict[str, str] = {
    "sequencer_window": "Step Sequencer A",
    "audio_window": "Audio analyzer",
    "vimix_media_window": "Vimix sources",
    "mapper_window": "Mapper",
    "logs_window": "Logs",
    "settings_window": "Settings",
    "midi_window": "MIDI",
    "leap_window": "Leap Motion",
    "help_window": "Info",
    SOURCES_DATA_WINDOW_TAG: "Sources data",
}
_MAP_ACTIONS_ENTRIES: tuple[tuple[str, dict[str, Any], str], ...] = (
    *(
        (MIDI_ACTION_SHOW_WINDOW, {"window": window}, label)
        for window, label in _MAP_ACTION_WINDOW_LABELS.items()
    ),
    (MIDI_ACTION_PROJECT_NEW, {}, "New project"),
    (MIDI_ACTION_PROJECT_OPEN, {}, "Open project"),
    (MIDI_ACTION_PROJECT_SAVE, {}, "Save project"),
)


def show_map_actions_window(
    sender: Any = None, app_data: Any = None, user_data: Any = None
) -> None:
    """Open the Map actions panel: the global actions as mappable rows (e33s05)."""
    dpg.show_item(MAP_ACTIONS_WINDOW_TAG)
    dpg.focus_item(MAP_ACTIONS_WINDOW_TAG)
    _sync_map_actions_panel()


def _sync_map_actions_panel() -> None:
    """(Re)render the Map actions rows: one label + red-M marker per action."""
    if not dpg.does_item_exist(MAP_ACTIONS_ROWS_TAG):
        return
    dpg.delete_item(MAP_ACTIONS_ROWS_TAG, children_only=True)
    for index, (action_id, params, label) in enumerate(_MAP_ACTIONS_ENTRIES):
        row_tag = f"{MAP_ACTIONS_ROWS_TAG}_{index}"
        with dpg.group(horizontal=True, tag=row_tag, parent=MAP_ACTIONS_ROWS_TAG):
            themed_text(label, slot="text")
        if state.midi_learn_mode:
            learn_marker(
                action_id,
                params,
                parent=row_tag,
                tag=f"{row_tag}_marker",
                tooltip=f"Map: {label}",
            )


def _exec_show_window(params: dict[str, Any], value: int) -> None:
    """e33s05: show + focus an allow-listed window (logged no-op otherwise)."""
    if value < MIDI_CC_TRIGGER_THRESHOLD:
        return
    window = str(params.get("window", ""))
    if window not in _MAP_ACTION_WINDOW_LABELS:
        log_error("MIDI", f"show_window: unknown window '{window}'")
        return
    show = _toolbar_show_func(window)
    if show is None or not dpg.does_item_exist(window):
        log_error("MIDI", f"show_window: window '{window}' is not available")
        return
    show()


def _exec_project_new(params: dict[str, Any], value: int) -> None:
    """e33s05: the New-project flow (confirm-aware) from MIDI."""
    if value < MIDI_CC_TRIGGER_THRESHOLD:
        return
    request_new_project()


def _exec_project_open(params: dict[str, Any], value: int) -> None:
    """e33s05: the Open-project dialog from MIDI."""
    if value < MIDI_CC_TRIGGER_THRESHOLD:
        return
    show_open_project_dialog()


def _exec_project_save(params: dict[str, Any], value: int) -> None:
    """e33s05: Save (or Save-as) the project from MIDI."""
    if value < MIDI_CC_TRIGGER_THRESHOLD:
        return
    save_current_project()


# ==============================================================================
# e61s03: SHADER WINDOW — a GLSL asset and its FILE-PATH deploy (decision D4')
#
# The deploy NEVER carries the GLSL: an inline `/code` above 4098 bytes of OSC
# datagram crashes vimix (specs/archive/spikes/SPIKE-shader-deployment.md), so the
# document is flushed to its asset file and only the PATH travels. Two message
# shapes, both verified on the rig: `/filter ss custom <path>` in ONE message for
# an effect (a CloneSource), `/code s <path>` for a generator (a ShaderSource).
# ==============================================================================
_shader_source_options_cache: tuple[str, list[str]] | tuple[()] = ()


def _set_shader_status(text: str) -> None:
    """One-line status for the Shader window (a no-op when it is not built yet)."""
    if dpg.does_item_exist(SHADER_STATUS_TAG):
        dpg.set_value(SHADER_STATUS_TAG, text)


def shader_source_targets(sources: dict[str, Any], kind: str | None = None) -> list[str]:
    """OSC targets for the Shader picker, FILTERED to the deploy ROLE (e61s03, e68).

    A generator deploys `/code` and needs a ShaderSource (50); an effect deploys `/filter ss
    custom` and needs a Clone (41) — a DraftSource (42) is a temporary draft and has no role. So
    the picker offers only the sources whose TYPE matches the kind, which makes the incoherent
    pair impossible to choose. When NO live source carries a type (an older viOSC or vimix) it
    falls back to every source by name: the operator's kind declaration still decides the message
    shape, and the deploy guard refuses a pair the type later proves wrong.
    """
    ordered = sorted(sources, key=lambda key: _source_numeric_sort_key(sources, key))

    def _target(key: Any) -> str:
        name = (sources.get(key) or {}).get("name")
        return str(name) if name else f"{TEXT_SOURCE_INDEX_PREFIX}{key}"

    roles = {key: sourcekind.shader_role((sources.get(key) or {}).get("type")) for key in ordered}
    typed = any(sourcekind.source_kind_of(sources.get(key)) is not None for key in ordered)
    if not typed:
        return [_target(key) for key in ordered]
    return [_target(key) for key in ordered if kind is not None and roles[key] == kind]


def refresh_shader_source_options(*_args: Any, force: bool = False) -> None:
    """Rebuild the Shader target combo from the live state table (e61s03).

    Called on window open, on every state push and by the Refresh button; the
    cached list short-circuits a steady state so no widget is touched needlessly.
    """
    global _shader_source_options_cache
    if not dpg.does_item_exist(SHADER_TARGET_COMBO_TAG):
        return
    options = shader_source_targets(
        state.global_vimix_state.get("sources") or {}, state.shader_kind
    )
    if (state.shader_kind, options) == _shader_source_options_cache and not force:
        return
    _shader_source_options_cache = (state.shader_kind, options)
    selected = str(dpg.get_value(SHADER_TARGET_COMBO_TAG) or "")
    if selected not in options:
        selected = state.shader_target if state.shader_target in options else ""
    if not selected and options:
        selected = options[0]
    dpg.configure_item(SHADER_TARGET_COMBO_TAG, items=options)
    if selected:
        dpg.set_value(SHADER_TARGET_COMBO_TAG, selected)
    state.shader_target = selected
    if not options:
        # e68: filtering can legitimately leave nothing (no Clone in the session, no ShaderSource).
        # Say so instead of showing a silently empty picker.
        wanted = "ShaderSource" if state.shader_kind == shadercode.KIND_GENERATOR else "Clone"
        _set_shader_status(f"No {wanted} source in the session")


def on_shader_target_changed(
    sender: Any = None, app_data: Any = None, user_data: Any = None
) -> None:
    """The picker drives state.shader_target (the deploy reads it).

    e68: the target's OSC `type` DERIVES the kind (a ShaderSource 50 is a generator, a Clone 41 an
    effect), so the operator cannot leave the two disagreeing when the type is known. With no type
    the declaration stands, which is the fallback for an older viOSC/vimix.
    """
    state.shader_target = str(app_data or "")
    if _derive_shader_kind_from_target():
        refresh_shader_library()
    _rebuild_shader_uniform_panel()
    if state.shader_target:
        _set_shader_status(f"Target {state.shader_target} declared as {state.shader_kind}")
    else:
        _set_shader_status("Pick the vimix source to deploy to")


def _derive_shader_kind_from_target() -> bool:
    """Set the kind from the target's type when the type answers; True when it changed (e68)."""
    role = sourcekind.shader_role(
        sourcekind.type_of_source(
            state.global_vimix_state.get("sources") or {}, state.shader_target
        )
    )
    if role is None or role == state.shader_kind:
        return False
    state.shader_kind = role
    if dpg.does_item_exist(SHADER_KIND_COMBO_TAG):
        dpg.set_value(SHADER_KIND_COMBO_TAG, role)
    return True


def on_shader_kind_changed(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """The declared kind drives the validation profile and the deploy shape.

    e64s02: it also FILTERS the picker, so the list is refreshed here — the kind is
    the fastest way the operator narrows the library, and a stale row would offer an
    asset whose deploy shape contradicts the declaration.
    """
    state.shader_kind = str(app_data or SHADER_KIND_DEFAULT)
    refresh_shader_source_options(force=True)  # e68: the target list follows the kind
    refresh_shader_library()
    _rebuild_shader_uniform_panel()
    _refresh_shader_validation()
    _set_shader_status(f"Target kind: {state.shader_kind}")


def _refresh_shader_validation() -> None:
    """Show the validation result and gate the Send button (e61s03).

    Vimix compiles asynchronously and reports nothing over OSC, and its own editor
    reads "Ready" even for code that never compiled (SPIKE-3), so this pre-flight
    is the only signal the operator gets before the deploy.
    """
    issue = shadercode.validate_shader(state.shader_document, state.shader_kind)
    if dpg.does_item_exist(SHADER_VALIDATE_TAG):
        dpg.set_value(
            SHADER_VALIDATE_TAG,
            "Valid" if issue is None else f"Line {issue.line}, col {issue.column}: {issue.message}",
        )
    if dpg.does_item_exist(SHADER_SEND_BUTTON_TAG):
        dpg.configure_item(SHADER_SEND_BUTTON_TAG, enabled=issue is None)


def _shader_document_to_editor(code: str, status: str) -> None:
    """Push a document into the editor AND the live state (main thread only)."""
    state.shader_document = str(code)
    if dpg.does_item_exist(SHADER_EDITOR_TAG):
        dpg.set_value(SHADER_EDITOR_TAG, state.shader_document)
    _refresh_shader_validation()
    _set_shader_status(status)


def on_shader_editor_changed(
    sender: Any = None, app_data: Any = None, user_data: Any = None
) -> None:
    """Keep state.shader_document in sync: the deploy flushes it to the asset file."""
    state.shader_document = str(app_data if app_data is not None else "")
    _refresh_shader_validation()


def on_shader_library_picked(
    sender: Any = None, app_data: Any = None, user_data: Any = None
) -> None:
    """Load a library file COMPLETELY: document and asset path (e62 D3, e64s02).

    The file on disk is what Send deploys, so the pick sets the path as well as the
    editor: a shader picked from the list needs no Save before it goes on air. The
    name is resolved against a fresh scan, so a file that disappeared between the
    refresh and the click is reported instead of loading nothing.

    e64s02: the pick no longer OVERWRITES the declared kind. The list only offers
    assets of the kind in force, so there is nothing to align — and a click that
    races a file edited on disk is refused by `load_shader_file` rather than
    silently changing which OSC message the next Send emits.
    """
    name = str(app_data or "")
    entry = next((item for item in shadercode.scan_library().entries if item.name == name), None)
    if entry is None:
        _set_shader_status(f"Shader {name!r} is no longer in the library: reopen the window")
        return
    if not load_shader_file(entry.path):
        return
    _set_shader_status(
        f"Loaded {os.path.basename(entry.path)} ({shadercode.entry_kind_and_family(entry)})"
    )


def refresh_shader_library() -> shadercode.LibraryScan:
    """Repopulate the picker from the library folder and return the scan (e62, e64s02).

    The FOLDER is the list: a file copied in appears, a file deleted disappears, and
    the application carries no shader of its own. Called when the window opens, after
    a Save and on every kind or family change, so the picker never shows a stale list.

    e64s02: the fast path offers the assets that declare the KIND IN FORCE — the
    picker is for files that already conform to the pack schema, and anything else is
    reached through Load from file… — and the info line states the arithmetic so the
    shorter list never reads as an empty folder. e65s06 adds the FAMILY filter beside
    it: the same list, one more predicate, and the items of the family combo come from
    the LIBRARY (the operator's own families are filterable too) with `any family`
    first. A family whose last asset left the folder resets the filter and SAYS so —
    a view that can never be filled again is worse than a reset, and a silent reset is
    worse than both.
    """
    scan = shadercode.scan_library()
    families = sorted({entry.family for entry in scan.entries if entry.family})
    if state.shader_family and state.shader_family not in families:
        _set_shader_status(
            f"Family filter reset to '{SHADER_FAMILY_ANY}': no shader declares "
            f"{state.shader_family}"
        )
        state.shader_family = ""
    if dpg.does_item_exist(SHADER_FAMILY_COMBO_TAG):
        dpg.configure_item(SHADER_FAMILY_COMBO_TAG, items=[SHADER_FAMILY_ANY, *families])
        dpg.set_value(SHADER_FAMILY_COMBO_TAG, state.shader_family or SHADER_FAMILY_ANY)
    shown = [entry for entry in scan.entries if _shader_entry_is_offered(entry)]
    if dpg.does_item_exist(SHADER_TEMPLATE_COMBO_TAG):
        dpg.configure_item(SHADER_TEMPLATE_COMBO_TAG, items=[entry.name for entry in shown])
    _set_shader_library_info(scan, len(shown))
    return scan


def _shader_entry_is_offered(entry: shadercode.LibraryEntry) -> bool:
    """The two filters of the picker, in one place: the kind, then the family."""
    if entry.kind != state.shader_kind:
        return False
    return not state.shader_family or entry.family == state.shader_family


def on_shader_family_changed(
    sender: Any = None, app_data: Any = None, user_data: Any = None
) -> None:
    """Narrow the picker by family, beside the kind (e65s06).

    The combo's first item is the filter OFF; anything else is a declared token. The
    state keeps the TOKEN, so an empty string means "any" and the label never travels.
    """
    selected = str(app_data or "")
    state.shader_family = "" if selected == SHADER_FAMILY_ANY else selected
    refresh_shader_library()
    _set_shader_status(
        f"Family: {state.shader_family}" if state.shader_family else f"Family: {SHADER_FAMILY_ANY}"
    )


def _set_shader_library_info(scan: shadercode.LibraryScan, shown: int) -> None:
    """State the picker's arithmetic in the row itself, so it costs no line (e64s02).

    The short form is the normal case: `19 of 37 shaders` says both numbers and the
    combos right beside it explain the rest. The filters still have to be EXPLICIT
    where a number alone would mislead — an empty list (which would read as an empty
    library) and an empty folder — because e62's rule is that an absent file is never
    a mystery. With the family filter in force the sentence names BOTH: the reason a
    list is empty is the pair, not one of them.
    """
    if not dpg.does_item_exist(SHADER_LIBRARY_INFO_TAG):
        return
    total = len(scan.entries)
    hidden = total - shown
    if total == 0:
        text = "No shader in the library yet: Save to file… writes one there"
    elif shown == 0 and state.shader_family:
        text = (
            f"No {state.shader_kind} shader in '{state.shader_family}': {hidden} of "
            f"{total} hidden by the Kind and Family filters — switch either or use "
            f"Load from file…"
        )
    elif shown == 0:
        text = (
            f"No {state.shader_kind} shader: {hidden} of {total} hidden by the Kind "
            f"filter — switch Kind or use Load from file…"
        )
    else:
        text = f"{shown} of {total} shaders"
    dpg.set_value(SHADER_LIBRARY_INFO_TAG, text)


def report_skipped_library_files(scan: shadercode.LibraryScan) -> None:
    """Name the library files the picker cannot offer, and the line to add (e62 D2).

    A file without a valid kind declaration is NOT listed (user decision
    2026-10-10): the kind is declared, never inferred from the body. Saying so is
    what keeps the absence from looking like a bug.
    """
    if not scan.skipped:
        return
    named = ", ".join(item.filename for item in scan.skipped[:SHADER_MAX_SKIPS_NAMED])
    extra = len(scan.skipped) - SHADER_MAX_SKIPS_NAMED
    more = f" (+{extra} more)" if extra > 0 else ""
    _set_shader_status(
        f"{len(scan.skipped)} library file(s) not listed: {named}{more} — "
        f"{shadercode.KIND_DECLARATION_HINT}"
    )


def _shader_asset_path() -> str:
    """The asset file a deploy will send.

    A document with no file yet resolves to its library default, so Send always has
    a path to write and to send: the file on disk is the source of truth (D4').
    """
    return state.shader_path or shadercode.default_asset_path(state.shader_target)


def load_shader_file(path: str) -> bool:
    """Read a GLSL asset into the editor; False + status on any problem (e64s02).

    One rule for BOTH doors (the picker and Load from file…): an asset whose
    declaration disagrees with the kind in force is refused with the file's kind and
    the one action that fixes it. The kind selects which OSC message the next Send
    emits, so re-aligning it silently would change the deploy's destination shape
    under the operator's hands. An asset that declares nothing still loads — it is
    the operator's own file — with the exact line to add so the picker can list it.
    """
    try:
        code = shadercode.load_shader(path)
    except shadercode.ShaderAssetError as error:
        log_error("Shader", str(error))
        _set_shader_status(str(error))
        return False
    declared = shadercode.parse_kind(code)
    problem = _shader_kind_mismatch(declared, path)
    if problem is not None:
        _set_shader_status(problem)
        return False
    state.shader_path = path
    note = f"Loaded {len(code)} bytes from {os.path.basename(path)}"
    if declared is None:
        note = f"{note} — {shadercode.KIND_DECLARATION_HINT}"
    _shader_document_to_editor(code, note)
    return True


def _shader_kind_mismatch(declared: str | None, path: str) -> str | None:
    """Why a hand-picked asset cannot be loaded for the kind in force (e64s02).

    None when the asset agrees with the declared kind, or declares none at all.
    """
    if declared is None or declared == state.shader_kind:
        return None
    return (
        f"{os.path.basename(path)} declares {declared}, and the kind in force is "
        f"{state.shader_kind}: set Kind to {declared} to load and deploy it"
    )


def save_shader_file(path: str) -> bool:
    """Write the live document to `path` (the asset the deploy sends)."""
    try:
        shadercode.save_shader(path, state.shader_document)
    except shadercode.ShaderAssetError as error:
        log_error("Shader", str(error))
        _set_shader_status(str(error))
        return False
    state.shader_path = path
    _set_shader_status(f"Saved {os.path.basename(path)}")
    refresh_shader_library()
    return True


def on_shader_file_picked(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """Load-dialog result -> read the chosen asset into the editor."""
    path = app_data.get("file_path_name") if isinstance(app_data, dict) else None
    if path:
        load_shader_file(str(path))


def on_shader_file_saved(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """Save-dialog result -> write the document to the chosen asset path."""
    path = app_data.get("file_path_name") if isinstance(app_data, dict) else None
    if path:
        save_shader_file(str(path))


def show_shader_load_dialog(
    sender: Any = None, app_data: Any = None, user_data: Any = None
) -> None:
    """Open the Load-asset dialog (.glsl/any), fresh each time."""
    if dpg.does_item_exist(SHADER_LOAD_DIALOG_TAG):
        dpg.delete_item(SHADER_LOAD_DIALOG_TAG)
    default_path = os.path.dirname(state.shader_path) or shadercode.shader_library_dir()
    with dpg.file_dialog(
        tag=SHADER_LOAD_DIALOG_TAG,
        show=True,
        width=520,
        height=380,
        callback=on_shader_file_picked,
        default_path=default_path,
        modal=True,
    ):
        dpg.add_file_extension(SHADER_ASSET_EXTENSION)
        dpg.add_file_extension(".*")
        dpg.add_file_extension("")


def show_shader_save_dialog(
    sender: Any = None, app_data: Any = None, user_data: Any = None
) -> None:
    """Open the Save-asset dialog, prefilled with the current (or default) name."""
    if dpg.does_item_exist(SHADER_SAVE_DIALOG_TAG):
        dpg.delete_item(SHADER_SAVE_DIALOG_TAG)
    path = _shader_asset_path()
    with dpg.file_dialog(
        tag=SHADER_SAVE_DIALOG_TAG,
        show=True,
        width=520,
        height=380,
        callback=on_shader_file_saved,
        default_path=os.path.dirname(path) or os.path.expanduser("~"),
        default_filename=os.path.basename(path),
        modal=True,
    ):
        dpg.add_file_extension(SHADER_ASSET_EXTENSION)
        dpg.add_file_extension(".*")
        dpg.add_file_extension("")


def _sync_shader_learn_markers() -> None:
    """(Re)render the Shader window's learn markers (e33 rule)."""
    if not dpg.does_item_exist(SHADER_LEARN_SLOT_TAG):
        return
    dpg.delete_item(SHADER_LEARN_SLOT_TAG, children_only=True)
    if not state.midi_learn_mode:
        return
    for action_id, tag in (
        (MIDI_ACTION_SHADER_WINDOW_TOGGLE, "shader_mk_toggle"),
        (MIDI_ACTION_SHADER_SEND, "shader_mk_send"),
        (MIDI_ACTION_SHADER_LOAD, "shader_mk_load"),
        (MIDI_ACTION_SHADER_SAVE, "shader_mk_save"),
        (MIDI_ACTION_SHADER_BYPASS, "shader_mk_bypass"),
    ):
        learn_marker(
            action_id,
            {},
            parent=SHADER_LEARN_SLOT_TAG,
            tag=tag,
            tooltip=f"Map: {actions.action_label(action_id)}",
        )


def show_shader_window(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """Open (and focus) the Shader window, refreshing what it shows (e61s03)."""
    if not dpg.does_item_exist(SHADER_WINDOW_TAG):
        log_error("Shader", "the Shader window was not created: the app is still building")
        return
    dpg.show_item(SHADER_WINDOW_TAG)
    dpg.focus_item(SHADER_WINDOW_TAG)
    refresh_shader_source_options(force=True)
    if dpg.does_item_exist(SHADER_KIND_COMBO_TAG):
        dpg.set_value(SHADER_KIND_COMBO_TAG, state.shader_kind)
    _sync_shader_learn_markers()
    _refresh_shader_validation()
    sync_shader_registry()
    report_skipped_library_files(refresh_shader_library())


def toggle_shader_window(*_args: Any) -> None:
    """Toolbar/action toggle: hide the Shader window when it is open."""
    if dpg.does_item_exist(SHADER_WINDOW_TAG) and dpg.is_item_shown(SHADER_WINDOW_TAG):
        dpg.hide_item(SHADER_WINDOW_TAG)
    else:
        show_shader_window()


def send_shader_asset(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """Deploy the asset FILE PATH to the declared target (e61s03, decision D4').

    Order matters and every step reports: validate the document, FLUSH it to the
    asset file, refuse a path the vimix machine cannot read, then send the composed
    messages. Nothing raises and no refusal sends a byte.
    """
    issue = shadercode.validate_shader(state.shader_document, state.shader_kind)
    if issue is not None:
        _set_shader_status(f"Not deployable (line {issue.line}): {issue.message}")
        return
    path = _shader_asset_path()
    if not save_shader_file(path):
        return
    blocker = shadercode.deploy_blocker(
        state.shader_target,
        state.shader_kind,
        path,
        sourcekind.type_of_source(
            state.global_vimix_state.get("sources") or {}, state.shader_target
        ),
    )
    if blocker is not None:
        _set_shader_status(blocker)
        return
    messages = shadercode.compose_deploy_messages(state.shader_target, state.shader_kind, path)
    with osc.sent_by(IO_MONITOR_KIND_SHADER):
        for address, args in messages:
            osc_client.send_message(address, args)
    _set_shader_status(
        f"Deployed {os.path.basename(path)} to {state.shader_target} "
        f"({state.shader_kind}) via {', '.join(address for address, _args in messages)}"
    )
    # e61s04: the deploy replaced the program, so every uniform went back to its
    # declared default — put the operator's values back before they notice.
    sync_shader_registry()
    replay_shader_uniforms()


def _exec_shader_window_toggle(params: dict[str, Any], value: int) -> None:
    """e61s03: a momentary press shows or hides the Shader window."""
    if value < MIDI_CC_TRIGGER_THRESHOLD:
        return
    toggle_shader_window()


def _exec_shader_send(params: dict[str, Any], value: int) -> None:
    """e61s03: a momentary press flushes the document and deploys the asset path."""
    if value < MIDI_CC_TRIGGER_THRESHOLD:
        return
    send_shader_asset()


def _exec_shader_load(params: dict[str, Any], value: int) -> None:
    """e61s03: a momentary press opens the Load-asset dialog."""
    if value < MIDI_CC_TRIGGER_THRESHOLD:
        return
    show_shader_load_dialog()


def _exec_shader_save(params: dict[str, Any], value: int) -> None:
    """e61s03: a momentary press opens the Save-asset dialog."""
    if value < MIDI_CC_TRIGGER_THRESHOLD:
        return
    show_shader_save_dialog()


# --- e61s04: the uniform registry, its live controls, the replay and the bypass ---


def _current_shader_registry() -> dict[str, dict[str, float | None]]:
    """The registry rows of the DECLARED target (empty when none is chosen)."""
    return state.shader_uniforms.get(state.shader_target) or {}


def sync_shader_registry() -> None:
    """Re-derive the target's uniform registry from the live document (e61s04).

    Vimix reports neither the code nor the uniforms back, so the registry is
    rebuilt from what VJmix is about to deploy, carrying over the values and the
    manual ranges the operator set; a uniform that disappeared is dropped and
    LOGGED (a silent prune would look like a bug in the panel).
    """
    target = state.shader_target
    if not target:
        return
    previous = state.shader_uniforms.get(target)
    # e70s02: the slot -> name picture BEFORE the rebuild, so a re-deploy that moves a
    # parameter to another slot is VISIBLE (the positional model's one hazard).
    before = {
        shadercode.registry_slot(row, index + 1): name
        for index, (name, row) in enumerate((previous or {}).items())
    }
    registry, dropped = shadercode.build_registry(state.shader_document, previous)
    state.shader_uniforms[target] = registry
    if dropped:
        log_error("Shader", f"{target}: uniforms no longer in the shader: {', '.join(dropped)}")
    for index, (name, row) in enumerate(registry.items()):
        slot = shadercode.registry_slot(row, index + 1)
        was = before.get(slot)
        if was is not None and was != name:
            log_error("Shader", f"{target}: uniform{slot} now drives '{name}' (was '{was}')")
    _rebuild_shader_uniform_panel()
    _refresh_property_pickers()  # e61s05: the Mapper/Cue pickers offer the new names


def _catalog_entry(prop: str) -> dict[str, Any]:
    """The catalogue entry of a property, static or live-uniform (e61s05).

    Raises KeyError for an unknown property, exactly like indexing the static table
    did: callers that must tolerate an unknown key use `_maybe_catalog_entry`.
    """
    entry = shadercode.uniform_entries(state.shader_uniforms).get(str(prop))
    return entry if entry is not None else catalog.PROPERTY_CATALOG[str(prop)]


def _maybe_catalog_entry(prop: str) -> dict[str, Any] | None:
    """The entry of a property or None: the catalog, a uniform, or a Mapper action."""
    return mapper.mapping_entry(str(prop))


def _refresh_property_pickers() -> None:
    """Re-offer the property vocabulary after the uniform registry changed (e61s05).

    The Mapper dialog's combo and the Cue row's combo both come from
    `mapper.mappable_properties()`, so a uniform registered minutes ago must appear
    in them without restarting the app. The value is preserved when it is still legal.
    """
    for tag, options in (
        ("mapping_property_combo", mapper.mapper_properties()),  # e83: the Mapper extras
        ("cue_dlg_prop_combo", mapper.mappable_properties()),
    ):
        if not dpg.does_item_exist(tag):
            continue
        value = str(dpg.get_value(tag) or "")
        dpg.configure_item(tag, items=options)
        if value in options:
            dpg.set_value(tag, value)


def _uniform_row_tag(index: int, kind: str) -> str:
    """A stable widget tag for one row of the panel (order = declaration order)."""
    return f"shader_uniform_{index}_{kind}"


def _shader_target_is_fixed() -> bool:
    """Whether `/uniform` may be sent to the current shader target (e68s04).

    The target's own OSC `type` is the signal — a source that reports a type runs a vimix
    newer than the #221 fix, and VJmix 1.1.0 requires that beta (e74s04 retired the
    operator's rig declaration).
    """
    return sourcekind.supports_uniform(_source_props(state.shader_target)) is True


def _rebuild_shader_uniform_panel() -> None:
    """Render one control row per registered uniform (e61s04).

    The rows are rebuilt rather than updated: the registry changes shape on every
    deploy (a uniform can appear or disappear), and a handful of rows is cheap.
    """
    if not dpg.does_item_exist(SHADER_UNIFORM_ROWS_TAG):
        return
    dpg.delete_item(SHADER_UNIFORM_ROWS_TAG, children_only=True)
    if not state.shader_target:
        themed_text(
            "Pick a target to see its uniforms", slot="text", parent=SHADER_UNIFORM_ROWS_TAG
        )
        return
    if state.shader_kind != shadercode.KIND_EFFECT:
        if _shader_target_is_fixed():
            themed_text(
                "A generator draws on an empty buffer and its uniforms are yours to "
                "declare: this target reports a shader-capable type, so /uniform is allowed.",
                slot="text",
                parent=SHADER_UNIFORM_ROWS_TAG,
            )
        else:
            themed_text(
                "A generator has no live uniforms until its OSC type answers: VJmix sends "
                "/uniform only to a source vimix reports as shader-capable (SPIKE-6).",
                slot="text_dim",
                parent=SHADER_UNIFORM_ROWS_TAG,
            )
            return
    registry = _current_shader_registry()
    if not registry:
        themed_text(
            "No uniforms: write `uniform float name = 0.0;` in the shader",
            slot="text",
            parent=SHADER_UNIFORM_ROWS_TAG,
        )
        return
    # e70s03: a uniform the asset's `// uniformN: name` map does not cover falls back to
    # the declaration order — say so where the operator controls it, rather than let a
    # reorder move a binding silently.
    declared_names = set(shadercode.parse_uniform_slots(state.shader_document).values())
    uncovered = [name for name in registry if name not in declared_names]
    if uncovered:
        themed_text(
            f"{len(uncovered)} uniform(s) not in the `// uniformN` map: "
            "positions follow declaration order",
            slot="text_dim",
            parent=SHADER_UNIFORM_ROWS_TAG,
        )
    for index, (name, row) in enumerate(registry.items()):
        low, high = shadercode.effective_range(row)
        value = row.get("value")
        current = float(value if value is not None else row.get("default") or 0.0)
        slot = shadercode.registry_slot(row, index + 1)
        beyond = " (not mappable)" if slot > SHADER_MAPPABLE_UNIFORM_SLOTS else ""
        with dpg.group(horizontal=True, parent=SHADER_UNIFORM_ROWS_TAG):
            dpg.add_text(
                f"uniform{slot} = {name}{'' if shadercode.is_bounded(row) else ' (open)'}{beyond}"
            )
            dpg.add_slider_float(
                tag=_uniform_row_tag(index, "slider"),
                default_value=min(max(current, low), high),
                min_value=low,
                max_value=high,
                width=SHADER_UNIFORM_SLIDER_W,
                callback=on_shader_uniform_moved,
                user_data=name,
            )
            dpg.add_input_float(
                tag=_uniform_row_tag(index, "override_min"),
                default_value=row.get("override_min")
                if row.get("override_min") is not None
                else low,
                width=70,
                step=0,
                callback=on_shader_uniform_range,
                user_data=name,
            )
            dpg.add_input_float(
                tag=_uniform_row_tag(index, "override_max"),
                default_value=(
                    row.get("override_max") if row.get("override_max") is not None else high
                ),
                width=70,
                step=0,
                callback=on_shader_uniform_range,
                user_data=name,
            )
            dpg.add_button(
                label="Send",
                callback=on_shader_uniform_send,
                user_data=name,
            )


def on_shader_uniform_moved(
    sender: Any = None, app_data: Any = None, user_data: Any = None
) -> None:
    """A moved control sets the uniform NOW: the value is also what a deploy replays."""
    name = str(user_data or "")
    row = _current_shader_registry().get(name)
    if row is None:
        return
    moved = float(app_data)
    row["value"] = moved
    _send_shader_uniform(name, moved)


def on_shader_uniform_send(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """A momentary re-send of the row's current value (no motion required)."""
    name = str(user_data or "")
    row = _current_shader_registry().get(name)
    if row is None:
        return
    value = row.get("value")
    _send_shader_uniform(name, float(value if value is not None else row.get("default") or 0.0))


def on_shader_uniform_range(
    sender: Any = None, app_data: Any = None, user_data: Any = None
) -> None:
    """The two range boxes set the operator's manual range (the parsed one is a hint)."""
    name = str(user_data or "")
    row = _current_shader_registry().get(name)
    if row is None:
        return
    low_tag = _uniform_row_tag(shadercode.registry_slot(row, 1) - 1, "override_min")
    high_tag = _uniform_row_tag(shadercode.registry_slot(row, 1) - 1, "override_max")
    row["override_min"] = float(dpg.get_value(low_tag))
    row["override_max"] = float(dpg.get_value(high_tag))
    _rebuild_shader_uniform_panel()


def _send_shader_uniform(name: str, value: float) -> None:
    """Send ONE `/uniform` for the declared target and report it (e61s04, e68s04)."""
    if not state.shader_target:
        _set_shader_status("Pick a target before moving a uniform")
        return
    if shadercode.uniform_blocked(
        state.shader_target,
        state.shader_target,
        state.shader_kind,
        sourcekind.type_of_source(
            state.global_vimix_state.get("sources") or {}, state.shader_target
        ),
    ):
        # e68s04: a typed source that is not shader-capable takes no uniform; an untyped one
        # that is the declared generator is refused too (the conservative fallback).
        _set_shader_status(f"{state.shader_target} cannot take a uniform")
        return
    address, args = shadercode.compose_uniform_message(state.shader_target, name, value)
    with osc.sent_by(IO_MONITOR_KIND_SHADER):
        osc_client.send_message(address, args)
    _set_shader_status(f"Uniform {name} = {value:g} on {state.shader_target}")


def replay_shader_uniforms() -> int:
    """Re-send every registered value after a deploy; returns how many (e61s04).

    `SetCode` replaces the whole program, so a deploy resets every uniform to the
    default written in the code (rig-confirmed). Both an EFFECT and a GENERATOR are
    replayed: VJmix 1.1.0 requires a vimix beta, where `/uniform` on a generator is
    safe (#221) — e74s04 retired the operator's rig declaration.
    """
    if not state.shader_target:
        return 0
    messages = shadercode.replay_messages(state.shader_target, _current_shader_registry())
    if not messages:
        return 0
    with osc.sent_by(IO_MONITOR_KIND_SHADER):
        for address, args in messages:
            osc_client.send_message(address, args)
    _set_shader_status(f"Replayed {len(messages)} uniform(s) after the deploy")
    return len(messages)


def toggle_shader_bypass(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """Bypass or re-enable the effect on the declared target (e61s04).

    Bypassing swaps the filter for the pass-through; re-enabling re-DEPLOYS the
    asset path (vimix creates a fresh custom filter with its default program, so
    the code has to be sent again) and then replays the uniforms. Only an effect
    target has a filter to swap.
    """
    if state.shader_kind != shadercode.KIND_EFFECT:
        _set_shader_status("Bypass applies to an effect target (a Clone with a custom filter)")
        return
    if not state.shader_target:
        _set_shader_status("Pick a target before bypassing")
        return
    state.shader_bypass = not state.shader_bypass
    if dpg.does_item_exist(SHADER_BYPASS_BUTTON_TAG):
        dpg.configure_item(SHADER_BYPASS_BUTTON_TAG, label=_shader_bypass_label())
    if not state.shader_bypass:
        # send_shader_asset re-deploys the path (which is what restores the code) and
        # then replays the uniforms itself: one path, no duplicate traffic.
        send_shader_asset()
        return
    with osc.sent_by(IO_MONITOR_KIND_SHADER):
        for address, args in shadercode.compose_bypass_messages(state.shader_target, True):
            osc_client.send_message(address, args)
    _set_shader_status(f"Bypassed the effect on {state.shader_target}")


def _shader_bypass_label() -> str:
    return "Bypassed" if state.shader_bypass else "Bypass"


def _exec_shader_bypass(params: dict[str, Any], value: int) -> None:
    """e61s04: a momentary press toggles the effect's bypass."""
    if value < MIDI_CC_TRIGGER_THRESHOLD:
        return
    toggle_shader_bypass()


# WINDOW 0c: SHADER (e61s03; hidden until opened from the toolbar work group).
with dpg.window(
    label="Shader",
    width=SHADER_WINDOW_WIDTH,
    height=SHADER_WINDOW_HEIGHT,
    pos=(320, TOOLBAR_BAR_H),
    tag=SHADER_WINDOW_TAG,
    show=False,
):
    # Row 1 (e64s02, e65s06): the KIND first, then the FAMILY filter beside it, then
    # the SHADER of that kind, then the count in the row itself (`19 of 37 shaders`),
    # which is why the label sits before the combo and there is no second line. The
    # kind is a declaration about the vimix target (the OSC feed exposes no source
    # type, so the operator states it — decision D1); it selects the validation
    # profile, the deploy shape AND the picker's fast path. The family narrows that
    # same list and nothing else: it is the second axis of the pack (`// family:`), it
    # comes from the LIBRARY, and `any family` turns it off.
    with dpg.group(horizontal=True):
        themed_text("Kind:", slot="text")
        dpg.add_combo(
            list(shadercode.KINDS),
            default_value=SHADER_KIND_DEFAULT,
            tag=SHADER_KIND_COMBO_TAG,
            width=130,
            callback=on_shader_kind_changed,
        )
        themed_text("Family:", slot="text")
        dpg.add_combo(
            [SHADER_FAMILY_ANY],
            default_value=SHADER_FAMILY_ANY,
            tag=SHADER_FAMILY_COMBO_TAG,
            width=130,
            callback=on_shader_family_changed,
        )
        themed_text("Shader:", slot="text")
        dpg.add_combo(
            [],
            tag=SHADER_TEMPLATE_COMBO_TAG,
            width=240,
            callback=on_shader_library_picked,
        )
        themed_text("", slot="text_dim", tag=SHADER_LIBRARY_INFO_TAG)
    dpg.add_separator()
    # Row 2 (e64s02): the asset tools, then the TARGET and Send — the target is what a
    # deploy acts ON, so it sits next to the action that uses it. Send flushes the
    # document to its file and deploys the PATH: no GLSL text ever travels (D4').
    with dpg.group(horizontal=True):
        help_tooltip(
            dpg.add_button(label="Validate", callback=lambda: _refresh_shader_validation()),
            "shader.validate",
        )
        help_tooltip(
            dpg.add_button(label="Load from file...", callback=show_shader_load_dialog),
            "shader.load",
        )
        help_tooltip(
            dpg.add_button(label="Save to file...", callback=show_shader_save_dialog),
            "shader.save",
        )
        themed_text("Target:", slot="text")
        dpg.add_combo([], tag=SHADER_TARGET_COMBO_TAG, width=200, callback=on_shader_target_changed)
        help_tooltip(
            dpg.add_button(label="Refresh", callback=refresh_shader_source_options),
            "shader.refresh_targets",
        )
        dpg.add_button(
            label="Send to target", tag=SHADER_SEND_BUTTON_TAG, callback=send_shader_asset
        )
        dpg.add_group(tag=SHADER_LEARN_SLOT_TAG, horizontal=True)
    dpg.add_input_text(
        tag=SHADER_VALIDATE_TAG,
        readonly=True,
        width=SHADER_WINDOW_WIDTH - SHADER_WINDOW_PADDING,
    )
    dpg.add_input_text(
        tag=SHADER_EDITOR_TAG,
        multiline=True,
        width=SHADER_WINDOW_WIDTH - SHADER_WINDOW_PADDING,
        height=SHADER_EDITOR_HEIGHT,
        callback=on_shader_editor_changed,
        default_value=state.shader_document,
    )
    dpg.add_separator()
    # e61s04: the uniform panel. One row per `uniform float` of the asset, with a
    # live send, the manual range and the effect bypass.
    with dpg.group(horizontal=True):
        themed_text("Uniforms:", slot="text")
        dpg.add_button(
            label="Re-scan", tag=SHADER_UNIFORM_SCAN_BUTTON_TAG, callback=sync_shader_registry
        )
        dpg.add_button(label="Bypass", tag=SHADER_BYPASS_BUTTON_TAG, callback=toggle_shader_bypass)
    with dpg.child_window(
        tag=SHADER_UNIFORM_ROWS_TAG,
        width=SHADER_WINDOW_WIDTH - SHADER_WINDOW_PADDING,
        height=SHADER_UNIFORM_PANEL_HEIGHT,
    ):
        pass
    dpg.add_input_text(
        tag=SHADER_STATUS_TAG,
        readonly=True,
        width=SHADER_WINDOW_WIDTH - SHADER_WINDOW_PADDING,
    )

# WINDOW 0b: TEXT (e59s02; hidden until opened from the toolbar work group).
with dpg.window(
    label="Text",
    width=TEXT_WINDOW_WIDTH,
    height=TEXT_WINDOW_HEIGHT,
    pos=(300, TOOLBAR_BAR_H),
    tag=TEXT_WINDOW_TAG,
    show=False,
):
    # Row 1: the vimix-interaction tools (e59s06: separated from the editor tools).
    with dpg.group(horizontal=True):
        themed_text("Source:", slot="text")
        dpg.add_combo([], tag=TEXT_SOURCE_COMBO_TAG, width=200, callback=on_text_target_changed)
        help_tooltip(
            dpg.add_button(label="Refresh", callback=refresh_text_source_options), "text.refresh"
        )
        help_tooltip(
            dpg.add_button(label="Clear", callback=clear_text_source),  # clears the SOURCE
            "text.clear_source",
        )
        help_tooltip(
            dpg.add_button(label="Send to source", callback=send_text_contents), "text.send"
        )
        dpg.add_group(tag=TEXT_LEARN_SLOT_TAG, horizontal=True)
    dpg.add_separator()
    # Row 2 (e59s08): the progressive reveal modes. Momentary: a first press
    # selects the mode and sends step 1, pressing the same mode again advances.
    with dpg.group(horizontal=True):
        for mode, label in textplay.REVEAL_MODES:
            help_tooltip(
                dpg.add_button(label=label, callback=on_text_mode_button, user_data=mode),
                "text.reveal",
            )
        dpg.add_group(tag=TEXT_MODE_LEARN_SLOT_TAG, horizontal=True)
    dpg.add_separator()
    # Row 3: the editor's file tools (Load / Save / Clear the local document).
    with dpg.group(horizontal=True):
        help_tooltip(
            dpg.add_button(label="Load from file...", callback=show_text_load_dialog), "text.load"
        )
        help_tooltip(
            dpg.add_button(label="Save to file...", callback=show_text_save_dialog), "text.save"
        )
        help_tooltip(
            dpg.add_button(label="Clear", callback=on_text_clear),  # clears the DOCUMENT
            "text.clear_document",
        )
    with dpg.group(horizontal=True, tag=TEXT_WRAP_ROW_TAG):
        dpg.add_checkbox(label="Wrap clipboard", tag=TEXT_WRAP_CLIPBOARD_TAG, default_value=True)
        themed_text("(fallback: Ctrl+X the text, click a tag, Ctrl+V)", slot="text_dim")
    with dpg.group(horizontal=True):
        for template in textmarkup.BASE_MARKUP_TEMPLATES:
            help_tooltip(
                dpg.add_button(
                    label=template.label,
                    width=28,
                    callback=on_text_insert_template,
                    user_data=template,
                ),
                "text.template",
            )
        dpg.add_combo(
            list(textmarkup.PANGO_SIZE_KEYWORDS),
            default_value="large",
            tag="text_size_keyword",
            width=100,
        )
        dpg.add_button(label="Size", callback=on_text_insert_size)
    with dpg.group(horizontal=True):
        dpg.add_color_edit(
            default_value=(255, 255, 255, 255),
            no_alpha=True,
            width=TEXT_COLOR_EDIT_WIDTH,
            tag="text_fg_color",
        )
        help_tooltip(
            dpg.add_button(label="Foreground", callback=on_text_insert_foreground),
            "text.foreground",
        )
        dpg.add_color_edit(
            default_value=(0, 0, 0, 255),
            no_alpha=True,
            width=TEXT_COLOR_EDIT_WIDTH,
            tag="text_bg_color",
        )
        help_tooltip(
            dpg.add_button(label="Background", callback=on_text_insert_background),
            "text.background",
        )
    with dpg.group(horizontal=True):
        help_tooltip(dpg.add_button(label="Escape text", callback=on_text_escape), "text.escape")
        help_tooltip(
            dpg.add_button(label="Unescape text", callback=on_text_unescape), "text.unescape"
        )
        help_tooltip(dpg.add_button(label="Validate", callback=on_text_validate), "text.validate")
    dpg.add_input_text(
        tag=TEXT_EDITOR_TAG,
        multiline=True,
        # e74s01: fill the LIVE window width; a fixed width clipped the editor when
        # the window was restored narrower or shown under display scaling.
        width=-1,
        height=TEXT_EDITOR_HEIGHT,
        callback=on_text_editor_changed,
    )
    themed_text("Markup OK", slot="text_dim", tag=TEXT_STATUS_TAG)

_sync_text_wrap_row()  # e59s07: decide the fallback row once, at build time


def create_sequencer_grid(
    rows: int,
    cols: int,
    level: int,
    parent: str = "sequencer_window",
    prefix: str = SEQ_TAG_PREFIX,
    index: int = 0,
) -> None:
    """Create the sequencer's table at a geometry and a zoom level (e66s03 revised).

    Rows and columns beyond the geometry are never built, which is the whole point: a hidden
    column cannot leave a gutter and a resized column cannot disagree with its cell, because
    there is nothing hidden and nothing resized. A sequencer is created at the size it will
    keep (the operator's decision, 2026-10-12).

    Reason for depth: the table is the ONE thing DearPyGui will not re-shape after creation —
    measured, a column's width is fixed at setup and `configure_item(column, width=…)` on it is
    read back but NOT applied — so building it is the only honest way to offer a geometry.
    """
    grid = seqlayout.cell_layout(level)
    with dpg.table(
        parent=parent,
        header_row=False,
        borders_innerH=False,
        borders_innerV=False,
        borders_outerH=False,
        borders_outerV=False,
        scrollX=True,
        scrollY=True,
        # e68: CONTENT height, so the table cannot stretch to the window's bottom. e74s08:
        # exactly rows * (cell + row pad) — the trailing extra pad left a blank band under
        # the last row (the operator's "empty row").
        height=rows * (grid.cell + SEQ_GRID_TABLE_ROW_PAD),
        policy=dpg.mvTable_SizingFixedFit,
        tag=f"{prefix}_table",
    ):
        for col in range(cols):
            dpg.add_table_column(
                width_fixed=True, init_width_or_weight=grid.cell, tag=f"{prefix}_col_{col}"
            )
        dpg.add_table_column(
            width_fixed=True, init_width_or_weight=grid.slot_width, tag=f"{prefix}_slot_col"
        )

        for row in range(rows):
            with dpg.table_row():
                for step in range(cols):
                    with dpg.child_window(
                        width=grid.cell,
                        height=grid.cell,
                        tag=f"{prefix}_cell_{row}_{step}",
                        no_scrollbar=True,
                    ):
                        pass
                    update_step_ui(row, step, prefix, index)

                # ASSIGNABLE CLIP SLOT (bare centered button, no table frame)
                with dpg.child_window(
                    width=grid.slot_width,
                    height=grid.slot_height,
                    border=False,
                    tag=f"{prefix}_slot_{row}",
                    no_scrollbar=True,
                ):
                    pass
                dpg.bind_item_theme(f"{prefix}_slot_{row}", theme_slot_clear)
                update_track_slot_ui(row, prefix, index)

    dpg.bind_item_theme(f"{prefix}_table", theme_compact_table)
    _bind_seq_zoom_fonts(index, prefix)


def destroy_sequencer_grid(prefix: str = SEQ_TAG_PREFIX) -> None:
    """Remove the grid, deleting every popup by its OWN tag FIRST (the landmine cure).

    `_clear_step_cell`'s docstring says why, and it is measured: a popup anchored inside a cell
    survives the deletion of its anchor group as an ORPHAN that keeps its alias, so rebuilding
    under the same tags fails with `No container to pop.` Deleting each `seq_pop_…` first is
    what makes a rebuild possible at all, and it is the recipe this repo already ships for one
    cell.
    """
    for row in range(NUM_TRACKS):
        for col in range(NUM_STEPS):
            popup_tag = f"{prefix}_pop_{row}_{col}"
            if dpg.does_item_exist(popup_tag):
                dpg.delete_item(popup_tag)
    if dpg.does_item_exist(f"{prefix}_table"):
        dpg.delete_item(f"{prefix}_table")


def build_sequencer_transport(index: int, parent: str) -> None:
    """Build the WHOLE transport row of ONE sequencer (e67s04).

    ONE builder, called once per instance: A's row is `index=0` in the Sequencer window and B's
    is `index=1` in its own, so the two rows agree by CONSTRUCTION rather than by maintenance.
    The defect this closes is `BUG-2026-10-12T230000`: B's row was a hand-written copy, and its
    checkboxes took the source as a default argument that DearPyGui's third positional
    overwrote with None, so every box unchecked itself.

    A's tags are the bare names the layout, the learn markers and the project round-trip
    address; B's carry its namespace. Both come from `sequencer_transport_tag`, so the names
    cannot drift apart by hand.
    """
    row_tag = f"{sequencer_prefix(index)}_transport_row"
    # e74s07c: the row is a CONTAINER of wrapped lines; `relayout_transport_row` fills it and
    # rebuilds the lines only when the wrap changes (the window width is read from the window).
    with dpg.group(tag=row_tag, parent=parent):
        pass
    dpg.bind_item_theme(row_tag, theme_seq_row_compact)
    _transport_layout_signature.pop(index, None)
    relayout_transport_row(index)


_transport_layout_signature: dict[int, tuple[tuple[str, ...], ...]] = {}


def _transport_available_width(index: int) -> int:
    """The content width one transport row may use (the window's live width; e74s07c)."""
    window_tag = "sequencer_window" if index == 0 else SEQUENCER_B_WINDOW_TAG
    if not dpg.does_item_exist(window_tag):
        return TRANSPORT_ROW_DEFAULT_WIDTH  # built outside its window (a rig probe, a test)
    width = int(dpg.get_item_width(window_tag) or 0)
    if width <= 0:
        return TRANSPORT_ROW_DEFAULT_WIDTH  # not measurable yet (boot, tests)
    return max(TRANSPORT_ROW_MIN_WIDTH, width - TRANSPORT_ROW_SIDE_PAD)


def transport_row_blocks() -> list[tuple[str, int]]:
    """The transport row's ATOMIC blocks and their widths (pure; e74s07c)."""
    buttons = (
        TRANSPORT_PLAY_W + 2 * TRANSPORT_NUDGE_W + TRANSPORT_RESYNC_W + 3 * TRANSPORT_BLOCK_GAP
    )
    blocks: list[tuple[str, int]] = [("transport", buttons)]
    for mode in (
        BEAT_SOURCE_ANALYSIS,
        BEAT_SOURCE_BAND1,
        BEAT_SOURCE_MIDI,
        BEAT_SOURCE_LINK,
        BEAT_SOURCE_MANUAL,
    ):
        blocks.append((f"beat:{mode}", SEQ_BEAT_BOX_WIDTHS[mode]))
    # e74s07d: the delete X is the SAME box as `R` (the operator asked for it).
    blocks.append(("delete", TRANSPORT_RESYNC_W))
    return blocks


def wrap_transport_blocks(available: int) -> list[list[str]]:
    """Greedy wrap of the blocks into lines that fit `available` px (pure; e74s07c).

    A block is never split: the buttons travel together and each beat box travels with its
    tools, so a narrow window produces more LINES, not a squeezed row.
    """
    lines: list[list[str]] = [[]]
    used = 0
    for name, width in transport_row_blocks():
        step = width if not lines[-1] else width + TRANSPORT_BLOCK_GAP
        if lines[-1] and used + step > available:
            lines.append([name])
            used = width
            continue
        lines[-1].append(name)
        used += step
    return lines


def _build_transport_block(index: int, record: Any, block: str) -> None:
    """Build ONE atomic block of a transport row (e74s07c)."""
    if block == "transport":
        _build_transport_buttons(index)
        return
    if block == "delete":
        # e74s07: the small delete `X`, replacing the wide bottom button.
        dpg.add_button(
            label="X",
            tag=sequencer_transport_tag(index, "btn_delete"),
            callback=on_sequencer_delete_click,
            user_data=index,
            width=TRANSPORT_RESYNC_W,
            height=TRANSPORT_BUTTON_H,
        )
        return
    _build_beat_box(index, record, block.split(":", 1)[1])


def relayout_transport_row(index: int) -> None:
    """Rebuild ONE transport row into wrapped lines when its WRAP changed (e74s07c).

    The signature gate is what makes a resize drag cheap: the greedy wrap changes at a few
    breakpoints, so most pixels of a drag re-use the existing widgets.
    """
    row_tag = f"{sequencer_prefix(index)}_transport_row"
    if not dpg.does_item_exist(row_tag):
        return
    lines = wrap_transport_blocks(_transport_available_width(index))
    signature = tuple(tuple(line) for line in lines)
    if _transport_layout_signature.get(index) == signature:
        return
    _transport_layout_signature[index] = signature
    dpg.delete_item(row_tag, children_only=True)
    record = state.sequencer(index)
    for line in lines:
        with dpg.group(horizontal=True, parent=row_tag):
            for block in line:
                _build_transport_block(index, record, block)


def tick_transport_layout() -> None:
    """Re-wrap every existing transport row when its window width changes (e74s07c)."""
    for index in range(state.sequencer_count()):
        relayout_transport_row(index)


def _build_transport_buttons(index: int) -> None:
    """PLAY, the two nudges and R of ONE instance (e67s04, e74s07c), each with its own tag."""
    dpg.add_button(
        label="PLAY",
        tag=sequencer_transport_tag(index, "btn_play"),
        callback=toggle_play,  # e33s04: marker captures (uniform), the button executes
        user_data=index,
        width=TRANSPORT_PLAY_W,
        height=TRANSPORT_BUTTON_H,
    )
    dpg.add_button(
        label="<",
        tag=sequencer_transport_tag(index, "btn_nudge_back"),
        callback=on_sequencer_nudge,
        user_data=(index, SEQ_NUDGE_STEP),
        width=TRANSPORT_NUDGE_W,
        height=TRANSPORT_BUTTON_H,
    )
    dpg.add_button(
        label="R",  # e74s07c: RESYNC shrank to a single R (space, and the tooltip says the rest)
        tag=sequencer_transport_tag(index, "btn_resync"),
        callback=on_sequencer_resync,
        user_data=index,
        width=TRANSPORT_RESYNC_W,
        height=TRANSPORT_BUTTON_H,
    )
    dpg.add_button(
        label=">",
        tag=sequencer_transport_tag(index, "btn_nudge_forward"),
        callback=on_sequencer_nudge,
        user_data=(index, -SEQ_NUDGE_STEP),
        width=TRANSPORT_NUDGE_W,
        height=TRANSPORT_BUTTON_H,
    )


def _build_beat_box(index: int, record: Any, mode: str) -> None:
    """ONE beat source in its own box with its tools (e67s04, e74s07, e75).

    The source rides in `user_data` as `(index, mode)` — a default argument is what DearPyGui's
    third positional overwrote (BUG-2026-10-12T230000). The box needs an explicit width: a
    child_window in a horizontal row fills the available width unless it is given one.
    """
    with (
        dpg.child_window(
            tag=beat_box_tag(index, mode),
            border=True,
            no_scrollbar=True,
            width=SEQ_BEAT_BOX_WIDTHS[mode],
            height=SEQ_BEAT_BOX_HEIGHT,
        ),
        dpg.group(horizontal=True),
    ):
        # e74s07: the theme's tight padding, so the row fits the box (no clipping).
        dpg.bind_item_theme(beat_box_tag(index, mode), theme_beat_box)
        dpg.add_checkbox(
            label=BEAT_SOURCE_LABELS[mode],
            tag=beat_checkbox_tag(index, mode),
            default_value=record["beat_source"] == mode,
            callback=on_sequencer_beat_source,
            user_data=(index, mode),
        )
        # The drawlist is as tall as the row, so the circle is vertically centred on
        # the checkbox/input line instead of riding its top edge.
        with dpg.drawlist(width=SEQ_BEAT_LED_W, height=SEQ_BEAT_LED_H):
            dpg.draw_circle(
                center=[SEQ_BEAT_LED_W / 2, SEQ_BEAT_LED_H / 2],
                radius=5,
                color=(0, 0, 0, 255),
                fill=(50, 50, 50, 255),
                tag=beat_led_tag(index, mode),
            )
        if mode == BEAT_SOURCE_ANALYSIS:
            # e74s07: the theme's text colour, like every other transport label.
            dpg.add_text("---", tag=sequencer_transport_tag(index, "testo_bpm"))
        elif mode == BEAT_SOURCE_LINK:
            # e75: the shared Link tempo (or `n/a` when the engine is absent).
            dpg.add_text("---", tag=sequencer_transport_tag(index, "link_tempo_text"))
        elif mode == BEAT_SOURCE_MANUAL:
            _build_manual_bpm(index, record)


def _build_manual_bpm(index: int, record: Any) -> None:
    """The manual BPM number, TAP and readout of ONE instance (e67s04, e74s07).

    ALWAYS visible (e74s07): the operator wants the tools in front of them whatever the
    selected source, so nothing here carries `show=` and no mode switch hides them.
    """
    dpg.add_input_int(
        default_value=int(record["bpm"]),
        min_value=30,
        max_value=300,
        width=70,
        tag=sequencer_transport_tag(index, "manual_bpm_input"),
        callback=on_sequencer_manual_bpm,
        user_data=index,
    )
    dpg.add_button(
        label="TAP",
        tag=sequencer_transport_tag(index, "btn_tap"),
        callback=tap_bpm,
        user_data=index,
        width=32,
        height=SEQ_BEAT_TAP_HEIGHT,
    )
    dpg.add_text("", tag=sequencer_transport_tag(index, "manual_bpm_text"))


def build_sequencer(
    rows: int,
    cols: int,
    level: int,
    prefix: str = SEQ_TAG_PREFIX,
    parent: str = "sequencer_window",
    index: int = 0,
) -> None:
    """(Re)create ONE sequencer at a geometry and a level, and make them ITS LIVE state.

    The ONE place a grid is born: it sanitizes what it is given, tears the old grid down
    safely (`destroy_sequencer_grid`) and builds the new one. Called at boot for a project's
    record and by the creation dialog's Create.

    e67s05: the shape belongs to the INSTANCE. Instance 0's record is a LIVE VIEW over the
    globals, so A writes what it always wrote; B writes its own record instead of clobbering
    A's live zoom (which the old global write did the moment two different sizes existed).
    """
    record = state.sequencer(index)
    record["rows"] = sanitize_geometry(rows)
    record["cols"] = sanitize_geometry(cols)
    record["zoom"] = sanitize_seq_zoom(level)
    record["step"] = -1  # a new instrument starts with no playhead
    state.mark_sequencer_created(index)
    destroy_sequencer_grid(prefix)
    create_sequencer_grid(
        record["rows"], record["cols"], record["zoom"], prefix=prefix, parent=parent, index=index
    )
    # The auto bindings cover the INTERSECTION of the device and the live geometry, so a new
    # shape needs them re-registered: without this a pad press would still toggle a step the
    # rebuilt grid does not have.
    reregister_grid_bindings()


# WINDOW 1: SEQUENCER (explicit tag so the layout save/restore can address it, e06)
with dpg.window(
    label="Step Sequencer A",
    width=1050,
    height=800,
    pos=(10, TOOLBAR_BAR_H),
    tag="sequencer_window",
):
    # e67s05: the shape is chosen at CREATION and then it stays (the operator's rule): the
    # e66 live Grid/Cells combos are GONE, because changing a sequencer means deleting it and
    # creating another. The dialog's Create is the only door to a shape.
    build_sequencer_transport(0, "sequencer_window")

    # e68: the grid lives in its OWN host so a grid built later does not land after the
    # transport row. e74s07: the delete is the `X` in the row, so the window no longer
    # carries a bottom button. e74s07b: no spacer — B's row sits closer to its steps and
    # the operator wants A to match it.
    with dpg.group(tag="seq_grid_host"):
        pass

    # e67s05: A is NO LONGER BUILT HERE. The boot builds it only when a project carries its
    # shape (`_apply_sequencer_state`), and otherwise the first opening asks for it — exactly as
    # B always did. The window still exists for the transport row and A's selectors, so a
    # project's record (or the dialog's Create) has a parent to build the grid into.

# WINDOW 2: AUDIO ANALYZER
input_devices_list = get_input_devices()

with dpg.window(
    label="Audio analyzer",
    width=350,
    height=316,  # e71s01: two more band rows
    pos=(10, 806),
    tag="audio_window",
):
    dpg.add_combo(
        items=input_devices_list, default_value=input_devices_list[0], tag="combo_devices", width=-1
    )
    dpg.add_checkbox(
        label="Enable Level Analysis (Spectrum)",
        tag="cb_spectrum_analysis",  # e28s03: stable tag for project restore
        callback=toggle_audio_stream,
        user_data="vu_meter",
    )
    dpg.add_spacer(height=2)
    with dpg.drawlist(width=SPEC_DRAWLIST_W, height=SPEC_DRAWLIST_H, tag="spec_drawlist"):
        for i in range(SPECTRUM_BARS):
            themed_draw_rectangle(
                pmin=(i * (SPEC_DRAWLIST_W / SPECTRUM_BARS) + 1, SPEC_DRAWLIST_H - 2),
                pmax=((i + 1) * (SPEC_DRAWLIST_W / SPECTRUM_BARS) - 1, SPEC_DRAWLIST_H - 2),
                color=(0, 0, 0, 0),
                slot="spectrum",
                tag=f"spec_bar_{i}",
            )
        for band_id, (fill, edge) in BAND_RECT_COLORS.items():
            dpg.draw_rectangle(
                pmin=(0, 2),
                pmax=(SPEC_DRAWLIST_W, SPEC_DRAWLIST_H - 2),
                color=edge,
                fill=fill,
                tag=f"band{band_id}_rect",
                show=False,
            )
        _build_band_labels()  # e71s02: the band number, inside its own rectangle
        # e50s01: the grab highlight — one line per band, moved onto the armed
        # edge by the mouse handlers (hidden until an edge is hovered/grabbed)
        for band_id, (_fill, edge) in BAND_RECT_COLORS.items():
            dpg.draw_line(
                p1=(0, 0),
                p2=(0, 0),
                color=edge,
                thickness=BAND_EDGE_HIGHLIGHT_THICKNESS,
                tag=f"band{band_id}_edge_hl",
                show=False,
            )
    # e50s01/e50s02: the band-rect drag. Mouse handlers are GLOBAL ONLY in DPG
    # 2.x (an item registry accepts just the item_* handlers; the real library
    # raises [1003] "Incompatible parent" otherwise), so the seam gates every
    # handler on the drawlist's own client rectangle (`_band_rect_hovered`).
    with dpg.handler_registry(tag=SPECTRUM_MOUSE_REG):
        dpg.add_mouse_down_handler(button=dpg.mvMouseButton_Left, callback=_band_rect_mouse_down)
        dpg.add_mouse_drag_handler(
            button=dpg.mvMouseButton_Left, threshold=0.0, callback=_band_rect_mouse_drag
        )
        dpg.add_mouse_release_handler(
            button=dpg.mvMouseButton_Left, callback=_band_rect_mouse_release
        )
        dpg.add_mouse_move_handler(callback=_band_rect_mouse_move)
    _build_band_rows()
    with dpg.group(horizontal=True):
        dpg.add_checkbox(
            label="Enable BPM Analysis (Essentia)",
            tag="cb_bpm_analysis",  # e28s03: stable tag for project restore
            callback=toggle_audio_stream,
            user_data="beat_tracking",
        )
    dpg.add_checkbox(
        label="Use Low-Pass Filter (kick only)",
        default_value=True,
        tag="cb_lowpass",
        callback=on_lowpass_toggle,
    )

# WINDOW 3: SETTINGS (hidden; opened from the toolbar "Settings" entry).
# e58s03 rework (user decision 2026-09-25): ONE configuration window holds
# everything, in this order: Project, Theme (colours on two columns), viOSC
# connections and OSC Configuration. e74s03 moved the raw source-data table out
# into its own Sources-data window, opened from the Vimix-sources toolbar.
with (
    dpg.window(
        label="General",
        width=900,
        height=860,
        pos=(370, 60),
        tag="settings_window",
        show=False,
    ),
    dpg.child_window(height=-1, border=False),
):
    # --- Project (e11s04) ---
    themed_text("Project", slot="text")
    dpg.add_separator()
    dpg.add_checkbox(
        label="Restore last project at startup",
        tag="cb_restore_project_boot",
        default_value=True,
        callback=on_restore_project_boot_toggle,
    )

    # --- Interface (e83: moved out of the Info window) ---
    dpg.add_spacer(height=8)
    themed_text("Interface", slot="text")
    dpg.add_separator()
    # e76s01: the hover-help switch. A VJ moves the mouse over controls while
    # performing, so the cards are switchable; the flag persists in the app config.
    # It is a DISPLAY preference, so it belongs in General, next to the theme.
    help_tooltip(
        dpg.add_checkbox(
            label="Show hover help",
            tag="help_hover_cb",
            default_value=state.hover_help,
            callback=on_toggle_hover_help,
        ),
        "ui.hover_help",
    )

    # --- Theme (e06s02): preset combo + five colour pickers on two columns ---
    dpg.add_spacer(height=8)
    themed_text("Theme", slot="text")
    dpg.add_separator()
    dpg.add_combo(
        items=["Dark", "Light", "Custom"],
        default_value="Dark",
        tag="theme_preset",
        width=150,
        callback=on_theme_preset,
    )
    with dpg.table(header_row=False, policy=dpg.mvTable_SizingStretchSame):
        dpg.add_table_column()
        dpg.add_table_column()
        for index in range(0, len(THEME_PRIMARY_SLOTS), 2):
            with dpg.table_row():
                for slot in THEME_PRIMARY_SLOTS[index : index + 2]:
                    dpg.add_color_edit(
                        label=THEME_PRIMARY_LABELS[slot],
                        default_value=palette_rgba(state.active_palette[slot]),
                        tag=f"theme_color_{slot}",
                        width=170,
                        callback=on_theme_color,
                        user_data=slot,
                    )

    # --- viOSC connections (the link: pairing + both OSC endpoints) ---
    dpg.add_spacer(height=8)
    themed_text("viOSC connections", slot="text")
    dpg.add_separator()
    with dpg.group(horizontal=True):
        help_tooltip(
            dpg.add_button(label="Pair with viOSC", callback=show_pairing_prompt),
            "settings.pair",
        )
        # e58s03: green while viOSC state flows, red when the link is silent.
        with dpg.drawlist(width=14, height=14):
            dpg.draw_circle(
                center=[7, 7],
                radius=5,
                color=(0, 0, 0, 255),
                fill=VIOSC_LED_DOWN_RGBA,
                tag=VIOSC_LED_TAG,
            )
        with dpg.group(tag="settings_pairing_learn_slot"):
            pass
    dpg.add_text("client OSC (to viOSC):")
    with dpg.group(horizontal=True):
        dpg.add_input_text(default_value="127.0.0.1", tag="viosc_ip", width=120)
        dpg.add_input_int(default_value=6666, tag="viosc_port", width=80, step=0)
        help_tooltip(
            dpg.add_button(label="Connect Client", callback=connect_to_viosc),
            "settings.client_connect",
        )
        themed_text("Client Status: Waiting", slot="text_dim", tag="viosc_status")
    dpg.add_text("OSC Server (from viOSC):")
    with dpg.group(horizontal=True):
        dpg.add_input_text(default_value="127.0.0.1", tag="listen_ip", width=120)
        dpg.add_input_int(default_value=VIOSC_LISTEN_PORT, tag="listen_port", width=80, step=0)
        dpg.add_button(label="Start Server", tag="btn_server_toggle", callback=toggle_local_server)
        themed_text("Server Status: Stopped", slot="text_dim", tag="server_status")

    # --- viOSC configuration: the remote settings ---
    dpg.add_spacer(height=8)
    themed_text("viOSC configuration", slot="text")
    dpg.add_separator()
    with dpg.group(horizontal=True):
        help_tooltip(
            dpg.add_button(label="Load", callback=load_viosc_config), "settings.viosc_load"
        )
        help_tooltip(
            dpg.add_button(label="Save", callback=save_viosc_config), "settings.viosc_save"
        )
        help_tooltip(
            dpg.add_button(label="Restart viOSC", callback=restart_viosc),
            "settings.viosc_restart",
        )
    # e58s03: shown only when there is something to say (errors / the report).
    themed_text("", slot="text_dim", tag=VIOSC_CFG_STATUS_TAG, show=False)
    dpg.add_group(tag=VIOSC_CFG_FIELDS_TAG)


# WINDOW 4: VIMIX MEDIA
with (
    dpg.window(
        label="Vimix sources",
        # e83 fix: 4 tiles (4 x 137 = 548 px) + MEDIA_GRID_MARGIN 26 = 574, rounded
        # up. At 550 the 4th tile never fit and the window showed a ~110 px strip on
        # the right; a resize still leaves a remainder of at most one tile.
        width=580,
        height=690,
        pos=(1100, TOOLBAR_BAR_H),
        tag="vimix_media_window",
    ),
    dpg.group(tag="vimix_media_group"),
    # e74s02: the persistent browsing toolbar. `<`/`>` dispatch the SAME actions the
    # MIDI controllers drive (one implementation, one gate); `Sources data` opens the
    # raw viOSC table. The rebuilt grid always lands below this row.
    dpg.group(horizontal=True, tag=SOURCES_TOOLBAR_TAG),
):
    help_tooltip(
        dpg.add_button(label="<", tag=SOURCES_TOOLBAR_PREV_TAG, callback=on_sources_browse_prev),
        "sources.browse_prev",
    )
    help_tooltip(
        dpg.add_button(label=">", tag=SOURCES_TOOLBAR_NEXT_TAG, callback=on_sources_browse_next),
        "sources.browse_next",
    )
    # e74s10: make the SELECTED source current in vimix — the same action the MIDI
    # binding runs (`set_current`), so the button and the controller share one path.
    set_btn = dpg.add_button(
        label="Set", tag=SOURCES_TOOLBAR_SET_TAG, callback=on_sources_set_current
    )
    help_tooltip(set_btn, "sources.set_current")  # e76: one card path, 2 s, switchable
    help_tooltip(
        dpg.add_button(
            label="Sources data",
            tag=SOURCES_DATA_BUTTON_TAG,
            callback=toggle_sources_data_window,
        ),
        "sources.data",
    )

# WINDOW 4b: SOURCES DATA (e74s03; hidden until opened from the Vimix-sources toolbar).
# The raw viOSC state table lived at the bottom of Settings until e74s03.
with dpg.window(
    label="Sources data",
    width=SOURCES_DATA_WINDOW_WIDTH,
    height=SOURCES_DATA_WINDOW_HEIGHT,
    pos=(370, 60),
    tag=SOURCES_DATA_WINDOW_TAG,
    show=False,
):
    # e82s08: the EXPLICIT refresh. The tier's properties are already live; this
    # button asks for the rest, ONCE — nothing is swept automatically on open.
    with dpg.group(horizontal=True):
        help_tooltip(
            dpg.add_button(
                label="Refresh all",
                tag=SOURCES_DATA_REFRESH_TAG,
                callback=on_sources_data_refresh,
            ),
            "sources.refresh_all",
        )
        dpg.add_group(tag=SOURCES_DATA_LEARN_SLOT)
        themed_text("", slot="text_dim", tag=SOURCES_DATA_STATUS_TAG)
    # the table is built here by update_vimix_sources_ui and deleted/rebuilt on a
    # signature change; the toolbar above lives OUTSIDE it.
    with dpg.group(tag=SOURCES_DATA_GROUP_TAG):
        pass

# WINDOW 5: OSC LOGS (hidden; opened from the menubar "Show" > "Logs")
with dpg.window(label="Logs", width=950, height=170, pos=(720, 820), tag="logs_window", show=False):
    # e81: the SYSTEM window — boot, config, links, decisions, failures. Traffic (OSC and
    # MIDI, both directions) lives in the I/O Monitor; a line here never repeats a message.
    with dpg.group(horizontal=True):
        themed_text("Level", slot="text_dim")
        dpg.add_combo(
            items=list(_LOG_LEVEL_LABELS),
            default_value="All levels",
            width=120,
            tag="log_level_combo",
            callback=on_log_level,
        )
        dpg.add_button(label="Pause", tag="log_pause_btn", callback=toggle_log_pause)
        dpg.add_button(label="Clear", tag="log_clear_btn", callback=clear_logs)
        dpg.add_button(label="Copy", tag="log_copy_btn", callback=copy_logs)
        themed_text("", slot="text_dim", tag="log_status")
    # e38 UAT (user, 2026-09-07): the log must be selectable/copyable — a
    # readonly multiline input (ImGui readonly still allows mouse selection
    # and Ctrl+C); a plain text item cannot be copied.
    dpg.add_input_text(
        default_value="",
        multiline=True,
        readonly=True,
        width=930,
        height=126,
        tag="osc_log_text",
    )


def _build_help_logo() -> None:
    """The Info window's brand mark, centered by LAYOUT (e08s03).

    A fixed left indent used to guess the dialog's inner width, so the mark drifted off
    centre as soon as the content region stopped matching that guess (theme padding, a
    scrollbar). Two equal stretch columns around a fixed-width centre put the mark in the
    middle of whatever width the dialog actually has.
    """
    if _help_logo_texture is None:
        themed_text("VJmix", slot="text_bright")  # missing logo asset: textual fallback
        return
    with dpg.table(
        tag="help_logo_table",
        header_row=False,
        borders_innerH=False,
        borders_innerV=False,
        borders_outerH=False,
        borders_outerV=False,
        no_pad_outerX=True,
        no_pad_innerX=True,
        policy=dpg.mvTable_SizingStretchProp,
        width=-1,
    ):
        dpg.add_table_column(init_width_or_weight=1.0, width_stretch=True)
        dpg.add_table_column(init_width_or_weight=HELP_LOGO_WIDTH, width_fixed=True)
        dpg.add_table_column(init_width_or_weight=1.0, width_stretch=True)
        with dpg.table_row():
            dpg.add_spacer()
            dpg.add_image(
                _help_logo_texture,
                tag="help_logo_image",
                width=HELP_LOGO_WIDTH,
                height=HELP_LOGO_HEIGHT,
            )
            dpg.add_spacer()


# e83: the FontAwesome face (and its private-use range) is needed by the Info
# window's donation glyph, which is built BEFORE the toolbar: the loader lives
# here, early, and the toolbar's own call is a no-op once it has run.
TOOLBAR_ICON_FONT_SIZE = 16
TOOLBAR_ICON_FONT_PATHS: tuple[str, ...] = (
    str(Path(__file__).resolve().parent / "vjmixapp" / "assets" / "fontawesome-webfont.ttf"),
    "/usr/share/fonts/truetype/font-awesome/fontawesome-webfont.ttf",
    "/usr/share/fonts/opentype/font-awesome/FontAwesome.otf",
)
toolbar_icon_font: Any = None


def load_toolbar_icon_font() -> Any:
    """Register the FontAwesome font (with its private-use range) or None (e46s01).

    DearPyGui renders NOTHING for the icon codepoints unless the 0xF000-0xF3FF
    range is added to the font, and each button needs `bind_item_font`; when no
    font is found the toolbar falls back to text labels. The result is stored in
    the module global `toolbar_icon_font` (the builder reads it).
    """
    global toolbar_icon_font
    for path in TOOLBAR_ICON_FONT_PATHS:
        if not os.path.exists(path):
            continue
        try:
            with dpg.font_registry():
                font = dpg.add_font(path, size=TOOLBAR_ICON_FONT_SIZE)
                dpg.add_font_range(0xF000, 0xF3FF, parent=font)
            toolbar_icon_font = font
            return font
        except Exception as exc:  # a broken font must never block the boot
            log_error("Toolbar icon font", f"{path}: {exc!r}")
    toolbar_icon_font = None
    return None


load_toolbar_icon_font()  # e83: the Info window's donation glyph comes first

# WINDOW 6: HELP / ABOUT (hidden; opened from the menubar "Help", re-centered on open, e08)
with dpg.window(
    label="Info",
    width=HELP_WINDOW_WIDTH,
    height=HELP_WINDOW_HEIGHT,
    pos=(0, 0),
    tag="help_window",
    show=False,
    no_resize=True,  # e08s03: a fixed-content dialog keeps its shape
    no_collapse=True,
):
    dpg.add_spacer(height=8)
    _build_help_logo()
    dpg.add_spacer(height=6)
    themed_text("VJmix - VJ Controller for Vimix", slot="text_bright")
    dpg.add_separator()
    themed_text(f"Version: {APP_VERSION}", slot="text")
    themed_text("License: GPL-3.0", slot="text")
    themed_text("Created by: Luca Franceschini aka Lupin3rd", slot="text")
    dpg.add_button(label=f"GitHub: {GITHUB_URL}", callback=open_github)
    dpg.add_separator()
    # e83: a donation link, with the FontAwesome coffee cup (U+F0F4). The glyph is
    # its own text item because the button label must stay in the UI font.
    themed_text("Support VJmix", slot="text")
    with dpg.group(horizontal=True):
        donate_icon = dpg.add_text(
            "\uf0f4", color=palette_rgba(state.active_palette["accent"]), tag="help_donate_icon"
        )
        if toolbar_icon_font is not None:
            dpg.bind_item_font(donate_icon, toolbar_icon_font)
        help_tooltip(
            dpg.add_button(label="Buy me a coffee", callback=open_donation),
            "help.donate",
        )

# WINDOW 7: MIDI (hidden; opened from the menubar "MIDI"). ALL MIDI features live here:
# enable toggle, controller selection, MIDI Learn and the mappings list (e09s02, user
# revision — no scattered menu items).
try:
    import mido as _mido

    _midi_input_devices: list[str] = list(_mido.get_input_names())
except Exception:
    _midi_input_devices = []

with dpg.window(label="MIDI", width=520, height=520, pos=(560, 320), tag="midi_window", show=False):
    dpg.add_checkbox(
        label="Enable MIDI",
        tag="midi_enable_cb",
        default_value=state.midi_enabled,
        callback=on_midi_enable,
    )
    dpg.add_separator()
    dpg.add_spacer(height=4)
    # e14s03: Controllers section — add any available input port, list the connected
    # controllers (profile auto-detected, grid role, remove), bindings per controller.
    themed_text("Controllers", slot="text")
    # BUG-2026-09-07: input-scan outcome line — shows the ALSA failure instead of
    # presenting a silent empty device list when the sequencer is exhausted.
    themed_text("", slot="text_dim", tag="midi_ports_status")
    with dpg.group(horizontal=True):
        dpg.add_combo(items=available_controller_ports(), tag="midi_add_combo", width=320)
        help_tooltip(
            dpg.add_button(
                label="Add",
                callback=lambda: add_controller_from_port(str(dpg.get_value("midi_add_combo"))),
                width=60,
            ),
            "midi.add_controller",
        )
        help_tooltip(
            dpg.add_button(label="Refresh", callback=refresh_midi_devices, width=80),
            "midi.refresh",
        )
    with (
        dpg.child_window(height=120, tag="midi_controllers_scroll"),
        dpg.group(tag="midi_controllers_group"),
    ):
        pass
    dpg.add_separator()
    dpg.add_spacer(height=4)
    # e52s01: Modes — named, additive layers. Create/delete by name here; each
    # row's red M captures MODE_TOGGLE{mode} while MIDI Learn is on.
    themed_text("Modes", slot="text")
    with dpg.group(horizontal=True):
        dpg.add_input_text(tag=MIDI_MODE_NAME_INPUT_TAG, width=200)
        dpg.add_button(
            label="Add", tag=MIDI_MODE_ADD_BUTTON_TAG, callback=on_add_midi_mode, width=60
        )
    dpg.add_text("", tag=MIDI_MODE_STATUS_TAG)
    with (
        dpg.child_window(height=110, tag=MIDI_MODES_SCROLL_TAG),
        dpg.group(tag=MIDI_MODES_GROUP_TAG),
    ):
        pass
    dpg.add_separator()
    dpg.add_spacer(height=4)
    themed_text("Bindings", slot="text")
    dpg.add_button(
        label="Learn mapping...", tag="midi_learn_btn", callback=toggle_midi_learn, width=150
    )
    dpg.add_text("", tag="midi_learn_status")
    # e33s05: the global actions (window show + project) live in their own panel.
    help_tooltip(
        dpg.add_button(label="Map global actions...", callback=show_map_actions_window, width=200),
        "midi.global_actions",
    )
    dpg.add_separator()
    dpg.add_spacer(height=4)
    with (
        dpg.child_window(height=160, tag="midi_mappings_scroll"),
        dpg.group(tag="midi_mappings_group"),
    ):
        pass
    # BUG-2026-09-18T194658: no Save button here. Every mutation of this window
    # (enable, add/remove a controller, the grid role, learn, delete, a monitor
    # bind) calls save_midi_controllers() at the moment it happens, so a manual
    # save only re-wrote identical data — and pressing it after opening a project
    # leaked that project's Mapper bindings into the global config.

# WINDOW 7b: MAP ACTIONS (e33s05; hidden, opened from the MIDI window). One row
# per global action with the uniform red-M marker while MIDI Learn is on.
with dpg.window(
    label="Map actions",
    width=360,
    height=380,
    pos=(560, 320),
    tag=MAP_ACTIONS_WINDOW_TAG,
    show=False,
):
    themed_text("Arm an action, then press a MIDI control.", slot="text_dim")
    dpg.add_separator()
    with (
        dpg.child_window(height=300, tag=f"{MAP_ACTIONS_WINDOW_TAG}_scroll"),
        dpg.group(tag=MAP_ACTIONS_ROWS_TAG),
    ):
        pass
_sync_map_actions_panel()


# WINDOW 8: Leap Motion (hidden; opened from Settings > "Leap Motion"). One
# window hosts EVERYTHING (user request, e26s02): the Enable switch, the
# device/service status line and the LIVE two-hand value monitor — static rows
# built ONCE at construction (one row per snapshot field, both hands), refreshed
# by tick_leap_monitor on the main thread. e26s04 adds the embedded visualizer
# toggle + hidden panel between the status line and the monitor; the window stays
# COMPACT (560x680, never widens — user decision). Never touches the external
# leap package at import time.
# e48s02 (user request): the monitor is FOUR columns — each hand on two — built
# directly in the window with no inner scroll box, so the window's own scrollbar
# is the only one.

# e26s04: compact visualizer layout. The always-present toggle row costs the
# monitor ~25 px; the 150-tall panel costs a further ~165 px, absorbed by the
# window scrollbar (e48s02).
LEAP_VIZ_PANEL_H: int = 158
with dpg.window(
    label="Leap Motion", width=560, height=680, pos=(560, 300), tag="leap_window", show=False
):
    dpg.add_checkbox(
        label="Enable Leap Motion",
        tag="leap_enable_cb",
        default_value=state.leap_enabled,
        callback=on_leap_enable,
    )
    # BUG-2026-09-18T212400: recovery control. The worker rebuilds its connection on
    # the generation bump, so a stuck engine never needs an app restart.
    dpg.add_button(
        label="Restart engine",
        tag="leap_restart_btn",
        callback=on_leap_restart,
        enabled=state.leap_enabled,
    )
    dpg.add_separator()
    dpg.add_spacer(height=4)
    dpg.add_text("", tag="leap_status_text")
    # e48: tracking frame rate (diagnostics; per frame, not per hand).
    dpg.add_text("", tag="leap_fps_text")
    dpg.add_spacer(height=4)
    dpg.add_separator()
    dpg.add_checkbox(
        label="Show device view + hands",
        tag="leap_viz_cb",
        default_value=state.leap_visualizer,
        callback=on_leap_visualizer,
    )
    with dpg.child_window(height=LEAP_VIZ_PANEL_H, show=False, tag="leap_viz_panel"):
        dpg.add_text("Waiting for the Leap device...", tag="leap_viz_wait_text")
    with dpg.group(horizontal=True, tag="leap_monitor_group"):
        for hand in leap.LEAP_HANDS:
            for column_index, column in enumerate(leap.monitor_columns()):
                with dpg.group(tag=f"leap_mon_{hand}_col{column_index + 1}"):
                    themed_text(leap.monitor_column_title(hand, column_index), slot="text_bright")
                    for field in column:
                        with dpg.group(horizontal=True):
                            themed_text(leap.monitor_label(field), slot="text_dim")
                            dpg.add_text(
                                leap.LEAP_MONITOR_PLACEHOLDER,
                                tag=f"leap_mon_{hand}_{field}",
                            )

# e16/e22/e23/e24: Mapper window — the body is rebuilt by refresh_mapper_ui()
# (menu open, create, delete, prune, resize) as a stack of wrapping source
# blocks. Hidden at boot and never part of the saved layout (transient
# workspace, like Logs).
# e20s02: only the mapping blocks — no header line, and the scroll container is
# borderless so no outer frame wraps the content.
# e23: compact theme (theme_mapper_compact).
# e24s02: sources WRAP onto multiple lines (no overflow), so the scroll child
# keeps NO horizontal_scrollbar (DPG would force both scrollbar tracks) and its
# vertical scrollbar appears only when the wrapped content is taller than the
# window. A resize item handler reflows the body live.
with (
    dpg.window(
        label="Mapper",
        width=MAPPER_WINDOW_WIDTH,
        height=MAPPER_WINDOW_HEIGHT,
        pos=(60, 60),
        tag="mapper_window",
        show=False,
    ),
    dpg.child_window(
        height=MAPPER_SCROLL_HEIGHT,
        border=False,
        tag="mapper_scroll",
    ),
):
    # e40s01: the section chips + New Mapping sit above the body inside the scroll
    with dpg.group(horizontal=True, tag="mapper_filter_group"):
        themed_text("Show", slot="text_dim")
        dpg.add_checkbox(
            label="Control",
            tag="mapper_filter_control",
            default_value=True,
            callback=on_mapper_filter,
        )
        dpg.add_checkbox(
            label="State", tag="mapper_filter_get", default_value=True, callback=on_mapper_filter
        )
        dpg.add_checkbox(
            label="Clock+Constant",
            tag="mapper_filter_global",
            default_value=True,
            callback=on_mapper_filter,
        )
        # e40s11/e40s12: the GENERAL creator lives here, set apart from the
        # Show chips and captioned, so it reads as an action and not a filter;
        # the '+' of a line and of the Clock+Constant line stay contextual.
        dpg.add_spacer(width=MAPPER_FILTER_ADD_GAP)
        dpg.add_button(
            label="+",
            width=MAPPER_ADD_W,
            height=MAPPER_ADD_H,
            callback=open_mapping_creator,
            tag="mapper_filter_add",
        )
        themed_text("New mapping", slot="text_dim")
        dpg.add_group(tag="mapper_filter_learn_slot", horizontal=True)
    # NOTE: a bare dpg.group(...) call does NOT create the item — the context
    # manager must be entered (dearpygui 2.x), same as the original tuple-with.
    with dpg.group(tag="mapper_mappings_group"):
        pass
dpg.bind_item_theme("mapper_window", theme_mapper_compact)
with dpg.item_handler_registry(tag="mapper_resize_reg"):
    # e24s02: reflow the wrapping body whenever the user resizes the window
    dpg.add_item_resize_handler(callback=lambda s, a: refresh_mapper_ui())
dpg.bind_item_handler_registry("mapper_window", "mapper_resize_reg")

# WINDOW: FILE MANAGER (e43s02) — browse machine A's Media Roots over the /fs
# data plane. A workspace window: LAYOUT_WINDOW_TAGS persists its pos/size/open.
with dpg.window(
    label="Sessions Manager",
    width=FILE_MANAGER_WIDTH,
    height=FILE_MANAGER_HEIGHT,
    pos=(30, 840),
    tag=FILE_MANAGER_TAG,
    show=False,
):
    with dpg.group(horizontal=True):
        dpg.add_combo(
            items=[],
            width=360,
            tag=FILE_MANAGER_ROOTS_TAG,
            callback=_on_fs_root_selected,
        )
        dpg.add_button(label="Up", callback=fs_go_up)
        dpg.add_button(label="Refresh", callback=fs_refresh)
        with dpg.group(tag=FILE_MANAGER_LEARN_SLOT, horizontal=True):
            pass
    themed_text("", slot="text_dim", tag=FILE_MANAGER_BREADCRUMB_TAG)
    with dpg.child_window(height=FILE_MANAGER_LIST_HEIGHT, border=False, tag="fs_scroll"):
        pass
    with dpg.group(parent="fs_scroll", tag=FILE_MANAGER_ENTRIES_TAG):
        pass
    themed_text("", slot="text_dim", tag=FILE_MANAGER_STATUS_TAG)
    dpg.add_separator(tag=FS_DRAFTS_SEPARATOR_TAG)
    themed_text("Session Drafts", slot="text")
    with dpg.group(horizontal=True):
        help_tooltip(dpg.add_button(label="New", callback=fs_new_draft), "sessions.new")
        dpg.add_button(label="Open...", callback=fs_open_sessions)
        dpg.add_button(label="Delete", callback=fs_delete_selected_draft)
        dpg.add_button(label="Rename", callback=fs_open_rename_draft)
        help_tooltip(dpg.add_button(label="Save", callback=fs_write_draft), "sessions.save")
        help_tooltip(dpg.add_button(label="Send to Vimix", callback=fs_load_draft), "sessions.send")
        with dpg.group(tag=FS_DRAFT_LEARN_SLOT, horizontal=True):
            pass
    themed_text("", slot="text_dim", tag=FS_DRAFT_STATUS_TAG)
    with dpg.group(tag=FS_DRAFTS_GROUP):
        pass
    with dpg.group(tag=FS_DRAFT_FILES_GROUP):
        pass

# NEW THREAD FOR HIGH-FREQUENCY FADES
threading.Thread(target=fade_tick_loop, daemon=True).start()
threading.Thread(target=fsclient.fs_thumb_worker, daemon=True).start()  # e43s03
threading.Thread(target=cue_tick_loop, daemon=True).start()  # e35s03: cue engine clock
threading.Thread(target=spectrum_analyzer_loop, daemon=True).start()
threading.Thread(target=midi_clock_loop, daemon=True).start()
threading.Thread(target=midi_control_loop, daemon=True).start()  # e09: control worker
threading.Thread(target=leap_control_loop, daemon=True).start()  # e26: leap worker

threading.Thread(target=sequencer_tick, daemon=True).start()
threading.Thread(target=visual_metronome_loop, daemon=True).start()
threading.Thread(target=essentia_analyzer_loop, daemon=True).start()
threading.Thread(target=thumbnail_decoder_worker, daemon=True).start()
threading.Thread(target=thumbnail_fetch_worker, daemon=True).start()  # e41s03 data plane
threading.Thread(target=state_poll_worker, daemon=True).start()  # e41s04 state pull
threading.Thread(target=streamlane.stream_worker, daemon=True).start()  # e82s04 delta stream

dpg.create_viewport(title="VJmix - VJ Controller for Vimix", width=1700, height=1080)
# e19/e37s04: closing the main window goes through the dirty-gated request — a
# clean session quits immediately, a dirty one opens the exit modal
# (disable_close keeps rendering on; the modal's Exit button stops the app).
dpg.set_exit_callback(request_exit)
dpg.configure_viewport("__viewport", disable_close=True)
apply_boot_config()  # e06: apply the saved theme + (optionally) the saved window layout
_drafts_load()  # e43s05: the application-level Session Drafts library
refresh_drafts_ui()
ensure_user_dirs()  # e21s01: eager XDG user dirs (config + projects) + legacy .vjmix migration

# ---------------------------------------------------------------------------
# e46s01: THE MAIN TOOLBAR — a flat row of FontAwesome icon buttons replacing the
# VJmix / Windows / Settings dropdowns (ADR-main-toolbar.md). Icon-only, with a
# tooltip per icon (name + shortcut) and a text fallback when the font is missing.
TOOLBAR_ICON_BUTTON_W = 32
TOOLBAR_ICON_BUTTON_H = 26
# e46 amendment: the brand mark is wider than an icon frame (the vector is 953:306, so
# 22 px tall is 68 px wide), and the bar width is computed per item (see
# _toolbar_item_width) instead of assuming every item is TOOLBAR_ICON_BUTTON_W.
TOOLBAR_BRAND_W = 68
TOOLBAR_BRAND_H = 22
# (kind, target, glyph, label, shortcut); kind: action | focus | toggle | mode | brand
type ToolbarItem = tuple[str, str, str, str, str]
TOOLBAR_ITEM_GROUPS: tuple[tuple[ToolbarItem, ...], ...] = (
    (
        ("action", "new_project", "\uf016", "New project", ""),
        ("action", "open_project", "\uf115", "Open project", ""),
        ("action", "save_project", "\uf0c7", "Save", ""),
        ("action", "save_project_as", "\uf044", "Save as...", ""),
        ("action", "last_project", "\uf1da", "Last project", ""),
    ),
    (
        # e68 (operator): the working set reads left to right in the order the operator works —
        # sources, then the two sequencers, then the tools. The POSITION identifies A and B.
        ("toggle", "vimix_media_window", "\uf108", "Vimix sources", ""),
        ("toggle", "sequencer_window", "\uf00a", "Step Sequencer A", ""),
        ("toggle", SEQUENCER_B_WINDOW_TAG, "\uf00a", "Step Sequencer B", ""),
        ("toggle", "mapper_window", "\uf0ce", "Mapper", ""),
        ("toggle", "shader_window", "\uf121", "Shader", ""),
        ("toggle", "text_window", "\uf031", "Text", ""),
        ("toggle", "file_manager_window", "\uf07b", "Sessions Manager", ""),
        ("toggle", "audio_window", "\uf080", "Audio analyzer", ""),
    ),
    (
        ("toggle", "settings_window", "\uf013", "Settings", ""),
        ("toggle", "midi_window", "\uf11c", "MIDI", ""),
        ("mode", "midi_learn", "\uf140", "MIDI Learn", ""),
        ("toggle", "leap_window", "\uf256", "Leap Motion", ""),
        # e55: the I/O Monitor is not a workspace window; its icon joins the
        # configuration block on the right.
        ("toggle", "io_monitor_window", "\uf0ec", "I/O Monitor", ""),
        # e68 (operator): Logs CLOSES the menu, right before the brand mark.
        ("toggle", "logs_window", "\uf0ca", "Logs", ""),
    ),
    # e46 amendment (2026-10-03, user request): the bar's rightmost control is the brand
    # mark — a small monochrome image button that OPENS the Info window (no toggle, and
    # deliberately no Mapper action: user decision). If the asset is missing the build
    # falls back to the FontAwesome Info icon, so the destination is never lost.
    (("brand", "help_window", "\uf05a", "Info", ""),),
)
TOOLBAR_RECENTS_TAG = "toolbar_recents_popup"
TOOLBAR_BAR_TAG = "main_toolbar_bar"
TOOLBAR_THEME_OPEN = "theme_toolbar_open"
TOOLBAR_THEME_ACTIVE = "theme_toolbar_active"
TOOLBAR_THEME_FLAT = "theme_toolbar_flat"
TOOLBAR_THEME_PLAIN = "theme_toolbar_plain"
TOOLBAR_THEME_LEARN = "theme_toolbar_learn"
TOOLBAR_BAR_MARGIN_RIGHT = 4
TOOLBAR_ITEM_SPACING = 4
TOOLBAR_BAR_PAD_X = 4
TOOLBAR_BAR_PAD_Y = 3
TOOLBAR_GROUP_GAP = 10
# e47: the MIDI Learn mode item. The button tag mirrors `_toolbar_button_tag("mode",
# "midi_learn")` — a test locks the two together — and the tooltip's text item is
# tagged so the paint can reword it as the engine state changes.
TOOLBAR_LEARN_BUTTON_TAG = "toolbar_mode_midi_learn"
TOOLBAR_LEARN_TOOLTIP_TEXT_TAG = f"{TOOLBAR_LEARN_BUTTON_TAG}_tooltip_text"
# ASCII only: ProggyClean renders U+2014 EM DASH as a fallback glyph, not a dash
# (BUG-2026-09-18T193805; the e13s01 convention).
TOOLBAR_LEARN_TIP_READY = "MIDI Learn: arm, then click a control to bind (Ctrl+M)"
TOOLBAR_LEARN_TIP_CANCEL = "Cancel MIDI Learn (Ctrl+M)"
TOOLBAR_LEARN_TIP_UNAVAILABLE = "MIDI Learn: enable MIDI first"

# e52s07: the keyboard entry point the e47 ADR reserved. Edge-triggered, so a
# held chord toggles once, and guarded while a text input has focus.
MIDI_LEARN_SHORTCUT_KEY = dpg.mvKey_M
_midi_learn_shortcut_held = False
_toolbar_geom_sig: tuple[int, int] | None = None


def _toolbar_button_tag(kind: str, target: str) -> str:
    return f"toolbar_{kind}_{target}"


def _toolbar_item_text(item: ToolbarItem) -> str:
    """The icon glyph, or the text label when the icon font is unavailable."""
    return item[2] if toolbar_icon_font is not None else item[3]


def _show_and_focus(tag: str) -> None:
    """Show + focus a workspace window (a toolbar toggle target, e46s01)."""
    dpg.show_item(tag)
    dpg.focus_item(tag)


def show_sequencer_window(*_args: Any) -> None:
    """Open the Step Sequencer A — ASKING for its shape the first time (e67s05)."""
    if state.needs_creation(0):
        open_creation_dialog(0)
        return
    _show_and_focus("sequencer_window")


def show_sequencer_b_window(*_args: Any) -> None:
    """Open Step Sequencer B — ASKING for its shape the first time (e68)."""
    if state.needs_creation(1):
        open_creation_dialog(1)
        return
    _show_and_focus(SEQUENCER_B_WINDOW_TAG)


def show_audio_window(*_args: Any) -> None:
    """Open the Audio analyzer (a toggle window since e46s01)."""
    _show_and_focus("audio_window")


def show_vimix_window(*_args: Any) -> None:
    """Open the Vimix sources grid (a toggle window since e46s01)."""
    _show_and_focus("vimix_media_window")


def _toolbar_show_func(target: str) -> Any:
    """The show function of a toolbar window target."""
    return {
        "sequencer_window": show_sequencer_window,
        SEQUENCER_B_WINDOW_TAG: show_sequencer_b_window,
        "audio_window": show_audio_window,
        "vimix_media_window": show_vimix_window,
        "mapper_window": show_mapper_window,
        "logs_window": show_logs_window,
        "io_monitor_window": show_io_monitor,
        "file_manager_window": show_file_manager_window,
        SOURCES_DATA_WINDOW_TAG: show_sources_data_window,
        "text_window": show_text_window,
        "shader_window": show_shader_window,
        "settings_window": show_settings_window,
        "midi_window": show_midi_window,
        "leap_window": show_leap_window,
        "help_window": show_help_window,
    }.get(target)


def _toolbar_window_items() -> list[ToolbarItem]:
    """The toolbar items that address a window (focus or toggle)."""
    return [
        item for group in TOOLBAR_ITEM_GROUPS for item in group if item[0] in ("focus", "toggle")
    ]


def _toolbar_shown_signature() -> tuple[str, ...]:
    """The BAR's open windows, as the per-frame repaint gate (BUG-2026-09-19T003052).

    Built from the bar's own window items, not from the Ctrl+Tab list: every
    icon must repaint when its window opens or closes, and the Ctrl+Tab list
    holds only the workspace windows.
    """
    return tuple(
        target
        for _kind, target, _glyph, _label, _shortcut in _toolbar_window_items()
        if dpg.does_item_exist(target) and dpg.is_item_shown(target)
    )


def _toolbar_item_width(item: ToolbarItem) -> int:
    """The frame width one item occupies (the brand mark is wider than an icon)."""
    return TOOLBAR_BRAND_W if item[0] == "brand" else TOOLBAR_ICON_BUTTON_W


def toolbar_bar_width() -> int:
    """The exact width of the icon row (e46s01).

    `autosize` did NOT fit the window to the icons on the rig (it stayed almost
    viewport-wide, whose bottom border read as a full-width line), so the width
    is computed from the items and the spacing/padding the plain theme sets.
    """
    items = [item for group in TOOLBAR_ITEM_GROUPS for item in group]
    buttons = len(items)
    separators = len(TOOLBAR_ITEM_GROUPS)
    frames = sum(_toolbar_item_width(item) for item in items)
    frames += separators * TOOLBAR_GROUP_GAP
    gaps = max(0, buttons + separators - 1) * TOOLBAR_ITEM_SPACING
    # e52s06: the badge strip lives in its OWN window (see
    # _build_mode_badges_window); the bar keeps its exact e46 shape.
    return frames + gaps + 2 * TOOLBAR_BAR_PAD_X


def reposition_toolbar() -> None:
    """Anchor the toolbar to the top-RIGHT of the viewport (e46s01)."""
    if not dpg.does_item_exist(TOOLBAR_BAR_TAG):
        return
    width = int(dpg.get_item_width(TOOLBAR_BAR_TAG) or 0)
    client = int(dpg.get_viewport_client_width() or 0)
    if width <= 0 or client <= 0:
        return
    dpg.set_item_pos(
        TOOLBAR_BAR_TAG, (max(0, client - width - TOOLBAR_BAR_MARGIN_RIGHT), TOOLBAR_BAR_POS[1])
    )


def _toolbar_color(slot: str, alpha: int) -> tuple[int, int, int, int]:
    """A palette colour with an explicit alpha, for the accent highlights (e46s01)."""
    red, green, blue, _ = palette_rgba(state.active_palette[slot])
    return (red, green, blue, alpha)


def _build_main_toolbar() -> None:
    """Build the flat icon bar (called once, at the menubar position).

    The buttons are FLAT: no frame, no background, no border, so only the glyph
    shows (the aligned frame top edges read as a "line" on the rig). The accent
    marks an open window (soft) and the active one (full).
    """
    with dpg.theme(tag=TOOLBAR_THEME_FLAT), dpg.theme_component(dpg.mvThemeCat_Core):
        dpg.add_theme_color(dpg.mvThemeCol_Button, (0, 0, 0, 0))
        dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, _toolbar_color("accent", 80))
        dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, _toolbar_color("accent", 140))
        dpg.add_theme_color(dpg.mvThemeCol_Border, (0, 0, 0, 0))
        # e47: the MIDI Learn icon greys out while the MIDI engine is off; the
        # disabled text colour is palette-driven so it re-themes with the palette
        # instead of falling back to an ImGui default on the transparent bar.
        theme_color(dpg.mvThemeCol_TextDisabled, "text_dim")
        dpg.add_theme_style(dpg.mvStyleVar_FrameBorderSize, 0)
        dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 0)
    with dpg.theme(tag=TOOLBAR_THEME_OPEN), dpg.theme_component(dpg.mvThemeCat_Core):
        dpg.add_theme_color(dpg.mvThemeCol_Button, _toolbar_color("accent", 110))
        dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, _toolbar_color("accent", 150))
        dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, _toolbar_color("accent", 150))
        dpg.add_theme_color(dpg.mvThemeCol_Border, (0, 0, 0, 0))
        dpg.add_theme_color(dpg.mvThemeCol_BorderShadow, (0, 0, 0, 0))
        dpg.add_theme_style(dpg.mvStyleVar_FrameBorderSize, 0)
        dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 0)
    with dpg.theme(tag=TOOLBAR_THEME_ACTIVE), dpg.theme_component(dpg.mvThemeCat_Core):
        dpg.add_theme_color(dpg.mvThemeCol_Button, _toolbar_color("accent", 255))
        dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, _toolbar_color("accent", 255))
        dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, _toolbar_color("accent", 255))
        dpg.add_theme_color(dpg.mvThemeCol_Border, (0, 0, 0, 0))
        dpg.add_theme_color(dpg.mvThemeCol_BorderShadow, (0, 0, 0, 0))
        dpg.add_theme_style(dpg.mvStyleVar_FrameBorderSize, 0)
        dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 0)
    with dpg.theme(tag=TOOLBAR_THEME_LEARN), dpg.theme_component(dpg.mvThemeCat_Core):
        # e47: the MIDI Learn ON state wears the shared learn red on its button
        # background. Deliberately NOT the accent — the full accent means "this
        # window is active" on the icons next to it (ADR-midi-learn-entry-point).
        dpg.add_theme_color(dpg.mvThemeCol_Button, MIDI_LEARN_RED_RGBA)
        dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, MIDI_LEARN_RED_RGBA)
        dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, MIDI_LEARN_RED_RGBA)
        dpg.add_theme_color(dpg.mvThemeCol_Border, (0, 0, 0, 0))
        dpg.add_theme_color(dpg.mvThemeCol_BorderShadow, (0, 0, 0, 0))
        dpg.add_theme_style(dpg.mvStyleVar_FrameBorderSize, 0)
        dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 0)
    # The toolbar window is fully plain: no background, no 1px window border
    # (the rig line above the icons), a small padding.
    with dpg.theme(tag=TOOLBAR_THEME_PLAIN), dpg.theme_component(dpg.mvThemeCat_Core):
        dpg.add_theme_color(dpg.mvThemeCol_WindowBg, (0, 0, 0, 0))
        dpg.add_theme_color(dpg.mvThemeCol_ChildBg, (0, 0, 0, 0))
        dpg.add_theme_color(dpg.mvThemeCol_PopupBg, (0, 0, 0, 0))
        dpg.add_theme_color(dpg.mvThemeCol_MenuBarBg, (0, 0, 0, 0))
        dpg.add_theme_color(dpg.mvThemeCol_TitleBg, (0, 0, 0, 0))
        dpg.add_theme_color(dpg.mvThemeCol_TitleBgActive, (0, 0, 0, 0))
        dpg.add_theme_color(dpg.mvThemeCol_TitleBgCollapsed, (0, 0, 0, 0))
        dpg.add_theme_color(dpg.mvThemeCol_Border, (0, 0, 0, 255))
        dpg.add_theme_color(dpg.mvThemeCol_BorderShadow, (0, 0, 0, 255))
        dpg.add_theme_style(dpg.mvStyleVar_WindowBorderSize, 1)
        dpg.add_theme_style(dpg.mvStyleVar_ChildBorderSize, 0)
        dpg.add_theme_style(dpg.mvStyleVar_WindowRounding, 0)
        dpg.add_theme_style(dpg.mvStyleVar_WindowPadding, TOOLBAR_BAR_PAD_X, TOOLBAR_BAR_PAD_Y)
        dpg.add_theme_style(dpg.mvStyleVar_ItemSpacing, TOOLBAR_ITEM_SPACING, 0)
    # BUG-2026-09-16T155639: a tooltip is a child window and inherited the bar's opaque
    # black frame. Since e76 the whole app has ONE tooltip theme — the help card — built
    # right after the context (HELP_THEME_TOOLTIP): it paints its own palette surface and
    # border, so the bar's frame can no longer leak in.
    # A compact, borderless, auto-sized toolbar WINDOW: the native viewport menu
    # bar always spans the full width and ignores item themes (probed), so it
    # cannot show "only the icons". This window is exactly as wide as the icons,
    # has no background/border, and the workspace windows start at TOOLBAR_BAR_H.
    with (
        dpg.window(
            # BUG-2026-09-19T005453: a label exists purely so ImGui's Ctrl+Tab
            # panel never renders the bar as "(Untitled)" (no title bar shows it).
            label="Toolbar",
            tag=TOOLBAR_BAR_TAG,
            no_title_bar=True,
            no_resize=True,
            no_move=True,
            no_scrollbar=True,
            no_collapse=True,
            no_background=True,
            no_bring_to_front_on_focus=True,
            no_saved_settings=True,
            no_scroll_with_mouse=True,
            width=toolbar_bar_width(),
            height=TOOLBAR_BAR_H,
            pos=TOOLBAR_BAR_POS,
        ),
        dpg.group(horizontal=True),
    ):
        for group in TOOLBAR_ITEM_GROUPS:
            for item in group:
                kind, target, _glyph, label, shortcut = item
                tag = _toolbar_button_tag(kind, target)
                if kind == "brand" and _toolbar_brand_texture is not None:
                    # e46 amendment: the monochrome brand mark replaces the Info icon as
                    # the rightmost control. An image button does not inherit the theme's
                    # text colour, so it is tinted from the palette and repainted with it
                    # (see _paint_toolbar_brand).
                    dpg.add_image_button(
                        _toolbar_brand_texture,
                        tag=tag,
                        width=TOOLBAR_BRAND_W,
                        height=TOOLBAR_BRAND_H,
                        tint_color=_toolbar_color("text", 255),
                        callback=on_toolbar_item,
                        user_data={"kind": kind, "target": target},
                    )
                else:
                    dpg.add_button(
                        label=_toolbar_item_text(item),
                        tag=tag,
                        width=TOOLBAR_ICON_BUTTON_W,
                        height=TOOLBAR_ICON_BUTTON_H,
                        callback=on_toolbar_item,
                        user_data={"kind": kind, "target": target},
                    )
                    if toolbar_icon_font is not None:
                        dpg.bind_item_font(tag, toolbar_icon_font)
                dpg.bind_item_theme(tag, TOOLBAR_THEME_FLAT)
                tooltip_tag = f"{tag}_tooltip"
                with dpg.tooltip(tag, tag=tooltip_tag, delay=HELP_HOVER_DELAY_S):
                    dpg.add_text(
                        f"{label} ({shortcut})" if shortcut else label,
                        # e47: tagged so the mode item's tooltip can reword itself
                        # as the engine state changes (see refresh_toolbar_learn_icon)
                        tag=f"{tooltip_tag}_text",
                    )
                dpg.bind_item_theme(tooltip_tag, HELP_THEME_TOOLTIP)
            dpg.add_spacer(width=TOOLBAR_GROUP_GAP)
    dpg.bind_item_theme(TOOLBAR_BAR_TAG, TOOLBAR_THEME_PLAIN)
    refresh_toolbar_learn_icon()  # e47: the learn item's boot state


def on_toolbar_item(sender: Any = None, app_data: Any = None, user_data: Any = None) -> None:
    """One toolbar icon: focus a window, toggle a window, or run a project action."""
    payload = user_data if isinstance(user_data, dict) else {}
    kind = str(payload.get("kind") or "")
    target = str(payload.get("target") or "")
    if kind == "focus":
        switch_to_window(None, None, target)
        return
    if kind == "toggle":
        show = _toolbar_show_func(target)
        if show is None:
            return
        # BUG-2026-09-19T002150: existence BEFORE the shown query. DearPyGui
        # raises [1005] for a tag with no item, and the I/O Monitor is built
        # lazily — an unguarded query aborted the callback on the first click.
        if dpg.does_item_exist(target) and dpg.is_item_shown(target):
            dpg.hide_item(target)
            return
        show()
        return
    if kind == "brand":
        # e46 amendment: the brand mark opens the Info window; it never toggles it
        # (user decision), so it is not part of the open/active accent machinery.
        show_help_window()
        return
    if kind == "mode":
        # e47: a global MODE switch (MIDI Learn). It is not a window and not a
        # binding target, so it runs the one shared toggle path.
        {"midi_learn": toggle_midi_learn}.get(target, lambda *_: None)()
        return
    {
        "new_project": request_new_project,
        "open_project": show_open_project_dialog,
        "save_project": save_current_project,
        "save_project_as": show_save_project_dialog,
        "last_project": show_recent_projects_popup,
        "pair": show_pairing_prompt,
    }.get(target, lambda *_: None)()


def _paint_toolbar_brand() -> None:
    """Tint the toolbar brand mark from the palette (e46 amendment).

    An image button keeps the tint it was created with, while the icons take the
    theme's text colour: re-applying the tint when the palette changes (the text
    colour is part of tick_toolbar's signature) keeps the mark in step with them.
    """
    if _toolbar_brand_texture is None:
        return
    tag = _toolbar_button_tag("brand", "help_window")
    if dpg.does_item_exist(tag):
        dpg.configure_item(tag, tint_color=_toolbar_color("text", 255))


def refresh_toolbar_icons() -> None:
    """Paint the open (soft) / active (full) accent on the window icons (e46s01).

    BUG-2026-09-19T003052: only an OPEN window wears an accent — state.current_window
    keeps a hidden window's tag, so "open" is checked before the active mark.
    """
    active = str(state.current_window or "")
    _paint_toolbar_brand()
    for kind, target, _glyph, _label, _shortcut in _toolbar_window_items():
        tag = _toolbar_button_tag(kind, target)
        if not dpg.does_item_exist(tag):
            continue
        is_open = dpg.does_item_exist(target) and bool(dpg.is_item_shown(target))
        if is_open and target == active:
            dpg.bind_item_theme(tag, TOOLBAR_THEME_ACTIVE)
        elif is_open:
            dpg.bind_item_theme(tag, TOOLBAR_THEME_OPEN)
        else:
            dpg.bind_item_theme(tag, TOOLBAR_THEME_FLAT)


def refresh_toolbar_learn_icon() -> None:
    """Paint the MIDI Learn mode icon from the MIDI engine state (e47).

    One global mode deserves one always-visible switch whose state is readable at
    a glance (ADR-midi-learn-entry-point.md): plain/flat while ready, the shared
    learn red while the mode is on, and greyed + non-clickable while MIDI is
    disabled (user decision: the disabled affordance itself says the feature is
    unavailable, and the bar never reflows as it would if the icon were hidden).
    The tooltip always names the next step, so the refusal is never silent.

    Called at the tails of the mode transitions and of the MIDI engine toggle
    (toggle_midi_learn, _exit_midi_learn, on_midi_enable) and once after the bar
    is built — never from a per-frame tick.
    """
    if not dpg.does_item_exist(TOOLBAR_LEARN_BUTTON_TAG):
        return
    enabled = bool(state.midi_enabled)
    learning = enabled and bool(state.midi_learn_mode)
    dpg.configure_item(TOOLBAR_LEARN_BUTTON_TAG, enabled=enabled)
    dpg.bind_item_theme(
        TOOLBAR_LEARN_BUTTON_TAG, TOOLBAR_THEME_LEARN if learning else TOOLBAR_THEME_FLAT
    )
    if not enabled:
        tooltip = TOOLBAR_LEARN_TIP_UNAVAILABLE
    elif learning:
        tooltip = TOOLBAR_LEARN_TIP_CANCEL
    else:
        tooltip = TOOLBAR_LEARN_TIP_READY
    if dpg.does_item_exist(TOOLBAR_LEARN_TOOLTIP_TEXT_TAG):
        dpg.set_value(TOOLBAR_LEARN_TOOLTIP_TEXT_TAG, tooltip)


def tick_midi_learn_shortcut() -> None:
    """Ctrl+M arms/cancels MIDI Learn, once per chord (e52s07).

    The SAME mode transition as the toolbar icon (one source of truth); the tick
    is edge-triggered so a held chord toggles once, and it yields while a text or
    number input has focus (the guard Ctrl+C/V already rely on).
    """
    global _midi_learn_shortcut_held
    held = bool(dpg.is_key_down(MIDI_LEARN_SHORTCUT_KEY)) and bool(
        dpg.is_key_down(dpg.mvKey_ModCtrl)
    )
    if held and not _midi_learn_shortcut_held and not _any_input_focused():
        toggle_midi_learn()
    _midi_learn_shortcut_held = held


def show_recent_projects_popup() -> None:
    """The Last project icon: a compact popup with the recent project files."""
    if dpg.does_item_exist(TOOLBAR_RECENTS_TAG):
        dpg.delete_item(TOOLBAR_RECENTS_TAG)
    recent = recent_project_paths(load_config())
    position = dpg.get_mouse_pos(local=False)
    with dpg.window(
        tag=TOOLBAR_RECENTS_TAG, popup=True, no_title_bar=True, pos=position, min_size=(240, 10)
    ):
        themed_text("Last projects", slot="text_dim")
        if not recent:
            dpg.add_text("No recent projects")
        for path in recent:
            dpg.add_button(
                label=os.path.basename(path),
                width=-1,
                callback=open_recent_project,
                user_data=path,
            )
    dpg.show_item(TOOLBAR_RECENTS_TAG)


load_toolbar_icon_font()
_build_main_toolbar()
_build_mode_badges_window()  # e52s06: the mode strip lives in a window of its own
dpg.setup_dearpygui()
dpg.show_viewport()
refresh_window_title()  # e37s03: the title announces the boot project identity
autostart_osc()  # boot: auto-connect OSC client + start listening server (no manual clicks)

try:
    while dpg.is_dearpygui_running():
        # e55: center the import-time windows before the first frame is drawn (the
        # viewport size is measurable now); a no-op once every window is placed.
        tick_first_open_centering()
        if not state.pairing_prompt_shown:
            state.pairing_prompt_shown = True
            show_pairing_prompt()
        if dpg.does_item_exist("vimix_media_window"):
            w = dpg.get_item_width("vimix_media_window")
            # e83: measure first, then count — a column is dropped only when it
            # genuinely does not fit.
            measure_media_cell(state.last_num_cols)
            current_cols = media_columns(media_available_width(w), state.media_cell_w)
            if current_cols != state.last_num_cols:
                state.last_num_cols = current_cols
                if state.global_vimix_state.get("sources"):
                    update_vimix_sources_ui(json.dumps(state.global_vimix_state))

        has_new_logs = False
        while not log_queue.empty():
            osc_log_history.append(log_queue.get())
            has_new_logs = True

        if has_new_logs:
            if len(osc_log_history) > LOG_HISTORY_LIMIT:
                del osc_log_history[:-LOG_HISTORY_LIMIT]
            _refresh_log_text()  # e81: honours the level filter and Pause

        # Run queued UI mutations from worker threads on the main thread (audit HIGH-1)
        while not ui_task_queue.empty():
            task = ui_task_queue.get()
            try:
                task()
            except Exception as e:
                log_error("UI task", str(e))

        latest_json = None
        while not ui_state_queue.empty():
            latest_json = ui_state_queue.get()

        if latest_json:
            update_vimix_sources_ui(latest_json)

        while not state.watch_state_queue.empty():
            watch_name, watch_args = state.watch_state_queue.get()
            _apply_watch_reply(watch_name, watch_args)

        # e82s04: the delta stream, applied on the main thread (HIGH-1).
        stream_applied = False
        while not state.event_queue.empty():
            if _apply_event(state.event_queue.get()):
                stream_applied = True
        if stream_applied or _stream_pending:
            _refresh_after_stream()

        while not texture_queue.empty():
            name, idx, img_data, w, h = texture_queue.get()
            apply_thumbnail_texture(name, idx, img_data, w, h)
            _fs_on_thumb_texture(name)

        tick_thumb_cycle(time.time())
        tick_link_readout()  # e75: the Link tempo readout follows the worker
        tick_transport_layout()  # e74s07c: re-wrap a narrowed sequencer transport row

        tick_toolbar()  # e46s01: keep the toolbar highlight + active mark fresh
        tick_viosc_led()  # e58s03: the settings connection LED
        tick_midi_learn_shortcut()  # e52s07: Ctrl+M arms/cancels MIDI Learn

        tick_project_dirty(time.time())  # e37s03: unsaved-changes marker cadence

        tick_drafts(time.time())  # e43s05: persist the draft library (debounced)
        tick_send_remap(time.monotonic())  # e45s02: expire an unreached reassignment

        tick_cue_triggers()  # e35s03: cue-list card running labels (idle-cheap)

        tick_text_caret()  # e59s05: capture the live caret/selection while editing

        tick_io_monitor()  # e39s01: I/O Monitor panes (idle-cheap, revision-gated)

        tick_raw_flash()  # e82s08: return the changed raw cells to the normal colour
        tick_tile_status()  # e83: the seek bars between UI passes

        tick_mappings()  # e40s01: state Origin -> MIDI/OSC Destination emissions
        tick_mapper_clipboard()  # e74s11: expire the Mapper clipboard (its Paste buttons)

        tick_midi_learn_timeout()  # e18: expire stale MIDI Learn sessions (incl. mapper)

        tick_leap_monitor()  # e26s02: live two-hand values in the Leap Motion window

        tick_leap_visualizer()  # e26s04: embed the IR + skeleton frame (when shown)

        tick_source_preview(time.time())  # e38s03: preview frames + transport sync

        request_missing_thumbnails(time.time())

        dpg.render_dearpygui_frame()
        time.sleep(frame_sleep())  # perf e07 P1: throttle the idle render cadence
finally:
    # L-4 clean exit: stop audio, shut down the OSC server, destroy the context
    if audio_stream is not None:
        with contextlib.suppress(Exception):
            audio_stream.stop()
            audio_stream.close()
    if state.local_osc_server is not None:
        with contextlib.suppress(Exception):
            state.local_osc_server.shutdown()
    dpg.destroy_context()
