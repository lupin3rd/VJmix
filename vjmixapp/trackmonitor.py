"""The tracking signal monitor: one flattened view of every bindable signal.

The Mapper already owns four catalogs (Leap, hands, bodies, zones); this module
turns them into ONE list of rows with the live value, so the operator can see
what the stage is producing and turn a row into a Mapper line without learning
four dialogs (e90s06).

Pure: no dpg, no state writes. ``vjmix.py`` renders the rows and performs the
click-to-map; this module only decides WHAT a row is.
"""

from dataclasses import dataclass
from typing import Any

from vjmixapp import bodytrack, handtrack, leap, zonetrack

ENGINE_LEAP = "leap"
ENGINE_HAND = "hand"
ENGINE_BODY = "body"
ENGINE_ZONES = "zones"
ENGINES: tuple[str, ...] = (ENGINE_LEAP, ENGINE_HAND, ENGINE_BODY, ENGINE_ZONES)

ENGINE_LABELS: dict[str, str] = {
    ENGINE_LEAP: "Leap Motion",
    ENGINE_HAND: "Hands (webcam)",
    ENGINE_BODY: "Bodies",
    ENGINE_ZONES: "Zones",
}
MOTION_GROUP = "motion"
HAND_SIDES: tuple[str, str] = ("left", "right")
EMPTY_VALUE = "—"


@dataclass(frozen=True)
class SignalRow:
    """One bindable signal with its live value (None = nothing to show yet)."""

    engine: str
    group: str  # display name ("Body 1", "Front stage")
    group_id: str  # the persisted id ("body1", "zone1", "left")
    key: str
    label: str
    value: float | None

    def text(self, decimals: int = 2) -> str:
        """``label  value`` — the one-line form the monitor renders."""
        if self.value is None:
            return f"{self.label:<22} {EMPTY_VALUE:>8}"
        return f"{self.label:<22} {self.value:>{8}.{decimals}f}"


def _hand_rows(provider: str, values: dict[str, float]) -> list[SignalRow]:
    rows: list[SignalRow] = []
    for side in HAND_SIDES:
        for field in handtrack.bindable_signals(provider):
            key = handtrack.binding_key(side, field)
            rows.append(
                SignalRow(
                    engine=ENGINE_HAND,
                    group=side.capitalize(),
                    group_id=side,
                    key=key,
                    label=handtrack.binding_label(key, provider),
                    value=values.get(key),
                )
            )
    return rows


def _leap_rows(values: dict[str, float]) -> list[SignalRow]:
    rows: list[SignalRow] = []
    for side in HAND_SIDES:
        for field in leap.bindable_signals():
            key = leap.binding_key(side, field)
            rows.append(
                SignalRow(
                    engine=ENGINE_LEAP,
                    group=side.capitalize(),
                    group_id=side,
                    key=key,
                    label=leap.binding_label(key),
                    value=values.get(key),
                )
            )
    return rows


def _body_rows(snapshot: dict[str, dict[str, float]]) -> list[SignalRow]:
    rows: list[SignalRow] = []
    for group in sorted(snapshot):
        for signal in bodytrack.BODY_SIGNALS:
            rows.append(
                SignalRow(
                    engine=ENGINE_BODY,
                    group=group.replace("body", "Body "),
                    group_id=group,
                    key=signal,
                    label=bodytrack.body_signal_label(signal),
                    value=snapshot[group].get(signal),
                )
            )
    return rows


def _zone_rows(
    snapshot: dict[str, dict[str, float]], zones: list[dict[str, Any]]
) -> list[SignalRow]:
    rows: list[SignalRow] = []
    names = {str(zone["id"]): str(zone.get("name") or f"Zone {zone['id']}") for zone in zones}
    for group in sorted(snapshot):
        zone_id = group.replace("zone", "")
        for signal, value in sorted(snapshot[group].items()):
            rows.append(
                SignalRow(
                    engine=ENGINE_ZONES,
                    group=names.get(zone_id, group),
                    group_id=group,
                    key=signal,
                    label=zonetrack.zone_signal_label(signal),
                    value=value,
                )
            )
    return rows


def monitor_rows(
    hand_provider: str,
    leap_values: dict[str, float],
    body_snapshot: dict[str, dict[str, float]],
    zones_snapshot: dict[str, dict[str, float]],
    zones: list[dict[str, Any]],
) -> list[SignalRow]:
    """Every row the monitor shows, grouped by engine, in a stable order."""
    rows: list[SignalRow] = []
    # ONE hand source at a time (specs/HAND_TRACKING_MODES_LATEST.md): both
    # catalogs read the same snapshot (`leap_values`), so showing both listed the
    # same numbers twice and the operator saw "webcam values under Leap Motion"
    # (rig, 2026-10-29). Only the ACTIVE provider's catalog is listed.
    if hand_provider == handtrack.PROVIDER_LEAP:
        rows.extend(_leap_rows(leap_values))
    else:
        rows.extend(_hand_rows(handtrack.PROVIDER_WEBCAM, leap_values))
    rows.extend(_body_rows(body_snapshot))
    rows.extend(_zone_rows(zones_snapshot, zones))
    return rows


def group_rows(rows: list[SignalRow]) -> list[tuple[str, list[SignalRow]]]:
    """Rows grouped as ``(title, rows)`` for the dialog, engines in fixed order."""
    grouped: list[tuple[str, list[SignalRow]]] = []
    for engine in ENGINES:
        engine_rows = [row for row in rows if row.engine == engine]
        if engine_rows:
            grouped.append((ENGINE_LABELS[engine], engine_rows))
    return grouped
