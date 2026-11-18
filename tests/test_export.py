"""Unit tests for ranking/history/summary serialization and output writing.

These tests build ``CalculationResult`` fixtures from the shared immutable
contracts, so they run without the data/engine lanes being integrated.
"""

import csv
import io
import json

import pytest

from tennis_elo.models import (
    CalculationResult,
    HistoryEntry,
    LoadResult,
    Match,
    PlayerRating,
    RatingConfig,
    RatingResult,
)

INSIDE_DAY = 1704067200  # 2024-01-01T00:00:00+00:00
NEXT_DAY = 1704153600  # 2024-01-02T00:00:00+00:00

RANKING_HEADER = "rank,player_id,name,rating,matches,wins,losses,first_match_date,last_match_date"
HISTORY_HEADER = (
    "match_id,season_year,date,timestamp,player_id,player_name,opponent_id,"
    "opponent_name,won,rating_before,opponent_rating_before,expected_score,"
    "rating_after,tournament,surface,tournament_level,tournament_weight,"
    "effective_k_factor"
)


def _players():
    return (
        PlayerRating("p3", "Carol", 1484.0, 2, 1, 1, INSIDE_DAY, NEXT_DAY),
        PlayerRating("p1", "Alice", 1516.0, 3, 2, 1, INSIDE_DAY, NEXT_DAY),
        PlayerRating("p2", "Bob", 1500.0, 1, 0, 1, INSIDE_DAY, INSIDE_DAY),
    )


def _load():
    matches = (
        Match("m1", 2024, INSIDE_DAY, "p1", "p2", "Alice", "Bob", 1),
        Match("m2", 2024, NEXT_DAY, "p1", "p3", "Alice", "Carol", 2),
    )
    return LoadResult(
        matches,
        ("2024-atp-season.csv",),
        (2024, 2025),
        10,
        6,
        {"walkover": 3, "canceled": 1},
        0,
    )


def _history():
    return (
        HistoryEntry(
            "m1", 2024, INSIDE_DAY, "p1", "Alice", "p2", "Bob", True, 1500.0, 1500.0, 0.5, 1516.0
        ),
        HistoryEntry(
            "m1", 2024, INSIDE_DAY, "p2", "Bob", "p1", "Alice", False, 1500.0, 1500.0, 0.5, 1484.0
        ),
        HistoryEntry(
            "m2",
            2024,
            NEXT_DAY,
            "p1",
            "Alice",
            "p3",
            "Carol",
            False,
            1516.0,
            1500.0,
            0.5203,
            1504.3,
            tournament="United Cup ATP",
            surface="hard",
        ),
    )


def build_result(
    *, players=None, history=(), config=None, load=None, seasons=(2024,), matches_processed=2
):
    return CalculationResult(
        seasons,
        config or RatingConfig(),
        load or _load(),
        RatingResult(_players() if players is None else players, tuple(history), matches_processed),
    )


def _weighted_load():
    """Eligible matches spanning known levels, a blank name and unknowns."""

    matches = (
        Match(
            "m1", 2024, INSIDE_DAY, "p1", "p2", "Alice", "Bob", 1,
            tournament="Rome Masters", tournament_level="masters_1000",
        ),
        Match(
            "m2", 2024, NEXT_DAY, "p1", "p3", "Alice", "Carol", 2,
            tournament="Cordoba Challenger", tournament_level="challenger",
        ),
        Match(
            "m3", 2024, NEXT_DAY, "p2", "p3", "Bob", "Carol", 1,
            tournament="United Cup", tournament_level="other",
        ),
        Match(
            "m4", 2024, NEXT_DAY, "p1", "p2", "Alice", "Bob", 1,
            tournament="Mystery Cup", tournament_level="unknown",
        ),
        Match(
            "m5", 2025, INSIDE_DAY, "p1", "p2", "Alice", "Bob", 1,
            tournament="Blank Open", tournament_level="unknown",
        ),
        Match(
            "m6", 2025, NEXT_DAY, "p2", "p3", "Bob", "Carol", 1,
            tournament="", tournament_level="unknown",
        ),
        Match(
            "m7", 2025, NEXT_DAY, "p1", "p3", "Alice", "Carol", 2,
            tournament="Blank Open", tournament_level="unknown",
        ),
    )
    return LoadResult(
        matches,
        ("2024-atp-season.csv", "2025-atp-season.csv"),
        (2024, 2025),
        7,
        7,
        {},
        0,
    )


