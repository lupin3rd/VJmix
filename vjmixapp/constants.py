"""Named constants for VJmix (REFACTOR_LATEST.md commit 2/13).

Pure data — no mutable app state, no dpg. Moved verbatim from vjmix.py;
vjmix.py imports these names so every usage site and the test facade
keep working unchanged.
"""

import copy
from typing import Any

MAX_THUMBNAIL_PIXELS = 3_000_000  # explicit cap; real thumbs are ~58k px


MAX_THUMBNAIL_BLOB_BYTES = 8 * 1024 * 1024  # per-blob cap


MAX_STATE_JSON_BYTES = 1 * 1024 * 1024  # per-replydata cap


# e41s02: explicit UDP receive buffer for the OSC listener. socketserver inherits
# the kernel default (208 KiB on Linux), which is small for a burst of datagrams
# (a state broadcast arriving together with a burst of monitor/watch replies).
# The kernel caps the request at net.core.rmem_max and doubles the effective
# value; the helper suppresses a refusing platform.
RECV_BUFFER_BYTES = 262144


THUMB_REQUEST_INTERVAL = 3.0  # min seconds between thumbnail requests per source


# e41s02: how many frame indices a source is asked for, ONE per throttle cycle.
# Mirrors viOSC's THUMB_MAX_COUNT (up to 3 thumbs per media, jittered anchors):
# asking for all of them in one `all` request made the daemon emit three JPEG
# blobs back-to-back — a multi-fragment burst on a transport that never
# retransmits.
THUMB_REQUESTS_PER_SOURCE = 3


LOG_HISTORY_LIMIT = 25  # max entries kept in the OSC log window


DPG_COLOR_SCALE = 255.0  # DPG ToColor divides color inputs by 255 -> its color API is 0..255


# --- BEHAVIORAL CONSTANTS (audit L-6) ---
# Main-loop render cadence (perf e07 P1): full rate while something animates, throttled
# while idle (input stays responsive at ~30 fps; SPIKE-perf measured the idle render as
# the biggest fixed cost).
FRAME_SLEEP_ANIMATED = 0.016  # ~60 fps while sequencer/spectrum/monitor video animate


FRAME_SLEEP_IDLE = 0.033  # ~30 fps at rest


# Step-cell layout: a centered square leaves the checkbox/type row on top (audit L-6)
# ImGui WindowPadding.x inside child windows (default style; app themes don't override)
# Measured on DPG 2.3.1: this indent centers the swatch in the 90px cell (padding included)
STEP_CELL_SIZE = 90  # px side of each sequencer step cell


STEP_COLOR_SQUARE_SIZE = 40  # px side of the centered color square inside a step cell


STEP_CELL_CONTENT_PADDING = 8


# e66s03: the three zoom levels — user decision 2 (2026-10-12): THREE fixed levels, not a
# continuous range, because a level is a PAIR (pixels + a font) and only a fixed set lets
# all three fonts be built once at boot. `SEQ_ZOOM_DEFAULT` is the level the cell literals
# below are written for, so the shipped look is the reference and a level is a departure
# from it. The zoom is APP-LEVEL config, not project content: opening a project must not
# resize the operator's cells.
# 2026-10-12 the operator REPLACED the first set (64/90/128) after the rig check: at 64 px the
# fonts and the inner widgets did not fit. ImGui has MINIMUM widget sizes (frame padding, grab
# size) that a cell holding a checkbox, a label and a value editor cannot beat by arithmetic, so
# 64 was a level below the floor rather than a bug to chase. 80 is the smallest that fits.
SEQ_ZOOM_LEVELS = (80, 90, 100)
SEQ_ZOOM_DEFAULT = 90


# e67s05: the operator reads a SIZE, the code keeps three ordered levels. A LABEL map derived
# from the levels, so a label can never name a level that does not exist; the stored value and
# the sanitizer do not change.
SEQ_ZOOM_LABELS = dict(zip(("Small", "Medium", "Large"), SEQ_ZOOM_LEVELS, strict=True))


# e68: the grid table is given its CONTENT height. Without one, DearPyGui stretches the table to
# the window's remaining space, which pushed the delete button to the very bottom instead of just
# under the last row (the operator's report). One row adds this much table padding to its cell.
# e74s08: the vertical space ONE grid row needs beyond the cell = 2 * the table's
# CellPadding.y (theme_compact_table binds 1, 1). The table height is
# rows * (cell + SEQ_GRID_TABLE_ROW_PAD) EXACTLY: the old formula added one extra pad at
# the end, which left a blank band under the last row (the operator's "empty row").
SEQ_GRID_TABLE_ROW_PAD = 2


# e66s03 (REVISED 2026-10-12, operator decision): a sequencer is CREATED at a geometry and a
# zoom, and then it STAYS — changing either means deleting it and creating another one. That
# is why the list is bounded: two are offered (A and B), and a corrupt document cannot
# balloon it. ZERO is a legal state: the sequencer can be deleted for good.
SEQ_MAX_SEQUENCERS = 2


# e67s02: the namespace of a grid's tags. A keeps the shape it has always had, so every
# existing test, binding and screenshot keeps its meaning; B passes its own.
SEQ_TAG_PREFIX = "seq"


# e67s01: the sequencer clock's poll interval. The loop asks the two-clock decision who is due, so
# this bounds how late a beat can be — the same reason the old loop polled the event with 0.1 s.
SEQUENCER_TICK_POLL_SECONDS = 0.02


# e67s04: the transport row's nudge and TAP values. ONE home for both rows, so A's bare controls
# and B's prefixed row cannot drift apart by hand.
SEQ_NUDGE_STEP = 0.05  # phase correction one nudge click applies, in seconds
TAP_STALE_SECONDS = 2.0  # a longer gap starts a new TAP sequence instead of averaging
TAP_MAX_TAPS = 8  # how many recent taps the average is computed from


# Clip-slot layout: a bare centered assign button, no table frame around it (audit L-6).
# The borderless slot has no WindowPadding (content_region_avail == full size, measured on
# 2.3.1), so horizontal centering is pure (width - button_width) / 2. Vertically the button's
# frame rect sits SLOT_BUTTON_FRAME_INSET px below its layout box (measured), hence the -inset.
SLOT_WIDTH = 135  # px width of the clip slot column


SLOT_BUTTON_WIDTH = 110  # px width of the assign button/thumbnail


SLOT_BUTTON_HEIGHT = 70  # px height of the assign button/thumbnail


SLOT_BUTTON_FRAME_INSET = 4  # px: ImGui button rect offset below its widget box (2.3.1)


# NOTE (e66s03): the DERIVED layouts — the colour square's indent, this button's indent and
# its top spacer — no longer live here. They are a function of the zoom level and are computed
# by `vjmixapp/seqlayout.py`, which is also where the bases above are scaled; a constant here
# would be a second source of truth for the same pixel.


# Mediagrid tile: index badge overlay + compact layout (audit L-6)
# e10s06: the tile title fits at most two wrapped lines, truncated with an ellipsis.
# The title font is ProggyTiny (monospace, pixel family of the default ProggyClean):
# at 9 px its line height equals the font size and the advance is ~5.4 px.
MEDIA_TITLE_FONT_SIZE = 10  # px font size of the media tile title


MEDIA_TITLE_CHARS_PER_LINE = 20  # ProggyTiny-10 capacity at MEDIA_TITLE_WRAP (measured):
#                                  the whole ONE-line budget of a tile title (e79)


MEDIA_TILE_PAD = 5  # px uniform WindowPadding of a media tile (equal gaps all around)


MEDIA_TITLE_GAP = 2  # px base gap between the tile title and the thumbnail row


MEDIA_BADGE_W = 20  # px width of the media-index badge overlay on the thumbnail


MEDIA_BADGE_H = 15  # px height of the media-index badge overlay on the thumbnail


MEDIA_TILE_H = 116  # px media tile (title + thumbnail + alpha, e83: + seek bar + status line)
# e83 fix: how many tiles fit the window. The old guess (145 px, including a margin)
# dropped a column while the grid still had room, so the scrollbar appeared too early.
# The count now uses the MEASURED available width and the MEASURED cell footprint,
# with the estimate only as the first-frame fallback.
# The real footprint: the 135 px tile + the compact table's CellPadding (1 px each
# side). The old 145 made a column drop ~18 px too early, which is what made the
# scrollbar appear while the grid still had room.
MEDIA_TILE_W_ESTIMATE = 137  # px per tile + the table's 1 px cell padding each side
# Window padding (8) + the vertical scrollbar (16) + 2 safety: the count assumes the
# scrollbar may be there, ALWAYS. Measuring the live content width instead would
# feed back (a column fits -> no scrollbar -> the width grows -> a column fits...).
MEDIA_GRID_MARGIN = 26  # px of window chrome excluded from the grid
# e83: the compact tile status. The P/C/L badges are drawn ON the thumbnail (the
# index badge already lives there), the seek is a 4 px bar under it and one 10 px
# line carries blending/depth/speed/seek. Everything fits the ~25 px the tile has
# free, so the grid does not grow.
# e83 (second pass, operator): the P/C/L letters moved to the line under the seek
# bar, so the thumbnail keeps ONE badge — the blending icon, bigger.
TILE_BLEND_BADGE_SIZE = 16  # px square of the blending icon badge
TILE_BLEND_ICON_INSET = 2  # px between the square and the glyph
TILE_BLEND_BADGE_GAP = 3  # px from the thumbnail's right/top edge
TILE_SEEK_BAR_H = 4  # px height of the seek bar
TILE_STATUS_BADGES: tuple[tuple[str, str], ...] = (
    ("play", "P"),
    ("correction", "C"),
    ("lock", "L"),
)
# The strip refreshes at this rate between UI passes (the state tier answers seek
# once per second; the bar must move continuously).
TILE_STATUS_TICK_S = 0.1
# e83: the status line is distributed across the tile: P C L, then the depth in the
# middle and the speed on the right, with two spacers doing the math. The tile font
# is MONOSPACE, so a character is exactly MEDIA_TITLE_WRAP / MEDIA_TITLE_CHARS_PER_LINE
# wide and no runtime measurement is needed (dpg.get_text_size answers only after
# the first frame).
TILE_STATUS_GAP = 2  # px: the tile theme's ItemSpacing.x


