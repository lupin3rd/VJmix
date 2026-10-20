"""GLSL shader assets for VJmix (e61s02).

The single place that knows what a shader asset IS: the uniforms vimix will
expose for it, whether it is valid for its kind, and where the per-user library
lives. DPG-FREE, state-free and I/O-free except for the explicit load/save, so
every helper is unit-testable headless and safe on any thread (HIGH-1).

Why the regexes look odd: VJmix must discover EXACTLY the uniforms vimix
discovers (`ImageFilter::setProgram`, `Filter/ImageFilter.cpp:514-518`), because
vimix only accepts a `/uniform` name its own parse created. Mirroring it means a
single-character name (`[a-zA-Z_][\\w]+` needs two characters) or a declaration
without its closing semicolon is invisible to BOTH sides — a superset would
register uniforms whose every send vimix answers with "unknown uniform".

vimix's own regexes, quoted verbatim (Filter/ImageFilter.cpp:514-518):

    #define REGEX_UNIFORM_DECLARATION "uniform\\\\s+float\\\\s+"
    #define REGEX_VARIABLE_NAME       "[a-zA-Z_][\\\\w]+"
    #define REGEX_UNIFORM_VALUE       "(\\\\s*=\\\\s*[[:digit:]]+(\\\\.[[:digit:]]*)?)?\\\\s*\\\\;"
    #define REGEX_RANGE_COMMENT       "\\/\\/\\s*range\\s*\\[*G\\s+*G\\s*\\]"
    (*G = "([+-]?[[:digit:]]+(\\.[[:digit:]]*)?)", repeated twice: min and max)

The compiled forms below add named groups to those same shapes and write `\\w` and
the digit class in ASCII, because Python's `\\w` is Unicode-aware while vimix's
ECMAScript `\\w` is not (a name like `café` must be invisible on both sides).

The range comment is an in-code, undocumented feature (none of vimix's shipped
shaders uses it) and the rig spike could not observe it over OSC: treat the parsed
range as a HINT, with the user's manual override winning (decision D2).

`ImageFilter.cpp:40-66` defines the contract the code must satisfy: vimix pastes
the asset between a fixed fragment header (`#version 330 core`, `iTransform`,
`iResolution`, `iChannel0`, `iChannel1`, `iTime`, `iTimeDelta`, `iFrame`, `iDate`,
`iMouse`) and a footer that calls `mainImage(FragColor, ...)`, so the asset is a
ShaderToy-shaped BODY and never a complete shader.
"""

import os
import re
from dataclasses import dataclass
from typing import Any

from vjmixapp import catalog, sourcekind
from vjmixapp.config import user_config_dir
from vjmixapp.constants import (
    MAX_SHADER_BYTES,
    SHADER_ASSET_EXTENSION,
    SHADER_DEFAULT_ASSET_STEM,
    SHADER_KIND_EFFECT,
    SHADER_KIND_GENERATOR,
    SHADER_KINDS,
    SHADER_LIBRARY_DIRNAME,
    SHADER_MAPPABLE_UNIFORM_SLOTS,
    SHADER_MAX_LIBRARY_ENTRIES,
    SHADER_MAX_TARGETS,
    SHADER_MAX_UNIFORMS_PER_TARGET,
    SHADER_UNIFORM_KEYS,
)

# The kinds live in constants (state.py needs a default without importing this
# module); these aliases are the module's public spelling of them.
KIND_EFFECT = SHADER_KIND_EFFECT
KIND_GENERATOR = SHADER_KIND_GENERATOR
KINDS: tuple[str, ...] = SHADER_KINDS

# --- uniform discovery (mirrors vimix 1:1, see the module docstring) ---
UNIFORM_DECLARATION = r"uniform\s+float\s+"
VARIABLE_NAME = r"[a-zA-Z_][A-Za-z0-9_]+"
UNIFORM_VALUE = r"[0-9]+(?:\.[0-9]*)?"
RANGE_COMMENT = r"\/\/\s*range\s*\[\s*([+-]?[0-9]+(?:\.[0-9]*)?)\s+([+-]?[0-9]+(?:\.[0-9]*)?)\s*\]"
_UNIFORM_RE = re.compile(
    UNIFORM_DECLARATION
    + f"(?P<name>{VARIABLE_NAME})"
    + rf"(?:\s*=\s*(?P<value>{UNIFORM_VALUE}))?\s*;"
)
_RANGE_RE = re.compile(RANGE_COMMENT)
# `// …` and `/* … */`, replaced by spaces of the same length so every position
# reported to the user still points at the original character.
_COMMENT_RE = re.compile(r"//[^\n]*|/\*.*?\*/", re.DOTALL)

