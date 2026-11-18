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
    "rating_after,tournament,surface"
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
