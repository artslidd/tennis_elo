"""Tests for the optional dashboard lane: pure view helpers, launcher, and app.

The pure helper tests use real shared-model fixtures (:mod:`tennis_elo.models`)
so they never depend on the sibling P0 modules. The Streamlit app is exercised
with :class:`streamlit.testing.v1.AppTest`; the isolated UI-state tests inject
stub ``tennis_elo.api`` / ``tennis_elo.export`` modules through Python's import
machinery, while the integration test is skipped until the real P0 modules and
data files are available (parent integration).
"""

from __future__ import annotations

import dataclasses
import subprocess
import sys
import types
from pathlib import Path

import pytest

from tennis_elo import dashboard_launcher
from tennis_elo.dashboard_views import (
    COMPARISON_COLUMNS,
    FRESH_START_NOTICE,
    HISTORY_COLUMNS,
    LEADERBOARD_COLUMNS,
    MISSING_DASHBOARD_DEPENDENCIES,
    build_player_options,
    build_rating_config,
    comparison_entry,
    comparison_rows,
    control_error,
    display_ranking_rows,
    elo_chart_rows,
    error_message,
    escape_markdown,
    exclusion_rows,
    filter_player_options,
    filter_ranking_rows,
    load_accounting,
    plain_text,
    player_history_rows,
    player_option_label,
    player_stat_rows,
    run_metadata_rows,
    safe_download_filename,
    safe_label,
    season_selection_problem,
    season_window_plan,
    sort_ranking_rows,
    timestamp_to_iso_date,
    window_label,
    window_plans,
)
from tennis_elo.models import (
    CalculationResult,
    HistoryEntry,
    LoadResult,
    Match,
    PlayerRating,
    RatingConfig,
    RatingResult,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_PATH = REPO_ROOT / "src" / "tennis_elo" / "dashboard.py"
REAL_CSV = REPO_ROOT / "2026-atp-season.csv"

HOSTILE_NAME = "<img src=x onerror=alert(1)>"
LINK_NAME = "[click](javascript:alert(1))"

# 2026-01-01, 2026-01-02 and 2026-07-01 in UTC.
TS_1 = 1_767_225_600
TS_2 = 1_767_312_000
TS_3 = 1_782_864_000

MATCHES = (
    Match(
        match_id="m1",
        season_year=2025,
        timestamp=TS_1,
        home_id="p1",
        away_id="p2",
        home_name="Alpha A.",
        away_name="Beta B.",
        winner_code=1,
        tournament="Test Open",
        surface="hard",
    ),
    Match(
        match_id="m2",
        season_year=2025,
        timestamp=TS_2,
        home_id="p2",
        away_id="p1",
        home_name="Beta B.",
        away_name="Alpha A.",
        winner_code=2,
        tournament="Test Open",
        surface="hard",
    ),
    Match(
        match_id="m3",
        season_year=2026,
        timestamp=TS_3,
        home_id="p1",
        away_id="p3",
        home_name="Alpha A.",
        away_name=HOSTILE_NAME,
        winner_code=1,
        tournament="Test Masters",
        surface="clay",
    ),
)

PLAYERS = (
    PlayerRating(
        player_id="p1",
        name="Alpha A.",
        rating=1532.5,
        matches=3,
        wins=2,
        losses=1,
        first_match_timestamp=TS_1,
        last_match_timestamp=TS_3,
    ),
    PlayerRating(
        player_id="p2",
        name="Alpha A.",  # deliberate duplicate name: the UI must disambiguate by ID
        rating=1484.25,
        matches=2,
        wins=1,
        losses=1,
        first_match_timestamp=TS_1,
        last_match_timestamp=TS_2,
    ),
    PlayerRating(
        player_id="p3",
        name=HOSTILE_NAME,
        rating=1466.0,
        matches=1,
        wins=0,
        losses=1,
        first_match_timestamp=TS_3,
        last_match_timestamp=TS_3,
    ),
)

HISTORY = (
    HistoryEntry(
        match_id="m1",
        season_year=2025,
        timestamp=TS_1,
        player_id="p1",
        player_name="Alpha A.",
        opponent_id="p2",
        opponent_name="Beta B.",
        won=True,
        rating_before=1500.0,
        opponent_rating_before=1500.0,
        expected_score=0.5,
        rating_after=1516.0,
        tournament="Test Open",
        surface="hard",
    ),
    HistoryEntry(
        match_id="m1",
        season_year=2025,
        timestamp=TS_1,
        player_id="p2",
        player_name="Beta B.",
        opponent_id="p1",
        opponent_name="Alpha A.",
        won=False,
        rating_before=1500.0,
        opponent_rating_before=1500.0,
        expected_score=0.5,
        rating_after=1484.0,
        tournament="Test Open",
        surface="hard",
    ),
    HistoryEntry(
        match_id="m2",
        season_year=2025,
        timestamp=TS_2,
        player_id="p1",
        player_name="Alpha A.",
        opponent_id="p2",
        opponent_name="Beta B.",
        won=False,
        rating_before=1516.0,
        opponent_rating_before=1484.0,
        expected_score=0.545,
        rating_after=1498.6,
        tournament="Test Open",
        surface="hard",
    ),
    HistoryEntry(
        match_id="m3",
        season_year=2026,
        timestamp=TS_3,
        player_id="p1",
        player_name="Alpha A.",
        opponent_id="p3",
        opponent_name=HOSTILE_NAME,
        won=True,
        rating_before=1498.6,
        opponent_rating_before=1500.0,
        expected_score=0.498,
        rating_after=1532.5,
        tournament="Test Masters",
        surface="clay",
    ),
)


def make_calculation_result(seasons: tuple[int, ...] = (2025, 2026)) -> CalculationResult:
    """Build a real shared-model fixture with consistent load accounting."""
    load = LoadResult(
        matches=MATCHES,
        input_files=("2025-atp-season.csv", "2026-atp-season.csv"),
        available_seasons=(2024, 2025, 2026),
        rows_read=10,
        selected_rows=6,
        excluded_counts={"walkover": 1, "exhibition": 1, "canceled": 0},
        duplicate_rows=1,
    )
    ratings = RatingResult(players=PLAYERS, history=HISTORY, matches_processed=3)
    return CalculationResult(seasons=seasons, config=RatingConfig(), load=load, ratings=ratings)


def make_ranking_rows() -> list[dict]:
    """Export-shaped ranking rows (as ``export.ranking_rows`` promises)."""
    return [
        {
            "rank": 1,
            "player_id": "p1",
            "name": "Alpha A.",
            "rating": 1532.5,
            "matches": 3,
            "wins": 2,
            "losses": 1,
            "first_match_date": "2026-01-01",
            "last_match_date": "2026-07-01",
        },
        {
            "rank": 2,
            "player_id": "p2",
            "name": "Alpha A.",
            "rating": 1484.25,
            "matches": 2,
            "wins": 1,
            "losses": 1,
            "first_match_date": "2026-01-01",
            "last_match_date": "2026-01-02",
        },
        {
            "rank": 3,
            "player_id": "p3",
            "name": HOSTILE_NAME,
            "rating": 1466.0,
            "matches": 1,
            "wins": 0,
            "losses": 1,
            "first_match_date": "2026-07-01",
            "last_match_date": "2026-07-01",
        },
    ]


def make_history_rows() -> list[dict]:
    """Export-shaped history rows (every HistoryEntry field plus ``date``)."""
    rows = []
    for entry in HISTORY:
        row = dataclasses.asdict(entry)
        row["date"] = timestamp_to_iso_date(entry.timestamp)
        rows.append(row)
    return rows


# --------------------------------------------------------------------------- #
# Pure presentation helpers
# --------------------------------------------------------------------------- #


def test_plain_text_removes_control_and_direction_characters():
    assert plain_text("  Alpha\n\tA.\x00 ") == "Alpha A."
    assert plain_text("safe\u202eevil\ufeff") == "safeevil"
    assert plain_text(None) == ""
    assert plain_text(12) == "12"


def _unescaped(text: str) -> str:
    """Drop every backslash-escaped character to spot markdown-active syntax."""
    kept = []
    index = 0
    while index < len(text):
        if text[index] == "\\":
            index += 2
            continue
        kept.append(text[index])
        index += 1
    return "".join(kept)


def test_escape_markdown_neutralises_html_and_link_syntax():
    html = escape_markdown(HOSTILE_NAME)
    assert "\\<" in html and "\\>" in html
    assert "<" not in _unescaped(html) and ">" not in _unescaped(html)

    link = escape_markdown(LINK_NAME)
    plain = _unescaped(link)
    assert "[" not in plain and "]" not in plain and "(" not in plain and ")" not in plain


def test_safe_download_filename_strips_unsafe_characters():
    name = safe_download_filename("../../etc/pa ss wd?<script>.csv")
    assert "/" not in name and "\\" not in name and "<" not in name
    assert name.endswith(".csv")
    assert len(name) <= 80


def test_safe_download_filename_falls_back_when_empty():
    assert safe_download_filename("") == "tennis-elo.csv"
    assert safe_download_filename("/") == "tennis-elo.csv"


def test_player_labels_include_ids_for_disambiguation():
    first = player_option_label("Alpha A.", "p1")
    second = player_option_label("Alpha A.", "p2")
    assert first != second
    assert "p1" in first and "p2" in second
    hostile = player_option_label(HOSTILE_NAME, "p3")
    assert "<" not in hostile and ">" not in hostile
    assert "img" in hostile and "p3" in hostile


def test_player_options_skip_duplicates_and_blank_ids():
    rows = make_ranking_rows() + [
        {"player_id": "p1", "name": "Alpha A."},
        {"player_id": "", "name": "ghost"},
    ]
    options = build_player_options(rows)
    assert [option.player_id for option in options] == ["p1", "p2", "p3"]
    assert all(option.label == f"{option.name} ({option.player_id})" for option in options)


def test_filter_player_options_matches_name_and_id():
    options = build_player_options(make_ranking_rows())
    assert len(filter_player_options(options, "")) == 3
    assert [o.player_id for o in filter_player_options(options, "beta")] == []
    assert [o.player_id for o in filter_player_options(options, "alpha")] == ["p1", "p2"]
    assert [o.player_id for o in filter_player_options(options, "P3")] == ["p3"]


def test_filter_ranking_rows_searches_name_and_id():
    rows = make_ranking_rows()
    assert [r["player_id"] for r in filter_ranking_rows(rows, query="alpha")] == ["p1", "p2"]
    assert [r["player_id"] for r in filter_ranking_rows(rows, query="p3")] == ["p3"]
    assert filter_ranking_rows(rows, query="nobody") == ()


def test_filter_ranking_rows_applies_min_matches_presentation_filter():
    rows = make_ranking_rows()
    assert [r["player_id"] for r in filter_ranking_rows(rows)] == ["p1", "p2", "p3"]
    assert [r["player_id"] for r in filter_ranking_rows(rows, min_matches=2)] == ["p1", "p2"]
    assert [r["player_id"] for r in filter_ranking_rows(rows, min_matches=3)] == ["p1"]
    assert filter_ranking_rows(rows, min_matches=-5)


def test_filter_ranking_rows_does_not_mutate_input():
    rows = make_ranking_rows()
    filter_ranking_rows(rows, query="alpha", min_matches=2)
    assert rows == make_ranking_rows()


def test_sort_ranking_rows_orders_numerically_and_reverse():
    rows = make_ranking_rows()
    by_rating = sort_ranking_rows(rows, column="rating", descending=True)
    assert [r["player_id"] for r in by_rating] == ["p1", "p2", "p3"]
    by_rank = sort_ranking_rows(rows, column="rank")
    assert [r["player_id"] for r in by_rank] == ["p1", "p2", "p3"]
    by_name = sort_ranking_rows(rows, column="name")
    assert [r["player_id"] for r in by_name] == ["p1", "p2", "p3"]


def test_sort_ranking_rows_is_stable_and_ignores_missing_values():
    rows = [{"rank": 2, "player_id": "b"}, {"rank": 1, "player_id": "a"}, {"player_id": "c"}]
    ordered = sort_ranking_rows(rows, column="rank")
    assert [r["player_id"] for r in ordered] == ["a", "b", "c"]


def test_display_ranking_rows_rounds_rating_without_mutating_input():
    rows = make_ranking_rows()
    displayed = display_ranking_rows(rows)
    assert displayed[0]["rating"] == 1532.5
    assert displayed[1]["rating"] == 1484.2  # banker's rounding is irrelevant here
    assert displayed[2]["rating"] == 1466.0
    assert rows == make_ranking_rows()
    assert displayed[2]["name"] == safe_label(HOSTILE_NAME)
    assert "<" not in displayed[2]["name"]


def test_season_window_plan_available():
    plan = season_window_plan((2024, 2025, 2026), end_year=2026, size=2)
    assert plan.available is True
    assert plan.years == (2025, 2026)
    assert plan.missing == ()
    assert plan.label == "2-season window 2025\u20132026"


def test_season_window_plan_marks_missing_prior_season_unavailable():
    plan = season_window_plan((2025, 2026), end_year=2025, size=2)
    assert plan.available is False
    assert plan.years is None
    assert plan.missing == (2024,)
    assert "unavailable" in plan.label
    assert "2024" in plan.reason


def test_window_plans_never_silently_shorten():
    plans = window_plans((2026,), end_year=2026)
    assert [plan.size for plan in plans] == [1, 2, 3]
    assert plans[0].available is True and plans[0].years == (2026,)
    assert plans[1].available is False and plans[1].years is None
    assert plans[2].available is False and plans[2].years is None


def test_window_plans_include_reason_for_missing_seasons():
    plans = window_plans((2024, 2025, 2026), end_year=2024)
    assert plans[1].available is False
    assert "2023" in plans[1].reason
    assert plans[2].available is False
    assert "2022" in plans[2].reason and "2023" in plans[2].reason
    assert plans[0].available is True


def test_window_label():
    assert window_label((2026,)) == "2026"
    assert window_label((2025, 2026)) == "2025\u20132026"
    assert window_label((2024, 2025, 2026)) == "2024\u20132026"
    assert window_label(()) == "no seasons"


def test_season_selection_problem():
    assert season_selection_problem(()) is not None
    assert season_selection_problem((2026,)) is None
    assert season_selection_problem((2025, 2026)) is None
    assert season_selection_problem((2024, 2025, 2026)) is None
    assert season_selection_problem((2024, 2025, 2026, 2027)) is not None
    assert season_selection_problem((2024, 2024)) is not None
    assert season_selection_problem((2024, 2026)) is not None


def test_run_metadata_rows_report_full_eligibility_metadata():
    metadata = {row["field"]: row["value"] for row in run_metadata_rows(make_calculation_result())}
    assert metadata["Seasons"] == "2025\u20132026"
    assert metadata["Players rated"] == 3
    assert metadata["Matches rated"] == 3
    assert metadata["Retirements included"] == "yes"
    assert metadata["K-factor"] == "32"
    assert metadata["Available seasons"] == "2024, 2025, 2026"
    assert metadata["Input files"].endswith("2026-atp-season.csv")
    assert metadata["Excluded rows"] == 2
    assert metadata["Accounting check"] == "consistent"


def test_exclusion_rows_sorted_by_count():
    rows = exclusion_rows({"walkover": 1, "exhibition": 3, "canceled": 0})
    assert [(row["exclusion"], row["count"]) for row in rows] == [
        ("exhibition", 3),
        ("walkover", 1),
        ("canceled", 0),
    ]


def test_load_accounting_consistent_and_inconsistent():
    load = make_calculation_result().load
    accounting = load_accounting(load)
    assert accounting.consistent is True
    assert accounting.computed_selected_rows == 6

    broken = dataclasses.replace(load, duplicate_rows=7)
    assert load_accounting(broken).consistent is False


def test_timestamp_to_iso_date_handles_invalid_values():
    assert timestamp_to_iso_date(TS_1) == "2026-01-01"
    assert timestamp_to_iso_date("not-a-timestamp") == ""


def test_player_history_rows_filters_sorts_and_labels_opponent():
    rows = player_history_rows(make_history_rows(), "p1")
    assert [row["match_id"] for row in rows] == ["m1", "m2", "m3"]
    assert rows[-1]["opponent"] == safe_label(HOSTILE_NAME)
    assert player_history_rows(make_history_rows(), "unknown") == ()
    assert all(row["player_id"] == "p1" for row in rows)


def test_elo_chart_rows_expose_dates_and_rounded_ratings():
    rows = elo_chart_rows(make_history_rows(), "p1")
    assert [row["date"] for row in rows] == ["2026-01-01", "2026-01-02", "2026-07-01"]
    assert [row["rating"] for row in rows] == [1516.0, 1498.6, 1532.5]


def test_player_stat_rows_include_win_rate_and_ids():
    stats = {row["stat"]: row["value"] for row in player_stat_rows(make_ranking_rows()[0])}
    assert stats["Player ID"] == "p1"
    assert stats["Rating"] == 1532.5
    assert stats["Win rate"] == "66.7%"
    assert stats["First match"] == "2026-01-01"


def test_control_error_and_build_rating_config():
    assert control_error(initial_rating=1500.0, k_factor=32.0) is None
    assert "finite" in control_error(initial_rating=float("nan"), k_factor=32.0)
    assert "greater than zero" in control_error(initial_rating=1500.0, k_factor=0.0)
    config = build_rating_config(initial_rating=1400.0, k_factor=16.0, include_retirements=False)
    assert config == RatingConfig(initial_rating=1400.0, k_factor=16.0, include_retirements=False)
    with pytest.raises(ValueError):
        build_rating_config(initial_rating=1500.0, k_factor=-1.0, include_retirements=True)


def test_error_message_maps_validation_filesystem_and_missing_dependency():
    assert "Invalid data" in error_message(ValueError("seasons must be consecutive"))
    assert "not found" in error_message(FileNotFoundError("no such directory"))
    assert MISSING_DASHBOARD_DEPENDENCIES in error_message(
        ModuleNotFoundError("No module named 'streamlit'")
    )
    assert "uv sync --extra dashboard" in error_message(
        ModuleNotFoundError("No module named 'streamlit'")
    )
    assert "pandas" in error_message(ModuleNotFoundError("No module named 'pandas'"))
    assert "tennis_elo.api" in error_message(
        ModuleNotFoundError("No module named 'tennis_elo.api'")
    )
    assert "<img" not in error_message(ValueError(HOSTILE_NAME))


def test_comparison_entry_reads_models_and_disambiguates_top_player():
    entry = comparison_entry(make_calculation_result())
    assert entry["players_rated"] == 3
    assert entry["matches_processed"] == 3
    assert entry["top_player"] == "Alpha A. (p1)"
    assert entry["top_rating"] == 1532.5
    assert entry["seasons"] == "2025\u20132026"
    assert entry["excluded_matches"] == 2
    assert entry["duplicate_rows"] == 1


def test_comparison_rows_mark_unavailable_and_error_windows():
    plans = window_plans((2025, 2026), end_year=2026)
    entries = {1: comparison_entry(make_calculation_result(seasons=(2026,))), 2: "boom"}
    rows = comparison_rows(plans, entries)
    assert [row["status"] for row in rows] == ["available", "error", "unavailable"]
    assert rows[2]["seasons"] == ""
    assert "2024" in rows[2]["note"]
    assert rows[0]["top_player"] == "Alpha A. (p1)"
    assert rows[1]["note"] == "boom"


# --------------------------------------------------------------------------- #
# Launcher
# --------------------------------------------------------------------------- #


def test_default_app_path_points_to_dashboard_file():
    assert dashboard_launcher.APP_PATH.name == "dashboard.py"
    assert dashboard_launcher.APP_PATH.exists()


def test_build_streamlit_argv_binds_localhost_and_app_file():
    argv = dashboard_launcher.build_streamlit_argv(app_path=Path("/tmp/dashboard.py"))
    assert argv[:2] == ["streamlit", "run"]
    assert argv[2] == "/tmp/dashboard.py"
    assert "--server.address=localhost" in argv
    assert "--server.port=8501" in argv
    assert "--browser.gatherUsageStats=false" in argv


def test_build_streamlit_argv_includes_headless_and_extra_args():
    argv = dashboard_launcher.build_streamlit_argv(
        port=8600,
        address="127.0.0.1",
        headless=True,
        extra=("--theme.base=dark",),
        app_path=Path("/tmp/dashboard.py"),
    )
    assert "--server.address=127.0.0.1" in argv
    assert "--server.port=8600" in argv
    assert "--server.headless=true" in argv
    assert argv[-1] == "--theme.base=dark"


def test_launcher_main_runs_streamlit_cli_and_restores_argv(monkeypatch):
    seen = {}

    def fake_cli_main():
        seen["argv"] = list(sys.argv)
        return 0

    monkeypatch.setattr(dashboard_launcher, "_import_streamlit_cli_main", lambda: fake_cli_main)
    original = list(sys.argv)
    assert dashboard_launcher.main(["--port", "8601"]) == 0
    assert seen["argv"][:2] == ["streamlit", "run"]
    assert "--server.port=8601" in seen["argv"]
    assert sys.argv == original


def test_launcher_main_reports_missing_dashboard_extra(monkeypatch, capsys):
    def missing_cli_main():
        raise ModuleNotFoundError("No module named 'streamlit'")

    monkeypatch.setattr(dashboard_launcher, "_import_streamlit_cli_main", missing_cli_main)
    assert dashboard_launcher.main([]) == 1
    captured = capsys.readouterr()
    assert "uv sync --extra dashboard" in captured.err


def test_launcher_main_rejects_invalid_port(capsys):
    assert dashboard_launcher.main(["--port", "0"]) == 2
    assert dashboard_launcher.main(["--port", "70000"]) == 2
    assert "port" in capsys.readouterr().err.lower()


def test_launcher_help_returns_zero(capsys):
    assert dashboard_launcher.main(["--help"]) == 0
    assert "tennis-elo-dashboard" in capsys.readouterr().out


def test_launcher_import_does_not_import_streamlit_or_pandas():
    script = (
        "import sys; import tennis_elo.dashboard_launcher as launcher;"
        "assert launcher.APP_PATH.exists();"
        "print('streamlit' in sys.modules, 'pandas' in sys.modules)"
    )
    completed = subprocess.run(
        [sys.executable, "-c", script], cwd=REPO_ROOT, capture_output=True, text=True, check=True
    )
    assert completed.stdout.strip() == "False False"


# --------------------------------------------------------------------------- #
# Streamlit app (AppTest)
# --------------------------------------------------------------------------- #

st = pytest.importorskip("streamlit")

from streamlit.testing.v1 import AppTest


def _install_stub_modules(
    monkeypatch,
    *,
    seasons=(2024, 2025, 2026),
    result=None,
    calculate_error=None,
    calls=None,
):
    """Inject stub P0 modules; the app imports them lazily at runtime only."""
    api_stub = types.ModuleType("tennis_elo.api")
    export_stub = types.ModuleType("tennis_elo.export")

    def note(*entry):
        if calls is not None:
            calls.append(entry)

    def fake_available_seasons(input_dir):
        note("available_seasons", str(input_dir))
        return tuple(seasons)

    def fake_calculate(input_dir, seasons_, *, config=None, include_history=False):
        note("calculate", tuple(seasons_), config, include_history)
        if calculate_error is not None:
            raise calculate_error
        return result if result is not None else make_calculation_result(tuple(seasons_))

    def fake_ranking_rows(calculated, min_matches=0):
        note("ranking_rows", min_matches)
        return make_ranking_rows()

    def fake_history_rows(calculated):
        note("history_rows")
        return make_history_rows()

    def fake_rankings_csv(calculated, min_matches=0):
        note("rankings_csv", min_matches)
        return "rank,player_id\n1,p1\n"

    def fake_history_csv(calculated):
        note("history_csv")
        return "date,match_id\n2026-01-01,m1\n"

    api_stub.available_seasons = fake_available_seasons
    api_stub.calculate = fake_calculate
    export_stub.ranking_rows = fake_ranking_rows
    export_stub.history_rows = fake_history_rows
    export_stub.rankings_csv = fake_rankings_csv
    export_stub.history_csv = fake_history_csv
    monkeypatch.setitem(sys.modules, "tennis_elo.api", api_stub)
    monkeypatch.setitem(sys.modules, "tennis_elo.export", export_stub)
    return api_stub, export_stub


def _run_app(monkeypatch, **stub_kwargs):
    _install_stub_modules(monkeypatch, **stub_kwargs)
    app = AppTest.from_file(str(APP_PATH), default_timeout=60)
    app.run()
    return app


def _texts(elements):
    return " ".join(element.value for element in elements)


def _frame(app, columns):
    """Find a rendered dataframe by its column contract.

    ``st.dataframe`` user keys are not exposed through this AppTest version, so
    tests identify tables by the columns they are specified to render.
    """
    for element in app.dataframe:
        frame = element.value
        if frame is not None and list(frame.columns) == list(columns):
            return frame
    raise AssertionError(f"no rendered dataframe with columns {list(columns)}")


def test_app_renders_caveat_and_calculation_controls(monkeypatch):
    app = _run_app(monkeypatch)
    assert not app.exception
    assert FRESH_START_NOTICE in _texts(app.info)
    assert app.button(key="calculate").label == "Calculate ratings"
    assert app.number_input(key="initial_rating").value == 1500.0
    assert app.number_input(key="k_factor").value == 32.0
    assert app.checkbox(key="include_retirements").value is True
    assert app.number_input(key="min_matches").value == 0
    assert app.selectbox(key="end_season").value == 2026
    assert list(app.multiselect(key="seasons").value) == [2026]


def test_app_reports_missing_data_directory_without_exception(monkeypatch):
    app = _run_app(monkeypatch)
    app.text_input(key="input_dir").set_value(str(REPO_ROOT / "definitely-missing")).run()
    assert not app.exception
    assert "not found" in _texts(app.error).lower()


def test_app_reports_missing_seasons_without_exception(monkeypatch):
    app = _run_app(monkeypatch, seasons=())
    assert not app.exception
    assert "no seasons" in (_texts(app.warning) + _texts(app.error)).lower()
    assert app.button(key="calculate").disabled is True


def test_app_calculates_and_renders_leaderboard_player_detail_and_downloads(monkeypatch):
    calls = []
    app = _run_app(monkeypatch, calls=calls)
    assert not app.button(key="calculate").value
    assert not app.dataframe

    app.button(key="calculate").click().run()
    assert not app.exception

    assert [call[0] for call in calls if call[0] in {"available_seasons", "calculate"}] == [
        "available_seasons",
        "calculate",
    ]
    calculate_call = next(call for call in calls if call[0] == "calculate")
    assert calculate_call[1] == (2026,)
    assert calculate_call[2] == RatingConfig()
    assert calculate_call[3] is True  # history is always requested

    leaderboard = _frame(app, LEADERBOARD_COLUMNS)
    assert list(leaderboard["player_id"]) == ["p1", "p2", "p3"]
    assert leaderboard["rating"].iloc[1] == 1484.2  # rounded for presentation only

    metadata = {
        row["field"]: row["value"] for row in _frame(app, ("field", "value")).to_dict("records")
    }
    assert metadata["Players rated"] == "3"
    assert metadata["Matches rated"] == "3"
    assert metadata["Seasons"] == "2026"
    assert metadata["Accounting check"] == "consistent"
    assert _frame(app, ("exclusion", "count"))["exclusion"].tolist()[:1] == ["exhibition"]

    # The rankings CSV comes from the P0 export with the presentation filter forwarded.
    assert app.download_button(key="download_rankings").label == "Download rankings CSV"
    assert ("rankings_csv", 0) in calls
    assert not any(call[0] == "history_csv" for call in calls)

    assert "Player ID" in set(_frame(app, ("stat", "value"))["stat"])
    assert "(p1)" in app.selectbox(key="player_label").value
    assert _frame(app, HISTORY_COLUMNS) is not None
    assert len(app.get("vega_lite_chart")) >= 1


def test_app_preset_marks_unavailable_window_without_shortening(monkeypatch):
    app = _run_app(monkeypatch, seasons=(2025, 2026))
    app.radio(key="preset_size").set_value("3 seasons").run()
    assert list(app.multiselect(key="seasons").value) == []  # never silently shortened
    notices = _texts(app.info) + _texts(app.warning)
    assert "unavailable" in notices.lower()
    assert "2024" in notices
    assert app.button(key="calculate").disabled is True

    app.radio(key="preset_size").set_value("2 seasons").run()
    assert list(app.multiselect(key="seasons").value) == [2025, 2026]
    assert app.button(key="calculate").disabled is False


def test_app_warns_when_controls_change_after_calculation(monkeypatch):
    app = _run_app(monkeypatch)
    app.button(key="calculate").click().run()
    assert not app.warning
    app.number_input(key="k_factor").set_value(16.0).run()
    assert "changed" in _texts(app.warning).lower()


def test_app_leaderboard_search_and_sort(monkeypatch):
    calls = []
    app = _run_app(monkeypatch, calls=calls)
    app.button(key="calculate").click().run()
    app.text_input(key="leaderboard_search").set_value("p3").run()
    assert list(_frame(app, LEADERBOARD_COLUMNS)["player_id"]) == ["p3"]

    app.text_input(key="leaderboard_search").set_value("").run()
    app.selectbox(key="leaderboard_sort").set_value("matches").run()
    assert list(_frame(app, LEADERBOARD_COLUMNS)["player_id"]) == ["p3", "p2", "p1"]

    app.number_input(key="min_matches").set_value(2).run()
    app.button(key="calculate").click().run()
    assert list(_frame(app, LEADERBOARD_COLUMNS)["player_id"]) == ["p2", "p1"]
    assert ("rankings_csv", 2) in calls
    # Minimum matches is presentation only: it never reaches the rating call.
    assert all(len(call) == 4 for call in calls if call[0] == "calculate")


def test_app_player_selector_disambiguates_ids_and_search_resets_selection(monkeypatch):
    app = _run_app(monkeypatch)
    app.button(key="calculate").click().run()

    labels = app.selectbox(key="player_label").options
    assert labels == [
        "Alpha A. (p1)",
        "Alpha A. (p2)",
        "img src=x onerror=alert(1) (p3)",
    ]
    assert len(set(labels)) == 3  # duplicate player names stay distinguishable by ID

    app.selectbox(key="player_label").select(labels[2]).run()
    assert "p3" in app.selectbox(key="player_label").value
    rendered = _texts(app.subheader) + _texts(app.markdown) + _texts(app.caption)
    assert "alert" in rendered
    assert "<img" not in rendered

    app.text_input(key="player_search").set_value("p2").run()
    assert app.selectbox(key="player_label").value == "Alpha A. (p2)"

    app.text_input(key="player_search").set_value("no-such-player").run()
    assert not app.exception
    assert "no player" in _texts(app.info).lower()


def test_app_player_history_and_chart_follow_selected_player(monkeypatch):
    app = _run_app(monkeypatch)
    app.button(key="calculate").click().run()
    assert list(_frame(app, HISTORY_COLUMNS)["match_id"]) == ["m1", "m2", "m3"]

    app.selectbox(key="player_label").select("Alpha A. (p2)").run()
    assert list(_frame(app, HISTORY_COLUMNS)["match_id"]) == ["m1"]


def test_app_history_csv_download_is_opt_in(monkeypatch):
    calls = []
    app = _run_app(monkeypatch, calls=calls)
    app.button(key="calculate").click().run()
    assert not app.toggle(key="prepare_history").value
    with pytest.raises(KeyError):
        app.download_button(key="download_history")
    assert not any(call[0] == "history_csv" for call in calls)

    app.toggle(key="prepare_history").set_value(True).run()
    assert app.download_button(key="download_history").label == "Download match-history CSV"
    assert [call[0] for call in calls if call[0] == "history_csv"] == ["history_csv"]

    app.button(key="reload_seasons").click().run()
    assert [call[0] for call in calls if call[0] == "history_csv"] == ["history_csv"]


def test_app_surfaces_calculation_errors(monkeypatch):
    app = _run_app(monkeypatch, calculate_error=ValueError("seasons must be consecutive"))
    app.button(key="calculate").click().run()
    assert not app.exception
    assert "Invalid data" in _texts(app.error)
    assert "consecutive" in _texts(app.error)


def test_app_rejects_invalid_explicit_selection(monkeypatch):
    app = _run_app(monkeypatch)
    app.multiselect(key="seasons").set_value([2024, 2026]).run()
    app.button(key="calculate").click().run()
    assert not app.exception
    assert "consecutive" in _texts(app.error).lower()


def test_app_comparison_labels_unavailable_windows(monkeypatch):
    calls = []
    app = _run_app(monkeypatch, seasons=(2025, 2026), calls=calls)
    app.button(key="calculate").click().run()
    calls.clear()

    app.button(key="compare_windows").click().run()
    assert not app.exception
    comparison = _frame(app, COMPARISON_COLUMNS)
    statuses = list(comparison["status"])
    assert statuses == ["available", "available", "unavailable"]
    assert "2024" in comparison["note"].iloc[2]
    assert list(comparison["seasons"])[:2] == ["2026", "2025\u20132026"]

    computed_windows = [call[1] for call in calls if call[0] == "calculate"]
    assert computed_windows == [(2026,), (2025, 2026)]
    assert all(call[3] is False for call in calls if call[0] == "calculate")
    assert "initial rating" in _texts(app.info).lower()


@pytest.mark.skipif(not REAL_CSV.exists(), reason="real season CSV not available")
def test_app_integration_with_real_p0_modules_and_data():
    pytest.importorskip("tennis_elo.api")
    pytest.importorskip("tennis_elo.export")

    app = AppTest.from_file(str(APP_PATH), default_timeout=300)
    app.run()
    assert not app.exception

    app.text_input(key="input_dir").set_value(str(REPO_ROOT)).run()
    assert not app.exception
    assert int(app.selectbox(key="end_season").value) == 2026

    app.button(key="calculate").click().run()
    assert not app.exception, _texts(app.error)
    leaderboard = _frame(app, LEADERBOARD_COLUMNS)
    assert len(leaderboard) > 0
    rankings_csv = app.download_button(key="download_rankings")
    assert rankings_csv.label == "Download rankings CSV"
