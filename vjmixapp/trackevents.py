"""Tracking events: continuous signals turned into cue-grade edges (e90s07).

VJ control is continuous; theatre is event-driven. A held pose or a performer
walking into a zone must fire a cue ONCE, on the edge — a retrigger every frame
is worse than no trigger at all, because it restarts the cue endlessly.

This module is PURE: it consumes the zone and body snapshots and returns the
events of this step. Persistence (the project's ``tracking_events`` section) and
dispatch (``cue.cue_start`` on the main thread) live in ``vjmix.py``.
"""

from dataclasses import dataclass, field
from typing import Any

from vjmixapp import bodytrack

EVENT_ZONE_ENTER = "zone_enter"
EVENT_ZONE_EXIT = "zone_exit"
EVENT_POSE_HELD = "pose_held"
EVENT_POSE_RELEASED = "pose_released"
EVENT_TRACK_LOST = "track_lost"
EVENT_KINDS: tuple[str, ...] = (
    EVENT_ZONE_ENTER,
    EVENT_ZONE_EXIT,
    EVENT_POSE_HELD,
    EVENT_POSE_RELEASED,
    EVENT_TRACK_LOST,
)
EVENT_LABELS: dict[str, str] = {
    EVENT_ZONE_ENTER: "Zone entered",
    EVENT_ZONE_EXIT: "Zone left",
    EVENT_POSE_HELD: "Pose held",
    EVENT_POSE_RELEASED: "Pose released",
    EVENT_TRACK_LOST: "Body track lost",
}
EVENT_DECIMALS = 0
EDGE_ON = 0.5
DEFAULT_COOLDOWN_S = 0.5
DETAIL_MAX = 32


@dataclass(frozen=True)
class TrackingEvent:
    """One edge: ``detail`` names the zone, the body slot or the pose."""

    kind: str
    detail: str
    label: str = ""

    def key(self) -> tuple[str, str]:
        return (self.kind, self.detail)


def _zone_detail(group: str) -> str:
    return group


def _pose_name(signal: str) -> str:
    return signal.removeprefix("pose_")


@dataclass
class EventBus:
    """Edge detection with a per-(kind, detail) cooldown."""

    cooldown_s: float = DEFAULT_COOLDOWN_S
    _last: dict[tuple[str, str], float] = field(default_factory=dict)
    _present: set[str] = field(default_factory=set)
    _poses: set[str] = field(default_factory=set)
    _zone_edges: dict[tuple[str, str], bool] = field(default_factory=dict)

    def reset(self) -> None:
        self._last.clear()
        self._present.clear()
        self._poses.clear()
        self._zone_edges.clear()

    def _ready(self, now: float, kind: str, detail: str) -> bool:
        previous = self._last.get((kind, detail))
        if previous is not None and now - previous < self.cooldown_s:
            return False
        self._last[(kind, detail)] = now
        return True

    def _emit(self, now: float, kind: str, detail: str, events: list[TrackingEvent]) -> None:
        if self._ready(now, kind, detail):
            events.append(TrackingEvent(kind, detail, EVENT_LABELS[kind]))

    def _zone_events(
        self, now: float, zones: dict[str, dict[str, float]], events: list[TrackingEvent]
    ) -> None:
        for group, signals in sorted(zones.items()):
            for signal, kind in (
                ("enter", EVENT_ZONE_ENTER),
                ("exit", EVENT_ZONE_EXIT),
            ):
                rising = float(signals.get(signal, 0.0)) >= EDGE_ON
                edge = (group, signal)
                if rising and not self._zone_edges.get(edge, False):
                    self._emit(now, kind, _zone_detail(group), events)
                self._zone_edges[edge] = rising

    def _body_events(
        self, now: float, bodies: dict[str, dict[str, float]], events: list[TrackingEvent]
    ) -> None:
        live = {
            group for group, signals in bodies.items() if signals.get("present", 0.0) >= EDGE_ON
        }
        held: set[str] = set()
        for group in sorted(live):
            signals = bodies[group]
            for signal in signals:
                if not signal.startswith("pose_"):
                    continue
                if float(signals[signal]) < EDGE_ON:
                    continue
                held.add(f"{group}.{_pose_name(signal)}")
        for detail in sorted(held - self._poses):
            self._emit(now, EVENT_POSE_HELD, detail, events)
        for detail in sorted(self._poses - held):
            self._emit(now, EVENT_POSE_RELEASED, detail, events)
        for group in sorted(self._present - live):
            self._emit(now, EVENT_TRACK_LOST, group, events)
        self._present = live
        self._poses = held

    def step(
        self,
        now: float,
        zones: dict[str, dict[str, float]],
        bodies: dict[str, dict[str, float]],
    ) -> list[TrackingEvent]:
        """The events produced by one step of the live snapshots."""
        events: list[TrackingEvent] = []
        self._zone_events(now, zones, events)
        self._body_events(now, bodies, events)
        return events


def kind_from_label(label: str) -> str:
    """The event kind behind a combo label (the editor stores the KIND)."""
    for kind in EVENT_KINDS:
        if EVENT_LABELS[kind] == label:
            return kind
    return label if label in EVENT_KINDS else EVENT_ZONE_ENTER


def compose_detail(group: str, pose: str) -> str:
    """The binding detail for a body pose ("body1.arms_up")."""
    return f"{group}.{pose}"


def pose_choices() -> tuple[str, ...]:
    """Every body pose the rules can produce (the editor's detail hints)."""
    return tuple(bodytrack.POSE_NAMES)


def sanitize_binding(raw: Any) -> dict[str, Any] | None:
    """One ``{kind, detail, mapping_id}`` row, or None when it is unusable."""
    if not isinstance(raw, dict):
        return None
    kind = str(raw.get("kind") or "")
    if kind not in EVENT_KINDS:
        return None
    try:
        mapping_id = int(raw.get("mapping_id") or 0)
    except (TypeError, ValueError):
        return None
    if mapping_id <= 0:
        return None
    detail = str(raw.get("detail") or "")[:DETAIL_MAX]
    return {"kind": kind, "detail": detail, "mapping_id": mapping_id}


def sanitize_bindings(raw: Any) -> list[dict[str, Any]]:
    """The persisted bindings, healed; a legacy project yields an empty list."""
    if not isinstance(raw, list):
        return []
    clean: list[dict[str, Any]] = []
    seen: set[tuple[str, str, int]] = set()
    for item in raw:
        binding = sanitize_binding(item)
        if binding is None:
            continue
        key = (binding["kind"], binding["detail"], binding["mapping_id"])
        if key in seen:
            continue
        seen.add(key)
        clean.append(binding)
    return clean


def matches(binding: dict[str, Any], event: TrackingEvent) -> bool:
    """A binding fires when kind and detail match (an empty detail = any)."""
    if binding.get("kind") != event.kind:
        return False
    detail = str(binding.get("detail") or "")
    return not detail or detail == event.detail


def targets(bindings: list[dict[str, Any]], event: TrackingEvent) -> list[int]:
    """The mapping ids one event starts, de-duplicated and in binding order."""
    found: list[int] = []
    for binding in bindings:
        if matches(binding, event):
            mapping_id = int(binding["mapping_id"])
            if mapping_id not in found:
                found.append(mapping_id)
    return found


def drop_mapping(bindings: list[dict[str, Any]], mapping_id: int) -> list[dict[str, Any]]:
    """Remove the bindings of a deleted mapping (the Mapper's orphan rule)."""
    return [binding for binding in bindings if int(binding["mapping_id"]) != mapping_id]