def _applied_history():
    """History already tagged with the values replay actually applied."""

    return (
        HistoryEntry(
            "m1", 2024, INSIDE_DAY, "p1", "Alice", "p2", "Bob", True,
            1500.0, 1500.0, 0.5, 1524.0,
            tournament="Rome Masters", surface="clay",
            tournament_level="masters_1000", tournament_weight=1.5, effective_k_factor=48.0,
        ),
        HistoryEntry(
            "m2", 2024, NEXT_DAY, "p2", "Bob", "p3", "Carol", False,
            1484.0, 1500.0, 0.4769, 1478.0,
            tournament="Cordoba Challenger", surface="clay",
            tournament_level="challenger", tournament_weight=0.75, effective_k_factor=24.0,
        ),
    )


def test_ranking_rows_sorted_by_rating_then_player_id():
    from tennis_elo.export import ranking_rows

    rows = ranking_rows(build_result())
    assert [row["player_id"] for row in rows] == ["p1", "p2", "p3"]
    assert [row["rank"] for row in rows] == [1, 2, 3]


def test_ranking_rows_breaks_rating_ties_by_player_id():
    from tennis_elo.export import ranking_rows

    players = (
        PlayerRating("pz", "Zed", 1500.0, 1, 1, 0, INSIDE_DAY, INSIDE_DAY),
        PlayerRating("pa", "Ann", 1500.0, 1, 1, 0, INSIDE_DAY, INSIDE_DAY),
    )
    rows = ranking_rows(build_result(players=players))
    assert [row["player_id"] for row in rows] == ["pa", "pz"]


def test_ranking_rows_expose_utc_dates_and_counters():
    from tennis_elo.export import ranking_rows

    assert ranking_rows(build_result())[0] == {
        "rank": 1,
        "player_id": "p1",
        "name": "Alice",
        "rating": 1516.0,
        "matches": 3,
        "wins": 2,
        "losses": 1,
        "first_match_date": "2024-01-01",
        "last_match_date": "2024-01-02",
    }


def test_ranking_rows_round_rating_for_display_only():
    from tennis_elo.export import ranking_rows

    players = (PlayerRating("p1", "Alice", 1516.6666, 1, 1, 0, INSIDE_DAY, INSIDE_DAY),)
    assert ranking_rows(build_result(players=players))[0]["rating"] == 1516.67


def test_ranking_rows_min_matches_filters_without_renumbering():
    from tennis_elo.export import ranking_rows

    players = (
        PlayerRating("p2", "Bob", 1516.0, 1, 1, 0, INSIDE_DAY, INSIDE_DAY),
        PlayerRating("p1", "Alice", 1500.0, 3, 2, 1, INSIDE_DAY, NEXT_DAY),
    )
    rows = ranking_rows(build_result(players=players), min_matches=2)
    assert [row["player_id"] for row in rows] == ["p1"]
    assert rows[0]["rank"] == 2


def test_ranking_rows_reject_negative_min_matches():
    from tennis_elo.export import ranking_rows

    with pytest.raises(ValueError, match="min_matches"):
        ranking_rows(build_result(), min_matches=-1)


def test_history_rows_include_every_field_and_utc_date():
    from tennis_elo.export import history_rows

    rows = history_rows(build_result(history=_history()))
    assert len(rows) == 3
    assert list(rows[0]) == HISTORY_HEADER.split(",")
    assert rows[0]["date"] == "2024-01-01"
    assert rows[0]["timestamp"] == INSIDE_DAY
    assert rows[0]["won"] is True
    assert rows[0]["expected_score"] == 0.5
    assert rows[2]["date"] == "2024-01-02"
    assert rows[2]["tournament"] == "United Cup ATP"
    assert rows[2]["surface"] == "hard"


