"""Pure body-tracking core (e89s02): canonical frame, tracker slots, poses.

WORKER-SAFE: no dpg, no av, no onnxruntime. The adapter (`bodyio.py`) supplies
33 MediaPipe landmarks in FRAME PIXELS; this module normalizes, tracks, derives
the five body poses and draws the skeleton overlay.

Canonical frame (stage camera, no mirror by default):

    x  -1..+1, +1 = the right of the image
    y  -1..+1, +1 = up
    height  0..1, apparent head-to-ankle size (a distance proxy, not metres)

Slots: the tracker publishes body1..bodyN ordered by track id (body1 = the
oldest live track), so a mapping survives a performer leaving and another
entering. IDs can swap when two performers cross; that is accepted and stated.
"""

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from PIL import Image, ImageDraw

BODY_MAX = 3
BODY_DEFAULT = 2
VEL_CLAMP = 4.0
VEL_TAU_S = 0.20
TRACK_MATCH_RADIUS = 0.25
TRACK_GAP_S = 2.0
POSE_HOLD_S = 0.15
POSE_RELEASE_S = 0.10
POSE_COOLDOWN_S = 0.30
POSE_NAMES: tuple[str, ...] = ("arms_up", "t_pose", "point", "clap", "crouch")
SLOT_COLORS: tuple[tuple[int, int, int], ...] = (
    (255, 180, 60),
    (80, 220, 255),
    (255, 120, 200),
)

# MediaPipe pose landmarks (33).
NOSE = 0
L_SHOULDER, R_SHOULDER = 11, 12
L_ELBOW, R_ELBOW = 13, 14
L_WRIST, R_WRIST = 15, 16
L_HIP, R_HIP = 23, 24
L_KNEE, R_KNEE = 25, 26
L_ANKLE, R_ANKLE = 27, 28

BODY_EDGES: tuple[tuple[int, int], ...] = (
    (0, 1),
    (1, 2),
    (2, 3),
    (3, 7),
    (0, 4),
    (4, 5),
    (5, 6),
    (6, 8),
    (9, 10),
    (11, 12),
    (11, 13),
    (13, 15),
    (15, 17),
    (15, 19),
    (15, 21),
    (17, 19),
    (12, 14),
    (14, 16),
    (16, 18),
    (16, 20),
    (16, 22),
    (18, 20),
    (11, 23),
    (12, 24),
    (23, 24),
    (23, 25),
    (24, 26),
    (25, 27),
    (26, 28),
    (27, 29),
    (28, 30),
    (29, 31),
    (30, 32),
    (27, 31),
    (28, 32),
)

BODY_FIELDS: dict[str, dict[str, Any]] = {
    "x": {"label": "Position X", "decimals": 2, "input_from": -1.0, "input_to": 1.0},
    "y": {"label": "Position Y", "decimals": 2, "input_from": -1.0, "input_to": 1.0},
    "vel_x": {
        "label": "Velocity X",
        "decimals": 2,
        "input_from": -VEL_CLAMP,
        "input_to": VEL_CLAMP,
    },
    "vel_y": {
        "label": "Velocity Y",
        "decimals": 2,
        "input_from": -VEL_CLAMP,
        "input_to": VEL_CLAMP,
    },
    "height": {"label": "Height", "decimals": 2, "input_from": 0.0, "input_to": 1.0},
    "conf": {"label": "Confidence", "decimals": 2, "input_from": 0.0, "input_to": 1.0},
    "present": {"label": "Present", "decimals": 0, "input_from": 0.0, "input_to": 1.0},
}
for _pose in POSE_NAMES:
    BODY_FIELDS[f"pose_{_pose}"] = {
        "label": f"Pose {_pose}",
        "decimals": 0,
        "input_from": 0.0,
        "input_to": 1.0,
    }
BODY_SIGNALS: tuple[str, ...] = tuple(BODY_FIELDS)


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def body_signal_range(signal: str) -> tuple[float, float]:
    entry = BODY_FIELDS[signal]
    return float(entry["input_from"]), float(entry["input_to"])


def body_signal_label(signal: str) -> str:
    return str(BODY_FIELDS[signal]["label"])


