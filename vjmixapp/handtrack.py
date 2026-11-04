"""Canonical hand-tracking core (e87): provider catalog, landmark math, gate.

WORKER-SAFE: no dpg, no av, no onnxruntime (HIGH-1). The Leap side of the field
matrix REUSES ``leap.LEAP_FIELDS`` so there is one source of truth for the mm
ranges; this module adds the canonical frame every provider must produce:

    x     -1..+1, +1 = the user's RIGHT   (mirrored: a mirror-camera default)
    y     -1..+1, +1 = UP
    roll  degrees, 0 = fingers up, + = clockwise as the user sees it
    pinch/grab/spread/curl_*  0..1, scale-invariant (divided by the palm length)

Everything here is pure and testable with synthetic landmark arrays: the camera,
the models and the toolkit stay out of this module (specs/HAND_TRACKING_MODES_LATEST.md
§2.3 and §7).
"""

import math
from collections.abc import Sequence
from typing import Any

import numpy as np

from vjmixapp import camera, leap, state
from vjmixapp.config import load_config, save_config
from vjmixapp.queues import log_error

PROVIDER_LEAP = "leap"
PROVIDER_WEBCAM = "webcam"
HAND_PROVIDERS: tuple[str, ...] = (PROVIDER_LEAP, PROVIDER_WEBCAM)
PROVIDER_LABELS: dict[str, str] = {PROVIDER_LEAP: "Leap Motion", PROVIDER_WEBCAM: "Webcam"}
PROVIDER_BADGES: dict[str, str] = {PROVIDER_LEAP: "L", PROVIDER_WEBCAM: "W"}

# Interaction box: the fraction of the frame that is "the instrument". The
# central 60 % is the measured-comfortable zone on a laptop camera (MODES §4);
# the Mapper still rescales with input_from/to, so no calibration is needed.
# The maximum is the whole frame (operator request 2026-10-24: 0.9 left a margin
# the hand could not use, while `in_box` and the preview already treat the box as
# the fraction it is).
BOX_FRACTION_DEFAULT: float = 0.60
BOX_FRACTION_MIN: float = 0.30
BOX_FRACTION_MAX: float = 1.00

# MediaPipe Hand Landmarks (21 points).
WRIST = 0
THUMB_CMC, THUMB_MCP, THUMB_IP, THUMB_TIP = 1, 2, 3, 4
INDEX_MCP, INDEX_PIP, INDEX_DIP, INDEX_TIP = 5, 6, 7, 8
MIDDLE_MCP, MIDDLE_PIP, MIDDLE_DIP, MIDDLE_TIP = 9, 10, 11, 12
RING_MCP, RING_PIP, RING_DIP, RING_TIP = 13, 14, 15, 16
PINKY_MCP, PINKY_PIP, PINKY_DIP, PINKY_TIP = 17, 18, 19, 20
LANDMARK_COUNT = 21
PALM_POINTS: tuple[int, ...] = (WRIST, INDEX_MCP, MIDDLE_MCP, RING_MCP, PINKY_MCP)
FINGERS: tuple[str, ...] = ("thumb", "index", "middle", "ring", "pinky")
FINGER_MCP: dict[str, int] = {
    "thumb": THUMB_MCP,
    "index": INDEX_MCP,
    "middle": MIDDLE_MCP,
    "ring": RING_MCP,
    "pinky": PINKY_MCP,
}
FINGER_TIP: dict[str, int] = {
    "thumb": THUMB_TIP,
    "index": INDEX_TIP,
    "middle": MIDDLE_TIP,
    "ring": RING_TIP,
    "pinky": PINKY_TIP,
}
FINGERTIPS: tuple[int, ...] = (THUMB_TIP, INDEX_TIP, MIDDLE_TIP, RING_TIP, PINKY_TIP)

GEOM_EPS = 1e-6
# Pinch: thumb-tip to index-tip distance divided by the palm length. Measured
# ranges on the frontal rig: ~0.2 fully pinched, ~1.4+ wide open.
PINCH_TIGHT = 0.25
PINCH_OPEN = 1.10
# Curl: tip-to-wrist over mcp-to-wrist. Extended ~1.8-2.2, closed ~0.9-1.1.
CURL_OPEN = 1.85
CURL_CLOSED = 0.95
CURL_FIST = 0.75  # the gate's "closed fist" threshold on the mean curl
# Spread: mean pairwise fingertip distance over the palm length.
SPREAD_MIN = 0.80
SPREAD_MAX = 1.60
# Palm facing the camera: palm WIDTH (index MCP to pinky MCP) over its LENGTH
# (wrist to middle MCP). Edge-on collapses toward 0.25, flat toward 0.85+ (MODES §3).
FACING_MIN = 0.28
FACING_FULL = 0.85
VEL_CLAMP = 8.0  # normalized units per second
VEL_TAU_S = 0.03
ROLL_LIMIT = 180.0

