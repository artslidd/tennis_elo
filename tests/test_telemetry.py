"""Tests for the optional Datadog telemetry in :mod:`tennis_elo.telemetry`."""

from __future__ import annotations

import json

import pytest

from tennis_elo import telemetry


@pytest.fixture()
def capture(monkeypatch: pytest.MonkeyPatch):
    """Inline the fire-and-forget dispatch and capture each request.

    Returns the list of (url, data, api_key) tuples POSTed so far.
    """
    posted: list[tuple[str, bytes, str]] = []

    def fake_urlopen(req, timeout=5):
        posted.append((req.full_url, req.data, req.get_header("Dd-api-key")))

    class InlineThread:
        def __init__(self, target=None, args=(), **_):
            self._target, self._args = target, args

        def start(self):
            self._target(*self._args)

    monkeypatch.setattr(telemetry.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(telemetry.threading, "Thread", InlineThread)
    return posted


@pytest.fixture()
def key(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DD_API_KEY", "test-key")


def test_disabled_without_api_key(capture, monkeypatch):
    monkeypatch.delenv("DD_API_KEY", raising=False)
    telemetry.send_log("hello")
    telemetry.count("tennis_elo.page_views")
    assert capture == []


def test_log_payload_shape(capture, key):
    telemetry.send_log(
        "calculation finished", status="info", tags=["seasons:2026"], attrs={"matches": 10}
    )
    url, data, api_key = capture[0]
    assert url == "https://http-intake.logs.datadoghq.com/api/v2/logs"
    assert api_key == "test-key"
    body = json.loads(data)
    assert body[0]["message"] == "calculation finished"
    assert body[0]["status"] == "info"
    assert body[0]["ddtags"] == "seasons:2026"
    assert body[0]["service"] == "tennis-elo-dashboard"
    assert body[0]["matches"] == 10


def test_count_metric_payload_shape(capture, key):
    telemetry.count("tennis_elo.sessions", value=1, tags=["app:tennis-elo"])
    url, data, api_key = capture[0]
    assert url == "https://api.datadoghq.com/api/v1/series"
    assert api_key == "test-key"
    series = json.loads(data)["series"][0]
    assert series["metric"] == "tennis_elo.sessions"
    assert series["type"] == "count"
    assert series["tags"] == ["app:tennis-elo"]
    point_ts, point_value = series["points"][0]
    assert point_value == 1
    assert point_ts > 0


def test_custom_site(capture, key, monkeypatch):
    monkeypatch.setenv("DD_SITE", "datadoghq.eu")
    telemetry.send_log("hello")
    telemetry.count("tennis_elo.page_views")
    assert capture[0][0] == "https://http-intake.logs.datadoghq.eu/api/v2/logs"
    assert capture[1][0] == "https://api.datadoghq.eu/api/v1/series"


def test_transport_failure_is_silent(monkeypatch, key):
    def boom(req, timeout=5):
        raise OSError("network down")

    monkeypatch.setattr(telemetry.urllib.request, "urlopen", boom)
    telemetry.send_log("hello")  # dispatched on an (inlined) thread; must not raise


def test_enabled_flag(key, monkeypatch):
    assert telemetry.enabled() is True
    monkeypatch.delenv("DD_API_KEY", raising=False)
    assert telemetry.enabled() is False
