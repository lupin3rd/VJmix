"""SO (Secondary Output) transport dispatcher for VJmix (e95).

The SO is one mirrored egress with two transports: OSC (the e92 wire path) and
MIDI (an output port chosen by name). Mappings and sequencer steps call
``send_so`` and stay transport-blind. WORKER-SAFE: no dpg import (HIGH-1).
"""

from __future__ import annotations

from typing import Any

from vjmixapp import osc
from vjmixapp.constants import (
    MAPPING_SO_DEFAULT_TRANSPORT,
    MAPPING_SO_MIDI_SCALE_TO,
    SECONDARY_OUTPUT_TRANSPORTS,
)


def transport_of(spec: Any) -> str:
    """The SO spec's transport; an absent key is the e92 OSC default (e95)."""
    if not isinstance(spec, dict):
        return ""
    return str(spec.get("transport") or MAPPING_SO_DEFAULT_TRANSPORT)


def secondary_output_midi_value(
    spec: Any,
    value: float,
    output_from: float | None = None,
    output_to: float | None = None,
) -> int:
    """The 0..127 MIDI value of one SO send (e95).

    An explicit ``from``/``to`` scale wins (the e92 math, reversed intervals
    included). Without a scale, a Mapping's output interval maps onto
    ``0..127`` so a 0..1 value lands mid-range instead of being clamped to 0;
    a sequencer step (no output interval) sends its fixed value as-is. A
    degenerate output interval yields 0. The result is rounded and clamped.
    """
    explicit = isinstance(spec, dict) and ("from" in spec or "to" in spec)
    if output_from is None or output_to is None:
        scaled = float(value)
    elif explicit:
        scaled = osc.secondary_output_value(spec, value, output_from, output_to)
    else:
        low, high = float(output_from), float(output_to)
        unit = 0.0 if high == low else (float(value) - low) / (high - low)
        scaled = unit * MAPPING_SO_MIDI_SCALE_TO
    return max(0, min(127, round(scaled)))


def send_so(
    spec: Any,
    value: float,
    output_from: float | None = None,
    output_to: float | None = None,
) -> bool:
    """Send one SO value on its transport; False when nothing was sent (e95).

    Best-effort, like the e92 sender: an unknown transport or a refused spec is
    False, never an exception into the Mapper or the beat thread.
    """
    transport = transport_of(spec)
    if transport not in SECONDARY_OUTPUT_TRANSPORTS:
        return False
    if transport == "midi":
        # Lazy: midi imports mapper, so a module-level import would cycle.
        from vjmixapp import midi

        return midi.send_secondary_output_midi(
            spec, secondary_output_midi_value(spec, value, output_from, output_to)
        )
    return osc.send_secondary_output(spec, float(value), output_from, output_to)
