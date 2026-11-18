"""Optional Datadog telemetry for the Tennis Elo dashboard.

The package stays stdlib-only, so this module POSTs directly to the Datadog
HTTP intake with :mod:`urllib` - no ``datadog`` dependency, no agent needed.
Everything is fire-and-forget on a daemon thread and every failure is
swallowed: telemetry must never break or slow down the dashboard.

Configuration comes from the environment (Streamlit Community Cloud maps
``secrets.toml`` entries onto ``st.secrets``, which the deploy entrypoint
forwards to ``os.environ``):

- ``DD_API_KEY``  - when missing or blank, every call is a no-op.
- ``DD_SITE``     - defaults to ``datadoghq.com``; use e.g. ``datadoghq.eu``.

Metrics sent are counts (``type: count``) namespaced ``tennis_elo.*``:
``tennis_elo.sessions``, ``tennis_elo.page_views``, ``tennis_elo.runs`` and
``tennis_elo.run_errors``. Logs carry the same events with attributes such as
the selected seasons, matches/players rated and the run duration.
"""

from __future__ import annotations

import json
import os
import threading
import time
import urllib.request
from collections.abc import Mapping, Sequence

__all__ = ["count", "enabled", "send_log"]

SERVICE = "tennis-elo-dashboard"
_REQUEST_TIMEOUT_SECONDS = 5


def enabled() -> bool:
    """True when a Datadog API key is configured."""
    return bool(_api_key())


def count(metric: str, *, value: float = 1, tags: Sequence[str] = ()) -> None:
    """Increment a count metric, e.g. ``tennis_elo.page_views``."""
    if not enabled():
        return
    payload = {
        "series": [
            {
                "metric": metric,
                "type": "count",
                "points": [[int(time.time()), value]],
                "tags": list(tags),
            }
        ]
    }
    _post_async(f"https://api.{_site()}/api/v1/series", payload)


def send_log(
    message: str,
    *,
    status: str = "info",
    tags: Sequence[str] = (),
    attrs: Mapping[str, object] | None = None,
) -> None:
    """Ship a log event to the HTTP logs intake."""
    if not enabled():
        return
    entry: dict[str, object] = {
        "message": message,
        "status": status,
        "service": SERVICE,
        "ddtags": ",".join(tags),
    }
    if attrs:
        entry.update(attrs)
    _post_async(f"https://http-intake.logs.{_site()}/api/v2/logs", [entry])


# --------------------------------------------------------------------------- #
# Internals
# --------------------------------------------------------------------------- #


def _api_key() -> str:
    return os.environ.get("DD_API_KEY", "").strip()


def _site() -> str:
    return os.environ.get("DD_SITE", "").strip() or "datadoghq.com"


def _post_async(url: str, payload: object) -> None:
    threading.Thread(
        target=_post, args=(url, payload, _api_key()), daemon=True
    ).start()


def _post(url: str, payload: object, api_key: str) -> None:
    try:
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json", "DD-API-KEY": api_key},
            method="POST",
        )
        urllib.request.urlopen(request, timeout=_REQUEST_TIMEOUT_SECONDS).close()
    except Exception:  # noqa: S110,BLE001 - telemetry must never break the app
        pass
