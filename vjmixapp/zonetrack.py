"""Pure zone-motion core for the stage camera (e88s01).

T0 has no model and no identity: a running background plus a thresholded frame
difference is enough to say "something moved inside this polygon". Everything
here is pure and testable with synthetic frames — the camera stays out of the
module (``CameraSource`` lives in ``handio``), and no dpg, ``av`` or
``onnxruntime`` import is allowed (HIGH-1).

Coordinate conventions (shared with the hand engine):

    x  -1..+1, +1 = the right of the image (mirrored only when ``mirror``)
    y  -1..+1, +1 = up
    zone x/y are relative to the zone bounding box: 0 = centre, +/-1 = edge

The model is deliberately small: background EMA, 3x3 open, minimum area,
per-zone mass/centroid/energy/velocity, occupancy hysteresis and enter/exit
pulses. A zone with no motion HOLDS its last position; it never snaps to zero,
because a position mapping must not jump when a performer stops moving.
"""

import copy
import math
from dataclasses import dataclass
from typing import Any

import numpy as np
from PIL import Image, ImageDraw

from vjmixapp import camera, state
from vjmixapp.config import load_config, save_config
from vjmixapp.queues import log_error

ZONE_MAX = 8
ZONE_MIN_POINTS = 3
ZONE_NAME_MAX = 24

PROCESSING_WIDTH_DEFAULT = 320
PROCESSING_WIDTH_MIN = 160
PROCESSING_WIDTH_MAX = 640
THRESHOLD_DEFAULT = 18.0
THRESHOLD_MIN = 4.0
THRESHOLD_MAX = 60.0
MIN_AREA_DEFAULT = 0.004
MIN_AREA_MIN = 0.0005
MIN_AREA_MAX = 0.10
BG_TAU_DEFAULT = 2.0
BG_TAU_MIN = 0.2
BG_TAU_MAX = 10.0
BG_ALPHA_MIN = 0.005
CAMERA_WIDTH_MIN = 160
CAMERA_WIDTH_MAX = 1920
CAMERA_HEIGHT_MIN = 120
CAMERA_HEIGHT_MAX = 1080
MAX_HZ_DEFAULT = 10.0
MAX_HZ_MIN = 2.0
MAX_HZ_MAX = 15.0
PREVIEW_HZ = 20.0

# Energy: the fraction of a zone that reads as "full" motion. A performer
# crossing a zone rarely fills it; 35 % is a useful ceiling for the Mapper.
ENERGY_FULL = 0.35
ENERGY_TAU_S = 0.30
VEL_TAU_S = 0.20
VEL_CLAMP = 4.0

# Occupancy hysteresis: the mass fraction that arms the zone, the lower one that
# releases it, and how long each side must persist (a single noisy frame cannot
# toggle a trigger or a video position).
OCCUPANCY_ENTER = 0.015
OCCUPANCY_EXIT = 0.006
ENTER_HOLD_S = 0.15
EXIT_HOLD_S = 0.40
PULSE_S = 0.15

DEFAULT_COLOR: tuple[int, int, int] = (255, 180, 60)

ZONE_FIELDS: dict[str, dict[str, Any]] = {
    "energy": {"label": "Energy", "decimals": 2, "input_from": 0.0, "input_to": 1.0},
    "occupancy": {"label": "Occupancy", "decimals": 0, "input_from": 0.0, "input_to": 1.0},
    "x": {"label": "Position X", "decimals": 2, "input_from": -1.0, "input_to": 1.0},
    "y": {"label": "Position Y", "decimals": 2, "input_from": -1.0, "input_to": 1.0},
    "vx": {
        "label": "Velocity X",
        "decimals": 2,
        "input_from": -VEL_CLAMP,
        "input_to": VEL_CLAMP,
    },
    "vy": {
        "label": "Velocity Y",
        "decimals": 2,
        "input_from": -VEL_CLAMP,
        "input_to": VEL_CLAMP,
    },
    "enter": {"label": "Enter", "decimals": 0, "input_from": 0.0, "input_to": 1.0},
    "exit": {"label": "Exit", "decimals": 0, "input_from": 0.0, "input_to": 1.0},
}
ZONE_SIGNALS: tuple[str, ...] = tuple(ZONE_FIELDS)
MOTION_FIELDS: dict[str, dict[str, Any]] = {
    "energy": {"label": "Motion energy", "decimals": 2, "input_from": 0.0, "input_to": 1.0},
    "x": {"label": "Motion X", "decimals": 2, "input_from": -1.0, "input_to": 1.0},
    "y": {"label": "Motion Y", "decimals": 2, "input_from": -1.0, "input_to": 1.0},
    "present": {"label": "Motion", "decimals": 0, "input_from": 0.0, "input_to": 1.0},
}