MEDIA_TILE_NAME_CHARS = 14  # max chars of a source name in a non-media tile (fits 115 px)


# e69s01: max chars of a NAME or TYPE label in the two-line non-thumbnailable
# placeholder (the Mapper row slot and the Sequencer clip slot). The longest wiki
# type label is 'Screen capture'/'Image sequence' (14 chars) and fits the 110 px slot.
NON_THUMB_LABEL_CHARS = 14


MEDIA_ALPHA_SLIDER_W = 10  # px width of the thin vertical alpha slider on a tile
# e74s12: a small red STOP sits UNDER the alpha slider and parks the source. The column
# keeps the slider's footprint: the media row is 65 px tall = slider + 2 px gap + stop.
MEDIA_ALPHA_STOP_H = 15
MEDIA_ALPHA_SLIDER_H = 48
# Any negative alpha parks the source: vimix maps alpha<0 to a mixing distance
# |alpha| + 1 and deactivates it when that distance is NOT below the session's
# activationThreshold (1.3..1.9, default 1.3). -1.0 -> D = 2.0, above the whole range,
# so the source ALWAYS stops (alpha -0.5 would only stop a threshold <= 1.5).
MEDIA_ALPHA_PARKED = -1.0


MEDIA_TITLE_WRAP = 125  # px wrap width of the media tile title


# e79: ONE line per tile (operator request). A second line forced every tile to reserve it and
# pushed the thumbnail row down; the name is cut in the MIDDLE instead, so both the prefix and
# the tail survive (see truncate_media_title) and the full name lives in the hover card.
MEDIA_TITLE_MAX_LINES = 1


MEDIA_TITLE_ELLIPSIS = "..."  # ASCII dots: ProggyClean (default font) has no U+2026 glyph


MEDIA_TITLE_CHAR_PX = 7  # default-font estimate (ProggyClean 13 px) used before the atlas is built


# e16/e20/e22/e23: Mapper window geometry — the body is a vertical stack of
# source rows (e22s01): one horizontal line per vimix source = the source
# thumbnail at the sequencer slot size (110x70, bare) + one bordered mini-card
# per mapping. e23: each mini-card holds — caption (label + X) above a control
# that spans the content width, then the 'output:' from/to line and the
# 'input:' from/to line (visible when a source is bound) under it. e23 iteration:
# everything renders COMPACT — the 10 px ProggyTiny font (MEDIA_TITLE_FONT_SIZE)
# for texts/controls, tight frame/item paddings, small X (16 px) and 40 px
# drag boxes — so rows are short and the mini-cards narrow. Rows are sized to
# their OWN content (see _mapper_row_height): slider rows ~60 px, knob rows
# taller, +16 px when a source is bound. Measured on DearPyGui 2.3.1 with the
# compact theme (WindowPadding 4/FramePadding y 2/ItemSpacing 2): content inset
# ~4 px top + ~4 px bottom air (MAPPER_ROW_PAD_V = 8 — trimmed 2026-09-05 so the
# cards no longer show a dead band at the bottom), a small-font text/drag row is
# 14 px, a slider/button box 14 px, the knob a fixed 44 px, gaps 2 px; the
# ProggyTiny-10 advance is 6 px/char (widest label 'Transparency' = 72 px).
MAPPER_WINDOW_WIDTH = 660


MAPPER_WINDOW_HEIGHT = 460


MAPPER_ROW_THUMB_W = SLOT_BUTTON_WIDTH  # px width of the row thumbnail (= the sequencer slot)


MAPPER_ROW_THUMB_H = SLOT_BUTTON_HEIGHT  # px height of the row thumbnail


MAPPER_LINE_NO_W = 16  # px width of the row line-number column (e32s02; fits 2 digits flush)


MAPPER_LINE_NO_DIGIT_PX = 8  # px advance of a ProggyTiny-13 digit (5.4 px @9 px -> ~7.8 px)


MAPPER_LINE_NO_FONT_SIZE = 13  # px size of the row line numbers (ProggyTiny, > the 10 px font)


# e69s01: px size of the TYPE line under a non-thumbnailable source's name in the
# Mapper row slot (ProggyTiny, one step BELOW the 10 px mapper font so the name leads).
MAPPER_KIND_FONT_SIZE = 9


MAPPER_LINE_NO_TEXT_H = 13  # px text height used to center the line number in the row


MAPPER_TEXT_H = 14  # px height of one compact text/drag row (measured 2026-09-06 on the
# 10 px ProggyTiny theme: a drag box is ~14 px, not 17 — the old value left a
# visible dead band under the last readout row of a card)


MAPPER_CTRL_H = 14  # px height of a compact slider/button box (same 10 px-font measure)


MAPPER_KNOB_H = 44  # px height of the fixed knob widget


MAPPER_ROW_GAP = 2  # px item spacing between the card rows


MAPPER_ROW_PAD_V = 8  # card inset: 4 top + 4 bottom air (2026-09-05: was 6+12 —
# rows reclaimed ~8-10 px and the cards no longer show a dead band at the bottom)


MAPPER_SMALL_CHAR_PX = 6  # px advance of the 10 px ProggyTiny mapper font (measured)


MAPPER_MINI_W = 150  # px width of one mapping mini-card (caption + output line fit)


MAPPER_X_W = 16  # px width of the X delete button on a mini-card caption row


MAPPER_X_H = 16  # px height of the X delete button


MAPPER_RESET_W = 16  # px width of the reset button on a mini-card caption row (e27s01)


MAPPER_RESET_H = 16  # px height of the reset button


MAPPER_CB_W = 16  # px width of the enable checkbox on a caption row (measured, compact theme)


# e77: a MOMENTARY GUI button sends its ON value and lights up, then returns OFF on its
# own after this long. One fixed constant: the operator asked for a behaviour choice at
# creation, not a duration to tune per Mapping (2026-10-16).
MAPPER_MOMENTARY_FLASH_S = 0.15


# e34s01: per-row '+' add button — a NARROW trailing slot (2026-09-05 rework:
# it used to span the full card pitch and wrapped like a 150 px card on resize).
MAPPER_ADD_W = 24  # the '+' button width
MAPPER_ADD_H = 22  # the '+' button height
MAPPER_ADD_SLOT_W = 36  # the slot child + its spacing (small, NOT the card pitch)
# e51s02 follow-up (rig report): the Paste button needs to read its label —
# wider than the '+' and wide enough for 5 compact-font characters plus the
# mapper theme's 6 px frame padding (5 * 6 + 12 = 42), and its slot must hold
# that button inside the 4 px child padding (42 + 8 = 50).
MAPPER_PASTE_W = 42  # the 'Paste' button width
MAPPER_PASTE_SLOT_W = 50  # the trailing slot width while a Paste button rides it
# e74s11: the clipboard ARMS its Paste buttons; they must not ride the lines forever.
# After this many seconds the snapshot expires and the body rebuilds without them.
MAPPER_CLIPBOARD_TTL_SECONDS = 30.0
# e51 follow-up: the Inp row label is always 'inp'; a button that toggles on each
# press (MIDI note, or a 127..127 window) explains itself on hover instead.
MAPPER_INPUT_ALT_TOOLTIP = "Alternate input: each press toggles ON/OFF"


MAPPER_DRAG_W = 40  # px width of the from/to drag boxes on the slider 'output:'/'input:' lines


# e34s02: px width of the from/to drag boxes in the compact knob/button band —
# smaller than MAPPER_DRAG_W so 'Out'/'Inp' + two boxes fit beside the 44 px control.
MAPPER_BAND_DRAG_W = 34

# e33s04: fixed slot count of the Mapper in the learn bar (user rule: 4 lines,
# pre-bindable even when fewer rows exist — a missing line is a logged no-op).
MAPPER_LEARN_SLOTS = 4

# e33s02: learn-marker button on a card caption / row lead (compact, tooltip-only)
MAPPER_MARKER_W = 15
MAPPER_MARKER_H = 15

# e40s13: the Mapper body scroll area. DPG's child_window treats a NEGATIVE
# height as "fill the available height", so the area always matches the window
# even after a resize. It used MAPPER_WINDOW_HEIGHT - 8, a number computed from
# the INITIAL window size while the Mapper window is resizable and its
# geometry persisted (e28s02): a user-grown window then showed a scrollbar with
# free space below it (and the fixed value was ~20 px too tall anyway).
MAPPER_SCROLL_HEIGHT = -1

# e40s12: gap between the Mapper's Show chips and the general '+' creator, so
# the create action reads as its own control and not as a fourth filter.
MAPPER_FILTER_ADD_GAP = 24

# e40s08: the per-source State band — a bordered box on the source line's OWN
# sub-line (no line number) holding that source's State Mappings, plus a header
# row ('State' + a small '+'). Height = the box WindowPadding air
# (MAPPER_ROW_PAD_V) + the header + N rows + the ItemSpacing gap between each.
# 17 px is the MEASURED height of both rows on the rig with real DPG 2.3.1 (the
# header's text and a Mapping row's checkbox both settle at 17, one px above the
# 16 px buttons); the buttons are forced to the same 17 so a row can never
# outgrow the box.
MAPPER_STATE_BOX_HEADER_H = 17  # px height of the box header row
MAPPER_STATE_BOX_ROW_H = 17  # px height of one State Mapping row inside the box

# e33s04: wider spacing BETWEEN the learn-bar groups (replaces the almost
# invisible DPG vertical separators — the user asked for plain space).
MARKER_GROUP_GAP = 18


VIOSC_IP = "127.0.0.1"


VIOSC_PORT = 6666


VIOSC_LISTEN_PORT = 6667  # the port viOSC sends replies to; VJmix's own server listens here


