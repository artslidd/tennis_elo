"""Cross-component regressions for CSV validation and weighted CLI/dashboard flows."""

import csv
import io
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

CSV_HEADER = (
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
GOOD_ROW = [
    "m1",
    "2026",
    "1767320100",
    "ATP Tour",
    "FINISHED",
    "FINISHED",
    "p1",
    "p2",
    "Alpha",
    "Beta",
    "1",
]


def csv_bytes(row):
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer)
    writer.writerow(CSV_HEADER)
    writer.writerow(row)
    return buffer.getvalue().encode()


def malformed_payload(kind):
    if kind == "too_few_fields":
        return csv_bytes(GOOD_ROW[:-1])
    if kind == "too_many_fields":
        return csv_bytes([*GOOD_ROW, "unexpected"])
    if kind == "oversized_field":
        row = list(GOOD_ROW)
        row[8] = "X" * 140000
        return csv_bytes(row)
    if kind == "unterminated_quote":
        header = ",".join(CSV_HEADER)
        return (header + '\nm1,2026,1767320100,ATP Tour,FINISHED,FINISHED,p1,p2,"Alpha\n').encode()
    if kind == "invalid_utf8":
        return csv_bytes(GOOD_ROW).replace(b"Alpha", b"\xffAlpha")
    raise AssertionError(f"unknown test case: {kind}")


@pytest.mark.parametrize(
    "kind",
    ["too_few_fields", "too_many_fields", "oversized_field", "unterminated_quote", "invalid_utf8"],
)
def test_cli_rejects_structural_csv_errors_without_traceback(tmp_path, kind):
    path = tmp_path / "2026-atp-season.csv"
    path.write_bytes(malformed_payload(kind))
    output = tmp_path / "output"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "tennis_elo",
            "rank",
            "--seasons",
            "2026",
            "--input-dir",
            str(tmp_path),
            "--output-dir",
            str(output),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2, result.stdout + result.stderr
    assert "Traceback" not in result.stderr
    assert str(path) in result.stderr
    assert not output.exists()


WEIGHT_CASES = (
    ("challenger", "ATP Chall", "Canberra Challenger", 0.75),
    ("atp_250", "ATP Tour", "Brisbane ATP", 1.0),
    ("atp_500", "ATP Tour", "Rotterdam ATP (indoor)", 1.25),
    ("masters_1000", "ATP Tour", "Indian Wells ATP", 1.5),
    ("atp_finals", "ATP Tour", "Finals - Turin ATP (indoor)", 1.75),
    ("grand_slam", "ATP Tour", "Australian Open ATP", 2.0),
    ("other", "ATP Tour", "United Cup ATP", 1.0),
    ("unknown", "ATP Tour", "Uncatalogued Event ATP", 1.0),
)