def clamp(value: float, low: float, high: float) -> float:
    """Clamp a number into an inclusive interval."""
    return max(low, min(high, value))


def zone_signal_range(signal: str) -> tuple[float, float]:
    """The default Mapper input window for one zone signal (KeyError if unknown)."""
    entry = ZONE_FIELDS[signal]
    return float(entry["input_from"]), float(entry["input_to"])


def zone_signal_label(signal: str) -> str:
    """The human label of one zone signal."""
    return str(ZONE_FIELDS[signal]["label"])


# ---------------------------------------------------------------------------
# Zone model
# ---------------------------------------------------------------------------


def _heal_point(raw: Any) -> list[float] | None:
    if not isinstance(raw, (list, tuple)) or len(raw) < 2:
        return None
    try:
        x, y = float(raw[0]), float(raw[1])
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(x) and math.isfinite(y)):
        return None
    return [clamp(x, 0.0, 1.0), clamp(y, 0.0, 1.0)]


def _heal_color(raw: Any) -> list[int]:
    if not isinstance(raw, (list, tuple)) or len(raw) < 3:
        return list(DEFAULT_COLOR)
    healed: list[int] = []
    for channel in raw[:3]:
        try:
            healed.append(int(clamp(float(channel), 0.0, 255.0)))
        except (TypeError, ValueError):
            healed.append(0)
    return healed


def sanitize_zone(raw: Any, fallback_id: int = 1) -> dict[str, Any] | None:
    """Heal one stored zone; None when it cannot become a polygon.

    A zone with fewer than ``ZONE_MIN_POINTS`` valid points is dropped. The id
    is clamped into ``1..ZONE_MAX`` (a duplicate is renumbered by
    :func:`sanitize_zones`), the name is truncated and the colour is clamped.
    """
    if not isinstance(raw, dict):
        return None
    points_raw = raw.get("points")
    if not isinstance(points_raw, (list, tuple)):
        return None
    points = [p for p in (_heal_point(item) for item in points_raw) if p is not None]
    if len(points) < ZONE_MIN_POINTS:
        return None
    try:
        zone_id = int(raw.get("id", fallback_id))
    except (TypeError, ValueError):
        zone_id = fallback_id
    zone_id = int(clamp(zone_id, 1, ZONE_MAX))
    name = str(raw.get("name") or f"Zone {zone_id}")[:ZONE_NAME_MAX]
    return {
        "id": zone_id,
        "name": name,
        "color": _heal_color(raw.get("color")),
        "points": points,
    }


def sanitize_zones(raw: Any) -> list[dict[str, Any]]:
    """Heal a zone list: drop garbage, renumber duplicates, cap at ``ZONE_MAX``."""
    if not isinstance(raw, (list, tuple)):
        return []
    healed: list[dict[str, Any]] = []
    used: set[int] = set()
    for item in raw:
        if len(healed) >= ZONE_MAX:
            break
        zone = sanitize_zone(item)
        if zone is None:
            continue
        zone_id = zone["id"]
        if zone_id in used:
            free = next(
                (candidate for candidate in range(1, ZONE_MAX + 1) if candidate not in used), None
            )
            if free is None:
                break
            zone_id = free
            zone["id"] = zone_id
        used.add(zone_id)
        healed.append(zone)
    return healed


def zone_bounds(points: list[list[float]]) -> tuple[float, float, float, float]:
    """The (x0, y0, x1, y1) bounding box of normalized points."""
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return min(xs), min(ys), max(xs), max(ys)