def _ema(previous: float | None, value: float, dt: float, tau: float) -> float:
    if previous is None or tau <= 0.0:
        return float(value)
    alpha = 1.0 - math.exp(-max(0.0, dt) / tau)
    return float(previous + alpha * (value - previous))


@dataclass
class BodyDetection:
    """One pose detection: 33x3 frame-pixel landmarks + model confidence."""

    landmarks: np.ndarray
    score: float


@dataclass
class _Track:
    track_id: int
    landmarks: np.ndarray
    score: float
    x: float
    y: float
    height: float
    vx: float = 0.0
    vy: float = 0.0
    last_seen: float = 0.0
    last_x: float = 0.0
    last_y: float = 0.0
    last_time: float = 0.0
    gate: "_PoseGate" = field(default_factory=lambda: _PoseGate())


class _PoseGate:
    """Hold/release/cooldown for one body's pose (the hand PoseTracker shape)."""

    def __init__(self) -> None:
        self.current: str | None = None
        self.candidate: str | None = None
        self.candidate_since = 0.0
        self.release_since: float | None = None
        self.cooldown_until = 0.0

    def step(self, now: float, pose: str | None) -> dict[str, float]:
        if self.current is not None:
            if pose == self.current:
                self.release_since = None
            else:
                if self.release_since is None:
                    self.release_since = now
                if now - self.release_since >= POSE_RELEASE_S:
                    self.current = None
                    self.candidate = None
                    self.cooldown_until = now + POSE_COOLDOWN_S
        elif pose is not None and now >= self.cooldown_until:
            if pose != self.candidate:
                self.candidate = pose
                self.candidate_since = now
            if now - self.candidate_since >= POSE_HOLD_S:
                self.current = pose
                self.candidate = None
        else:
            self.candidate = None
        return {f"pose_{name}": 1.0 if self.current == name else 0.0 for name in POSE_NAMES}


def _angle(a: np.ndarray, b: np.ndarray, c: np.ndarray) -> float:
    """Angle at b in degrees (a-b-c)."""
    ba = a - b
    bc = c - b
    denominator = float(np.linalg.norm(ba) * np.linalg.norm(bc))
    if denominator <= 1e-9:
        return 180.0
    cosine = float(np.clip(np.dot(ba, bc) / denominator, -1.0, 1.0))
    return math.degrees(math.acos(cosine))


def _mid(landmarks: np.ndarray, first: int, second: int) -> np.ndarray:
    return (landmarks[first, :2] + landmarks[second, :2]) / 2.0


def canonical(landmarks: np.ndarray, width: int, height: int, score: float) -> dict[str, float]:
    """Frame-pixel landmarks -> canonical x/y/height/conf (no velocity)."""
    if width <= 0 or height <= 0:
        raise ValueError(f"frame must be positive, got {width}x{height}")
    hip = _mid(landmarks, L_HIP, R_HIP)
    ankle = _mid(landmarks, L_ANKLE, R_ANKLE)
    head_y = float(landmarks[NOSE, 1])
    size = abs(float(ankle[1]) - head_y) / height
    x = float(hip[0]) / width * 2.0 - 1.0
    y = 1.0 - float(hip[1]) / height * 2.0
    return {
        "x": clamp(x, -1.0, 1.0),
        "y": clamp(y, -1.0, 1.0),
        "height": clamp(size, 0.0, 1.0),
        "conf": clamp(float(score), 0.0, 1.0),
    }


def _shoulder_width(landmarks: np.ndarray) -> float:
    return float(np.linalg.norm(landmarks[L_SHOULDER, :2] - landmarks[R_SHOULDER, :2]))


