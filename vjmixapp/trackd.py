"""The tracker child: camera capture and ONNX inference OUTSIDE the show (e90s02).

Why this process exists: the tracking stack runs native code (onnxruntime,
ffmpeg, V4L2) that no Python guard can survive — a segfault or an abort in the
app process kills the performance UI. Moving capture and inference here means
the worst case is this process dying, and the supervisor
(``vjmixapp/trackchild.py``) restarts it or hands the operator a choice.

Contract: this module imports no dpg, no ``state``, no ``mapper``. It speaks
only the envelope of ``vjmixapp/trackpipe.py`` over the socket it is told to
connect to, and it is driven by ``Control`` messages from the parent.

One camera owner (e90s03): the three producers are mutually exclusive with the
same priority the app uses — hand > body > zones — and the inactive ones hold
no device at all.

Run: ``python -m vjmixapp.trackd`` (the parent sets the socket path and the
session token in the environment, never in argv).
"""

import io
import os
import signal
import socket
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Any

import numpy as np

from vjmixapp import bodyio, bodytrack, handio, trackpipe, zonetrack

ENV_SOCKET = "VJMIX_TRACK_SOCKET"
ENV_TOKEN = "VJMIX_TRACK_TOKEN"

HEARTBEAT_S = 0.5
IDLE_SLEEP_S = 0.05
# e94s02: the preview has its own cadence; inference keeps its own. 20 Hz is
# smooth on a 30 fps camera without running the model on every read.
DEFAULT_PREVIEW_HZ = 20.0
MIN_PREVIEW_HZ = 1.0
MAX_PREVIEW_HZ = 30.0
CONTROL_TIMEOUT_S = 0.2
# A failed camera open is retried on a slow cadence: retrying at the frame rate
# burns CPU in ffmpeg probing (measured 26 % with a missing device).
RETRY_SLEEP_S = 2.0
RETRY_BEAT_S = 0.4
# A blocked camera read cannot be interrupted from Python (it is a C call). The
# watchdog turns "frozen forever" into "this process exits", which the parent
# already knows how to recover: kill -> restart a clean child. Measured on the
# rig: after a SIGKILL the UVC node can deliver one frame and then stall.
STUCK_ITERATION_S = 10.0
# BUG-2026-11-05T230841: a child must not outlive its parent. The control loop
# notices the socket EOF, but a thread blocked in a camera call cannot; this
# guard exits the process even then.
PARENT_GUARD_POLL_S = 1.0
EXIT_PARENT_GONE = 3
PR_SET_PDEATHSIG = 1
WATCHDOG_POLL_S = 1.0
EXIT_STUCK = 3
JPEG_QUALITY = 70

STATUS_OFF = "off"
STATUS_MISSING_DEPS = "missing-deps"
STATUS_NO_CAMERA = "no-camera"
STATUS_STALLED = "stalled"
STATUS_LOST = "lost"
STATUS_SEARCHING = "searching"
STATUS_LIVE = "live"

EMPTY_LANDMARKS = (0, 3)


def _number(raw: Any, default: float, low: float, high: float) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return default
    return min(high, max(low, value))


@dataclass
class HandConfig:
    """The hand engine's share of the parent's ``Control`` message."""

    enabled: bool = False
    device: str = ""
    width: int = 640
    height: int = 480
    max_hz: float = 12.0
    preview: bool = False
    preview_w: int = 160
    preview_h: int = 120
    prefer_frame_rate: bool = False


@dataclass
class BodyConfig:
    enabled: bool = False
    device: str = ""
    width: int = 640
    height: int = 480
    max_hz: float = 8.0
    max_bodies: int = 2
    detect_every: int = 3
    score: float = 0.5
    roi: tuple[float, float, float, float] = bodytrack.ROI_DEFAULT
    preview: bool = False
    preview_w: int = 320
    preview_h: int = 240
    reset: int = 0
    prefer_frame_rate: bool = False