def test_history_rows_empty_without_history():
    from tennis_elo.export import history_rows

    assert history_rows(build_result()) == []


def test_rankings_csv_has_header_and_sorted_rows():
    from tennis_elo.export import rankings_csv

    text = rankings_csv(build_result())
    assert text.startswith(RANKING_HEADER + "\n")
    assert text.endswith("\n")
    assert "\r" not in text
    rows = list(csv.DictReader(io.StringIO(text)))
    assert [row["player_id"] for row in rows] == ["p1", "p2", "p3"]
    assert rows[0]["rating"] == "1516.0"


def test_rankings_csv_is_header_only_for_zero_players():
    from tennis_elo.export import rankings_csv

    assert rankings_csv(build_result(players=())) == RANKING_HEADER + "\n"


def test_rankings_csv_respects_min_matches():
    from tennis_elo.export import rankings_csv

    rows = list(csv.DictReader(io.StringIO(rankings_csv(build_result(), min_matches=2))))
    assert [row["player_id"] for row in rows] == ["p1", "p3"]
    assert [row["rank"] for row in rows] == ["1", "3"]


def test_history_csv_has_header_and_rows():
    from tennis_elo.export import history_csv

    text = history_csv(build_result(history=_history()))
    assert text.startswith(HISTORY_HEADER + "\n")
    rows = list(csv.DictReader(io.StringIO(text)))
    assert len(rows) == 3
    assert rows[0]["date"] == "2024-01-01"
    assert rows[0]["won"] == "True"


def test_history_csv_is_header_only_without_history():
    from tennis_elo.export import history_csv

    assert history_csv(build_result()) == HISTORY_HEADER + "\n"


def test_summary_dict_reports_accounting_and_fresh_start():
    from tennis_elo.export import summary_dict

    summary = summary_dict(build_result(history=_history()))
    assert summary["seasons"] == [2024]
    assert summary["available_seasons"] == [2024, 2025]
    assert summary["input_files"] == ["2024-atp-season.csv"]
    assert summary["rows_read"] == 10
    assert summary["selected_rows"] == 6
    assert summary["matches_processed"] == 2
    assert summary["players_rated"] == 3
    assert summary["duplicate_rows"] == 0
    assert summary["excluded_counts"] == {"walkover": 3, "canceled": 1}
    assert summary["history_included"] is True
    assert summary["configuration"] == {
        "initial_rating": 1500.0,
        "k_factor": 32.0,
        "include_retirements": True,
        "use_tournament_weights": True,
    }
    assert summary["fresh_start"] is True
    assert "initial_rating" in summary["fresh_start_note"]
    assert "not" in summary["fresh_start_note"]


def test_summary_dict_history_included_false_without_history():
    from tennis_elo.export import summary_dict

    summary = summary_dict(build_result())
    assert summary["history_included"] is False
    assert json.dumps(summary)  # JSON-serializable


def test_write_outputs_writes_rankings_history_and_summary(tmp_path):
    from tennis_elo.export import write_outputs

    written = write_outputs(build_result(history=_history()), tmp_path, include_history=True)
    assert set(written) == {"rankings", "history", "summary"}
    assert written["rankings"] == tmp_path / "rankings.csv"
    assert written["history"] == tmp_path / "history.csv"
    assert written["summary"] == tmp_path / "summary.json"
    assert written["rankings"].read_text(encoding="utf-8").startswith(RANKING_HEADER)
    summary = json.loads(written["summary"].read_text(encoding="utf-8"))
    assert summary["history_included"] is True
    assert summary["players_rated"] == 3


