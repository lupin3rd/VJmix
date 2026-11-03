"""Pose/detector adapter for the body engine (e89s03).

WORKER-ONLY MODULE (HIGH-1): no dpg. ``av`` and ``onnxruntime`` are imported
inside functions, so a missing wheel degrades to a status instead of an
ImportError (the ``handio``/``leap`` posture).

Pipeline (ported from the Apache-2.0 OpenCV Zoo demos, OpenCV-free):

    PyAV frame -> BGR letterbox 224 -> person detector -> 4 keypoints
      -> rotated hip-centred crop 256 -> pose landmark model -> 33 landmarks

The pose crop is the REFERENCE one: the detector's 4 keypoints are the person
geometry (hip centre + full-body point), not the small box; the crop is rotated
so the hip -> full-body vector is upright. The spike measured 0.98 confidence
with this crop versus 0.51 with a naive axis-aligned crop.
"""

import math
import os
from dataclasses import dataclass
from typing import Any

import numpy as np
from PIL import Image

BODY_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "bodytrack")
PERSON_MODEL = "person_detection_mediapipe_2023mar.onnx"
POSE_MODEL = "pose_estimation_mediapipe_2023mar.onnx"
ANCHORS_FILE = "anchors.npy"

PERSON_INPUT = 224
POSE_INPUT = 256
SCORE_THRESHOLD = 0.5
NMS_IOU = 0.3
MAX_BODIES = 3
LANDMARK_COUNT = 33
POSE_ROTATE_SIGN = 1.0  # PIL rotates the opposite way of the reference warp
POSE_CROP_FACTOR = 1.0
POSE_MIN_CONF = 0.5
ORT_THREADS = 1

