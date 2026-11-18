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
import os
import subprocess
import sys
import types
from datetime import UTC, datetime
from pathlib import Path

import pytest

from tennis_elo import dashboard_launcher
from tennis_elo.dashboard_views import (
    CLASSIFICATION_COLUMNS,
    COEFFICIENT_COLUMNS,
    COMPARISON_COLUMNS,
    DATA_DIR_ENV,
    FRESH_START_NOTICE,
    HISTORY_COLUMNS,
    LEADERBOARD_COLUMNS,
    MISSING_DASHBOARD_DEPENDENCIES,
    PLAYER_COMPARISON_COLUMNS,
    TOP_PLAYERS_ENV,
    UNKNOWN_TOURNAMENT_COLUMNS,
    build_player_options,
    build_rating_config,
    coefficient_rows,
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
    merge_player_rows,
    plain_text,
    player_comparison_rows,
    player_history_rows,
    player_option_label,
    player_stat_rows,
    run_metadata_rows,
    safe_download_filename,
    safe_label,
    season_selection_problem,
    season_window_plan,
    sort_ranking_rows,
    timestamp_to_datetime_utc,
    timestamp_to_iso_date,
    top_players_chart_rows,
    top_players_limit,
    tournament_weighting_report,
    weighting_mode_notice,
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
from tennis_elo.weighting import TOURNAMENT_COEFFICIENTS

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_PATH = REPO_ROOT / "src" / "tennis_elo" / "dashboard.py"
DEPLOY_APP_PATH = REPO_ROOT / "deploy" / "streamlit_app.py"
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


def make_calculation_result(
    seasons: tuple[int, ...] = (2025, 2026), *, config: RatingConfig | None = None
) -> CalculationResult:
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
    return CalculationResult(
        seasons=seasons, config=config if config is not None else RatingConfig(), load=load,
        ratings=ratings,
    )


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


def same_day_history_rows() -> list[dict]:
    """Two matches for p1 on the same UTC date, one morning and one midday."""
    base = {
        "season_year": 2026,
        "player_id": "p1",
        "player_name": "Alpha A.",
        "opponent_id": "p2",
        "opponent_name": "Beta B.",
        "won": True,
        "rating_before": 1500.0,
        "opponent_rating_before": 1500.0,
        "expected_score": 0.5,
        "tournament": "Test Open",
        "surface": "hard",
    }
    return [
        {**base, "match_id": "m-late", "timestamp": TS_1 + 43200, "rating_after": 1516.0},
        {**base, "match_id": "m-early", "timestamp": TS_1, "rating_after": 1508.0},
    ]


def weighted_history_rows() -> list[dict]:
    """Export-shaped history rows that carry recorded weighting metadata."""
    base = {
        "season_year": 2026,
        "player_id": "p1",
        "player_name": "Alpha A.",
        "opponent_id": "p2",
        "opponent_name": "Beta B.",
        "won": True,
        "rating_before": 1500.0,
        "opponent_rating_before": 1500.0,
        "expected_score": 0.5,
        "surface": "hard",
        "date": "2026-01-01",
    }
    return [
        {
            **base,
            "match_id": "g1",
            "timestamp": TS_1,
            "rating_after": 1532.0,
            "tournament": "Wimbledon",
            "tournament_level": "grand_slam",
            "tournament_weight": 2.0,
            "effective_k_factor": 64.0,
        },
        {
            **base,
            "match_id": "a1",
            "timestamp": TS_2,
            "rating_after": 1540.0,
            "tournament": "Doha",
            "tournament_level": "atp_250",
            "tournament_weight": 1.0,
            "effective_k_factor": 32.0,
        },
    ]


_DEFAULT_SUMMARY = object()


def make_weighting_section(
    *,
    enabled: bool = True,
    unknown: tuple[dict, ...] = (),
    matches_by_level=None,
) -> dict:
    """The sibling ``tournament_weighting`` summary section shape."""
    return {
        "enabled": enabled,
        "coefficients": dict(TOURNAMENT_COEFFICIENTS),
        "matches_by_level": {"atp_250": 3} if matches_by_level is None else matches_by_level,
        "unknown_matches": sum(int(record["matches"]) for record in unknown),
        "unknown_tournaments": [dict(record) for record in unknown],
    }


def make_summary(result=None, *, weighting_section=_DEFAULT_SUMMARY) -> dict:
    """A summary dict in the shape ``tennis_elo.export.summary_dict`` promises."""
    if result is None:
        result = make_calculation_result()
    config = result.config
    summary = {
        "seasons": list(result.seasons),
        "configuration": {
            "initial_rating": config.initial_rating,
            "k_factor": config.k_factor,
            "include_retirements": config.include_retirements,
            "use_tournament_weights": config.use_tournament_weights,
        },
        "fresh_start": True,
    }
    if weighting_section is _DEFAULT_SUMMARY:
        summary["tournament_weighting"] = make_weighting_section(
            enabled=config.use_tournament_weights
        )
    elif weighting_section is not None:
        summary["tournament_weighting"] = weighting_section
    return summary


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
    assert all(
        option.label == player_option_label(option.name, option.player_id) for option in options
    )


def test_player_options_preserve_raw_ids_while_labels_stay_display_safe():
    rows = [
        {"player_id": " 12345 ", "name": HOSTILE_NAME},
        {"player_id": "[evil](x)", "name": "Normal N."},
        {"player_id": "", "name": "ghost"},
    ]
    options = build_player_options(rows)
    # Selection state must keep the raw identity the API uses, not a display label.
    assert [option.player_id for option in options] == ["12345", "[evil](x)"]
    assert options[0].label == "img src=x onerror=alert(1) (12345)"
    assert "<" not in options[0].label and ">" not in options[0].label


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
    assert metadata["Base K-factor"] == "32"
    assert "enabled" in metadata["Tournament weighting"]
    assert "effective K" in metadata["Tournament weighting"]
    assert metadata["Available seasons"] == "2024, 2025, 2026"
    assert metadata["Input files"].endswith("2026-atp-season.csv")
    assert metadata["Excluded rows"] == 2
    assert metadata["Accounting check"] == "consistent"


def test_run_metadata_rows_report_the_weighting_mode_truthfully():
    weighted = {
        row["field"]: row["value"] for row in run_metadata_rows(make_calculation_result())
    }
    assert weighted["Base K-factor"] == "32"
    assert weighted["Tournament weighting"].startswith("enabled")
    assert "effective K" in weighted["Tournament weighting"]

    unweighted_result = make_calculation_result(
        config=RatingConfig(use_tournament_weights=False)
    )
    unweighted = {
        row["field"]: row["value"] for row in run_metadata_rows(unweighted_result)
    }
    assert unweighted["Tournament weighting"].startswith("disabled")
    assert "classic" in unweighted["Tournament weighting"].lower()


def test_coefficient_rows_show_the_fixed_canonical_policy():
    rows = coefficient_rows()
    assert list(rows[0]) == list(COEFFICIENT_COLUMNS)
    assert [row["coefficient"] for row in rows] == [
        0.75,
        1.0,
        1.25,
        1.5,
        1.75,
        2.0,
        1.0,
        1.0,
    ]
    labels = " ".join(row["level"] for row in rows).lower()
    for token in ("challenger", "atp 250", "atp 500", "masters 1000", "atp finals"):
        assert token in labels
    assert "grand slam" in labels
    assert "other" in labels and "unknown" in labels and "fallback" in labels
    assert {row["coefficient"] for row in rows} == set(TOURNAMENT_COEFFICIENTS.values())


def test_weighting_mode_notice_explains_base_and_effective_k():
    weighted = weighting_mode_notice(True)
    lowered = weighted.lower()
    assert "base k" in lowered and "effective k" in lowered
    assert "coefficient" in lowered
    assert "base k x" in lowered or "base k *" in lowered

    unweighted = weighting_mode_notice(False).lower()
    assert "classic elo" in unweighted
    assert "effective k" in unweighted
    assert "base k" in unweighted


def test_tournament_weighting_report_reads_the_summary_section_and_warns_on_unknowns():
    result = make_calculation_result()
    summary = make_summary(
        result,
        weighting_section=make_weighting_section(
            unknown=(
                {"season_year": 2025, "tournament": "Mystery Cup", "matches": 1},
                {"season_year": 2024, "tournament": "Atlantis Open", "matches": 2},
            ),
            matches_by_level={"grand_slam": 1, "atp_250": 2},
        ),
    )
    report = tournament_weighting_report(result, summary)
    assert report.reported is True
    assert report.enabled is True
    assert report.absent_notice == ""
    assert [row["level"] for row in report.matches_by_level] == ["ATP 250", "Grand Slam"]
    assert [row["matches"] for row in report.matches_by_level] == [2, 1]
    assert list(report.matches_by_level[0]) == list(CLASSIFICATION_COLUMNS)
    assert report.unknown_matches == 3
    # Deterministic display order even if the summary is not pre-sorted.
    assert [row["tournament"] for row in report.unknown_tournaments] == [
        "Atlantis Open",
        "Mystery Cup",
    ]
    assert [row["season_year"] for row in report.unknown_tournaments] == [2024, 2025]
    assert list(report.unknown_tournaments[0]) == list(UNKNOWN_TOURNAMENT_COLUMNS)
    notice = report.unknown_notice.lower()
    assert "3" in notice and "fallback" in notice and "unknown" in notice


def test_tournament_weighting_report_accepts_record_style_level_counts():
    section = make_weighting_section(matches_by_level=[{"level": "atp_500", "matches": 4}])
    result = make_calculation_result()
    report = tournament_weighting_report(result, {"tournament_weighting": section})
    assert report.reported is True
    assert report.matches_by_level == ({"level": "ATP 500", "matches": 4},)


def test_tournament_weighting_report_unweighted_mode_has_no_unknown_warning():
    result = make_calculation_result(config=RatingConfig(use_tournament_weights=False))
    report = tournament_weighting_report(result, make_summary(result))
    assert report.enabled is False
    assert report.reported is True
    assert report.unknown_matches == 0
    assert report.unknown_notice == ""


def test_tournament_weighting_report_without_the_section_never_invents_data():
    result = make_calculation_result()
    summaries = (
        None,
        {},
        {"configuration": {}},
        {"configuration": {"use_tournament_weights": True}},
        {"tournament_weighting": None},
        {"tournament_weighting": "not-a-mapping"},
    )
    for summary in summaries:
        report = tournament_weighting_report(result, summary)
        assert report.reported is False, summary
        # The frozen run config is authoritative for the mode, even without a summary.
        assert report.enabled is True, summary
        assert report.matches_by_level == (), summary
        assert report.unknown_matches is None, summary
        assert report.unknown_tournaments == (), summary
        assert report.unknown_notice == "", summary
        assert "did not include" in report.absent_notice.lower()


def test_history_columns_contract_includes_the_weighting_fields():
    assert HISTORY_COLUMNS[:4] == ("date", "match_id", "season_year", "tournament")
    assert HISTORY_COLUMNS[4:7] == (
        "tournament_level",
        "tournament_weight",
        "effective_k_factor",
    )


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


def test_timestamp_to_datetime_utc_handles_invalid_values():
    moment = timestamp_to_datetime_utc(TS_1)
    assert moment == datetime(2026, 1, 1, tzinfo=UTC)
    assert moment.tzinfo is UTC
    assert timestamp_to_datetime_utc("not-a-timestamp") is None
    assert timestamp_to_datetime_utc(None) is None
    assert timestamp_to_datetime_utc(True) is None


def test_player_history_rows_show_recorded_weighting_values():
    rows = player_history_rows(make_history_rows(), "p1")
    # The shared model defaults are real recorded values, not invented ones.
    assert rows[0]["tournament_level"] == "unknown"
    assert rows[0]["tournament_weight"] == 1.0
    assert rows[0]["effective_k_factor"] == 32.0

    recorded = player_history_rows(weighted_history_rows(), "p1")
    assert [row["match_id"] for row in recorded] == ["g1", "a1"]
    assert recorded[0]["tournament_level"] == "grand_slam"
    assert recorded[0]["tournament_weight"] == 2.0
    assert recorded[0]["effective_k_factor"] == 64.0
    assert recorded[1]["tournament_level"] == "atp_250"


def test_player_history_rows_do_not_invent_missing_weighting_values():
    legacy = [{"player_id": "p1", "match_id": "old", "timestamp": TS_1, "rating_after": 1510.0}]
    row = player_history_rows(legacy, "p1")[0]
    assert row["tournament_level"] == ""
    assert row["tournament_weight"] == ""
    assert row["effective_k_factor"] == ""


def test_player_history_rows_filters_sorts_and_labels_opponent():
    rows = player_history_rows(make_history_rows(), "p1")
    assert [row["match_id"] for row in rows] == ["m1", "m2", "m3"]
    assert rows[-1]["opponent"] == safe_label(HOSTILE_NAME)
    assert player_history_rows(make_history_rows(), "unknown") == ()
    assert all(row["player_id"] == "p1" for row in rows)


def test_elo_chart_rows_expose_dates_and_rounded_ratings():
    rows = elo_chart_rows(make_history_rows(), "p1")
    assert [row["match_date"] for row in rows] == [
        datetime(2026, 1, 1, tzinfo=UTC),
        datetime(2026, 1, 2, tzinfo=UTC),
        datetime(2026, 7, 1, tzinfo=UTC),
    ]
    assert [row["rating"] for row in rows] == [1516.0, 1498.6, 1532.5]
    assert all(isinstance(row["match_date"], datetime) for row in rows)


def test_elo_chart_rows_keep_same_day_matches_distinct_and_ordered():
    points = elo_chart_rows(same_day_history_rows(), "p1")
    assert [point["match_id"] for point in points] == ["m-early", "m-late"]
    assert [point["match_date"] for point in points] == [
        datetime(2026, 1, 1, tzinfo=UTC),
        datetime(2026, 1, 1, 12, tzinfo=UTC),
    ]
    assert points[0]["match_date"] != points[1]["match_date"]  # one point per match
    assert [point["rating"] for point in points] == [1508.0, 1516.0]


def test_top_players_chart_rows_cover_the_top_ranked_players_in_rank_order():
    ranking = list(reversed(make_ranking_rows()))  # input order must not matter
    points = top_players_chart_rows(ranking, make_history_rows(), limit=2)
    assert {point["player_id"] for point in points} == {"p1", "p2"}
    # Legend labels sort in rank order and stay distinct even for duplicate names.
    assert sorted({point["player"] for point in points}) == ["#01 Alpha A.", "#02 Alpha A."]
    p1 = [point for point in points if point["player_id"] == "p1"]
    assert [point["rating"] for point in p1] == [1516.0, 1498.6, 1532.5]
    assert all(isinstance(point["match_date"], datetime) for point in points)


def test_top_players_chart_rows_respect_min_matches_and_handle_empty_input():
    points = top_players_chart_rows(make_ranking_rows(), make_history_rows(), min_matches=2)
    assert {point["player_id"] for point in points} == {"p1", "p2"}
    assert top_players_chart_rows([], make_history_rows()) == ()
    assert top_players_chart_rows(make_ranking_rows(), []) == ()


def test_top_players_chart_rows_default_to_twenty_players():
    ranking = [
        {"rank": rank, "player_id": f"q{rank}", "name": f"Q{rank}", "matches": 1}
        for rank in range(1, 26)
    ]
    history = [
        {"player_id": f"q{rank}", "match_id": f"m{rank}", "timestamp": TS_1, "rating_after": 1500}
        for rank in range(1, 26)
    ]
    points = top_players_chart_rows(ranking, history)
    assert [point["player_id"] for point in points] == [f"q{rank}" for rank in range(1, 21)]


def test_top_players_limit_parses_and_clamps_the_configured_value():
    assert top_players_limit(None) == 20
    assert top_players_limit("") == 20
    assert top_players_limit("10") == 10
    assert top_players_limit(" 7 ") == 7
    assert top_players_limit("abc") == 20
    assert top_players_limit("0") == 1
    assert top_players_limit("500") == 50
    assert TOP_PLAYERS_ENV == "TENNIS_ELO_TOP_PLAYERS"


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
    assert config.use_tournament_weights is True
    unweighted = build_rating_config(
        initial_rating=1400.0,
        k_factor=16.0,
        include_retirements=False,
        use_tournament_weights=False,
    )
    assert unweighted == RatingConfig(
        initial_rating=1400.0,
        k_factor=16.0,
        include_retirements=False,
        use_tournament_weights=False,
    )
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


def test_fresh_start_notice_states_carry_within_run_and_independent_resets():
    notice = FRESH_START_NOTICE.lower()
    assert "initial rating" in notice
    assert "carry" in notice and "within" in notice
    assert "independent" in notice or "separately" in notice
    assert "not continuous annual" in notice


def test_merge_player_rows_prefers_the_nearest_window():
    newest = [{"player_id": "p1", "name": "Alice New"}]
    older = [
        {"player_id": "p1", "name": "Alice Old"},
        {"player_id": "p4", "name": "Veteran V."},
    ]
    merged = merge_player_rows([newest, older])
    assert [row["player_id"] for row in merged] == ["p1", "p4"]
    assert merged[0]["name"] == "Alice New"
    assert merge_player_rows([]) == ()
    assert merge_player_rows([[], []]) == ()


def test_player_comparison_rows_statuses_never_fake_ratings():
    plans = window_plans((2024, 2025, 2026), end_year=2026)
    top = make_ranking_rows()[0]
    players = {1: {"p1": top}, 3: {"p1": top}}
    rows = player_comparison_rows(plans, players, player_id="p1", player_label="Alice New (p1)")
    assert [row["status"] for row in rows] == ["rated", "not rated", "rated"]
    assert rows[0]["rating"] == 1532.5 and rows[0]["rank"] == 1 and rows[0]["matches"] == 3
    assert rows[0]["player"] == "Alice New (p1)"
    assert rows[1]["rating"] == "" and rows[1]["rank"] == "" and rows[1]["matches"] == ""
    assert "1500" not in str(rows[1])
    assert "no eligible match" in rows[1]["note"]

    with_errors = player_comparison_rows(
        plans, players, player_id="p1", player_label="Alice New (p1)", errors={3: "boom"}
    )
    assert with_errors[2]["status"] == "error" and with_errors[2]["note"] == "boom"

    short = window_plans((2026,), end_year=2026)
    unavailable = player_comparison_rows(short, {}, player_id="p1", player_label="Alice New (p1)")
    assert [row["status"] for row in unavailable] == ["not rated", "unavailable", "unavailable"]
    assert "2025" in unavailable[1]["note"]

    no_player = player_comparison_rows(plans, players, player_id=None)
    assert {row["status"] for row in no_player} == {"no player selected"}


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


def test_launcher_top_players_flag_is_exposed_to_the_app_and_restored(monkeypatch):
    seen = {}

    def fake_cli_main():
        seen["value"] = os.environ.get(TOP_PLAYERS_ENV)
        seen["argv"] = list(sys.argv)
        return 0

    monkeypatch.setattr(dashboard_launcher, "_import_streamlit_cli_main", lambda: fake_cli_main)
    monkeypatch.delenv(TOP_PLAYERS_ENV, raising=False)
    assert dashboard_launcher.main(["--top-players", "10"]) == 0
    assert seen["value"] == "10"
    assert not any("top-players" in item for item in seen["argv"])  # not forwarded to Streamlit
    assert TOP_PLAYERS_ENV not in os.environ

    assert dashboard_launcher.main([]) == 0
    assert seen["value"] is None


def test_launcher_rejects_invalid_top_players(capsys):
    assert dashboard_launcher.main(["--top-players", "0"]) == 2
    assert dashboard_launcher.main(["--top-players", "51"]) == 2
    assert dashboard_launcher.main(["--top-players", "many"]) == 2


def test_launcher_main_rejects_invalid_port(capsys):
    assert dashboard_launcher.main(["--port", "0"]) == 2
    assert dashboard_launcher.main(["--port", "70000"]) == 2
    assert "port" in capsys.readouterr().err.lower()


def test_launcher_help_returns_zero(capsys):
    assert dashboard_launcher.main(["--help"]) == 0
    assert "tennis-elo-dashboard" in capsys.readouterr().out


def test_no_loopback_only_claims_in_user_facing_text():
    paths = (APP_PATH, Path(dashboard_launcher.__file__), REPO_ROOT / "docs" / "dashboard.md")
    for path in paths:
        text = " ".join(path.read_text(encoding="utf-8").lower().split())
        assert "loopback only" not in text, path
        assert "hosts nothing remotely" not in text, path
        assert "localhost by default" in text, path


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


def _window_ranking_rows(calculated, min_matches=0):
    """Stub export rows that vary per window: alias name and a 2024-only player."""
    seasons = tuple(getattr(calculated, "seasons", ()))
    rows = make_ranking_rows()
    for row in rows:
        if row["player_id"] == "p1":
            row["name"] = "Alice A." if seasons == (2025,) else "Alice New"
    if 2024 in seasons:
        rows.append(
            {
                "rank": 4,
                "player_id": "p4",
                "name": "Veteran V.",
                "rating": 1440.0,
                "matches": 4,
                "wins": 1,
                "losses": 3,
                "first_match_date": "2024-01-08",
                "last_match_date": "2024-11-10",
            }
        )
    return [row for row in rows if int(row["matches"]) >= min_matches]


def _install_stub_modules(
    monkeypatch,
    *,
    seasons=(2024, 2025, 2026),
    seasons_by_name=None,
    result=None,
    calculate_error=None,
    ranking_rows_hook=None,
    history_rows_fixture=None,
    summary=_DEFAULT_SUMMARY,
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
        if seasons_by_name:
            named = seasons_by_name.get(Path(input_dir).name)
            if named is not None:
                return tuple(named)
        return tuple(seasons)

    def fake_calculate(input_dir, seasons_, *, config=None, include_history=False):
        note("calculate", tuple(seasons_), config, include_history)
        if calculate_error is not None:
            raise calculate_error
        if result is not None:
            return result
        return make_calculation_result(tuple(seasons_), config=config)

    def fake_ranking_rows(calculated, min_matches=0):
        note("ranking_rows", tuple(getattr(calculated, "seasons", ())), min_matches)
        if ranking_rows_hook is not None:
            return ranking_rows_hook(calculated, min_matches)
        return make_ranking_rows()

    def fake_history_rows(calculated):
        note("history_rows")
        if history_rows_fixture is not None:
            return history_rows_fixture
        return make_history_rows()

    def fake_rankings_csv(calculated, min_matches=0):
        note("rankings_csv", min_matches)
        return "rank,player_id\n1,p1\n"

    def fake_history_csv(calculated):
        note("history_csv")
        return "date,match_id\n2026-01-01,m1\n"

    def fake_summary_dict(calculated):
        note("summary_dict")
        if summary is _DEFAULT_SUMMARY:
            return make_summary(calculated)
        return summary

    api_stub.available_seasons = fake_available_seasons
    api_stub.calculate = fake_calculate
    export_stub.ranking_rows = fake_ranking_rows
    export_stub.history_rows = fake_history_rows
    export_stub.rankings_csv = fake_rankings_csv
    export_stub.history_csv = fake_history_csv
    export_stub.summary_dict = fake_summary_dict
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
    assert metadata["Base K-factor"] == "32"
    assert "enabled" in metadata["Tournament weighting"]
    assert metadata["Accounting check"] == "consistent"
    assert _frame(app, ("exclusion", "count"))["exclusion"].tolist()[:1] == ["exhibition"]

    # The rankings CSV comes from the P0 export with the presentation filter forwarded.
    assert app.download_button(key="download_rankings").label == "Download rankings CSV"
    assert ("rankings_csv", 0) in calls
    assert not any(call[0] == "history_csv" for call in calls)

    assert "Player ID" in set(_frame(app, ("stat", "value"))["stat"])
    assert "(p1)" in app.selectbox(key="player_id").format_func("p1")
    assert _frame(app, HISTORY_COLUMNS) is not None
    assert len(app.get("vega_lite_chart")) >= 1
    # The weighting policy is fixed and always shown; the classification counts come
    # from the run summary (the sibling export section).
    assert _frame(app, COEFFICIENT_COLUMNS) is not None
    assert _frame(app, CLASSIFICATION_COLUMNS) is not None


def test_app_weighting_checkbox_defaults_on_and_threads_into_the_config(monkeypatch):
    calls = []
    app = _run_app(monkeypatch, calls=calls)
    checkbox = app.checkbox(key="use_tournament_weights")
    assert checkbox.label == "Use tournament weights"
    assert checkbox.value is True
    help_text = checkbox.help.lower()
    assert "base k" in help_text and "effective k" in help_text
    assert "coefficient" in help_text and "classic elo" in help_text

    app.button(key="calculate").click().run()
    weighted_config = next(call[2] for call in calls if call[0] == "calculate")
    assert weighted_config == RatingConfig(use_tournament_weights=True)
    metadata = {
        row["field"]: row["value"] for row in _frame(app, ("field", "value")).to_dict("records")
    }
    assert "enabled" in metadata["Tournament weighting"]
    summary_notices = _texts(app.caption) + _texts(app.info)
    assert "enabled" in summary_notices.lower()
    assert "coefficient" in summary_notices.lower()

    calls.clear()
    app.checkbox(key="use_tournament_weights").set_value(False).run()
    app.button(key="calculate").click().run()
    unweighted_config = next(call[2] for call in calls if call[0] == "calculate")
    assert unweighted_config == RatingConfig(use_tournament_weights=False)
    metadata = {
        row["field"]: row["value"] for row in _frame(app, ("field", "value")).to_dict("records")
    }
    assert "disabled" in metadata["Tournament weighting"]
    assert "classic elo" in (_texts(app.caption) + _texts(app.info)).lower()
    assert not app.exception


def test_app_weighting_mode_change_stales_the_run_and_recalculation_refreshes(monkeypatch):
    app = _run_app(monkeypatch)
    app.button(key="calculate").click().run()
    assert not app.warning

    app.checkbox(key="use_tournament_weights").set_value(False).run()
    assert not app.exception
    assert "changed" in _texts(app.warning).lower()

    app.button(key="calculate").click().run()
    assert not app.warning
    assert not app.exception


def test_app_weighting_mode_change_stales_comparisons_until_recomputed(monkeypatch):
    calls = []
    app = _run_app(monkeypatch, calls=calls, ranking_rows_hook=_window_ranking_rows)
    app.button(key="calculate").click().run()
    app.button(key="compare_windows").click().run()
    weighted_calls = [call for call in calls if call[0] == "calculate"]
    assert [call[1] for call in weighted_calls] == [
        (2026,),
        (2026,),
        (2025, 2026),
        (2024, 2025, 2026),
    ]
    assert all(call[2] == RatingConfig(use_tournament_weights=True) for call in weighted_calls)
    assert all(call[3] is False for call in weighted_calls[1:])

    calls.clear()
    app.checkbox(key="use_tournament_weights").set_value(False).run()
    # The mode is part of the comparison signature: the old window results are not reused.
    assert "compare windows" in _texts(app.info).lower()
    assert not any(call[0] == "calculate" for call in calls)

    app.button(key="compare_windows").click().run()
    recomputed = [call for call in calls if call[0] == "calculate"]
    assert [call[1] for call in recomputed] == [(2026,), (2025, 2026), (2024, 2025, 2026)]
    assert all(call[2] == RatingConfig(use_tournament_weights=False) for call in recomputed)
    assert all(call[3] is False for call in recomputed)

    # Switching player still reuses the cached per-window rows: nothing is recomputed.
    after_compare = len(recomputed)
    app.selectbox(key="player_id").select("p3").run()
    assert len([call for call in calls if call[0] == "calculate"]) == after_compare
    assert not app.exception


def test_app_shows_the_weighting_policy_and_visible_unknown_fallback_warning(monkeypatch):
    section = make_weighting_section(
        unknown=(
            {"season_year": 2026, "tournament": "Mystery Cup", "matches": 2},
            {"season_year": 2025, "tournament": "Atlantis Open", "matches": 1},
        ),
        matches_by_level={"atp_250": 2, "grand_slam": 1},
    )
    summary = make_summary(make_calculation_result(), weighting_section=section)
    app = _run_app(monkeypatch, summary=summary)
    app.button(key="calculate").click().run()
    assert not app.exception

    warning = _texts(app.warning).lower()
    assert "3" in warning and "fallback" in warning and "unknown" in warning

    coefficients = _frame(app, COEFFICIENT_COLUMNS)
    assert "Grand Slam" in coefficients["level"].tolist()
    classification = _frame(app, CLASSIFICATION_COLUMNS).to_dict("records")
    assert classification == [
        {"level": "ATP 250", "matches": 2},
        {"level": "Grand Slam", "matches": 1},
    ]
    unclassified = _frame(app, UNKNOWN_TOURNAMENT_COLUMNS).to_dict("records")
    assert [row["tournament"] for row in unclassified] == ["Atlantis Open", "Mystery Cup"]
    assert [row["season_year"] for row in unclassified] == [2025, 2026]


def test_app_handles_a_summary_without_weighting_metadata(monkeypatch):
    legacy = {
        "seasons": [2026],
        "configuration": {"use_tournament_weights": True},
        "fresh_start": True,
    }
    for summary in (None, legacy):
        app = _run_app(monkeypatch, summary=summary)
        app.button(key="calculate").click().run()
        assert not app.exception, summary
        assert not app.warning, summary  # nothing to warn about, and no invented unknowns
        assert "did not include" in _texts(app.info).lower(), summary
        # The fixed policy table is always shown; run classification is not invented.
        assert _frame(app, COEFFICIENT_COLUMNS) is not None
        with pytest.raises(AssertionError):
            _frame(app, CLASSIFICATION_COLUMNS)
        metadata = {
            row["field"]: row["value"]
            for row in _frame(app, ("field", "value")).to_dict("records")
        }
        assert "enabled" in metadata["Tournament weighting"]


def test_app_player_history_table_shows_recorded_weighting_columns(monkeypatch):
    app = _run_app(monkeypatch, history_rows_fixture=weighted_history_rows())
    app.button(key="calculate").click().run()
    assert not app.exception
    history = _frame(app, HISTORY_COLUMNS)
    assert list(history.columns)[4:7] == [
        "tournament_level",
        "tournament_weight",
        "effective_k_factor",
    ]
    assert list(history["match_id"]) == ["g1", "a1"]
    assert list(history["tournament_level"]) == ["grand_slam", "atp_250"]
    assert list(history["tournament_weight"]) == [2.0, 1.0]
    assert list(history["effective_k_factor"]) == [64.0, 32.0]



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

    selector = app.selectbox(key="player_id")
    assert selector.options == [
        "Alpha A. (p1)",
        "Alpha A. (p2)",
        "img src=x onerror=alert(1) (p3)",
    ]
    assert len(set(selector.options)) == 3  # duplicate names stay distinguishable by ID
    assert selector.value == "p1"  # the widget state is the raw stable ID
    assert selector.format_func("p3") == "img src=x onerror=alert(1) (p3)"

    selector.select("p3").run()
    assert app.selectbox(key="player_id").value == "p3"
    rendered = _texts(app.subheader) + _texts(app.markdown) + _texts(app.caption)
    assert "alert" in rendered
    assert "<img" not in rendered

    app.text_input(key="player_search").set_value("p2").run()
    assert app.selectbox(key="player_id").value == "p2"

    app.text_input(key="player_search").set_value("no-such-player").run()
    assert not app.exception
    assert "no player" in _texts(app.info).lower()


def test_app_player_history_and_chart_follow_selected_player(monkeypatch):
    app = _run_app(monkeypatch)
    app.button(key="calculate").click().run()
    assert list(_frame(app, HISTORY_COLUMNS)["match_id"]) == ["m1", "m2", "m3"]

    app.selectbox(key="player_id").select("p2").run()
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
    comparison = _frame(app, COMPARISON_COLUMNS)  # secondary dataset summary
    statuses = list(comparison["status"])
    assert statuses == ["available", "available", "unavailable"]
    assert "2024" in comparison["note"].iloc[2]
    assert list(comparison["seasons"])[:2] == ["2026", "2025\u20132026"]

    per_player = _frame(app, PLAYER_COMPARISON_COLUMNS)  # primary player table
    assert list(per_player["status"]) == ["rated", "rated", "unavailable"]
    assert list(per_player["rating"])[:2] == ["1532.5", "1532.5"]
    assert list(per_player["rank"])[:2] == ["1", "1"]

    computed_windows = [call[1] for call in calls if call[0] == "calculate"]
    assert computed_windows == [(2026,), (2025, 2026)]
    assert all(call[3] is False for call in calls if call[0] == "calculate")
    assert "initial rating" in _texts(app.info).lower()


def test_app_player_selector_keeps_raw_id_when_latest_name_changes(monkeypatch):
    app = _run_app(monkeypatch, ranking_rows_hook=_window_ranking_rows)
    app.button(key="calculate").click().run()
    assert app.selectbox(key="player_id").value == "p1"
    assert app.selectbox(key="player_id").format_func("p1") == "Alice New (p1)"

    # Same player ID, newer/older latest name depending on the window.
    app.selectbox(key="end_season").select(2025).run()
    app.button(key="calculate").click().run()
    assert not app.exception
    assert app.session_state["player_id"] == "p1"  # raw stable ID, never a label
    assert app.selectbox(key="player_id").value == "p1"
    assert app.selectbox(key="player_id").format_func("p1") == "Alice A. (p1)"
    assert "Alice A" in _texts(app.subheader)


def test_app_comparison_uses_selected_player_without_recomputing(monkeypatch):
    calls = []
    app = _run_app(monkeypatch, calls=calls, ranking_rows_hook=_window_ranking_rows)
    app.button(key="calculate").click().run()
    assert app.selectbox(key="player_id").value == "p1"

    app.button(key="compare_windows").click().run()
    assert not app.exception
    after_compare = len([call for call in calls if call[0] == "calculate"])
    assert after_compare == 4  # the main run plus three independent windows
    ranking_calls = len([call for call in calls if call[0] == "ranking_rows"])

    primary = _frame(app, PLAYER_COMPARISON_COLUMNS)
    assert list(primary["status"]) == ["rated", "rated", "rated"]
    assert list(primary["player"]) == ["Alice New (p1)"] * 3
    assert list(primary["rating"]) == ["1532.5"] * 3
    assert list(primary["rank"]) == ["1"] * 3
    assert list(primary["matches"]) == ["3"] * 3
    assert list(primary["seasons"]) == ["2026", "2025\u20132026", "2024\u20132026"]

    # Changing the selected player re-renders from the cached per-window results.
    app.selectbox(key="player_id").select("p3").run()
    assert not app.exception
    # Cached per-window player rows: no window and no ranking table is recomputed.
    assert len([call for call in calls if call[0] == "calculate"]) == after_compare
    assert len([call for call in calls if call[0] == "ranking_rows"]) == ranking_calls
    primary = _frame(app, PLAYER_COMPARISON_COLUMNS)
    assert all("(p3)" in label for label in primary["player"])
    assert list(primary["rating"]) == ["1466.0"] * 3
    assert list(primary["rank"]) == ["3"] * 3


def test_app_comparison_before_main_run_uses_union_picker_and_marks_not_rated(monkeypatch):
    calls = []
    app = _run_app(monkeypatch, calls=calls, ranking_rows_hook=_window_ranking_rows)
    assert "player_id" not in app.session_state

    app.button(key="compare_windows").click().run()
    assert not app.exception
    after_compare = len([call for call in calls if call[0] == "calculate"])

    picker = app.selectbox(key="comparison_player")
    assert picker.options == [  # union of the compared windows, disambiguated by ID
        "Alice New (p1)",
        "Alpha A. (p2)",
        "img src=x onerror=alert(1) (p3)",
        "Veteran V. (p4)",
    ]
    assert picker.value == "p1"  # raw stable ID
    assert picker.format_func("p4") == "Veteran V. (p4)"

    primary = _frame(app, PLAYER_COMPARISON_COLUMNS)
    assert list(primary["status"]) == ["rated", "rated", "rated"]

    picker.select("p4").run()
    assert not app.exception
    assert len([call for call in calls if call[0] == "calculate"]) == after_compare
    primary = _frame(app, PLAYER_COMPARISON_COLUMNS)
    assert list(primary["status"]) == ["not rated", "not rated", "rated"]
    assert list(primary["player"]) == ["Veteran V. (p4)"] * 3
    assert list(primary["rating"]) == ["", "", "1440.0"]  # never a fabricated 1500
    assert "1500" not in str(primary["rating"].tolist())
    assert "no eligible match" in primary["note"].iloc[0]


def test_app_chart_uses_temporal_match_timestamps(monkeypatch):
    app = _run_app(monkeypatch)
    app.button(key="calculate").click().run()
    charts = app.get("vega_lite_chart")
    assert len(charts) == 2  # top-20 timeseries + selected player chart
    for chart in charts:
        spec = chart.proto.spec
        assert '"field": "match_date"' in spec
        assert '"type": "temporal"' in spec
    player_spec = charts[-1].proto.spec
    assert '"type": "nominal"' not in player_spec


def test_app_renders_top_players_rating_timeseries(monkeypatch):
    app = _run_app(monkeypatch)
    app.button(key="calculate").click().run()
    assert not app.exception
    top_spec = app.get("vega_lite_chart")[0].proto.spec
    assert '"field": "player"' in top_spec  # one coloured series per player
    assert "Top 20" in " ".join(element.value for element in app.markdown)
    assert app.number_input(key="top_players").value == 20


def test_app_top_players_control_limits_the_chart(monkeypatch):
    monkeypatch.setenv(TOP_PLAYERS_ENV, "2")
    app = _run_app(monkeypatch)
    assert app.number_input(key="top_players").value == 2  # startup default from the launcher
    app.button(key="calculate").click().run()
    assert "Top 2 players" in " ".join(element.value for element in app.markdown)

    app.number_input(key="top_players").set_value(1).run()
    assert not app.exception
    assert "Top 1 players" in " ".join(element.value for element in app.markdown)
    assert not app.warning  # presentation only: the run is not stale


def test_app_data_directory_change_reapplies_preset(monkeypatch, tmp_path):
    season_dirs = {
        "A": (2024, 2025, 2026),
        "D": (2025, 2026),
        "B": (2020, 2021),
    }
    for name in season_dirs:
        (tmp_path / name).mkdir()
    app = _run_app(monkeypatch, seasons_by_name=season_dirs)

    app.text_input(key="input_dir").set_value(str(tmp_path / "A")).run()
    app.radio(key="preset_size").set_value("3 seasons").run()
    assert list(app.multiselect(key="seasons").value) == [2024, 2025, 2026]
    assert app.button(key="calculate").disabled is False

    # A directory with only two seasons must not keep a two-season subset enabled.
    app.text_input(key="input_dir").set_value(str(tmp_path / "D")).run()
    assert list(app.multiselect(key="seasons").value) == []
    assert app.button(key="calculate").disabled is True
    assert "unavailable" in (_texts(app.info) + _texts(app.warning)).lower()

    app.radio(key="preset_size").set_value("2 seasons").run()
    assert list(app.multiselect(key="seasons").value) == [2025, 2026]
    assert app.button(key="calculate").disabled is False

    # A directory whose seasons do not overlap the previous preset at all.
    app.radio(key="preset_size").set_value("3 seasons").run()
    app.text_input(key="input_dir").set_value(str(tmp_path / "B")).run()
    assert list(app.multiselect(key="seasons").value) == []
    assert int(app.selectbox(key="end_season").value) == 2021
    app.radio(key="preset_size").set_value("2 seasons").run()
    assert list(app.multiselect(key="seasons").value) == [2020, 2021]
    assert app.button(key="calculate").disabled is False


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


# --------------------------------------------------------------------------- #
# Hosted deployment (fixed data directory, Community Cloud entrypoint)
# --------------------------------------------------------------------------- #


def test_app_fixed_data_dir_hides_the_free_text_directory_input(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setenv(DATA_DIR_ENV, str(tmp_path))
    app = _run_app(monkeypatch, calls=calls)
    assert not app.exception
    assert not [widget for widget in app.text_input if widget.key == "input_dir"]
    assert ("available_seasons", str(tmp_path.resolve())) in calls
    sidebar_text = " ".join(element.value for element in app.sidebar.caption)
    assert "fixed by this deployment" in sidebar_text
    assert str(tmp_path) not in sidebar_text  # server paths are not shown to visitors

    app.button(key="calculate").click().run()
    assert not app.exception
    assert _frame(app, LEADERBOARD_COLUMNS) is not None


def test_app_blank_data_dir_env_keeps_the_local_directory_input(monkeypatch):
    monkeypatch.setenv(DATA_DIR_ENV, "  ")
    app = _run_app(monkeypatch)
    assert app.text_input(key="input_dir") is not None


def test_deploy_requirements_pin_the_locked_dashboard_dependencies():
    lock = (REPO_ROOT / "uv.lock").read_text(encoding="utf-8")
    pins = {}
    for line in (REPO_ROOT / "deploy" / "requirements.txt").read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            name, version = line.split("==")
            pins[name] = version
    assert set(pins) == {"streamlit", "pandas"}
    for name, version in pins.items():
        assert f'name = "{name}"\nversion = "{version}"' in lock


def test_deploy_entrypoint_serves_the_repo_data_without_a_directory_input(monkeypatch):
    pytest.importorskip("tennis_elo.api")
    # Empty means unset; monkeypatch restores the original environment afterwards.
    monkeypatch.setenv(DATA_DIR_ENV, "")
    app = AppTest.from_file(str(DEPLOY_APP_PATH), default_timeout=300)
    app.run()
    assert not app.exception
    assert not [widget for widget in app.text_input if widget.key == "input_dir"]
    assert {2024, 2025, 2026} <= {int(option) for option in app.selectbox(key="end_season").options}

    app.button(key="calculate").click().run()
    assert not app.exception, _texts(app.error)
    assert len(_frame(app, LEADERBOARD_COLUMNS)) > 0
