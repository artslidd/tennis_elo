"""Regression tests for the season-aware ATP tournament level catalog.

``tournaments.classify_tournament`` is the only classification source the loader
consults, so these tests pin the approved policy:

* only canonical levels are ever returned;
* the catalog is season-aware (Toronto/Montreal alternation, the 2025
  Dallas/Doha/Munich ATP 500 upgrades, one-season and relocated events);
* the ATP Challenger tour wins over any event or city name, in any season;
* ordinary qualifying inherits its parent category, explicitly including Grand
  Slam qualifying (coefficient 2.0) and excluding US Open WIC;
* team and non-standard events use ``other``;
* unsupported names and unsupported seasons return ``unknown`` instead of being
  guessed as ATP 250;
* only known label decorations are normalized: no fuzzy city substring match.
"""

import ast
import csv
import sys
from pathlib import Path

import pytest

from tennis_elo import tournaments
from tennis_elo.tournaments import classify_tournament
from tennis_elo.weighting import TOURNAMENT_COEFFICIENTS, coefficient_for_level

SEASONS = (2023, 2024, 2025, 2026)
TOUR = "ATP Tour"
CHALLENGER = "ATP Chall"

CANONICAL_LEVELS = frozenset(TOURNAMENT_COEFFICIENTS)

GRAND_SLAMS = ("Australian Open ATP", "French Open ATP", "Wimbledon ATP", "US Open ATP")

MASTERS_1000 = (
    "Indian Wells ATP",
    "Miami ATP",
    "Monte Carlo ATP",
    "Madrid ATP",
    "Rome ATP",
    "Cincinnati ATP",
    "Shanghai ATP",
    "Paris ATP (indoor)",
)

ATP_500_CORE = (
    "Rotterdam ATP (indoor)",
    "Rio de Janeiro ATP",
    "Acapulco ATP",
    "Dubai ATP",
    "Barcelona ATP",
    "Halle ATP",
    "London ATP",
    "Hamburg ATP",
    "Washington ATP",
    "Beijing ATP",
    "Tokyo ATP",
    "Vienna ATP (indoor)",
    "Basel ATP (indoor)",
)


# --------------------------------------------------------------------------- #
# canonical levels and Grand Slams
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("season", SEASONS)
@pytest.mark.parametrize("label", GRAND_SLAMS)
def test_grand_slam_main_draws_are_grand_slams(label, season):
    assert classify_tournament(label, season, TOUR) == "grand_slam"


@pytest.mark.parametrize("season", SEASONS)
@pytest.mark.parametrize(
    "label",
    (
        "Australian Open ATP - Qualification",
        "French Open ATP - Qualification",
        "Wimbledon ATP - Qualification",
        "US Open ATP - Qualification",
    ),
)
def test_grand_slam_qualifying_inherits_the_main_draw_coefficient(label, season):
    level = classify_tournament(label, season, TOUR)
    assert level == "grand_slam"
    assert coefficient_for_level(level) == 2.0


@pytest.mark.parametrize("season", SEASONS)
@pytest.mark.parametrize("label", MASTERS_1000)
def test_masters_1000_events_and_qualifying(label, season):
    assert classify_tournament(label, season, TOUR) == "masters_1000"
    assert classify_tournament(f"{label} - Qualification", season, TOUR) == "masters_1000"


@pytest.mark.parametrize("season", SEASONS)
@pytest.mark.parametrize("label", ATP_500_CORE)
def test_atp_500_core_events_are_500_in_every_supplied_season(label, season):
    assert classify_tournament(label, season, TOUR) == "atp_500"


@pytest.mark.parametrize("season", SEASONS)
def test_every_canonical_level_has_a_coefficient(season):
    for label in (*GRAND_SLAMS, *MASTERS_1000, *ATP_500_CORE, "Finals - Turin ATP (indoor)"):
        assert classify_tournament(label, season, TOUR) in CANONICAL_LEVELS


# --------------------------------------------------------------------------- #
# season awareness: upgrades, alternation, relocations, one-season events
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("season", "expected"),
    [(2023, "atp_250"), (2024, "atp_250"), (2025, "atp_500"), (2026, "atp_500")],
)
@pytest.mark.parametrize(
    "label",
    ("Dallas ATP (indoor)", "Doha ATP", "Munich ATP"),
)
def test_dallas_doha_munich_were_upgraded_to_atp_500_from_2025(label, season, expected):
    assert classify_tournament(label, season, TOUR) == expected
    assert classify_tournament(f"{label} - Qualification", season, TOUR) == expected