# --- validation ---
MAIN_IMAGE = "mainImage"
# The generator kind draws on a 64x64 EMPTY buffer, so sampling it renders
# black: the warning is the only guard available without a GL preview.
INPUT_CHANNEL = "iChannel0"
# The OSC name of vimix's custom-shader filter: SetFilter matches the FIRST WORD of
# the filter label lowercased, and the label is "Custom shader"
# (FrameBufferFilter::Types). The filename rides as its METHOD argument.
FILTER_CUSTOM = "custom"
# vimix's pass-through filter ("None" in the filter table): the bypass of an
# effect, which leaves the asset file untouched so un-bypassing can re-deploy it.
FILTER_PASSTHROUGH = "none"
# A target name is not necessarily a filename: keep it recognizable and safe.
_UNSAFE_STEM_RE = re.compile(r"[^A-Za-z0-9_.-]+")
# `// range` is a hint, so an unparsable range falls back to a wide band.
UNBOUNDED_RANGE: tuple[float, float] = (-10.0, 10.0)

# --- the kind declaration (e62) ---
# The kind an asset DECLARES in its header. A convention of this project, not of
# vimix: vimix pastes the asset between its own header and footer, so the comment
# survives the deploy and stays visible in vimix's Shader Editor.
KIND_DECLARATION = re.compile(r"//\s*kind\s*:\s*([A-Za-z]+)", re.IGNORECASE)
# The remediation a file missing from the picker needs (it names the exact line).
KIND_DECLARATION_HINT = "add a '// kind: effect' or '// kind: generator' line"
# The pack's SECOND axis (e65s01): `// family: <token>` says what a file IS, where
# `// kind:` says how it deploys. The declaration is the WHOLE line — a token with a
# tail is not a token, because a half-read family would be displayed as if the file
# had declared it. It is DECORATIVE: nothing here can hide a file from the picker.
FAMILY_DECLARATION = re.compile(
    r"//[ \t]*family[ \t]*:[ \t]*([A-Za-z_]+)[ \t\r]*$", re.IGNORECASE | re.MULTILINE
)

# e70s03: the DECLARED uniform map — `// uniformN: <glsl_name>`, the exact shape of
# the other header directives (a whole line, a token, nothing after it). It PINS a
# position to a name, so reordering the declarations cannot move a binding.
UNIFORM_SLOT_DECLARATION = re.compile(
    r"//[ \t]*uniform([1-9][0-9]*)[ \t]*:[ \t]*([A-Za-z_][A-Za-z0-9_]*)[ \t\r]*$",
    re.IGNORECASE | re.MULTILINE,
)


class ShaderAssetError(Exception):
    """A shader asset could not be read or written (message says why and how to fix it)."""


@dataclass(frozen=True)
class ShaderUniform:
    """One `uniform float` of an asset, as vimix will expose it."""

    name: str
    default: float
    range_min: float | None
    range_max: float | None


@dataclass(frozen=True)
class ShaderIssue:
    """Why an asset is not deployable, at a position a human can act on."""

    line: int
    column: int
    message: str


def _parse_range_comment(line_tail: str) -> tuple[float | None, float | None]:
    """The `// range [min max]` on the declaration line, else (None, None)."""
    found = _RANGE_RE.search(line_tail)
    if found is None:
        return None, None
    return float(found.group(1)), float(found.group(2))


def parse_uniforms(code: str) -> list[ShaderUniform]:
    """Every `uniform float` of an asset, in declaration order (vimix's own set).

    A malformed declaration is skipped, never raised: the asset is user text and
    the result drives the registry UI, so an exception here would take the window
    down with it.
    """
    uniforms: list[ShaderUniform] = []
    remaining = str(code or "")
    while True:
        found = _UNIFORM_RE.search(remaining)
        if found is None:
            return uniforms
        declared = found.group("value")
        range_min, range_max = _parse_range_comment(remaining[found.end() :].partition("\n")[0])
        uniforms.append(
            ShaderUniform(
                name=found.group("name"),
                default=float(declared) if declared else 0.0,
                range_min=range_min,
                range_max=range_max,
            )
        )
        remaining = remaining[found.end() :]


def parse_uniform_slots(code: str) -> dict[int, str]:
    """The DECLARED slot -> GLSL name map of an asset (e70s03).

    A `// uniformN: <glsl_name>` header directive (the exact shape of `// kind:` /
    `// family:`) PINS a position to a name, so reordering the `uniform float`
    statements cannot move what a binding drives. The FIRST declaration of a slot
    wins — a duplicated line cannot flip the map under the operator. A slot the asset
    does not declare falls back to the declaration order at registry build time.
    """
    declared: dict[int, str] = {}
    for found in UNIFORM_SLOT_DECLARATION.finditer(str(code or "")):
        declared.setdefault(int(found.group(1)), found.group(2))
    return declared


def _mask_comments(code: str) -> str:
    """The code with every comment blanked out, keeping offsets (so issues point right).

    Comments are legal GLSL and must not count: a `}` inside a comment is not a
    brace, and a generator template that merely NAMES iChannel0 in a comment does
    not sample the empty buffer.
    """
    return _COMMENT_RE.sub(lambda found: re.sub(r"[^\n]", " ", found.group(0)), code)


def _issue_at(code: str, index: int, message: str) -> ShaderIssue:
    """A ShaderIssue for the character at `index` (1-based line/column)."""
    head = code[: max(0, index)]
    return ShaderIssue(line=head.count("\n") + 1, column=index - head.rfind("\n"), message=message)


