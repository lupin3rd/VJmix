"""The compact status of one source tile (e83). DPG-free (HIGH-1).

One tile shows, at a glance: whether the source is playing (P), whether its colour
correction is active (C), whether it is locked (L), the blending mode, the depth,
the speed and the seek position. The three toggles are badges drawn on the
thumbnail, the seek is a 4 px bar, and everything else is ONE 10 px line — all
inside the existing 104 px tile, whose layout must not grow.

The seek is the only value that is not polled: the state tier answers it once per
second, and the bar moves smoothly between answers by dead reckoning, exactly like
the Mapper does (`speed` and `play` are already in the tier, so the inputs are
there).

ASCII ONLY: the UI renders in a pixel font and a missing glyph falls back
(BUG-2026-09-18T193805), so the separator is a space and speed is `x1.00`, never
the multiplication sign.
"""

from typing import Any

# The wiki's blending order, 0..7. The tile shows vimix's own ICON for the mode
# (one cell of the 8 in assets/blending_icons.png, in this same order), so the
# names are only for diagnostics and documentation.
BLENDING_NAMES: tuple[str, ...] = (
    "Normal",
    "Screen",
    "Subtract",
    "Multiply",
    "Hard light",
    "Soft light",
    "Soft subtract",
    "Lighten only",
)
BLENDING_CELLS = len(BLENDING_NAMES)
SEEK_MIN = 0.0
SEEK_MAX = 1.0


def blending_index(value: Any) -> int | None:
    """The 0..7 blending index of a vimix answer, or None when it is not one."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    index = round(float(value))
    if 0 <= index < BLENDING_CELLS:
        return index
    return None


def blending_name(value: Any) -> str | None:
    """The wiki's name of a blending index (diagnostics; the tile shows the icon)."""
    index = blending_index(value)
    return BLENDING_NAMES[index] if index is not None else None


def blending_uv(value: Any) -> tuple[tuple[float, float], tuple[float, float]] | None:
    """The uv rectangle of one blending icon in the strip, or None (e83).

    The strip is a horizontal row of BLENDING_CELLS cells, so cell i spans
    u in [i/8, (i+1)/8] and the whole height.
    """
    index = blending_index(value)
    if index is None:
        return None
    step = 1.0 / BLENDING_CELLS
    return (index * step, 0.0), ((index + 1) * step, 1.0)


def depth_text(value: Any) -> str | None:
    """`D6.0` — the depth with one decimal, or None when it is not a number."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return f"D{float(value):.1f}"


def speed_text(value: Any) -> str | None:
    """`x1.00` — the playback rate with two decimals, or None."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return f"x{float(value):.2f}"


def is_on(value: Any) -> bool:
    """A vimix flag (`play`, `lock`, `correction`) is a float > 0.5."""
    if isinstance(value, bool):
        return value
    return isinstance(value, (int, float)) and float(value) > 0.5


def seek_now(
    last_seek: Any,
    speed: Any,
    playing: Any,
    elapsed_s: Any,
    duration_s: Any = None,
) -> float:
    """The seek fraction extrapolated from the last REAL value (dead reckoning).

    `seek` is a FRACTION of the clip, so the advance per second is
    `speed / duration`, never `speed`: without the clip length the bar used to
    saturate to 100% in one second (the operator's sawtooth). An unknown duration
    therefore FREEZES the bar on the last real value — never a guess.

    Clamped to 0..1; a paused source, a non-numeric speed or an elapsed <= 0 all
    return the last real value, so a stall never moves the bar.
    """
    try:
        base = float(last_seek)
    except (TypeError, ValueError):
        return 0.0  # unknown base: extrapolating from zero would be a guess
    base = max(SEEK_MIN, min(SEEK_MAX, base))
    if not is_on(playing) or not isinstance(elapsed_s, (int, float)):
        return base
    try:
        duration = float(duration_s)
    except (TypeError, ValueError):
        return base
    if duration <= 0.0:
        return base
    elapsed = max(0.0, float(elapsed_s))
    rate = float(speed) if isinstance(speed, (int, float)) and not isinstance(speed, bool) else 1.0
    if elapsed <= 0.0 or rate <= 0.0:
        return base
    return max(SEEK_MIN, min(SEEK_MAX, base + rate * elapsed / duration))