def zone_mask(points: list[list[float]], width: int, height: int) -> np.ndarray:
    """Rasterize a normalized polygon at pixel centres (ray casting).

    Convex and concave polygons are both supported; a degenerate polygon
    (zero-area bounding box) yields an all-False mask.
    """
    x0, y0, x1, y1 = zone_bounds(points)
    if x1 <= x0 or y1 <= y0:
        return np.zeros((height, width), dtype=bool)
    px = np.array([p[0] * width for p in points], dtype=np.float64)
    py = np.array([p[1] * height for p in points], dtype=np.float64)
    grid_x, grid_y = np.meshgrid(
        np.arange(width, dtype=np.float64) + 0.5,
        np.arange(height, dtype=np.float64) + 0.5,
    )
    inside = np.zeros((height, width), dtype=bool)
    previous = len(points) - 1
    for current in range(len(points)):
        xi, yi = px[current], py[current]
        xj, yj = px[previous], py[previous]
        crosses = (yi > grid_y) != (yj > grid_y)
        with np.errstate(divide="ignore", invalid="ignore"):
            intersection = (xj - xi) * (grid_y - yi) / (yj - yi) + xi
        inside ^= crosses & (grid_x < intersection)
        previous = current
    return inside


# ---------------------------------------------------------------------------
# Motion model
# ---------------------------------------------------------------------------


def gray_frame(rgb: np.ndarray, width: int = PROCESSING_WIDTH_DEFAULT) -> np.ndarray:
    """Luma + area-average downscale to ``width`` (never upscales), numpy only."""
    array = np.asarray(rgb)
    if array.ndim != 3 or array.shape[2] < 3 or array.shape[0] == 0 or array.shape[1] == 0:
        raise ValueError(f"expected an HxWx3 RGB frame, got shape {array.shape!r}")
    height, source_width = array.shape[:2]
    target_width = int(clamp(float(width), 1.0, float(source_width)))
    target_height = max(1, round(height * target_width / source_width))
    luma = (
        array[..., 0].astype(np.float32) * 0.299
        + array[..., 1].astype(np.float32) * 0.587
        + array[..., 2].astype(np.float32) * 0.114
    )
    if target_width == source_width and target_height == height:
        return np.clip(luma, 0.0, 255.0).astype(np.uint8)
    xs = np.linspace(0, source_width, target_width + 1).astype(np.int64)
    ys = np.linspace(0, height, target_height + 1).astype(np.int64)
    row_sums = np.add.reduceat(luma, ys[:-1], axis=0)
    cell_sums = np.add.reduceat(row_sums, xs[:-1], axis=1)
    counts = np.outer(np.diff(ys), np.diff(xs)).astype(np.float32)
    return np.clip(cell_sums / counts, 0.0, 255.0).astype(np.uint8)


def _shifted(mask: np.ndarray) -> list[np.ndarray]:
    height, width = mask.shape
    padded = np.pad(mask, 1, mode="constant", constant_values=False)
    return [padded[dy : dy + height, dx : dx + width] for dy in range(3) for dx in range(3)]


def open_mask(mask: np.ndarray) -> np.ndarray:
    """A 3x3 morphological open (erode then dilate) to remove salt noise."""
    binary = np.asarray(mask, dtype=bool)
    if not binary.any():
        return binary.copy()
    eroded = np.logical_and.reduce(_shifted(binary))
    return np.logical_or.reduce(_shifted(eroded))


def _ema(previous: float | None, value: float, dt: float, tau: float) -> float:
    if previous is None:
        return float(value)
    if tau <= 0.0:
        return float(value)
    alpha = 1.0 - math.exp(-max(0.0, dt) / tau)
    return float(previous + alpha * (value - previous))


@dataclass
class MotionFrame:
    """One processed frame: the mask plus the global motion signals."""

    mask: np.ndarray
    energy: float
    x: float
    y: float
    vx: float
    vy: float
    present: float
    dt: float