# e38: source video preview (SOURCE_PREVIEW_LATEST.md) — the HTTP file
# transport on machine A (viOSC, VIOSC_PREVIEW_PORT default) and the local
# decode/display caps on machine B. Frames are decoded at <= the texture cap
# (DPG stretches the small texture to the panel) and pushed at most
# PREVIEW_MAX_FPS — one raw-texture set_value per frame on the main thread.
PREVIEW_PORT = 8686  # matches the viOSC HTTP preview server default
PREVIEW_PATH_PREFIX = "/preview/"  # served as /preview/<source-name>/file|meta
THUMB_PATH_PREFIX = "/thumb/"  # e41s03: served as /thumb/<source-name>/<index>
STATE_PATH = "/state"  # e41s04: the state table as a pull resource
INTEREST_PATH = "/interest"  # e82s05: what a consumer needs, at its cadence
# e82s05: the properties viOSC keeps synchronised at 1 s (the mirror's state
# tier). The app must know them to tell "never asked" from "asked, no value".
STATE_TIER_PROPS = (
    "id",
    "index",
    "name",
    "alpha",
    "blending",
    "correction",
    "depth",
    "position",
    "size",
    "angle",
    # e82s08 (user request): the transport/visibility state a tile or a lever may
    # want to show without declaring an interest for it.
    "play",
    "lock",
    "speed",
    "seek",  # e83: the tile's seek bar (dead-reckoned between answers)
)
DATA_PLANE_TIMEOUT = 5.0  # s: bounded data-plane request (the OSC lane is the fallback)
# e41s04: how often VJmix reads the state table. The push fires whenever vimix
# changes a property — the rate belongs to vimix, not to the consumer — while
# this cadence belongs to the machine that pays the render cost. Measured cost at
# 50 sources: 24.8 KB serialized in 0.149 ms (SPIKE-transport-planes M1), i.e.
# cheaper in wall cost than the 2 s push baseline AND fresher.
STATE_PULL_INTERVAL = 1.0  # s
# e41s04: consecutive state pulls with NO ANSWER before the pull is given up for
# the session and the cadence returns to the OSC push lane.
STATE_PULL_MAX_FAILURES = 3
# e82s04: the delta stream (SSE on the data plane). A read timeout well above the
# daemon's 15 s heartbeat detects a dead peer without racing the heartbeat; a
# revision gap or a reconnect means the client missed a change, so it refetches.
EVENTS_PATH = "/events"
STREAM_READ_TIMEOUT = 60.0  # s
STREAM_BACKOFF_MAX = 30.0  # s: the reconnect ceiling
# While the stream is live the snapshot survives as a slow reconciliation (source
# churn, drift), and the ETag makes it cost headers only.
STATE_PULL_STREAM_INTERVAL = 5.0  # s
# The table is re-rendered after stream deltas at most this often: a fade emits
# ~100 events/s and the tiles need 10 Hz, not 100.
STREAM_UI_REFRESH_MIN_S = 0.1
# e41s03: consecutive data-plane fetches with NO ANSWER before the fast lane is
# given up for the session. A 404 is an ANSWER (the endpoint is alive and has no
# such frame) and must not count — an out-of-range index on the stall path would
# otherwise cost the lane for the whole session.
THUMB_HTTP_MAX_FAILURES = 3
PREVIEW_CAP_WIDTH = 640  # px texture-cap width (measured budget, SPIKE-source-preview)
PREVIEW_CAP_HEIGHT = 360  # px texture-cap height
PREVIEW_MAX_FPS = 30.0  # decoded/pushed frame ceiling
PREVIEW_HTTP_TIMEOUT = 10.0  # s: av.open + meta request timeout
# e38 BUG-2026-09-12: playback rate. The transport is paced against the wall
# clock from the frame PTS; 1.0 is real time (the default). The control lets the
# user speed up/slow down and reset to the default.
PREVIEW_SPEED_DEFAULT = 1.0  # real-time playback (the reset target)
PREVIEW_SPEED_MIN = 0.25  # slowest selectable rate (~4x longer)
PREVIEW_SPEED_MAX = 4.0  # fastest selectable rate
PREVIEW_SPEED_STEP = 0.05  # drag speed of the Speed field


# Palette slots drive every chrome color: the global theme, the per-item themes, explicit
# text colors and the main draw items. The five primaries are user-editable in the Settings
# window; the rest derive from them (derive_palette). The "Dark" preset reproduces the
# legacy look exactly, so first launch is visually identical (SCOPE_LATEST criterion).
PALETTE_SLOTS: list[str] = [
    "window_bg",
    "panel_bg",
    "border",
    "border_active",
    "text",
    "text_dim",
    "text_bright",
    "accent",
    "accent_bg",
    "badge_bg",
    "warning",
    "play_bg",
    "play_on_bg",
    "spectrum",
]


THEME_PRIMARY_SLOTS: list[str] = ["window_bg", "panel_bg", "text", "border", "accent"]


THEME_PRIMARY_LABELS: dict[str, str] = {
    "window_bg": "Background",
    "panel_bg": "Panels",
    "text": "Text",
    "border": "Lines",
    "accent": "Accent",
}


THEME_PRESET_LABELS: dict[str, str] = {
    "scuro": "Dark",
    "chiaro": "Light",
    "custom": "Custom",
}


DEFAULT_PALETTE: dict[str, list[int]] = {
    # Scuro: the exact legacy look (e06s02 acceptance criterion 1)
    "window_bg": [24, 24, 24],
    "panel_bg": [40, 40, 40],
    "border": [80, 80, 80],
    "border_active": [50, 255, 50],
    "text": [200, 200, 200],
    "text_dim": [150, 150, 150],
    "text_bright": [255, 255, 255],
    "accent": [50, 255, 50],
    "accent_bg": [30, 80, 30],
    "badge_bg": [45, 55, 75],
    "warning": [255, 220, 80],
    "play_bg": [80, 80, 80],
    "play_on_bg": [80, 220, 80],
    "spectrum": [80, 255, 120],
}


LIGHT_PALETTE: dict[str, list[int]] = {
    # Chiaro: light background, dark text (the user's "sfondo scuro" counterpart)
    "window_bg": [235, 235, 235],
    "panel_bg": [248, 248, 248],
    "border": [130, 130, 130],
    "border_active": [20, 140, 20],
    "text": [30, 30, 30],
    "text_dim": [105, 105, 105],
    "text_bright": [25, 25, 25],
    "accent": [20, 140, 20],
    "accent_bg": [205, 235, 205],
    "badge_bg": [210, 216, 226],
    "warning": [190, 150, 20],
    "play_bg": [185, 185, 185],
    "play_on_bg": [140, 210, 140],
    "spectrum": [30, 150, 60],
}


# e74s02/s03: THE VIMIX-SOURCES TOOLBAR + THE SOURCES-DATA WINDOW. The toolbar is
# the persistent top row of the Vimix-sources window (source browsing + the button
# that opens the raw table); the table itself leaves Settings for a workspace window
# of its own. SOURCES_DATA_GROUP_TAG keeps the historical tag so the table builder in
# `update_vimix_sources_ui` is untouched — only its PARENT changes.
SOURCES_TOOLBAR_TAG = "sources_toolbar"
SOURCES_TOOLBAR_PREV_TAG = "sources_browse_prev"
SOURCES_TOOLBAR_NEXT_TAG = "sources_browse_next"
SOURCES_TOOLBAR_SET_TAG = "sources_set_current"
SOURCES_DATA_BUTTON_TAG = "sources_data_button"
SOURCES_DATA_WINDOW_TAG = "sources_data_window"
SOURCES_DATA_GROUP_TAG = "vimix_raw_group"
SOURCES_DATA_WINDOW_WIDTH = 1000
SOURCES_DATA_WINDOW_HEIGHT = 560
# e82s08: the Sources-data window no longer sweeps everything on open. A changed
# cell is emphasised (the pixel font has ONE weight, so it is the bright palette
# colour, not bold) for this long, and a button asks for a full one-shot sweep.
SOURCES_DATA_REFRESH_TAG = "sources_data_refresh"
SOURCES_DATA_STATUS_TAG = "sources_data_status"
SOURCES_DATA_LEARN_SLOT = "sources_data_learn_slot"
RAW_FLASH_SECONDS = 1.5


# The workspace windows whose pos/size/open state persist with the project
# (user decision e55, 2026-09-21; e59 added the Text window, e74 the Sources-data
# one). Config panels (settings), diagnostics (I/O Monitor), MIDI/Leap and every
# dialog are NOT workspace: they open centered and are never restored by a load.
LAYOUT_WINDOW_TAGS: list[str] = [
    "sequencer_window",
    # e67s02: B joins the layout AND the Ctrl+Tab cycle, but only once it EXISTS — both
    # readers are guarded (`_existing_layout_window_tags` when saving, `does_item_exist` when
    # applying), so a session with no B saves and restores without inventing a second window.
    "sequencer_b_window",
    "audio_window",
    "vimix_media_window",
    "logs_window",
    "text_window",  # e59s02: the Text window (vimix `contents` authoring)
    "shader_window",  # e61s03: the Shader window (GLSL asset + file-path deploy)
    "mapper_window",  # e28s02: the Mapper is a workspace window — pos/size/open persist
    "file_manager_window",  # e43s02: the File Manager is a workspace window
    SOURCES_DATA_WINDOW_TAG,  # e74s03: the raw viOSC table window
]


# e08: About window (Help menubar). The brand mark is the packaged PNG rasterised at 2x
# from logo.svg (vjmixapp/assets/vjmix_logo.png): 920x296 drawn at HELP_LOGO_WIDTH, so it
# stays crisp and never needs a bundled vector renderer. The window is a transient dialog:
# it stays out of LAYOUT_WINDOW_TAGS, so a saved layout never re-opens it at boot and the
# layout snapshot never records it.
HELP_WINDOW_WIDTH = 540


HELP_WINDOW_HEIGHT = 400  # logo + title + version/license/author lines + GitHub button
#                           + the e83 donation block (the hover-help switch moved to
#                           General, where the display preferences live)


HELP_LOGO_WIDTH = 460  # keeps the source 953:306 aspect ratio (460 x 306/953 -> 148)


HELP_LOGO_HEIGHT = 148


