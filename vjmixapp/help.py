"""Hover-help prose catalog (e76s01).

The ONE place the explanations live: `vjmix.py` only attaches them to widgets.
Pure data + pure helpers — no dpg, no state, no I/O (HIGH-1), so the tests can
walk the whole catalog without a viewport.

Keys are stable dotted names, ``"<surface>.<control>"``, never a widget tag: a
tag can be renamed or rebuilt (the Mapper editor is rebuilt on every open) while
the explanation stays. The option VALUES duplicate the app's vocabulary on
purpose and a test proves them identical to the live tuples — that test, not a
comment, is what keeps the two from drifting.

Every string is ASCII: tooltips render in ProggyClean, which shows a fallback
glyph for anything else (BUG-2026-09-18T193805). Every string is short by
construction: the caps in ``constants.py`` are asserted by the gate.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from vjmixapp import catalog
from vjmixapp.constants import (
    CLOCK_DEFAULT,
    CLOCK_STEP,
    DEST_MIDI,
    DEST_OSC,
    DEST_VIMIX,
    MIDI_KIND_CC,
    MIDI_KIND_NOTE,
    ORIGIN_CLOCK,
    ORIGIN_CONST,
    ORIGIN_CONTROL,
    ORIGIN_STATE,
)


@dataclass(frozen=True)
class HelpEntry:
    """One hover card: a title, an optional body, an optional option table."""

    title: str
    body: str = ""
    options: tuple[tuple[str, str], ...] = ()


# e76s01: the enumerated cards — their values are the app's vocabulary verbatim.
HELP: dict[str, HelpEntry] = {
    "mapper.type": HelpEntry(
        "Type",
        "Where the incoming value comes from. It decides the fields below.",
        (
            (ORIGIN_CONTROL, "a MIDI control drives the value live"),
            (ORIGIN_STATE, "read a live Vimix attribute of the source"),
            (ORIGIN_CLOCK, "transport values: bpm, step, playing"),
            (ORIGIN_CONST, "a fixed value you type"),
        ),
    ),
    "mapper.destination": HelpEntry(
        "Destination",
        "Where the value goes. Only the ones this Type allows are listed.",
        (
            (DEST_VIMIX, "write a Vimix attribute (OSC /vimix/...)"),
            (DEST_MIDI, "send a CC or note to a controller"),
            (DEST_OSC, "send to any host:port/address"),
        ),
    ),
    "mapper.control": HelpEntry(
        "Control",
        "The Mapper card's widget: how you drive the value.",
        (
            ("slider", "one continuous value, 0 to 1"),
            ("knob", "rotary control, 0 to 1"),
            ("button", "momentary press, toggles output"),
            ("cue list", "a trigger that runs a cue list"),
        ),
    ),
    "mapper.button_mode": HelpEntry(
        "Button mode",
        "What the GUI square does when you press it.",
        (
            ("toggle", "press flips ON and OFF, and stays"),
            ("momentary", "press fires once, then the square goes OFF"),
        ),
    ),
    "mapper.clock": HelpEntry(
        "Clock",
        "Which transport value the Mapping reads.",
        (
            (CLOCK_DEFAULT, "tempo in beats per minute"),
            (CLOCK_STEP, "the sequencer's live column"),
            ("playing", "1 while the transport plays"),
        ),
    ),
    "mapper.message": HelpEntry(
        "Message",
        "The MIDI message kind sent to the controller.",
        (
            (MIDI_KIND_CC, "control change, 0 to 127"),
            (MIDI_KIND_NOTE, "note on/off with velocity"),
        ),
    ),
    "mapper.source": HelpEntry(
        "Source",
        "The Vimix source this Mapping writes to, or reads from.",
    ),
    "mapper.property": HelpEntry(
        "Property",
        "The Vimix attribute the Mapping drives. Each one shows its own range.",
    ),
    "mapper.component": HelpEntry(
        "Component",
        "Which value of a multi-value property this Mapping drives.",
    ),
    "mapper.cadence": HelpEntry(
        "Cadence (ms)",
        "How often a State or Clock Origin reads the value, in milliseconds.",
    ),
    "mapper.value": HelpEntry("Value", "The fixed value a Constant Origin sends."),
    "mapper.controller": HelpEntry(
        "Controller", "The MIDI output port this Destination writes to."
    ),
    "mapper.channel": HelpEntry("Channel", "MIDI channel, 0 to 15."),
    "mapper.number": HelpEntry("Number", "The CC number or the note number, 0 to 127."),
    "mapper.host": HelpEntry("Host", "IP address of the OSC receiver."),
    "mapper.port": HelpEntry("Port", "UDP port of the OSC receiver."),
    "mapper.address": HelpEntry("Address", "OSC address path, for example /vjmix/mapping."),
    "mapper.steps": HelpEntry(
        "Steps (1 = continuous)",
        "1 = continuous. 2 = on/off. N = N discrete levels.",
    ),
    "tile.blending": HelpEntry(
        "Blending",
        "How the source is composited onto the layer below.",
        (
            ("Normal", "opaque, replaces what is below"),
            ("Screen", "brightens: 1 - (1-a)(1-b)"),
            ("Subtract", "b minus a, clamped at zero"),
            ("Multiply", "darkens by the product"),
            ("Hard light", "strong light overlay"),
            ("Soft light", "gentle light overlay"),
            ("Soft subtract", "gentle subtract blend"),
            ("Lighten only", "keeps the brighter pixel"),
        ),
    ),
    "cue.row_kind": HelpEntry(
        "Row kind",
        "What one row of a cue list does when it fires.",
        (
            ("property", "write a Vimix property"),
            ("wait", "pause for N milliseconds"),
            ("mapper", "trigger a Mapper row"),
            ("burst", "fire a short burst of messages"),
        ),
    ),
    "quality.invert": HelpEntry(
        "Invert",
        "Which channels the invert inverts.",
        (
            ("None", "no inversion"),
            ("RGB", "invert red, green and blue"),
            ("Luminance", "invert the luminance only"),
        ),
    ),
    # --- e76s03: the sequencer, the transport row and the audio analyser ---------------
    "sequencer.play": HelpEntry(
        "Play / Stop",
        "Start or stop this sequencer. The playhead column advances by one step per beat.",
    ),
    "sequencer.nudge_back": HelpEntry("<", "Move the playhead one step back."),
    "sequencer.nudge_forward": HelpEntry(">", "Move the playhead one step forward."),
    "sequencer.resync": HelpEntry("R", "Restart the playhead from the first step."),
    "sequencer.delete": HelpEntry(
        "X",
        "Delete this sequencer. It asks for confirmation; the other one is untouched.",
    ),
    "sequencer.beat_source": HelpEntry(
        "Beat source",
        "How this sequencer gets its tempo. Each box is one source; its LED blinks on the beat.",
        (
            ("bpm_analysis", "the BPM the analyser detects"),
            ("band1_beat", "the onset of Band 1"),
            ("midi_sync", "MIDI clock from the controller"),
            ("ableton_link", "the shared Ableton Link tempo"),
            ("manual_bpm", "the number you type, or TAP"),
        ),
    ),
    "sequencer.manual_bpm": HelpEntry("Manual BPM", "Tempo for the Manual source, 30 to 300."),
    "sequencer.tap": HelpEntry("TAP", "Tap a few times in time to set the manual tempo."),
    "sequencer.grid": HelpEntry(
        "Pattern",
        "One column per step, one row per source. A lit cell fires that source on that step.",
    ),
    "sequencer.rows": HelpEntry(
        "Rows", "How many source rows the pattern holds. Fixed for the life of this sequencer."
    ),
    "sequencer.columns": HelpEntry(
        "Columns", "How many steps per bar. Fixed for the life of this sequencer."
    ),
    "sequencer.size": HelpEntry(
        "Size", "How large the cells are drawn. It is a display choice, not a pattern change."
    ),
    "audio.device": HelpEntry("Input", "The audio input the analyser listens to."),
    "audio.spectrum": HelpEntry(
        "Level analysis",
        "Read the input for the spectrum and the VU meters, and feed the Band rows.",
    ),
    "audio.bpm": HelpEntry(
        "BPM analysis",
        "Detect the tempo from the input. The BPM readouts and the BPM Det beat source use it.",
    ),
    "audio.lowpass": HelpEntry(
        "Low-pass", "Smooth the analysed bands before the beat detector sees them."
    ),
    # --- e76s04: the Vimix sources window ---------------------------------------------
    "sources.browse_prev": HelpEntry("<", "Select the previous source in the grid."),
    "sources.browse_next": HelpEntry(">", "Select the next source in the grid."),
    "sources.set_current": HelpEntry("Set", "Make the selected source the current one in vimix."),
    "ui.hover_help": HelpEntry(
        "Show hover help",
        "Explain a control when the pointer rests on it. A VJ moves the mouse over "
        "the controls while performing, so the cards can be switched off.",
    ),
    "help.donate": HelpEntry(
        "Buy me a coffee",
        "Open the author's donation page in the browser. VJmix is free and GPL-3.0; "
        "a coffee is a thank-you, never a requirement.",
    ),
    "sources.refresh_all": HelpEntry(
        "Refresh all",
        "Ask viOSC for every readable property of every source, once. The table "
        "is not swept automatically: this is the explicit refresh. Changed cells "
        "flash bright for a moment.",
    ),
    "sources.data": HelpEntry(
        "Sources data",
        "Open the raw viOSC state table: every source and attribute exactly as vimix reports it.",
    ),
    "sources.tile_name": HelpEntry(
        "Source name",
        "The full name of this source; the tile shows a shortened form.",
    ),
    "sources.tile": HelpEntry(
        "Source",
        "Click a tile to select it, right-click for its menu (mapper, alpha, blending).",
    ),
    "sources.alpha": HelpEntry(
        "Alpha", "Opacity of this source in vimix: 0 is invisible, 1 is opaque."
    ),
    "sources.stop": HelpEntry(
        "STOP",
        "Send alpha -1: the source leaves the mixing circle and its media stops.",
    ),
    # --- e76s05: MIDI, the I/O monitor and pairing ------------------------------------
    "midi.enable": HelpEntry(
        "Enable MIDI", "Open the controller input ports and start the MIDI engine."
    ),
    "midi.add_controller": HelpEntry(
        "Add", "Put the selected input port under VJmix's control, with its profile."
    ),
    "midi.refresh": HelpEntry("Refresh", "Re-scan the available MIDI input ports."),
    "midi.mode_name": HelpEntry(
        "Mode name",
        "A named layer: the same message can mean a different binding in each mode.",
    ),
    "midi.mode_add": HelpEntry("Add mode", "Create a mode with the name on the left."),
    "midi.learn": HelpEntry(
        "Learn mapping",
        "Arm learn: click a red M on the control, then move the knob, key or pad to bind it.",
    ),
    "midi.bindings": HelpEntry(
        "Bindings", "Every binding of the selected controller; a row shows its last state."
    ),
    "midi.global_actions": HelpEntry(
        "Map global actions",
        "Window and project actions you can bind, each with its own red M marker.",
    ),
    "io.outcome": HelpEntry(
        "Outcome",
        "Narrow the stream to what the app made of each message: sent, received, "
        "matched, no match, no binding, learn, muted or ignored.",
    ),
    "logs.level": HelpEntry(
        "Level",
        "Show everything, or only warnings and errors. Errors are failures, "
        "warnings are things the app worked around.",
    ),
    "logs.pause": HelpEntry(
        "Pause",
        "Freeze this view; lines keep collecting and appear when you resume.",
    ),
    "logs.clear": HelpEntry("Clear", "Empty the log history."),
    "logs.copy": HelpEntry("Copy", "Put the visible lines on the clipboard."),
    "io.pause": HelpEntry("Pause", "Freeze the stream view; traffic keeps being recorded."),
    "io.peer": HelpEntry("Peer", "Show only the traffic of one MIDI port or OSC endpoint."),
    "io.direction": HelpEntry("Direction", "Filter in, out or both directions of the stream."),
    "io.transport": HelpEntry(
        "Transport", "Filter MIDI, OSC or HTTP (the viOSC data plane), or all of them."
    ),
    "io.control": HelpEntry(
        "Control", "Jump to one control: its traffic and the bindings it reaches."
    ),
    "io.mapping": HelpEntry(
        "Mapping", "The binding a control reaches; Assign binds the two from here."
    ),
    "pairing.code": HelpEntry(
        "Pairing code",
        "The six characters viOSC shows. Pairing points both OSC endpoints at each other.",
    ),
    # --- e76s06: the Text window ------------------------------------------------------
    "text.source": HelpEntry("Source", "The vimix Text source that receives the document."),
    "text.clear_source": HelpEntry(
        "Clear (source)",
        "Send an empty string: the text disappears in vimix. The local document is untouched.",
    ),
    "text.refresh": HelpEntry("Refresh", "Re-scan the vimix Text sources."),
    "text.send": HelpEntry(
        "Send to source", "Send the whole document, markup included, to the selected source."
    ),
    "text.reveal": HelpEntry(
        "Reveal",
        "Reveal the document step by step. The same mode again advances; another one restarts.",
        (
            ("word", "one more word"),
            ("word_plus", "one more word, keeping the cursor"),
            ("line", "one more line"),
            ("line_plus", "one more line, keeping the cursor"),
        ),
    ),
    "text.load": HelpEntry("Load from file", "Replace the document with a file from disk."),
    "text.save": HelpEntry("Save to file", "Write the document to a file on disk."),
    "text.clear_document": HelpEntry(
        "Clear (document)", "Empty the local document. Nothing is sent."
    ),
    "text.wrap_clipboard": HelpEntry(
        "Wrap clipboard",
        "The clipboard fallback wraps pasted text in a tag. Turn it off when you paste markup.",
    ),
    "text.template": HelpEntry(
        "Markup tag",
        "Insert this Pango tag around the selection (or wrap the clipboard fallback).",
    ),
    "text.size_keyword": HelpEntry("Size keyword", "The Pango size the Size button inserts."),
    "text.foreground": HelpEntry(
        "Foreground", "The colour the Foreground button inserts as a span."
    ),
    "text.background": HelpEntry(
        "Background", "The colour the Background button inserts as a span."
    ),
    "text.escape": HelpEntry(
        "Escape text", "Turn &, < and > into entities so they render as characters."
    ),
    "text.unescape": HelpEntry("Unescape text", "Turn the entities back into characters."),
    "text.validate": HelpEntry(
        "Validate", "Check the markup; the status line under the editor says what is wrong."
    ),
    "text.editor": HelpEntry(
        "Document",
        "The Pango markup sent to the source. It travels as the OSC contents attribute.",
    ),
    # --- e76s07: the Shader window ----------------------------------------------------
    "shader.kind": HelpEntry(
        "Kind",
        "What the target is. It picks the validation profile and the deploy shape.",
    ),
    "shader.family": HelpEntry(
        "Family", "Narrow the library to one family; 'any family' turns the filter off."
    ),
    "shader.template": HelpEntry("Shader", "The library asset loaded in the editor."),
    "shader.refresh_targets": HelpEntry(
        "Refresh", "Re-scan the vimix sources and clones a shader can be deployed to."
    ),
    "shader.validate": HelpEntry(
        "Validate",
        "Check the document against the kind's profile; the line below shows the verdict.",
    ),
    "shader.load": HelpEntry("Load from file", "Load a GLSL asset from disk into the editor."),
    "shader.save": HelpEntry("Save to file", "Write the document to a file on disk."),
    "shader.target": HelpEntry("Target", "The vimix source or clone that receives the deploy."),
    "shader.send": HelpEntry(
        "Send to target",
        "Flush the document to its file and deploy the PATH. No GLSL text travels over OSC.",
    ),
    "shader.rescan": HelpEntry(
        "Re-scan", "Re-read the uniform names from the document; the panel rebuilds."
    ),
    "shader.bypass": HelpEntry(
        "Bypass", "Send 0 to every uniform without losing the values, and back again."
    ),
    "shader.editor": HelpEntry(
        "Document", "The GLSL asset. Validate before Send: a broken body fails on the target."
    ),
    # --- e76s08: settings, Leap, cue lists, the Mapper window, sessions ---------------
    "settings.restore_project": HelpEntry(
        "Restore last project", "Re-open the last project at startup."
    ),
    "settings.theme_preset": HelpEntry(
        "Theme",
        "A saved palette set. Custom keeps the colours below.",
        (
            ("Dark", "the dark default"),
            ("Light", "the light variant"),
            ("Custom", "the colours below, unchanged by a preset"),
        ),
    ),
    "settings.client_ip": HelpEntry("Client IP", "Where VJmix sends OSC: viOSC's address."),
    "settings.client_port": HelpEntry("Client port", "viOSC's listening port."),
    "settings.client_connect": HelpEntry(
        "Connect Client", "Open the OSC client toward viOSC with the address on the left."
    ),
    "settings.listen_ip": HelpEntry("Listen IP", "Where VJmix receives viOSC's state feed."),
    "settings.listen_port": HelpEntry("Listen port", "The port viOSC sends its state to."),
    "settings.server": HelpEntry(
        "Start Server", "Start or stop the listening server for viOSC's state feed."
    ),
    "settings.pair": HelpEntry(
        "Pair with viOSC", "Ask viOSC for a pairing code and point both endpoints at each other."
    ),
    "settings.viosc_load": HelpEntry(
        "Load", "Read viOSC's remote configuration into the fields below."
    ),
    "settings.viosc_save": HelpEntry(
        "Save", "Write the fields below into viOSC's remote configuration."
    ),
    "settings.viosc_restart": HelpEntry("Restart viOSC", "Restart the viOSC daemon."),
    "leap.enable": HelpEntry("Enable Leap Motion", "Feed hand tracking into the Mapper controls."),
    "leap.restart": HelpEntry(
        "Restart engine", "Rebuild the device connection; the app need not restart."
    ),
    "leap.viz": HelpEntry(
        "Device view", "Show the device view and both hands; it is a diagnostic."
    ),
    "cue.kind": HelpEntry(
        "Kind",
        "What this row does when the cue list runs.",
        (
            ("property", "write a Vimix property"),
            ("wait", "pause for N milliseconds"),
            ("mapper", "trigger a Mapper row"),
            ("burst", "fire a short burst of messages"),
        ),
    ),
    "cue.property": HelpEntry("Property", "The Vimix property this row writes."),
    "cue.rate_burst": HelpEntry(
        "Rate burst", "A rate property fired as a burst of several messages."
    ),
    "cue.wait": HelpEntry(
        "Wait ms", "How long this row waits before the next one, in milliseconds."
    ),
    "cue.mapper": HelpEntry("Mapper", "The button or cue-list mapping this row triggers."),
    "cue.gap": HelpEntry("Level gap (ms)", "Pause between rows of this cue list."),
    "cue.run": HelpEntry("Run", "Run the cue list from the first row."),
    "cue.stop": HelpEntry("Stop", "Stop the cue list."),
    "cue.add_row": HelpEntry("Add row", "Append a row to this cue list."),
    "mapper.filter_control": HelpEntry("Control", "Show the mappings whose Origin is a control."),
    "mapper.filter_state": HelpEntry(
        "State", "Show the mappings that read a live Vimix attribute."
    ),
    "mapper.filter_global": HelpEntry(
        "Clock+Constant", "Show the mappings driven by the transport or by a fixed value."
    ),
    "mapper.new": HelpEntry(
        "New mapping", "Create a mapping of any Type; it asks which Source when needed."
    ),
    "sessions.roots": HelpEntry("Media root", "The machine A folder the sessions manager browses."),
    "sessions.new": HelpEntry("New", "Start a new, empty set of sources."),
    "sessions.save": HelpEntry("Save", "Write the current set of sources to disk."),
    "sessions.send": HelpEntry(
        "Send to Vimix", "Load the selected session into vimix, replacing what is on screen."
    ),
}


# e76s02: one sentence per mappable property. The OSC wiki (section 3.1/3.2) is the
# authority for the semantics; the range/neutral are read from the catalog, never
# repeated here. The gate proves the coverage, so a property can never render with
# its numbers alone.
PROPERTY_NOTES: dict[str, str] = {
    "alpha": "Opacity; below 0 the source leaves the mixing circle.",
    "transparency": "Opacity's logical opposite: higher is more transparent.",
    "depth": "Stacking depth: below 2 sits behind, above 10 in front.",
    "angle": "Absolute rotation, in radians.",
    "brightness": "Black level of the source.",
    "contrast": "Contrast around the mid point.",
    "saturation": "Colour intensity; -1 gives grayscale.",
    "hue": "Colour shift around the wheel.",
    "gamma": "Mid-tone curve; vimix applies 10^x internally.",
    "threshold": "Cut level used by the threshold look.",
    "posterize": "Number of posterize levels; 0 disables it.",
    "seek": "Playhead position, as a fraction of the duration.",
    "speed": "Media playback rate; negative plays backwards.",
    "position": "Offset of the source, per axis.",
    "size": "Scale of the source; neutral 1,1 leaves it unchanged.",
    "color": "RGB gamma per channel; needs Correction on.",
    "corner": "Four corner points, one quadrant each.",
    "play": "Start playback; no argument needed.",
    "pause": "Stop playback.",
    "lock": "A locked source ignores OSC.",
    "correction": "Master switch of the colour block.",
    "replay": "Restart the media from the beginning.",
    "reset": "Position 0,0, size 1,1 and angle 0.",
    "reload": "Reload the media file from disk.",
    "flag": "A media flag id; -1 advances to the next flag.",
    "blending": "Compositing mode, one of the eight modes.",
    "invert": "Which channels the invert inverts.",
}


def entry(key: str) -> HelpEntry:
    """The card for `key`; KeyError is the loud, test-visible failure mode."""
    return HELP[key]


def option_lines(key: str) -> tuple[tuple[str, str], ...]:
    """The option table of one card (empty for a behaviour card)."""
    return HELP[key].options


def _number(value: float) -> str:
    """A compact number for prose: -1.0 -> '-1', 0.8 -> '0.8'."""
    return f"{value:g}"


def type_card(origins: Sequence[str]) -> HelpEntry:
    """The Type card restricted to the origins ONE editor entry point offers.

    The general '+', a line's '+' and the Clock/Constant '+' each build the same
    combo from a different tuple; the card must not promise an option the combo
    below it does not list.
    """
    return _restricted(HELP["mapper.type"], origins)


def destination_card(destinations: Sequence[str]) -> HelpEntry:
    """The Destination card restricted to ``MAPPING_DIRECTIONS[origin]``."""
    return _restricted(HELP["mapper.destination"], destinations)


def property_card(prop: str) -> HelpEntry:
    """The LIVE Property card: what the CURRENT property is and its catalog range."""
    return HelpEntry(
        "Property",
        f"{property_line(prop)} The value this Mapping writes or reads.",
    )


def component_card(prop: str) -> HelpEntry:
    """The Component card: the axis/channel of a vector property, with its range."""
    spec = catalog.PROPERTY_CATALOG.get(prop)
    if spec is None or len(spec["components"]) <= 1:
        return HelpEntry("Component", "Only a multi-value property asks for a component.")
    options = tuple(
        (str(component["key"]), _component_label(component)) for component in spec["components"]
    )
    return HelpEntry("Component", "Which value of the property this Mapping drives.", options)


def _restricted(card: HelpEntry, values: Sequence[str]) -> HelpEntry:
    """One enumerated card cut down to `values`, order preserved."""
    meanings = dict(card.options)
    options = tuple((value, meanings.get(value, "")) for value in values)
    return HelpEntry(card.title, card.body, options)


def _component_label(component: dict[str, Any]) -> str:
    return (
        f"{component['label']} "
        f"{_number(float(component['min']))}..{_number(float(component['max']))}"
    )


def property_line(prop: str, registry: dict[str, object] | None = None) -> str:
    """The LIVE line of a Property card: catalogue label, span and note.

    The numbers come from ``catalog.PROPERTY_CATALOG`` — the same table the OSC
    layer sends with — so a range change on the wiki side reaches the card
    without touching prose. A shader uniform is not in the catalogue (it is a
    POSITION into the deployed shader's parameter list) and gets its own line.
    ``registry`` is accepted for the caller's convenience and unused: the uniform
    text is the same for every slot.
    """
    del registry  # the uniform line does not depend on the live registry
    if str(prop) == catalog.SET_CURRENT_PROPERTY:
        # e83: a Mapper-only action, not a vimix attribute.
        return "Set current - the button makes this line's source the current one."
    spec = catalog.PROPERTY_CATALOG.get(prop)
    if spec is None:
        slot = catalog.parse_uniform_slot(prop)
        position = f" {slot}" if slot is not None else ""
        return f"Shader uniform{position} - the deployed shader's value at this slot."
    label = str(spec["label"])
    components = spec["components"]
    if len(components) == 1:
        component = components[0]
        span = (
            f"Range {_number(component['min'])}..{_number(component['max'])}, "
            f"neutral {_number(component['neutral'])}."
        )
    else:
        names = ", ".join(str(c["label"]) for c in components)
        span = f"{len(components)} values: {names}."
    note = PROPERTY_NOTES.get(prop, "")
    return f"{label} - {note} {span}" if note else f"{label} - {span}"