@pytest.mark.parametrize(
    ("season", "expected"),
    [
        (2023, "masters_1000"),
        (2024, "unknown"),
        (2025, "masters_1000"),
        (2026, "unknown"),
    ],
)
def test_toronto_is_masters_only_in_its_seasons(season, expected):
    assert classify_tournament("Toronto ATP", season, TOUR) == expected
    assert classify_tournament("Toronto ATP - Qualification", season, TOUR) == expected


@pytest.mark.parametrize(
    ("season", "expected"),
    [
        (2023, "unknown"),
        (2024, "masters_1000"),
        (2025, "unknown"),
        (2026, "masters_1000"),
    ],
)
def test_montreal_is_masters_only_in_its_seasons(season, expected):
    assert classify_tournament("Montreal ATP", season, TOUR) == expected


@pytest.mark.parametrize(
    ("label", "season", "expected"),
    [
        # 2025 Antwerp -> Brussels, 2025 Belgrade -> Athens relocations.
        ("Antwerp ATP (indoor)", 2024, "atp_250"),
        ("Antwerp ATP (indoor)", 2025, "unknown"),
        ("Brussels ATP (indoor)", 2025, "atp_250"),
        ("Brussels ATP (indoor)", 2026, "atp_250"),
        ("Athens ATP (indoor)", 2025, "atp_250"),
        ("Athens ATP (indoor)", 2026, "unknown"),
        # 2026 Marseille -> Lyon (indoor, October) relocation; Metz dropped.
        ("Marseille ATP (indoor)", 2025, "atp_250"),
        ("Marseille ATP (indoor)", 2026, "unknown"),
        ("Metz ATP (indoor)", 2025, "atp_250"),
        ("Metz ATP (indoor)", 2026, "unknown"),
        ("Lyon ATP", 2023, "atp_250"),
        ("Lyon ATP", 2024, "atp_250"),
        ("Lyon ATP (indoor)", 2026, "atp_250"),
        # 2024 Astana -> Almaty relocation, 2023-only and 2024-only events.
        ("Astana ATP (indoor)", 2023, "atp_250"),
        ("Astana ATP (indoor)", 2024, "unknown"),
        ("Almaty ATP (indoor)", 2024, "atp_250"),
        ("Almaty ATP (indoor)", 2026, "atp_250"),
        ("Adelaide 2 ATP", 2023, "atp_250"),
        ("Adelaide 2 ATP", 2024, "unknown"),
        ("Belgrade 2 ATP (indoor)", 2024, "atp_250"),
        ("Belgrade 2 ATP (indoor)", 2025, "unknown"),
        ("Banja Luka ATP", 2023, "atp_250"),
        ("Pune ATP", 2023, "atp_250"),
        ("Pune ATP", 2024, "unknown"),
        ("Sofia ATP (indoor)", 2023, "atp_250"),
        ("Sofia ATP (indoor)", 2024, "unknown"),
        ("Zhuhai ATP", 2023, "atp_250"),
        ("Zhuhai ATP", 2024, "unknown"),
        ("Cordoba ATP", 2024, "atp_250"),
        ("Cordoba ATP", 2025, "unknown"),
        ("Atlanta ATP", 2024, "atp_250"),
        ("Atlanta ATP", 2025, "unknown"),
        ("Newport ATP", 2024, "atp_250"),
        ("Newport ATP", 2025, "unknown"),
        ("Estoril ATP", 2024, "atp_250"),
        ("Estoril ATP", 2025, "unknown"),
        ("Estoril ATP", 2026, "atp_250"),
        ("Chengdu ATP", 2023, "atp_250"),
        ("Hangzhou ATP", 2023, "unknown"),
        ("Hangzhou ATP", 2024, "atp_250"),
        ("Hangzhou ATP", 2026, "atp_250"),
        ("Hong Kong ATP", 2024, "atp_250"),
        ("Hong Kong ATP", 2026, "atp_250"),
        ("Brisbane ATP", 2023, "unknown"),
        ("Brisbane ATP", 2025, "atp_250"),
        ("Bucharest ATP", 2024, "atp_250"),
        ("Bucharest ATP", 2026, "atp_250"),
    ],
)
def test_season_specific_atp_250_catalog(label, season, expected):
    assert classify_tournament(label, season, TOUR) == expected


