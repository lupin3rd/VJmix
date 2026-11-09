"""The tracker-child supervisor: spawn, handshake, heartbeat, restart (e90s02).

The child (``vjmixapp/trackd.py``) owns the camera and the models. This module
owns the child: it spawns it, validates the handshake (protocol version + a
per-session token), reads its envelopes, watches the heartbeat, and restarts it
with backoff. After ``RESTART_LIMIT`` failures it stops restarting, raises
``state.tracking_needs_decision`` and reports ``inline`` so the app keeps
working; e90s05 turns that flag into the operator dialog.

Invariant that matters more than any number here: **a dead child never takes
the app down**. Every failure is a status, never an exception on the app thread.
The last accepted frame stays in place (hold): no zeroing, no synthetic frame.
"""

import contextlib
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable
from typing import Any

from vjmixapp import state, trackpipe
from vjmixapp.config import load_config, save_config
from vjmixapp.queues import append_log, log_error, log_warn

STATUS_OFF = "off"
STATUS_STARTING = "starting"
STATUS_LIVE = "live"
STATUS_STALLED = "stalled"
STATUS_OFFLINE = "offline"
STATUS_MISMATCH = "mismatch"
STATUS_INLINE = "inline"

HEARTBEAT_TIMEOUT_S = 3.0
# A cold child imports numpy/PIL/onnxruntime bindings before it can say hello;
# 10 s is generous on a slow disk or inside the AppImage, and a hung child is
# still caught by the heartbeat right after.
HANDSHAKE_TIMEOUT_S = 10.0
# A connection that stayed healthy this long clears the failure streak, so
# three failures means "three CONSECUTIVE failures", not "three over an evening".
LIVE_RESET_S = 15.0
RESTART_LIMIT = 3
RESTART_DELAY_S = 1.0
RESTART_DELAY_MAX_S = 8.0
CONNECT_TIMEOUT_S = 5.0
READ_TIMEOUT_S = 0.5
SUPERVISE_SLEEP_S = 0.2
SOCKET_PREFIX = "vjmix-track"
# BUG-2026-11-05T230841: the spawn polls the listener in short slices so a
# confirmed Exit can CANCEL an accept in flight instead of waiting it out.
SPAWN_POLL_S = 0.1


class SpawnCancelled(Exception):
    """The supervisor was stopped while spawn was still waiting for the child.

    Carries the process it already started, so the caller can make sure it is
    dead: the whole point of the fix is that a stopped app never leaks a child.
    """

    def __init__(self, process: Any = None) -> None:
        super().__init__("tracker spawn cancelled")
        self.process = process


HANDSHAKE_OK = "ok"
HANDSHAKE_TIMEOUT = "timeout"
HANDSHAKE_MISMATCH = "mismatch"

ENV_SOCKET = "VJMIX_TRACK_SOCKET"
ENV_TOKEN = "VJMIX_TRACK_TOKEN"

HOST_INLINE = "inline"
HOST_CHILD = "child"
HOSTS: tuple[str, ...] = (HOST_INLINE, HOST_CHILD)
CHILD_MODULE = "vjmixapp.trackd"


def socket_path_for(pid: int) -> str:
    """The per-process socket path (a crash cannot leave the NEXT run's path)."""
    return os.path.join(tempfile.gettempdir(), f"{SOCKET_PREFIX}-{pid}.sock")


def forward_child_stderr(stream: Any) -> None:
    """Copy the child's stderr into the Logs window (the only window into it).

    Before this, the child's stderr went to /dev/null: a camera that never
    opened looked exactly like a wedged process, and the operator had no
    evidence at all.
    """
    if stream is None:
        return
    try:
        for line in stream:
            text = str(line).strip()
            if text:
                append_log("Tracker child", text[:400])
    except (OSError, ValueError):
        return


