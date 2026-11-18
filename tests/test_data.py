"""Tests for CSV discovery, season selection, validation, and match loading."""

import csv

import pytest

from tennis_elo.data import available_seasons, discover_csv_files, load_matches
from tennis_elo.models import LoadResult, Match

COLUMNS = [
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
    "tournament",
    "round",
    "surface",
]

# A December 2023 instant belongs to the 2024 season in these files.
DEC_2023 = "1703815800"
JAN_2026 = "1767320100"


def make_row(**overrides):
    row = {
        "match_id": "m1",
        "season_year": "2024",
        "date_timestamp": DEC_2023,
        "tour_type_human": "ATP Tour",
        "status": "FINISHED",
        "status_extra": "FINISHED",
        "home_id": "p1",
        "away_id": "p2",
        "home_name": "Home Player",
        "away_name": "Away Player",
        "winner_code": "1",
        "tournament": "Test Open",
        "round": "R16",
        "surface": "hard",
    }
    row.update(overrides)
    return row


def write_season_csv(path, rows, *, encoding="utf-8", columns=COLUMNS):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding=encoding, newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in columns})
    return path


# A 49-column schema mirroring the real *-atp-season.csv layout. Used to pin
# structural corruption (missing/extra fields, broken quoting) that the frozen
# 14-column helper above cannot express.
WIDE_COLUMNS = [
    "match_id",
    "season_year",
    "tour_type",
    "tour_type_human",
    "date_timestamp",
    "date_human",
    "tournament",
    "round",
    "surface",
    "surface_id",
    "status",
    "status_extra",
    "home_name",
    "away_name",
    "home_id",
    "away_id",
    "home_rank",
    "away_rank",
    "home_points",
    "away_points",
    "winner_code",
    "home_set_score",
    "away_set_score",
    "home_set_1_score",
    "away_set_1_score",
    "home_set_2_score",
    "away_set_2_score",
    "home_set_3_score",
    "away_set_3_score",
    "home_set_4_score",
    "away_set_4_score",
    "home_set_5_score",
    "away_set_5_score",
    "home_odds_match_winner",
    "away_odds_match_winner",
    "home_odds_first_set_winner",
    "away_odds_first_set_winner",
    "home_aces",
    "away_aces",
    "home_double_faults",
    "away_double_faults",
    "home_service_points_won_perc",
    "away_service_points_won_perc",
    "home_return_points_won_perc",
    "away_return_points_won_perc",
    "home_break_points_won_perc",
    "away_break_points_won_perc",
    "home_break_points_saved_perc",
    "away_break_points_saved_perc",
]

WIDE_DEFAULTS = {
    "match_id": "75191598",
    "season_year": "2024",
    "tour_type": "1",
    "tour_type_human": "ATP Tour",
    "date_timestamp": DEC_2023,
    "date_human": "29 Dec 2023",
    "tournament": "United Cup ATP",
    "round": "",
    "surface": "hard",
    "surface_id": "1",
    "status": "FINISHED",
    "status_extra": "FINISHED",
    "home_name": "Home Player",
    "away_name": "Away Player",
    "home_id": "292653",
    "away_id": "956292",
    "home_rank": "36",
    "away_rank": "45",
    "home_points": "1395",
    "away_points": "1155",
    "winner_code": "2",
}


def wide_values(**overrides):
    values = dict(WIDE_DEFAULTS)
    values.update(overrides)
    return [values.get(column, "0") for column in WIDE_COLUMNS]


def write_wide_rows(path, value_rows, *, encoding="utf-8"):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding=encoding, newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(WIDE_COLUMNS)
        for values in value_rows:
            writer.writerow(values)
    return path