def classify_pose(landmarks: np.ndarray, height_px: float) -> str | None:
    """One body pose from geometry (scale-invariant), or None."""
    if height_px <= 1.0:
        return None
    shoulder_y = (landmarks[L_SHOULDER, 1] + landmarks[R_SHOULDER, 1]) / 2.0
    hip_y = (landmarks[L_HIP, 1] + landmarks[R_HIP, 1]) / 2.0
    left_wrist = landmarks[L_WRIST, :2]
    right_wrist = landmarks[R_WRIST, :2]
    width = max(1.0, _shoulder_width(landmarks))
    both_wrists_up = (
        landmarks[L_WRIST, 1] < shoulder_y - 0.05 * height_px
        and landmarks[R_WRIST, 1] < shoulder_y - 0.05 * height_px
    )
    elbows_up = landmarks[L_ELBOW, 1] < hip_y and landmarks[R_ELBOW, 1] < hip_y
    if both_wrists_up and elbows_up:
        return "arms_up"
    horizontal = (
        abs(landmarks[L_WRIST, 1] - shoulder_y) < 0.12 * height_px
        and abs(landmarks[R_WRIST, 1] - shoulder_y) < 0.12 * height_px
        and abs(left_wrist[0] - landmarks[L_SHOULDER, 0]) > 0.7 * width
        and abs(right_wrist[0] - landmarks[R_SHOULDER, 0]) > 0.7 * width
    )
    if horizontal:
        return "t_pose"
    wrist_distance = float(np.linalg.norm(left_wrist - right_wrist))
    chest = (shoulder_y + hip_y) / 2.0
    if (
        wrist_distance < 0.55 * width
        and abs((left_wrist[1] + right_wrist[1]) / 2.0 - chest) < 0.25 * height_px
    ):
        return "clap"
    left_arm = _angle(landmarks[L_SHOULDER, :2], landmarks[L_ELBOW, :2], landmarks[L_WRIST, :2])
    right_arm = _angle(landmarks[R_SHOULDER, :2], landmarks[R_ELBOW, :2], landmarks[R_WRIST, :2])
    left_reach = float(np.linalg.norm(left_wrist - landmarks[L_SHOULDER, :2])) / height_px
    right_reach = float(np.linalg.norm(right_wrist - landmarks[R_SHOULDER, :2])) / height_px
    if (left_arm > 150.0 and left_reach > 0.45) ^ (right_arm > 150.0 and right_reach > 0.45):
        return "point"
    left_knee = _angle(landmarks[L_HIP, :2], landmarks[L_KNEE, :2], landmarks[L_ANKLE, :2])
    right_knee = _angle(landmarks[R_HIP, :2], landmarks[R_KNEE, :2], landmarks[R_ANKLE, :2])
    if left_knee < 130.0 and right_knee < 130.0:
        return "crouch"
    return None