# Engagement gate (MODES §6): arm on an open palm facing the camera, stay while
# the hand is inside the box, disarm on leaving it / a fist / tracking loss.
ARM_HOLD_S = 0.30
ARM_FACING = 0.45
DISARM_OUT_S = 0.50
DISARM_FIST_S = 0.30
DISARM_LOSS_S = 1.00

# Handedness (BUG-2026-10-23T213000, re-measured 2026-10-24): MediaPipe labels a
# hand by its VISUAL chirality, so a right hand with the BACK to the camera reads
# as a left hand. The model's own `right`/`left` label and any 2D/3D palm normal
# derived from its landmarks carry the SAME bit (measured on a saved frame: the
# normal z is -0.595 for the right palm and +0.598 for the same frame mirrored),
# so palm-vs-back is NOT recoverable from one view — the name is kept by
# continuity instead (SideStabilizer, SIDE_RELOCK_S).
SIDE_RELOCK_S = 1.0  # a hand absent this long may be a DIFFERENT hand: re-name it

# The signal monitor (operator request 2026-10-24): one COLUMN per hand, like the
# Leap window, so narrowing the window never hides the other hand's signals. The
# seven signals are the ones the operator reads while performing; a hand that is
# absent keeps its rows with the placeholder so the two columns stay comparable
# row by row.
MONITOR_HANDS: tuple[str, ...] = ("left", "right")
MONITOR_FIELDS: tuple[str, ...] = (
    "palm_x",
    "palm_y",
    "roll",
    "pinch",
    "grab",
    "spread",
    "engaged",
)
MONITOR_PLACEHOLDER = "-"

# Pose rules (s05): a pose must be held before it asserts, and cannot re-assert
# inside the cooldown, so one flickering frame cannot machine-gun a trigger.
POSE_EXTENDED = 0.35  # curl at or below this reads "extended"
POSE_CURLED = 0.55  # curl at or above this reads "curled"
POSE_SPREAD_OPEN = 0.45
POSE_HOLD_S = 0.15
POSE_RELEASE_S = 0.10
POSE_COOLDOWN_S = 0.30
POSE_NAMES: tuple[str, ...] = ("open", "fist", "point", "victory", "thumbs")

# Preview geometry (s04): the box border and the cursor are drawn in numpy so
# the geometry is testable without dpg and the worker never touches the toolkit.
PREVIEW_HZ = 20.0
PREVIEW_COLOR_ENGAGED: tuple[int, int, int] = (80, 255, 80)
PREVIEW_COLOR_IDLE: tuple[int, int, int] = (200, 200, 200)
PREVIEW_BORDER = 1
PREVIEW_CURSOR_RADIUS = 3


# ---------------------------------------------------------------------------
# The field matrix: one entry per canonical signal, availability + default range
# per provider. The Leap side is copied from the Leap catalog (same names, same
# ranges) and the webcam side carries the normalized ranges of a frontal camera.
# ---------------------------------------------------------------------------
WEBCAM_FIELDS: dict[str, dict[str, Any]] = {
    "palm_x": {"label": "Palm X", "decimals": 2, "input_from": -1.0, "input_to": 1.0},
    "palm_y": {"label": "Palm Y", "decimals": 2, "input_from": -1.0, "input_to": 1.0},
    "vel_x": {
        "label": "Velocity X",
        "short": "Vel. X",
        "suffix": "/s",
        "decimals": 1,
        "input_from": -VEL_CLAMP,
        "input_to": VEL_CLAMP,
    },
    "vel_y": {
        "label": "Velocity Y",
        "short": "Vel. Y",
        "suffix": "/s",
        "decimals": 1,
        "input_from": -VEL_CLAMP,
        "input_to": VEL_CLAMP,
    },
    "pinch": {"label": "Pinch", "decimals": 2, "input_from": 0.0, "input_to": 1.0},
    "grab": {"label": "Grab", "decimals": 2, "input_from": 0.0, "input_to": 1.0},
    "spread": {"label": "Spread", "decimals": 2, "input_from": 0.0, "input_to": 1.0},
    "roll": {
        "label": "Hand roll",
        "suffix": "°",
        "decimals": 0,
        "input_from": -90.0,
        "input_to": 90.0,
    },
    "palm_facing": {"label": "Palm facing", "decimals": 2, "input_from": 0.0, "input_to": 1.0},
    "conf": {"label": "Confidence", "decimals": 2, "input_from": 0.0, "input_to": 1.0},
    "present": {"label": "Present", "decimals": 0, "input_from": 0.0, "input_to": 1.0},
    "engaged": {"label": "Engaged", "decimals": 0, "input_from": 0.0, "input_to": 1.0},
}
for _finger in FINGERS:
    WEBCAM_FIELDS[f"curl_{_finger}"] = {
        "label": f"{_finger.title()} curl",
        "decimals": 2,
        "input_from": 0.0,
        "input_to": 1.0,
    }