def _unbalanced_issue(code: str, opening: str, closing: str, label: str) -> ShaderIssue | None:
    """The first position where `opening`/`closing` stop nesting, else None."""
    depth = 0
    for index, char in enumerate(code):
        if char == opening:
            depth += 1
        elif char == closing:
            depth -= 1
            if depth < 0:
                return _issue_at(code, index, f"unbalanced {label}: '{closing}' has no opener")
    if depth > 0:
        return _issue_at(code, len(code) - 1, f"unbalanced {label}: {depth} '{opening}' left open")
    return None


def _first_issue(code: str, kind: str) -> ShaderIssue | None:
    """The first problem of an asset, in the order a user meets it."""
    if kind not in KINDS:
        return ShaderIssue(1, 1, f"unknown shader kind {kind!r}: use one of {list(KINDS)}")
    if not _mask_comments(str(code or "")).strip():
        return ShaderIssue(1, 1, "the shader is empty: write a mainImage body or load a template")
    if len(code) > MAX_SHADER_BYTES:
        return ShaderIssue(
            1,
            1,
            f"the shader is too large ({len(code)} bytes > {MAX_SHADER_BYTES}): "
            "split it or delete the dead code",
        )
    return None


def _body_issue(masked: str, kind: str) -> ShaderIssue | None:
    """The issues that only apply once the asset is non-empty and in range."""
    if MAIN_IMAGE not in masked:
        message = f"missing {MAIN_IMAGE}(): vimix calls it as the fragment entry point"
        return ShaderIssue(1, 1, message)
    for opening, closing, label in (("{", "}", "brace"), ("(", ")", "parenthesis")):
        issue = _unbalanced_issue(masked, opening, closing, label)
        if issue is not None:
            return issue
    reserved = reserved_identifier_issue(masked)
    if reserved is not None:
        return reserved
    if kind == KIND_GENERATOR and INPUT_CHANNEL in masked:
        return _issue_at(
            masked,
            masked.index(INPUT_CHANNEL),
            f"a generator draws on an empty buffer, so sampling {INPUT_CHANNEL} renders black: "
            "use fragCoord and iTime instead, or declare the target as an effect",
        )
    return None


# --- the two laws of a REAL video effect (e73) --------------------------------
# Every `_over_source` asset before e73 sampled the cloned frame at the identity
# coordinate and then composited a generated layer over it, so the video was a plate and
# never the subject. These two functions are the mechanical definition of the difference;
# the pack's own ADD idiom is used as the falsification probe in the contract test.
#
# C1 the passthrough law: `amount` is the pack's WET/DRY MIX, so at 0 the asset returns
# the source untouched — which is what makes a VU-driven `amount` dissolve the video.
PASSTHROUGH_UNIFORM = "amount"
# C2 the transformation law: at least one sample reads the frame at a coordinate that is
# not the frame's own uv. The frame's uv is the identifier every asset binds from
# `fragCoord` and `iResolution`; that binding IS the identity C2 is measured from.
_UV_DECLARATION = re.compile(r"\bvec2\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?P<expr>[^;]*);")
_SOURCE_SAMPLE = re.compile(rf"texture\s*\(\s*{INPUT_CHANNEL}\s*,")
_IDENTITY_BINDING = re.compile(
    rf"\bvec[234]\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*"
    rf"texture\s*\(\s*{INPUT_CHANNEL}\s*,\s*(?P<coord>[A-Za-z_][A-Za-z0-9_]*)\s*\)"
)
_IDENTITY_SAMPLE_TEXT = re.compile(
    rf"^texture\s*\(\s*{INPUT_CHANNEL}\s*,\s*(?P<coord>[A-Za-z_][A-Za-z0-9_]*)\s*\)"
    r"(?:\.[rgba]{3,4})?$"
)
_MIX_CALL = re.compile(r"\bmix\s*\(")


def _arguments_from(masked: str, start: int) -> list[str]:
    """The top-level arguments of a call whose first argument starts at `start`.

    `start` sits just after the opening parenthesis, so depth begins at 1 and a nested
    call, a swizzle or an inline constructor stays inside ONE argument.
    """
    depth = 1
    arguments: list[str] = []
    current = ""
    for char in masked[start:]:
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                break
        elif char == "," and depth == 1:
            arguments.append(current)
            current = ""
            continue
        current += char
    arguments.append(current)
    return [argument.strip() for argument in arguments if argument.strip()]


def frame_uv_names(code: str) -> frozenset[str]:
    """The identifiers that ARE the frame's own coordinate (the identity of C2).

    Recognised from the binding every asset of the pack writes — a `vec2` initialised from
    BOTH `fragCoord` and `iResolution`. A local computed from it (a warped coordinate) is
    deliberately not one of these: that is the transform C2 asks for.
    """
    masked = _mask_comments(code)
    return frozenset(
        found.group("name")
        for found in _UV_DECLARATION.finditer(masked)
        if "fragCoord" in found.group("expr") and "iResolution" in found.group("expr")
    )


def source_sample_coordinates(code: str) -> tuple[str, ...]:
    """The coordinate of every `texture(iChannel0, …)`, comments masked and whitespace folded."""
    masked = _mask_comments(code)
    return tuple(
        " ".join(_arguments_from(masked, found.end())[0].split())
        for found in _SOURCE_SAMPLE.finditer(masked)
        if _arguments_from(masked, found.end())
    )