@pytest.mark.parametrize(
    "label",
    (
        "Adelaide ATP",
        "Auckland ATP",
        "Bastad ATP",
        "Buenos Aires ATP",
        "Delray Beach ATP",
        "Eastbourne ATP",
        "Geneva ATP",
        "Gstaad ATP",
        "Hertogenbosch ATP",
        "Houston ATP",
        "Kitzbuhel ATP",
        "Los Cabos ATP",
        "Mallorca ATP",
        "Marrakech ATP",
        "Montpellier ATP (indoor)",
        "Santiago ATP",
        "Stockholm ATP (indoor)",
        "Stuttgart ATP",
        "Umag ATP",
        "Winston-Salem ATP",
    ),
)
def test_atp_250_events_present_in_every_supplied_season(label):
    assert {classify_tournament(label, season, TOUR) for season in SEASONS} == {"atp_250"}


# --------------------------------------------------------------------------- #
# finals, Next Gen Finals, and other team / non-standard events
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("season", SEASONS)
@pytest.mark.parametrize(
    "label", ("Finals - Turin ATP (indoor)", "Finals - Turin ATP - Play Offs (indoor)")
)
def test_atp_finals_aliases_are_atp_finals(label, season):
    assert classify_tournament(label, season, TOUR) == "atp_finals"


@pytest.mark.parametrize(
    ("season", "expected"), [(2023, "other"), (2024, "other"), (2025, "other")]
)
@pytest.mark.parametrize(
    "label",
    ("Next Gen Finals - Jeddah ATP (indoor)", "Next Gen Finals - Jeddah ATP - Play Offs (indoor)"),
)
def test_next_gen_finals_are_other_and_never_atp_finals(label, season, expected):
    assert classify_tournament(label, season, TOUR) == expected


@pytest.mark.parametrize(
    ("label", "season"), [("Turin ATP (indoor)", 2025), ("Riyadh Finals ATP", 2025)]
)
def test_no_broad_substring_match_on_finals(label, season):
    assert classify_tournament(label, season, TOUR) == "unknown"


@pytest.mark.parametrize(
    ("label", "season"),
    [
        ("United Cup ATP", 2026),
        ("United Cup ATP - Play Offs", 2024),
        ("Davis Cup - World Group ATP", 2023),
        ("Davis Cup - World Group ATP - Play Offs", 2023),
        ("Davis Cup - World Group ATP - Qualification", 2025),
        ("Davis Cup - World Group I ATP", 2026),
        ("Davis Cup - World Group II ATP - Preliminary", 2026),
        ("Hopman Cup ATP", 2023),
        ("Hopman Cup ATP", 2025),
        ("Laver Cup ATP (indoor)", 2026),
        ("Olympic Games ATP", 2024),
        ("Asian Games ATP (indoor)", 2023),
    ],
)
def test_team_and_nonstandard_events_are_other(label, season):
    assert classify_tournament(label, season, TOUR) == "other"
    assert coefficient_for_level("other") == 1.0


def test_exhibition_tour_is_other():
    level = classify_tournament("Six Kings Slam Exhibition Men (indoor)", 2024, "ATP Exhib")
    assert level == "other"


def test_us_open_wic_is_other_and_not_grand_slam_qualifying():
    assert classify_tournament("US Open ATP - WIC", 2026, TOUR) == "other"
    assert classify_tournament("US Open ATP - Qualification", 2026, TOUR) == "grand_slam"


# --------------------------------------------------------------------------- #
# Challenger precedence
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("label", "season", "tour", "expected"),
    [
        ("Hamburg Chall. Men", 2023, CHALLENGER, "challenger"),
        ("Hamburg Chall. Men - Qualification (indoor)", 2026, CHALLENGER, "challenger"),
        ("Athens 2 Chall. Men", 2025, CHALLENGER, "challenger"),
        ("Lyon Chall. Men (indoor)", 2026, CHALLENGER, "challenger"),
        ("Montreal Chall. Men", 2024, CHALLENGER, "challenger"),
        ("Next Gen Finals - Jeddah Chall. Men", 2024, CHALLENGER, "challenger"),
        ("Nowhere Chall. Men", 2022, CHALLENGER, "challenger"),
        ("Rotterdam Chall. Men", 2027, CHALLENGER, "challenger"),
        ("Wimbledon Chall. Men", 2024, "ATP Challenger", "challenger"),
        ("Dallas Chall. Men (indoor)", 2024, "atp chall", "challenger"),
    ],
)
def test_challenger_tour_wins_over_event_name_and_is_year_agnostic(label, season, tour, expected):
    assert classify_tournament(label, season, tour) == expected