def test_write_outputs_skips_history_by_default(tmp_path):
    from tennis_elo.export import write_outputs

    written = write_outputs(build_result(), tmp_path)
    assert set(written) == {"rankings", "summary"}
    assert not (tmp_path / "history.csv").exists()
    assert (
        json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))["history_included"]
        is False
    )


def test_write_outputs_creates_missing_nested_directory(tmp_path):
    from tennis_elo.export import write_outputs

    target = tmp_path / "outputs" / "2024"
    written = write_outputs(build_result(), target)
    assert written["rankings"].parent == target
    assert target.is_dir()


def test_write_outputs_accepts_existing_empty_directory(tmp_path):
    from tennis_elo.export import write_outputs

    write_outputs(build_result(), tmp_path)
    assert (tmp_path / "rankings.csv").is_file()


def test_write_outputs_rejects_non_empty_directory_without_touching_it(tmp_path):
    from tennis_elo.export import write_outputs

    (tmp_path / "keep.txt").write_text("keep", encoding="utf-8")
    with pytest.raises(FileExistsError, match="not empty"):
        write_outputs(build_result(), tmp_path)
    assert sorted(path.name for path in tmp_path.iterdir()) == ["keep.txt"]


def test_write_outputs_refuses_to_overwrite_an_earlier_run(tmp_path):
    from tennis_elo.export import write_outputs

    write_outputs(build_result(), tmp_path)
    with pytest.raises(FileExistsError, match="not empty"):
        write_outputs(build_result(), tmp_path)


def test_write_outputs_rejects_file_in_place_of_directory(tmp_path):
    from tennis_elo.export import write_outputs

    target = tmp_path / "outputs"
    target.write_text("not a directory", encoding="utf-8")
    with pytest.raises(FileExistsError):
        write_outputs(build_result(), target)


def test_write_outputs_passes_min_matches_to_rankings(tmp_path):
    from tennis_elo.export import write_outputs

    written = write_outputs(build_result(), tmp_path, min_matches=2)
    rows = list(csv.DictReader(io.StringIO(written["rankings"].read_text(encoding="utf-8"))))
    assert [row["player_id"] for row in rows] == ["p1", "p3"]


def test_write_outputs_rejects_history_request_without_processed_history(tmp_path):
    from tennis_elo.export import write_outputs

    result = build_result(history=(), matches_processed=2)
    target = tmp_path / "out"

    with pytest.raises(ValueError, match="include_history"):
        write_outputs(result, target, include_history=True)

    # Rejected before the output directory is created or touched.
    assert not target.exists()


def test_write_outputs_history_mismatch_fails_before_directory_checks(tmp_path):
    from tennis_elo.export import write_outputs

    (tmp_path / "keep.txt").write_text("keep", encoding="utf-8")

    with pytest.raises(ValueError, match="include_history"):
        write_outputs(build_result(history=()), tmp_path, include_history=True)

    assert sorted(path.name for path in tmp_path.iterdir()) == ["keep.txt"]


def test_write_outputs_allows_history_request_with_zero_eligible_matches(tmp_path):
    from tennis_elo.export import write_outputs

    result = build_result(players=(), history=(), matches_processed=0)

    written = write_outputs(result, tmp_path, include_history=True)

    assert set(written) == {"rankings", "history", "summary"}
    assert written["history"].read_text(encoding="utf-8") == HISTORY_HEADER + "\n"
    summary = json.loads(written["summary"].read_text(encoding="utf-8"))
    assert summary["history_included"] is True


def test_write_outputs_rejects_negative_min_matches_before_creating_dir(tmp_path):
    from tennis_elo.export import write_outputs

    target = tmp_path / "out"

    with pytest.raises(ValueError, match="min_matches"):
        write_outputs(build_result(), target, min_matches=-1)

    assert not target.exists()


def test_write_outputs_negative_min_matches_leaves_existing_empty_dir_unchanged(tmp_path):
    from tennis_elo.export import write_outputs

    with pytest.raises(ValueError, match="min_matches"):
        write_outputs(build_result(), tmp_path, min_matches=-1)

    assert list(tmp_path.iterdir()) == []