# MediaPipe pose edges for the preview overlay (33 landmarks).
POSE_EDGES: tuple[tuple[int, int], ...] = (
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


def _import_av() -> Any:
    try:
        import av

        return av
    except Exception:
        return None


def _import_ort() -> Any:
    try:
        import onnxruntime

        return onnxruntime
    except Exception:
        return None


def models_present(model_dir: str = BODY_DIR) -> bool:
    """Both ONNX files and the anchor table exist."""
    return all(
        os.path.isfile(os.path.join(model_dir, name))
        for name in (PERSON_MODEL, POSE_MODEL, ANCHORS_FILE)
    )


def available() -> bool:
    """Capture + runtime + models are all present."""
    return _import_av() is not None and _import_ort() is not None and models_present()


def load_anchors(model_dir: str = BODY_DIR) -> np.ndarray:
    """The 2254x2 person-detector anchor table."""
    return np.load(os.path.join(model_dir, ANCHORS_FILE))


@dataclass
class PersonBox:
    """One person detection in FRAME pixels (box + the 4 detector keypoints)."""

    x1: float
    y1: float
    x2: float
    y2: float
    score: float
    keypoints: np.ndarray

    @property
    def height(self) -> float:
        return self.y2 - self.y1


@dataclass
class PoseCrop:
    """The rotated pose crop geometry: image, origin, angle and size."""

    image: np.ndarray
    pad_bias: np.ndarray  # frame coordinates of the padded square's top-left
    angle: float  # radians, the reference hip -> full-body angle
    size: int


def letterbox_rgb(rgb: np.ndarray, size: int = PERSON_INPUT) -> tuple[np.ndarray, np.ndarray]:
    """Resize keeping aspect, black pad, [-1,1] RGB NCHW (the reference channel)."""
    height, width = rgb.shape[:2]
    ratio = min(size / height, size / width)
    resized_w = max(1, round(width * ratio))
    resized_h = max(1, round(height * ratio))
    image = Image.fromarray(np.ascontiguousarray(rgb, dtype=np.uint8)).resize(
        (resized_w, resized_h), Image.Resampling.BILINEAR
    )
    left = (size - resized_w) // 2
    top = (size - resized_h) // 2
    canvas = np.full((size, size, 3), -1.0, dtype=np.float32)
    patch = np.asarray(image, dtype=np.float32) / 255.0
    canvas[top : top + resized_h, left : left + resized_w] = (patch - 0.5) * 2.0
    return np.transpose(canvas, [2, 0, 1])[None], np.array([left, top]) / ratio


def nms(boxes: list[PersonBox], iou_threshold: float = NMS_IOU) -> list[PersonBox]:
    """Greedy NMS on frame-pixel boxes."""
    ordered = sorted(boxes, key=lambda box: box.score, reverse=True)
    keep: list[PersonBox] = []
    while ordered:
        current = ordered.pop(0)
        keep.append(current)
        rest: list[PersonBox] = []
        for other in ordered:
            xx1 = max(current.x1, other.x1)
            yy1 = max(current.y1, other.y1)
            xx2 = min(current.x2, other.x2)
            yy2 = min(current.y2, other.y2)
            inter = max(0.0, xx2 - xx1) * max(0.0, yy2 - yy1)
            area_current = max(0.0, current.x2 - current.x1) * max(0.0, current.y2 - current.y1)
            area_other = max(0.0, other.x2 - other.x1) * max(0.0, other.y2 - other.y1)
            union = area_current + area_other - inter
            if union <= 1e-9 or inter / union <= iou_threshold:
                rest.append(other)
        ordered = rest
    return keep


def decode_person(
    raw_boxes: np.ndarray,
    raw_scores: np.ndarray,
    anchor_table: np.ndarray,
    pad_bias: np.ndarray,
    scale: float,
    score_threshold: float = SCORE_THRESHOLD,
) -> list[PersonBox]:
    """Decode the detector outputs; the 4 keypoints define the person geometry."""
    scores = 1.0 / (1.0 + np.exp(-np.clip(raw_scores.astype(np.float64), -100.0, 100.0)))
    centers = raw_boxes[:, :2] / PERSON_INPUT
    sizes = raw_boxes[:, 2:4] / PERSON_INPUT
    xy1 = (centers - sizes / 2.0 + anchor_table) * scale
    xy2 = (centers + sizes / 2.0 + anchor_table) * scale
    has_keypoints = raw_boxes.shape[1] >= 12
    boxes: list[PersonBox] = []
    for index in np.where(scores >= score_threshold)[0]:
        x1 = float(xy1[index, 0] - pad_bias[0])
        y1 = float(xy1[index, 1] - pad_bias[1])
        x2 = float(xy2[index, 0] - pad_bias[0])
        y2 = float(xy2[index, 1] - pad_bias[1])
        keypoints = np.zeros((4, 2), dtype=np.float64)
        if has_keypoints:
            keypoints = (
                raw_boxes[index, 4:12].reshape(4, 2) / PERSON_INPUT + anchor_table[index]
            ) * scale - pad_bias
            mid_hip, full_body = keypoints[0], keypoints[1]
            distance = float(np.linalg.norm(full_body - mid_hip))
            if distance > 4.0:
                x1, y1 = float(mid_hip[0] - distance), float(mid_hip[1] - distance)
                x2, y2 = float(mid_hip[0] + distance), float(mid_hip[1] + distance)
        if x2 <= x1 or y2 <= y1:
            continue
        boxes.append(PersonBox(x1, y1, x2, y2, float(scores[index]), keypoints))
    return nms(boxes)


def pose_crop(rgb: np.ndarray, person: PersonBox) -> PoseCrop:
    """The reference rotated hip-centred square crop (black-padded)."""
    height, width = rgb.shape[:2]
    mid_hip = person.keypoints[0]
    full_body = person.keypoints[1]
    distance = float(np.linalg.norm(full_body - mid_hip))
    if distance < 4.0:
        distance = max(8.0, person.height / 2.0)
    half = distance * POSE_CROP_FACTOR
    size = max(8, round(half * 2.0))
    full_left = round(mid_hip[0] - half)
    full_top = round(mid_hip[1] - half)
    canvas = np.zeros((size, size, 3), dtype=np.uint8)
    src_x0, src_y0 = max(0, full_left), max(0, full_top)
    src_x1, src_y1 = min(width, full_left + size), min(height, full_top + size)
    if src_x1 > src_x0 and src_y1 > src_y0:
        canvas[src_y0 - full_top : src_y1 - full_top, src_x0 - full_left : src_x1 - full_left] = (
            rgb[src_y0:src_y1, src_x0:src_x1]
        )
    mid_local = np.array([mid_hip[0] - full_left, mid_hip[1] - full_top], dtype=np.float64)
    dx = float(full_body[0] - mid_hip[0])
    dy = float(full_body[1] - mid_hip[1])
    radians = math.pi / 2.0 - math.atan2(-dy, dx)
    radians = radians - 2.0 * math.pi * math.floor((radians + math.pi) / (2.0 * math.pi))
    angle = radians
    rotated = Image.fromarray(canvas).rotate(
        math.degrees(angle) * POSE_ROTATE_SIGN,
        center=(mid_local[0], mid_local[1]),
        resample=Image.Resampling.BILINEAR,
    )
    return PoseCrop(
        image=np.array(rotated, dtype=np.uint8),
        pad_bias=np.array([full_left, full_top], dtype=np.float64),
        angle=angle,
        size=size,
    )


def map_pose_landmarks(raw: np.ndarray, crop: PoseCrop) -> np.ndarray:
    """Map the 39x5 raw pose output (input pixels) back to frame pixels."""
    landmarks = np.array(raw.reshape(-1, 5)[:LANDMARK_COUNT], dtype=np.float64, copy=True)
    offsets = (landmarks[:, :2] - POSE_INPUT / 2.0) * (crop.size / POSE_INPUT)
    cos_a, sin_a = math.cos(crop.angle), math.sin(crop.angle)
    rotation = np.array([[cos_a, sin_a], [-sin_a, cos_a]], dtype=np.float64)
    rotated = offsets @ rotation
    landmarks[:, :2] = rotated + np.array([crop.size / 2.0, crop.size / 2.0]) + crop.pad_bias
    return landmarks


class PersonDetector:
    """The person-detector ORT session (lazy import; injectable for tests)."""

    def __init__(
        self, model_dir: str = BODY_DIR, session: Any = None, channel: str = "bgr"
    ) -> None:
        self.channel = channel
        self.anchors = load_anchors(model_dir)
        self._session = session
        if self._session is None:
            ort = _import_ort()
            if ort is not None:
                options = ort.SessionOptions()
                options.intra_op_num_threads = ORT_THREADS
                options.log_severity_level = 3
                self._session = ort.InferenceSession(
                    os.path.join(model_dir, PERSON_MODEL),
                    options,
                    providers=["CPUExecutionProvider"],
                )

    def detect(
        self, rgb: np.ndarray, roi: tuple[float, float, float, float] | None = None
    ) -> list[PersonBox]:
        if self._session is None:
            return []
        if roi is not None:
            height, width = rgb.shape[:2]
            left = int(max(0, min(width - 1, roi[0] * width)))
            top = int(max(0, min(height - 1, roi[1] * height)))
            right = int(max(left + 2, min(width, roi[2] * width)))
            bottom = int(max(top + 2, min(height, roi[3] * height)))
            boxes = self._detect_frame(rgb[top:bottom, left:right])
            return [
                PersonBox(
                    box.x1 + left,
                    box.y1 + top,
                    box.x2 + left,
                    box.y2 + top,
                    box.score,
                    box.keypoints + np.array([left, top]),
                )
                for box in boxes
            ]
        return self._detect_frame(rgb)

    def _detect_frame(self, rgb: np.ndarray) -> list[PersonBox]:
        input_chw, pad_bias = letterbox_rgb(rgb)
        outputs = self._session.run(None, {self._session.get_inputs()[0].name: input_chw})
        first, second = outputs[0], outputs[1]
        if first.shape[-1] == 1:
            raw_scores, raw_boxes = first[0, :, 0], second[0]
        else:
            raw_boxes, raw_scores = first[0], second[0, :, 0]
        return decode_person(raw_boxes, raw_scores, self.anchors, pad_bias, max(rgb.shape[:2]))


class PoseEstimator:
    """The pose-landmark ORT session (lazy import; injectable for tests)."""

    def __init__(self, model_dir: str = BODY_DIR, session: Any = None) -> None:
        self._session = session
        if self._session is None:
            ort = _import_ort()
            if ort is not None:
                options = ort.SessionOptions()
                options.intra_op_num_threads = ORT_THREADS
                options.log_severity_level = 3
                self._session = ort.InferenceSession(
                    os.path.join(model_dir, POSE_MODEL),
                    options,
                    providers=["CPUExecutionProvider"],
                )

    def estimate(self, rgb: np.ndarray, person: PersonBox) -> tuple[np.ndarray | None, float]:
        if self._session is None:
            return None, 0.0
        crop = pose_crop(rgb, person)
        image = Image.fromarray(crop.image).resize(
            (POSE_INPUT, POSE_INPUT), Image.Resampling.BILINEAR
        )
        blob = (np.asarray(image, dtype=np.float32) / 255.0)[None]
        outputs = self._session.run(None, {self._session.get_inputs()[0].name: blob})
        confidence = float(outputs[1][0][0])
        if confidence < POSE_MIN_CONF:
            return None, confidence
        return map_pose_landmarks(outputs[0][0], crop), confidence
