"""Cue engine for VJmix (e35s02).

A cue-list mapping's "cue" (vjmixapp/mapper.py) is an ordered macro of rows:
property rows send one /vimix/<target>/<property> float, wait rows pause the
run clock, mapper rows activate another mapping (a button press or another
cue-list run). WORKER-SAFE: this module never imports dpg (HIGH-1) — the run
state lives in ``state.cue_runs`` and the composition-root scheduler thread
calls ``tick`` with a monotonic clock.

Execution model (user decisions, 2026-09-06): ONE sequential clock over the
levels in increasing order and the rows in list order inside a level — the
level alone decides the wave (global level rule, nodo 2). ``gap_ms`` (the
per-cue "ms between levels", default 0 = cascade without delays, nodo 1/B) is
added between consecutive non-empty levels; a wait row advances the clock and
delays the remaining rows of its level AND all deeper levels. A mapper row
activates its target with ``allow_restart=False`` — a target that is already
running in the activation chain (including the running cue itself) is a no-op
(cycle guard); only a real trigger press may restart (e35s03).
"""

from typing import Any

from vjmixapp import catalog, mapper, osc, shadercode, sourcekind, state
from vjmixapp.constants import IO_MONITOR_KIND_CUE
from vjmixapp.osc import osc_client
from vjmixapp.queues import append_log, log_warn

_PLAN_SEND = "send"
_PLAN_ACTIVATE = "activate"


def build_cue_plan(cue: dict[str, Any], target_id: str) -> list[tuple[float, str, Any]]:
    """Pure, deterministic plan builder (e35s02) — no I/O, no wall clock.

    Returns dispatch entries ``(time_ms, action, payload)`` sorted by time:
    levels in increasing order, rows in list order inside a level, the clock
    advancing ``gap_ms`` per level STEP (a row at level L starts L*gap after
    the cue's start, plus the waits it follows — the user's "every indent
    level = one configurable delay", nodo 1/B) and wait rows advancing the
    clock. Actions: ``send`` with {property, value} (to the mapping's target)
    and ``activate`` with {mapping_id}. With gap 0 and no waits every action
    lands at t=0 — the user's "default ms 0 = a cascata senza ritardi".
    """
    rows = list(cue.get("rows", []))
    ordered = sorted(enumerate(rows), key=lambda pair: (int(pair[1]["level"]), pair[0]))
    entries: list[tuple[float, str, Any]] = []
    t = 0.0
    gap_ms = float(cue.get("gap_ms") or 0.0)
    last_level: int | None = None
    for _, row in ordered:
        level = int(row["level"])
        if last_level is not None and level > last_level:
            t += (level - last_level) * gap_ms
        last_level = level
        kind = row.get("kind")
        payload = row.get("payload", {})
        if kind in ("property", "burst"):
            prop = str(payload.get("property") or "")
            if prop:
                entry: dict[str, Any] = {"property": prop}
                if isinstance(payload.get("values"), list):
                    entry["values"] = list(payload["values"])
                else:
                    entry["value"] = float(payload.get("value", 0.0))
                if payload.get("ms"):
                    entry["ms"] = float(payload["ms"])
                entries.append((t, _PLAN_SEND, entry))
        elif kind == "wait":
            t += float(payload.get("ms") or 0.0)
        elif kind == "mapper":
            mapping_id = payload.get("mapping_id")
            if mapping_id:
                entries.append((t, _PLAN_ACTIVATE, {"mapping_id": int(mapping_id)}))
    return entries


def cue_is_running(mapping_id: int) -> bool:
    """True when the mapping's cue is in the active run chain (e35s02)."""
    return any(run["mapping_id"] == mapping_id for run in state.cue_runs)


def cue_start(mapping_id: int, *, allow_restart: bool = False) -> bool:
    """Run (or restart) a mapping's cue on the engine clock (e35s02).

    A real trigger press (e35s03) calls this with ``allow_restart=True``: a
    cue that is already running restarts from the beginning. Every gate is a
    logged no-op returning False: the mapping must exist and be a cue-list
    control, be enabled (e24), carry a non-empty cue and have a target.
    """
    return _cue_start(mapping_id, ancestry=[], restart_allowed=allow_restart)