def write_wide_raw(path, lines, *, encoding="utf-8"):
    """Write a wide CSV with pre-built raw data lines (for corrupt fixtures)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    body = ",".join(WIDE_COLUMNS) + "\n" + "\n".join(lines) + "\n"
    path.write_text(body, encoding=encoding, newline="")
    return path


def assert_both_loaders_reject(tmp_path, path, *, expect_width=None):
    """Both entry points must reject a structural defect with file context."""
    for label, call in (
        ("load_matches", lambda: load_matches([path], [2024])),
        ("available_seasons", lambda: available_seasons(tmp_path)),
    ):
        with pytest.raises(ValueError) as excinfo:
            call()
        message = str(excinfo.value)
        assert path.name in message, label
        assert ":2" in message, label
        assert "invalid_winner" not in message, label
        if expect_width is not None:
            expected, actual = expect_width
            assert f"expected {expected} fields" in message, label
            assert f"got {actual} fields" in message, label


def assert_accounting(result: LoadResult) -> None:
    assert result.selected_rows == (
        len(result.matches) + sum(result.excluded_counts.values()) + result.duplicate_rows
    )


# --------------------------------------------------------------------------- #
# discover_csv_files
# --------------------------------------------------------------------------- #


def test_discover_csv_files_returns_sorted_tuple(tmp_path):
    write_season_csv(tmp_path / "2026-atp-season.csv", [make_row()])
    write_season_csv(tmp_path / "2024-atp-season.csv", [make_row()])
    (tmp_path / "notes.txt").write_text("ignore me")
    (tmp_path / "2025-atp.csv").write_text("ignore me too")

    files = discover_csv_files(tmp_path)

    assert files == (
        tmp_path / "2024-atp-season.csv",
        tmp_path / "2026-atp-season.csv",
    )
    assert isinstance(files, tuple)
    assert all(isinstance(path, type(tmp_path)) for path in files)


def test_discover_csv_files_accepts_string_input(tmp_path):
    write_season_csv(tmp_path / "2024-atp-season.csv", [make_row()])
    assert discover_csv_files(str(tmp_path)) == (tmp_path / "2024-atp-season.csv",)


def test_discover_csv_files_missing_directory_raises_oserror(tmp_path):
    with pytest.raises(FileNotFoundError):
        discover_csv_files(tmp_path / "does-not-exist")


def test_discover_csv_files_file_instead_of_directory_raises_oserror(tmp_path):
    target = tmp_path / "2024-atp-season.csv"
    target.write_text("nope")
    with pytest.raises(NotADirectoryError):
        discover_csv_files(target)


def test_discover_csv_files_no_matches_raises_value_error(tmp_path):
    (tmp_path / "notes.txt").write_text("nothing here")
    with pytest.raises(ValueError, match="atp-season"):
        discover_csv_files(tmp_path)


# --------------------------------------------------------------------------- #
# available_seasons
# --------------------------------------------------------------------------- #


def test_available_seasons_uses_season_year_column(tmp_path):
    write_season_csv(
        tmp_path / "mixed-atp-season.csv",
        [
            make_row(match_id="a", season_year="2024", date_timestamp=DEC_2023),
            make_row(match_id="b", season_year="2026", date_timestamp=JAN_2026),
            make_row(match_id="c", season_year="2024", date_timestamp=DEC_2023),
            make_row(match_id="d", season_year="2025", date_timestamp="1735689600"),
        ],
    )
    assert available_seasons(tmp_path) == (2024, 2025, 2026)


def test_available_seasons_reads_utf8_bom(tmp_path):
    write_season_csv(
        tmp_path / "bom-atp-season.csv",
        [make_row(season_year="2024")],
        encoding="utf-8-sig",
    )
    assert available_seasons(tmp_path) == (2024,)


def test_available_seasons_missing_column_mentions_file(tmp_path):
    write_season_csv(
        tmp_path / "broken-atp-season.csv",
        [make_row()],
        columns=[column for column in COLUMNS if column != "season_year"],
    )
    with pytest.raises(ValueError) as excinfo:
        available_seasons(tmp_path)
    message = str(excinfo.value)
    assert "broken-atp-season.csv" in message
    assert "season_year" in message


def test_available_seasons_invalid_value_has_file_and_line(tmp_path):
    write_season_csv(
        tmp_path / "badseason-atp-season.csv",
        [make_row(season_year="not-a-year")],
    )
    with pytest.raises(ValueError) as excinfo:
        available_seasons(tmp_path)
    message = str(excinfo.value)
    assert "badseason-atp-season.csv" in message
    assert ":2:" in message


# --------------------------------------------------------------------------- #
# load_matches: happy path and season semantics
# --------------------------------------------------------------------------- #


def test_load_matches_builds_expected_match(tmp_path):
    path = write_season_csv(
        tmp_path / "2024-atp-season.csv",
        [make_row(match_id="0001", home_id="007", away_id="010")],
    )
    result = load_matches([path], [2024])

    assert isinstance(result, LoadResult)
    assert result.matches == (
        Match(
            match_id="0001",
            season_year=2024,
            timestamp=int(DEC_2023),
            home_id="007",
            away_id="010",
            home_name="Home Player",
            away_name="Away Player",
            winner_code=1,
            tournament="Test Open",
            round="R16",
            surface="hard",
        ),
    )
    assert result.input_files == (str(path),)
    assert result.available_seasons == (2024,)
    assert result.rows_read == 1
    assert result.selected_rows == 1
    assert result.excluded_counts == {}
    assert result.duplicate_rows == 0
    assert_accounting(result)


def test_load_matches_optional_fields_default_to_empty(tmp_path):
    path = write_season_csv(
        tmp_path / "2024-atp-season.csv",
        [make_row(tournament="", round="", surface="")],
    )
    (match,) = load_matches([path], [2024]).matches
    assert (match.tournament, match.round, match.surface) == ("", "", "")


def test_season_year_is_authoritative_over_calendar_date(tmp_path):
    path = write_season_csv(
        tmp_path / "2024-atp-season.csv",
        [make_row(match_id="dec", season_year="2024", date_timestamp=DEC_2023)],
    )
    # Selected as 2024 even though the timestamp is in calendar 2023.
    assert len(load_matches([path], [2024]).matches) == 1
    # 2023 is never silently substituted for the authoritative season_year.
    with pytest.raises(ValueError, match="2023"):
        load_matches([path], [2023])


def test_unselected_season_rows_counted_in_rows_read_only(tmp_path):
    path = write_season_csv(
        tmp_path / "mixed-atp-season.csv",
        [
            make_row(match_id="a", season_year="2024"),
            make_row(match_id="b", season_year="2025"),
            make_row(match_id="c", season_year="2025"),
        ],
    )
    result = load_matches([path], [2024])
    assert result.rows_read == 3
    assert result.selected_rows == 1
    assert len(result.matches) == 1
    assert result.available_seasons == (2024, 2025)
    assert_accounting(result)


def test_one_two_and_three_consecutive_seasons_accepted(tmp_path):
    write_season_csv(tmp_path / "2024-atp-season.csv", [make_row(match_id="a", season_year="2024")])
    write_season_csv(tmp_path / "2025-atp-season.csv", [make_row(match_id="b", season_year="2025")])
    write_season_csv(tmp_path / "2026-atp-season.csv", [make_row(match_id="c", season_year="2026")])
    paths = discover_csv_files(tmp_path)

    assert [match.match_id for match in load_matches(paths, [2025]).matches] == ["b"]
    assert [match.match_id for match in load_matches(paths, [2025, 2026]).matches] == ["b", "c"]
    assert [match.match_id for match in load_matches(paths, [2024, 2025, 2026]).matches] == [
        "a",
        "b",
        "c",
    ]
    # Selection order does not matter.
    assert load_matches(paths, [2026, 2024, 2025]).matches == load_matches(
        paths, [2024, 2025, 2026]
    ).matches


@pytest.mark.parametrize(
    "seasons",
    [
        [],
        [2024, 2024],
        [2024, 2025, 2026, 2027],
        [2024, 2026],
        [2024, 2025, 2027],
    ],
)
def test_invalid_season_selections_rejected(tmp_path, seasons):
    write_season_csv(tmp_path / "2024-atp-season.csv", [make_row()])
    with pytest.raises(ValueError):
        load_matches(discover_csv_files(tmp_path), seasons)


def test_non_integer_season_rejected(tmp_path):
    write_season_csv(tmp_path / "2024-atp-season.csv", [make_row()])
    with pytest.raises(ValueError, match="season"):
        load_matches(discover_csv_files(tmp_path), ["2024-ish"])


@pytest.mark.parametrize(
    "bad",
    [2026.5, 2026.0, float("inf"), float("-inf"), float("nan"), True, False],
    ids=["fractional", "integral-float", "inf", "-inf", "nan", "true", "false"],
)
def test_strict_season_values_rejected_with_value_in_message(tmp_path, bad):
    path = write_season_csv(tmp_path / "2024-atp-season.csv", [make_row()])
    with pytest.raises(ValueError) as excinfo:
        load_matches([path], [bad])
    message = str(excinfo.value)
    assert "season" in message
    assert repr(bad) in message


def test_strict_season_rejects_mixed_valid_and_invalid(tmp_path):
    path = write_season_csv(tmp_path / "2024-atp-season.csv", [make_row()])
    with pytest.raises(ValueError) as excinfo:
        load_matches([path], [2024, 2026.0])
    assert "2026.0" in str(excinfo.value)


def test_valid_integer_seasons_accepted(tmp_path):
    write_season_csv(tmp_path / "2024-atp-season.csv", [make_row(match_id="a", season_year="2024")])
    write_season_csv(tmp_path / "2025-atp-season.csv", [make_row(match_id="b", season_year="2025")])
    paths = discover_csv_files(tmp_path)
    assert [match.match_id for match in load_matches(paths, [2024, 2025]).matches] == ["a", "b"]


def test_unavailable_season_rejected(tmp_path):
    write_season_csv(tmp_path / "2024-atp-season.csv", [make_row(season_year="2024")])
    with pytest.raises(ValueError) as excinfo:
        load_matches(discover_csv_files(tmp_path), [2025])
    message = str(excinfo.value)
    assert "2025" in message
    assert "2024" in message


def test_empty_paths_rejected(tmp_path):
    with pytest.raises(ValueError, match="path"):
        load_matches([], [2024])


def test_single_string_path_accepted(tmp_path):
    path = write_season_csv(tmp_path / "2024-atp-season.csv", [make_row()])
    assert len(load_matches(str(path), [2024]).matches) == 1


def test_bytes_paths_rejected(tmp_path):
    with pytest.raises(TypeError, match="bytes"):
        load_matches(b"2024-atp-season.csv", [2024])


def test_string_seasons_rejected(tmp_path):
    path = write_season_csv(tmp_path / "2024-atp-season.csv", [make_row()])
    with pytest.raises(TypeError, match="non-string"):
        load_matches([path], "2024")


# --------------------------------------------------------------------------- #
# load_matches: ordering and duplicate handling
# --------------------------------------------------------------------------- #


def test_matches_sorted_by_timestamp_then_match_id(tmp_path):
    path = write_season_csv(
        tmp_path / "2024-atp-season.csv",
        [
            make_row(match_id="b", date_timestamp="200"),
            make_row(match_id="a", date_timestamp="200"),
            make_row(match_id="z", date_timestamp="100"),
            make_row(match_id="10", date_timestamp="150"),
            make_row(match_id="9", date_timestamp="150"),
        ],
    )
    result = load_matches([path], [2024])
    # Same timestamp: string comparison puts "10" before "9".
    assert [match.match_id for match in result.matches] == ["z", "10", "9", "a", "b"]


def test_shuffled_paths_and_rows_yield_same_sorted_matches(tmp_path):
    rows_a = [
        make_row(match_id="x", date_timestamp="300", season_year="2024"),
        make_row(match_id="a", date_timestamp="100", season_year="2024"),
    ]
    rows_b = [
        make_row(match_id="b", date_timestamp="200", season_year="2025"),
        make_row(match_id="c", date_timestamp="100", season_year="2025"),
    ]
    path_a = write_season_csv(tmp_path / "2024-atp-season.csv", rows_a)
    path_b = write_season_csv(tmp_path / "2025-atp-season.csv", rows_b)

    first = load_matches([path_a, path_b], [2024, 2025])
    second = load_matches([path_b, path_a], [2025, 2024])
    assert first.matches == second.matches
    assert [match.match_id for match in first.matches] == ["a", "c", "b", "x"]


def test_identical_duplicate_rows_ignored_and_counted(tmp_path):
    path = write_season_csv(
        tmp_path / "2024-atp-season.csv",
        [make_row(match_id="m1"), make_row(match_id="m1")],
    )
    result = load_matches([path], [2024])
    assert len(result.matches) == 1
    assert result.duplicate_rows == 1
    assert result.selected_rows == 2
    assert_accounting(result)


def test_identical_duplicate_across_files_ignored(tmp_path):
    path_a = write_season_csv(tmp_path / "alpha-atp-season.csv", [make_row(match_id="m1")])
    path_b = write_season_csv(tmp_path / "beta-atp-season.csv", [make_row(match_id="m1")])
    result = load_matches([path_a, path_b], [2024])
    assert len(result.matches) == 1
    assert result.duplicate_rows == 1
    assert result.rows_read == 2
    assert_accounting(result)


def test_conflicting_duplicate_rows_rejected_with_context(tmp_path):
    path = write_season_csv(
        tmp_path / "2024-atp-season.csv",
        [
            make_row(match_id="m1", date_timestamp="100"),
            make_row(match_id="m1", date_timestamp="200"),
        ],
    )
    with pytest.raises(ValueError) as excinfo:
        load_matches([path], [2024])
    message = str(excinfo.value)
    assert "m1" in message
    assert "2024-atp-season.csv" in message
    assert ":2" in message and ":3" in message


def test_identical_duplicate_of_excluded_row_counted_once(tmp_path):
    path = write_season_csv(
        tmp_path / "2024-atp-season.csv",
        [
            make_row(match_id="m1", status_extra="CANCELED"),
            make_row(match_id="m1", status_extra="CANCELED"),
        ],
    )
    result = load_matches([path], [2024])
    assert result.matches == ()
    assert result.excluded_counts == {"canceled": 1}
    assert result.duplicate_rows == 1
    assert result.selected_rows == 2
    assert_accounting(result)


def test_conflicting_duplicate_between_eligible_and_excluded_rejected(tmp_path):
    path = write_season_csv(
        tmp_path / "2024-atp-season.csv",
        [
            make_row(match_id="m1", status_extra="FINISHED"),
            make_row(match_id="m1", status_extra="CANCELED"),
        ],
    )
    with pytest.raises(ValueError, match="m1"):
        load_matches([path], [2024])


# --------------------------------------------------------------------------- #
# load_matches: exclusions and accounting
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"tour_type_human": "ATP Exhib"}, "exhibition"),
        ({"tour_type_human": "WTA Tour"}, "unsupported_tour"),
        ({"status_extra": "WALKOVER"}, "walkover"),
        ({"status_extra": "AWARDED"}, "awarded"),
        ({"status_extra": "CANCELED"}, "canceled"),
        ({"status": "SCHEDULED", "status_extra": "SCHEDULED"}, "scheduled"),
        ({"status_extra": "ABANDONED"}, "unfinished"),
        ({"winner_code": ""}, "invalid_winner"),
        ({"winner_code": "3"}, "invalid_winner"),
    ],
)
def test_exclusion_reasons(tmp_path, overrides, reason):
    path = write_season_csv(tmp_path / "2024-atp-season.csv", [make_row(**overrides)])
    result = load_matches([path], [2024])
    assert result.matches == ()
    assert result.excluded_counts == {reason: 1}
    assert result.selected_rows == 1
    assert_accounting(result)


def test_canceled_wins_over_status_finished(tmp_path):
    path = write_season_csv(
        tmp_path / "2024-atp-season.csv",
        [make_row(status="FINISHED", status_extra="CANCELED")],
    )
    result = load_matches([path], [2024])
    assert result.excluded_counts == {"canceled": 1}
    assert result.matches == ()


def test_blank_status_extra_falls_back_to_status(tmp_path):
    path = write_season_csv(
        tmp_path / "2024-atp-season.csv",
        [
            make_row(match_id="finished", status="FINISHED", status_extra=""),
            make_row(match_id="scheduled", status="SCHEDULED", status_extra=""),
        ],
    )
    result = load_matches([path], [2024])
    assert [match.match_id for match in result.matches] == ["finished"]
    assert result.excluded_counts == {"scheduled": 1}


def test_retirements_included_by_default(tmp_path):
    path = write_season_csv(
        tmp_path / "2024-atp-season.csv",
        [make_row(match_id="ret", status_extra="RETIRED", winner_code="2")],
    )
    result = load_matches([path], [2024])
    assert [match.match_id for match in result.matches] == ["ret"]
    assert result.matches[0].winner_code == 2
    assert result.excluded_counts == {}


def test_retirements_excluded_when_disabled(tmp_path):
    path = write_season_csv(
        tmp_path / "2024-atp-season.csv",
        [make_row(match_id="ret", status_extra="RETIRED", winner_code="2")],
    )
    result = load_matches([path], [2024], include_retirements=False)
    assert result.matches == ()
    assert result.excluded_counts == {"retirement": 1}
    assert_accounting(result)


def test_retired_with_invalid_winner_uses_winner_reason_when_included(tmp_path):
    path = write_season_csv(
        tmp_path / "2024-atp-season.csv",
        [make_row(status_extra="RETIRED", winner_code="")],
    )
    assert load_matches([path], [2024]).excluded_counts == {"invalid_winner": 1}
    assert load_matches([path], [2024], include_retirements=False).excluded_counts == {
        "retirement": 1
    }


def test_include_retirements_is_keyword_only(tmp_path):
    path = write_season_csv(tmp_path / "2024-atp-season.csv", [make_row()])
    with pytest.raises(TypeError):
        load_matches([path], [2024], False)


def test_mixed_fixture_accounting(tmp_path):
    alpha = write_season_csv(
        tmp_path / "alpha-atp-season.csv",
        [
            make_row(match_id="m1"),
            make_row(match_id="m2", status_extra="RETIRED"),
            make_row(match_id="m3", status_extra="CANCELED"),
            make_row(match_id="m4", status_extra="WALKOVER"),
            make_row(match_id="m5", status_extra="AWARDED"),
            make_row(match_id="m6", tour_type_human="ATP Exhib"),
            make_row(match_id="m7", tour_type_human="WTA Tour"),
            make_row(match_id="m8", status="SCHEDULED", status_extra="SCHEDULED"),
            make_row(match_id="m9", winner_code=""),
            make_row(match_id="m10", status_extra="ABANDONED"),
        ],
    )
    beta = write_season_csv(
        tmp_path / "beta-atp-season.csv",
        [
            make_row(match_id="m1"),
            make_row(match_id="m11", season_year="2025"),
            make_row(match_id="m12"),
        ],
    )
    result = load_matches([alpha, beta], [2024])

    assert result.rows_read == 13
    assert result.selected_rows == 12
    assert {match.match_id for match in result.matches} == {"m1", "m2", "m12"}
    assert result.duplicate_rows == 1
    assert result.excluded_counts == {
        "awarded": 1,
        "canceled": 1,
        "exhibition": 1,
        "invalid_winner": 1,
        "scheduled": 1,
        "unfinished": 1,
        "unsupported_tour": 1,
        "walkover": 1,
    }
    assert_accounting(result)

    without_retirements = load_matches([alpha, beta], [2024], include_retirements=False)
    assert len(without_retirements.matches) == 2
    assert without_retirements.excluded_counts["retirement"] == 1
    assert_accounting(without_retirements)


# --------------------------------------------------------------------------- #
# load_matches: malformed schema and eligible rows
# --------------------------------------------------------------------------- #


def test_missing_required_column_mentions_file(tmp_path):
    path = write_season_csv(
        tmp_path / "schema-atp-season.csv",
        [make_row()],
        columns=[column for column in COLUMNS if column != "winner_code"],
    )
    with pytest.raises(ValueError) as excinfo:
        load_matches([path], [2024])
    message = str(excinfo.value)
    assert "schema-atp-season.csv" in message
    assert "winner_code" in message


def test_empty_file_rejected(tmp_path):
    path = tmp_path / "empty-atp-season.csv"
    path.write_text("")
    with pytest.raises(ValueError, match="header"):
        load_matches([path], [2024])


@pytest.mark.parametrize(
    "overrides",
    [
        {"date_timestamp": "not-a-timestamp"},
        {"home_id": ""},
        {"away_id": ""},
        {"away_id": "p1"},
        {"match_id": ""},
    ],
)
def test_malformed_eligible_row_rejected_with_context(tmp_path, overrides):
    path = write_season_csv(tmp_path / "malformed-atp-season.csv", [make_row(**overrides)])
    with pytest.raises(ValueError) as excinfo:
        load_matches([path], [2024])
    message = str(excinfo.value)
    assert "malformed-atp-season.csv" in message
    assert ":2:" in message


@pytest.mark.parametrize(
    "bad_timestamp",
    ["1767320100000", str(10**20), str(-(10**20))],
    ids=["milliseconds", "huge-positive", "huge-negative"],
)
def test_unrepresentable_timestamp_rejected_with_context(tmp_path, bad_timestamp):
    path = write_season_csv(
        tmp_path / "timestamp-atp-season.csv",
        [make_row(date_timestamp=bad_timestamp)],
    )
    with pytest.raises(ValueError) as excinfo:
        load_matches([path], [2024])
    message = str(excinfo.value)
    assert "timestamp-atp-season.csv" in message
    assert ":2:" in message
    assert "date_timestamp" in message


def test_representable_timestamps_accepted(tmp_path):
    path = write_season_csv(
        tmp_path / "epoch-atp-season.csv",
        [
            make_row(match_id="epoch", date_timestamp="0"),
            make_row(match_id="negative", date_timestamp="-1"),
            make_row(match_id="december-season", date_timestamp=DEC_2023, season_year="2024"),
        ],
    )
    result = load_matches([path], [2024])
    assert {match.match_id for match in result.matches} == {"epoch", "negative", "december-season"}
    # No calendar or current-date constraint: a negative representable epoch is kept as-is.
    assert {match.timestamp for match in result.matches} == {0, -1, int(DEC_2023)}
    assert_accounting(result)


def test_malformed_excluded_row_is_not_rejected(tmp_path):
    path = write_season_csv(
        tmp_path / "excluded-atp-season.csv",
        [make_row(status_extra="CANCELED", date_timestamp="not-a-timestamp", home_id="")],
    )
    result = load_matches([path], [2024])
    assert result.excluded_counts == {"canceled": 1}
    assert_accounting(result)


def test_invalid_season_year_value_rejected_with_context(tmp_path):
    path = write_season_csv(tmp_path / "year-atp-season.csv", [make_row(season_year="oops")])
    with pytest.raises(ValueError) as excinfo:
        load_matches([path], [2024])
    message = str(excinfo.value)
    assert "year-atp-season.csv" in message
    assert ":2:" in message


# --------------------------------------------------------------------------- #
# load_matches: CSV parsing details
# --------------------------------------------------------------------------- #


def test_utf8_bom_and_quoted_fields_parsed(tmp_path):
    path = write_season_csv(
        tmp_path / "quoted-atp-season.csv",
        [make_row(match_id="q1", home_name='Player, "One"', tournament="Open, Inc.")],
        encoding="utf-8-sig",
    )
    (match,) = load_matches([path], [2024]).matches
    assert match.home_name == 'Player, "One"'
    assert match.tournament == "Open, Inc."


def test_whitespace_fields_are_stripped(tmp_path):
    path = write_season_csv(
        tmp_path / "space-atp-season.csv",
        [make_row(match_id="  s1  ", home_id=" p1 ", round=" R16 ")],
    )
    (match,) = load_matches([path], [2024]).matches
    assert match.match_id == "s1"
    assert match.home_id == "p1"
    assert match.round == "R16"


# --------------------------------------------------------------------------- #
# Structural CSV integrity (missing/extra fields, malformed quoting)
# --------------------------------------------------------------------------- #


def test_wide_schema_sanity_check():
    assert len(WIDE_COLUMNS) == 49


def test_valid_wide_row_loads(tmp_path):
    path = write_wide_rows(tmp_path / "valid-atp-season.csv", [wide_values()])
    (match,) = load_matches([path], [2024]).matches
    assert match.match_id == "75191598"
    assert match.home_id == "292653"
    assert match.away_id == "956292"
    assert match.winner_code == 2
    assert available_seasons(tmp_path) == (2024,)


def test_missing_closing_quote_48_fields_rejected(tmp_path):
    # An opening quote on `tournament` and a stray closing quote on `round` merge
    # two fields: the row parses as 48 of 49 columns, previously reading "26" as a
    # phantom home/away ID through DictReader's restval=None padding.
    values = wide_values()
    values[6] = '"United Cup ATP'
    values[7] = 'R16"'
    path = write_wide_raw(tmp_path / "missing-quote-atp-season.csv", [",".join(values)])
    assert_both_loaders_reject(tmp_path, path, expect_width=(49, 48))


def test_unquoted_comma_50_fields_rejected(tmp_path):
    values = wide_values()
    values[6] = "United Cup, ATP"
    path = write_wide_raw(tmp_path / "extra-field-atp-season.csv", [",".join(values)])
    assert_both_loaders_reject(tmp_path, path, expect_width=(49, 50))


def test_truncated_finished_row_rejected_not_silently_excluded(tmp_path):
    # Dropping the tail removes winner_code; before this fix it became "" and the
    # finished match was silently counted as invalid_winner.
    values = wide_values()[:20]
    path = write_wide_raw(tmp_path / "truncated-atp-season.csv", [",".join(values)])
    assert_both_loaders_reject(tmp_path, path, expect_width=(49, 20))
    with pytest.raises(ValueError) as excinfo:
        load_matches([path], [2024])
    assert "invalid_winner" not in str(excinfo.value)


def test_unterminated_quote_at_eof_rejected(tmp_path):
    values = wide_values()
    values[-1] = '"unterminated'
    path = write_wide_raw(tmp_path / "unterminated-atp-season.csv", [",".join(values)])
    assert_both_loaders_reject(tmp_path, path)


def test_oversized_quoted_field_rejected(tmp_path):
    values = wide_values()
    values[6] = '"' + ("x" * 140_000) + '"'
    path = write_wide_raw(tmp_path / "oversized-atp-season.csv", [",".join(values)])
    assert_both_loaders_reject(tmp_path, path)


def test_quoted_multiline_field_still_supported(tmp_path):
    path = write_wide_rows(
        tmp_path / "multiline-atp-season.csv",
        [wide_values(tournament="United Cup\nATP", round="R16")],
    )
    (match,) = load_matches([path], [2024]).matches
    assert match.tournament == "United Cup\nATP"
    assert available_seasons(tmp_path) == (2024,)


def test_correct_width_excluded_row_with_bad_timestamp_still_ignored(tmp_path):
    path = write_wide_rows(
        tmp_path / "canceled-wide-atp-season.csv",
        [wide_values(status_extra="CANCELED", date_timestamp="not-a-timestamp")],
    )
    result = load_matches([path], [2024])
    assert result.matches == ()
    assert result.excluded_counts == {"canceled": 1}
    assert_accounting(result)


def test_invalid_utf8_rejected_with_file_context(tmp_path):
    path = tmp_path / "invalid-utf8-atp-season.csv"
    body = (
        ",".join(WIDE_COLUMNS).encode("utf-8")
        + b"\n"
        + ",".join(wide_values()).encode("utf-8")
        + b"\xc3\x28\n"
    )
    path.write_bytes(body)
    for call in (
        lambda: load_matches([path], [2024]),
        lambda: available_seasons(tmp_path),
    ):
        with pytest.raises(ValueError) as excinfo:
            call()
        assert "invalid-utf8-atp-season.csv" in str(excinfo.value)


def test_duplicate_header_rejected(tmp_path):
    header = list(WIDE_COLUMNS)
    header[-1] = "match_id"
    path = tmp_path / "duplicate-header-atp-season.csv"
    path.write_text(",".join(header) + "\n" + ",".join(wide_values()) + "\n", encoding="utf-8")
    with pytest.raises(ValueError) as excinfo:
        load_matches([path], [2024])
    message = str(excinfo.value)
    assert "duplicate" in message
    assert "match_id" in message
