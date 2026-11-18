"""Tests for the public ``tennis_elo.api`` orchestration layer.

Season-selection validation and orchestration tests run in isolation by
stubbing the (not yet integrated) ``tennis_elo.data`` and
``tennis_elo.ratings`` module seams in ``sys.modules``. Real end-to-end tests
over synthetic CSVs are skipped until the sibling lanes are integrated.
"""

import csv
import importlib.util
import subprocess
import sys
import types
from pathlib import Path

import pytest

import tennis_elo
from tennis_elo import api
from tennis_elo.models import (
    CalculationResult,
    LoadResult,
    Match,
    PlayerRating,
    RatingConfig,
    RatingResult,
)

TS_1 = 1704067200  # 2024-01-01T00:00:00+00:00
TS_2 = 1704153600  # 2024-01-02T00:00:00+00:00


@pytest.fixture
def stubs(monkeypatch):
    """Install temporary data/ratings module seams for isolated orchestration tests.

    These are in-memory test doubles, not source modules: the real siblings own
    ``src/tennis_elo/data.py`` and ``src/tennis_elo/ratings.py``.
    """

    data = types.ModuleType("tennis_elo.data")
    ratings = types.ModuleType("tennis_elo.ratings")
    monkeypatch.setitem(sys.modules, "tennis_elo.data", data)
    monkeypatch.setitem(sys.modules, "tennis_elo.ratings", ratings)
    monkeypatch.setattr(tennis_elo, "data", data, raising=False)
    monkeypatch.setattr(tennis_elo, "ratings", ratings, raising=False)
    return data, ratings


def _sample_match() -> Match:
    return Match("m1", 2024, TS_1, "p1", "p2", "Alice", "Bob", 1)


@pytest.mark.parametrize("seasons", [(2024,), (2024, 2025), (2024, 2025, 2026)])
def test_normalize_accepts_one_to_three_consecutive_seasons(seasons):
    assert api._normalize_seasons(seasons) == tuple(sorted(seasons))


def test_normalize_sorts_unsorted_selection():
    assert api._normalize_seasons([2026, 2024, 2025]) == (2024, 2025, 2026)


@pytest.mark.parametrize("seasons", [[], (2024, 2025, 2026, 2027)])
def test_normalize_rejects_wrong_season_count(seasons):
    with pytest.raises(ValueError):
        api._normalize_seasons(seasons)


def test_normalize_rejects_duplicates_instead_of_discarding_them():
    with pytest.raises(ValueError, match="distinct"):
        api._normalize_seasons([2024, 2024, 2025])


def test_normalize_rejects_non_consecutive_seasons():
    with pytest.raises(ValueError, match="consecutive"):
        api._normalize_seasons([2024, 2026])


@pytest.mark.parametrize("value", ["2025", 2025.0, None, True])
def test_normalize_rejects_non_integer_seasons(value):
    with pytest.raises(ValueError, match="integer"):
        api._normalize_seasons([2024, value])


def test_calculate_validates_seasons_before_loading_anything():
    with pytest.raises(ValueError, match="distinct"):
        api.calculate("input-that-does-not-exist", [2024, 2024])


def test_calculate_rejects_bad_config_type():
    with pytest.raises(ValueError, match="config"):
        api.calculate("input-that-does-not-exist", [2024], config="not-a-config")


def test_calculate_orchestrates_discovery_loading_and_replay(stubs):
    data, ratings = stubs
    match = _sample_match()
    load = LoadResult((match,), ("2024-atp-season.csv",), (2024,), 1, 1, {}, 0)
    player = PlayerRating("p1", "Alice", 1516.0, 1, 1, 0, TS_1, TS_1)
    rating_result = RatingResult((player,), (), 1)
    calls: dict = {}

    data.discover_csv_files = lambda input_dir: (Path("2024-atp-season.csv"),)

    def fake_load(paths, seasons, *, include_retirements=True):
        calls["paths"] = tuple(paths)
        calls["seasons"] = tuple(seasons)
        calls["include_retirements"] = include_retirements
        return load

    def fake_rate(matches, config=None, *, include_history=False):
        calls["matches"] = tuple(matches)
        calls["config"] = config
        calls["include_history"] = include_history
        return rating_result

    data.load_matches = fake_load
    ratings.rate_matches = fake_rate

    config = RatingConfig(initial_rating=1600.0, k_factor=16.0, include_retirements=False)
    result = api.calculate("data-dir", [2025, 2024], config=config, include_history=True)

    assert isinstance(result, CalculationResult)
    assert result.seasons == (2024, 2025)
    assert result.config is config
    assert result.load is load
    assert result.ratings is rating_result
    assert calls["paths"] == (Path("2024-atp-season.csv"),)
    assert calls["seasons"] == (2024, 2025)
    assert calls["include_retirements"] is False
    assert calls["matches"] == (match,)
    assert calls["config"] is config
    assert calls["include_history"] is True