# e76: HOVER HELP — one short card per control, on the control AND on its label.
# The cards are static items (no per-frame work), so the numbers below are the whole
# budget: a card is a title, at most a few wrapped lines of body, and an option table
# capped in both width and line count. Tooltips render in ProggyClean, so every string
# stays ASCII (BUG-2026-09-18T193805).
HELP_WRAP_WIDTH = 340
HELP_HOVER_DELAY_S = 2.0  # the mouse must REST this long (operator, 2026-10-16): a card
#                            that appears while you cross a control is noise during a set
HELP_TITLE_MAX = 40
HELP_BODY_MAX = 240
HELP_OPTION_MAX = 44  # one option line fits HELP_WRAP_WIDTH at the default font
HELP_MAX_OPTION_LINES = 8  # the 8 blending modes are the widest vocabulary
HELP_OPTION_COLUMN = 14  # px-free monospace column: "Soft subtract" fits, values align
HELP_BODY_TAG_SUFFIX = "_help_body"  # the LIVE cards rewrite this text item
HELP_TIP_TAG_SUFFIX = "_help"
# The card must READ: it sits on its OWN raised surface (operator, 2026-10-16 — a tooltip
# inherited window_bg, so the dim text sat on the window colour and the popup was hard to
# read). The slot is palette-driven, so Dark / Light / Custom move the card with the UI.
HELP_CARD_BG_SLOT = "panel_bg"
HELP_CARD_BORDER_SLOT = "border"
HELP_CARD_BORDER = 1
HELP_CARD_PAD_X = 10
HELP_CARD_PAD_Y = 8
HELP_CARD_GAP_X = 8
HELP_CARD_GAP_Y = 3


# e59: TEXT WINDOW — authors Pango markup and sends it to a vimix Text source
# with the frozen-contract message /vimix/<target>/contents (one string arg).
# e74s01: the default frame is wide enough for the widest row and tall enough for
# the whole stack (rows + editor + status) with margin; the editor itself follows
# the LIVE width (`width=-1`), so resizing can never clip a field.
TEXT_WINDOW_WIDTH = 700
TEXT_WINDOW_HEIGHT = 560
TEXT_WINDOW_TAG = "text_window"
TEXT_EDITOR_TAG = "text_editor"
TEXT_SOURCE_COMBO_TAG = "text_source_combo"
TEXT_STATUS_TAG = "text_status"
TEXT_LEARN_SLOT_TAG = "text_learn_slot"
TEXT_MODE_LEARN_SLOT_TAG = "text_mode_learn_slot"
# e33s05: the Map actions panel (one row + marker per global action).
MAP_ACTIONS_WINDOW_TAG = "map_actions_window"
MAP_ACTIONS_ROWS_TAG = "map_actions_rows"
TEXT_WRAP_CLIPBOARD_TAG = "text_wrap_clipboard"
TEXT_WRAP_ROW_TAG = "text_wrap_row"
TEXT_LOAD_DIALOG_TAG = "text_load_dialog"
TEXT_SAVE_DIALOG_TAG = "text_save_dialog"
# Rate limit (defensive category): a text file / a project document is bounded
# so a stray multi-megabyte file cannot be loaded into the editor and pushed.
TEXT_MAX_LOAD_BYTES = 1_000_000
# The per-keystroke validity check parses the whole document as XML; a large
# document is only validated on demand (the Validate button) to keep typing cheap.
TEXT_LIVE_VALIDATE_MAX_CHARS = 20_000
# Editor height (small on purpose: ImGui's multiline input scrolls the overflow).
# e74s01: the editor's WIDTH is `width=-1` (fill the window), so the former
# TEXT_WINDOW_PADDING-derived width is gone.
TEXT_EDITOR_HEIGHT = 200
# e74s01b: the colour editors need room for the preview button PLUS one drag field
# per channel; at the former 80 px even "255" was clipped.
TEXT_COLOR_EDIT_WIDTH = 180
# vimix resolves #<n> and the bare <n> index form; the '#' form is the
# documented one (ControlManager.cpp OSC_SOURCEID) and is what the picker shows.
TEXT_SOURCE_INDEX_PREFIX = "#"

# e61s03: SHADER WINDOW. The window authors a GLSL asset and deploys its FILE
# PATH (D4': the GLSL text never travels over OSC — an inline `/code` above 4098
# bytes crashes vimix). The layout mirrors the Text window. Since e64s02 its first
# row REPLACES the editor as the place the choice happens (kind, then the asset of
# that kind) and e65s06 added the FAMILY filter beside the kind, which is what this
# width pays for: the row carries `Kind: [combo] Family: [combo] Shader: [combo]
# <count>`, with the three combos sized to their longest real value (a kind, a family
# token, and a pack asset name like `particle_streak_over_source`).
SHADER_WINDOW_WIDTH = 880
SHADER_WINDOW_HEIGHT = 560
SHADER_WINDOW_PADDING = 24
SHADER_EDITOR_HEIGHT = 320
SHADER_WINDOW_TAG = "shader_window"
SHADER_TARGET_COMBO_TAG = "shader_target_combo"
SHADER_KIND_COMBO_TAG = "shader_kind_combo"
SHADER_TEMPLATE_COMBO_TAG = "shader_template_combo"
# e65s06: the FAMILY filter, beside the kind — the second predicate on the same list.
# The first item is the filter OFF, and its label carries a SPACE on purpose: a
# `// family:` token is `[A-Za-z_]+` (shadercode.FAMILY_DECLARATION), so no shader can
# ever declare a family called this and the item can never be ambiguous. The state
# holds the TOKEN (`""` for any), never this label, so what a project remembers is the
# declaration and not the UI's wording.
SHADER_FAMILY_COMBO_TAG = "shader_family_combo"
SHADER_FAMILY_ANY = "any family"
# e64s02: the line under the picker that states the library's arithmetic — how many
# assets exist, how many the Kind filter shows and how many it hides. The e62 rule
# is that an unlisted file is never a mystery; a second category of absent file
# (hidden by the filter) needs its own count, and the scan's own skips keep the
# status line (`report_skipped_library_files`).
SHADER_LIBRARY_INFO_TAG = "shader_library_info"
SHADER_EDITOR_TAG = "shader_editor"
SHADER_STATUS_TAG = "shader_status"
SHADER_VALIDATE_TAG = "shader_validate_text"
SHADER_LEARN_SLOT_TAG = "shader_learn_slot"
SHADER_SEND_BUTTON_TAG = "shader_send_button"
# e61s04: the uniform panel (one row per discovered `uniform float`) and the
# bypass control, which swaps the effect's filter for the pass-through.
SHADER_UNIFORM_PANEL_TAG = "shader_uniform_panel"
SHADER_UNIFORM_ROWS_TAG = "shader_uniform_rows"
SHADER_UNIFORM_SCAN_BUTTON_TAG = "shader_uniform_scan"
SHADER_BYPASS_BUTTON_TAG = "shader_bypass_button"
SHADER_UNIFORM_PANEL_HEIGHT = 150
SHADER_UNIFORM_LABEL_W = 120
SHADER_UNIFORM_SLIDER_W = 180
SHADER_LOAD_DIALOG_TAG = "shader_load_dialog"
SHADER_SAVE_DIALOG_TAG = "shader_save_dialog"
# The asset extension the Load/Save dialogs offer first (vimix reads any text
# file, but a project asset should be findable by name).
SHADER_ASSET_EXTENSION = ".glsl"
# The stem the deploy uses when the document has no file yet: inside the per-user
# shader library, named after the target (a stable path per target).
SHADER_DEFAULT_ASSET_STEM = "shader"

# e61: SHADER DEPLOYMENT — GLSL assets authored here and deployed to vimix as a
# FILE PATH (user decision D4': an inline /code above 4098 bytes of OSC datagram
# CRASHES vimix, measured on the rig). The asset is the source of truth, so these
# caps bound the FILE, not an OSC message.
SHADER_LIBRARY_DIRNAME = "shaders"
# The two declared target profiles (e61 D1): an EFFECT is a CloneSource with a
# custom filter (the shader samples iChannel0 = the cloned frame), a GENERATOR is
# a ShaderSource drawing on an empty 64x64 buffer. The OSC state feed exposes no
# source type, so the operator declares this per target.
SHADER_KIND_EFFECT = "effect"
SHADER_KIND_GENERATOR = "generator"
SHADER_KINDS: tuple[str, ...] = (SHADER_KIND_EFFECT, SHADER_KIND_GENERATOR)
SHADER_KIND_DEFAULT = SHADER_KIND_EFFECT
# vimix compiles the code it is given; a sanity cap keeps a stray multi-megabyte
# file out of the editor and the deploy path (the spike's largest test asset was
# 40 KB, so 256 KB is generous by three orders of magnitude).
MAX_SHADER_BYTES = 262_144
# Rate limit (defensive category): a project document / an asset file loaded into
# the editor is bounded, exactly like TEXT_MAX_LOAD_BYTES.
SHADER_MAX_LOAD_BYTES = 1_000_000
# Sanity caps on the persisted uniform registry (a hand-edited project cannot
# grow it without bound).
SHADER_MAX_TARGETS = 64
SHADER_MAX_UNIFORMS_PER_TARGET = 128
# The picker lists the LIBRARY FOLDER (e62), so one scan reads one file per
# entry: the cap bounds how many assets a single scan opens (rate limit,
# defensive category) so a folder full of hundreds of files cannot stall the
# window. The excess is reported, never silently dropped.
SHADER_MAX_LIBRARY_ENTRIES = 128
# How many skipped library files the Shader window names in its status line
# before summarising the rest (e62): the message stays readable with a folder
# full of undeclared files.
SHADER_MAX_SKIPS_NAMED = 3