def test_write_outputs_records_reporting_selection(tmp_path):
    from tennis_elo.export import summary_dict, write_outputs

    written = write_outputs(build_result(), tmp_path, min_matches=2)
    summary = json.loads(written["summary"].read_text(encoding="utf-8"))

    assert summary["reporting"] == {"min_matches": 2, "ranking_rows": 2}
    # summary_dict has no filter parameter, so it stays unchanged.
    assert "reporting" not in summary_dict(build_result())


def test_write_outputs_reporting_counts_and_ratings_are_filter_independent(tmp_path):
    from tennis_elo.export import write_outputs

    unfiltered_dir = tmp_path / "all"
    filtered_dir = tmp_path / "filtered"
    write_outputs(build_result(), unfiltered_dir)
    write_outputs(build_result(), filtered_dir, min_matches=2)

    all_summary = json.loads((unfiltered_dir / "summary.json").read_text(encoding="utf-8"))
    filtered_summary = json.loads((filtered_dir / "summary.json").read_text(encoding="utf-8"))
    assert all_summary["reporting"] == {"min_matches": 0, "ranking_rows": 3}
    assert filtered_summary["reporting"] == {"min_matches": 2, "ranking_rows": 2}

    def ratings(directory):
        text = (directory / "rankings.csv").read_text(encoding="utf-8")
        return {row["player_id"]: row["rating"] for row in csv.DictReader(io.StringIO(text))}

    all_ratings = ratings(unfiltered_dir)
    filtered_ratings = ratings(filtered_dir)
    assert set(filtered_ratings) == {"p1", "p3"}
    # Presentation filtering never changes Elo values.
    assert filtered_ratings == {player_id: all_ratings[player_id] for player_id in filtered_ratings}


# --- Tournament weighting in history exports and summaries ------------------


def test_history_columns_append_weighting_fields_after_existing_columns():
    from tennis_elo.export import HISTORY_FIELDS

    assert HISTORY_FIELDS[:15] == (
        "match_id",
        "season_year",
        "date",
        "timestamp",
        "player_id",
        "player_name",
        "opponent_id",
        "opponent_name",
        "won",
        "rating_before",
        "opponent_rating_before",
        "expected_score",
        "rating_after",
        "tournament",
        "surface",
    )
    assert HISTORY_FIELDS[15:] == (
        "tournament_level",
        "tournament_weight",
        "effective_k_factor",
    )


def test_ranking_columns_are_unchanged_by_weighting():
    from tennis_elo.export import RANKING_FIELDS

    assert RANKING_FIELDS == (
        "rank",
        "player_id",
        "name",
        "rating",
        "matches",
        "wins",
        "losses",
        "first_match_date",
        "last_match_date",
    )


def test_history_rows_carry_applied_tournament_weighting_values():
    from tennis_elo.export import history_rows

    rows = history_rows(build_result(history=_applied_history()))

    assert rows[0]["tournament_level"] == "masters_1000"
    assert rows[0]["tournament_weight"] == 1.5
    assert rows[0]["effective_k_factor"] == 48.0
    assert rows[1]["tournament_level"] == "challenger"
    assert rows[1]["tournament_weight"] == 0.75
    assert rows[1]["effective_k_factor"] == 24.0


def test_history_export_uses_recorded_values_not_the_current_config():
    from tennis_elo.export import history_rows

    # The current config is unweighted, but these entries were replayed with
    # weights: exports report what happened, never re-derive it from config.
    rows = history_rows(
        build_result(
            history=_applied_history(), config=RatingConfig(use_tournament_weights=False)
        )
    )

    assert rows[0]["tournament_weight"] == 1.5
    assert rows[0]["effective_k_factor"] == 48.0

    # And the mirror case: unweighted history keeps its classified level while
    # recording weight 1.0 and the actual base K.
    unweighted_entries = (
        HistoryEntry(
            "m1", 2024, INSIDE_DAY, "p1", "Alice", "p2", "Bob", True,
            1500.0, 1500.0, 0.5, 1516.0,
            tournament="Rome Masters", surface="clay",
            tournament_level="masters_1000", tournament_weight=1.0, effective_k_factor=32.0,
        ),
    )
    rows = history_rows(
        build_result(history=unweighted_entries, config=RatingConfig())
    )
    assert rows[0]["tournament_level"] == "masters_1000"
    assert rows[0]["tournament_weight"] == 1.0
    assert rows[0]["effective_k_factor"] == 32.0


