"""Tests for the argparse CLI.

Isolated unit tests monkeypatch ``tennis_elo.api.calculate`` (the CLI resolves
it through the module, never through an eager data/ratings import). Season
validation tests use the real ``api.calculate``, which rejects bad selections
before it touches the data/engine lanes. A synthetic-CSV integration test is
skipped until those lanes are integrated.
"""

import csv
import importlib.util
import subprocess
import sys

import pytest

from tennis_elo import api
from tennis_elo.cli import main
from tennis_elo.models import (
    CalculationResult,
    HistoryEntry,
    LoadResult,
    Match,
    PlayerRating,
    RatingConfig,
    RatingResult,
)

TS_1 = 1704067200  # 2024-01-01T00:00:00+00:00
TS_2 = 1704153600  # 2024-01-02T00:00:00+00:00


def _players():
    return (
        PlayerRating("p1", "Alice", 1516.0, 3, 2, 1, TS_1, TS_2),
        PlayerRating("p2", "Bob", 1500.0, 2, 1, 1, TS_1, TS_1),
        PlayerRating("p3", "Carol", 1484.0, 1, 0, 1, TS_2, TS_2),
    )


def _history():
    return (
        HistoryEntry(
            "m1", 2024, TS_1, "p1", "Alice", "p2", "Bob", True, 1500.0, 1500.0, 0.5, 1516.0
        ),
        HistoryEntry(
            "m1", 2024, TS_1, "p2", "Bob", "p1", "Alice", False, 1500.0, 1500.0, 0.5, 1484.0
        ),
    )


def build_result(*, seasons=(2024,), include_history=False, players=None):
    matches = (Match("m1", seasons[0], TS_1, "p1", "p2", "Alice", "Bob", 1),)
    load = LoadResult(matches, ("2024-atp-season.csv",), tuple(seasons), 3, 3, {"walkover": 1}, 0)
    history = _history() if include_history else ()
    return CalculationResult(
        tuple(seasons),
        RatingConfig(),
        load,
        RatingResult(_players() if players is None else players, history, 2),
    )


@pytest.fixture
def fake_calculate(monkeypatch):
    """Patch the module-level seam the CLI calls and record its arguments."""

    calls: list[dict] = []

    def _fake(input_dir, seasons, *, config=None, include_history=False):
        calls.append(
            {
                "input_dir": input_dir,
                "seasons": list(seasons),
                "config": config,
                "include_history": include_history,
            }
        )
        return build_result(seasons=tuple(sorted(seasons)), include_history=include_history)

    monkeypatch.setattr(api, "calculate", _fake)
    return calls


def test_rank_writes_outputs_and_prints_table(tmp_path, fake_calculate, capsys):
    output_dir = tmp_path / "out"

    status = main(["rank", "--seasons", "2024", "--output-dir", str(output_dir)])

    assert status == 0
    captured = capsys.readouterr()
    assert "Alice" in captured.out
    assert "1516" in captured.out
    assert (output_dir / "rankings.csv").is_file()
    assert (output_dir / "summary.json").is_file()
    assert not (output_dir / "history.csv").exists()
    assert fake_calculate[0]["seasons"] == [2024]
    assert fake_calculate[0]["config"] == RatingConfig()
    assert fake_calculate[0]["include_history"] is False


def test_rank_defaults_output_dir_to_outputs_selected_years(tmp_path, fake_calculate, monkeypatch):
    monkeypatch.chdir(tmp_path)

    status = main(["rank", "--seasons", "2024", "2025"])

    assert status == 0
    assert (tmp_path / "outputs" / "2024-2025" / "rankings.csv").is_file()


def test_rank_single_season_default_dir_is_the_year(tmp_path, fake_calculate, monkeypatch):
    monkeypatch.chdir(tmp_path)

    assert main(["rank", "--seasons", "2026"]) == 0
    assert (tmp_path / "outputs" / "2026" / "rankings.csv").is_file()


def test_rank_writes_history_when_requested(tmp_path, fake_calculate, capsys):
    status = main(["rank", "--seasons", "2024", "--output-dir", str(tmp_path), "--history"])

    assert status == 0
    assert (tmp_path / "history.csv").is_file()
    assert fake_calculate[0]["include_history"] is True


def test_rank_top_limits_displayed_rows(tmp_path, fake_calculate, capsys):
    status = main(["rank", "--seasons", "2024", "--output-dir", str(tmp_path), "--top", "1"])

    assert status == 0
    out = capsys.readouterr().out
    assert "Alice" in out
    assert "Bob" not in out
    # The exported rankings still contain every player by default.
    assert "p2" in (tmp_path / "rankings.csv").read_text(encoding="utf-8")


def test_rank_min_matches_filters_exports(tmp_path, fake_calculate):
    status = main(
        ["rank", "--seasons", "2024", "--output-dir", str(tmp_path), "--min-matches", "2"]
    )

    assert status == 0
    rows = list(csv.DictReader((tmp_path / "rankings.csv").open(encoding="utf-8")))
    assert [row["player_id"] for row in rows] == ["p1", "p2"]


