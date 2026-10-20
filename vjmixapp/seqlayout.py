"""The sequencer grid's layout arithmetic: one zoom level -> every pixel it needs.

e66s03. The cell was a set of import-time literals (`STEP_CELL_SIZE = 90`, a 40 px
colour square, drags of 70 and 34 px, a list of indents and spacers, and the clip
slot's own widths) spread over `update_step_ui`, `update_track_slot_ui` and
`constants.py`. A zoom level multiplies them all by one factor, and this module is the
ONE place that arithmetic lives.

Why a module rather than a helper in the composition root: the numbers are shared by the
cell builder, the slot builder and the in-place sweep, and they must be computable
WITHOUT DearPyGui so every level's geometry can be tested headlessly — the alternative is
discovering a broken layout on the rig.

The FLOORS are the point of the module. A level scales; a floor protects the smallest
one, because a drag box too narrow to read its own value is worse than a cell that is
slightly larger than the level asked for.
"""

from dataclasses import dataclass

from vjmixapp.constants import (
    SEQ_ZOOM_DEFAULT,
    SLOT_BUTTON_FRAME_INSET,
    SLOT_BUTTON_HEIGHT,
    SLOT_BUTTON_WIDTH,
    SLOT_WIDTH,
    STEP_CELL_CONTENT_PADDING,
    STEP_CELL_SIZE,
    STEP_COLOR_SQUARE_SIZE,
)

# The smallest sizes that still work, whatever a level computes. `drag_wide` is the
# single-value editor (`%.2f`), `drag_narrow` one of the two boxes a fade lays out per
# row, `color_square` the swatch a colour step shows. Below these the widget stops being
# usable long before it stops being drawable.
MIN_DRAG_WIDE = 46
MIN_DRAG_NARROW = 24
MIN_COLOR_SQUARE = 26
MIN_CONTENT_PADDING = 4
MIN_TEXT_INDENT = 10
MIN_LABEL_FONT = 9

# Label font size at the default level, scaled like everything else (e66s03).
LABEL_FONT_SIZE = 12


@dataclass(frozen=True)
class SeqCellLayout:
    """Every pixel one cell, its widgets and the clip slot need at ONE zoom level."""

    level: int
    scale: float
    font_size: int
    cell: int
    content_padding: int
    color_square: int
    color_square_indent: int
    drag_wide: int
    drag_narrow: int
    spacer_tall: int
    spacer_mid: int
    spacer_short: int
    text_indent: int
    slot_width: int
    slot_height: int
    slot_button_width: int
    slot_button_height: int
    slot_button_inset: int
    slot_button_indent: int
    slot_button_top_spacer: int


def _scaled(base: int, scale: float, floor: int) -> int:
    """One size at one level, never below its floor (e66s03)."""
    return max(floor, round(base * scale))


def cell_layout(level: int = SEQ_ZOOM_DEFAULT) -> SeqCellLayout:
    """The whole cell + slot geometry of a zoom level (pure, dpg-free, e66s03).

    At the DEFAULT level every derived size equals its base constant exactly, so the
    shipped look is the reference and a level is a departure from it rather than a
    redefinition. The cell and the slot share one height BY CONSTRUCTION (both scale from
    the same base), which is what keeps the rows aligned when a level changes: a grid
    whose cell and slot disagree is a misaligned grid.
    """
    scale = level / SEQ_ZOOM_DEFAULT
    cell = _scaled(STEP_CELL_SIZE, scale, MIN_COLOR_SQUARE + 2 * MIN_CONTENT_PADDING)
    content_padding = _scaled(STEP_CELL_CONTENT_PADDING, scale, MIN_CONTENT_PADDING)
    color_square = _scaled(STEP_COLOR_SQUARE_SIZE, scale, MIN_COLOR_SQUARE)
    slot_width = _scaled(SLOT_WIDTH, scale, SLOT_BUTTON_WIDTH)
    # The slot's height IS the cell's, and that is not a shortcut: `SLOT_HEIGHT` and
    # `STEP_CELL_SIZE` are the same 90 px base, and scaling them SEPARATELY let their two
    # floors diverge — at 64 px the slot's floor (70) exceeded the cell (64) and the rows
    # went askew. One value, one height, no way to drift.
    slot_height = cell
    slot_button_width = _scaled(SLOT_BUTTON_WIDTH, scale, MIN_DRAG_WIDE)
    slot_button_height = _scaled(SLOT_BUTTON_HEIGHT, scale, MIN_DRAG_NARROW)
    slot_button_inset = _scaled(SLOT_BUTTON_FRAME_INSET, scale, 2)
    return SeqCellLayout(
        level=level,
        scale=scale,
        font_size=_scaled(LABEL_FONT_SIZE, scale, MIN_LABEL_FONT),
        cell=cell,
        content_padding=content_padding,
        color_square=color_square,
        color_square_indent=(cell - 2 * content_padding - color_square) // 2,
        drag_wide=_scaled(70, scale, MIN_DRAG_WIDE),
        drag_narrow=_scaled(34, scale, MIN_DRAG_NARROW),
        spacer_tall=_scaled(6, scale, 2),
        spacer_mid=_scaled(5, scale, 2),
        spacer_short=_scaled(2, scale, 1),
        text_indent=_scaled(20, scale, MIN_TEXT_INDENT),
        slot_width=slot_width,
        slot_height=slot_height,
        slot_button_width=slot_button_width,
        slot_button_height=slot_button_height,
        slot_button_inset=slot_button_inset,
        slot_button_indent=(slot_width - slot_button_width) // 2,
        slot_button_top_spacer=(slot_height - slot_button_height) // 2 - slot_button_inset,
    )
