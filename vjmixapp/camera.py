"""One camera owner for the two camera engines (e88s02).

The webcam hand engine (e87) and the stage-zones engine both open the same
V4L2 device, and two simultaneous opens are the bug already measured in e87
(BUG-2026-10-23T220000: a wedged driver and a dead worker). This module is the
single policy point: the boot, the hand Enable path and the zones Enable path
all write the owner here, so the two persisted flags can never drift.

The Leap is a different device and is NOT part of this policy: it may run while
the zones engine reads the camera.
"""

from vjmixapp import state

CAMERA_NONE = "none"
CAMERA_HAND = "hand"
CAMERA_BODY = "body"
CAMERA_ZONES = "zones"
CAMERA_ENGINES: tuple[str, ...] = (CAMERA_NONE, CAMERA_HAND, CAMERA_BODY, CAMERA_ZONES)

# Local copy of the hand provider name: `handtrack` imports this module (the
# enable path delegates here), so importing it back would be a cycle.
HAND_PROVIDER_WEBCAM = "webcam"


def camera_engine() -> str:
    """The engine that owns the camera right now (hand wins a both-true file)."""
    if state.handtrack_enabled and state.hand_provider == HAND_PROVIDER_WEBCAM:
        return CAMERA_HAND
    if state.body_enabled:
        return CAMERA_BODY
    if state.zones_enabled:
        return CAMERA_ZONES
    return CAMERA_NONE


def zones_engine_active() -> bool:
    """Is the zones engine the active camera owner?"""
    return camera_engine() == CAMERA_ZONES


def set_camera_engine(engine: str) -> bool:
    """Make ``engine`` the camera owner: STATE only, never the config.

    The engine switches are PROJECT content (specs/TRACKING_PERSISTENCE_LATEST.md):
    "this show uses the hands" belongs to the show, while the camera device and
    its options stay in the app config (the rig). Writing them here would make a
    per-machine file decide what a performance uses — the exact confusion that
    left a checkbox unticked while an engine ran (rig 2026-10-29).

    ``hand`` turns the zones engine off, ``body``/``zones`` turn the others off,
    ``none`` turns all three off. The return value is kept for the callers that
    report the write; there is no write to fail any more, so it is always True.
    """
    if engine not in CAMERA_ENGINES:
        engine = CAMERA_NONE
    state.handtrack_enabled = engine == CAMERA_HAND
    state.body_enabled = engine == CAMERA_BODY
    state.zones_enabled = engine == CAMERA_ZONES
    return True