class MotionModel:
    """Running-background motion at the processing resolution."""

    def __init__(
        self,
        processing_width: int = PROCESSING_WIDTH_DEFAULT,
        threshold: float = THRESHOLD_DEFAULT,
        min_area: float = MIN_AREA_DEFAULT,
        bg_tau_s: float = BG_TAU_DEFAULT,
        mirror: bool = False,
    ) -> None:
        self.processing_width = int(
            clamp(float(processing_width), PROCESSING_WIDTH_MIN, PROCESSING_WIDTH_MAX)
        )
        self.threshold = clamp(float(threshold), THRESHOLD_MIN, THRESHOLD_MAX)
        self.min_area = clamp(float(min_area), MIN_AREA_MIN, MIN_AREA_MAX)
        self.bg_tau_s = clamp(float(bg_tau_s), BG_TAU_MIN, BG_TAU_MAX)
        self.mirror = bool(mirror)
        self.reset()

    def reset(self) -> None:
        """Forget the background and every smoothed value."""
        self._background: np.ndarray | None = None
        self._last_time = 0.0
        self._last_x: float | None = None
        self._last_y: float | None = None
        self._vx = 0.0
        self._vy = 0.0
        self._energy = 0.0

    def step(self, rgb: np.ndarray, now: float) -> MotionFrame:
        """Process one frame at ``now`` (monotonic seconds)."""
        gray = gray_frame(rgb, self.processing_width)
        height, width = gray.shape
        if self._background is None or self._background.shape != gray.shape:
            self._background = gray.astype(np.float32)
            self._last_time = float(now)
            dt = 0.0
            mask = np.zeros_like(gray, dtype=bool)
        else:
            dt = max(0.0, float(now) - self._last_time)
            self._last_time = float(now)
            alpha = clamp(1.0 - math.exp(-dt / self.bg_tau_s), BG_ALPHA_MIN, 1.0)
            self._background += alpha * (gray.astype(np.float32) - self._background)
            difference = np.abs(gray.astype(np.float32) - self._background) > self.threshold
            mask = open_mask(difference)
        present = 1.0 if float(mask.mean()) >= self.min_area else 0.0
        if present == 0.0:
            mask = np.zeros_like(mask, dtype=bool)
        fraction = float(mask.mean())
        self._energy = _ema(self._energy, clamp(fraction / ENERGY_FULL, 0.0, 1.0), dt, ENERGY_TAU_S)
        x, y = self._position(mask, width, height)
        if mask.any() and dt > 0.0 and self._last_x is not None and self._last_y is not None:
            raw_vx = clamp((x - self._last_x) / dt, -VEL_CLAMP, VEL_CLAMP)
            raw_vy = clamp((y - self._last_y) / dt, -VEL_CLAMP, VEL_CLAMP)
        else:
            raw_vx = raw_vy = 0.0
        self._vx = _ema(self._vx, raw_vx, dt, VEL_TAU_S)
        self._vy = _ema(self._vy, raw_vy, dt, VEL_TAU_S)
        self._last_x, self._last_y = x, y
        return MotionFrame(mask, self._energy, x, y, self._vx, self._vy, present, dt)

    def _position(self, mask: np.ndarray, width: int, height: int) -> tuple[float, float]:
        if not mask.any():
            return (self._last_x or 0.0, self._last_y or 0.0)
        ys, xs = np.nonzero(mask)
        x = (float(xs.mean()) + 0.5) / width * 2.0 - 1.0
        y = 1.0 - (float(ys.mean()) + 0.5) / height * 2.0
        if self.mirror:
            x = -x
        return float(clamp(x, -1.0, 1.0)), float(clamp(y, -1.0, 1.0))


# ---------------------------------------------------------------------------
# Per-zone signals
# ---------------------------------------------------------------------------


@dataclass
class _ZoneState:
    energy: float = 0.0
    vx: float = 0.0
    vy: float = 0.0
    x: float = 0.0
    y: float = 0.0
    occupied: bool = False
    enter_s: float = 0.0
    exit_s: float = 0.0
    enter_until: float = -1.0
    exit_until: float = -1.0

    def step(self, now: float, fraction: float, x: float, y: float, dt: float) -> dict[str, float]:
        self.energy = _ema(self.energy, clamp(fraction / ENERGY_FULL, 0.0, 1.0), dt, ENERGY_TAU_S)
        if dt > 0.0:
            self.vx = _ema(self.vx, clamp((x - self.x) / dt, -VEL_CLAMP, VEL_CLAMP), dt, VEL_TAU_S)
            self.vy = _ema(self.vy, clamp((y - self.y) / dt, -VEL_CLAMP, VEL_CLAMP), dt, VEL_TAU_S)
        self.x, self.y = x, y
        self._occupancy(now, fraction, dt)
        return {
            "energy": self.energy,
            "occupancy": 1.0 if self.occupied else 0.0,
            "x": self.x,
            "y": self.y,
            "vx": self.vx,
            "vy": self.vy,
            "enter": 1.0 if now < self.enter_until else 0.0,
            "exit": 1.0 if now < self.exit_until else 0.0,
        }

    def _occupancy(self, now: float, fraction: float, dt: float) -> None:
        if not self.occupied:
            if fraction >= OCCUPANCY_ENTER:
                self.enter_s += dt
                if self.enter_s >= ENTER_HOLD_S:
                    self.occupied = True
                    self.enter_until = now + PULSE_S
                    self.exit_s = 0.0
            else:
                self.enter_s = 0.0
            return
        if fraction <= OCCUPANCY_EXIT:
            self.exit_s += dt
            if self.exit_s >= EXIT_HOLD_S:
                self.occupied = False
                self.exit_until = now + PULSE_S
                self.enter_s = 0.0
        else:
            self.exit_s = 0.0