# e63: THE REFERENCE SHADER PACK. The canonical copy of the pack's assets (a
# generator + an effect overlay per LOOK) lives in the repository under
# SHADER_PACK_DIRNAME; the library folder above is a deployment TARGET that
# scripts/sync_shader_pack.py fills from it. A stem is a LOOK: a reference clip
# read frame by frame (e63), or a DESIGNED look with a written criterion (e65).
SHADER_PACK_DIRNAME = "shaders"
SHADER_PACK_CLIP_COUNT = 36
# Of those looks, how many are EFFECT-ONLY (e73): a look of such a family is ONE file, not a
# generator/effect pair. Both numbers are bumped by the story that lands the looks.
SHADER_PACK_EFFECT_ONLY_CLIP_COUNT = 12
# The files the pack must hold, derived rather than repeated: every generating family
# contributes two files per look, an effect-only family one.
SHADER_PACK_ASSET_COUNT = (
    2 * (SHADER_PACK_CLIP_COUNT - SHADER_PACK_EFFECT_ONLY_CLIP_COUNT)
    + SHADER_PACK_EFFECT_ONLY_CLIP_COUNT
)
# The four uniforms EVERY asset of the pack declares, in the order the header
# documents them. A single Mapper row keeps its meaning across clips because
# these names and their ranges are identical everywhere.
SHADER_VOCAB_COMMON: tuple[str, ...] = ("motion", "geo", "amount", "hue")
# At most this many clip-specific names per asset, so no asset drifts into its
# own vocabulary (the cap the contract test enforces).
SHADER_VOCAB_PER_CLIP_CAP = 2
# The family token the pack's particle assets declare (e65s01/e65s02). The family is
# a free-form, DECORATIVE declaration; this is the ONE token the pack owns, and the
# contract test is what asserts the assets use it.
SHADER_PACK_FAMILY_PARTICLES = "particles"
# e72: the two families of the burst/collision epic. `burst` is the explosion family
# (firework_shell, shock_ring, impact_debris, spark_fountain); `collision` is the
# collisions/plexus family (bounce_gas, plexus_web, orbit_impact, ricochet_sparks).
SHADER_PACK_FAMILY_BURST = "burst"
SHADER_PACK_FAMILY_COLLISION = "collision"
# e73: the three families of TRANSFORMATIVE effects. Unlike every family before them they
# are EFFECT-ONLY: a pure effect has no generator twin, because a kaleidoscope of the empty
# 64x64 generator buffer is not a look. `optics` folds the sampling domain, `broadcast`
# damages the signal, `flux` drags the pixels by motion-like fields.
SHADER_PACK_FAMILY_OPTICS = "optics"
SHADER_PACK_FAMILY_BROADCAST = "broadcast"
SHADER_PACK_FAMILY_FLUX = "flux"
# The pack's WHOLE family vocabulary (e65s05, extended by e72): one token per family,
# on every asset. It lives here so the assets, the contract test and the docs read one
# source — but it is the PACK's vocabulary, not a validation set: `parse_family` stays
# free-form, and the operator's own shaders may declare their own families.
SHADER_PACK_FAMILIES: tuple[str, ...] = (
    "ink_fluid",
    "radial",
    "cellular",
    "light",
    SHADER_PACK_FAMILY_PARTICLES,
    SHADER_PACK_FAMILY_BURST,
    SHADER_PACK_FAMILY_COLLISION,
    SHADER_PACK_FAMILY_OPTICS,
    SHADER_PACK_FAMILY_BROADCAST,
    SHADER_PACK_FAMILY_FLUX,
)
# The families whose looks are EFFECT-ONLY (e73, operator decision (a)): the audit asserts
# the effect asset and NO generator for these, and both halves for every other family. It
# is a set of TOKENS rather than a per-stem flag so a family cannot drift half-way.
SHADER_PACK_EFFECT_ONLY_FAMILIES: tuple[str, ...] = (
    SHADER_PACK_FAMILY_OPTICS,
    SHADER_PACK_FAMILY_BROADCAST,
    SHADER_PACK_FAMILY_FLUX,
)
# The file-name convention of the pack, read off the operator's own library
# (particles_field.glsl + particles_over_source.glsl, ocean_filaments.glsl +
# ocean_filaments_over_source.glsl): a clip's generator is `<stem>.glsl` and its
# effect overlay is `<stem>_over_source.glsl`.
SHADER_PACK_EFFECT_SUFFIX = "_over_source"
# The dev-only render harness (scripts/render_shader_pack.py) turns an asset into
# pixels: it renders at SHADER_RENDER_SIZE, refuses a frame whose coverage
# (fraction of pixels away from the background) is under SHADER_CHECK_MIN_COVERAGE
# so "it rendered" can never mean "it rendered black", and fails a uniform that
# does not move the image. "Moves the image" is deliberately TWO criteria, not
# one: a uniform passes when the whole frame changes by more than
# SHADER_SWEEP_MIN_DELTA (mean absolute difference per channel, 0..1 scale) OR
# when at least SHADER_SWEEP_MIN_CHANGED of the pixels change by more than
# SHADER_SWEEP_PIXEL_DELTA. The second criterion exists because the first one
# dilutes a SPARSE feature: the glitter field of `marble_dust` lit 1.8% of the
# frame and moved the mean by 0.0018 (a false "dead control") until the
# changed-fraction test was added.
SHADER_RENDER_SIZE = (512, 512)
SHADER_CHECK_MIN_COVERAGE = 0.02
SHADER_SWEEP_MIN_DELTA = 0.004
SHADER_SWEEP_PIXEL_DELTA = 0.03
SHADER_SWEEP_MIN_CHANGED = 0.002
# C1, the passthrough law (e73): the harness renders an effect with its `amount` uniform at
# its declared minimum and the identity body over the same source, and requires the two
# frames to match. The expected difference is EXACTLY zero (a mix at 0 is `a*(1-0)+b*0`,
# exact in IEEE), so this tolerance exists only to keep the gate off a driver's rounding:
# one 8-bit step per channel is the most an honest implementation can differ by.
SHADER_PASSTHROUGH_MAX_DELTA = 1.0 / 255.0
# The registry row keys, in the persisted order. `min`/`max` are the range the
# shader declares with `// range [min max]` (re-derived on every scan), and
# `override_min`/`override_max` are the operator's manual range: when both are
# set they win, which is how a shader without the comment still gets a usable
# control (e61s04 refined `override` from one value into the pair a range needs).
SHADER_UNIFORM_KEYS = ("default", "min", "max", "override_min", "override_max", "value")


# e70s01: how many shader parameters are MAPPABLE, by position (`uniform1..uniformN`).
# The coder window keeps a slider for every parsed uniform; only the first N are
# offered to the Mapper/Sequencer/Cue.
SHADER_MAPPABLE_UNIFORM_SLOTS = 8


MIDI_ACTION_SEQ_TOGGLE = "seq_toggle"


# e66s02: the selector's items, in the order they are offered, each naming its geometry.
# The key IS the label the combo shows, and `f"{rows}x{cols}"` is the same spelling, so
# the map and the live geometry can never disagree about how a geometry is written.
SEQ_GEOMETRY_LABELS: dict[str, tuple[int, int]] = {
    "4x4": (4, 4),
    "4x8": (4, 8),
    "8x4": (8, 4),
    "8x8": (8, 8),
}


MIDI_ACTION_TRANSPORT_PLAY = "transport_play"


MIDI_ACTION_TRANSPORT_RESYNC = "transport_resync"


MIDI_ACTION_TRANSPORT_TAP = "transport_tap"


MIDI_ACTION_NUDGE_BACK = "nudge_back"


MIDI_ACTION_NUDGE_FORWARD = "nudge_forward"


MIDI_ACTION_BEAT_SOURCE = "beat_source"


MIDI_ACTION_TRACK_ASSIGN = "track_assign"


MIDI_ACTION_MAPPER_MAPPING = "mapper_mapping"  # e18: a learned MIDI control drives a Mapper mapping


MIDI_ACTION_MAPPER_CUE_OPEN = "mapper_cue_open"  # e34s05: open a cue-list mapping's window

# e33s02: marker-based learn targets on a Mapper card caption (enable + reset)
MIDI_ACTION_MAPPER_ENABLE = "mapper_enable"  # toggle the e24 armed flag (momentary)
MIDI_ACTION_MAPPER_RESET = "mapper_reset"  # return the control to its neutral default (e27)

# e33s03: marker-based learn targets on the Mapper rows and the card source menu
MIDI_ACTION_MAPPER_LINE = "mapper_line"  # variant B: selected media -> the mapper row (line)
MIDI_ACTION_MAPPER_BAND = "mapper_band"  # bind the mapping to an audio band (2..5)

# e33s04: source browsing + selection-relative actions (Mediagrid learn bar).
# Rule (user, 2026-09-05): bindings never anchor to a volatile source — the
# action applies to the SELECTED source at trigger time.
MIDI_ACTION_SOURCE_NEXT = "source_next"  # select the next source in the grid order (wrap)
MIDI_ACTION_SOURCE_PREV = "source_prev"  # select the previous source in the grid order (wrap)
# e52s04: the same selection move driven by a knob's ROTATION — the resolver
# turns the signed CC delta into detents and hands them to the executor.
MIDI_ACTION_SOURCE_STEP = "source_step"  # params {"steps": signed detent count}
MIDI_ACTION_REGEN_SELECTED = "regen_selected_thumb"  # regen the selected source's thumbs
MIDI_ACTION_SEQ_ROW_ASSIGN = "seq_row_assign"  # selected source -> a sequencer row (slot)
MIDI_ACTION_SEQ_ROW_ENABLE = "seq_row_enable"  # activate every step of a sequencer row
MIDI_ACTION_SEQ_ROW_DISABLE = "seq_row_disable"  # deactivate every step of a sequencer row
MIDI_ACTION_ENABLE_CORRECTION = "enable_correction"  # arm the SELECTED source's CC block
MIDI_ACTION_SET_CURRENT = "set_current"  # make the SELECTED source current in vimix
MIDI_ACTION_SOURCES_DATA_REFRESH = (
    "sources_data_refresh"  # e82s08: one-shot sweep of every readable property
)
MIDI_ACTION_SET_BLENDING = "set_blending"  # set the SELECTED source's blending (enum index)
MIDI_ACTION_IO_MONITOR_TOGGLE = "monitor_toggle"  # e39s01: show/hide the I/O Monitor window
MIDI_ACTION_MAPPING_TOGGLE = "mapping_toggle"  # e40s01: arm/disarm a Mapping (Enabled gate)
MIDI_ACTION_MAPPING_ADD = "mapping_add"  # e40s08: add a State Mapping on a source line