def test_rank_passes_rating_configuration(tmp_path, fake_calculate):
    status = main(
        [
            "rank",
            "--seasons",
            "2024",
            "--output-dir",
            str(tmp_path),
            "--initial-rating",
            "1600",
            "--k-factor",
            "16",
            "--exclude-retirements",
        ]
    )

    assert status == 0
    config = fake_calculate[0]["config"]
    assert config == RatingConfig(initial_rating=1600.0, k_factor=16.0, include_retirements=False)


def test_rank_accepts_input_dir(tmp_path, fake_calculate):
    assert (
        main(
            ["rank", "--seasons", "2024", "--input-dir", "some/data", "--output-dir", str(tmp_path)]
        )
        == 0
    )
    assert fake_calculate[0]["input_dir"] == "some/data"


@pytest.mark.parametrize(
    "seasons,message",
    [
        (["2024", "2024"], "distinct"),
        (["2024", "2026"], "consecutive"),
        (["2021", "2022", "2023", "2024"], "three"),
    ],
)
def test_rank_reports_invalid_selections_without_traceback(tmp_path, capsys, seasons, message):
    status = main(["rank", "--seasons", *seasons, "--output-dir", str(tmp_path / "out")])

    captured = capsys.readouterr()
    assert status == 2
    assert message in captured.err
    assert "Traceback" not in captured.err
    assert not (tmp_path / "out").exists()


def test_rank_rejects_non_empty_output_dir(tmp_path, fake_calculate, capsys):
    (tmp_path / "existing.txt").write_text("keep", encoding="utf-8")

    status = main(["rank", "--seasons", "2024", "--output-dir", str(tmp_path)])

    captured = capsys.readouterr()
    assert status == 2
    assert "not empty" in captured.err
    assert "Traceback" not in captured.err


def test_rank_reports_history_mismatch_without_traceback(tmp_path, monkeypatch, capsys):
    def calculate_without_history(input_dir, seasons, *, config=None, include_history=False):
        # Simulates a result that was calculated without history entries.
        return build_result(seasons=tuple(sorted(seasons)), include_history=False)

    monkeypatch.setattr(api, "calculate", calculate_without_history)
    target = tmp_path / "out"

    status = main(["rank", "--seasons", "2024", "--output-dir", str(target), "--history"])

    captured = capsys.readouterr()
    assert status == 2
    assert "include_history" in captured.err
    assert "Traceback" not in captured.err
    assert not target.exists()


@pytest.mark.parametrize("flag,value", [("--top", "-1"), ("--min-matches", "-1")])
def test_rank_rejects_negative_limits(tmp_path, flag, value, capsys):
    status = main(["rank", "--seasons", "2024", "--output-dir", str(tmp_path), flag, value])

    captured = capsys.readouterr()
    assert status == 2
    assert flag in captured.err


def test_rank_rejects_invalid_k_factor(tmp_path, capsys):
    status = main(["rank", "--seasons", "2024", "--output-dir", str(tmp_path), "--k-factor", "0"])

    captured = capsys.readouterr()
    assert status == 2
    assert "k_factor" in captured.err
    assert "Traceback" not in captured.err


def test_seasons_is_required(capsys):
    with pytest.raises(SystemExit) as excinfo:
        main(["rank"])
    assert excinfo.value.code == 2


def test_unknown_command_exits_with_usage_error(capsys):
    with pytest.raises(SystemExit) as excinfo:
        main(["frobnicate"])
    assert excinfo.value.code == 2


def test_main_reads_and_returns_status_from_sys_argv(tmp_path, fake_calculate, monkeypatch):
    monkeypatch.setattr(
        sys, "argv", ["tennis-elo", "rank", "--seasons", "2024", "--output-dir", str(tmp_path)]
    )

    assert main() == 0
    assert (tmp_path / "rankings.csv").is_file()


def test_python_m_entry_point_reports_errors_without_traceback(tmp_path):
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "tennis_elo",
            "rank",
            "--seasons",
            "2024",
            "2024",
            "--output-dir",
            str(tmp_path / "out"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 2
    assert "distinct" in completed.stderr
    assert "Traceback" not in completed.stderr


# --- Integration test: requires the data and engine lanes -------------------


def _siblings_available() -> bool:
    return (
        importlib.util.find_spec("tennis_elo.data") is not None
        and importlib.util.find_spec("tennis_elo.ratings") is not None
    )


requires_siblings = pytest.mark.skipif(
    not _siblings_available(),
    reason="data/ratings lanes not integrated yet; parent runs this after integration",
)


@requires_siblings
def test_rank_end_to_end_on_synthetic_csv(tmp_path, capsys, monkeypatch):
    input_dir = tmp_path / "data"
    input_dir.mkdir()
    csv_path = input_dir / "2024-atp-season.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
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
            ]
        )
        writer.writerow(
            [
                "m1",
                2024,
                1704067200,
                "ATP Tour",
                "FINISHED",
                "FINISHED",
                "p1",
                "p2",
                "Alice",
                "Bob",
                1,
            ]
        )
    monkeypatch.chdir(tmp_path)

    status = main(["rank", "--seasons", "2024", "--input-dir", str(input_dir)])

    assert status == 0
    out = capsys.readouterr().out
    assert "Alice" in out
    rankings = (tmp_path / "outputs" / "2024" / "rankings.csv").read_text(encoding="utf-8")
    assert "Alice" in rankings
    assert "1516" in rankings