def test_history_csv_writes_the_weighting_columns():
    from tennis_elo.export import history_csv

    text = history_csv(build_result(history=_applied_history()))
    rows = list(csv.DictReader(io.StringIO(text)))

    assert text.startswith(HISTORY_HEADER + "\n")
    assert rows[0]["tournament_level"] == "masters_1000"
    assert rows[0]["tournament_weight"] == "1.5"
    assert rows[0]["effective_k_factor"] == "48.0"


def test_summary_configuration_reports_the_weighting_flag():
    from tennis_elo.export import summary_dict

    assert summary_dict(build_result())["configuration"]["use_tournament_weights"] is True
    unweighted = summary_dict(
        build_result(config=RatingConfig(use_tournament_weights=False))
    )
    assert unweighted["configuration"]["use_tournament_weights"] is False


def test_summary_tournament_weighting_section_has_exact_keys_in_order():
    from tennis_elo.export import summary_dict

    section = summary_dict(build_result(load=_weighted_load()))["tournament_weighting"]

    assert list(section) == [
        "enabled",
        "coefficients",
        "matches_by_level",
        "unknown_matches",
        "unknown_tournaments",
    ]


def test_summary_tournament_weighting_reports_the_fixed_plain_coefficient_table():
    from tennis_elo.export import summary_dict
    from tennis_elo.weighting import TOURNAMENT_COEFFICIENTS

    coefficients = summary_dict(build_result(load=_weighted_load()))["tournament_weighting"][
        "coefficients"
    ]

    assert type(coefficients) is dict
    assert coefficients == {
        "challenger": 0.75,
        "atp_250": 1.0,
        "atp_500": 1.25,
        "masters_1000": 1.5,
        "atp_finals": 1.75,
        "grand_slam": 2.0,
        "other": 1.0,
        "unknown": 1.0,
    }
    assert list(coefficients) == list(TOURNAMENT_COEFFICIENTS)


def test_summary_tournament_weighting_counts_every_eligible_match_by_level():
    from tennis_elo.export import summary_dict

    result = build_result(load=_weighted_load())
    section = summary_dict(result)["tournament_weighting"]

    assert section["matches_by_level"] == {
        "challenger": 1,
        "atp_250": 0,
        "atp_500": 0,
        "masters_1000": 1,
        "atp_finals": 0,
        "grand_slam": 0,
        "other": 1,
        "unknown": 4,
    }
    assert sum(section["matches_by_level"].values()) == len(result.load.matches)


def test_summary_tournament_weighting_sorts_unknown_tournaments():
    from tennis_elo.export import summary_dict

    section = summary_dict(build_result(load=_weighted_load()))["tournament_weighting"]

    assert section["unknown_matches"] == 4
    assert section["unknown_tournaments"] == [
        {"season_year": 2024, "tournament": "Mystery Cup", "matches": 1},
        {"season_year": 2025, "tournament": "", "matches": 1},
        {"season_year": 2025, "tournament": "Blank Open", "matches": 2},
    ]
    assert [list(item) for item in section["unknown_tournaments"]] == [
        ["season_year", "tournament", "matches"]
    ] * 3


def test_summary_tournament_weighting_reports_no_unknowns_for_known_levels():
    from tennis_elo.export import summary_dict

    result = build_result(load=_weighted_load())
    known_only = LoadResult(
        tuple(match for match in result.load.matches if match.tournament_level != "unknown"),
        result.load.input_files,
        result.load.available_seasons,
        result.load.rows_read,
        result.load.selected_rows,
        result.load.excluded_counts,
        result.load.duplicate_rows,
    )
    section = summary_dict(build_result(load=known_only))["tournament_weighting"]

    assert section["unknown_matches"] == 0
    assert section["unknown_tournaments"] == []


