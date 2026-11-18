"""Bundled, season-aware ATP tournament level catalog.

The season CSVs carry no category column, so this module is the deterministic,
dependency-free, offline classification source the loader consults. It returns
only the canonical level keys of :data:`tennis_elo.weighting.TOURNAMENT_COEFFICIENTS`.

Policy (approved in ``docs/superpowers/specs/2026-11-18-tournament-weighting.md``
and documented in ``docs/tournament-levels.md``):

* The ATP Challenger tour is a tour-level fact, so it wins over every event or
  city name and does not depend on the season.
* Ordinary qualifying, play-offs and preliminary rounds inherit their parent
  event's category. Grand Slam qualifying therefore also weighs 2.00, while the
  US Open ``WIC`` event is ``other`` and is checked before any normalization.
* Only the known label decorations are normalized: a trailing ``ATP`` marker,
  ``- Qualification``, ``- Play Offs``, ``- Preliminary`` and ``(indoor)``.
  There is no fuzzy city or substring matching.
* Team and non-standard events (United Cup, Davis Cup including World Group I/II
  and Preliminary, Hopman Cup, Laver Cup, Olympic Games, Asian Games, Next Gen
  Finals, US Open WIC, exhibition tours) use ``other``.
* Events that were not held in a season, and seasons outside the bundled
  2023-2026 calendar, use ``unknown``. The classifier never falls back to
  ``atp_250``.

Additions are maintenance work: add the event to the table below for the seasons
it was actually held at that level, with a public ATP calendar or media-guide
citation in ``docs/tournament-levels.md``.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from types import MappingProxyType
from typing import Final

_SUPPORTED_SEASONS: Final = (2023, 2024, 2025, 2026)
_ALL_SEASONS: Final = frozenset(_SUPPORTED_SEASONS)

_GRAND_SLAM: Final = "grand_slam"
_MASTERS_1000: Final = "masters_1000"
_ATP_500: Final = "atp_500"
_ATP_250: Final = "atp_250"
_ATP_FINALS: Final = "atp_finals"
_OTHER: Final = "other"
_CHALLENGER: Final = "challenger"
_UNKNOWN: Final = "unknown"

# Shortest sound prefix of a normalized label. Decorations were already removed.
_GRAND_SLAMS: Final = frozenset({"Australian Open", "French Open", "Wimbledon", "US Open"})

_MASTERS_1000_IN_ALL_SEASONS: Final = frozenset(
    {
        "Indian Wells",
        "Miami",
        "Monte Carlo",
        "Madrid",
        "Rome",
        "Cincinnati",
        "Shanghai",
        "Paris",
    }
)

# The North American Masters 1000 alternates between the two cities.
_MASTERS_1000_BY_SEASON: Final[Mapping[str, frozenset[int]]] = {
    "Toronto": frozenset({2023, 2025}),
    "Montreal": frozenset({2024, 2026}),
}

_ATP_500_IN_ALL_SEASONS: Final = frozenset(
    {
        "Rotterdam",
        "Rio de Janeiro",
        "Acapulco",
        "Dubai",
        "Barcelona",
        "Halle",
        "London",
        "Hamburg",
        "Washington",
        "Beijing",
        "Tokyo",
        "Vienna",
        "Basel",
    }
)

# Dallas, Doha and Munich were upgraded from ATP 250 to ATP 500 for 2025.
_ATP_500_BY_SEASON: Final[Mapping[str, frozenset[int]]] = {
    "Dallas": frozenset({2025, 2026}),
    "Doha": frozenset({2025, 2026}),
    "Munich": frozenset({2025, 2026}),
}

_ATP_250_IN_ALL_SEASONS: Final = frozenset(
    {
        "Adelaide",
        "Auckland",
        "Bastad",
        "Buenos Aires",
        "Chengdu",
        "Delray Beach",
        "Eastbourne",
        "Geneva",
        "Gstaad",
        "Hertogenbosch",
        "Houston",
        "Kitzbuhel",
        "Los Cabos",
        "Mallorca",
        "Marrakech",
        "Montpellier",
        "Santiago",
        "Stockholm",
        "Stuttgart",
        "Umag",
        "Winston-Salem",
    }
)

_ATP_250_BY_SEASON: Final[Mapping[str, frozenset[int]]] = {
    "Adelaide 2": frozenset({2023}),
    "Almaty": frozenset({2024, 2025, 2026}),
    "Antwerp": frozenset({2023, 2024}),
    "Astana": frozenset({2023}),
    "Athens": frozenset({2025}),
    "Atlanta": frozenset({2023, 2024}),
    "Banja Luka": frozenset({2023}),
    "Belgrade 2": frozenset({2024}),
    "Brisbane": frozenset({2024, 2025, 2026}),
    "Brussels": frozenset({2025, 2026}),
    "Bucharest": frozenset({2024, 2025, 2026}),
    "Cordoba": frozenset({2023, 2024}),
    "Dallas": frozenset({2023, 2024}),
    "Doha": frozenset({2023, 2024}),
    "Estoril": frozenset({2023, 2024, 2026}),
    "Hangzhou": frozenset({2024, 2025, 2026}),
    "Hong Kong": frozenset({2024, 2025, 2026}),
    "Lyon": frozenset({2023, 2024, 2026}),
    "Marseille": frozenset({2023, 2024, 2025}),
    "Metz": frozenset({2023, 2024, 2025}),
    "Munich": frozenset({2023, 2024}),
    "Newport": frozenset({2023, 2024}),
    "Pune": frozenset({2023}),
    "Sofia": frozenset({2023}),
    "Zhuhai": frozenset({2023}),
}

_ATP_FINALS_EVENTS: Final = frozenset({"Finals - Turin"})

_OTHER_IN_ALL_SEASONS: Final = frozenset({"Laver Cup", "United Cup"})

_OTHER_BY_SEASON: Final[Mapping[str, frozenset[int]]] = {
    "Asian Games": frozenset({2023}),
    "Hopman Cup": frozenset({2023, 2025}),
    "Next Gen Finals - Jeddah": frozenset({2023, 2024, 2025}),
    "Olympic Games": frozenset({2024}),
    "Six Kings Slam Exhibition Men": frozenset({2024}),
}

# Davis Cup is a team competition; labels are "Davis Cup - World Group ...",
# "Davis Cup - World Group I/II ..." and include Qualification/Play Offs/Preliminary.
_OTHER_NAME_PREFIXES: Final = ("davis cup",)

_INDOOR_DECORATION: Final = re.compile(r"\(indoor\)", re.IGNORECASE)
_PARENT_CATEGORY_DECORATIONS: Final = frozenset({"qualification", "play offs", "preliminary"})
_LABEL_SEPARATOR: Final = " - "
_ASSOCIATION_SUFFIX: Final = " atp"
_WIC_TOKEN: Final = "wic"


def _build_catalog() -> Mapping[int, Mapping[str, str]]:
    per_season: dict[int, dict[str, str]] = {season: {} for season in _SUPPORTED_SEASONS}

    def add(level: str, name: str, seasons: frozenset[int]) -> None:
        for season in seasons:
            per_season[season][name.casefold()] = level

    for name in _GRAND_SLAMS:
        add(_GRAND_SLAM, name, _ALL_SEASONS)
    for name in _MASTERS_1000_IN_ALL_SEASONS:
        add(_MASTERS_1000, name, _ALL_SEASONS)
    for name, seasons in _MASTERS_1000_BY_SEASON.items():
        add(_MASTERS_1000, name, seasons)
    for name, seasons in _ATP_500_BY_SEASON.items():
        add(_ATP_500, name, seasons)
    for name in _ATP_500_IN_ALL_SEASONS:
        add(_ATP_500, name, _ALL_SEASONS)
    for name in _ATP_250_IN_ALL_SEASONS:
        add(_ATP_250, name, _ALL_SEASONS)
    for name, seasons in _ATP_250_BY_SEASON.items():
        add(_ATP_250, name, seasons)
    for name in _ATP_FINALS_EVENTS:
        add(_ATP_FINALS, name, _ALL_SEASONS)
    for name in _OTHER_IN_ALL_SEASONS:
        add(_OTHER, name, _ALL_SEASONS)
    for name, seasons in _OTHER_BY_SEASON.items():
        add(_OTHER, name, seasons)

    return MappingProxyType(
        {
            season: MappingProxyType(dict(sorted(per_season[season].items())))
            for season in _SUPPORTED_SEASONS
        }
    )


_CATALOG_BY_SEASON: Final[Mapping[int, Mapping[str, str]]] = _build_catalog()


def classify_tournament(tournament: str, season_year: int, tour_type_human: str) -> str:
    """Return the canonical tournament level for one season CSV row.

    ``tour_type_human`` decides Challenger and exhibition rows on its own;
    ``tournament`` and ``season_year`` then select the catalogued level. Any
    label or season the bundled calendar does not cover is ``unknown``.
    """
    tour = tour_type_human.strip().casefold()
    if "chall" in tour:
        return _CHALLENGER
    if "exhib" in tour:
        return _OTHER

    catalog = _CATALOG_BY_SEASON.get(season_year)
    if catalog is None:
        return _UNKNOWN

    if _WIC_TOKEN in {token.casefold() for token in tournament.split()}:
        return _OTHER

    name = _base_event_name(tournament)
    if not name:
        return _UNKNOWN
    if name.startswith(_OTHER_NAME_PREFIXES):
        return _OTHER
    return catalog.get(name, _UNKNOWN)


def _base_event_name(tournament: str) -> str:
    """Strip only the known label decorations and return a casefolded lookup key."""
    label = _INDOOR_DECORATION.sub(" ", tournament)
    segments = [segment.strip() for segment in label.split(_LABEL_SEPARATOR)]
    while len(segments) > 1 and segments[-1].casefold() in _PARENT_CATEGORY_DECORATIONS:
        segments.pop()
    label = _LABEL_SEPARATOR.join(segments).strip()
    if label.casefold().endswith(_ASSOCIATION_SUFFIX):
        label = label[: -len(_ASSOCIATION_SUFFIX)]
    return " ".join(label.split()).casefold()
