"""Capture + inference adapter for the webcam hand engine (e87).

WORKER-ONLY MODULE (HIGH-1): no dpg anywhere. ``av`` and ``onnxruntime`` are
imported INSIDE functions so a missing wheel (or the test suite) degrades to a
status instead of an ImportError — the same posture as ``vjmixapp/leap.py``.

Pipeline (ported from the Apache-2.0 OpenCV Zoo demos, rewritten without OpenCV):

    PyAV V4L2 (MJPEG) -> RGB frame
      -> palm detector (192x192 NHWC) -> boxes + 7 palm keypoints (NMS)
      -> rotated/padded crop -> landmark model (224x224) -> 21 landmarks + score
      -> frame-normalized landmarks, handedness

TWO models, ~8 MB together, are the same two networks MediaPipe Hands uses; the
int8 variants are SLOWER on x86 (measured 36 ms vs 14 ms), so fp32 is kept.
Tracking-skip: while the previous detection scores well, only the landmark model
runs (4.6 ms/frame at 1 thread, measured); the palm detector (13.9 ms) re-runs
only to (re)acquire.
"""

import contextlib
import glob
import math
import os
import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
from PIL import Image

HAND_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "handtrack")
PALM_MODEL = "palm_detection_mediapipe_2023feb.onnx"
HAND_MODEL = "handpose_estimation_mediapipe_2023feb.onnx"

PALM_INPUT = 192
HAND_INPUT = 224
PALM_ANCHOR_COUNT = 2016
LANDMARK_COUNT = 21
PALM_KEYPOINTS = 7

# Camera defaults: the measured integrated-camera capability is MJPEG 640x480 at
# 30 fps nominal (~17.7 fps delivered in ambient light) and 320x240 decodes for
# 0.06 ms/frame. 640x480 keeps landmark precision; the models downscale anyway.
CAMERA_WIDTH = 640
CAMERA_HEIGHT = 480
CAMERA_FPS = 30
CAMERA_OPEN_TIMEOUT_S = 2.0
# BUG-2026-10-23T220000: av.open() covers its I/O with an interrupt callback, but
# NOT the V4L2 ioctls it issues while setting up the stream. A wedged node (seen
# after two clients contended for the device) blocked a worker thread inside
# av.open() forever: the engine never read a frame, fps/latency stayed 0 and the
# UI showed nothing. The open now runs on a helper thread with a deadline; a
# wedged device is reported as `stalled` instead of silently killing the engine.
CAMERA_OPEN_DEADLINE_S = 6.0
CAMERA_MAX_FAILURES = 3
CAMERA_RETRY_MIN_S = 0.5
CAMERA_RETRY_MAX_S = 4.0
# BUG-2026-10-23T201500: the device captures at its own rate while the worker reads
# once per pass (6 Hz searching, the user's Max Hz tracking), so the V4L2 queue
# filled up and every read returned a frame from the BACK of it — measured 3.9 s
# of age within 30 reads. read() now drains the queued packets (without decoding)
# and decodes only the freshest one.
# BUG-2026-10-24T020000: the drain stopped at an AGE threshold, but the reported
# age always includes one capture interval, and the camera delivers 16.7 fps
# (60 ms measured; 100 ms under a starved queue) although it is opened at 30 fps.
# Every packet therefore looked stale: the drain burnt its whole budget on every
# pass (3.4 passes/s instead of 6, worse while tracking) and, on a finite queue,
# ended in StopIteration. The drain now stops when a pull has to WAIT for the
# camera: a queued pull returns in well under CAMERA_LIVE_WAIT_S, and the first
# pull that waits is the live edge — measured 6.0 passes/s at 106 ms of age
# (against 2072 ms with one pull per pass and 100 ms age + 250 ms wasted with the
# age rule).
CAMERA_LIVE_WAIT_S = 0.020  # a pull slower than this waited for the camera
CAMERA_DRAIN_BUDGET_S = 0.25  # hard bound on one drain pass (protects the thread)
CAMERA_MAX_DRAIN = 240  # hard bound on packets pulled by one read
CAMERA_CLOCK_SANE_S = 30.0  # a timestamp this far out is not our clock: ignore