@dataclass
class ZonesConfig:
    enabled: bool = False
    device: str = ""
    width: int = 320
    height: int = 240
    processing_width: int = zonetrack.PROCESSING_WIDTH_DEFAULT
    threshold: float = zonetrack.THRESHOLD_DEFAULT
    min_area: float = zonetrack.MIN_AREA_DEFAULT
    bg_tau_s: float = zonetrack.BG_TAU_DEFAULT
    max_hz: float = 10.0
    mirror: bool = False
    preview: bool = False
    preview_w: int = 320
    preview_h: int = 180
    reset: int = 0
    zones: list[dict[str, Any]] = field(default_factory=list)
    prefer_frame_rate: bool = False


def hand_config(raw: Any) -> HandConfig:
    """Sanitize one ``hand`` block; a malformed field falls back, never raises."""
    block = raw if isinstance(raw, dict) else {}
    return HandConfig(
        enabled=bool(block.get("enabled", False)),
        device=str(block.get("device") or ""),
        width=int(_number(block.get("width"), 640, 80, 3840)),
        height=int(_number(block.get("height"), 480, 60, 2160)),
        max_hz=_number(block.get("max_hz"), 12.0, 1.0, 30.0),
        preview=bool(block.get("preview", False)),
        preview_w=int(_number(block.get("preview_w"), 160, 64, 640)),
        preview_h=int(_number(block.get("preview_h"), 120, 48, 480)),
    )


def body_config(raw: Any) -> BodyConfig:
    """Sanitize one ``body`` block against the pure core's own limits."""
    block = raw if isinstance(raw, dict) else {}
    left, top, right, bottom = bodytrack.sanitize_roi(block.get("roi"))
    return BodyConfig(
        enabled=bool(block.get("enabled", False)),
        device=str(block.get("device") or ""),
        width=int(_number(block.get("width"), 640, 80, 3840)),
        height=int(_number(block.get("height"), 480, 60, 2160)),
        max_hz=_number(block.get("max_hz"), 8.0, 1.0, 15.0),
        max_bodies=int(
            _number(block.get("max_bodies"), bodytrack.BODY_DEFAULT, 1, bodytrack.BODY_MAX)
        ),
        detect_every=int(_number(block.get("detect_every"), 3, 1, 6)),
        score=_number(block.get("score"), 0.5, 0.0, 1.0),
        roi=(left, top, right, bottom),
        preview=bool(block.get("preview", False)),
        preview_w=int(_number(block.get("preview_w"), 320, 64, 640)),
        preview_h=int(_number(block.get("preview_h"), 240, 48, 480)),
        reset=int(_number(block.get("reset"), 0, 0, 2**31)),
    )


def zones_config(raw: Any) -> ZonesConfig:
    """Sanitize one ``zones`` block against the pure core's own limits."""
    block = raw if isinstance(raw, dict) else {}
    return ZonesConfig(
        enabled=bool(block.get("enabled", False)),
        device=str(block.get("device") or ""),
        width=int(_number(block.get("width"), 320, 160, 1920)),
        height=int(_number(block.get("height"), 240, 120, 1080)),
        processing_width=int(
            _number(
                block.get("processing_width"),
                zonetrack.PROCESSING_WIDTH_DEFAULT,
                zonetrack.PROCESSING_WIDTH_MIN,
                zonetrack.PROCESSING_WIDTH_MAX,
            )
        ),
        threshold=_number(
            block.get("threshold"),
            zonetrack.THRESHOLD_DEFAULT,
            zonetrack.THRESHOLD_MIN,
            zonetrack.THRESHOLD_MAX,
        ),
        min_area=_number(
            block.get("min_area"),
            zonetrack.MIN_AREA_DEFAULT,
            zonetrack.MIN_AREA_MIN,
            zonetrack.MIN_AREA_MAX,
        ),
        bg_tau_s=_number(
            block.get("bg_tau_s"),
            zonetrack.BG_TAU_DEFAULT,
            zonetrack.BG_TAU_MIN,
            zonetrack.BG_TAU_MAX,
        ),
        max_hz=_number(block.get("max_hz"), 10.0, 1.0, 30.0),
        mirror=bool(block.get("mirror", False)),
        preview=bool(block.get("preview", False)),
        preview_w=int(_number(block.get("preview_w"), 320, 64, 640)),
        preview_h=int(_number(block.get("preview_h"), 180, 48, 480)),
        reset=int(_number(block.get("reset"), 0, 0, 2**31)),
        zones=zonetrack.sanitize_zones(block.get("zones")),
    )