def test_summary_tournament_weighting_reports_counted_unknowns_by_default():
    from tennis_elo.export import summary_dict

    section = summary_dict(build_result())["tournament_weighting"]

    assert section["unknown_matches"] == 2
    assert section["unknown_tournaments"] == [
        {"season_year": 2024, "tournament": "", "matches": 2},
    ]


def test_summary_tournament_weighting_enabled_flag_follows_the_config():
    from tennis_elo.export import summary_dict

    section = summary_dict(
        build_result(load=_weighted_load(), config=RatingConfig(use_tournament_weights=False))
    )["tournament_weighting"]

    assert section["enabled"] is False
    # Classification accounting is independent of whether weights are applied.
    assert section["unknown_matches"] == 4
    assert section["matches_by_level"]["masters_1000"] == 1


def test_summary_counts_non_canonical_levels_deterministically():
    from tennis_elo.export import summary_dict
    from tennis_elo.weighting import TOURNAMENT_COEFFICIENTS

    matches = (
        Match("m1", 2024, INSIDE_DAY, "p1", "p2", "A", "B", 1, tournament_level="zeta"),
        Match("m2", 2024, NEXT_DAY, "p1", "p2", "A", "B", 2, tournament_level="alpha"),
    )
    load = LoadResult(matches, ("2024-atp-season.csv",), (2024,), 2, 2, {}, 0)

    counts = summary_dict(build_result(load=load))["tournament_weighting"]["matches_by_level"]

    assert list(counts)[: len(TOURNAMENT_COEFFICIENTS)] == list(TOURNAMENT_COEFFICIENTS)
    assert list(counts)[len(TOURNAMENT_COEFFICIENTS) :] == ["alpha", "zeta"]
    assert sum(counts.values()) == 2


def test_summary_dict_is_deterministic_and_json_serializable():
    from tennis_elo.export import summary_dict

    first = json.dumps(summary_dict(build_result(load=_weighted_load())), sort_keys=True)
    second = json.dumps(summary_dict(build_result(load=_weighted_load())), sort_keys=True)

    assert first == second


def test_summary_dict_does_not_mutate_the_result():
    from tennis_elo.export import summary_dict

    result = build_result(load=_weighted_load(), history=_applied_history())
    matches = result.load.matches
    history = result.ratings.history

    summary_dict(result)

    assert result.load.matches is matches
    assert result.ratings.history is history
    assert result.config.use_tournament_weights is True


def test_write_outputs_summary_carries_the_weighting_report(tmp_path):
    from tennis_elo.export import write_outputs

    written = write_outputs(build_result(load=_weighted_load(), history=_applied_history()), tmp_path, include_history=True)
    summary = json.loads(written["summary"].read_text(encoding="utf-8"))

    assert summary["configuration"]["use_tournament_weights"] is True
    assert summary["tournament_weighting"]["unknown_matches"] == 4
    assert summary["tournament_weighting"]["unknown_tournaments"][0] == {
        "season_year": 2024,
        "tournament": "Mystery Cup",
        "matches": 1,
    }
    history_text = written["history"].read_text(encoding="utf-8")
    assert history_text.startswith(HISTORY_HEADER + "\n")
    rows = list(csv.DictReader(io.StringIO(history_text)))
    assert rows[0]["tournament_level"] == "masters_1000"
    assert rows[0]["effective_k_factor"] == "48.0"


def test_write_outputs_still_reports_history_mismatch_before_touching_disk(tmp_path):
    from tennis_elo.export import write_outputs

    target = tmp_path / "out"

    with pytest.raises(ValueError, match="include_history"):
        write_outputs(build_result(load=_weighted_load(), history=()), target, include_history=True)

    assert not target.exists()
