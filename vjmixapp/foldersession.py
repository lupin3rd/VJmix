"""Session recipe — the folder session's memory (e100s02).

A folder session is a `.mix` plus a sidecar `<name>.vjmix.json` beside it. This
module is the model of that sidecar: versioned, sanitized, healable, and turned
into the writer's payload. A folder session is keyed by its FOLDER, so it is a
separate store from the ad-hoc draft library in `drafts.py` (ADR decision 1);
only the alpha constants are shared, so "parked" and "visible" keep one meaning.

DPG-FREE and network-free by construction (HIGH-1): the composition root owns the
UI and `fsclient` moves the bytes, this module only reads and writes dicts.
"""

import math
import os
from typing import Any

from vjmixapp import drafts

RECIPE_FORMAT = "vjmix-session-recipe"
RECIPE_VERSION = 1
RECIPE_EXT = ".vjmix.json"
# The writer's own bound (viOSC mix_schema.MAX_SOURCES): a recipe never promises a
# source the session cannot carry.
MAX_RECIPE_FILES = 256
ASSIGNMENT_KINDS = ("mapper", "seq")
# The opening clip is the only visible source at load; the rest stay parked, so
# the alpha pass of a session change shows exactly one clip (ADR decision 3).
FIRST_ALPHA = 1.0


def default_name(folder: str) -> str:
    """The session name a folder suggests: its basename (the UI may edit it)."""
    clean = str(folder or "").replace("\\", "/").rstrip("/")
    return os.path.basename(clean)


def _clean_paths(raw: Any, limit: int = MAX_RECIPE_FILES) -> list[str]:
    """Valid, unique, non-empty strings, bounded."""
    if not isinstance(raw, (list, tuple, set)):
        return []
    paths: list[str] = []
    for item in raw:
        if not isinstance(item, str) or not item.strip() or item in paths:
            continue
        paths.append(item)
        if len(paths) >= limit:
            break
    return paths


def _clean_transition(raw: Any) -> float:
    """A finite, non-negative crossfade duration (0.0 when unusable)."""
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(value):
        return 0.0
    return max(0.0, value)


def alphas_for(files: list[str], first: str) -> dict[str, float]:
    """``{path: alpha}`` with the opening clip visible and every other parked."""
    return {
        str(path): (FIRST_ALPHA if str(path) == str(first) else drafts.DEFAULT_FILE_ALPHA)
        for path in files
    }


def _clean_assignment(raw: Any) -> dict[str, Any] | None:
    """One ``{kind, key, target}`` with a usable key for its kind, else None."""
    if not isinstance(raw, dict):
        return None
    kind = str(raw.get("kind") or "")
    if kind not in ASSIGNMENT_KINDS:
        return None
    target = raw.get("target")
    if not isinstance(target, str) or not target.strip():
        return None
    if kind == "mapper":
        key: Any = raw.get("key")
        if not isinstance(key, str) or not key.strip():
            return None
    else:
        raw_key = raw.get("key")
        if not isinstance(raw_key, (int, float, str)):
            return None
        try:
            key = int(raw_key)
        except (TypeError, ValueError):
            return None
        if key < 0:
            return None
    return {"kind": kind, "key": key, "target": target}