for _pose in POSE_NAMES:
    WEBCAM_FIELDS[f"gesture_{_pose}"] = {
        "label": f"Gesture {_pose}",
        "decimals": 0,
        "input_from": 0.0,
        "input_to": 1.0,
    }


def _build_fields() -> dict[str, dict[str, Any]]:
    fields: dict[str, dict[str, Any]] = {}
    for name in leap.bindable_signals():
        meta = leap.leap_field(name)
        entry = fields.setdefault(
            name,
            {
                "label": meta["label"],
                "decimals": meta.get("decimals", 1),
                "suffix": meta.get("suffix", ""),
                "providers": {},
            },
        )
        entry["providers"][PROVIDER_LEAP] = {
            "bindable": True,
            "input_from": float(meta["input_from"]),
            "input_to": float(meta["input_to"]),
            "decimals": int(meta.get("decimals", 1)),
        }
    for name, meta in WEBCAM_FIELDS.items():
        entry = fields.setdefault(
            name,
            {
                "label": meta["label"],
                "decimals": meta["decimals"],
                "suffix": meta.get("suffix", ""),
                "providers": {},
            },
        )
        entry["providers"][PROVIDER_WEBCAM] = {
            "bindable": True,
            "input_from": float(meta["input_from"]),
            "input_to": float(meta["input_to"]),
            "decimals": int(meta["decimals"]),
        }
    return fields


HAND_FIELDS: dict[str, dict[str, Any]] = _build_fields()
WEBCAM_SIGNALS: tuple[str, ...] = tuple(WEBCAM_FIELDS)


def bindable_signals(provider: str) -> tuple[str, ...]:
    """The signals that provider can actually produce, in catalog order."""
    return tuple(name for name, meta in HAND_FIELDS.items() if provider in meta["providers"])


def signal_default_range(field: str, provider: str) -> tuple[float, float] | None:
    """The default input range of ``field`` for ``provider`` (None if not provided)."""
    entry = HAND_FIELDS.get(field, {}).get("providers", {}).get(provider)
    if entry is None:
        return None
    return (float(entry["input_from"]), float(entry["input_to"]))


def field_label(field: str) -> str:
    """Human label of a canonical field (shared by both providers when present)."""
    return str(HAND_FIELDS.get(field, {}).get("label", field))


def field_decimals(field: str, provider: str | None = None) -> int:
    """Display decimals of a canonical field (the provider's, when given).

    Shared fields carry different scales per engine (palm_x is millimetres on the
    Leap, normalized on the webcam), so the monitor shows each with its own
    precision (e87s04).
    """
    entry = HAND_FIELDS.get(field, {})
    if provider is not None:
        per_provider = entry.get("providers", {}).get(provider, {})
        if "decimals" in per_provider:
            return int(per_provider["decimals"])
    return int(entry.get("decimals", 2))


def monotonic_columns(provider: str) -> tuple[tuple[str, ...], ...]:
    """The monitor columns (four fields each, matching the Leap window's shape)."""
    signals = [s for s in bindable_signals(provider) if not s.startswith("gesture_")]
    columns: list[tuple[str, ...]] = []
    for start in range(0, len(signals), 4):
        columns.append(tuple(signals[start : start + 4]))
    return tuple(columns)


def binding_parts(key: str) -> tuple[str, str] | None:
    """Split ``'<hand>.<field>'`` into (hand, field); None when malformed.

    The FIELD is validated against the canonical matrix, not the Leap catalog:
    the webcam owns fields the device does not (roll, spread, palm_facing, the
    gestures), and a mapping of that provider must still resolve (e87s04).
    """
    if key.count(".") == 1:
        hand, field = key.split(".")
        if hand in leap.LEAP_HANDS and field in HAND_FIELDS:
            return hand, field
    return None