class ZoneEngine:
    """The pure per-frame engine: zones in, signal snapshot out."""

    def __init__(
        self,
        zones: list[dict[str, Any]] | None = None,
        processing_width: int = PROCESSING_WIDTH_DEFAULT,
        threshold: float = THRESHOLD_DEFAULT,
        min_area: float = MIN_AREA_DEFAULT,
        bg_tau_s: float = BG_TAU_DEFAULT,
        mirror: bool = False,
    ) -> None:
        self.mirror = bool(mirror)
        self.motion = MotionModel(processing_width, threshold, min_area, bg_tau_s, mirror)
        self._zones: list[dict[str, Any]] = []
        self._states: dict[int, _ZoneState] = {}
        self._masks: dict[int, tuple[tuple[Any, ...], np.ndarray]] = {}
        self.set_zones(zones or [])

    def set_zones(self, zones: list[dict[str, Any]]) -> None:
        """Replace the zone list, dropping the state of zones that vanished."""
        self._zones = sanitize_zones(zones)
        live = {zone["id"] for zone in self._zones}
        self._states = {
            zone_id: state for zone_id, state in self._states.items() if zone_id in live
        }
        for zone in self._zones:
            self._states.setdefault(zone["id"], _ZoneState())
        self._masks.clear()

    def reset_activity(self) -> None:
        """Forget the background, occupancy and pulses (a lighting change)."""
        self.motion.reset()
        self._states = {zone["id"]: _ZoneState() for zone in self._zones}

    def step(self, rgb: np.ndarray, now: float) -> dict[str, dict[str, float]]:
        """One frame: the global ``motion`` block plus one block per zone."""
        motion = self.motion.step(rgb, now)
        height, width = motion.mask.shape
        snapshot: dict[str, dict[str, float]] = {
            "motion": {
                "energy": motion.energy,
                "x": motion.x,
                "y": motion.y,
                "vx": motion.vx,
                "vy": motion.vy,
                "present": motion.present,
            }
        }
        for zone in self._zones:
            mask = self._mask_for(zone, width, height)
            state = self._states[zone["id"]]
            area = int(mask.sum())
            fraction = 0.0
            x, y = state.x, state.y
            if area > 0:
                inside = motion.mask & mask
                mass = int(inside.sum())
                fraction = mass / area
                if mass > 0:
                    ys, xs = np.nonzero(inside)
                    x, y = _zone_relative(
                        zone["points"], float(xs.mean()), float(ys.mean()), width, height
                    )
            signals = state.step(now, fraction, x, y, motion.dt)
            if self.mirror:
                signals["x"] = -signals["x"]
                signals["vx"] = -signals["vx"]
            snapshot[f"zone{zone['id']}"] = signals
        return snapshot

    def _mask_for(self, zone: dict[str, Any], width: int, height: int) -> np.ndarray:
        key = (tuple(tuple(point) for point in zone["points"]), width, height)
        cached = self._masks.get(zone["id"])
        if cached is None or cached[0] != key:
            cached = (key, zone_mask(zone["points"], width, height))
            self._masks[zone["id"]] = cached
        return cached[1]


def _zone_relative(
    points: list[list[float]], pixel_x: float, pixel_y: float, width: int, height: int
) -> tuple[float, float]:
    x0, y0, x1, y1 = zone_bounds(points)
    centre_x, centre_y = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    half_width = max((x1 - x0) / 2.0, 1e-6)
    half_height = max((y1 - y0) / 2.0, 1e-6)
    normalized_x = (pixel_x + 0.5) / width
    normalized_y = (pixel_y + 0.5) / height
    x = clamp((normalized_x - centre_x) / half_width, -1.0, 1.0)
    y = clamp(-(normalized_y - centre_y) / half_height, -1.0, 1.0)
    return float(x), float(y)