def _cue_start(mapping_id: int, *, ancestry: list[int], restart_allowed: bool) -> bool:
    """Shared start path: top-level triggers and mapper-row activations.

    ``ancestry`` is the activation chain the start happens inside — a
    top-level trigger passes an empty chain, a mapper row passes its own run's
    chain. The cycle guard: a start whose mapping is ALREADY running only
    proceeds when ``restart_allowed`` (a real trigger), and a mapping that
    already appears anywhere in ``ancestry`` is a logged no-op — this stops
    self re-entry and A->B->A ping-pong even after the ancestor's run finished
    and left the active chain.
    """
    mapping = mapper.find_mapping(mapping_id)
    if mapping is None or mapping.get("control") != "cue list":
        append_log("CUE", f"no-op: mapping {mapping_id} is not a runnable cue list")
        return False
    if not mapping.get("enabled", False):
        append_log("CUE", f"no-op: mapping {mapping_id} disabled (e24 gate)")
        return False
    target_id = mapping.get("target_id")
    if not target_id:
        append_log("CUE", f"no-op: mapping {mapping_id} has no source")
        return False
    cue = mapping.get("cue") or mapper.fresh_cue()
    if mapper.cue_rows_empty(cue):
        append_log("CUE", f"no-op: mapping {mapping_id} cue is empty")
        return False
    if cue_is_running(mapping_id):
        if not restart_allowed:
            append_log("CUE", f"no-op: mapping {mapping_id} already running (cycle guard)")
            return False
        plan = build_cue_plan(cue, str(target_id))
        for run in state.cue_runs:
            if run["mapping_id"] == mapping_id:
                run["plan"] = plan
                run["cursor"] = 0
                run["start_ms"] = None  # a restart re-anchors at its next tick
                run["chain"] = [mapping_id]
                append_log("CUE", f"restart cue of mapping {mapping_id}")
                return True
    if mapping_id in ancestry:
        append_log("CUE", f"no-op: mapping {mapping_id} already in the run chain (cycle guard)")
        return False
    plan = build_cue_plan(cue, str(target_id))
    state.cue_runs.append(
        {
            "mapping_id": mapping_id,
            "target_id": str(target_id),
            "plan": plan,
            "cursor": 0,
            "start_ms": None,  # anchored at the run's first tick (absolute clock)
            "chain": [*ancestry, mapping_id],
        }
    )
    append_log("CUE", f"run cue of mapping {mapping_id}")
    return True


def cue_stop(mapping_id: int) -> None:
    """Stop a running cue: drop it from the chain. Sends NO OSC (e35s03)."""
    state.cue_runs[:] = [run for run in state.cue_runs if run["mapping_id"] != mapping_id]


def cue_progress(mapping_id: int) -> tuple[int, int]:
    """(executed, total) cue actions of a mapping (UAT e35).

    Wait rows are PACING, not actions: only property/mapper/burst rows count
    toward the total and toward the executed counter (the run's cursor). Idle or
    finished runs read 0 executed, so the card shows '0 of N' at rest.
    """
    mapping = mapper.find_mapping(mapping_id)
    total = 0
    if mapping is not None:
        cue = mapping.get("cue")
        if isinstance(cue, dict):
            total = sum(
                1 for r in cue.get("rows", []) if r.get("kind") in ("property", "mapper", "burst")
            )
    executed = 0
    for run in state.cue_runs:
        if run["mapping_id"] == mapping_id:
            executed = min(int(run["cursor"]), total)
    return executed, total