def binding_key(hand: str, field: str) -> str:
    """The snapshot key of one field of one hand (``'left.pinch'``)."""
    return f"{hand}.{field}"


def binding_label(key: str, provider: str = PROVIDER_LEAP) -> str:
    """Readable label of a bound signal, e.g. ``Left · Pinch (Webcam)``."""
    parts = binding_parts(key)
    if parts is None:
        return key
    label = field_label(parts[1])
    return f"{parts[0].title()} · {label} ({PROVIDER_LABELS.get(provider, provider)})"


class SideStabilizer:
    """The physical hand name, kept while the hand stays in view.

    BUG-2026-10-23T213000: MediaPipe labels a hand by what it LOOKS like, so the
    same right hand reads "left" as soon as its back faces the camera — and no
    single-view signal can tell those two apart (measured: the landmark palm
    normal is the same chirality bit, and a back-facing hand passes the
    palm_facing test exactly like a flat palm does). Renaming the hand
    mid-performance would move every mapping to the other prefix, so the name is
    locked while the hand is CONTINUOUSLY in view.

    BUG-2026-10-24T010500: the lock used to re-open on any "palm-facing" frame,
    i.e. on every frame — the name flipped as soon as the operator turned the
    hand. The evidence that a DIFFERENT hand arrived is the hand having LEFT:
    only a gap of SIDE_RELOCK_S in the detections lets a new name take over.
    """

    def __init__(self, relock_s: float = SIDE_RELOCK_S) -> None:
        self.side: str | None = None
        self.relock_s = relock_s
        self._last_seen: float | None = None

    def update(self, side: str, now: float) -> str:
        """The name to publish: the locked one unless the hand has been away."""
        if self.side is None or self._last_seen is None or now - self._last_seen >= self.relock_s:
            self.side = side
        self._last_seen = now
        return self.side

    def reset(self) -> None:
        self.side = None
        self._last_seen = None


def clamp(value: float, low: float, high: float) -> float:
    """Clamp ``value`` into ``[low, high]`` (``high < low`` returns ``low``)."""
    return min(max(value, low), high) if high >= low else low


def ema(prev: float | None, value: float, dt: float, tau: float) -> float:
    """Exponential smoothing; a missing/zero time step passes the value through."""
    if prev is None or not math.isfinite(prev) or dt <= 0.0 or tau <= 0.0:
        return float(value)
    alpha = 1.0 - math.exp(-dt / tau)
    return float(prev) + alpha * (float(value) - float(prev))


def _dist(a: np.ndarray, b: np.ndarray) -> float:
    return float(math.hypot(*(a - b)))


def box_half_extent(fraction: float = BOX_FRACTION_DEFAULT) -> tuple[float, float]:
    """Half width/height (in normalized frame units) of the interaction box."""
    clamped = clamp(float(fraction), BOX_FRACTION_MIN, BOX_FRACTION_MAX)
    return clamped / 2.0, clamped / 2.0