HAND_ORT_THREADS = 1
HAND_DETECT_SCORE = 0.5  # palm detector score threshold (the reference default)
HAND_NMS_IOU = 0.3
HAND_LANDMARK_CONF = 0.6  # below this the landmark model has no hand
HAND_TRACK_CONF = 0.8  # while tracking, a weaker answer re-acquires
HAND_REDETECT_S = 2.0  # safety re-acquire even while tracking
HAND_MAX_HANDS = 1

# The reference demo's crop geometry, verbatim (see the module docstring).
PALM_BOX_PRE_SHIFT = np.array([0.0, 0.0])
PALM_BOX_PRE_ENLARGE = 4.0
PALM_BOX_SHIFT = np.array([0.0, -0.4])
PALM_BOX_ENLARGE = 3.0
PALM_LANDMARK_BASE = 0
PALM_LANDMARK_MIDDLE_BASE = 2


def _import_av() -> Any:
    """The ``av`` package, or None when it is not installed (lazy)."""
    try:
        import av

        return av
    except Exception:
        return None


def _import_ort() -> Any:
    """The ``onnxruntime`` package, or None when it is not installed (lazy)."""
    try:
        import onnxruntime

        return onnxruntime
    except Exception:
        return None


def models_present(model_dir: str = HAND_DIR) -> bool:
    """Both ONNX files exist on disk."""
    return os.path.isfile(os.path.join(model_dir, PALM_MODEL)) and os.path.isfile(
        os.path.join(model_dir, HAND_MODEL)
    )


def available() -> bool:
    """Can the webcam engine run at all (capture + runtime + models)?"""
    return _import_av() is not None and _import_ort() is not None and models_present()


def list_devices() -> list[str]:
    """The V4L2 capture nodes this machine exposes, sorted."""
    return sorted(p for p in glob.glob("/dev/video*") if os.path.exists(p))


# ---------------------------------------------------------------------------
# Geometry (pure numpy/PIL, unit-tested without a camera)
# ---------------------------------------------------------------------------


def palm_anchors() -> np.ndarray:
    """The palm detector's 2016x2 anchor table (MediaPipe SSD grid).

    MediaPipe's palm detector scores 2016 anchors: a 24x24 feature map with 2
    anchors per cell followed by a 12x12 map with 6. The reference demo hardcodes
    the table; generating it keeps the file small and a test pins the values.
    """
    anchors = []
    for y in range(24):
        for x in range(24):
            cx = (x + 0.5) / 24.0
            cy = (y + 0.5) / 24.0
            anchors.extend([(cx, cy), (cx, cy)])
    for y in range(12):
        for x in range(12):
            cx = (x + 0.5) / 12.0
            cy = (y + 0.5) / 12.0
            anchors.extend([(cx, cy)] * 6)
    return np.asarray(anchors, dtype=np.float64)


def resize_rgb(rgb: np.ndarray, size_wh: tuple[int, int]) -> np.ndarray:
    """Bilinear RGB resize through Pillow (no OpenCV)."""
    image = Image.fromarray(np.ascontiguousarray(rgb, dtype=np.uint8))
    return np.asarray(image.resize(size_wh, Image.Resampling.BILINEAR), dtype=np.uint8)


def letterbox_square(rgb: np.ndarray, size: int) -> tuple[np.ndarray, np.ndarray, float]:
    """Aspect-preserving resize into a black ``size``x``size`` canvas.

    Returns ``(canvas, pad_in_original_px, scale)`` where ``scale`` is the
    original long side (the demo's ``max(original_shape)``).
    """
    height, width = rgb.shape[:2]
    ratio = min(size / height, size / width)
    resized_w, resized_h = int(width * ratio), int(height * ratio)
    resized = resize_rgb(rgb, (max(1, resized_w), max(1, resized_h)))
    pad_left, pad_top = (size - resized.shape[1]) // 2, (size - resized.shape[0]) // 2
    canvas = np.zeros((size, size, 3), dtype=np.uint8)
    canvas[pad_top : pad_top + resized.shape[0], pad_left : pad_left + resized.shape[1]] = resized
    pad_original = np.array([pad_left, pad_top], dtype=np.float64) / ratio
    return canvas, pad_original, float(max(height, width))