class BodyTracker:
    """Continuity tracker: detections -> stable ids -> body slots."""

    def __init__(self, max_bodies: int = BODY_DEFAULT, max_gap_s: float = TRACK_GAP_S) -> None:
        self.max_bodies = int(clamp(float(max_bodies), 1, BODY_MAX))
        self.max_gap_s = max(0.1, float(max_gap_s))
        self.reset()

    def reset(self) -> None:
        self._tracks: dict[int, _Track] = {}
        self._next_id = 1

    def step(
        self,
        detections: list[BodyDetection],
        width: int,
        height: int,
        now: float,
    ) -> dict[str, dict[str, float]]:
        """Match detections to live tracks and publish body1..bodyN."""
        canonical_rows = [canonical(det.landmarks, width, height, det.score) for det in detections]
        live = [track for track in self._tracks.values() if now - track.last_seen <= self.max_gap_s]
        used: set[int] = set()
        assignments: list[tuple[_Track, int]] = []
        for index, row in enumerate(canonical_rows):
            best: _Track | None = None
            best_distance = TRACK_MATCH_RADIUS
            for track in live:
                if track.track_id in used:
                    continue
                distance = math.hypot(track.x - row["x"], track.y - row["y"])
                if distance < best_distance:
                    best = track
                    best_distance = distance
            if best is not None:
                used.add(best.track_id)
                assignments.append((best, index))
        for track, index in assignments:
            row = canonical_rows[index]
            detection = detections[index]
            dt = max(1e-3, now - track.last_time)
            track.vx = _ema(
                track.vx,
                clamp((row["x"] - track.last_x) / dt, -VEL_CLAMP, VEL_CLAMP),
                dt,
                VEL_TAU_S,
            )
            track.vy = _ema(
                track.vy,
                clamp((row["y"] - track.last_y) / dt, -VEL_CLAMP, VEL_CLAMP),
                dt,
                VEL_TAU_S,
            )
            track.x, track.y, track.height = row["x"], row["y"], row["height"]
            track.score = detection.score
            track.landmarks = detection.landmarks
            track.last_seen = now
            track.last_x, track.last_y, track.last_time = row["x"], row["y"], now
        for index, detection in enumerate(detections):
            if any(index == assigned for _track, assigned in assignments):
                continue
            if len(self._tracks) >= BODY_MAX:
                continue
            row = canonical_rows[index]
            track = _Track(
                track_id=self._next_id,
                landmarks=detection.landmarks,
                score=detection.score,
                x=row["x"],
                y=row["y"],
                height=row["height"],
                last_seen=now,
                last_x=row["x"],
                last_y=row["y"],
                last_time=now,
            )
            self._tracks[track.track_id] = track
            self._next_id += 1
        self._tracks = {
            track_id: track
            for track_id, track in self._tracks.items()
            if now - track.last_seen <= self.max_gap_s
        }
        ordered = sorted(self._tracks.values(), key=lambda track: track.track_id)[: self.max_bodies]
        self._ordered = ordered
        snapshot: dict[str, dict[str, float]] = {}
        for slot, track in enumerate(ordered, start=1):
            height_px = max(1.0, track.height * height)
            pose = classify_pose(track.landmarks, height_px)
            signals = {
                "x": track.x,
                "y": track.y,
                "vel_x": track.vx,
                "vel_y": track.vy,
                "height": track.height,
                "conf": clamp(track.score, 0.0, 1.0),
                "present": 1.0,
            }
            signals.update(track.gate.step(now, pose))
            snapshot[f"body{slot}"] = signals
        return snapshot


def landmarks_by_slot(tracker: BodyTracker) -> dict[int, np.ndarray]:
    """The frame-pixel landmarks of the live slots (for the preview overlay)."""
    ordered = getattr(tracker, "_ordered", [])
    return {slot: track.landmarks for slot, track in enumerate(ordered, start=1)}


def draw_overlay(rgb: np.ndarray, landmarks: dict[int, np.ndarray]) -> np.ndarray:
    """Draw each slot's 33-point skeleton on a copy of ``rgb``."""
    image = Image.fromarray(np.asarray(rgb, dtype=np.uint8)).copy()
    draw = ImageDraw.Draw(image)
    for slot, points in landmarks.items():
        colour = SLOT_COLORS[(slot - 1) % len(SLOT_COLORS)]
        for start, end in BODY_EDGES:
            draw.line(
                [(points[start, 0], points[start, 1]), (points[end, 0], points[end, 1])],
                fill=colour,
                width=2,
            )
        for x, y in points[:, :2]:
            draw.ellipse([x - 2, y - 2, x + 2, y + 2], fill=colour)
    return np.array(image, dtype=np.uint8)


# ---------------------------------------------------------------------------
# Config (boot + persistence): the camera/hardware options live in the app
# config, like the zones/hand engines. The ROI is the performance area the
# 224 px detector can actually see (a wide stage frame is not).
# ---------------------------------------------------------------------------

CAMERA_WIDTH_MIN, CAMERA_WIDTH_MAX = 160, 1920
CAMERA_HEIGHT_MIN, CAMERA_HEIGHT_MAX = 120, 1080
MAX_HZ_MIN, MAX_HZ_MAX = 2.0, 10.0
DETECT_EVERY_MIN, DETECT_EVERY_MAX = 1, 6
SCORE_MIN, SCORE_MAX = 0.3, 0.9
ROI_DEFAULT: tuple[float, float, float, float] = (0.0, 0.0, 1.0, 1.0)


