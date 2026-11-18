"""Pure presentation helpers for the optional Tennis Elo Streamlit dashboard.

This module intentionally imports neither Streamlit nor pandas: it only uses the
shared immutable contracts from :mod:`tennis_elo.models` plus the standard
library. The dashboard renders with it, and tests can exercise the presentation
rules (searching, sorting, season-window availability, text safety) without a
web runtime.

Ratings, matches and exports stay owned by the P0 modules (``tennis_elo.api``
and ``tennis_elo.export``); nothing here recomputes Elo or reloads CSVs.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from math import isfinite
from types import MappingProxyType
from typing import Any

from .models import CalculationResult, LoadResult, RatingConfig
from .weighting import TOURNAMENT_COEFFICIENTS

__all__ = [
    "CLASSIFICATION_COLUMNS",
    "COEFFICIENT_COLUMNS",
    "COMPARISON_COLUMNS",
    "DATA_DIR_ENV",
    "DEFAULT_INITIAL_RATING",
    "DEFAULT_K_FACTOR",
    "FRESH_START_NOTICE",
    "HISTORY_COLUMNS",
    "LEADERBOARD_COLUMNS",
    "MAX_TOP_PLAYERS",
    "MISSING_DASHBOARD_DEPENDENCIES",
    "PLAYER_COMPARISON_COLUMNS",
    "TOP_PLAYERS_CHART_LIMIT",
    "TOP_PLAYERS_ENV",
    "UNKNOWN_TOURNAMENT_COLUMNS",
    "WEIGHTING_POLICY_NOTE",
    "WINDOW_SIZES",
    "LoadAccounting",
    "PlayerOption",
    "SeasonWindow",
    "WeightingReport",
    "build_player_options",
    "build_rating_config",
    "coefficient_rows",
    "comparison_entry",
    "comparison_rows",
    "control_error",
    "display_ranking_rows",
    "elo_chart_rows",
    "error_message",
    "escape_markdown",
    "exclusion_rows",
    "filter_player_options",
    "filter_ranking_rows",
    "load_accounting",
    "merge_player_rows",
    "plain_text",
    "player_comparison_rows",
    "player_history_rows",
    "player_option_label",
    "player_stat_rows",
    "raw_player_id",
    "run_metadata_rows",
    "safe_download_filename",
    "safe_label",
    "season_selection_problem",
    "season_window",
    "season_window_plan",
    "sort_ranking_rows",
    "timestamp_to_datetime_utc",
    "timestamp_to_iso_date",
    "top_players_chart_rows",
    "top_players_limit",
    "tournament_weighting_report",
    "weighting_mode_notice",
    "window_label",
    "window_plans",
]

DEFAULT_INITIAL_RATING = 1500.0
DEFAULT_K_FACTOR = 32.0
WINDOW_SIZES: tuple[int, ...] = (1, 2, 3)
TOP_PLAYERS_CHART_LIMIT = 20  # default number of players in the top-players chart
MAX_TOP_PLAYERS = 50
# Set by ``tennis-elo-dashboard --top-players N``; also usable directly.
TOP_PLAYERS_ENV = "TENNIS_ELO_TOP_PLAYERS"
# Hosted deployments set this to pin the data directory: the free-text directory
# input is then hidden, so visitors cannot point the server at other folders.
DATA_DIR_ENV = "TENNIS_ELO_DATA_DIR"

LEADERBOARD_COLUMNS: tuple[str, ...] = (
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
HISTORY_COLUMNS: tuple[str, ...] = (
    "date",
    "match_id",
    "season_year",
    "tournament",
    "tournament_level",
    "tournament_weight",
    "effective_k_factor",
    "surface",
    "opponent",
    "won",
    "rating_before",
    "opponent_rating_before",
    "expected_score",
    "rating_after",
)
PLAYER_COMPARISON_COLUMNS: tuple[str, ...] = (
    "window",
    "seasons",
    "status",
    "player",
    "rating",
    "rank",
    "matches",
    "wins",
    "losses",
    "note",
)
COMPARISON_COLUMNS: tuple[str, ...] = (
    "window",
    "seasons",
    "status",
    "players_rated",
    "matches_processed",
    "top_player",
    "top_rating",
    "note",
)
COEFFICIENT_COLUMNS: tuple[str, ...] = ("level", "coefficient")
CLASSIFICATION_COLUMNS: tuple[str, ...] = ("level", "matches")
UNKNOWN_TOURNAMENT_COLUMNS: tuple[str, ...] = ("season_year", "tournament", "matches")

# Human-readable tier names for the fixed canonical levels, in the operator's
# approved order (ascending coefficient, with the two 1.00 fallbacks last).
LEVEL_LABELS: Mapping[str, str] = MappingProxyType(
    {
        "challenger": "Challenger",
        "atp_250": "ATP 250",
        "atp_500": "ATP 500",
        "masters_1000": "Masters 1000",
        "atp_finals": "ATP Finals",
        "grand_slam": "Grand Slam",
        "other": "Other (team or nonstandard)",
        "unknown": "Unknown (fallback)",
    }
)

WEIGHTING_POLICY_NOTE = (
    "Operator-selected policy: the coefficient multiplies the BASE K-factor for both "
    "players (effective K = base K x coefficient); ratings and probabilities are never "
    "scaled. Qualifying inherits its parent tournament's category, so Grand Slam "
    "qualifying also uses 2.00. Team and nonstandard events (United Cup, Davis Cup, "
    "Laver Cup, Olympics, Next Gen Finals) use other = 1.00. Labels that cannot be "
    "classified use the explicit unknown fallback 1.00 and are reported here instead "
    "of being silently treated as ATP 250."
)

FRESH_START_NOTICE = (
    "Fresh start: each calculation starts every player at the configured initial rating "
    "(1500 by default) and replays only its selected seasons. Within one calculation, "
    "ratings carry from season to season in chronological order; between separate "
    "calculations nothing carries over, so independent window comparisons each start over "
    "from the initial rating. These are not continuous annual Elo changes."
)

MISSING_DASHBOARD_DEPENDENCIES = (
    "Streamlit and pandas are optional dashboard dependencies. Install them with "
    "`uv sync --extra dashboard`, then run `uv run --extra dashboard tennis-elo-dashboard`."
)

MISSING_PACKAGE_MODULE = (
    "The tennis_elo package is missing one of its runtime modules ({name}). "
    "Run `uv sync` in the project directory and try again."
)

_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")
_BIDI_AND_ZERO_WIDTH = re.compile("[\u200b-\u200f\u202a-\u202e\u2060-\u2064\u2066-\u2069\ufeff]")
_MARKDOWN_SPECIALS = "\\`*_{}[]()#+-.!|~<>"
_MISSING_MODULE = re.compile(r"No module named '([^']+)'")
_UNSAFE_FILENAME_CHARS = re.compile(r"[^A-Za-z0-9._-]+")
_DASH_RUN = re.compile(r"-{2,}")


# --------------------------------------------------------------------------- #
# Text safety
# --------------------------------------------------------------------------- #


def plain_text(value: Any) -> str:
    """Return ``value`` as single-line text without control or bidi characters."""
    if value is None:
        return ""
    text = _CONTROL_CHARS.sub(" ", str(value))
    text = _BIDI_AND_ZERO_WIDTH.sub("", text)
    return re.sub(r"\s+", " ", text).strip()


def safe_label(value: Any) -> str:
    """Return text that is safe inside plain widgets (no angle brackets)."""
    text = plain_text(value)
    return re.sub(r"\s+", " ", text.replace("<", "").replace(">", "")).strip()


def escape_markdown(value: Any) -> str:
    """Escape CSV-derived text before it is interpolated into Markdown."""
    text = plain_text(value)
    prefix = "\\"
    return "".join(prefix + char if char in _MARKDOWN_SPECIALS else char for char in text)


def safe_download_filename(value: Any, *, fallback: str = "tennis-elo.csv") -> str:
    """Build a conservative download file name from user/CSV-derived text."""
    text = plain_text(value)
    cleaned = _UNSAFE_FILENAME_CHARS.sub("-", text).strip("-._")
    cleaned = _DASH_RUN.sub("-", cleaned)
    if not cleaned:
        return fallback
    if cleaned.lower() in {".csv", "csv"}:
        return fallback
    if len(cleaned) > 80:
        cleaned = cleaned[:80].strip("-._") or fallback
    return cleaned


# --------------------------------------------------------------------------- #
# Leaderboard helpers
# --------------------------------------------------------------------------- #


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) else None


def _search_haystack(row: Mapping[str, Any]) -> str:
    return safe_label(f"{row.get('name', '')} {row.get('player_id', '')}").casefold()


def filter_ranking_rows(
    rows: Iterable[Mapping[str, Any]],
    *,
    query: str = "",
    min_matches: int = 0,
) -> tuple[dict[str, Any], ...]:
    """Search/minimum-match filtering for the leaderboard (presentation only).

    ``min_matches`` never changes Elo updates; it only decides which rows the
    leaderboard shows.
    """
    needle = safe_label(query).casefold()
    floor = max(0, _as_int(min_matches))
    selected: list[dict[str, Any]] = []
    for row in rows:
        if _as_int(row.get("matches")) < floor:
            continue
        if needle and needle not in _search_haystack(row):
            continue
        selected.append(dict(row))
    return tuple(selected)


def _sort_key(value: Any) -> tuple[int, float, str]:
    if isinstance(value, bool):
        return (1, float(value), "")
    if isinstance(value, (int, float)):
        return (0, float(value), "")
    return (1, 0.0, safe_label(value).casefold())


def sort_ranking_rows(
    rows: Iterable[Mapping[str, Any]],
    *,
    column: str = "rank",
    descending: bool = False,
) -> tuple[dict[str, Any], ...]:
    """Sort leaderboard rows by ``column``, keeping the incoming order for ties."""
    ordered = sorted(rows, key=lambda row: _sort_key(row.get(column)), reverse=descending)
    return tuple(dict(row) for row in ordered)


def display_ranking_rows(rows: Iterable[Mapping[str, Any]]) -> tuple[dict[str, Any], ...]:
    """Copy rows for display: Elo rounded to one decimal, text made safe."""
    displayed: list[dict[str, Any]] = []
    for row in rows:
        copy = dict(row)
        rating = _as_float(copy.get("rating"))
        if rating is not None:
            copy["rating"] = round(rating, 1)
        if "name" in copy:
            copy["name"] = safe_label(copy["name"])
        if "player_id" in copy:
            copy["player_id"] = safe_label(copy["player_id"])
        displayed.append(copy)
    return tuple(displayed)


# --------------------------------------------------------------------------- #
# Player selector
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class PlayerOption:
    """One selectable player.

    ``player_id`` is the raw, stable identity the API uses (never a display label);
    ``name`` and ``label`` are display-safe copies.
    """

    player_id: str
    name: str
    label: str


def raw_player_id(value: Any) -> str:
    """Return the raw player identity used for selection and lookups."""
    if value is None:
        return ""
    return str(value).strip()


def player_option_label(name: Any, player_id: Any) -> str:
    """Return the selector label: latest observed name plus the stable ID."""
    clean_name = safe_label(name) or "Unknown player"
    clean_id = safe_label(player_id) or "unknown-id"
    return f"{clean_name} ({clean_id})"


def build_player_options(rows: Iterable[Mapping[str, Any]]) -> tuple[PlayerOption, ...]:
    """Build ID-keyed player options, skipping blank or repeated IDs."""
    options: list[PlayerOption] = []
    seen: set[str] = set()
    for row in rows:
        player_id = raw_player_id(row.get("player_id"))
        if not player_id or player_id in seen:
            continue
        seen.add(player_id)
        name = safe_label(row.get("name"))
        options.append(
            PlayerOption(player_id=player_id, name=name, label=player_option_label(name, player_id))
        )
    return tuple(options)


def merge_player_rows(
    row_groups: Sequence[Iterable[Mapping[str, Any]]],
) -> tuple[dict[str, Any], ...]:
    """Union ranking rows across windows, in priority order (nearest window first)."""
    merged: dict[str, dict[str, Any]] = {}
    for rows in row_groups:
        for row in rows:
            player_id = raw_player_id(row.get("player_id"))
            if not player_id or player_id in merged:
                continue
            copy = dict(row)
            copy["player_id"] = player_id
            merged[player_id] = copy
    return tuple(merged.values())


def filter_player_options(
    options: Iterable[PlayerOption], query: str = ""
) -> tuple[PlayerOption, ...]:
    """Narrow player options by name or player ID."""
    needle = safe_label(query).casefold()
    if not needle:
        return tuple(options)
    return tuple(
        option
        for option in options
        if needle in option.label.casefold() or needle in option.player_id.casefold()
    )


def player_stat_rows(row: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    """Key statistics for one ranking row, ready for a two-column table."""
    wins = _as_int(row.get("wins"))
    losses = _as_int(row.get("losses"))
    played = wins + losses
    stats = (
        ("Player ID", safe_label(row.get("player_id"))),
        ("Name", safe_label(row.get("name"))),
        ("Rating", _as_float(row.get("rating"))),
        ("Matches", _as_int(row.get("matches"))),
        ("Wins", wins),
        ("Losses", losses),
        ("Win rate", f"{wins / played:.1%}" if played else "n/a"),
        ("First match", safe_label(row.get("first_match_date"))),
        ("Last match", safe_label(row.get("last_match_date"))),
    )
    return tuple({"stat": name, "value": value} for name, value in stats)


# --------------------------------------------------------------------------- #
# Season windows
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class SeasonWindow:
    """A one/two/three-season window ending at a chosen season."""

    size: int
    end_year: int
    years: tuple[int, ...] | None
    available: bool
    label: str
    reason: str
    missing: tuple[int, ...]


def season_window(end_year: int, size: int) -> tuple[int, ...]:
    """Consecutive seasons ending at ``end_year`` (newest last)."""
    if size < 1:
        raise ValueError("window size must be at least 1")
    return tuple(range(int(end_year) - size + 1, int(end_year) + 1))


def window_label(years: Sequence[int] | None) -> str:
    """Human-readable season list: ``2026``, ``2025-2026``, ``2024-2026``."""
    values = tuple(int(year) for year in years or ())
    if not values:
        return "no seasons"
    if len(values) == 1:
        return str(values[0])
    return f"{values[0]}\u2013{values[-1]}"


def season_window_plan(
    available_seasons: Iterable[int], *, end_year: int, size: int
) -> SeasonWindow:
    """Plan one window; missing prior seasons make it unavailable, never shorter."""
    years = season_window(end_year, size)
    available = {_as_int(year, default=-1) for year in available_seasons}
    missing = tuple(year for year in years if year not in available)
    if missing:
        listed = ", ".join(str(year) for year in missing)
        word = "Season" if len(missing) == 1 else "Seasons"
        return SeasonWindow(
            size=size,
            end_year=int(end_year),
            years=None,
            available=False,
            label=f"{_size_label(size)} window ending {int(end_year)} unavailable",
            reason=f"{word} {listed} not available in this data directory.",
            missing=missing,
        )
    return SeasonWindow(
        size=size,
        end_year=int(end_year),
        years=years,
        available=True,
        label=f"{_size_label(size)} window {window_label(years)}",
        reason="",
        missing=(),
    )


def window_plans(
    available_seasons: Iterable[int], *, end_year: int, sizes: Sequence[int] = WINDOW_SIZES
) -> tuple[SeasonWindow, ...]:
    """Plans for every requested window size ending at ``end_year``."""
    seasons = tuple(available_seasons)
    return tuple(season_window_plan(seasons, end_year=end_year, size=size) for size in sizes)


def _size_label(size: int) -> str:
    return f"{size}-season"


def season_selection_problem(seasons: Iterable[int]) -> str | None:
    """Validate an explicit season selection the same way the API does."""
    try:
        values = tuple(int(season) for season in seasons)
    except (TypeError, ValueError):
        return "Seasons must be whole years."
    if not values:
        return "Select at least one season."
    if len(values) > 3:
        return "Select at most three seasons."
    if len(set(values)) != len(values):
        return "Each season may be selected only once."
    if tuple(sorted(values)) != tuple(range(min(values), max(values) + 1)):
        return "Selected seasons must be consecutive."
    return None


# --------------------------------------------------------------------------- #
# Run metadata, exclusions, comparison
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class LoadAccounting:
    """The load accounting identity reported next to the run metadata."""

    reported_selected_rows: int
    computed_selected_rows: int
    matches: int
    excluded: int
    duplicates: int
    consistent: bool


def load_accounting(load: LoadResult) -> LoadAccounting:
    """Check ``selected_rows == matches + excluded + duplicates``."""
    matches = len(load.matches)
    excluded = sum(_as_int(count) for count in load.excluded_counts.values())
    duplicates = _as_int(load.duplicate_rows)
    computed = matches + excluded + duplicates
    reported = _as_int(load.selected_rows)
    return LoadAccounting(
        reported_selected_rows=reported,
        computed_selected_rows=computed,
        matches=matches,
        excluded=excluded,
        duplicates=duplicates,
        consistent=reported == computed,
    )


def exclusion_rows(excluded_counts: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    """Exclusion reason counts, largest first, then alphabetically."""
    rows = [
        {"exclusion": safe_label(reason), "count": _as_int(count)}
        for reason, count in excluded_counts.items()
    ]
    rows.sort(key=lambda row: (-row["count"], row["exclusion"]))
    return tuple(rows)


def run_metadata_rows(result: CalculationResult) -> tuple[dict[str, Any], ...]:
    """Full eligibility/config metadata for one calculated run."""
    load = result.load
    accounting = load_accounting(load)
    check = (
        "consistent"
        if accounting.consistent
        else (
            f"inconsistent (reported {accounting.reported_selected_rows}, "
            f"accounted {accounting.computed_selected_rows})"
        )
    )
    rows = (
        ("Seasons", window_label(result.seasons)),
        ("Initial rating", f"{result.config.initial_rating:g}"),
        ("Base K-factor", f"{result.config.k_factor:g}"),
        (
            "Tournament weighting",
            "enabled (effective K = base K x tournament coefficient)"
            if result.config.use_tournament_weights
            else "disabled (classic Elo: effective K = base K)",
        ),
        ("Retirements included", "yes" if result.config.include_retirements else "no"),
        ("Available seasons", ", ".join(str(year) for year in load.available_seasons) or "none"),
        ("Input files", ", ".join(safe_label(path) for path in load.input_files) or "none"),
        ("Physical rows read", _as_int(load.rows_read)),
        ("Selected-season rows", _as_int(load.selected_rows)),
        ("Matches rated", _as_int(result.ratings.matches_processed)),
        ("Players rated", len(result.ratings.players)),
        ("Duplicate rows ignored", _as_int(load.duplicate_rows)),
        ("Excluded rows", accounting.excluded),
        ("Accounting check", check),
    )
    return tuple({"field": name, "value": value} for name, value in rows)


# --------------------------------------------------------------------------- #
# Tournament weighting (policy, classification metadata, unknown fallback)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class WeightingReport:
    """Everything the dashboard shows about the active tournament-weighting model.

    ``enabled`` is always read from the frozen run configuration. The classification
    fields come from the run summary's ``tournament_weighting`` section (the sibling
    export contract) and stay empty when that section is absent, so an older summary
    never produces invented counts.
    """

    enabled: bool
    reported: bool
    mode_notice: str
    policy_note: str
    matches_by_level: tuple[dict[str, Any], ...]
    unknown_matches: int | None
    unknown_tournaments: tuple[dict[str, Any], ...]
    unknown_notice: str
    absent_notice: str


def coefficient_rows() -> tuple[dict[str, Any], ...]:
    """The fixed coefficient table, in the approved canonical order."""
    return tuple(
        {"level": _level_label(level), "coefficient": coefficient}
        for level, coefficient in TOURNAMENT_COEFFICIENTS.items()
    )


def weighting_mode_notice(enabled: bool) -> str:
    """Explain the active model and how base K relates to the effective K."""
    if enabled:
        return (
            "Tournament weighting is enabled: each match uses its effective K-factor, "
            "effective K = base K x tournament coefficient, for both players. Ratings "
            "and expected scores are never scaled, so updates stay zero-sum."
        )
    return (
        "Tournament weighting is disabled: classic Elo. Every match uses the base "
        "K-factor as its effective K; the tournament level is still recorded with "
        "coefficient 1.00."
    )


def _level_label(level: Any) -> str:
    text = safe_label(level)
    if not text:
        return ""
    return LEVEL_LABELS.get(text, text)


def _level_rank(label: str) -> int:
    order = {LEVEL_LABELS[level]: rank for rank, level in enumerate(TOURNAMENT_COEFFICIENTS)}
    return order.get(label, len(order))


def _as_int_or_none(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _level_count_rows(value: Any) -> tuple[dict[str, Any], ...]:
    """Normalize a ``matches_by_level`` summary value into display rows.

    Accepts either a level-to-count mapping or a sequence of ``{level, matches}``
    records; anything else yields no rows rather than invented data.
    """
    if isinstance(value, Mapping):
        items: Iterable[tuple[Any, Any]] = value.items()
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        items = (
            (record.get("level"), record.get("matches", record.get("count")))
            for record in value
            if isinstance(record, Mapping)
        )
    else:
        return ()
    counts: dict[str, int] = {}
    for level, count in items:
        key = safe_label(level)
        if not key:
            continue
        counts[key] = counts.get(key, 0) + _as_int(count)
    rows = [
        {"level": _level_label(level), "matches": count} for level, count in counts.items()
    ]
    rows.sort(key=lambda row: (_level_rank(row["level"]), row["level"]))
    return tuple(rows)


def _unknown_tournament_rows(value: Any) -> tuple[dict[str, Any], ...]:
    """Readable, deterministically sorted ``unknown_tournaments`` records."""
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    rows: list[dict[str, Any]] = []
    for record in value:
        if not isinstance(record, Mapping):
            continue
        year = _as_int_or_none(record.get("season_year"))
        rows.append(
            {
                "season_year": year if year is not None else safe_label(record.get("season_year")),
                "tournament": safe_label(record.get("tournament")) or "(unnamed event)",
                "matches": _as_int(record.get("matches")),
            }
        )
    rows.sort(key=_unknown_tournament_sort_key)
    return tuple(rows)


def _unknown_tournament_sort_key(row: Mapping[str, Any]) -> tuple[Any, ...]:
    year = row.get("season_year")
    name = safe_label(row.get("tournament")).casefold()
    if isinstance(year, int):
        return (0, year, name)
    return (1, 0, f"{safe_label(year)} {name}")


def tournament_weighting_report(
    result: CalculationResult, summary: Mapping[str, Any] | None = None
) -> WeightingReport:
    """Summarize the active weighting model and the run's classification metadata.

    The mode and policy always come from the run's frozen configuration and the
    operator's fixed coefficient table. Classification counts, unknown counts and the
    unknown tournament list come from the summary's ``tournament_weighting`` section;
    when that section is missing (an older summary or test fake) they stay empty and
    an explicit notice is shown instead of any made-up numbers.
    """
    enabled = bool(getattr(result.config, "use_tournament_weights", True))
    mode_notice = weighting_mode_notice(enabled)
    section: Mapping[str, Any] | None = None
    if isinstance(summary, Mapping):
        candidate = summary.get("tournament_weighting")
        if isinstance(candidate, Mapping):
            section = candidate
    if section is None:
        return WeightingReport(
            enabled=enabled,
            reported=False,
            mode_notice=mode_notice,
            policy_note=WEIGHTING_POLICY_NOTE,
            matches_by_level=(),
            unknown_matches=None,
            unknown_tournaments=(),
            unknown_notice="",
            absent_notice=(
                "This run's summary did not include tournament-weighting metadata, so "
                "classification counts and unknown warnings are unavailable. The "
                "coefficient policy below is still fixed and in force."
            ),
        )

    unknown_tournaments = _unknown_tournament_rows(section.get("unknown_tournaments"))
    unknown_matches = _as_int_or_none(section.get("unknown_matches"))
    if unknown_matches is None:
        unknown_matches = sum(row["matches"] for row in unknown_tournaments)
    unknown_notice = ""
    if unknown_matches > 0:
        unknown_notice = (
            f"{unknown_matches} match(es) used the explicit `unknown` fallback coefficient "
            "1.00 because their tournament could not be classified. They are rated, not "
            "excluded; the affected tournaments are listed below."
        )
        if not enabled:
            unknown_notice += " Tournament weighting is off, so this does not change K."
    return WeightingReport(
        enabled=enabled,
        reported=True,
        mode_notice=mode_notice,
        policy_note=WEIGHTING_POLICY_NOTE,
        matches_by_level=_level_count_rows(section.get("matches_by_level")),
        unknown_matches=unknown_matches,
        unknown_tournaments=unknown_tournaments,
        unknown_notice=unknown_notice,
        absent_notice="",
    )


def comparison_entry(result: CalculationResult) -> dict[str, Any]:
    """Compact summary of one calculated window for the comparison table."""
    players = result.ratings.players
    top = players[0] if players else None
    return {
        "seasons": window_label(result.seasons),
        "players_rated": len(players),
        "matches_processed": _as_int(result.ratings.matches_processed),
        "excluded_matches": sum(_as_int(count) for count in result.load.excluded_counts.values()),
        "duplicate_rows": _as_int(result.load.duplicate_rows),
        "top_player": player_option_label(top.name, top.player_id) if top else "",
        "top_rating": round(top.rating, 1) if top else None,
    }


def comparison_rows(
    plans: Iterable[SeasonWindow],
    entries: Mapping[int, Mapping[str, Any] | str | None],
) -> tuple[dict[str, Any], ...]:
    """Merge window plans with per-size dataset summaries (a ``str`` entry means an error)."""
    rows: list[dict[str, Any]] = []
    for plan in plans:
        row: dict[str, Any] = {
            "window": plan.label,
            "seasons": window_label(plan.years) if plan.years else "",
            "status": "available" if plan.available else "unavailable",
            "players_rated": "",
            "matches_processed": "",
            "top_player": "",
            "top_rating": "",
            "note": "" if plan.available else plan.reason,
        }
        entry = entries.get(plan.size)
        if plan.available and isinstance(entry, str):
            row["status"] = "error"
            row["note"] = safe_label(entry)
        elif plan.available and isinstance(entry, Mapping):
            row["players_rated"] = entry.get("players_rated", "")
            row["matches_processed"] = entry.get("matches_processed", "")
            row["top_player"] = safe_label(entry.get("top_player"))
            row["top_rating"] = entry.get("top_rating", "")
            row["excluded_matches"] = entry.get("excluded_matches", "")
            row["duplicate_rows"] = entry.get("duplicate_rows", "")
            if entry.get("seasons"):
                row["seasons"] = safe_label(entry["seasons"])
        rows.append(row)
    return tuple(rows)


def player_comparison_rows(
    plans: Iterable[SeasonWindow],
    players_by_window: Mapping[int, Mapping[str, Mapping[str, Any]]],
    *,
    player_id: str | None,
    player_label: str = "",
    errors: Mapping[int, str] | None = None,
) -> tuple[dict[str, Any], ...]:
    """Per-player comparison of the same selected player across windows.

    A window whose seasons are missing is ``unavailable``; a window where the
    selected player has no eligible match is ``not rated`` with empty numbers.
    No rating is ever invented (in particular nothing falls back to the initial
    rating).
    """
    failures = errors or {}
    wanted = raw_player_id(player_id)
    label = safe_label(player_label) or wanted
    rows: list[dict[str, Any]] = []
    for plan in plans:
        row: dict[str, Any] = {
            "window": plan.label,
            "seasons": window_label(plan.years) if plan.years else "",
            "status": "",
            "player": label,
            "rating": "",
            "rank": "",
            "matches": "",
            "wins": "",
            "losses": "",
            "note": "",
        }
        if not plan.available:
            row["status"] = "unavailable"
            row["note"] = plan.reason
        elif plan.size in failures:
            row["status"] = "error"
            row["note"] = safe_label(failures[plan.size])
        elif not wanted:
            row["status"] = "no player selected"
            row["note"] = "Choose a player to see their per-window rating."
        else:
            stat = (players_by_window.get(plan.size) or {}).get(wanted)
            if stat is None:
                row["status"] = "not rated"
                row["note"] = f"{label or wanted} has no eligible match in this window."
            else:
                rating = _as_float(stat.get("rating"))
                rank = _as_int(stat.get("rank"), default=-1)
                row["status"] = "rated"
                row["rating"] = round(rating, 1) if rating is not None else ""
                row["rank"] = rank if rank >= 0 else ""
                row["matches"] = _as_int(stat.get("matches"))
                row["wins"] = _as_int(stat.get("wins"))
                row["losses"] = _as_int(stat.get("losses"))
        rows.append(row)
    return tuple(rows)


# --------------------------------------------------------------------------- #
# Player history and chart
# --------------------------------------------------------------------------- #


def _history_date(row: Mapping[str, Any]) -> str:
    date = safe_label(row.get("date"))
    if date:
        return date
    return timestamp_to_iso_date(row.get("timestamp"))


def _history_sort_key(row: Mapping[str, Any]) -> tuple[int, str]:
    return (_as_int(row.get("timestamp")), safe_label(row.get("match_id")))


def player_history_rows(
    history_rows: Iterable[Mapping[str, Any]], player_id: str
) -> tuple[dict[str, Any], ...]:
    """Chronological match history for one player, with readable display text.

    The recorded weighting metadata is passed through unchanged: the player's
    tournament level, the applied coefficient and the actual effective K-factor.
    A legacy row without those keys shows empty cells; nothing is fabricated.
    """
    wanted = safe_label(player_id)
    if not wanted:
        return ()
    selected = [dict(row) for row in history_rows if safe_label(row.get("player_id")) == wanted]
    for row in selected:
        row["date"] = _history_date(row)
        row["match_id"] = safe_label(row.get("match_id"))
        row["tournament"] = safe_label(row.get("tournament"))
        row["surface"] = safe_label(row.get("surface"))
        row["opponent"] = safe_label(row.get("opponent_name")) or safe_label(row.get("opponent_id"))
        row["player_name"] = safe_label(row.get("player_name"))
        level = row.get("tournament_level")
        row["tournament_level"] = safe_label(level) if level is not None else ""
        weight = _as_float(row.get("tournament_weight"))
        row["tournament_weight"] = weight if weight is not None else ""
        effective_k = _as_float(row.get("effective_k_factor"))
        row["effective_k_factor"] = effective_k if effective_k is not None else ""
    selected.sort(key=_history_sort_key)
    return tuple(selected)


def elo_chart_rows(
    history_rows: Iterable[Mapping[str, Any]], player_id: str
) -> tuple[dict[str, Any], ...]:
    """Chart points for one player: one temporal point per match, rounded Elo.

    ``match_date`` is a timezone-aware UTC ``datetime`` built from the match
    timestamp, so several matches on the same calendar day stay distinct and in
    chronological (timestamp, match_id) order.
    """
    points: list[dict[str, Any]] = []
    for row in player_history_rows(history_rows, player_id):
        rating = _as_float(row.get("rating_after"))
        moment = timestamp_to_datetime_utc(row.get("timestamp"))
        if rating is None or moment is None:
            continue
        points.append(
            {
                "match_date": moment,
                "rating": round(rating, 1),
                "match_id": safe_label(row.get("match_id")),
                "opponent": row["opponent"],
            }
        )
    return tuple(points)


def top_players_limit(value: Any) -> int:
    """Parse a configured top-players count, clamped to ``1..MAX_TOP_PLAYERS``.

    Missing or non-numeric values fall back to :data:`TOP_PLAYERS_CHART_LIMIT`, so a
    bad environment value never breaks the dashboard.
    """
    text = plain_text(value)
    if not text:
        return TOP_PLAYERS_CHART_LIMIT
    try:
        count = int(text)
    except ValueError:
        return TOP_PLAYERS_CHART_LIMIT
    return min(max(count, 1), MAX_TOP_PLAYERS)


def top_players_chart_rows(
    ranking_rows: Iterable[Mapping[str, Any]],
    history_rows: Iterable[Mapping[str, Any]],
    *,
    limit: int = TOP_PLAYERS_CHART_LIMIT,
    min_matches: int = 0,
) -> tuple[dict[str, Any], ...]:
    """Rating-after-every-match points for the ``limit`` best-ranked players.

    Players are taken in rank order after the leaderboard's presentation-only
    ``min_matches`` filter. Each point carries a ``player`` series label prefixed
    with the zero-padded rank (``#01 Name``) so the chart legend sorts in rank
    order and duplicate names stay distinct. History is grouped in one pass.
    """
    eligible = filter_ranking_rows(ranking_rows, min_matches=min_matches)
    ordered = sorted(eligible, key=lambda row: _as_int(row.get("rank"), default=10**9))
    top: dict[str, str] = {}
    for row in ordered:
        if len(top) >= max(0, int(limit)):
            break
        player_id = raw_player_id(row.get("player_id"))
        if not player_id or player_id in top:
            continue
        rank = _as_int(row.get("rank"), default=len(top) + 1)
        top[player_id] = f"#{rank:02d} {safe_label(row.get('name')) or player_id}"
    if not top:
        return ()

    grouped: dict[str, list[Mapping[str, Any]]] = {player_id: [] for player_id in top}
    for row in history_rows:
        player_id = raw_player_id(row.get("player_id"))
        if player_id in grouped:
            grouped[player_id].append(row)

    points: list[dict[str, Any]] = []
    for player_id, label in top.items():
        for row in sorted(grouped[player_id], key=_history_sort_key):
            rating = _as_float(row.get("rating_after"))
            moment = timestamp_to_datetime_utc(row.get("timestamp"))
            if rating is None or moment is None:
                continue
            points.append(
                {
                    "match_date": moment,
                    "rating": round(rating, 1),
                    "player": label,
                    "player_id": player_id,
                }
            )
    return tuple(points)


def timestamp_to_datetime_utc(value: Any) -> datetime | None:
    """Timezone-aware UTC datetime for a Unix timestamp, or ``None``."""
    if value is None or isinstance(value, bool):
        return None
    try:
        seconds = int(value)
    except (TypeError, ValueError):
        return None
    try:
        return datetime.fromtimestamp(seconds, tz=UTC)
    except (OverflowError, OSError, ValueError):
        return None


def timestamp_to_iso_date(value: Any) -> str:
    """UTC ISO date for a Unix timestamp, or ``""`` when unusable."""
    if value is None or isinstance(value, bool):
        return ""
    try:
        seconds = int(value)
    except (TypeError, ValueError):
        return ""
    try:
        return datetime.fromtimestamp(seconds, tz=UTC).date().isoformat()
    except (OverflowError, OSError, ValueError):
        return ""


# --------------------------------------------------------------------------- #
# Controls and errors
# --------------------------------------------------------------------------- #


def control_error(*, initial_rating: Any, k_factor: Any) -> str | None:
    """Validate the sidebar rating controls before calling the P0 API."""
    rating = _as_float(initial_rating)
    if rating is None:
        return "Initial rating must be a finite number."
    k_value = _as_float(k_factor)
    if k_value is None:
        return "K-factor must be a finite number."
    if k_value <= 0:
        return "K-factor must be greater than zero."
    return None


def build_rating_config(
    *,
    initial_rating: float,
    k_factor: float,
    include_retirements: bool,
    use_tournament_weights: bool = True,
) -> RatingConfig:
    """Build the shared rating configuration; the model validates the values.

    ``use_tournament_weights`` defaults to the shared contract's enabled default so
    existing callers keep weighted behaviour. The value is passed through unchanged,
    so the model's strict bool validation still applies.
    """
    return RatingConfig(
        initial_rating=float(initial_rating),
        k_factor=float(k_factor),
        include_retirements=bool(include_retirements),
        use_tournament_weights=use_tournament_weights,
    )


def _missing_module_name(exc: ModuleNotFoundError) -> str:
    name = getattr(exc, "name", None)
    if isinstance(name, str) and name:
        return name
    match = _MISSING_MODULE.search(str(exc))
    return match.group(1) if match else ""


def error_message(exc: BaseException) -> str:
    """Turn an exception into a clear, non-technical dashboard message."""
    if isinstance(exc, ModuleNotFoundError):
        name = _missing_module_name(exc)
        if name == "streamlit" or name.startswith(("streamlit.", "pandas", "pyarrow")):
            return MISSING_DASHBOARD_DEPENDENCIES
        return MISSING_PACKAGE_MODULE.format(name=name or "unknown")
    detail = safe_label(exc) or type(exc).__name__
    if isinstance(exc, FileNotFoundError):
        return f"Data directory or file not found: {detail}"
    if isinstance(exc, PermissionError):
        return f"Permission denied while reading the data: {detail}"
    if isinstance(exc, IsADirectoryError):
        return f"Expected a CSV file but found a directory: {detail}"
    if isinstance(exc, OSError):
        return f"Filesystem error while reading the data: {detail}"
    if isinstance(exc, ValueError):
        return f"Invalid data or season selection: {detail}"
    return f"Unexpected error ({type(exc).__name__}): {detail}"
