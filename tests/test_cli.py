"""Tests for the argparse CLI.

Isolated unit tests monkeypatch ``tennis_elo.api.calculate`` (the CLI resolves
it through the module, never through an eager data/ratings import). Season
validation tests use the real ``api.calculate``, which rejects bad selections
before it touches the data/engine lanes. A synthetic-CSV integration test is
skipped until those lanes are integrated.
"""

import csv
import importlib.util
import json
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


def build_result(*, seasons=(2024,), include_history=False, players=None, load=None, config=None):
    matches = (
        Match(
            "m1",
            seasons[0],
            TS_1,
            "p1",
            "p2",
            "Alice",
            "Bob",
            1,
            tournament="Brisbane International",
            tournament_level="atp_250",
        ),
    )
    if load is None:
        load = LoadResult(
            matches, ("2024-atp-season.csv",), tuple(seasons), 3, 3, {"walkover": 1}, 0
        )
    history = _history() if include_history else ()
    return CalculationResult(
        tuple(seasons),
        config or RatingConfig(),
        load,
        RatingResult(_players() if players is None else players, history, 2),
    )


def _unknown_load():
    """Eligible matches whose categories the catalog could not classify."""

    matches = (
        Match(
            "m1", 2024, TS_1, "p1", "p2", "Alice", "Bob", 1,
            tournament="Mystery Cup", tournament_level="unknown",
        ),
        Match(
            "m2", 2024, TS_2, "p1", "p3", "Alice", "Carol", 2,
            tournament="", tournament_level="unknown",
        ),
        Match(
            "m3", 2024, TS_2, "p2", "p3", "Bob", "Carol", 1,
            tournament="Mystery Cup", tournament_level="unknown",
        ),
    )
    return LoadResult(matches, ("2024-atp-season.csv",), (2024,), 3, 3, {"walkover": 1}, 0)


@pytest.fixture
def fake_calculate_with_unknowns(monkeypatch):
    """Patch the calculation seam with a run that has unknown categories."""

    calls: list[dict] = []

    def _fake(input_dir, seasons, *, config=None, include_history=False):
        calls.append({"config": config, "include_history": include_history})
        return build_result(
            seasons=tuple(sorted(seasons)),
            include_history=include_history,
            load=_unknown_load(),
            config=config,
        )

    monkeypatch.setattr(api, "calculate", _fake)
    return calls


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
        return build_result(
            seasons=tuple(sorted(seasons)),
            include_history=include_history,
            config=config,
        )

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


# --- Tournament weighting model, help, output and unknown-category reports --


def test_rank_defaults_to_the_tournament_weighted_model(tmp_path, fake_calculate):
    status = main(["rank", "--seasons", "2024", "--output-dir", str(tmp_path)])

    assert status == 0
    assert fake_calculate[0]["config"].use_tournament_weights is True


def test_rank_unweighted_flag_selects_classic_elo(tmp_path, fake_calculate):
    status = main(
        ["rank", "--seasons", "2024", "--output-dir", str(tmp_path), "--unweighted"]
    )

    assert status == 0
    assert fake_calculate[0]["config"] == RatingConfig(use_tournament_weights=False)


def test_rank_k_factor_is_the_base_k_next_to_unweighted(tmp_path, fake_calculate):
    main(
        [
            "rank",
            "--seasons",
            "2024",
            "--output-dir",
            str(tmp_path),
            "--k-factor",
            "16",
            "--unweighted",
        ]
    )

    assert fake_calculate[0]["config"] == RatingConfig(
        k_factor=16.0, use_tournament_weights=False
    )


def test_rank_rejects_base_k_that_overflows_the_weighted_effective_k(tmp_path, capsys):
    target = tmp_path / "out"

    status = main(
        ["rank", "--seasons", "2024", "--output-dir", str(target), "--k-factor", "1e308"]
    )

    captured = capsys.readouterr()
    assert status == 2
    assert "effective K" in captured.err
    assert "Traceback" not in captured.err
    assert not target.exists()


def test_rank_help_documents_base_k_effective_k_and_the_unweighted_flag(capsys):
    with pytest.raises(SystemExit) as excinfo:
        main(["rank", "--help"])

    assert excinfo.value.code == 0
    out = capsys.readouterr().out
    assert "--unweighted" in out
    assert "tournament weighting" in out
    assert "base K" in out
    assert "effective K" in out
    assert "coefficient" in out


def test_rank_output_identifies_the_weighted_model(tmp_path, fake_calculate, capsys):
    main(["rank", "--seasons", "2024", "--output-dir", str(tmp_path)])

    out = capsys.readouterr().out
    assert (
        "Rating model: tournament-weighted (effective K = base K x coefficient; base K = 32)"
        in out
    )
    assert (
        "Tournament coefficients: challenger=0.75, atp_250=1.0, atp_500=1.25, "
        "masters_1000=1.5, atp_finals=1.75, grand_slam=2.0, other=1.0, unknown=1.0" in out
    )


def test_rank_output_reports_the_configured_base_k(tmp_path, fake_calculate, capsys):
    main(["rank", "--seasons", "2024", "--output-dir", str(tmp_path), "--k-factor", "16"])

    assert "base K = 16" in capsys.readouterr().out