def sanitize_roi(raw: Any) -> list[float]:
    """A normalized (x0, y0, x1, y1) ROI with x1 > x0 and y1 > y0."""
    if not isinstance(raw, (list, tuple)) or len(raw) < 4:
        return list(ROI_DEFAULT)
    try:
        x0, y0, x1, y1 = (float(value) for value in raw[:4])
    except (TypeError, ValueError):
        return list(ROI_DEFAULT)
    x0, x1 = sorted((clamp(x0, 0.0, 1.0), clamp(x1, 0.0, 1.0)))
    y0, y1 = sorted((clamp(y0, 0.0, 1.0), clamp(y1, 0.0, 1.0)))
    if x1 - x0 < 0.05 or y1 - y0 < 0.05:
        return list(ROI_DEFAULT)
    return [x0, y0, x1, y1]


def config_block(cfg: dict[str, Any]) -> dict[str, Any]:
    block = cfg.get("body")
    if not isinstance(block, dict):
        block = {}
        cfg["body"] = block
    return block


def init_from_config(cfg: dict[str, Any]) -> None:
    """Apply the persisted body-engine settings to the state mirrors (boot)."""
    from vjmixapp import camera, state
    from vjmixapp.queues import log_error

    block = cfg.get("body")
    if not isinstance(block, dict):
        block = {}
    # e90: the enable switch is project content, not config
    block.pop("enabled", None)
    state.body_device = str(block.get("device") or "")
    state.body_width = int(
        clamp(float(block.get("width", 640)), CAMERA_WIDTH_MIN, CAMERA_WIDTH_MAX)
    )
    state.body_height = int(
        clamp(float(block.get("height", 480)), CAMERA_HEIGHT_MIN, CAMERA_HEIGHT_MAX)
    )
    state.body_max_hz = clamp(float(block.get("max_hz", 8.0)), MAX_HZ_MIN, MAX_HZ_MAX)
    state.body_max_bodies = int(clamp(float(block.get("max_bodies", 2)), 1, BODY_MAX))
    state.body_detect_every = int(
        clamp(float(block.get("detect_every", 3)), DETECT_EVERY_MIN, DETECT_EVERY_MAX)
    )
    state.body_score = clamp(float(block.get("score", 0.5)), SCORE_MIN, SCORE_MAX)
    state.body_roi = sanitize_roi(block.get("roi"))
    state.body_mirror = bool(block.get("mirror", False))
    state.body_preview = bool(block.get("preview", False))
    state.body_status = "off"
    state.body_ready = True
    if state.body_enabled and camera.camera_engine() != camera.CAMERA_BODY:
        state.body_enabled = False
        log_error("Body tracking", "another camera engine is active: body disabled")


def _save(mutate: Any) -> bool:
    from vjmixapp.config import load_config, save_config
    from vjmixapp.queues import log_error

    cfg = load_config()
    mutate(config_block(cfg))
    if not save_config(cfg):
        log_error("Body tracking", "settings not persisted - this session only")
        return False
    return True


def set_option(name: str, value: Any) -> None:
    """Persist one camera/inference option (main thread)."""
    from vjmixapp import state

    if name == "device":
        state.body_device = str(value or "")
    elif name == "width":
        state.body_width = int(clamp(float(value), CAMERA_WIDTH_MIN, CAMERA_WIDTH_MAX))
        value = state.body_width
    elif name == "height":
        state.body_height = int(clamp(float(value), CAMERA_HEIGHT_MIN, CAMERA_HEIGHT_MAX))
        value = state.body_height
    elif name == "max_hz":
        state.body_max_hz = clamp(float(value), MAX_HZ_MIN, MAX_HZ_MAX)
        value = state.body_max_hz
    elif name == "max_bodies":
        state.body_max_bodies = int(clamp(float(value), 1, BODY_MAX))
        value = state.body_max_bodies
    elif name == "detect_every":
        state.body_detect_every = int(clamp(float(value), DETECT_EVERY_MIN, DETECT_EVERY_MAX))
        value = state.body_detect_every
    elif name == "score":
        state.body_score = clamp(float(value), SCORE_MIN, SCORE_MAX)
        value = state.body_score
    elif name == "roi":
        state.body_roi = sanitize_roi(value)
        value = state.body_roi
    elif name == "mirror":
        state.body_mirror = bool(value)
    elif name == "preview":
        state.body_preview = bool(value)
    else:
        raise KeyError(name)
    _save(lambda block: block.__setitem__(name, value))