def transform_law_issue(code: str) -> str | None:
    """Why the body is not a TREATMENT of the cloned frame (C2), else None.

    A body passes when at least one `iChannel0` sample reads the frame at a coordinate
    other than the frame's own uv. The pack's pre-e73 idiom fails by construction, which is
    the point: `src + col * amount` is a composite, however clever `col` is.
    """
    identity = frame_uv_names(code)
    coordinates = source_sample_coordinates(code)
    if not coordinates:
        return f"samples no {INPUT_CHANNEL}: a treatment must read the cloned frame"
    if all(coordinate in identity for coordinate in coordinates):
        return (
            "reads the frame only at its own uv: this is a composite, not a treatment "
            "(sample a transformed coordinate, or declare the asset as a generator)"
        )
    return None


def passthrough_law_issue(code: str) -> str | None:
    """Why the body does not return the source at `amount` 0 (C1), else None.

    The law is the wet/dry mix itself: a `mix(<source>, …, amount)` whose first argument is
    the identity sample, directly or through an identifier bound to it, and whose third
    argument is the `amount` uniform EXACTLY (the pack's range is [0 1], so no wrapper is
    needed; a wrapper would hide the law from every reader, human and machine alike).
    """
    masked = _mask_comments(code)
    identity = frame_uv_names(code)
    sources = set(identity) | {
        found.group("name")
        for found in _IDENTITY_BINDING.finditer(masked)
        if found.group("coord") in identity
    }

    def is_the_source(argument: str) -> bool:
        if argument in sources:
            return True
        found = _IDENTITY_SAMPLE_TEXT.match(argument)
        return found is not None and found.group("coord") in identity

    for call in _MIX_CALL.finditer(masked):
        arguments = _arguments_from(masked, call.end())
        if len(arguments) < 3:
            continue
        if is_the_source(arguments[0]) and arguments[2] == PASSTHROUGH_UNIFORM:
            return None
    return (
        f"no `mix(<the cloned frame>, <treated>, {PASSTHROUGH_UNIFORM})`: at "
        f"{PASSTHROUGH_UNIFORM} 0 the asset must return the source untouched, so that "
        "a VU-driven amount dissolves the video into the treatment"
    )


# --- the identifiers a GLSL 3.30 compiler refuses (BUG-2026-10-16T001500) ----------
# vimix wraps a body with `#version 330 core`, and §3.6 of that spec lists keywords
# "reserved for future use. Using them will result in an error". A driver may accept them
# anyway — the local EGL path compiles `float active = 0.5;` — which is why six assets of
# e72 shipped with an identifier vimix refuses on a conforming compiler. The list is static
# on purpose: the render harness CANNOT catch this class, so a compile is not the gate.
GLSL_RESERVED_WORDS: frozenset[str] = frozenset(
    {
        "common",
        "partition",
        "active",
        "asm",
        "class",
        "union",
        "enum",
        "typedef",
        "template",
        "this",
        "resource",
        "goto",
        "inline",
        "noinline",
        "public",
        "static",
        "extern",
        "external",
        "interface",
        "long",
        "short",
        "half",
        "fixed",
        "unsigned",
        "superp",
        "input",
        "output",
        "hvec2",
        "hvec3",
        "hvec4",
        "dvec2",
        "dvec3",
        "dvec4",
        "fvec2",
        "fvec3",
        "fvec4",
        "sampler3DRect",
        "filter",
        "sizeof",
        "cast",
        "namespace",
        "using",
        "sample",
    }
)
# The GLOBALS vimix's header declares (`Filter/ImageFilter.cpp`, `fragmentHeader`): a body
# that redeclares one shadows what it needs to draw, or fails to compile outright.
# `mainImage` is deliberately NOT here — it is the entry point the body is REQUIRED to
# define — and neither is `main`, which belongs to vimix's footer.
VIMIX_HEADER_NAMES: frozenset[str] = frozenset(
    {
        "FragColor",
        "vertexColor",
        "vertexUV",
        "iChannelResolution",
        "iTransform",
        "iResolution",
        "iChannel0",
        "iChannel1",
        "iTime",
        "iTimeDelta",
        "iFrame",
        "iDate",
        "iMouse",
    }
)
_DECLARED_NAME = re.compile(
    r"\b(?:float|int|uint|bool|void|vec[234]|ivec[234]|uvec[234]|bvec[234]|mat[234]"
    r"|mat[234]x[234]|sampler2D|sampler3D|samplerCube)\s+([A-Za-z_][A-Za-z0-9_]*)\b"
)


def declared_identifiers(code: str) -> tuple[str, ...]:
    """Every name a body DECLARES (a variable or a function), comments masked."""
    return tuple(_DECLARED_NAME.findall(_mask_comments(str(code or ""))))