def test_calculate_defaults_to_a_fresh_default_config(stubs):
    data, ratings = stubs
    data.discover_csv_files = lambda input_dir: ()
    data.load_matches = lambda paths, seasons, *, include_retirements=True: LoadResult(
        (), (), (2024,), 0, 0, {}, 0
    )
    ratings.rate_matches = lambda matches, config=None, *, include_history=False: RatingResult(
        (), (), 0
    )

    result = api.calculate("data-dir", [2024])

    assert result.config == RatingConfig()
    assert result.config.include_retirements is True


def test_available_seasons_delegates_to_data_lane(stubs):
    data, _ = stubs
    data.available_seasons = lambda input_dir: (2024, 2025)
    assert api.available_seasons("data-dir") == (2024, 2025)


def test_importing_package_does_not_pull_optional_dashboard_dependencies():
    code = (
        "import sys, tennis_elo, tennis_elo.api, tennis_elo.export, tennis_elo.cli; "
        "assert 'streamlit' not in sys.modules, 'streamlit imported'; "
        "assert 'pandas' not in sys.modules, 'pandas imported'"
    )
    completed = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=False
    )
    assert completed.returncode == 0, completed.stderr


# --- Integration tests: require the data and engine lanes -------------------

CSV_FIELDS = (
    "match_id",
    "season_year",
    "date_timestamp",
    "tour_type_human",
    "status",
    "status_extra",
    "home_id",
    "away_id",
    "home_name",
    "away_name",
    "winner_code",
)


def _siblings_available() -> bool:
    return (
        importlib.util.find_spec("tennis_elo.data") is not None
        and importlib.util.find_spec("tennis_elo.ratings") is not None
    )


requires_siblings = pytest.mark.skipif(
    not _siblings_available(),
    reason="data/ratings lanes not integrated yet; parent runs this after integration",
)


def _write_season(input_dir: Path, year: int, rows: list[list]) -> Path:
    path = input_dir / f"{year}-atp-season.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(CSV_FIELDS)
        writer.writerows(rows)
    return path


def _finished(match_id, year, timestamp, home, away, home_name, away_name, winner):
    return [
        match_id,
        year,
        timestamp,
        "ATP Tour",
        "FINISHED",
        "FINISHED",
        home,
        away,
        home_name,
        away_name,
        winner,
    ]


@requires_siblings
def test_available_seasons_reads_synthetic_csvs(tmp_path):
    _write_season(tmp_path, 2024, [_finished("m1", 2024, TS_1, "p1", "p2", "A", "B", 1)])
    _write_season(tmp_path, 2025, [_finished("m2", 2025, TS_2, "p1", "p3", "A", "C", 2)])
    assert api.available_seasons(tmp_path) == (2024, 2025)


@requires_siblings
def test_calculate_builds_a_fresh_window_from_synthetic_csvs(tmp_path):
    _write_season(
        tmp_path,
        2024,
        [
            _finished("m1", 2024, TS_1, "p1", "p2", "Alice", "Bob", 1),
            _finished("m2", 2024, TS_2, "p3", "p4", "Carol", "Dave", 2),
        ],
    )

    result = api.calculate(tmp_path, [2024])

    ratings = {player.player_id: player.rating for player in result.ratings.players}
    assert ratings == {"p1": 1516.0, "p2": 1484.0, "p3": 1484.0, "p4": 1516.0}
    assert result.ratings.matches_processed == 2
    assert result.load.rows_read == 2
    assert result.load.selected_rows == 2
    assert result.seasons == (2024,)


@requires_siblings
def test_calculate_replays_multiple_seasons_as_one_window(tmp_path):
    _write_season(tmp_path, 2024, [_finished("m1", 2024, TS_1, "p1", "p2", "A", "B", 1)])
    _write_season(tmp_path, 2025, [_finished("m2", 2025, TS_2, "p2", "p1", "B", "A", 1)])

    result = api.calculate(tmp_path, [2024, 2025])

    assert result.seasons == (2024, 2025)
    assert result.ratings.matches_processed == 2
    assert sum(player.rating for player in result.ratings.players) == pytest.approx(3000.0)
