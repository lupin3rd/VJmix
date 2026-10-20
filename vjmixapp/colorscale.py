"""The DPG colour-scale conversions, as a dpg-free leaf (HIGH-1).

DPG 2.x parses colour lists by dividing every channel by 255, so a colour pushed
programmatically (`default_value` / `set_value`) must arrive on the 0..255 scale
while a user-picked one arrives normalized 0..1. Those conversions are pure, and
they are needed by BOTH a UI module and a WORKER module: `palette` owns the theme
table (and therefore imports dearpygui at module level), while `sequencer` colours
a step cell through the queued `set_value` from its own thread.

They live in this leaf so the worker import chain stays free of the GUI toolkit
(BUG-2026-10-08T233000): `palette` re-exports them, so every existing caller keeps
its import unchanged.
"""

from vjmixapp.constants import DPG_COLOR_SCALE


def dpg_color_value(rgb: list[float]) -> list[float]:
    """Convert normalized 0..1 RGB to DPG's color API scale (0..255)."""
    return [round(c * DPG_COLOR_SCALE, 2) for c in rgb]


def dpg_color_rgba(rgb: list[float]) -> list[float]:
    """DPG-scale RGB plus an opaque alpha (color_button needs 4 components)."""
    return [*dpg_color_value(rgb), DPG_COLOR_SCALE]


def palette_rgba(color: list[int]) -> list[int]:
    """Palette RGB (0..255) plus an opaque alpha, the DPG color shape for themes/widgets."""
    return [color[0], color[1], color[2], 255]