def normalize_landmarks(
    landmarks: Sequence[Sequence[float]] | np.ndarray,
    *,
    box: tuple[float, float] = (0.30, 0.30),
    mirror: bool = True,
    conf: float = 1.0,
    prev: dict[str, float] | None = None,
    dt: float = 0.0,
) -> dict[str, float]:
    """Turn one hand's 21 landmarks (normalized frame coords) into the canonical fields.

    ``landmarks`` is the MediaPipe 21x3 array in FRAME-normalized ``[0,1]``
    coordinates (x right, y down); ``box`` is the half width/height of the
    interaction box. Output keys are the canonical fields WITHOUT the hand
    prefix — the worker adds it.
    """
    lm = np.asarray(landmarks, dtype=float)
    if lm.ndim != 2 or lm.shape[0] < LANDMARK_COUNT:
        raise ValueError(f"expected {LANDMARK_COUNT} landmarks, got {lm.shape}")
    xy = lm[:LANDMARK_COUNT, :2]
    half_w, half_h = box

    centre = xy[list(PALM_POINTS)].mean(axis=0)
    x = (float(centre[0]) - 0.5) / max(half_w, GEOM_EPS)
    y = -(float(centre[1]) - 0.5) / max(half_h, GEOM_EPS)
    if mirror:
        x = -x

    wrist = xy[WRIST]
    palm_len = _dist(xy[MIDDLE_MCP], wrist)
    palm_width = _dist(xy[INDEX_MCP], xy[PINKY_MCP])
    hand_size = max(palm_len, palm_width, GEOM_EPS)

    pinch_ratio = _dist(xy[THUMB_TIP], xy[INDEX_TIP]) / hand_size
    pinch = 1.0 - clamp((pinch_ratio - PINCH_TIGHT) / (PINCH_OPEN - PINCH_TIGHT), 0.0, 1.0)

    curls = {}
    for finger in FINGERS:
        to_tip = _dist(xy[FINGER_TIP[finger]], wrist)
        to_mcp = _dist(xy[FINGER_MCP[finger]], wrist)
        ratio = to_tip / max(to_mcp, GEOM_EPS)
        curls[f"curl_{finger}"] = clamp((CURL_OPEN - ratio) / (CURL_OPEN - CURL_CLOSED), 0.0, 1.0)
    grab = sum(curls.values()) / len(curls)

    tips = [xy[i] for i in FINGERTIPS]
    pairs = [_dist(tips[i], tips[j]) for i in range(len(tips)) for j in range(i + 1, len(tips))]
    spread_raw = (sum(pairs) / len(pairs)) / hand_size
    spread = clamp((spread_raw - SPREAD_MIN) / (SPREAD_MAX - SPREAD_MIN), 0.0, 1.0)

    facing = clamp(
        (palm_width / max(palm_len, GEOM_EPS) - FACING_MIN) / (FACING_FULL - FACING_MIN), 0.0, 1.0
    )

    axis = xy[MIDDLE_MCP] - wrist
    dx = float(axis[0])
    dy = -float(axis[1])
    if mirror:
        dx = -dx
    roll = math.degrees(math.atan2(dx, dy))

    out: dict[str, float] = {
        "palm_x": x,
        "palm_y": y,
        "roll": roll,
        "pinch": pinch,
        "grab": grab,
        "spread": spread,
        "palm_facing": facing,
        "present": 1.0,
        "conf": float(clamp(conf, 0.0, 1.0)),
        **curls,
    }
    prev = prev or {}
    prev_x, prev_y = prev.get("palm_x"), prev.get("palm_y")
    vx = (x - prev_x) / dt if prev_x is not None and dt > 0.0 else 0.0
    vy = (y - prev_y) / dt if prev_y is not None and dt > 0.0 else 0.0
    out["vel_x"] = clamp(ema(prev.get("vel_x"), vx, dt, VEL_TAU_S), -VEL_CLAMP, VEL_CLAMP)
    out["vel_y"] = clamp(ema(prev.get("vel_y"), vy, dt, VEL_TAU_S), -VEL_CLAMP, VEL_CLAMP)
    return out


def in_box(x: float, y: float) -> bool:
    """Is the canonical position inside the interaction box?"""
    return abs(float(x)) <= 1.0 and abs(float(y)) <= 1.0


class EngagementGate:
    """Arm / stay / disarm state machine (pure; the clock is passed in).

    MODES §6: a frontal camera always sees the hands, so "the hand is in frame"
    is not intent. The gate arms on an open palm FACING the camera held for
    ARM_HOLD_S, stays engaged while the hand is in the box, and disarms on
    leaving the box, on a closed fist, or on tracking loss. The driver HOLDS the
    last value while disarmed — it never zeroes a mapping.
    """

    def __init__(self) -> None:
        self.engaged = False
        self.reason = "idle"
        self._arm_since: float | None = None
        self._out_since: float | None = None
        self._fist_since: float | None = None
        self._loss_since: float | None = None

    def reset(self) -> None:
        """Forget everything (engine off, provider switch)."""
        self.engaged = False
        self.reason = "idle"
        self._arm_since = None
        self._out_since = None
        self._fist_since = None
        self._loss_since = None

    def _disarm(self, reason: str) -> None:
        self.engaged = False
        self.reason = reason
        self._arm_since = None
        self._out_since = None
        self._fist_since = None
        self._loss_since = None

    def step(
        self, now: float, *, present: bool, inside: bool, palm_facing: float, fist: bool
    ) -> tuple[bool, str]:
        """Advance the gate; returns ``(engaged, reason)``."""
        if not present:
            self._arm_since = None
            self._out_since = None
            self._fist_since = None
            if self.engaged:
                self._loss_since = self._loss_since if self._loss_since is not None else now
                if now - self._loss_since >= DISARM_LOSS_S:
                    self._disarm("lost")
                else:
                    self.reason = "losing"
            else:
                self.reason = "no-hand"
            return self.engaged, self.reason

        self._loss_since = None
        if not self.engaged:
            self._out_since = None
            self._fist_since = None
            if inside and palm_facing >= ARM_FACING:
                self._arm_since = self._arm_since if self._arm_since is not None else now
                if now - self._arm_since >= ARM_HOLD_S:
                    self.engaged = True
                    self.reason = "armed"
                    self._arm_since = None
                else:
                    self.reason = "arming"
            else:
                self._arm_since = None
                self.reason = "idle"
            return self.engaged, self.reason

        self._out_since = (
            None if inside else (self._out_since if self._out_since is not None else now)
        )
        self._fist_since = (
            (self._fist_since if self._fist_since is not None else now) if fist else None
        )
        if self._out_since is not None and now - self._out_since >= DISARM_OUT_S:
            self._disarm("out")
        elif self._fist_since is not None and now - self._fist_since >= DISARM_FIST_S:
            self._disarm("fist")
        else:
            self.reason = "engaged"
        return self.engaged, self.reason