def tick(now_ms: float) -> None:
    """Drive every active run on the monotonic clock (e35s02).

    Dispatches every due entry (time <= now), starts mapper-row activations
    through ``cue_start(allow_restart=False)`` and drops finished runs.
    HIGH-1 worker-safe: no dpg; the defensive try/except mirrors the worker
    posture — the scheduler thread must never die from a rogue dispatch.
    """
    for run in list(state.cue_runs):
        try:
            _advance_run(run, now_ms)
        except Exception as e:  # worker defensive posture (BLE001 allowed in this module)
            append_log("CUE", f"run error on mapping {run['mapping_id']}: {e}")
            cue_stop(int(run["mapping_id"]))


def _advance_run(run: dict[str, Any], now_ms: float) -> None:
    plan = run["plan"]
    cursor = int(run["cursor"])
    # e35 UAT: plan times are RELATIVE to the run start; the real clock is
    # absolute (monotonic ms since boot), so the first tick anchors the run's
    # baseline and every later entry fires at baseline + its offset. Without
    # this a wait row sent everything at once (offset 0/1000 both <= now).
    if run.get("start_ms") is None:
        run["start_ms"] = now_ms
    base = float(run["start_ms"])
    while cursor < len(plan) and plan[cursor][0] + base <= now_ms:
        _, action, payload = plan[cursor]
        if action == _PLAN_SEND:
            _send_property(run, payload)
        elif action == _PLAN_ACTIVATE:
            _cue_start(
                int(payload["mapping_id"]), ancestry=list(run["chain"]), restart_allowed=False
            )
        cursor += 1
    run["cursor"] = cursor
    if cursor >= len(plan):
        state.cue_runs.remove(run)


def _send_cue(address: str, args: Any) -> None:
    """Send one cue-row OSC message, tagged for the I/O Monitor (e39s05)."""
    with osc.sent_by(IO_MONITOR_KIND_CUE):
        osc_client.send_message(address, args)


def _send_property(run: dict[str, Any], payload: dict[str, Any]) -> None:
    """Send one cue action to the run mapping's source and log it (worker-safe).

    e36s05: property and burst rows carry the typed payload; the exact argument
    list is composed through the shared catalog composer (scalar float / full
    vector / rate burst + duration ms). Legacy scalar rows stay byte-identical
    (single float payload).
    """
    prop = str(payload["property"])
    ms = payload.get("ms")
    # e61s05: a uniform row keeps the native ms — the Cue is the ONLY surface allowed
    # to animate a shader parameter (e36 rule D5).
    uniform = shadercode.uniform_send(
        state.shader_uniforms, prop, float(payload.get("value", 0.0)), run["target_id"], ms
    )
    if uniform is not None:
        # e61s06: /uniform on a declared GENERATOR crashes vimix (SPIKE-6). Asked HERE,
        # once the property is known to be a uniform (BUG-2026-10-11T131042): asked
        # before, it dropped every Cue row aimed at a target declared a generator and
        # logged "uniform skipped" for rows that were not uniforms.
        if shadercode.uniform_blocked(
            run["target_id"],
            state.shader_target,
            state.shader_kind,
            sourcekind.type_of_source(
                state.global_vimix_state.get("sources") or {}, run["target_id"]
            ),
        ):
            log_warn("CUE", f"{run['target_id']}: uniform skipped (declared generator, SPIKE-6)")
            return
        address, uniform_args = uniform
        _send_cue(address, list(uniform_args))
        parts = [a if isinstance(a, str) else f"{float(a):.2f}" for a in uniform_args]
        return
    addr = f"/vimix/{run['target_id']}/{prop}"
    if isinstance(payload.get("values"), list):
        args: list[Any] = catalog.compose_send_args(
            prop, values=[float(x) for x in payload["values"]], ms=ms
        )
    else:
        args = catalog.compose_send_args(prop, value=float(payload.get("value", 0.0)), ms=ms)
    if len(args) == 1 and args[0] is not None:
        _send_cue(addr, float(args[0]))
    else:
        _send_cue(addr, list(args))
    parts = []
    for a in args:
        parts.append("N" if a is None else f"{float(a):.2f}")


__all__ = ["build_cue_plan", "cue_is_running", "cue_start", "cue_stop", "tick"]