class ChildConfig:
    """The live configuration, written by the control reader, read by the loop."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._preview_hz = DEFAULT_PREVIEW_HZ
        self._hand = HandConfig()
        self._body = BodyConfig()
        self._zones = ZonesConfig()

    def apply(self, message: trackpipe.Control) -> None:
        with self._lock:
            prefer = bool(message.config.get("prefer_frame_rate", False))
            self._hand = hand_config(message.config.get("hand"))
            self._body = body_config(message.config.get("body"))
            self._zones = zones_config(message.config.get("zones"))
            self._hand.prefer_frame_rate = prefer
            self._body.prefer_frame_rate = prefer
            self._zones.prefer_frame_rate = prefer
            self._preview_hz = _number(
                message.config.get("preview_hz"),
                DEFAULT_PREVIEW_HZ,
                MIN_PREVIEW_HZ,
                MAX_PREVIEW_HZ,
            )

    def preview_hz(self) -> float:
        with self._lock:
            return self._preview_hz

    def loop_hz(self, config: Any) -> float:
        """Capture cadence: inference rate, raised to the preview rate when on."""
        cadence = max(float(config.max_hz), 1.0)
        if getattr(config, "preview", False):
            cadence = max(cadence, self.preview_hz())
        return cadence

    def hand(self) -> HandConfig:
        with self._lock:
            return self._hand

    def body(self) -> BodyConfig:
        with self._lock:
            return self._body

    def zones(self) -> ZonesConfig:
        with self._lock:
            return self._zones

    def owner(self) -> str:
        """One camera owner, same priority as ``vjmixapp/camera.py``."""
        with self._lock:
            if self._hand.enabled:
                return trackpipe.ENGINE_HAND
            if self._body.enabled:
                return trackpipe.ENGINE_BODY
            if self._zones.enabled:
                return trackpipe.ENGINE_ZONES
            return ""


def encode_preview(rgb: np.ndarray, width: int, height: int) -> bytes | None:
    """Downscale one frame and encode it as JPEG; None on any encoder failure."""
    from PIL import Image

    try:
        small = handio.resize_rgb(rgb, (width, height))
        buffer = io.BytesIO()
        Image.fromarray(small).save(buffer, "JPEG", quality=JPEG_QUALITY)
        return buffer.getvalue()
    except (OSError, ValueError):
        return None


def open_camera(
    device: str, width: int, height: int, prefer_frame_rate: bool = False
) -> tuple[Any, str]:
    """Open one V4L2 node; returns ``(source, status)`` with status ``ok`` on success."""
    chosen = device or next(iter(handio.list_devices()), "")
    if not chosen:
        return None, STATUS_NO_CAMERA
    source = handio.open_capture(chosen, width, height, prefer_frame_rate)
    if not source.open():
        stalled = bool(getattr(source, "stalled", False))
        source.close()
        return None, STATUS_STALLED if stalled else STATUS_NO_CAMERA
    return source, "ok"


def read_frame(source: Any) -> tuple[np.ndarray | None, str]:
    """Read one frame, mapping a failure to the engine status vocabulary."""
    rgb = source.read()
    if rgb is not None:
        return rgb, "ok"
    return None, STATUS_LOST if getattr(source, "lost", False) else STATUS_NO_CAMERA


class HandProducer:
    """Capture + palm/landmark inference, one step at a time (no thread of its own)."""

    def __init__(self) -> None:
        self.source: Any = None
        self.model: Any = None
        self.status = STATUS_OFF
        self._last: Any = None
        self._last_infer = 0.0

    def close(self) -> None:
        if self.source is not None:
            self.source.close()
        self.source = None
        self.model = None
        self.status = STATUS_OFF

    def _open(self, config: HandConfig) -> bool:
        source, status = open_camera(
            config.device, config.width, config.height, config.prefer_frame_rate
        )
        if source is None:
            self.status = status
            return False
        self.source = source
        self.model = handio.HandModel()
        return True

    def step(self, config: HandConfig, seq: int) -> trackpipe.TrackingFrame | None:
        """One pass; returns the frame to publish or None when nothing ran."""
        if not handio.available():
            self.status = STATUS_MISSING_DEPS
            return None
        if self.source is None and not self._open(config):
            return None
        started = time.monotonic()
        rgb, status = read_frame(self.source)
        if rgb is None:
            self.status = status
            return None
        if self._preview_only(config, started):
            return self._preview_frame(rgb, config, seq)
        self._last_infer = started
        frame = self._frame(rgb, config, seq, started)
        self._last = frame
        return frame

    def _preview_only(self, config: HandConfig, now: float) -> bool:
        """e94s02: a preview-only pass when the inference interval has not elapsed."""
        if self._last is None or not config.preview:
            return False
        return now - self._last_infer < 1.0 / max(float(config.max_hz), 1.0)

    def _preview_frame(self, rgb: np.ndarray, config: HandConfig, seq: int) -> Any:
        preview = encode_preview(
            rgb, *handio.fit_size(rgb.shape, config.preview_w, config.preview_h)
        )
        now = time.monotonic()
        return replace(
            self._last,
            seq=seq,
            t_mono=now,
            timings=(float(getattr(self.source, "frame_age_ms", 0.0)), 0.0),
            preview=preview,
        )

    def _frame(
        self, rgb: np.ndarray, config: HandConfig, seq: int, started: float
    ) -> trackpipe.TrackingFrame:
        hands = self.model.detect(rgb, now=started)
        now = time.monotonic()
        capture_ms = float(getattr(self.source, "frame_age_ms", 0.0))
        infer_ms = (now - started) * 1000.0
        preview = (
            encode_preview(rgb, *handio.fit_size(rgb.shape, config.preview_w, config.preview_h))
            if config.preview
            else None
        )
        if not hands:
            self.status = STATUS_SEARCHING
            return replace(empty_frame(now, seq, capture_ms, infer_ms), preview=preview)
        hand = hands[0]
        self.status = STATUS_LIVE
        return trackpipe.TrackingFrame(
            engine=trackpipe.ENGINE_HAND,
            seq=seq,
            t_mono=now,
            frame_w=int(rgb.shape[1]),
            frame_h=int(rgb.shape[0]),
            payload=np.asarray(hand.landmarks, dtype=np.float32),
            payload_shape=tuple(int(d) for d in hand.landmarks.shape),
            score=float(hand.score),
            timings=(capture_ms, infer_ms),
            preview=preview,
            label=str(hand.side),
        )


def empty_frame(
    now: float, seq: int, capture_ms: float, infer_ms: float
) -> trackpipe.TrackingFrame:
    """A processed frame with no hand in view: the parent still learns the cadence."""
    return trackpipe.TrackingFrame(
        engine=trackpipe.ENGINE_HAND,
        seq=seq,
        t_mono=now,
        frame_w=0,
        frame_h=0,
        payload=np.zeros(EMPTY_LANDMARKS, dtype=np.float32),
        payload_shape=EMPTY_LANDMARKS,
        score=0.0,
        timings=(capture_ms, infer_ms),
    )


class BodyProducer:
    """Person detector + pose landmarks + the pure continuity tracker, in-process."""

    def __init__(self) -> None:
        self.source: Any = None
        self.detector: Any = None
        self.pose: Any = None
        self.tracker = bodytrack.BodyTracker()
        self.boxes: list[Any] = []
        self.passes = 0
        self.reset_seen = 0
        self.status = STATUS_OFF
        self._last: Any = None
        self._last_infer = 0.0

    def close(self) -> None:
        if self.source is not None:
            self.source.close()
        self.source = None
        self.detector = None
        self.pose = None
        self.status = STATUS_OFF

    def _open(self, config: BodyConfig) -> bool:
        if not bodyio.available():
            self.status = STATUS_MISSING_DEPS
            return False
        source, status = open_camera(
            config.device, config.width, config.height, config.prefer_frame_rate
        )
        if source is None:
            self.status = status
            return False
        self.source = source
        self.detector = bodyio.PersonDetector()
        self.pose = bodyio.PoseEstimator()
        self.tracker = bodytrack.BodyTracker(config.max_bodies)
        self.boxes = []
        self.passes = 0
        return True

    def step(self, config: BodyConfig, seq: int) -> trackpipe.Signals | None:
        if not bodyio.available():
            self.status = STATUS_MISSING_DEPS
            return None
        if self.source is None and not self._open(config):
            return None
        started = time.monotonic()
        rgb, status = read_frame(self.source)
        if rgb is None:
            self.status = status
            return None
        if config.reset != self.reset_seen:
            self.reset_seen = config.reset
            self.tracker.reset()
        if (
            self._last is not None
            and config.preview
            and started - self._last_infer < 1.0 / max(float(config.max_hz), 1.0)
        ):
            return replace(
                self._last,
                seq=seq,
                t_mono=time.monotonic(),
                timings=(float(getattr(self.source, "frame_age_ms", 0.0)), 0.0),
                preview=self._preview(rgb, config),
            )
        self._last_infer = started
        snapshot = self._snapshot(rgb, config, started)
        now = time.monotonic()
        self.status = STATUS_LIVE
        preview = self._preview(rgb, config)
        signals = trackpipe.Signals(
            engine=trackpipe.ENGINE_BODY,
            seq=seq,
            t_mono=now,
            values=snapshot,
            timings=(float(getattr(self.source, "frame_age_ms", 0.0)), (now - started) * 1000.0),
            preview=preview,
        )
        self._last = signals
        return signals

    def _snapshot(self, rgb: np.ndarray, config: BodyConfig, started: float) -> dict[str, Any]:
        self.passes += 1
        if self.passes % max(1, config.detect_every) == 1 or not self.boxes:
            self.boxes = self.detector.detect(rgb, roi=config.roi)
        height, width = rgb.shape[:2]
        detections = []
        for person in self.boxes[: config.max_bodies]:
            landmarks, confidence = self.pose.estimate(rgb, person)
            if landmarks is not None and confidence >= config.score:
                detections.append(bodytrack.BodyDetection(landmarks, confidence))
        return self.tracker.step(detections, width, height, started)

    def _preview(self, rgb: np.ndarray, config: BodyConfig) -> bytes | None:
        if not config.preview:
            return None
        overlay = bodytrack.draw_overlay(rgb, bodytrack.landmarks_by_slot(self.tracker))
        return encode_preview(
            overlay, *handio.fit_size(overlay.shape, config.preview_w, config.preview_h)
        )


class ZonesProducer:
    """The pure zone engine on the captured frame; the child draws its overlay."""

    def __init__(self) -> None:
        self.source: Any = None
        self.engine: Any = None
        self.key: tuple[Any, ...] | None = None
        self.reset_seen = 0
        self.status = STATUS_OFF
        self._last: Any = None
        self._last_infer = 0.0

    def close(self) -> None:
        if self.source is not None:
            self.source.close()
        self.source = None
        self.engine = None
        self.key = None
        self.status = STATUS_OFF

    def _engine_for(self, config: ZonesConfig) -> Any:
        key = (
            config.processing_width,
            config.threshold,
            config.min_area,
            config.bg_tau_s,
            config.mirror,
            tuple(
                (zone["id"], tuple(tuple(point) for point in zone["points"]))
                for zone in config.zones
            ),
        )
        if self.engine is None or self.key != key:
            self.engine = zonetrack.ZoneEngine(
                config.zones,
                processing_width=config.processing_width,
                threshold=config.threshold,
                min_area=config.min_area,
                bg_tau_s=config.bg_tau_s,
                mirror=config.mirror,
            )
            self.key = key
        return self.engine

    def _open(self, config: ZonesConfig) -> bool:
        source, status = open_camera(
            config.device, config.width, config.height, config.prefer_frame_rate
        )
        if source is None:
            self.status = status
            return False
        self.source = source
        return True

    def step(self, config: ZonesConfig, seq: int) -> trackpipe.Signals | None:
        if self.source is None and not self._open(config):
            return None
        started = time.monotonic()
        rgb, status = read_frame(self.source)
        if rgb is None:
            self.status = status
            return None
        engine = self._engine_for(config)
        if config.reset != self.reset_seen:
            self.reset_seen = config.reset
            engine.reset_activity()
        if (
            self._last is not None
            and config.preview
            and started - self._last_infer < 1.0 / max(float(config.max_hz), 1.0)
        ):
            return replace(
                self._last,
                seq=seq,
                t_mono=time.monotonic(),
                timings=(float(getattr(self.source, "frame_age_ms", 0.0)), 0.0),
                preview=self._preview(rgb, config, self._last.values),
            )
        self._last_infer = started
        snapshot = engine.step(rgb, started)
        now = time.monotonic()
        self.status = STATUS_LIVE
        signals = trackpipe.Signals(
            engine=trackpipe.ENGINE_ZONES,
            seq=seq,
            t_mono=now,
            values=snapshot,
            timings=(float(getattr(self.source, "frame_age_ms", 0.0)), (now - started) * 1000.0),
            preview=self._preview(rgb, config, snapshot),
        )
        self._last = signals
        return signals

    def _preview(
        self, rgb: np.ndarray, config: ZonesConfig, snapshot: dict[str, Any]
    ) -> bytes | None:
        if not config.preview:
            return None
        size = handio.fit_size(rgb.shape, config.preview_w, config.preview_h)
        small = handio.resize_rgb(rgb, size)
        overlay = zonetrack.draw_overlay(small, config.zones, snapshot, mirror=config.mirror)
        return encode_preview(overlay, *size)


class ChildRuntime:
    """The socket loop: drive the active producer, publish envelopes, take control."""

    def __init__(self, conn: socket.socket) -> None:
        self.conn = conn
        self.config = ChildConfig()
        self.hand = HandProducer()
        self.body = BodyProducer()
        self.zones = ZonesProducer()
        self.sequence = 0
        self.last_beat = 0.0
        self.last_progress = time.monotonic()
        self.stopping = threading.Event()
        # Injected so a test can observe the exit instead of dying with pytest.
        self._exit: Any = os._exit

    def _producer(self) -> tuple[Any, Any, str]:
        owner = self.config.owner()
        if owner == trackpipe.ENGINE_HAND:
            return self.hand, self.config.hand(), owner
        if owner == trackpipe.ENGINE_BODY:
            return self.body, self.config.body(), owner
        if owner == trackpipe.ENGINE_ZONES:
            return self.zones, self.config.zones(), owner
        return None, None, ""

    def _close_inactive(self, owner: str) -> None:
        for name, producer in (
            (trackpipe.ENGINE_HAND, self.hand),
            (trackpipe.ENGINE_BODY, self.body),
            (trackpipe.ENGINE_ZONES, self.zones),
        ):
            if name != owner and producer.source is not None:
                producer.close()

    def send(self, envelope: trackpipe.Envelope) -> None:
        self.conn.sendall(trackpipe.encode(envelope))

    def _control_loop(self) -> None:
        self.conn.settimeout(CONTROL_TIMEOUT_S)
        while not self.stopping.is_set():
            try:
                body = trackpipe.read_body(self.conn)
            except TimeoutError:
                # BUG-2026-10-28: a read timeout is NOT a disconnect. Treating it
                # as one made the child exit ~0.2 s after the handshake, so the
                # parent restarted it forever and hit the decision dialog.
                continue
            except (OSError, trackpipe.TrackPipeError):
                # The parent is gone (or asked us to stop). Exit NOW: the camera
                # belongs to this process, and waiting for the main loop to notice
                # would keep the device busy for up to STUCK_ITERATION_S — the next
                # VJmix would start with "camera already in use" (rig 2026-10-29).
                self.stopping.set()
                self._exit(0)
                return
            if not body:
                # clean EOF: the parent is gone, release the camera NOW
                self.stopping.set()
                self._exit(0)
                return
            try:
                message = trackpipe.decode(body)
            except trackpipe.TrackPipeError:
                continue
            if isinstance(message, trackpipe.Control):
                self.config.apply(message)

    def _wait_with_beats(self, status: str) -> None:
        """A failed pass rests, but keeps announcing liveness (the parent's watchdog)."""
        deadline = time.monotonic() + RETRY_SLEEP_S
        while time.monotonic() < deadline and not self.stopping.is_set():
            self._beat(time.monotonic(), status)
            time.sleep(RETRY_BEAT_S)

    def _beat(self, now: float, status: str) -> None:
        if now - self.last_beat >= HEARTBEAT_S:
            self.send(trackpipe.Beat(now, status))
            self.last_beat = now

    def stuck(self) -> bool:
        """True when no iteration completed for STUCK_ITERATION_S (a blocked C call)."""
        return time.monotonic() - self.last_progress > STUCK_ITERATION_S

    def _watchdog(self) -> None:
        while not self.stopping.is_set():
            time.sleep(WATCHDOG_POLL_S)
            if self.stuck():
                print(
                    f"trackd: no progress for {STUCK_ITERATION_S:.0f}s, exiting stuck",
                    file=sys.stderr,
                )
                sys.stderr.flush()
                os._exit(EXIT_STUCK)

    def run(self) -> int:
        threading.Thread(target=self._control_loop, daemon=True, name="trackd-control").start()
        threading.Thread(target=self._watchdog, daemon=True, name="trackd-watchdog").start()
        while not self.stopping.is_set():
            self._iteration()
        self.hand.close()
        self.body.close()
        self.zones.close()
        return 0

    def _iteration(self) -> None:
        producer, config, owner = self._producer()
        try:
            if producer is None:
                self._close_inactive("")
                self._beat(time.monotonic(), STATUS_OFF)
                self.last_progress = time.monotonic()
                time.sleep(IDLE_SLEEP_S)
                return
            self._close_inactive(owner)
            self.sequence += 1
            envelope = producer.step(config, self.sequence)
            now = time.monotonic()
            if envelope is None:
                self._wait_with_beats(producer.status)
                self.last_progress = time.monotonic()
                return
            self.send(envelope)
            self._beat(now, producer.status)
            self.last_progress = time.monotonic()
            time.sleep(1.0 / self.config.loop_hz(config))
        except Exception as exc:  # the child must survive anything (see pyproject)
            self._beat(time.monotonic(), STATUS_LOST)
            print(f"trackd: {exc!r}", file=sys.stderr)
            time.sleep(0.5)


def _prctl_parent_death_signal() -> bool:
    """Best-effort Linux PR_SET_PDEATHSIG(SIGKILL); False elsewhere, never raises."""
    if sys.platform != "linux":
        return False
    try:
        import ctypes

        libc = ctypes.CDLL(None, use_errno=True)
        return libc.prctl(PR_SET_PDEATHSIG, int(signal.SIGKILL), 0, 0, 0) == 0
    except Exception:
        return False


def install_parent_death_guard(
    parent_pid: int | None = None,
    *,
    poll: float = PARENT_GUARD_POLL_S,
    getppid: Callable[[], int] = os.getppid,
    exit_process: Callable[[int], None] = os._exit,
    stop: threading.Event | None = None,
) -> threading.Thread | None:
    """Exit this child when its parent dies (BUG-2026-11-05T230841).

    Two belts: the kernel's ``PR_SET_PDEATHSIG`` (Linux) and a polling thread
    that compares ``getppid()`` with the pid captured at startup — the portable
    path, and the one that fires even if the parent dies while no thread can
    read the socket. A parent already gone at install time exits immediately.
    Returns the guard thread, or None when the parent was already gone.
    """
    expected = int(os.getppid() if parent_pid is None else parent_pid)
    _prctl_parent_death_signal()
    if getppid() != expected:
        exit_process(EXIT_PARENT_GONE)
        return None

    def _watch() -> None:
        while stop is None or not stop.is_set():
            if stop is not None:
                stop.wait(poll)
            else:
                time.sleep(poll)
            if getppid() != expected:
                exit_process(EXIT_PARENT_GONE)
                return

    thread = threading.Thread(target=_watch, daemon=True, name="trackd-parent-guard")
    thread.start()
    return thread


def _install_signal_handlers(runtime: ChildRuntime) -> None:
    for signal_name in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signal_name, lambda *_: runtime.stopping.set())


def main() -> int:
    """Entry point: connect to the parent, handshake, then serve until told to stop."""
    parent_pid = os.getppid()
    install_parent_death_guard(parent_pid)
    socket_path = os.environ.get(ENV_SOCKET, "")
    token = os.environ.get(ENV_TOKEN, "")
    if not socket_path or not token:
        print("trackd: missing VJMIX_TRACK_SOCKET / VJMIX_TRACK_TOKEN", file=sys.stderr)
        return 2
    conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    conn.connect(socket_path)
    conn.sendall(trackpipe.encode(trackpipe.Handshake(trackpipe.PROTOCOL_VERSION, token)))
    runtime = ChildRuntime(conn)
    _install_signal_handlers(runtime)
    try:
        return runtime.run()
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