# ---------------------------------------------------------------------------
# Preview overlay (pure geometry, testable without dpg)
# ---------------------------------------------------------------------------


def draw_overlay(
    rgb: np.ndarray,
    zones: list[dict[str, Any]],
    snapshot: dict[str, dict[str, float]],
    mirror: bool = False,
) -> np.ndarray:
    """Draw zone outlines, names, centroids and energy bars on a copy of ``rgb``."""
    source = np.asarray(rgb, dtype=np.uint8)
    image = Image.fromarray(source.copy(), mode="RGB")
    draw = ImageDraw.Draw(image)
    width, height = image.size
    for zone in zones:
        points = [(p[0] * width, p[1] * height) for p in zone["points"]]
        if len(points) < 2:
            continue
        color = tuple(_heal_color(zone.get("color")))
        draw.line([*points, points[0]], fill=color, width=2)
        signals = snapshot.get(f"zone{zone['id']}", {})
        energy = float(signals.get("energy", 0.0))
        label = f"{zone['name']} {energy:.2f}"
        draw.text((points[0][0] + 4, points[0][1] + 4), label, fill=color)
        bar_width = int(clamp(energy, 0.0, 1.0) * 40)
        if bar_width > 0:
            draw.rectangle(
                [
                    points[0][0] + 4,
                    points[0][1] + 18,
                    points[0][0] + 4 + bar_width,
                    points[0][1] + 22,
                ],
                fill=color,
            )
        if "x" in signals and "y" in signals:
            x0, y0, x1, y1 = zone_bounds(zone["points"])
            centre_x = (x0 + x1) / 2.0 + float(signals["x"]) * (x1 - x0) / 2.0
            centre_y = (y0 + y1) / 2.0 - float(signals["y"]) * (y1 - y0) / 2.0
            if mirror:
                centre_x = x0 + x1 - centre_x
            radius = 3
            draw.ellipse(
                [
                    centre_x * width - radius,
                    centre_y * height - radius,
                    centre_x * width + radius,
                    centre_y * height + radius,
                ],
                fill=color,
            )
    return np.array(image, dtype=np.uint8)


# ---------------------------------------------------------------------------
# Config (boot + persistence). The worker owns the runtime; this is the
# main-thread mirror the window and the tests read.
# ---------------------------------------------------------------------------


def config_block(cfg: dict[str, Any]) -> dict[str, Any]:
    """The writable ``cfg['zones']`` mapping, healed in place."""
    block = cfg.get("zones")
    if not isinstance(block, dict):
        block = {}
        cfg["zones"] = block
    return block


def init_from_config(cfg: dict[str, Any]) -> None:
    """Apply the persisted zone-engine settings to the state mirrors (boot).

    A file that enables both camera engines heals to the hand engine: the
    webcam worker already existed and the operator's last explicit action is
    unknowable from two booleans. The healed value is not rewritten at boot.
    """
    block = cfg.get("zones")
    if not isinstance(block, dict):
        block = {}
    # e90: the enable switch is project content, not config
    block.pop("enabled", None)
    state.zones_device = str(block.get("device") or "")
    state.zones_width = int(
        clamp(float(block.get("width", 320)), CAMERA_WIDTH_MIN, CAMERA_WIDTH_MAX)
    )
    state.zones_height = int(
        clamp(float(block.get("height", 240)), CAMERA_HEIGHT_MIN, CAMERA_HEIGHT_MAX)
    )
    state.zones_processing_width = int(
        clamp(
            float(block.get("processing_width", PROCESSING_WIDTH_DEFAULT)),
            PROCESSING_WIDTH_MIN,
            PROCESSING_WIDTH_MAX,
        )
    )
    state.zones_threshold = clamp(
        float(block.get("threshold", THRESHOLD_DEFAULT)), THRESHOLD_MIN, THRESHOLD_MAX
    )
    state.zones_min_area = clamp(
        float(block.get("min_area", MIN_AREA_DEFAULT)), MIN_AREA_MIN, MIN_AREA_MAX
    )
    state.zones_bg_tau_s = clamp(
        float(block.get("bg_tau_s", BG_TAU_DEFAULT)), BG_TAU_MIN, BG_TAU_MAX
    )
    state.zones_max_hz = clamp(float(block.get("max_hz", MAX_HZ_DEFAULT)), MAX_HZ_MIN, MAX_HZ_MAX)
    state.zones_mirror = bool(block.get("mirror", False))
    state.zones_preview = bool(block.get("preview", False))
    legacy_zones = sanitize_zones(block.get("zones"))
    state.zones_config = legacy_zones
    state.zones_status = "off"
    state.zones_ready = True
    if legacy_zones:
        # e88s06: zones are PROJECT content now. The config may still carry the
        # pre-e88s06 list: load it into this session once and drop it from the
        # config, so the operator can save it into the project.
        _save(lambda zones_block: zones_block.__setitem__("zones", []))
        log_error(
            "Stage zones",
            "legacy config zones loaded: zones are project content now, "
            "save the project to keep them",
        )
    if state.zones_enabled and camera.camera_engine() == camera.CAMERA_HAND:
        state.zones_enabled = False
        log_error("Stage zones", "hand and zones were both enabled: hand wins, zones off")