# ---------------------------------------------------------------------------
# Pose commands (e87s05): five threshold rules over the canonical features, and
# a temporal tracker so one flickering frame cannot machine-gun a trigger.
# ---------------------------------------------------------------------------


def thumb_above_wrist(landmarks: Any) -> float:
    """1.0 when the thumb tip sits above the wrist in canonical y (0.0 else).

    Canonical y points UP (normalize_landmarks negates the frame y), so "above"
    is simply a smaller frame y on both landmarks (e87s05).

    Missing/short landmarks degrade to 0.0: the thumbs rule then cannot win.
    """
    if landmarks is None:
        return 0.0
    xy = np.asarray(landmarks, dtype=float)
    if xy.ndim != 2 or xy.shape[0] < LANDMARK_COUNT:
        return 0.0
    return 1.0 if float(xy[THUMB_TIP, 1]) < float(xy[WRIST, 1]) else 0.0


def _is_extended(features: dict[str, float], finger: str) -> bool:
    """Is this finger extended? (the dead band is NOT extended: no pose wins)."""
    return float(features.get(f"curl_{finger}", 1.0)) <= POSE_EXTENDED


def _is_curled(features: dict[str, float], finger: str) -> bool:
    """Is this finger curled? (the dead band is NOT curled either)."""
    return float(features.get(f"curl_{finger}", 0.0)) >= POSE_CURLED


def classify_pose(features: dict[str, float]) -> str | None:
    """The pose of ONE frame, or None (mixed fingers, dead band, between poses).

    Evaluated in a fixed order so two poses never win together. ``thumb_high``
    is the canonical "thumb tip above the wrist" bit (see thumb_above_wrist).
    """
    extended = {finger: _is_extended(features, finger) for finger in FINGERS}
    curled = {finger: _is_curled(features, finger) for finger in FINGERS}
    if all(curled.values()):
        return "fist"
    if all(extended.values()) and float(features.get("spread", 0.0)) >= POSE_SPREAD_OPEN:
        return "open"
    if extended["index"] and curled["middle"] and curled["ring"] and curled["pinky"]:
        return "point"
    if extended["index"] and extended["middle"] and curled["ring"] and curled["pinky"]:
        return "victory"
    if (
        extended["thumb"]
        and curled["index"]
        and curled["middle"]
        and curled["ring"]
        and curled["pinky"]
        and float(features.get("thumb_high", 0.0)) >= 0.5
    ):
        return "thumbs"
    return None


class PoseTracker:
    """Hold / release / cooldown state machine (pure; the clock is passed in).

    A pose must be held POSE_HOLD_S before it asserts; the active pose is
    released only after POSE_RELEASE_S of a DIFFERENT pose (or of None), and the
    same pose cannot re-assert before POSE_COOLDOWN_S — so a flicker is ignored
    and one clench fires one press. One pose is 1 at a time.
    """

    def __init__(self) -> None:
        self._candidate: str | None = None
        self._candidate_since: float = 0.0
        self._active: str | None = None
        self._cooldown_until: dict[str, float] = {}

    def reset(self) -> None:
        """Forget the pose history (engine off, provider switch)."""
        self._candidate = None
        self._candidate_since = 0.0
        self._active = None
        self._cooldown_until.clear()

    def step(self, now: float, pose: str | None) -> dict[str, float]:
        """Advance one frame; returns the five 0/1 gesture signals."""
        if pose != self._candidate:
            self._candidate = pose
            self._candidate_since = now

        if (
            self._active is not None
            and pose != self._active
            and now - self._candidate_since >= POSE_RELEASE_S
        ):
            self._cooldown_until[self._active] = now + POSE_COOLDOWN_S
            self._active = None

        if self._active is None and pose is not None:
            held = now - self._candidate_since
            if held >= POSE_HOLD_S and now >= self._cooldown_until.get(pose, 0.0):
                self._active = pose

        return {f"gesture_{name}": 1.0 if name == self._active else 0.0 for name in POSE_NAMES}