def reserved_identifier_issue(code: str) -> ShaderIssue | None:
    """The first name this body declares that a GLSL 3.30 compiler refuses, else None.

    Two refusals: a keyword reserved for future use (a compile error on a conforming
    driver, silently accepted by a lenient one) and a name vimix's own header declares.
    Identifiers containing `__` are reserved by the spec as well.
    """
    masked = _mask_comments(str(code or ""))
    for name in declared_identifiers(code):
        if name in GLSL_RESERVED_WORDS:
            index = masked.find(name)
            return _issue_at(
                masked,
                index,
                f"'{name}' is a GLSL keyword RESERVED for future use: a conforming compiler "
                "rejects it as an identifier (rename it, e.g. 'alive' for 'active')",
            )
        if name in VIMIX_HEADER_NAMES:
            index = masked.find(name)
            return _issue_at(
                masked, index, f"'{name}' is already declared by vimix's shader header: rename it"
            )
        if "__" in name:
            index = masked.find(name)
            return _issue_at(masked, index, f"'{name}': names with '__' are reserved by GLSL")
    return None


def validate_shader(code: str, kind: str) -> ShaderIssue | None:
    """None when the asset is deployable for its kind, else the first issue.

    This is a PRE-FLIGHT courtesy, not a compiler: vimix compiles asynchronously
    and reports nothing over OSC, and the rig showed its editor's "Status: Ready"
    is not a compile indicator (specs/archive/spikes/SPIKE-shader-deployment.md).
    """
    return _first_issue(code, kind) or _body_issue(_mask_comments(str(code or "")), kind)


def shader_library_dir() -> str:
    """The per-user shader library (an APPLICATION asset, never project content)."""
    return os.path.join(user_config_dir(), SHADER_LIBRARY_DIRNAME)


def parse_family(code: str) -> str:
    """The family the asset DECLARES with `// family: <token>`, else "" (e65s01).

    The pack's second axis, and a DECORATIVE one: absence is the normal state (the
    28 assets of e63 declare none), an unknown token is returned as it is (the
    operator's own files may carry their own families), a malformed line declares
    nothing, and the first declaration wins. Nothing here decides whether a file is
    listed — only `parse_kind` does.
    """
    found = FAMILY_DECLARATION.search(str(code or ""))
    return found.group(1).lower() if found is not None else ""


def parse_kind(code: str) -> str | None:
    """The kind the asset DECLARES with `// kind: effect|generator`, else None (e62).

    Never inferred from the body: an effect that ignores `iChannel0` is a legal
    effect (and a generator that samples it renders black), so the body cannot
    decide which profile applies — the operator declares it, one line, once.
    """
    found = KIND_DECLARATION.search(str(code or ""))
    if found is None:
        return None
    declared = found.group(1).lower()
    return declared if declared in KINDS else None


@dataclass(frozen=True)
class LibraryEntry:
    """One usable file of the shader library — what the picker offers (e62).

    `family` is the decorative second axis (e65s01): it is carried so the window can
    say what a file IS, and it is empty when the file declares none.
    """

    name: str
    path: str
    kind: str
    family: str = ""


def entry_kind_and_family(entry: LibraryEntry) -> str:
    """The one-line summary of an entry: `generator · particles` (e65s01).

    The pick states this, so the operator sees what a file IS beside how it deploys.
    A file that declares no family reads exactly as it always did.
    """
    return f"{entry.kind} · {entry.family}" if entry.family else entry.kind


@dataclass(frozen=True)
class SkippedLibraryFile:
    """A library file the picker cannot offer, and why (reported, never hidden)."""

    filename: str
    reason: str


@dataclass(frozen=True)
class LibraryScan:
    """The library as the window sees it: the usable entries and the skips (e62)."""

    entries: tuple[LibraryEntry, ...]
    skipped: tuple[SkippedLibraryFile, ...]


NO_KIND_REASON = f"not listed: {KIND_DECLARATION_HINT}"


def scan_library(directory: str | None = None) -> LibraryScan:
    """The shader library: the entries a target can use, and the files skipped (e62).

    The FOLDER is the template list (user decision 2026-10-10): copying a `.glsl`
    file in adds a picker entry, deleting it removes one, and the application
    carries no shader of its own. A file is usable when it declares its kind;
    every other `.glsl` file comes back as a skip with its reason, so the window
    can name what is missing instead of quietly dropping it. The declared FAMILY is
    carried on the entry and is never a skip reason (e65s01): it is a labelled axis,
    not a gate. A missing directory
    is an empty library, not an error: a fresh installation has no folder yet.
    """
    root = directory if directory is not None else shader_library_dir()
    try:
        names = sorted(os.listdir(root))
    except OSError:
        return LibraryScan((), ())
    entries: list[LibraryEntry] = []
    skipped: list[SkippedLibraryFile] = []
    for filename in names:
        if not filename.endswith(SHADER_ASSET_EXTENSION):
            continue
        path = os.path.join(root, filename)
        try:
            code = load_shader(path)
        except ShaderAssetError as error:
            skipped.append(SkippedLibraryFile(filename, str(error)))
            continue
        kind = parse_kind(code)
        if kind is None:
            skipped.append(SkippedLibraryFile(filename, NO_KIND_REASON))
        elif len(entries) >= SHADER_MAX_LIBRARY_ENTRIES:
            skipped.append(
                SkippedLibraryFile(
                    filename,
                    f"not listed: the library holds more than {SHADER_MAX_LIBRARY_ENTRIES} shaders",
                )
            )
        else:
            entries.append(
                LibraryEntry(os.path.splitext(filename)[0], path, kind, family=parse_family(code))
            )
    return LibraryScan(tuple(entries), tuple(skipped))