def test_challenger_and_tour_events_coexist_in_the_same_season():
    assert classify_tournament("Athens ATP (indoor)", 2025, TOUR) == "atp_250"
    assert classify_tournament("Athens 2 Chall. Men", 2025, CHALLENGER) == "challenger"
    assert classify_tournament("Hamburg ATP", 2023, TOUR) == "atp_500"
    assert classify_tournament("Hamburg Chall. Men", 2023, CHALLENGER) == "challenger"


# --------------------------------------------------------------------------- #
# unknowns and normalization
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("label", "season", "tour"),
    [
        ("Fictional City ATP", 2024, TOUR),
        ("Rotterdam ATP", 2022, TOUR),
        ("Rotterdam ATP", 2027, TOUR),
        ("Davis Cup - World Group ATP", 2027, TOUR),
        ("", 2024, TOUR),
        ("   ", 2024, TOUR),
        ("Qualification", 2024, TOUR),
        ("indoor", 2024, TOUR),
        ("Test Open", 2024, TOUR),
    ],
)
def test_unsupported_names_and_seasons_are_unknown(label, season, tour):
    level = classify_tournament(label, season, tour)
    assert level == "unknown"
    assert coefficient_for_level(level) == 1.0


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("  wimbledon atp  ", "grand_slam"),
        ("WIMBLEDON ATP - QUALIFICATION", "grand_slam"),
        ("Wimbledon  ATP", "grand_slam"),
        ("Dallas ATP  (indoor)", "atp_250"),
        ("Doha ATP - qualification", "atp_250"),
        ("Finals - Turin ATP - play offs (indoor)", "atp_finals"),
    ],
)
def test_known_decorations_and_case_are_normalized(label, expected):
    assert classify_tournament(label, 2024, TOUR) == expected


def test_normalization_does_not_strip_unknown_suffixes():
    assert classify_tournament("Wimbledon ATP - Super Tiebreak", 2024, TOUR) == "unknown"
    assert classify_tournament("Wimbledon ATP - Finals", 2024, TOUR) == "unknown"


def test_missing_tournament_label_is_a_valid_unknown_for_the_loader_contract():
    assert classify_tournament("", 2026, TOUR) == "unknown"


# --------------------------------------------------------------------------- #
# module-level invariants
# --------------------------------------------------------------------------- #


def test_every_canonical_level_is_reachable_from_a_documented_label():
    probes = {
        "challenger": ("Hamburg Chall. Men", 2024, CHALLENGER),
        "atp_250": ("Montpellier ATP (indoor)", 2024, TOUR),
        "atp_500": ("Halle ATP", 2024, TOUR),
        "masters_1000": ("Miami ATP", 2024, TOUR),
        "atp_finals": ("Finals - Turin ATP (indoor)", 2024, TOUR),
        "grand_slam": ("Wimbledon ATP", 2024, TOUR),
        "other": ("Laver Cup ATP (indoor)", 2024, TOUR),
        "unknown": ("Fictional City ATP", 2024, TOUR),
    }
    assert set(probes) == CANONICAL_LEVELS
    for level, (label, season, tour) in probes.items():
        assert classify_tournament(label, season, tour) == level


def test_classification_is_deterministic():
    first = classify_tournament("Munich ATP - Qualification", 2025, TOUR)
    second = classify_tournament("Munich ATP - Qualification", 2025, TOUR)
    assert first == second == "atp_500"


def test_classifier_imports_only_standard_library_modules():
    tree = ast.parse(Path(tournaments.__file__).read_text(encoding="utf-8"))
    third_party = {
        "requests",
        "socket",
        "urllib",
        "http",
        "httpx",
        "pandas",
        "streamlit",
    }
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            imported.add(node.module.split(".")[0])
    assert imported <= set(sys.stdlib_module_names)
    assert imported.isdisjoint(third_party)


# --------------------------------------------------------------------------- #
# real supplied input audit (tracked 2024-2026 CSVs in the repository root)
# --------------------------------------------------------------------------- #


def test_supplied_season_labels_classify_without_unknowns():
    files = sorted(Path(__file__).resolve().parents[1].glob("*-atp-season.csv"))
    if not files:
        pytest.skip("no supplied season CSVs in this checkout")

    unknown = set()
    checked = 0
    for path in files:
        with path.open(newline="", encoding="utf-8-sig") as handle:
            for row in csv.DictReader(handle):
                level = classify_tournament(
                    row["tournament"], int(row["season_year"]), row["tour_type_human"]
                )
                assert level in CANONICAL_LEVELS
                checked += 1
                if level == "unknown":
                    unknown.add((row["season_year"], row["tournament"]))

    assert checked > 0
    assert unknown == set()