# e51s02: Mapper clipboard + in-line moves (mirror of the sequencer step
# clipboard, e08): Copy/Cut snapshot a Mapping into state.mapper_clipboard,
# Paste appends it to a line (the line resolves at trigger time), Move shifts it
# one slot inside its own line. All four are MIDI-mappable (e33 rule).
MIDI_ACTION_MAPPING_COPY = "mapping_copy"  # snapshot a Mapping into the clipboard
MIDI_ACTION_MAPPING_CUT = "mapping_cut"  # snapshot + remove the Mapping
MIDI_ACTION_MAPPING_MOVE = "mapping_move"  # params mapping_id + delta: shift in its line
MIDI_ACTION_MAPPING_PASTE = "mapping_paste"  # append the clipboard to a line
MIDI_ACTION_PAIRING_PROMPT = "pairing_prompt"  # e42s02: re-pair with viOSC (code prompt)
MIDI_ACTION_FILE_MANAGER_TOGGLE = "file_manager_toggle"  # e43s02: show/hide the File Manager
# e59s02/e59s06: the Text window (e33 rule) — toggle, send, clear the source.
MIDI_ACTION_TEXT_WINDOW_TOGGLE = "text_window_toggle"
MIDI_ACTION_TEXT_SEND = "text_send"
MIDI_ACTION_TEXT_CLEAR = "text_clear"  # e59s06: send an EMPTY contents
# e61s03: the Shader window (e33 rule) — toggle the window, deploy the asset file
# path, load an asset, save the document.
MIDI_ACTION_SHADER_WINDOW_TOGGLE = "shader_window_toggle"
MIDI_ACTION_SHADER_SEND = "shader_send"
MIDI_ACTION_SHADER_LOAD = "shader_load"
MIDI_ACTION_SHADER_SAVE = "shader_save"
MIDI_ACTION_SHADER_BYPASS = "shader_bypass"  # e61s04: effect on/off (filter swap)
# e59s08: progressive reveal modes (momentary: select + first step, then advance).
MIDI_ACTION_TEXT_WORD = "text_word"
MIDI_ACTION_TEXT_WORD_PLUS = "text_word_plus"
MIDI_ACTION_TEXT_LINE = "text_line"
MIDI_ACTION_TEXT_LINE_PLUS = "text_line_plus"
# e33s05: the global actions (window show + project) made mappable.
MIDI_ACTION_SHOW_WINDOW = "show_window"  # params {"window": <tag>}
MIDI_ACTION_PROJECT_NEW = "project_new"
MIDI_ACTION_PROJECT_OPEN = "project_open"
MIDI_ACTION_PROJECT_SAVE = "project_save"

# e52s01: MIDI modes — named, additive layers that gate Bindings. MODE_TOGGLE
# turns ONE named mode on/off from a note (or a CC at the trigger threshold);
# MODES_CLEAR is the all-off panic action. Both are MIDI-mappable (e33 rule).
MIDI_ACTION_MODE_TOGGLE = "mode_toggle"  # params {"mode": name}
MIDI_ACTION_MODES_CLEAR = "modes_clear"


# e39s01: I/O Monitor (diagnostic window). The capture is bounded so a spinning
# wheel can never grow memory; coalescing is for display only (one row per
# control with last/min/max/count). The neutral centre is the app-wide CC/pitch
# midpoint used by _parse_midi_msg; the outcome tags are what the stream and
# controls panes render.
# e39s05: the monitor observes both directions (the I/O Monitor from task 3 on).
IO_MONITOR_TRANSPORT_MIDI = "midi"
IO_MONITOR_TRANSPORT_OSC = "osc"  # the OSC lanes join the same engine (task 2)
IO_MONITOR_TRANSPORT_HTTP = "http"  # e82s05: the data plane is traffic too
IO_MONITOR_DIRECTION_IN = "in"
IO_MONITOR_DIRECTION_OUT = "out"
IO_MONITOR_DIRECTIONS: tuple[str, ...] = (
    IO_MONITOR_DIRECTION_IN,
    IO_MONITOR_DIRECTION_OUT,
)
IO_MONITOR_KIND_MIDI_IN = "midi_in"
IO_MONITOR_KIND_MIDI_OUT = "midi_out"
# e39s05: the OSC kinds say WHY a message exists (the address says what it is).
IO_MONITOR_KIND_VIOSC = "viosc"
IO_MONITOR_KIND_VIMIX = "vimix"
IO_MONITOR_KIND_SYNC = "viosc_sync"
IO_MONITOR_KIND_MONITOR = "viosc_monitor"
IO_MONITOR_KIND_WATCH = "viosc_watch"
IO_MONITOR_KIND_WATCH_REPLY = "watch_reply"
IO_MONITOR_KIND_STATE = "state_broadcast"
IO_MONITOR_KIND_THUMBNAIL = "thumbnail"
IO_MONITOR_KIND_DESTINATION = "destination"
IO_MONITOR_KIND_FADE = "fade"
IO_MONITOR_KIND_SEQUENCER = "sequencer"
IO_MONITOR_KIND_CUE = "cue"
IO_MONITOR_KIND_OSC = "osc"
IO_MONITOR_KIND_SHADER = "shader"  # e61s03: the Shader window's deploy traffic
# e82s05: the HTTP data plane (snapshot, delta stream, interest, thumbnails).
# The KIND column is 8 chars wide (iomonitor.format_stream): these labels must FIT,
# or the Monitor shows a truncated word ("state_pu", "event_st").
IO_MONITOR_KIND_STATE_PULL = "state"
IO_MONITOR_KIND_EVENT_STREAM = "stream"
IO_MONITOR_KIND_INTEREST = "interest"
IO_MONITOR_KIND_THUMB_HTTP = "thumb"
IO_MONITOR_OUTCOME_RECV = "RECV"
# e39s05: a SHORT text/byte arg is summarised by size only beyond this many chars.
IO_MONITOR_SUMMARY_TEXT_MAX = 48

IO_MONITOR_STREAM_LIMIT = 400  # newest stream entries kept
IO_MONITOR_CONTROL_LIMIT = 256  # distinct controls tracked (oldest activity evicted)
IO_MONITOR_NEUTRAL_CENTRE = 64
IO_MONITOR_VALUE_MAX = 127.0
IO_MONITOR_REFRESH_INTERVAL = 0.1  # s; UI text blocks refresh at most this often
IO_MONITOR_OUTCOME_LEARN = "LEARN"
IO_MONITOR_OUTCOME_MATCH = "MATCH"
IO_MONITOR_OUTCOME_SENT = "SENT"
IO_MONITOR_OUTCOME_HOLD = "HOLD"
IO_MONITOR_OUTCOME_MUTED = "MUTED"
IO_MONITOR_OUTCOME_NOMATCH = "NOMATCH"
IO_MONITOR_OUTCOME_NOBIND = "NOBIND"
IO_MONITOR_OUTCOME_IGNORED = "IGNORED"  # e81: a message TYPE the app does not use


# e33s02: momentary learn actions trigger at CC value >= this threshold (MIDI's
# conventional CC-switch split); lower CC values are a deliberate no-op.
MIDI_CC_TRIGGER_THRESHOLD = 64

# e52s01: a mode's optional MIDI LED. The spec reuses the Destination = MIDI
# shape (controller port, channel, kind, number) plus the two values, so the
# mode editor and the Mapping editor look and behave alike.
MIDI_MODE_LED_KINDS: tuple[str, ...] = ("note", "cc")
MIDI_MODE_LED_ON_DEFAULT = 127
MIDI_MODE_LED_OFF_DEFAULT = 0
MIDI_MODE_LED_MIN_VALUE = 0
MIDI_MODE_LED_MAX_VALUE = 127
MIDI_MODE_LED_MIN_CHANNEL = 0
MIDI_MODE_LED_MAX_CHANNEL = 15
MIDI_MODE_LED_MIN_NUMBER = 0
MIDI_MODE_LED_MAX_NUMBER = 127

# e53s01: per-Binding LED feedback. `led_behavior` is how the LED follows its
# action: `press` is a timed flash on the trigger edge, `state` mirrors the
# action's boolean state (e53s02). A profile `feedback.led_mirror` derives the
# LED from the input control (same kind/channel/number), so a whole surface
# lights with no per-binding setup; MIDI_LED_PRESS_MS is the flash length.
MIDI_LED_BEHAVIORS: tuple[str, ...] = ("press", "state")
MIDI_LED_PRESS_MS = 120
MIDI_LED_MIRROR_MODES: tuple[str, ...] = ("note", "cc")
MIDI_LED_BEHAVIOR_PRESS = "press"
MIDI_LED_BEHAVIOR_STATE = "state"

# e52s04: rotation stepping. MIDI_STEP_SIZE is how many CC units make one
# detent; MIDI_STEP_MAX_DELTA is the wrap/glitch guard (a controller wrapping
# 127 -> 0 must not look like a full sweep).
MIDI_STEP_SIZE = 8
MIDI_STEP_MAX_DELTA = 64

# e54s01: the rotation decoder. An absolute knob reports a POSITION (delta between
# messages); a jog wheel / infinite encoder reports MOVEMENT. `relative64` is the
# Xponent convention (value 64 = still, value - 64 = the signed movement);
# `relative2s` is two's complement (1..63 = +n, 65..127 = -(128-n)). The cap
# bounds what ONE message may fire so a fast spin cannot launch a burst.
MIDI_STEP_ENCODINGS: tuple[str, ...] = ("absolute", "relative64", "relative2s")
MIDI_STEP_ENCODING_ABSOLUTE = "absolute"
MIDI_STEP_MAX_STEPS_PER_MESSAGE = 8

# e54s01 (rig feedback 2026-09-21): a wheel can be slower/faster than the default,
# so a profile's `feedback.step_size` (or a per-Binding override) changes how many
# CC units make one detent. Clamped to [1, MIDI_STEP_SIZE_MAX].
MIDI_STEP_SIZE_MAX = 64