def test_rank_output_identifies_the_unweighted_model(tmp_path, fake_calculate, capsys):
    main(["rank", "--seasons", "2024", "--output-dir", str(tmp_path), "--unweighted"])

    out = capsys.readouterr().out
    assert (
        "Rating model: unweighted (effective K = base K = 32; every tournament coefficient is "
        "treated as 1.0)" in out
    )
    assert "challenger" not in out


def test_rank_warns_about_unknown_tournaments_without_excluding_them(
    tmp_path, fake_calculate_with_unknowns, capsys
):
    status = main(["rank", "--seasons", "2024", "--output-dir", str(tmp_path)])

    out = capsys.readouterr().out
    assert status == 0
    assert (
        "Classification: 3 matches use unknown tournament names/years; the fallback coefficient "
        "1.0 applies and they are not excluded or errors." in out
    )
    assert (
        'Unknown tournaments: 2024 "(blank tournament name)" (1), 2024 "Mystery Cup" (2)' in out
    )
    # Unknown categories are reported, never counted as exclusions or errors.
    assert "Excluded rows: walkover=1" in out

    summary = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    assert summary["tournament_weighting"]["enabled"] is True
    assert summary["tournament_weighting"]["unknown_matches"] == 3
    assert summary["tournament_weighting"]["unknown_tournaments"] == [
        {"season_year": 2024, "tournament": "", "matches": 1},
        {"season_year": 2024, "tournament": "Mystery Cup", "matches": 2},
    ]


def test_rank_still_reports_unknowns_when_weighting_is_disabled(
    tmp_path, fake_calculate_with_unknowns, capsys
):
    status = main(
        ["rank", "--seasons", "2024", "--output-dir", str(tmp_path), "--unweighted"]
    )

    out = capsys.readouterr().out
    assert status == 0
    assert (
        "Classification: 3 matches use unknown tournament names/years; weighting is disabled, so "
        "the fallback coefficient 1.0 has no effect on ratings and they are not excluded or "
        "errors." in out
    )
    assert 'Unknown tournaments: 2024 "(blank tournament name)" (1), 2024 "Mystery Cup" (2)' in out

    summary = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    assert summary["tournament_weighting"]["enabled"] is False
    assert summary["configuration"]["use_tournament_weights"] is False
    assert summary["tournament_weighting"]["unknown_matches"] == 3


def test_rank_does_not_warn_when_every_tournament_is_classified(
    tmp_path, fake_calculate, capsys
):
    main(["rank", "--seasons", "2024", "--output-dir", str(tmp_path)])

    out = capsys.readouterr().out
    assert "unknown tournament names/years" not in out
    assert "Unknown tournaments:" not in out


def _classification_lines(text: str) -> list[str]:
    return [
        line
        for line in text.splitlines()
        if line.startswith(("Classification:", "Unknown tournaments:"))
    ]


def test_rank_unknown_report_is_deterministic(tmp_path, fake_calculate_with_unknowns, capsys):
    assert main(["rank", "--seasons", "2024", "--output-dir", str(tmp_path / "one")]) == 0
    first = _classification_lines(capsys.readouterr().out)
    assert main(["rank", "--seasons", "2024", "--output-dir", str(tmp_path / "two")]) == 0
    second = _classification_lines(capsys.readouterr().out)

    assert first
    assert first == second


def test_rank_unknown_report_caps_detail_and_points_at_the_summary(tmp_path, monkeypatch, capsys):
    matches = tuple(
        Match(
            f"m{i:02d}", 2024, TS_1 + i, "p1", "p2", "Alice", "Bob", 1,
            tournament=f"Event {i:02d}", tournament_level="unknown",
        )
        for i in range(12)
    )
    load = LoadResult(matches, ("2024-atp-season.csv",), (2024,), 12, 12, {}, 0)

    def _fake(input_dir, seasons, *, config=None, include_history=False):
        return build_result(
            seasons=tuple(sorted(seasons)), include_history=include_history, load=load
        )

    monkeypatch.setattr(api, "calculate", _fake)
    status = main(["rank", "--seasons", "2024", "--output-dir", str(tmp_path)])

    out = capsys.readouterr().out
    detail = next(line for line in out.splitlines() if line.startswith("Unknown tournaments:"))
    assert status == 0
    assert "Event 09" in detail
    assert "Event 10" not in detail
    assert "2 more" in detail
    assert "summary.json" in detail

    summary = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    assert len(summary["tournament_weighting"]["unknown_tournaments"]) == 12


def test_rank_flattens_untrusted_tournament_labels_in_the_report(tmp_path, monkeypatch, capsys):
    matches = (
        Match(
            "m1", 2024, TS_1, "p1", "p2", "Alice", "Bob", 1,
            tournament="Line One\nfake: not excluded", tournament_level="unknown",
        ),
    )
    load = LoadResult(matches, ("2024-atp-season.csv",), (2024,), 1, 1, {}, 0)

    def _fake(input_dir, seasons, *, config=None, include_history=False):
        return build_result(
            seasons=tuple(sorted(seasons)), include_history=include_history, load=load
        )

    monkeypatch.setattr(api, "calculate", _fake)
    main(["rank", "--seasons", "2024", "--output-dir", str(tmp_path)])

    out = capsys.readouterr().out
    assert 'Unknown tournaments: 2024 "Line One fake: not excluded" (1)' in out
    assert "Line One\nfake" not in out
    # The summary keeps the raw, untrusted label as data.
    summary = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    assert summary["tournament_weighting"]["unknown_tournaments"][0]["tournament"] == (
        "Line One\nfake: not excluded"
    )


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