@pytest.mark.parametrize("weighted", [True, False], ids=["weighted", "classic"])
def test_cli_tournament_weights_are_consistent_across_rankings_history_and_summary(
    tmp_path, weighted
):
    """Exercise the real catalog, loader, replay, CLI and serializers together."""
    path = tmp_path / "2026-atp-season.csv"
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow((*CSV_HEADER, "tournament"))
        for index, (level, tour, tournament, _) in enumerate(WEIGHT_CASES):
            writer.writerow(
                [
                    f"m{index}",
                    2026,
                    1767312000 + index * 3600,
                    tour,
                    "FINISHED",
                    "FINISHED",
                    f"{level}-home",
                    f"{level}-away",
                    f"{level} winner",
                    f"{level} loser",
                    1,
                    tournament,
                ]
            )
    output = tmp_path / "output"
    command = [
        sys.executable,
        "-m",
        "tennis_elo",
        "rank",
        "--seasons",
        "2026",
        "--input-dir",
        str(tmp_path),
        "--output-dir",
        str(output),
        "--history",
    ]
    if not weighted:
        command.append("--unweighted")
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Traceback" not in result.stderr
    messages = result.stdout + result.stderr
    assert "unknown tournament" in messages.lower()
    assert "coefficient 1.0" in messages
    assert "Uncatalogued Event ATP" in messages

    summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    assert summary["configuration"]["use_tournament_weights"] is weighted
    weighting = summary["tournament_weighting"]
    assert weighting["enabled"] is weighted
    assert weighting["coefficients"] == {
        level: coefficient for level, _, _, coefficient in WEIGHT_CASES
    }
    assert weighting["matches_by_level"] == {level: 1 for level, _, _, _ in WEIGHT_CASES}
    assert weighting["unknown_matches"] == 1
    assert weighting["unknown_tournaments"] == [
        {"season_year": 2026, "tournament": "Uncatalogued Event ATP", "matches": 1}
    ]

    with (output / "rankings.csv").open(newline="", encoding="utf-8") as stream:
        rankings = {row["player_id"]: row for row in csv.DictReader(stream)}
    assert len(rankings) == 16
    assert sum(float(row["rating"]) for row in rankings.values()) == pytest.approx(16 * 1500)
    for level, _, _, coefficient in WEIGHT_CASES:
        applied = coefficient if weighted else 1.0
        assert float(rankings[f"{level}-home"]["rating"]) == 1500 + 16 * applied
        assert float(rankings[f"{level}-away"]["rating"]) == 1500 - 16 * applied

    with (output / "history.csv").open(newline="", encoding="utf-8") as stream:
        histories = list(csv.DictReader(stream))
    assert len(histories) == 16
    coefficients = {level: coefficient for level, _, _, coefficient in WEIGHT_CASES}
    for entry in histories:
        level = entry["tournament_level"]
        applied = coefficients[level] if weighted else 1.0
        assert float(entry["tournament_weight"]) == applied
        assert float(entry["effective_k_factor"]) == 32 * applied
        delta = float(entry["rating_after"]) - float(entry["rating_before"])
        assert abs(delta) == 16 * applied