def draw_preview(
    frame_rgb: np.ndarray,
    x: float | None,
    y: float | None,
    *,
    box_fraction: float = BOX_FRACTION_DEFAULT,
    mirror: bool = True,
    engaged: bool = False,
) -> np.ndarray:
    """Draw the interaction box and the palm cursor on a preview frame (numpy only).

    ``x``/``y`` are CANONICAL coordinates (-1..1, ``x`` = the user's right); the
    frame is flipped horizontally first when ``mirror`` is on, so the panel reads
    like a mirror and ``x`` maps straight into it. ``None`` means "no hand in
    this frame": the box is still drawn, the cursor is not. Returns a uint8 RGB
    copy.
    """
    source = np.array(frame_rgb, dtype=np.uint8, copy=True)
    # BUG-2026-10-24T003000: the frame was never flipped (only the cursor was
    # moved), so the Mirror switch changed nothing on screen and the cursor of a
    # mirrored panel landed on the wrong side.
    frame = np.ascontiguousarray(source[:, ::-1]) if mirror else source
    height, width = frame.shape[:2]
    colour = PREVIEW_COLOR_ENGAGED if engaged else PREVIEW_COLOR_IDLE
    half_w, half_h = box_half_extent(box_fraction)
    x0 = round((0.5 - half_w) * width)
    x1 = round((0.5 + half_w) * width) - 1
    y0 = round((0.5 - half_h) * height)
    y1 = round((0.5 + half_h) * height) - 1
    x0, x1 = max(0, min(x0, width - 1)), max(0, min(x1, width - 1))
    y0, y1 = max(0, min(y0, height - 1)), max(0, min(y1, height - 1))
    b = PREVIEW_BORDER
    frame[y0 : y0 + b, x0 : x1 + 1] = colour
    frame[y1 - b + 1 : y1 + 1, x0 : x1 + 1] = colour
    frame[y0 : y1 + 1, x0 : x0 + b] = colour
    frame[y0 : y1 + 1, x1 - b + 1 : x1 + 1] = colour

    if x is None or y is None:
        return frame
    # The canonical x already carries the hand's side: +1 is the user's right,
    # which is the RIGHT half of a mirrored panel. One mapping for both modes —
    # in the raw image a non-mirrored x is what normalize_landmarks produced.
    cx = round((0.5 + float(x) * half_w) * width)
    cy = round((0.5 - y * half_h) * height)
    r = PREVIEW_CURSOR_RADIUS
    frame[max(0, cy - r) : min(height, cy + r + 1), max(0, cx - r) : min(width, cx + r + 1)] = (
        colour
    )
    return frame


# ---------------------------------------------------------------------------
# Config + state mirrors (main thread; the worker only READS state)
# ---------------------------------------------------------------------------

MAX_HZ_MIN = 5.0
MAX_HZ_MAX = 20.0
STATUS_LABELS: dict[str, str] = {
    "off": "Disabled",
    "missing-deps": "onnxruntime / models missing",
    "stalled": "camera not responding (unplug/replug it)",
    "no-camera": "No camera",
    "lost": "Camera lost — retrying",
    "searching": "No hand in view",
    "tracking": "Tracking",
    # e90s02: the host states of the supervised child (the same window).
    "starting": "Tracker starting",
    "offline": "Tracker process offline",
    "mismatch": "Tracker protocol mismatch",
}


def config_block(cfg: dict[str, Any]) -> dict[str, Any]:
    """The writable ``cfg['handtrack']`` mapping, healed in place (like leap)."""
    block = cfg.get("handtrack")
    if not isinstance(block, dict):
        block = {}
        cfg["handtrack"] = block
    return block


