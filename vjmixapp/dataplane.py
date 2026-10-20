"""The machine-A HTTP data plane client (e41s03, e41s04).

viOSC already serves HTTP on the preview port (the e38 surface). This module is
the VJmix side of that plane: it fetches ONE thumbnail frame by source NAME, and
it reads the state table as a PULL whose cadence VJmix owns.

WORKER-SAFE and COUPLING-FREE: no dpg import (HIGH-1), and the endpoint is passed
by the caller instead of read from state, so this module stays a pure transport —
which is also what makes it testable against a real HTTP server on an ephemeral
port, with no daemon, no config and no network.
"""

import contextlib
import json
import urllib.error
import urllib.request

from vjmixapp import pairing
from vjmixapp.constants import (
    DATA_PLANE_TIMEOUT,
    INTEREST_PATH,
    STATE_PATH,
    THUMB_PATH_PREFIX,
)


def thumbnail_url(host: str, port: int, source_name: str, index: int) -> str:
    """HTTP URL of one thumbnail frame on the viOSC data plane."""
    return f"http://{host}:{port}{THUMB_PATH_PREFIX}{source_name}/{index}"


def state_url(host: str, port: int) -> str:
    """HTTP URL of the state table resource on the viOSC data plane."""
    return f"http://{host}:{port}{STATE_PATH}"


def _fetch_ex(url: str, etag: int | None = None) -> tuple[bytes | None, bool, int | None]:
    """One GET; never raises. Returns ``(body, answered, status)``.

    ``answered`` is False ONLY when the server did not answer at all
    (connection refused, timeout). ``status`` is the HTTP status when there was
    an answer — the callers must be able to tell a 404 (old daemon, no route)
    from a 401 (pairing required, the route exists). ``etag`` (e82s04) turns the
    GET into a conditional one: a matching revision answers 304 with no body.
    """
    headers = pairing.http_headers()
    if etag is not None:
        headers["If-None-Match"] = f'"{int(etag)}"'
    try:
        with urllib.request.urlopen(
            urllib.request.Request(url, headers=headers),
            timeout=DATA_PLANE_TIMEOUT,
        ) as resp:
            if resp.status != 200:
                return None, True, resp.status
            return resp.read(), True, resp.status
    except urllib.error.HTTPError as e:
        return None, True, e.code
    except Exception:
        return None, False, None


def _fetch(url: str) -> tuple[bytes | None, bool]:
    """One GET of a data-plane resource; never raises — ``(body, answered)``."""
    body, answered, _status = _fetch_ex(url)
    return body, answered


def fetch_thumbnail(
    host: str, port: int, source_name: str, index: int
) -> tuple[bytes | None, bool]:
    """One GET of a thumbnail frame (e41s03). See ``_fetch`` for the contract."""
    if not host or not port:
        return None, False
    return _fetch(thumbnail_url(host, port, source_name, index))


def interest_url(host: str, port: int) -> str:
    """HTTP URL of the interest resource on the viOSC data plane."""
    return f"http://{host}:{port}{INTEREST_PATH}"


def post_interest(
    host: str,
    port: int,
    source: str,
    props: list[str],
    cadence_ms: int = 1000,
    once: bool = False,
) -> tuple[dict | None, int | None]:
    """POST /interest -> (report, status); never raises (e82s05).

    An empty ``props`` releases the entry. ``status`` is None when the endpoint
    did not answer at all, so the caller can tell "older daemon" (404) from
    "down" (None) exactly like the rest of the data-plane client.
    """
    if not host or not port:
        return None, None
    payload: dict = {
        "source": str(source),
        "props": [str(prop) for prop in props],
        "cadence_ms": int(cadence_ms),
    }
    if once:
        payload["once"] = True  # e82s08: one sweep, then back to the tier
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        interest_url(host, port),
        data=body,
        headers={**pairing.http_headers(), "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=DATA_PLANE_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8")), resp.status
    except urllib.error.HTTPError as e:
        with contextlib.suppress(Exception):
            return json.loads(e.read().decode("utf-8")), e.code
        return None, e.code
    except Exception:
        return None, None


def fetch_state_ex(
    host: str, port: int, etag: int | None = None
) -> tuple[str | None, bool, int | None]:
    """One GET of the state table plus its HTTP status (BUG-2026-09-13T231500).

    The text is handed on verbatim: the daemon produced it with the same
    serializer that feeds the OSC broadcast, so parsing it belongs to the
    existing state ingestion, not to the transport. The status lets the caller
    tell a 404 (old daemon without /state) from a 401 (pairing required).
    """
    if not host or not port:
        return None, False, None
    body, answered, status = _fetch_ex(state_url(host, port), etag)
    if body is None:
        return None, answered, status
    return body.decode("utf-8", errors="replace"), True, status


def fetch_state(host: str, port: int) -> tuple[str | None, bool]:
    """One GET of the state table as its exact JSON text (e41s04).

    The text is handed on verbatim: the daemon produced it with the same
    serializer that feeds the OSC broadcast, so parsing it belongs to the
    existing state ingestion, not to the transport.
    """
    text, answered, _status = fetch_state_ex(host, port)
    return text, answered
