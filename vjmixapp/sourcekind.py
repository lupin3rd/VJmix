"""What a vimix source IS, from the OSC `type` code (e68s01).

Source of truth: the vimix wiki, "Open Sound Control API", the `type` section <https://github.com/
brunoherbelin/vimix/wiki/Open-Sound-Control-API> (cross-checked with `src/ControlManager.cpp`,
`sourceType()`), read 2026-10-13. vimix answers `/vimix/<t>/get s type` with an OSC int32 code;
the tens digit is the family. This module is the ONE place that turns a code into a name and into
the capabilities a consumer needs, so no caller pattern-matches integers.

Pure data + pure helpers — no dpg, no state, no I/O (HIGH-1). `type` is READ-ONLY information,
not a control, so it is deliberately NOT in `catalog.py`: nothing here is Mapper-mappable.
"""

from dataclasses import dataclass
from typing import Any

from vjmixapp.constants import SHADER_KIND_EFFECT, SHADER_KIND_GENERATOR

# The wiki's code table. Do not renumber: the codes are part of vimix's public OSC API.
SOURCE_TYPE_UNKNOWN = 0
WIKI_SOURCE_TYPES: dict[int, str] = {
    10: "Video file",
    11: "Videos",
    12: "Image file",
    20: "GStreamer",
    21: "Device",
    22: "Screen capture",
    23: "Network stream",
    24: "SRT receiver",
    25: "Image sequence",
    26: "Pattern",
    27: "Text",
    30: "Session file",
    31: "Bundle",
    40: "Loopback",
    41: "Clone",
    42: "Draft",
    50: "Shader",
    60: "Canvas",
}

# The family of a code is its tens digit (the wiki's own rule).
SOURCE_FAMILIES: dict[int, str] = {
    1: "media",
    2: "stream",
    3: "session",
    4: "render-clone",
    5: "shader",
    6: "canvas",
}

# Capabilities: the three decisions a consumer makes from a kind.
#   media  — a FILE backs it and the extraction pipeline can decode it (thumbnailable)
#   video  — a moving picture a transport can play (previewable)
#   text   — the Text instrument can target it (`contents`)
#   shader — a shader uniform can be driven on it (`/uniform`, safe on a vimix that reports type)
_MEDIA_CODES = frozenset({10, 11, 12})
_VIDEO_CODES = frozenset({10, 11})
_TEXT_CODES = frozenset({27})
_SHADER_CODES = frozenset({41, 50})


@dataclass(frozen=True)
class SourceKind:
    """One source's kind: the code, its family, its label and what may be done with it."""

    code: int
    family: str
    label: str
    media: bool
    video: bool
    text: bool
    shader: bool


def source_kind(code: Any) -> SourceKind | None:
    """The kind behind a `type` code, or None when the value is absent/unknown.

    Total and strict on purpose: a `bool` is an `int` in Python and must not resolve to 1, and a
    code the wiki does not list (or a string, a float, None) returns None rather than inventing a
    label or indexing the table.
    """
    if isinstance(code, bool) or not isinstance(code, int):
        return None
    if code not in WIKI_SOURCE_TYPES:
        return None
    return SourceKind(
        code=code,
        family=SOURCE_FAMILIES.get(code // 10, "unknown"),
        label=WIKI_SOURCE_TYPES[code],
        media=code in _MEDIA_CODES,
        video=code in _VIDEO_CODES,
        text=code in _TEXT_CODES,
        shader=code in _SHADER_CODES,
    )


def source_kind_of(props: dict[str, Any] | None) -> SourceKind | None:
    """The kind of a vimix state entry (`props["type"]`), or None when unknown."""
    if not props:
        return None
    return source_kind(props.get("type"))


def is_thumbnailable(props: dict[str, Any] | None) -> bool:
    """Whether a thumbnail may be requested for this source.

    A known kind answers from its capability (file media only). An unknown kind falls back to the
    pre-e68 behaviour (`uri` present), so an older viOSC/vimix behaves exactly as today.
    """
    kind = source_kind_of(props)
    if not props:
        return False
    if kind is None:
        return bool(props.get("uri"))
    return kind.media and bool(props.get("uri"))


def thumbnail_possible(props: dict[str, Any] | None) -> bool:
    """Whether a thumbnail can EVER arrive for this source (e69s01).

    `is_thumbnailable` AND the probe has not already found no video stream
    (`media_kind == "other"`) — the exact conjunction the request loop applies, lifted here so
    the loop and the surfaces that label a missing thumbnail can never disagree. False means the
    UI should NAME the source instead of waiting.
    """
    if not is_thumbnailable(props):
        return False
    return (props or {}).get("media_kind") != "other"


def is_previewable(props: dict[str, Any] | None) -> bool | None:
    """Whether a transport can play this source.

    True/False when the type answers; None when it does not, so the caller applies its own
    `media_kind` fallback and an older stack keeps today's behaviour.
    """
    kind = source_kind_of(props)
    if kind is None:
        return None
    return kind.video


def supports_uniform(props: dict[str, Any] | None) -> bool | None:
    """Whether `/uniform` can drive this source.

    True/False when the type answers (a Clone's custom filter or a ShaderSource); None when it
    does not, so the caller keeps its own guard. `/uniform` on a typed source that is NOT
    shader-capable is a no-op in vimix, never a crash, but it is refused rather than sent.
    """
    kind = source_kind_of(props)
    if kind is None:
        return None
    return kind.shader


def type_of_source(sources: dict[str, Any], target_id: str) -> Any:
    """The `type` code of the source addressed by NAME `target_id`, or None when unknown.

    Pure: the caller passes the live state table. `target_id` is the source name (the frozen
    addressing), so this is a name lookup, not an index one.
    """
    for props in (sources or {}).values():
        if str(props.get("name")) == str(target_id):
            return props.get("type")
    return None


def shader_role(code: Any) -> str | None:
    """The DEPLOY role a source's type implies, or None when the type does not answer.

    A ShaderSource (50) deploys like a GENERATOR (`/code s <path>`); a Clone (41) like an EFFECT
    (`/filter ss custom <path>`, the Custom-shader filter that loads the file). A DraftSource (42)
    is a temporary draft of a session edit, not a normal target, so it has NO role. None here
    means "the type cannot decide", and the caller keeps the operator's declaration.
    """
    kind = source_kind(code)
    if kind is None:
        return None
    if kind.code == 50:
        return SHADER_KIND_GENERATOR
    if kind.code == 41:
        return SHADER_KIND_EFFECT
    return None