def rotation_matrix(centre: Sequence[float] | np.ndarray, angle_deg: float) -> np.ndarray:
    """The 2x3 affine matrix ``cv2.getRotationMatrix2D(centre, angle, 1)`` builds."""
    theta = math.radians(angle_deg)
    cos, sin = math.cos(theta), math.sin(theta)
    cx, cy = float(centre[0]), float(centre[1])
    return np.array(
        [
            [cos, sin, (1.0 - cos) * cx - sin * cy],
            [-sin, cos, sin * cx + (1.0 - cos) * cy],
        ],
        dtype=np.float64,
    )


def apply_affine(points: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    """Apply a 2x3 affine matrix to an (N,2) point array."""
    pts = np.asarray(points, dtype=np.float64).reshape(-1, 2)
    return pts @ matrix[:, :2].T + matrix[:, 2]


def expanded_box(box: np.ndarray, shift: np.ndarray, enlarge: float) -> np.ndarray:
    """The int32 crop box ``crop_pad_square`` will take (shift, then enlarge)."""
    box = np.asarray(box, dtype=np.float64).reshape(2, 2)
    wh = box[1] - box[0]
    box = box + shift * wh
    centre = box.sum(axis=0) / 2.0
    wh = box[1] - box[0]
    half = wh * enlarge / 2.0
    return np.array([centre - half, centre + half]).astype(np.int32)


def rotation_window(
    shape: tuple[int, ...],
    centre: Sequence[float] | np.ndarray,
    angle_deg: float,
    needed_box: np.ndarray,
    margin: float = 2.0,
) -> tuple[int, int, int, int]:
    """The source window a rotation can touch (e87s06 CPU fix).

    PIL rotates the WHOLE image (O(area)), and the landmark path used to rotate
    the 4x pre-crop when only the landmark crop was needed. The rotated
    coordinates of ``needed_box`` come from ``rotation_matrix``, so the source
    region is its inverse image: rotate the four corners back about the centre
    and take the axis-aligned box. Rotating that window is pixel-identical and
    ~3x cheaper on a 160 px hand.

    Returns ``(x0, y0, x1, y1)`` clipped to the image.
    """
    height, width = shape[:2]
    corners = np.array(
        [
            [needed_box[0][0], needed_box[0][1]],
            [needed_box[1][0], needed_box[0][1]],
            [needed_box[1][0], needed_box[1][1]],
            [needed_box[0][0], needed_box[1][1]],
        ],
        dtype=np.float64,
    )
    source = apply_affine(corners, rotation_matrix(centre, -angle_deg))
    x0 = max(0, math.floor(float(source[:, 0].min()) - margin))
    x1 = min(width, math.ceil(float(source[:, 0].max()) + margin))
    y0 = max(0, math.floor(float(source[:, 1].min()) - margin))
    y1 = min(height, math.ceil(float(source[:, 1].max()) + margin))
    return x0, y0, x1, y1


def crop_pad_square(
    rgb: np.ndarray,
    box: np.ndarray,
    shift: np.ndarray,
    enlarge: float,
    *,
    square_by_diagonal: bool,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Crop a square around ``box`` (the demo's ``_cropAndPadFromPalm``).

    Returns ``(crop, clipped_box, bias)`` where ``bias = box[0] - [left, top]``
    maps crop coordinates back to the input image (``original = crop + bias``).
    """
    height, width = rgb.shape[:2]
    box = expanded_box(box, shift, enlarge)
    box[:, 0] = np.clip(box[:, 0], 0, width)
    box[:, 1] = np.clip(box[:, 1], 0, height)
    crop = rgb[box[0][1] : box[1][1], box[0][0] : box[1][0], :]
    if crop.size == 0:
        crop = np.zeros((1, 1, 3), dtype=rgb.dtype)
    side = int(np.linalg.norm(crop.shape[:2])) if square_by_diagonal else int(max(crop.shape[:2]))
    pad_h, pad_w = max(0, side - crop.shape[0]), max(0, side - crop.shape[1])
    left, top = pad_w // 2, pad_h // 2
    padded = np.zeros((crop.shape[0] + pad_h, crop.shape[1] + pad_w, 3), dtype=crop.dtype)
    padded[top : top + crop.shape[0], left : left + crop.shape[1]] = crop
    bias = box[0] - np.array([left, top])
    return padded, box, bias


def nms(
    boxes: np.ndarray,
    scores: np.ndarray,
    score_threshold: float = HAND_DETECT_SCORE,
    iou_threshold: float = HAND_NMS_IOU,
    top_k: int = 5000,
) -> np.ndarray:
    """Greedy non-maximum suppression over ``[x1, y1, x2, y2]`` boxes."""
    boxes = np.asarray(boxes, dtype=np.float64)
    scores = np.asarray(scores, dtype=np.float64)
    candidates = np.where(scores >= score_threshold)[0]
    if candidates.size == 0:
        return np.empty((0,), dtype=int)
    order = candidates[np.argsort(-scores[candidates])][:top_k]
    keep: list[int] = []
    while order.size:
        best = int(order[0])
        keep.append(best)
        if order.size == 1:
            break
        rest = order[1:]
        xx1 = np.maximum(boxes[best, 0], boxes[rest, 0])
        yy1 = np.maximum(boxes[best, 1], boxes[rest, 1])
        xx2 = np.minimum(boxes[best, 2], boxes[rest, 2])
        yy2 = np.minimum(boxes[best, 3], boxes[rest, 3])
        inter = np.maximum(0.0, xx2 - xx1) * np.maximum(0.0, yy2 - yy1)
        area_best = (boxes[best, 2] - boxes[best, 0]) * (boxes[best, 3] - boxes[best, 1])
        area_rest = (boxes[rest, 2] - boxes[rest, 0]) * (boxes[rest, 3] - boxes[rest, 1])
        union = area_best + area_rest - inter
        iou = np.where(union > 0.0, inter / np.maximum(union, 1e-9), 0.0)
        order = rest[iou < iou_threshold]
    return np.asarray(keep, dtype=int)


# ---------------------------------------------------------------------------
# The adapter
# ---------------------------------------------------------------------------


_OPEN_LOCK = threading.Lock()
_PENDING_OPEN: set[str] = set()


@dataclass
class DetectedHand:
    """One detected hand, in FRAME-normalized coordinates (x right, y down)."""

    landmarks: np.ndarray  # 21x3, x/y in [0,1], z wrist-relative
    side: str  # "left" | "right" (already corrected for the mirrored assumption)
    score: float


class CameraSource:
    """A V4L2 capture node through PyAV (MJPEG requested, RGB frames out)."""

    def __init__(
        self,
        device: str = "",
        width: int = CAMERA_WIDTH,
        height: int = CAMERA_HEIGHT,
        fps: int = CAMERA_FPS,
    ) -> None:
        self.device = device
        self.width = width
        self.height = height
        self.fps = fps
        self.failures = 0
        self.lost = False
        self.drained = 0  # packets pulled by the last read (stale ones discarded)
        self.frame_age_ms = 0.0  # kernel age of the frame read() last returned
        self.stalled = False  # the last open() did not return within the deadline
        self._container: Any = None
        self._stream: Any = None
        self._packets: Any = None

    def available(self) -> bool:
        return _import_av() is not None

    def open(self) -> bool:
        av = _import_av()
        if av is None or not self.device:
            return False
        self.close()
        self.stalled = False
        with _OPEN_LOCK:
            if self.device in _PENDING_OPEN:
                # An earlier open is still wedged inside the driver: opening a
                # second time would only stack a second stuck thread.
                self.stalled = True
                return False
            _PENDING_OPEN.add(self.device)
        # BUG-2026-10-24T001800: the hand-off is decided UNDER _OPEN_LOCK, and the
        # caller marks the attempt abandoned only after the deadline expired. The
        # old `consumed` flag was raised after join() — i.e. always after the
        # thread's `finally` had already run — so the healthy container was closed
        # moments after it was created (PyAV empties `streams` on close ->
        # IndexError -> open() False on EVERY attempt: the LED flashed and went
        # off), while a container arriving after the deadline was never closed
        # and kept the device busy.
        box: dict[str, Any] = {"container": None, "abandoned": False}

        def _do_open() -> None:
            try:
                container = av.open(
                    self.device,
                    format="v4l2",
                    options={
                        "input_format": "mjpeg",
                        "video_size": f"{self.width}x{self.height}",
                        "framerate": str(self.fps),
                    },
                    timeout=CAMERA_OPEN_TIMEOUT_S,
                )
            except Exception:
                container = None
            with _OPEN_LOCK:
                _PENDING_OPEN.discard(self.device)
                if container is not None and box["abandoned"]:
                    # The caller gave up: release what the driver finally handed us.
                    with contextlib.suppress(Exception):
                        container.close()
                    container = None
                box["container"] = container

        opener = threading.Thread(target=_do_open, name="handio-open", daemon=True)
        opener.start()
        opener.join(CAMERA_OPEN_DEADLINE_S)
        with _OPEN_LOCK:
            if opener.is_alive():
                box["abandoned"] = True
                self.stalled = True
                return False
            container = box["container"]
        if container is None:
            return False
        try:
            self._container = container
            self._stream = container.streams.video[0]
            self._stream.thread_type = "AUTO"
            self._packets = container.demux(self._stream)
        except Exception:
            # A half-open container keeps the V4L2 node claimed: every later
            # attempt would answer EBUSY for the rest of the session.
            self._container = None
            self._stream = None
            self._packets = None
            with contextlib.suppress(Exception):
                container.close()
            return False
        self.failures = 0
        self.lost = False
        return True

    def _packet_age(self, packet: Any, now: float) -> float:
        """Seconds since the kernel stamped this packet (0.0 when unusable)."""
        pts = getattr(packet, "pts", None)
        time_base = getattr(self._stream, "time_base", None)
        if pts is None or not time_base:
            return 0.0
        age = now - float(pts) * float(time_base)
        if age < 0.0 or age > CAMERA_CLOCK_SANE_S:
            return 0.0  # not the same clock: never drain on it
        return age

    def _newest_packet(self) -> Any:
        """The freshest packet the driver already handed over (the stale ones are drained).

        Queued packets come back immediately; the first pull that has to wait for
        the camera is the live edge, so that packet is the freshest available and
        the drain stops there (BUG-2026-10-24T020000: an age threshold cannot see
        that edge — the reported age always carries one capture interval).
        """
        self.drained = 0
        deadline = time.monotonic() + CAMERA_DRAIN_BUDGET_S
        newest = None
        while self.drained < CAMERA_MAX_DRAIN:
            started = time.monotonic()
            try:
                packet = next(self._packets)
            except StopIteration:
                break  # a finite queue is exhausted: the newest is in hand
            waited = time.monotonic() - started
            self.drained += 1
            if packet is None or not getattr(packet, "size", 1):
                break
            newest = packet
            self.frame_age_ms = self._packet_age(packet, time.monotonic()) * 1000.0
            if waited >= CAMERA_LIVE_WAIT_S:
                break  # this one had to wait for the camera: it IS the live edge
            if time.monotonic() >= deadline:
                break
        return newest

    def read(self) -> np.ndarray | None:
        """The NEWEST frame as RGB, or None (a failure is counted; the worker retries)."""
        if self._container is None and not self.open():
            self._note_failure()
            return None
        try:
            packet = self._newest_packet()
            if packet is None:
                self._note_failure()
                return None
            frames = packet.decode()
            if not frames:
                self._note_failure()
                return None
            rgb = frames[-1].to_ndarray(format="rgb24")
        except Exception:
            self._note_failure()
            return None
        self.failures = 0
        return rgb

    def _note_failure(self) -> None:
        self.close()
        self.failures += 1
        if self.failures >= CAMERA_MAX_FAILURES:
            self.lost = True

    def close(self) -> None:
        container = self._container
        self._container = None
        self._stream = None
        self._packets = None
        if container is not None:
            with contextlib.suppress(Exception):
                container.close()

    def retry_delay(self) -> float:
        """Exponential backoff after consecutive failures (bounded)."""
        exponent = max(0, self.failures - 1)
        return min(CAMERA_RETRY_MAX_S, CAMERA_RETRY_MIN_S * (2.0**exponent))


class HandModel:
    """The two ONNX sessions + the tracking-skip state machine."""

    def __init__(self, model_dir: str = HAND_DIR, threads: int = HAND_ORT_THREADS) -> None:
        self.model_dir = model_dir
        self.threads = threads
        self._sessions: dict[str, Any] = {}
        self._track: tuple[np.ndarray, np.ndarray] | None = None
        self._last_detect = 0.0

    def available(self) -> bool:
        return _import_ort() is not None and models_present(self.model_dir)

    def _session(self, filename: str) -> Any:
        ort = _import_ort()
        if ort is None:
            raise RuntimeError("onnxruntime is not installed")
        if filename not in self._sessions:
            options = ort.SessionOptions()
            options.intra_op_num_threads = self.threads
            options.inter_op_num_threads = 1
            options.log_severity_level = 3
            self._sessions[filename] = ort.InferenceSession(
                os.path.join(self.model_dir, filename),
                options,
                providers=["CPUExecutionProvider"],
            )
        return self._sessions[filename]

    # -- palm detector ------------------------------------------------------

    def _palm_detect(self, rgb: np.ndarray) -> list[tuple[np.ndarray, np.ndarray, float]]:
        canvas, pad, scale = letterbox_square(rgb, PALM_INPUT)
        blob = (canvas.astype(np.float32) / 255.0)[None, ...]
        session = self._session(PALM_MODEL)
        outputs = session.run(None, {session.get_inputs()[0].name: blob})
        raw = np.asarray(outputs[1])[0, :, 0]
        scores = 1.0 / (1.0 + np.exp(-raw.astype(np.float64)))
        deltas = np.asarray(outputs[0])[0]
        anchors = palm_anchors()
        centres = deltas[:, :2] / PALM_INPUT
        sizes = deltas[:, 2:4] / PALM_INPUT
        xy1 = (centres - sizes / 2.0 + anchors) * scale - pad
        xy2 = (centres + sizes / 2.0 + anchors) * scale - pad
        boxes = np.concatenate([xy1, xy2], axis=1)
        keep = nms(boxes, scores)
        if keep.size == 0:
            return []
        keypoints = deltas[keep, 4:].reshape(-1, PALM_KEYPOINTS, 2) / PALM_INPUT
        keypoints = (keypoints + anchors[keep][:, None, :]) * scale - pad
        return [(boxes[i], keypoints[n], float(scores[i])) for n, i in enumerate(keep)]

    # -- landmark model -----------------------------------------------------

    def _landmarks(
        self, rgb: np.ndarray, box: np.ndarray, palm_points: np.ndarray
    ) -> DetectedHand | None:
        height, width = rgb.shape[:2]
        pre_crop, pre_box, bias = crop_pad_square(
            rgb, box, PALM_BOX_PRE_SHIFT, PALM_BOX_PRE_ENLARGE, square_by_diagonal=True
        )
        palm_local = np.asarray(palm_points, dtype=np.float64) - bias
        p1 = palm_local[PALM_LANDMARK_BASE]
        p2 = palm_local[PALM_LANDMARK_MIDDLE_BASE]
        radians = math.pi / 2.0 - math.atan2(-(p2[1] - p1[1]), p2[0] - p1[0])
        radians -= 2.0 * math.pi * math.floor((radians + math.pi) / (2.0 * math.pi))
        angle = math.degrees(radians)
        box_local = pre_box - bias
        centre = box_local.sum(axis=0) / 2.0
        matrix = rotation_matrix(centre, angle)

        # The bbox of the rotated PALM KEYPOINTS (the demo's rule): a rotated
        # box's corners do not stay axis-aligned, so min/max them instead.
        rotated_points = apply_affine(palm_local, matrix)
        rotated_box = np.array([rotated_points.min(axis=0), rotated_points.max(axis=0)])

        # Rotate the pre-crop around the palm centre (PIL rotate is CCW, like
        # cv2.getRotationMatrix2D + warpAffine) and move the palm box with it.
        # e87s06: rotate ONLY the source window the landmark crop needs — Pillow's
        # bilinear rotate is O(area) and the 4x pre-crop is 2-3x larger than the
        # crop, so the windowed rotate is pixel-identical and ~3x cheaper.
        needed_box = expanded_box(rotated_box, PALM_BOX_SHIFT, PALM_BOX_ENLARGE)
        x0, y0, x1, y1 = rotation_window(pre_crop.shape, centre, angle, needed_box)
        offset = np.array([x0, y0], dtype=np.float64)
        window = np.ascontiguousarray(pre_crop[y0:y1, x0:x1])
        rotated = np.asarray(
            Image.fromarray(window).rotate(
                angle,
                resample=Image.Resampling.BILINEAR,
                center=(float(centre[0] - x0), float(centre[1] - y0)),
                fillcolor=(0, 0, 0),
            )
        )

        crop, rotated_box, _bias2 = crop_pad_square(
            rotated,
            rotated_box - offset,
            PALM_BOX_SHIFT,
            PALM_BOX_ENLARGE,
            square_by_diagonal=False,
        )
        blob = resize_rgb(crop, (HAND_INPUT, HAND_INPUT)).astype(np.float32) / 255.0
        session = self._session(HAND_MODEL)
        outputs = session.run(None, {session.get_inputs()[0].name: blob[None, ...]})
        landmarks = np.asarray(outputs[0])[0].reshape(-1, 3).astype(np.float64)
        presence = float(np.asarray(outputs[1]).reshape(-1)[0])
        handedness = float(np.asarray(outputs[2]).reshape(-1)[0])
        if presence < HAND_LANDMARK_CONF:
            return None

        # Back from the 224 crop to rotated-image pixels, then undo the crop.
        size = (rotated_box[1] - rotated_box[0]) / HAND_INPUT
        landmarks[:, :2] = (landmarks[:, :2] - HAND_INPUT / 2.0) * float(np.max(size))
        landmarks[:, 2] = landmarks[:, 2] * float(np.max(size))
        # The demo's inverse: `points @ R` (R^T applied) — a forward apply here
        # would rotate the hand the WRONG way and the landmarks land mirrored.
        unrotated = landmarks[:, :2] @ rotation_matrix((0.0, 0.0), angle)[:, :2]

        # Inverse of the rotation+crop affine, exactly as the reference builds it.
        rot = matrix[:, :2].T
        translation = matrix[:, 2]
        inverse_translation = -rot @ translation
        inverse = np.c_[rot, inverse_translation]
        # e87s06: the rotated crop lives in the WINDOW's coordinates, so the
        # centre must go back to pre-crop coordinates BEFORE the inverse rotation
        # (rotating a point is not translation-invariant).
        rotated_centre = np.append(rotated_box.sum(axis=0) / 2.0 + offset, 1.0)
        original_centre = np.array(
            [float(np.dot(rotated_centre, inverse[0])), float(np.dot(rotated_centre, inverse[1]))]
        )
        landmarks[:, :2] = unrotated + original_centre + bias

        normalized = landmarks.copy()
        normalized[:, 0] = landmarks[:, 0] / max(width, 1)
        normalized[:, 1] = landmarks[:, 1] / max(height, 1)
        # BUG-2026-10-24T004500: the model labels the RAW frame, measured, not the
        # "mirrored input" the MediaPipe docs describe (the OpenCV Zoo export is
        # its own convention; its demo comment reads "handedness, (left)[0,
        # 1](right) hand"). On the rig, a known RIGHT hand with the palm to the
        # camera in the raw 640x480 frame scored 0.905, and the same frame
        # flipped scored 0.054. A swap here published the opposite hand, and the
        # SideStabilizer then kept that wrong name for the whole session.
        side = "right" if handedness >= 0.5 else "left"
        return DetectedHand(landmarks=normalized, side=side, score=presence)

    # -- public -------------------------------------------------------------

    def detect(self, rgb: np.ndarray, now: float | None = None) -> list[DetectedHand]:
        """Detected hands (max ``HAND_MAX_HANDS``), with the tracking shortcut."""
        if now is None:
            now = time.monotonic()
        if self._track is not None and now - self._last_detect < HAND_REDETECT_S:
            box, palm_points = self._track
            hand = self._landmarks(rgb, box, palm_points)
            if hand is not None and hand.score >= HAND_TRACK_CONF:
                return [hand]
            self._track = None
        hands: list[DetectedHand] = []
        for box, palm_points, _score in self._palm_detect(rgb)[:HAND_MAX_HANDS]:
            hand = self._landmarks(rgb, box, palm_points)
            if hand is None:
                continue
            hands.append(hand)
            self._track = (box, palm_points)
            self._last_detect = now
        return hands

    def reset(self) -> None:
        """Forget the tracked crop (engine restart / provider switch)."""
        self._track = None
        self._last_detect = 0.0