def _save(mutate: Any) -> bool:
    """Read-modify-write the ``zones`` block; a failed write is logged, not raised."""
    cfg = load_config()
    mutate(config_block(cfg))
    if not save_config(cfg):
        log_error("Stage zones", "settings not persisted - this session only")
        return False
    return True


def set_option(name: str, value: Any) -> None:
    """Persist one camera/motion option (main thread)."""
    if name == "device":
        state.zones_device = str(value or "")
    elif name == "width":
        state.zones_width = int(clamp(float(value), CAMERA_WIDTH_MIN, CAMERA_WIDTH_MAX))
        value = state.zones_width
    elif name == "height":
        state.zones_height = int(clamp(float(value), CAMERA_HEIGHT_MIN, CAMERA_HEIGHT_MAX))
        value = state.zones_height
    elif name == "processing_width":
        state.zones_processing_width = int(
            clamp(float(value), PROCESSING_WIDTH_MIN, PROCESSING_WIDTH_MAX)
        )
        value = state.zones_processing_width
    elif name == "threshold":
        state.zones_threshold = clamp(float(value), THRESHOLD_MIN, THRESHOLD_MAX)
        value = state.zones_threshold
    elif name == "min_area":
        state.zones_min_area = clamp(float(value), MIN_AREA_MIN, MIN_AREA_MAX)
        value = state.zones_min_area
    elif name == "bg_tau_s":
        state.zones_bg_tau_s = clamp(float(value), BG_TAU_MIN, BG_TAU_MAX)
        value = state.zones_bg_tau_s
    elif name == "max_hz":
        state.zones_max_hz = clamp(float(value), MAX_HZ_MIN, MAX_HZ_MAX)
        value = state.zones_max_hz
    elif name == "mirror":
        state.zones_mirror = bool(value)
    elif name == "preview":
        state.zones_preview = bool(value)
    else:
        raise KeyError(name)
    _save(lambda block: block.__setitem__(name, value))


def set_zones(zones: Any) -> list[dict[str, Any]]:
    """Sanitize and mirror the operator's zone list (PROJECT content, e88s06).

    The list is not written to the app config: the project capture carries it
    and the project dirty fingerprint notices the edit. The camera/motion
    options still persist in the config (hardware, not show content).
    """
    healed = sanitize_zones(zones)
    state.zones_config = healed
    return healed


def capture_project_zones() -> list[dict[str, Any]]:
    """A deep copy of the live zone list for the project document (e88s06)."""
    return copy.deepcopy(state.zones_config)


def apply_project_zones(raw: Any) -> list[dict[str, Any]]:
    """Replace the live zones from a project section (missing -> empty, e88s06)."""
    state.zones_config = sanitize_zones(raw)
    state.zones_draft = []
    return state.zones_config


def draw_draft(
    rgb: np.ndarray, points: list[list[float]], color: tuple[int, int, int] = DEFAULT_COLOR
) -> np.ndarray:
    """Draw the in-progress polygon (points + line) on a copy of ``rgb``."""
    source = np.asarray(rgb, dtype=np.uint8)
    image = Image.fromarray(source.copy(), mode="RGB")
    draw = ImageDraw.Draw(image)
    width, height = image.size
    pixels = [(point[0] * width, point[1] * height) for point in points]
    if len(pixels) > 1:
        draw.line(pixels, fill=color, width=2)
    for x, y in pixels:
        draw.ellipse([x - 3, y - 3, x + 3, y + 3], fill=color)
    return np.array(image, dtype=np.uint8)