def _clean_assignments(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    cleaned: list[dict[str, Any]] = []
    for item in raw:
        entry = _clean_assignment(item)
        if entry is not None:
            cleaned.append(entry)
    return cleaned


def build_recipe(
    folder: str,
    session: str,
    files: list[str],
    first: str,
    *,
    excluded: list[str] | None = None,
    assignments: list[dict[str, Any]] | None = None,
    transition: Any = 0.0,
    updated: str = "",
) -> dict[str, Any]:
    """The recipe for a folder session, from the wizard's choices.

    The opening clip is moved to position 1, so the written `.mix` opens on it
    (its alpha is 1.0 and every other source is parked).
    """
    ordered = _clean_paths(files)
    chosen = str(first) if str(first) in ordered else (ordered[0] if ordered else "")
    included = ([chosen] + [path for path in ordered if path != chosen]) if chosen else []
    skipped = [path for path in _clean_paths(excluded) if path not in included]
    return {
        "format": RECIPE_FORMAT,
        "version": RECIPE_VERSION,
        "session": str(session or "").strip() or default_name(folder),
        "folder": str(folder or ""),
        "files": included,
        "excluded": skipped,
        "alphas": alphas_for(included, chosen),
        "first": chosen,
        "assignments": _clean_assignments(assignments),
        "transition": _clean_transition(transition),
        "updated": str(updated or ""),
    }


def sanitize_recipe(raw: Any) -> dict[str, Any] | None:
    """A healed recipe, or None when the input is not ours (never raises).

    A hand-edited or corrupt sidecar must not block the wizard: unknown entries
    are dropped, ids and paths healed, alphas clamped to the draft model's range,
    and a wrong format/version is treated as "no recipe at all".
    """
    if not isinstance(raw, dict):
        return None
    if raw.get("format") != RECIPE_FORMAT:
        return None
    raw_version = raw.get("version")
    if not isinstance(raw_version, (int, float, str)):
        return None
    try:
        version = int(raw_version)
    except (TypeError, ValueError):
        return None
    if version != RECIPE_VERSION:
        return None
    files = _clean_paths(raw.get("files"))
    if not files:
        return None
    first = str(raw.get("first") or "")
    if first not in files:
        first = files[0]
    excluded = [path for path in _clean_paths(raw.get("excluded")) if path not in files]
    raw_alphas = raw.get("alphas")
    if not isinstance(raw_alphas, dict):
        raw_alphas = {}
    alphas: dict[str, float] = {}
    for path in files:
        try:
            value = float(raw_alphas.get(path, drafts.DEFAULT_FILE_ALPHA))
        except (TypeError, ValueError):
            value = drafts.DEFAULT_FILE_ALPHA
        alphas[path] = min(drafts.MAX_FILE_ALPHA, max(drafts.MIN_FILE_ALPHA, value))
    return {
        "format": RECIPE_FORMAT,
        "version": RECIPE_VERSION,
        "session": str(raw.get("session") or "").strip(),
        "folder": str(raw.get("folder") or ""),
        "files": files,
        "excluded": excluded,
        "alphas": alphas,
        "first": first,
        "assignments": _clean_assignments(raw.get("assignments")),
        "transition": _clean_transition(raw.get("transition")),
        "updated": str(raw.get("updated") or ""),
    }


def merge_recipe(recipe: dict[str, Any], scanned_paths: list[str]) -> dict[str, Any]:
    """The recipe reconciled with a fresh scan of its folder.

    Keeps the recipe's order and every surviving choice; appends the files that
    appeared since (parked, so nothing new becomes visible on its own) and
    reports the ones that vanished. A chosen opening clip that is gone falls back
    to the first remaining file, so the session still opens on something.
    """
    scanned = _clean_paths(scanned_paths)
    known = _clean_paths(recipe.get("files"))
    excluded = [path for path in _clean_paths(recipe.get("excluded")) if path in scanned]
    kept = [path for path in known if path in scanned]
    vanished = [path for path in known if path not in scanned]
    added = [path for path in scanned if path not in known and path not in excluded]
    files = kept + added
    first = str(recipe.get("first") or "")
    if first not in files:
        first = files[0] if files else ""
    saved_alphas = recipe.get("alphas")
    if not isinstance(saved_alphas, dict):
        saved_alphas = {}
    alphas = {
        path: (
            FIRST_ALPHA
            if path == first
            else _clamped_alpha(saved_alphas.get(path), drafts.DEFAULT_FILE_ALPHA)
        )
        for path in files
    }
    return {
        "name": str(recipe.get("session") or ""),
        "files": files,
        "excluded": excluded,
        "alphas": alphas,
        "first": first,
        "assignments": _clean_assignments(recipe.get("assignments")),
        "transition": _clean_transition(recipe.get("transition")),
        "added": added,
        "vanished": vanished,
    }


def _clamped_alpha(raw: Any, fallback: float) -> float:
    """One alpha clamped into the draft model's range (the fallback when junk)."""
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return fallback
    return min(drafts.MAX_FILE_ALPHA, max(drafts.MIN_FILE_ALPHA, value))


def assignments_for_panel(
    assignments: list[dict[str, Any]], files: list[str]
) -> dict[tuple[str, Any], str]:
    """``{(kind, key): path}`` for the Send panel's pre-selection by path."""
    wanted = set(_clean_paths(files))
    return {
        (entry["kind"], entry["key"]): entry["target"]
        for entry in _clean_assignments(assignments)
        if entry["target"] in wanted
    }


def resolve_assignments(
    assignments: list[dict[str, Any]], sources: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """``[{kind, key, target: <live name>}]`` from the write response's sources.

    Vimix exposes no `uri` property, so a live source can only be matched by the
    name the writer chose; a path with no live source is dropped (the caller
    reports how many survived).
    """
    by_uri = {
        str(source.get("uri")): str(source.get("name"))
        for source in sources or []
        if isinstance(source, dict) and source.get("uri") and source.get("name")
    }
    resolved: list[dict[str, Any]] = []
    for entry in _clean_assignments(assignments):
        name = by_uri.get(entry["target"])
        if name:
            resolved.append({"kind": entry["kind"], "key": entry["key"], "target": name})
    return resolved