def spawn_child(
    socket_path: str,
    token: str,
    argv: list[str] | None = None,
    cancel: threading.Event | None = None,
) -> tuple[Any, socket.socket]:
    """Start the child and return ``(process, connected_socket)``.

    The socket is created and listened on BEFORE the spawn, so the child can
    connect immediately and a crash cannot leave a stale path behind. The accept
    is polled in short slices: when ``cancel`` is set (a confirmed Exit, a host
    change, a restart) the process is killed and ``SpawnCancelled`` is raised,
    so a stop can never leave a freshly spawned child behind
    (BUG-2026-11-05T230841).
    """
    with contextlib.suppress(FileNotFoundError):
        os.unlink(socket_path)
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(socket_path)
    os.chmod(socket_path, 0o600)
    server.listen(1)
    server.settimeout(SPAWN_POLL_S)
    env = os.environ.copy()
    env[ENV_SOCKET] = socket_path
    env[ENV_TOKEN] = token
    command = argv or [sys.executable, "-m", CHILD_MODULE]
    process = subprocess.Popen(
        command,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    threading.Thread(
        target=forward_child_stderr, args=(process.stderr,), daemon=True, name="trackchild-log"
    ).start()
    conn: socket.socket | None = None
    deadline = time.monotonic() + CONNECT_TIMEOUT_S
    try:
        while conn is None:
            if cancel is not None and cancel.is_set():
                raise SpawnCancelled(process)
            if time.monotonic() >= deadline:
                raise TimeoutError("tracker child did not connect")
            try:
                conn, _ = server.accept()
            except TimeoutError:
                continue
    except BaseException:
        # Any failure (cancel, timeout, a cancelled accept) owns the process we
        # just started: kill it here, the supervisor never sees a handle.
        _kill_quietly(process)
        raise
    finally:
        server.close()
        with contextlib.suppress(FileNotFoundError):
            os.unlink(socket_path)
    conn.settimeout(HANDSHAKE_TIMEOUT_S)
    return process, conn


def _wait_quietly(process: Any, timeout: float = 2.0) -> bool:
    """True when the process was reaped; False on a timeout (never raises)."""
    try:
        process.wait(timeout=timeout)
        return True
    except (subprocess.TimeoutExpired, OSError):
        return False


def _kill_quietly(process: Any, timeout: float = 2.0) -> None:
    """terminate -> kill -> give up, never raising (BUG-2026-11-05T230841)."""
    if process is None or process.poll() is not None:
        return
    with contextlib.suppress(Exception):
        process.terminate()
    with contextlib.suppress(Exception):
        process.wait(timeout=timeout)
        return
    with contextlib.suppress(Exception):
        process.kill()
        process.wait(timeout=timeout)


def _process_dead(process: Any) -> bool:
    return process is None or process.poll() is not None


class TrackerChild:
    """The parent end of one child session, supervised on its own thread."""

    def __init__(
        self,
        spawn: Callable[[str, str], tuple[Any, socket.socket]] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        # The default spawner takes the supervisor's stop flag, so a confirmed
        # Exit (or a host change) cancels an accept already in flight.
        self._spawn = spawn if spawn is not None else self._default_spawn
        self._clock = clock
        self._lock = threading.RLock()
        self._frame_ready = threading.Condition(self._lock)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._generation = 0
        self._reader: threading.Thread | None = None
        self._conn: socket.socket | None = None
        self._process: Any = None
        self._status = STATUS_OFF
        self._latest: dict[str, trackpipe.TrackingFrame | trackpipe.Signals] = {}
        self._guard = trackpipe.SequenceGuard()
        self._config: dict[str, Any] = {}
        self._sent_config: str = ""
        self._last_beat = 0.0
        self._live_since = 0.0
        self._failures = 0
        self._next_retry = 0.0
        self._on_exhausted: Callable[[], None] | None = None

    # -- read-only view -----------------------------------------------------

    def status(self) -> str:
        with self._lock:
            return self._status

    def alive(self) -> bool:
        with self._lock:
            return self._conn is not None and not _process_dead(self._process)

    def latest(self, engine: str) -> trackpipe.TrackingFrame | trackpipe.Signals | None:
        with self._lock:
            return self._latest.get(engine)

    def wait_next(
        self, engine: str, after_seq: int, timeout: float
    ) -> trackpipe.TrackingFrame | trackpipe.Signals | None:
        """Block until the engine has a frame with a NEW sequence (e94s03).

        The reader thread has already stored it; this removes the 200 ms polling
        sleep that made the parent miss the freshest frame. None on timeout.
        """
        deadline = self._clock() + max(0.0, float(timeout))
        with self._frame_ready:
            while not self._stop.is_set():
                frame = self._latest.get(engine)
                if frame is not None and frame.seq != after_seq:
                    return frame
                remaining = deadline - self._clock()
                if remaining <= 0.0:
                    return None
                self._frame_ready.wait(remaining)
        return None

    def failures(self) -> int:
        with self._lock:
            return self._failures

    def process_id(self) -> int | None:
        """The child's pid while it runs (the drill script kills it)."""
        with self._lock:
            process = self._process
        return None if process is None else int(getattr(process, "pid", 0))

    def on_exhausted(self, callback: Callable[[], None]) -> None:
        self._on_exhausted = callback

    # -- lifecycle ----------------------------------------------------------

    def start(self, config: dict[str, Any] | None = None) -> None:
        if config is not None:
            self.configure(config)
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._generation += 1
        generation = self._generation
        self._thread = threading.Thread(
            target=self._supervise, args=(generation,), daemon=True, name="trackchild"
        )
        self._thread.start()

    def stop(self) -> None:
        """Stop the session AND forget the thread, so start() can run again.

        BUG-2026-10-28: stop() left `_thread` set, so after a panic or a
        force-inline the supervisor could never be started again in that
        session — the host said child while no child existed.
        """
        self._stop.set()
        self._generation += 1  # the old supervisor leaves on its next wait
        self._thread = None
        self._reader = None
        self._close()
        with self._lock:
            self._status = STATUS_OFF

    def restart(self) -> None:
        """Operator-visible retry: forget the failures and connect again now."""
        with self._lock:
            self._failures = 0
            self._next_retry = 0.0
            state.tracking_restarts = 0
            state.tracking_needs_decision = False
        self._close()

    def configure(self, config: dict[str, Any]) -> None:
        with self._lock:
            self._config = config
        self._send_config()

    def _send_config(self) -> None:
        with self._lock:
            conn = self._conn
            payload = trackpipe.Control(dict(self._config))
            encoded = repr(sorted(payload.config.items()))
            if conn is None or encoded == self._sent_config:
                return
            self._sent_config = encoded
        try:
            conn.sendall(trackpipe.encode(payload))
        except OSError as exc:
            self._note(f"config send failed: {exc}")

    # -- supervision --------------------------------------------------------

    def _supervise(self, generation: int) -> None:
        while not self._stop.is_set() and generation == self._generation:
            self._tick()
            self._stop.wait(SUPERVISE_SLEEP_S)

    def _tick(self) -> None:
        with self._lock:
            conn, process = self._conn, self._process
            stale = conn is not None and self._clock() - self._last_beat > HEARTBEAT_TIMEOUT_S
        if conn is None:
            if self._failures < RESTART_LIMIT and self._clock() >= self._next_retry:
                self._connect()
            return
        if _process_dead(process):
            code = getattr(process, "returncode", None)
            self._fail(STATUS_OFFLINE, f"process exited ({code})")
        elif stale:
            self._fail(STATUS_STALLED, "heartbeat lost")
        else:
            self._clear_streak_if_healthy()

    def _clear_streak_if_healthy(self) -> None:
        """A long healthy run resets the streak: three strikes must be CONSECUTIVE."""
        with self._lock:
            healthy = self._clock() - self._live_since
            if self._failures == 0 or healthy < LIVE_RESET_S:
                return
            self._failures = 0
            self._status = STATUS_LIVE
        state.tracking_restarts = 0

    def _default_spawn(self, socket_path: str, token: str) -> tuple[Any, socket.socket]:
        """The real spawner, wired to this supervisor's stop flag (e95 bugfix)."""
        return spawn_child(socket_path, token, cancel=self._stop)

    def _connect(self) -> None:
        with self._lock:
            self._status = STATUS_STARTING
            token = os.urandom(16).hex()
            generation = self._generation
        try:
            process, conn = self._spawn(socket_path_for(os.getpid()), token)
        except SpawnCancelled:
            return  # a stop cancelled the spawn; spawn_child killed the child
        except (OSError, subprocess.SubprocessError) as exc:
            self._fail(STATUS_OFFLINE, f"spawn failed: {exc}")
            return
        # BUG-2026-11-05T230841: publish the handle BEFORE the handshake (which
        # can take 10 s), so a stop() in that window can terminate it. The old
        # order left _process None and leaked the child.
        with self._lock:
            self._process = process
        reason = self._handshake(conn, token)
        with self._lock:
            stopped = self._stop.is_set() or generation != self._generation
        if stopped:
            # stop() may already have killed it; this is the belt-and-braces.
            _kill_quietly(process)
            with contextlib.suppress(OSError):
                conn.close()
            with self._lock:
                if self._process is process:
                    self._process = None
            return
        if reason != HANDSHAKE_OK:
            _kill_quietly(process)
            with contextlib.suppress(OSError):
                conn.close()
            with self._lock:
                if self._process is process:
                    self._process = None
            self._handshake_failed(reason)
            return
        conn.settimeout(READ_TIMEOUT_S)
        with self._lock:
            self._conn = conn
            self._process = process
            self._status = STATUS_LIVE
            self._last_beat = self._clock()
            self._live_since = self._last_beat
            self._sent_config = ""
            # BUG-2026-10-28 (operator rig): a restarted child starts its
            # sequence at 1, so the old high-water mark would reject every new
            # frame as stale (live host, frozen values). A new session is a new
            # sequence space; the HELD frame stays until the first new one lands.
            self._guard.reset()
        state.tracking_status = STATUS_LIVE
        self._send_config()
        self._reader = threading.Thread(target=self._read_loop, args=(conn,), daemon=True)
        self._reader.start()

    def _handshake(self, conn: socket.socket, token: str) -> str:
        """Return ``ok``, ``mismatch`` (terminal) or ``timeout`` (retryable)."""
        try:
            body = trackpipe.read_body(conn)
            message = trackpipe.decode(body)
        except TimeoutError:
            return HANDSHAKE_TIMEOUT
        except (OSError, trackpipe.TrackPipeError):
            return HANDSHAKE_TIMEOUT
        if not isinstance(message, trackpipe.Handshake) or message.token != token:
            return HANDSHAKE_MISMATCH
        return HANDSHAKE_OK

    def _handshake_failed(self, reason: str) -> None:
        if reason == HANDSHAKE_MISMATCH:
            self._terminal_mismatch("handshake token or version mismatch")
        else:
            self._fail(STATUS_OFFLINE, "handshake timeout")

    def _terminal_mismatch(self, detail: str) -> None:
        """A wrong version/token never heals by retrying: stop and ask the operator."""
        with self._lock:
            self._status = STATUS_MISMATCH
            self._failures = RESTART_LIMIT
        state.tracking_status = STATUS_MISMATCH
        state.tracking_needs_decision = True
        log_error("Tracking", detail)

    # -- reader -------------------------------------------------------------

    def _read_loop(self, conn: socket.socket) -> None:
        while not self._stop.is_set():
            try:
                body = trackpipe.read_body(conn)
            except TimeoutError:
                continue
            except (OSError, trackpipe.TrackPipeError) as exc:
                self._note(f"read failed: {exc}")
                return
            if not body:
                self._note("child closed the socket")
                return
            self._accept(body)

    def _accept(self, body: bytes) -> None:
        try:
            message = trackpipe.decode(body)
        except trackpipe.TrackPipeError as exc:
            log_warn("Tracking", f"rejected message: {exc}")
            return
        if isinstance(message, trackpipe.Beat):
            self._beat(message)
        elif isinstance(message, (trackpipe.TrackingFrame, trackpipe.Signals)):
            self._frame(message)

    def _beat(self, beat: trackpipe.Beat) -> None:
        with self._lock:
            self._last_beat = self._clock()
            if beat.status:
                state.tracking_engine_status = beat.status

    def _frame(self, frame: trackpipe.TrackingFrame | trackpipe.Signals) -> None:
        with self._lock:
            if not self._guard.accept(frame):
                return
            self._latest[frame.engine] = frame
            self._frame_ready.notify_all()
        state.tracking_frame_age = 0.0

    # -- failures -----------------------------------------------------------

    def _note(self, detail: str) -> None:
        """A reader-side problem: the supervisor sees the dead socket and acts."""
        with self._lock:
            if self._status == STATUS_LIVE:
                self._status = STATUS_OFFLINE
        log_warn("Tracking", detail)

    def _fail(self, status: str, detail: str) -> None:
        with self._lock:
            self._failures += 1
            failures = self._failures
            delay = min(RESTART_DELAY_MAX_S, RESTART_DELAY_S * (2 ** (failures - 1)))
            self._status = status
            self._next_retry = self._clock() + delay
        state.tracking_restarts = failures
        state.tracking_status = status
        log_error("Tracking", f"child {detail} ({failures}/{RESTART_LIMIT})")
        self._close()
        if failures >= RESTART_LIMIT:
            self._exhausted()

    def _exhausted(self) -> None:
        with self._lock:
            self._status = STATUS_INLINE
        state.tracking_status = STATUS_INLINE
        state.tracking_needs_decision = True
        if self._on_exhausted is not None:
            self._on_exhausted()

    def _close(self) -> None:
        with self._lock:
            conn, process, self._conn, self._process = self._conn, self._process, None, None
            self._sent_config = ""
        if conn is not None:
            with contextlib.suppress(OSError):
                conn.shutdown(socket.SHUT_RDWR)
            conn.close()
        if process is not None and process.poll() is None:
            process.terminate()
            if not _wait_quietly(process):
                process.kill()
                if not _wait_quietly(process):
                    # A D-state camera open cannot be interrupted; say so instead
                    # of hiding the failure (shutdown used to swallow it).
                    log_warn(
                        "Tracking",
                        "tracker child survived SIGKILL - the camera may stay busy "
                        "until the device call returns",
                    )


def host_from_config(cfg: dict[str, Any]) -> str:
    """The configured host, healed to ``inline`` for an unknown value."""
    block = cfg.get("tracking")
    host = block.get("host") if isinstance(block, dict) else None
    return host if host in HOSTS else HOST_INLINE


def prefer_frame_rate_from_config(cfg: dict[str, Any]) -> bool:
    """The machine preference: keep the sensor frame rate (e94s01)."""
    block = cfg.get("tracking")
    return bool(block.get("prefer_frame_rate", False)) if isinstance(block, dict) else False


def init_from_config(cfg: dict[str, Any]) -> None:
    """Boot: mirror the persisted host and camera preference (never spawns)."""
    state.tracking_host = host_from_config(cfg)
    state.tracking_prefer_frame_rate = prefer_frame_rate_from_config(cfg)


def set_prefer_frame_rate(enabled: bool) -> bool:
    """Persist the frame-rate preference (machine settings, not project content)."""
    state.tracking_prefer_frame_rate = bool(enabled)
    cfg = load_config()
    block = cfg.get("tracking")
    if not isinstance(block, dict):
        block = {}
        cfg["tracking"] = block
    block["prefer_frame_rate"] = bool(enabled)
    if save_config(cfg):
        return True
    log_error("Tracking", "frame-rate preference not persisted - this session only")
    return False


def set_host(host: str) -> bool:
    """Switch the session host and persist it; report the write."""
    chosen = host if host in HOSTS else HOST_INLINE
    state.tracking_host = chosen
    cfg = load_config()
    block = cfg.get("tracking")
    if not isinstance(block, dict):
        block = {}
        cfg["tracking"] = block
    block["host"] = chosen
    if save_config(cfg):
        return True
    log_error("Tracking", f"host {chosen!r} not persisted - this session only")
    return False


def available() -> bool:
    """Is the child runnable here? (same interpreter, module present, unix sockets)."""
    if not hasattr(socket, "AF_UNIX"):
        return False
    return shutil.which(sys.executable) is not None