# e54s01 (rig feedback 2026-09-21): a fast jog spin must not run away. The step
# budget caps how many steps a control may emit per second (a token bucket,
# refilled at this rate), independently of the message magnitude/rate. Tunable
# per controller through `feedback.max_steps_per_second`.
MIDI_STEP_MAX_PER_SECOND = 8
MIDI_STEP_MAX_PER_SECOND_MAX = 64


# BUG-2026-09-06T124150: pitch-bend levers (DJ pitch faders) send mido
# `pitchwheel`, a 14-bit signed message (-8192..8191, centre 0), not CC. VJmix
# normalizes it onto the app-wide 0..127 value scale so every consumer (Mapper
# input-range seed, trigger thresholds) is unchanged. A pitch wheel has no
# number — the channel is its only discriminator.
MIDI_PITCH_MIN = -8192
MIDI_PITCH_MAX = 8191
MIDI_PITCH_NUMBER = 0
MIDI_PITCH_VALUE_STEPS = 127  # target scale, matching CC/note velocities


DEFAULT_CONFIG: dict[str, Any] = {
    # e11s02: the window layout moved into project files; the config keeps the
    # fallback theme, MIDI and the recent-projects list + restore flag.
    "theme": {"preset": "scuro", "colors": copy.deepcopy(DEFAULT_PALETTE)},
    # e14s02: multi-controller schema — controllers[] replaces the single input_port.
    "midi": {"enabled": False, "controllers": [], "clock_source": None},
    # e26: Leap Motion engine — persisted settings: enabled flag + the e26s04
    # embedded visualizer toggle (both off by default).
    "leap": {"enabled": False, "visualizer": False},
    "projects": {"recent": [], "restore_last_on_boot": True},
    # e28s04: OSC endpoints are rig settings (not project content) — the viOSC
    # client + listening-server IP:port persist app-level like theme/MIDI/Leap.
    "osc": {
        "client_ip": VIOSC_IP,
        "client_port": VIOSC_PORT,
        "listen_ip": VIOSC_IP,
        "listen_port": VIOSC_LISTEN_PORT,
    },
    # e38: source video preview — the viOSC HTTP file-server port (same host as
    # the OSC client, machine A). Only the port is tunable; the host always
    # follows the configured osc client_ip.
    "preview": {"port": PREVIEW_PORT},
    # e76: display preferences that are not project content. Hover help is ON by
    # default; a VJ switches it off while performing.
    "ui": {"hover_help": True},
}


# e14: a Learn session can never hijack the sequencer controls indefinitely — it
# auto-exits after this many seconds if no capture completes.
MIDI_LEARN_TIMEOUT_SECONDS = 30.0

# e47: the learn red — the fixed accent shared by the `M` learn markers and the
# toolbar MIDI Learn ON state (ADR-midi-learn-entry-point.md). Fixed on every
# palette by user decision: red is the learn colour and must stay distinguishable
# from the accent that marks the active window, so it is a constant rather than a
# palette slot. The RGBA the themes need derives from it — one source, no drift.
MIDI_LEARN_RED: tuple[int, int, int] = (225, 60, 60)
MIDI_LEARN_RED_RGBA: tuple[int, int, int, int] = (*MIDI_LEARN_RED, 255)


# BUG-2026-09-07: after a failed input open (or clock reconnect) the worker waits
# this long before trying again. Every failing mido/rtmidi open can leak an ALSA
# sequencer client (mido #256, fixed only in 1.3.4.dev+), so a dead ALSA must
# never be hammered — the 2 s retry loop saturated the 192-client kernel table
# on the live rig and silently killed controller detection.
MIDI_OPEN_RETRY_COOLDOWN_SECONDS = 15.0

# e53 (rig feedback 2026-09-21): a powered-off controller can leave a stale open
# input port in the worker, so a power-cycle is never noticed and the LED
# handshake (setup SysEx) is never re-sent until VJmix restarts. The worker
# re-reads the live port list at this cadence and drops the stale ones.
MIDI_PORT_RESCAN_SECONDS = 1.0


PROJECT_FORMAT = "vjmix-project"


# e66s01: the sequencer's project section became a LIST of records
# (`sequencers: [ {rows, cols, …} ]`), so this build WRITES version 2 and still READS
# version 1. The bump is deliberate and it is the reason the migration is total: an
# older build opening a v2 file looks for the singular `sequencer` key, finds nothing,
# and would silently load an EMPTY sequencer — the version gate turns that silent data
# loss into a legible refusal. Nothing else in the document changed, so the shape
# difference is confined to that one section.
PROJECT_VERSION = 2
PROJECT_VERSIONS_READABLE = (1, 2)


PROJECT_FILE_EXTENSION = ".vjmix"


RECENT_PROJECTS_MAX = 5  # cap for the Last-project submenu / config list (e11s02)


STEP_PERSISTED_KEYS: tuple[str, ...] = ("active", "type", "v1", "v2", "frames", "msgs", "color")


# e28s01: the mapping-model keys that survive in a project file (capture whitelist /
# sanitize schema). The runtime model never gains a key that is not persisted here.
MAPPER_PERSISTED_KEYS: tuple[str, ...] = (
    "id",
    "target_id",
    "property",
    "component",  # e36s02: controlled axis/channel of a multi-value property (None for scalar)
    "control",
    "value",
    "band",
    "midi",
    "leap",
    "output_from",
    "output_to",
    "input_from",
    "input_to",
    "button_mode",  # e77: how the GUI button behaves on a press (toggle / momentary)
    "enabled",
    "cue",  # e35s01: the per-mapping cue macro (rows + gap_ms), inert for non-cue-list controls
    # e40s01: a Mapping is a Mapping (Origin -> Rescale -> Destination). Legacy rows
    # carry none of these keys and hydrate to Control -> Vimix, so old project
    # files load unchanged; the new keys are additive.
    "origin",
    "destination",
    "destination_spec",
    "origin_spec",
    "cadence",
    "steps",
)


# e40s01: the Mapping discriminators (ADR-mapping-model). Origin = where the value
# comes from; Destination = where it goes.
ORIGIN_CONTROL = "control"  # a physical control / band / MIDI / Leap drives the value
ORIGIN_STATE = "state"  # a live Vimix property of a source is read
ORIGIN_CLOCK = "clock"  # a transport/app quantity (beat, BPM, step, cue progress)
ORIGIN_CONST = "const"  # a fixed value
ORIGINS: tuple[str, ...] = (ORIGIN_CONTROL, ORIGIN_STATE, ORIGIN_CLOCK, ORIGIN_CONST)
DEST_VIMIX = "vimix"  # writes /vimix/<source>/<property>
DEST_MIDI = "midi"  # writes a MIDI note/CC to a controller output port
DEST_OSC = "osc"  # writes an OSC message to a third-party host/port/address
DESTINATIONS: tuple[str, ...] = (DEST_VIMIX, DEST_MIDI, DEST_OSC)
# The default state Origin cadence: viOSC's sync_interval default (ADR: it stays 2 s).
MAPPING_DEFAULT_CADENCE_MS = 2000
MAPPING_MIN_CADENCE_MS = 20  # sanity floor for a per-Mapping cadence
MAPPING_RESYNC_EPSILON = 1e-6  # a live state change below this is not a resync
MAPPING_TICK_INTERVAL_S = 1.0 / 30.0  # emission tick cap (ADR: named constant)
MAPPING_MIDI_EMIT_EPSILON = 0.5  # one MIDI step (integer note velocity / CC)
MAPPING_OSC_EMIT_EPSILON = 1e-4  # a float OSC argument needs a real change
# MIDI Destination kinds (destination_spec['type'])
MIDI_KIND_NOTE = "note"
MIDI_KIND_CC = "cc"
MAPPING_STEPS_CONTINUOUS = 1  # quantisation steps <= 1 means no quantisation
# e66s01: the sequencer-column Clock Origin. Named because the geometry seed reads it.
CLOCK_STEP = "step"
# e40s02: the source-less Clock Origins and their natural value windows (the
# seeded Origin window; the value comes from the live transport/app state).
# e66s01: `step` is the sequencer's live COLUMN, so this window is the CAP of the tag
# space and NOT what a new mapping should seed with — a 4-column sequencer would spend
# half its output range on columns it does not have. `mapper.clock_window` seeds from the
# live `cols - 1` instead, and this entry stays the declared fallback for any kind that
# does not depend on the geometry.
CLOCK_SOURCES: dict[str, tuple[float, float]] = {
    "bpm": (0.0, 300.0),
    CLOCK_STEP: (0.0, 7.0),  # sequencer column, NUM_STEPS - 1
    "playing": (0.0, 1.0),  # transport flag as a value
}
CLOCK_DEFAULT = "bpm"
MAPPING_CONST_VALUE_MIN = -10.0
MAPPING_CONST_VALUE_MAX = 10.0
MAPPING_CONST_VALUE_DEFAULT = 0.5
# e40s03: an OSC Destination is a new, opt-in network egress: fixed address, one
# value argument (ADR decision 8). These are the defaults of a fresh Mapping.
MAPPING_OSC_DEFAULT_HOST = "127.0.0.1"
MAPPING_OSC_DEFAULT_PORT = 9000
# FROZEN CONTRACT VALUE as of VJmix 1.0.0 — the default OSC destination of a Mapper
# output. Deliberately renamed with the app (VJmix 1.0.0, user decision): a receiver
# still configured for the pre-1.0 address `/viseq/mapping` must be pointed at
# `/vjmix/mapping`. Everything else in the OSC contract (Vimix's attributes, the
# `/viosc/*` surface, the state keys) stays frozen.
MAPPING_OSC_DEFAULT_ADDRESS = "/vjmix/mapping"
MAPPING_OSC_MAX_PORT = 65535
MAPPING_DIRECTIONS: dict[str, tuple[str, ...]] = {
    ORIGIN_CONTROL: (DEST_VIMIX,),  # v1: a Control Origin keeps writing Vimix
    ORIGIN_STATE: (DEST_MIDI, DEST_OSC),
    ORIGIN_CLOCK: (DEST_MIDI, DEST_OSC),
    ORIGIN_CONST: (DEST_MIDI, DEST_OSC),
}


