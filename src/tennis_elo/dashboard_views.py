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
from typing import Any

from .models import CalculationResult, LoadResult, RatingConfig

__all__ = [
    "COMPARISON_COLUMNS",
    "DEFAULT_INITIAL_RATING",
    "DEFAULT_K_FACTOR",
    "FRESH_START_NOTICE",
    "HISTORY_COLUMNS",
    "LEADERBOARD_COLUMNS",
    "MISSING_DASHBOARD_DEPENDENCIES",
    "PLAYER_COMPARISON_COLUMNS",
    "WINDOW_SIZES",
    "LoadAccounting",
    "PlayerOption",
    "SeasonWindow",
    "build_player_options",
    "build_rating_config",
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
    "window_label",
    "window_plans",
]

DEFAULT_INITIAL_RATING = 1500.0
DEFAULT_K_FACTOR = 32.0
WINDOW_SIZES: tuple[int, ...] = (1, 2, 3)

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
        ("K-factor", f"{result.config.k_factor:g}"),
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
    """Chronological match history for one player, with readable display text."""
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
    *, initial_rating: float, k_factor: float, include_retirements: bool
) -> RatingConfig:
    """Build the shared rating configuration; the model validates the values."""
    return RatingConfig(
        initial_rating=float(initial_rating),
        k_factor=float(k_factor),
        include_retirements=bool(include_retirements),
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