def handtrack_init_from_config(cfg: dict[str, Any]) -> None:
    """Apply the persisted hand-engine settings to the state mirrors (boot)."""
    block = cfg.get("handtrack")
    if not isinstance(block, dict):
        block = {}
    provider = str(block.get("provider") or PROVIDER_LEAP)
    state.hand_provider = provider if provider in HAND_PROVIDERS else PROVIDER_LEAP
    # e90: the enable switch is project content (specs/TRACKING_PERSISTENCE_LATEST.md).
    # A legacy key is ignored here and dropped on the next save.
    block.pop("enabled", None)
    state.handtrack_device = str(block.get("device") or "")
    state.handtrack_mirror = bool(block.get("mirror", True))
    state.handtrack_box = clamp(
        float(block.get("box", BOX_FRACTION_DEFAULT)), BOX_FRACTION_MIN, BOX_FRACTION_MAX
    )
    state.handtrack_max_hz = clamp(float(block.get("max_hz", 12.0)), MAX_HZ_MIN, MAX_HZ_MAX)
    state.handtrack_preview = bool(block.get("preview", False))
    state.handtrack_status = "off"
    state.handtrack_ready = True


def _save(mutate: Any) -> bool:
    """Read-modify-write the handtrack block; a failed write is logged, not raised."""
    cfg = load_config()
    mutate(config_block(cfg))
    if not save_config(cfg):
        log_error("Hand tracking", "settings not persisted — this session only")
        return False
    return True


def set_handtrack_enabled(enabled: bool) -> None:
    """Enable/disable the WEBCAM engine through the one camera-owner policy.

    Enabling the hand clears the zones engine; disabling it leaves a running
    zones engine alone (the Leap provider switch calls this path and must not
    kill the zones camera, e88s02).
    """
    state.handtrack_enabled = bool(enabled)
    if not enabled:
        state.handtrack_status = "off"
    if enabled:
        camera.set_camera_engine(camera.CAMERA_HAND)
    else:
        target = camera.CAMERA_ZONES if state.zones_enabled else camera.CAMERA_NONE
        camera.set_camera_engine(target)


def set_handtrack_option(name: str, value: Any) -> None:
    """Persist one camera option (device / mirror / box / max_hz / preview)."""
    if name == "device":
        state.handtrack_device = str(value or "")
    elif name == "mirror":
        state.handtrack_mirror = bool(value)
    elif name == "box":
        state.handtrack_box = clamp(float(value), BOX_FRACTION_MIN, BOX_FRACTION_MAX)
        value = state.handtrack_box
    elif name == "max_hz":
        state.handtrack_max_hz = clamp(float(value), MAX_HZ_MIN, MAX_HZ_MAX)
        value = state.handtrack_max_hz
    elif name == "preview":
        state.handtrack_preview = bool(value)
    else:
        raise KeyError(name)
    _save(lambda block: block.__setitem__(name, value))


def set_hand_provider(provider: str) -> None:
    """Select the ACTIVE engine and turn the other one OFF (one engine at a time).

    Switching to the webcam disables the Leap (its persisted flag too); switching
    back to the Leap disables the webcam. The operator asked for exactly one
    engine: two producers writing the same snapshot would fight over every
    mapping (specs/HAND_TRACKING_MODES_LATEST.md §4).
    """
    if provider not in HAND_PROVIDERS:
        return
    state.hand_provider = provider
    _save(lambda block: block.__setitem__("provider", provider))
    if provider == PROVIDER_WEBCAM:
        if state.leap_enabled:
            leap.set_leap_enabled(False)
    else:
        if state.handtrack_enabled:
            set_handtrack_enabled(False)


def engine_active() -> bool:
    """Is the webcam engine supposed to run right now?"""
    return state.handtrack_enabled and state.hand_provider == PROVIDER_WEBCAM


def status_label() -> str:
    """The one-line status of the active engine (window + Logs)."""
    if state.hand_provider == PROVIDER_LEAP:
        return str(state.leap_status)
    label = STATUS_LABELS.get(state.handtrack_status, state.handtrack_status)
    if state.handtrack_status == "tracking":
        return f"{label} · {state.handtrack_fps:.0f} fps"
    return label


def provider_badge(mapping: dict[str, Any]) -> str:
    """The card badge of a mapping's hand source (``L`` / ``W``); empty otherwise."""
    if not mapping.get("leap"):
        return ""
    provider = str(mapping.get("hand_provider") or PROVIDER_LEAP)
    return PROVIDER_BADGES.get(provider, "")