def _write_ui_season(directory, year, tournament, *, winner=1):
    with (directory / f"{year}-atp-season.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow((*CSV_HEADER, "tournament"))
        record = list(GOOD_ROW)
        record[0] = f"m{year}"
        record[1] = str(year)
        record[2] = str({2024: 1704153600, 2025: 1735776000, 2026: 1767312000}[year])
        record[10] = str(winner)
        writer.writerow([*record, tournament])


def _assert_no_ui_exception(app):
    assert not app.exception, [error.value for error in app.exception]


def _ui_table(app, columns):
    return next(
        frame.value for frame in app.dataframe if list(frame.value.columns) == list(columns)
    )


def test_dashboard_weighted_mode_uses_real_api_and_invalidates_comparison_cache(tmp_path):
    testing = pytest.importorskip("streamlit.testing.v1")
    from tennis_elo.api import calculate
    from tennis_elo.dashboard_views import HISTORY_COLUMNS, PLAYER_COMPARISON_COLUMNS
    from tennis_elo.models import RatingConfig

    _write_ui_season(tmp_path, 2024, "Brisbane ATP")
    _write_ui_season(tmp_path, 2025, "Doha ATP", winner=2)
    _write_ui_season(tmp_path, 2026, "Australian Open ATP")
    script = Path(__file__).resolve().parents[1] / "src/tennis_elo/dashboard.py"
    with patch("tennis_elo.api.calculate", wraps=calculate) as calls:
        app = testing.AppTest.from_file(str(script), default_timeout=60).run()
        _assert_no_ui_exception(app)
        app.text_input(key="input_dir").set_value(str(tmp_path)).run()
        assert app.checkbox(key="use_tournament_weights").value is True
        app.button(key="calculate").click().run()
        _assert_no_ui_exception(app)
        run = app.session_state["run"]
        assert run["result"].config.use_tournament_weights is True
        assert next(p.rating for p in run["result"].ratings.players if p.player_id == "p1") == 1532
        assert run["summary"]["tournament_weighting"]["unknown_matches"] == 0
        history = _ui_table(app, HISTORY_COLUMNS)
        assert set(history["tournament_level"]) == {"grand_slam"}
        assert set(history["tournament_weight"]) == {2.0}
        assert set(history["effective_k_factor"]) == {64.0}

        app.button(key="compare_windows").click().run()
        _assert_no_ui_exception(app)
        assert calls.call_count == 4  # main run + three independent windows
        _ui_table(app, PLAYER_COMPARISON_COLUMNS)
        app.selectbox(key="player_id").set_value("p2").run()
        _assert_no_ui_exception(app)
        assert calls.call_count == 4  # player switching only reads cached rankings

        app.checkbox(key="use_tournament_weights").set_value(False).run()
        _assert_no_ui_exception(app)
        assert calls.call_count == 4
        assert any("controls changed" in warning.value.lower() for warning in app.warning)
        assert not any(
            list(frame.value.columns) == list(PLAYER_COMPARISON_COLUMNS) for frame in app.dataframe
        )
        # A stale main run retains its truthful recorded model until recalculated.
        assert app.session_state["run"]["result"].config.use_tournament_weights is True
        app.button(key="compare_windows").click().run()
        _assert_no_ui_exception(app)
        assert calls.call_count == 7
        assert all(
            call.kwargs["config"].use_tournament_weights is False
            for call in calls.call_args_list[-3:]
        )
        comparison = _ui_table(app, PLAYER_COMPARISON_COLUMNS)
        for index, seasons in enumerate(((2026,), (2025, 2026), (2024, 2025, 2026))):
            reference = calculate(
                tmp_path, seasons, config=RatingConfig(use_tournament_weights=False)
            )
            rank, player = next(
                (i, p) for i, p in enumerate(reference.ratings.players, 1) if p.player_id == "p2"
            )
            assert float(comparison.iloc[index]["rating"]) == round(round(player.rating, 2), 1)
            assert int(comparison.iloc[index]["rank"]) == rank
            assert int(comparison.iloc[index]["matches"]) == player.matches

        app.button(key="calculate").click().run()
        _assert_no_ui_exception(app)
        assert calls.call_count == 8
        run = app.session_state["run"]
        assert run["result"].config.use_tournament_weights is False
        assert run["summary"]["tournament_weighting"]["enabled"] is False
        assert next(p.rating for p in run["result"].ratings.players if p.player_id == "p1") == 1516
        assert app.selectbox(key="player_id").value == "p2"
        history = _ui_table(app, HISTORY_COLUMNS)
        assert set(history["tournament_level"]) == {"grand_slam"}
        assert set(history["tournament_weight"]) == {1.0}
        assert set(history["effective_k_factor"]) == {32.0}


def test_dashboard_unknown_fallback_is_visible_with_real_api(tmp_path):
    testing = pytest.importorskip("streamlit.testing.v1")
    from tennis_elo.dashboard_views import HISTORY_COLUMNS

    _write_ui_season(tmp_path, 2026, "Uncatalogued Event ATP")
    script = Path(__file__).resolve().parents[1] / "src/tennis_elo/dashboard.py"
    app = testing.AppTest.from_file(str(script), default_timeout=60).run()
    app.text_input(key="input_dir").set_value(str(tmp_path)).run()
    app.button(key="calculate").click().run()
    _assert_no_ui_exception(app)
    assert any(
        "unknown" in warning.value.lower() and "1.00" in warning.value for warning in app.warning
    )
    assert app.session_state["run"]["summary"]["tournament_weighting"]["unknown_matches"] == 1
    history = _ui_table(app, HISTORY_COLUMNS)
    assert set(history["tournament_level"]) == {"unknown"}
    assert set(history["tournament_weight"]) == {1.0}
    assert set(history["effective_k_factor"]) == {32.0}