def _check_asset_size(code: str, path: str) -> None:
    """Raise when the asset is beyond the sanity cap (L-6 named limit, e61 D4')."""
    if len(str(code)) > MAX_SHADER_BYTES:
        raise ShaderAssetError(
            f"shader asset {path!r} is {len(code)} bytes, beyond MAX_SHADER_BYTES "
            f"({MAX_SHADER_BYTES}): split the shader or delete the dead code"
        )


def load_shader(path: str) -> str:
    """The asset text at `path`, or a ShaderAssetError naming the reason."""
    try:
        with open(path, encoding="utf-8") as handle:
            code = handle.read()
    except OSError as error:
        raise ShaderAssetError(
            f"cannot read the shader asset {path!r} ({error.strerror}): the path must "
            "exist and be readable on the machine running vimix"
        ) from error
    _check_asset_size(code, path)
    return code


def save_shader(path: str, code: str) -> None:
    """Write the asset text to `path`, creating the library dir on demand."""
    _check_asset_size(code, path)
    directory = os.path.dirname(path)
    try:
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(code)
    except OSError as error:
        raise ShaderAssetError(
            f"cannot write the shader asset {path!r} ({error.strerror}): pick a writable "
            "path (the shader library dir is created on demand)"
        ) from error


def as_optional_float(value: Any) -> float | None:
    """Coerce a persisted registry value to a float, or None when it is junk."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _positive_int(value: Any) -> int | None:
    """A persisted 1-based slot, or None when it is missing or not a positive integer."""
    if value is None or isinstance(value, bool):
        return None
    try:
        slot = int(float(value))
    except (TypeError, ValueError):
        return None
    return slot if slot >= 1 else None


def registry_slot(row: dict[str, float | None], fallback: int) -> int:
    """The 1-based slot of a registry row (its own, else the given fallback) (e70s01)."""
    return _positive_int(row.get("slot")) or int(fallback)


def sanitize_uniform_registry(raw: Any) -> dict[str, dict[str, dict[str, float | None]]]:
    """Bound and normalize a persisted uniform registry (``target -> name -> row``).

    A corrupt row is dropped rather than defaulted: an invented range would make a
    Mapping clamp a real uniform. The caps come from constants
    (SHADER_MAX_TARGETS, SHADER_MAX_UNIFORMS_PER_TARGET), so a hand-edited project
    cannot grow without bound.
    """
    if not isinstance(raw, dict):
        return {}
    clean: dict[str, dict[str, dict[str, float | None]]] = {}
    for target, uniforms in list(raw.items())[:SHADER_MAX_TARGETS]:
        if not isinstance(uniforms, dict):
            continue
        rows: dict[str, dict[str, float | None]] = {}
        for index, (name, entry) in enumerate(
            list(uniforms.items())[:SHADER_MAX_UNIFORMS_PER_TARGET]
        ):
            if not isinstance(entry, dict):
                continue
            row = {key: as_optional_float(entry.get(key)) for key in SHADER_UNIFORM_KEYS}
            if any(value is not None for value in row.values()):
                # e70s01: the slot is the mappable identity; heal a missing/invalid one
                # from the row's order so a persisted registry always answers slot->name.
                slot = _positive_int(entry.get("slot")) or index + 1
                row["slot"] = float(slot)
                rows[str(name)] = row
        if rows:
            clean[str(target)] = rows
    return clean


def uniform_blocked(
    target: str,
    declared_target: str,
    declared_kind: str,
    source_type: Any = None,
) -> bool:
    """True when `/uniform` must NOT be sent to `target` (e61s06's guard, e68s04's fix).

    `/uniform` on a ShaderSource dereferenced a null pointer in vimix and KILLED the process
    (`SourceCallback.cpp`; confirmed on the rig twice, SPIKE-6). vimix commit 5ea524ca fixes it
    (issue #221). The guard lives in the SEND path, not in the UI: a stored Mapping, a Cue row or
    a script would otherwise do what a careful human is only one message away from doing.

    e68s04: the source's OSC `type` is the SIGNAL that the fix is present — the type answer
    landed in vimix AFTER the fix (commits 5ea524ca then 10abe99d, same session), so a target
    that reports a type at all runs a build where `/uniform` is safe. A typed source that is
    NOT shader-capable (a Video file, a Text) is refused too: `/uniform` there is a silent
    no-op, never a crash, but sending it is still wrong. A target with NO type that is the
    Shader window's current generator is still refused (the conservative fallback; e74s04
    retired the operator's rig declaration — VJmix 1.1.0 requires a vimix beta, so the type
    answers in practice).
    """
    typed = sourcekind.source_kind(source_type)
    if typed is not None:
        return not typed.shader
    return str(target) == str(declared_target) and str(declared_kind) == KIND_GENERATOR


def deploy_blocker(target: str, kind: str, path: str, target_type: Any = None) -> str | None:
    """Why a deploy would be refused, or None when it can be sent.

    The pre-flight runs BEFORE any OSC traffic because the rig showed both
    failures are silent: an empty target is a no-op at the vimix end, and a path
    that does not exist on the vimix machine becomes the shader CODE and renders
    nothing (specs/archive/spikes/SPIKE-shader-deployment.md, SPIKE-3).

    e68: when the target reports its OSC `type`, the pair must be COHERENT — a generator targets
    a ShaderSource (50) and an effect a Clone (41) — because `/code` on a Clone and `/filter` on
    a ShaderSource are the wrong messages, not merely no-ops. A target with no type keeps the
    operator's declaration, exactly as before.
    """
    if not str(target or "").strip():
        return "no target selected: pick the vimix source to deploy to"
    if kind not in KINDS:
        return f"unknown shader kind {kind!r}: declare the target as effect or generator"
    role = sourcekind.shader_role(target_type)
    if role is not None and role != kind:
        found = sourcekind.source_kind(target_type)
        label = found.label if found else "?"
        needs = (
            "a generator deploy needs a ShaderSource"
            if kind == KIND_GENERATOR
            else "an effect deploy needs a Clone"
        )
        return f"'{target}' is a {label} source: {needs}"
    if not str(path or "").strip():
        return "no asset file: save the shader first, the deploy sends its path"
    if not os.path.isfile(path):
        return f"the asset file {path!r} does not exist on the machine running vimix"
    return None


def compose_deploy_messages(target: str, kind: str, path: str) -> list[tuple[str, list[Any]]]:
    """The exact OSC messages that deploy an asset (the PATH only — decision D4').

    An EFFECT targets a CloneSource, and the filter message carries the custom
    filter name plus the path as its method: exactly TWO arguments, in ONE message
    (a third argument leaves vimix on a custom filter with its default program and
    the following `/code` does nothing — SPIKE-4). A GENERATOR targets a
    ShaderSource and takes the path as the single `/code` string.
    """
    base = f"/vimix/{str(target).strip()}"
    if kind == KIND_EFFECT:
        return [(f"{base}/filter", [FILTER_CUSTOM, str(path)])]
    return [(f"{base}/code", [str(path)])]


def default_asset_path(target: str) -> str:
    """The asset path a deploy uses when the document has no file yet.

    Inside the per-user library and named after the target, so every source has
    its own stable file: a second deploy overwrites its own asset and never
    another's.
    """
    stem = _UNSAFE_STEM_RE.sub("_", str(target or "").strip()) or SHADER_DEFAULT_ASSET_STEM
    return os.path.join(shader_library_dir(), stem + SHADER_ASSET_EXTENSION)


def _row_from(
    uniform: ShaderUniform, previous: dict[str, float | None] | None, slot: int
) -> dict[str, float | None]:
    """One registry row: the code's facts, plus whatever the operator set before.

    `slot` is the 1-based declaration position (e70s01): the mappable identity a
    binding persists, resolved back to `uniform.name` at send time.
    """
    old = previous or {}
    return {
        "slot": float(slot),
        "default": uniform.default,
        "min": uniform.range_min,
        "max": uniform.range_max,
        "override_min": old.get("override_min"),
        "override_max": old.get("override_max"),
        "value": old.get("value"),
    }


def build_registry(
    code: str, previous: dict[str, dict[str, float | None]] | None = None
) -> tuple[dict[str, dict[str, float | None]], list[str]]:
    """The uniform registry an asset implies, and the names it dropped.

    A re-scan re-derives the code's facts (name order, declared default, `// range`
    comment) and CARRIES OVER what only the operator knows (the manual range and the
    live value), because vimix reports neither back: losing them on a re-scan would
    silently move a control to its default. A uniform that disappeared (renamed or
    deleted) is dropped, and its name is returned so the caller can log the prune.
    """
    rows: dict[str, dict[str, float | None]] = {}
    declared = parse_uniform_slots(code)
    by_name = {name: slot for slot, name in declared.items()}
    used: set[int] = set()
    next_slot = 1
    for uniform in parse_uniforms(code):
        slot = by_name.get(uniform.name)
        if slot is None:
            # e70s03: the order only fills what the declared map leaves open (a slot
            # the asset RESERVES stays reserved, even if its name left the code).
            while next_slot in used or next_slot in declared:
                next_slot += 1
            slot = next_slot
        used.add(slot)
        next_slot = max(next_slot, slot + 1)
        rows[uniform.name] = _row_from(uniform, (previous or {}).get(uniform.name), slot)
    dropped = [name for name in (previous or {}) if name not in rows]
    return rows, dropped


def effective_range(row: dict[str, float | None]) -> tuple[float, float]:
    """The range a control should use: the operator's override, else the code's, else wide.

    The parsed `// range` is only a HINT (the rig could not observe it over OSC and
    vimix does not persist it), so a manual override wins and an asset without the
    comment still gets a usable control (decision D2).
    """
    override_min, override_max = row.get("override_min"), row.get("override_max")
    if override_min is not None and override_max is not None:
        return float(override_min), float(override_max)
    range_min, range_max = row.get("min"), row.get("max")
    if range_min is not None and range_max is not None:
        return float(range_min), float(range_max)
    return UNBOUNDED_RANGE


def is_bounded(row: dict[str, float | None]) -> bool:
    """True when the row carries a real range (the code's or the operator's)."""
    return effective_range(row) != UNBOUNDED_RANGE


def compose_uniform_message(target: str, name: str, value: float) -> tuple[str, list[Any]]:
    """The OSC message that sets one uniform — name and value only.

    No duration: the e36 rule (D5) keeps ms/animation in the Cue rows, where the
    native vimix ramp is a deliberate performance choice.
    """
    return (f"/vimix/{str(target).strip()}/uniform", [str(name), float(value)])


def replay_messages(
    target: str, registry: dict[str, dict[str, float | None]]
) -> list[tuple[str, list[Any]]]:
    """The messages that restore every registered value, in declaration order.

    `SetCode` replaces the whole program, so EVERY deploy resets the uniforms to the
    defaults written in the code (rig-confirmed, SPIKE-7): without this replay a
    deploy silently forgets what the operator had set. The live value wins, and a
    uniform the operator never touched replays its declared default (harmless, and
    it keeps one message per registered name).
    """
    messages: list[tuple[str, list[Any]]] = []
    for name, row in dict(registry or {}).items():
        value = row.get("value")
        if value is None:
            value = row.get("default")
        if value is not None:
            messages.append(compose_uniform_message(target, name, float(value)))
    return messages


def compose_bypass_messages(target: str, bypassed: bool) -> list[tuple[str, list[Any]]]:
    """The one message that bypasses (`none`) or re-enables (`custom`) an effect.

    Bypassing leaves the asset file alone; un-bypassing only restores the FILTER, so
    the caller re-deploys the path (that is what puts the code back) — vimix creates a
    fresh filter with its default program when the custom filter is re-selected.
    """
    name = FILTER_PASSTHROUGH if bypassed else FILTER_CUSTOM
    return [(f"/vimix/{str(target).strip()}/filter", [name])]


def uniform_entries(
    registry: dict[str, dict[str, dict[str, float | None]]],
) -> dict[str, dict[str, Any]]:
    """The dynamic catalogue entries of every registered uniform (e61s05).

    Keyed like a property (`uniform:<name>`) so the Mapper, the Sequencer and the
    Cue rows can drive a shader parameter without knowing what GLSL is. The same
    name may be registered on several sources: the entry keeps the first range
    found (the surfaces look up their OWN target's row when they clamp), and the
    label names the uniform, which is what the operator chose.
    """
    entries: dict[str, dict[str, Any]] = {}
    for target in sorted(registry or {}):
        for _name, row in (registry[target] or {}).items():
            slot = _positive_int(row.get("slot"))
            if slot is None or slot > SHADER_MAPPABLE_UNIFORM_SLOTS:
                continue  # beyond the mappable cap: the coder slider still drives it
            key = catalog.uniform_slot_property(slot)
            if key in entries:
                continue
            low, high = effective_range(row)
            value = row.get("value")
            neutral = float(value if value is not None else row.get("default") or 0.0)
            entries[key] = catalog.uniform_entry(f"uniform{slot}", neutral, low, high)
    return entries


def resolve_uniform(
    registry: dict[str, dict[str, dict[str, float | None]]], target: str, prop: str
) -> tuple[str, dict[str, float | None]] | None:
    """The (GLSL name, row) a slot property drives on ONE target, or None (e70s01).

    The SINGLE place a `uniform:<slot>` becomes a name: the Mapper's send, the
    Sequencer's step, the Cue's row and every surface label go through it. None means
    "nothing to drive" — the callers send NOTHING, never a message vimix would drop.
    """
    slot = catalog.parse_uniform_slot(prop)
    if slot is None:
        return None
    for name, row in ((registry or {}).get(str(target)) or {}).items():
        if _positive_int(row.get("slot")) == slot:
            return str(name), row
    return None


def uniform_send(
    registry: dict[str, dict[str, dict[str, float | None]]],
    prop: str,
    value: float,
    target: str,
    ms: float | None = None,
) -> tuple[str, list[Any]] | None:
    """The message a catalogue-driven surface sends for a uniform slot (e61s05, e70s01).

    None when the property is not a uniform, or when the slot has no live uniform on
    the target. `ms` is the Cue row's native ramp — the Mapper and the Sequencer never
    pass it (D5).
    """
    resolved = resolve_uniform(registry, target, prop)
    if resolved is None:
        return None
    name, _row = resolved
    args: list[Any] = [name, float(value)]
    if ms is not None:
        args.append(float(ms))
    return (f"/vimix/{str(target).strip()}/uniform", args)


def registry_row(
    registry: dict[str, dict[str, dict[str, float | None]]], target: str, prop: str
) -> dict[str, float | None] | None:
    """The registry row of a slot on ONE target, or None when it is absent (e70s01).

    The surfaces clamp against their OWN target's row (the same slot is a different
    uniform on two sources with different shaders), so this is the lookup they use
    rather than the aggregate entry from `uniform_entries`.
    """
    resolved = resolve_uniform(registry, target, prop)
    return resolved[1] if resolved is not None else None