# e28s01: restore cap for the mapper section of a project file — a corrupted or
# hand-edited document cannot balloon the live mapper beyond this many mappings.
MAPPER_MAX_MAPPINGS = 256


NUM_STEPS = 8


NUM_TRACKS = 8


# e66s01: the sequencer's size stops being the instrument's identity. NUM_STEPS and
# NUM_TRACKS keep their value as the CAP — and, with it, as the width of the tag space
# the grid builds ONCE (`seq_cell_{r}_{c}` for r, c in 0..7, so a geometry change cannot
# rename a live alias) — while the LIVE geometry becomes a value in
# SEQ_GEOMETRY_CHOICES per axis. User decision D1 (2026-10-12): exactly {4, 8}; 2 and 6
# were offered and refused. The cap and the default COINCIDE (8). That is why ONE
# sanitizer serves both axes: a fresh grid is the cap, and so is every doubt.
SEQ_MAX_ROWS = NUM_TRACKS
SEQ_MAX_COLS = NUM_STEPS
SEQ_GEOMETRY_CHOICES = (4, 8)
SEQ_GEOMETRY_DEFAULT = SEQ_MAX_ROWS


BEAT_SOURCE_ANALYSIS = "bpm_analysis"


BEAT_SOURCE_BAND1 = "band1_beat"


BEAT_SOURCE_MIDI = "midi_sync"


BEAT_SOURCE_MANUAL = "manual_bpm"


# e75: the shared Ableton Link session tempo/beat phase (the LINK box).
BEAT_SOURCE_LINK = "ableton_link"


BEAT_SOURCE_LABELS = {
    BEAT_SOURCE_ANALYSIS: "BPM Det",
    BEAT_SOURCE_BAND1: "Band 1",
    BEAT_SOURCE_MIDI: "MIDI",
    BEAT_SOURCE_LINK: "Link",
    BEAT_SOURCE_MANUAL: "Manual",
}

# e74s07: each beat-source option is enclosed in a bordered box together with its own
# tools. A child_window in a horizontal row fills the available width unless it is GIVEN
# one, so the box widths are explicit. The box's inner height must be at least the tallest
# row item or the content is CLIPPED (which hid the LED on the first attempt): the box
# carries `theme_beat_box`, whose WindowPadding is (4, SEQ_BEAT_BOX_PAD_Y). Widths are the
# measured content plus the left/right padding, kept tight so the boxes sit close.
SEQ_BEAT_BOX_HEIGHT = 25  # 2 * SEQ_BEAT_BOX_PAD_Y + the row item height
SEQ_BEAT_BOX_PAD_Y = 3
SEQ_BEAT_ROW_ITEM_H = 19  # the checkbox and the input are ~19 px tall
SEQ_BEAT_TAP_HEIGHT = SEQ_BEAT_ROW_ITEM_H  # the TAP matches the row, not taller
SEQ_BEAT_LED_W = 14
SEQ_BEAT_LED_H = SEQ_BEAT_ROW_ITEM_H  # the LED is as tall as the row, so it centres in it
# The width must hold the WHOLE row INCLUDING the LED drawlist (measured: the group of
# Analyse is 150 px, Band 1 83, MIDI 69, Manual ~250) plus the 2 * 4 px padding; the first
# widths were the checkbox extent only, so Band 1 and MIDI clipped their LED away.
SEQ_BEAT_BOX_WIDTHS: dict[str, int] = {
    BEAT_SOURCE_ANALYSIS: 140,  # e74s09: the readout is the value alone -> the box shrinks
    BEAT_SOURCE_BAND1: 96,
    BEAT_SOURCE_MIDI: 82,
    BEAT_SOURCE_LINK: 122,  # e75: checkbox + LED + the Link tempo readout
    BEAT_SOURCE_MANUAL: 232,
}

# e74s07c: the transport row WRAPS. DearPyGui has no flow layout, so the row is built as
# LINES of ATOMIC blocks (the transport buttons, one box per beat source, the delete X).
# Every block width is known, so a pure greedy wrap decides the break points for the
# window's width and the row is rebuilt only when the WRAP changes (not on every pixel of
# a resize drag). A narrow window — a two-column sequencer — then puts the tools on a
# second line instead of stretching one long strip.
TRANSPORT_ROW_SIDE_PAD = 20  # window padding + slack
TRANSPORT_ROW_DEFAULT_WIDTH = 1000  # before the window can be measured (boot, tests)
TRANSPORT_ROW_MIN_WIDTH = 200  # one block always fits, however narrow the window
TRANSPORT_BLOCK_GAP = 4  # ItemSpacing of theme_seq_row_compact
TRANSPORT_PLAY_W = 60
TRANSPORT_NUDGE_W = 28
TRANSPORT_RESYNC_W = 28  # e74s07c: RESYNC is a single 'R'
TRANSPORT_BUTTON_H = 26


DEFAULT_MANUAL_BPM = 120.0  # manual-mode BPM default (New project + sanitize fallback)


MIDI_CLOCK_PULSES_PER_BEAT = 24  # MIDI standard: 24 clock pulses (0xF8) per quarter note


BPM_DETECTION_STALE_SECONDS = 2.0  # 2x the 1 s analysis cadence


SPECTRUM_FFT_SIZE = 2048  # samples per FFT frame


SPECTRUM_BARS = 16


NUM_BANDS = 5  # independent selectable analyzer bands (band1..band5)

# e71s01: the bands a Mapper mapping may bind — band 1 stays the sequencer's BEAT source
# (e10s07), so it is not a Mapper source. Derived from the count so the two cannot drift.
BAND_SOURCES: tuple[int, ...] = tuple(range(2, NUM_BANDS + 1))


SPECTRUM_FPS = 30.0  # spectrum redraw rate while analyzing


SPECTRUM_DB_FLOOR = 60.0  # dB below full scale mapped to bar level 0


SPECTRUM_F_MIN = 40.0  # Hz: bottom of the perceptual bar range (sub-bass edge)


SPECTRUM_F_MAX = 20000.0  # Hz: top of the perceptual bar range (below Nyquist)


SPECTRUM_PEAK_TARGET = 0.9  # AGC: the recent spectral peak maps to this level


SPECTRUM_PEAK_FLOOR = 0.06  # AGC: below this peak the gain stays flat (silence guard)


SPECTRUM_PEAK_DECAY = 0.995  # AGC release per frame (~-0.04 dB/frame, ≈ -1.3 dB/s):


BAND_AGG_WEIGHT = 0.6  # band value = weight*peak + (1-weight)*mean of the band bars


BAND_BEAT_THRESHOLD = 0.6


SPEC_DRAWLIST_W = 330  # spectrum drawlist width (px)


SPEC_DRAWLIST_H = 66  # spectrum drawlist height (px) — tall enough to read the bars


# e50s01: mouse-editable band rectangles. The grab tolerance is in drawlist
# pixels, the minimum span keeps a dragged window a real window (an empty or
# inverted level window makes band_value_from_bars fall back to the plain bar
# mean, so a collapsed rectangle would silently change the band's meaning).
BAND_RECT_HIT_TOLERANCE_PX = 6.0
BAND_RECT_MIN_SPAN = 0.01
BAND_EDGE_LEFT = "left"
BAND_EDGE_RIGHT = "right"
BAND_EDGE_TOP = "top"
BAND_EDGE_BOTTOM = "bottom"
BAND_EDGE_BODY = "body"  # the whole-window move (e50s02)
BAND_EDGE_HIGHLIGHT_THICKNESS = 2.0  # px: the armed-edge highlight line (e50s01)
# the GLOBAL mouse handler registry: DPG 2.x accepts mouse_* handlers only there
# (an item_handler_registry takes just the item_* handlers)
SPECTRUM_MOUSE_REG = "spec_drawlist_mouse_reg"


THUMB_CYCLE_INTERVAL = 0.75  # seconds per frame in the Mediagrid thumb cycle


THUMB_FAIL_THRESHOLD = 5  # request cycles (~15 s) before the tile flips to failed


THUMB_FAIL_LABEL = " [ Thumb failed — right-click to retry ] "


GRID_LED_OFF = "off"


GRID_LED_WHITE = "white"


GRID_LED_RED = "red"


GRID_LED_AMBER = "amber"


GRID_LED_GREEN = "green"


GRID_FLASH_SECONDS = 0.12  # beat flash pulse duration (timer restores the head color)


# e43s03: File Manager thumbnails. The texture namespace is prefixed so the
# browser's per-file textures can never collide with a source thumbnail (and the
# state-table prune must skip them). Only the current page's media files are
# requested, capped, so a huge folder cannot fan out.
FS_THUMB_PREFIX = "fs:"
FS_THUMB_MAX_REQUESTS = 60
FS_THUMB_W = 64
FS_THUMB_H = 36


# e43s05: Session Drafts — the application-level library is written on a debounce
# after a change (a rename storm must not rewrite the file per keystroke).
DRAFTS_SAVE_DEBOUNCE_S = 1.0


# e43s07: Session Draft actions (Save/Send are mouse buttons; these are the
# stable MIDI-mappable actions, e33 rule). e44s02 adds draft_save.
MIDI_ACTION_DRAFT_LOAD = "draft_load"
MIDI_ACTION_DRAFT_NEXT = "draft_next"
MIDI_ACTION_DRAFT_PREV = "draft_prev"
MIDI_ACTION_DRAFT_SAVE = "draft_save"

# e54s02: rotary stepping targets. A `*_step` action carries the resolver's
# signed `steps` and fires its momentary pair by rotation (STEP_ACTIONS in
# vjmixapp/actions.py); the momentary `file_next`/`file_prev` step the File
# Manager selection through `state.fs_entries`.
MIDI_ACTION_DRAFT_STEP = "draft_step"
MIDI_ACTION_FILE_STEP = "file_step"
MIDI_ACTION_FILE_NEXT = "file_next"
MIDI_ACTION_FILE_PREV = "file_prev"
