"""Ranking, history, and summary serialization for calculation results.

Everything here is standard-library only. Ratings keep full precision while
they are computed and replayed; rounding happens only at this presentation
boundary. Dates are rendered as UTC ISO dates so exports do not depend on the
machine's local timezone.
"""

from __future__ import annotations

import csv
import io
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from .weighting import TOURNAMENT_COEFFICIENTS

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .models import CalculationResult, HistoryEntry, PlayerRating

RANKING_FIELDS: tuple[str, ...] = (
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

HISTORY_FIELDS: tuple[str, ...] = (
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
    "tournament_level",
    "tournament_weight",
    "effective_k_factor",
)

_RATING_DECIMALS = 2
_EXPECTED_SCORE_DECIMALS = 4


def _utc_iso_date(timestamp: int) -> str:
    """Render an epoch timestamp as a UTC ISO date (``YYYY-MM-DD``)."""

    return datetime.fromtimestamp(timestamp, tz=UTC).date().isoformat()


def _sorted_players(result: CalculationResult) -> list[PlayerRating]:
    """Rank order: descending rating, then ascending stable player ID."""

    return sorted(result.ratings.players, key=lambda player: (-player.rating, player.player_id))


def ranking_rows(result: CalculationResult, *, min_matches: int = 0) -> list[dict]:
    """Return presentation rows for every player, ranked.

    ``min_matches`` is a reporting-only filter: it never reorders or recomputes
    ratings, and rank numbers stay those of the full ranking so a filtered row
    always keeps its true position.
    """

    if min_matches < 0:
        raise ValueError("min_matches must be greater than or equal to zero")

    rows: list[dict] = []
    for rank, player in enumerate(_sorted_players(result), start=1):
        if player.matches < min_matches:
            continue
        rows.append(
            {
                "rank": rank,
                "player_id": player.player_id,
                "name": player.name,
                "rating": round(player.rating, _RATING_DECIMALS),
                "matches": player.matches,
                "wins": player.wins,
                "losses": player.losses,
                "first_match_date": _utc_iso_date(player.first_match_timestamp),
                "last_match_date": _utc_iso_date(player.last_match_timestamp),
            }
        )
    return rows


def _history_row(entry: HistoryEntry) -> dict:
    return {
        "match_id": entry.match_id,
        "season_year": entry.season_year,
        "date": _utc_iso_date(entry.timestamp),
        "timestamp": entry.timestamp,
        "player_id": entry.player_id,
        "player_name": entry.player_name,
        "opponent_id": entry.opponent_id,
        "opponent_name": entry.opponent_name,
        "won": entry.won,
        "rating_before": round(entry.rating_before, _RATING_DECIMALS),
        "opponent_rating_before": round(entry.opponent_rating_before, _RATING_DECIMALS),
        "expected_score": round(entry.expected_score, _EXPECTED_SCORE_DECIMALS),
        "rating_after": round(entry.rating_after, _RATING_DECIMALS),
        "tournament": entry.tournament,
        "surface": entry.surface,
        # Applied values recorded by replay. They are reported verbatim: never
        # re-derived from the current config and never overwritten here.
        "tournament_level": entry.tournament_level,
        "tournament_weight": entry.tournament_weight,
        "effective_k_factor": entry.effective_k_factor,
    }


def history_rows(result: CalculationResult) -> list[dict]:
    """Return one presentation row per history entry, in replay order."""

    return [_history_row(entry) for entry in result.ratings.history]


def _rows_to_csv(fieldnames: tuple[str, ...], rows: list[dict]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return buffer.getvalue()


def rankings_csv(result: CalculationResult, *, min_matches: int = 0) -> str:
    """CSV text for rankings; header-only when no player qualifies."""

    return _rows_to_csv(RANKING_FIELDS, ranking_rows(result, min_matches=min_matches))


def history_csv(result: CalculationResult) -> str:
    """CSV text for match history; header-only when there is no history."""

    return _rows_to_csv(HISTORY_FIELDS, history_rows(result))


def _tournament_weighting_summary(result: CalculationResult) -> dict:
    """Classification accounting for every eligible loaded match.

    Counting is deterministic and independent of replay: it reads the tagged
    level from ``result.load.matches`` and never touches ratings. ``unknown`` is
    the canonical fallback level, so unknown tournaments are grouped by
    ``(season_year, tournament)`` and sorted; a missing or blank name stays an
    empty string and is made readable by the CLI. Every canonical level is
    present in ``matches_by_level`` (zero when unused) so keys are stable, and
    the values always sum to the number of eligible matches.
    """

    counts = {level: 0 for level in TOURNAMENT_COEFFICIENTS}
    unexpected: dict[str, int] = {}
    unknown_tournaments: dict[tuple[int, str], int] = {}

    for match in result.load.matches:
        level = match.tournament_level
        if level in counts:
            counts[level] += 1
        else:
            unexpected[level] = unexpected.get(level, 0) + 1
        if level == "unknown":
            key = (match.season_year, match.tournament)
            unknown_tournaments[key] = unknown_tournaments.get(key, 0) + 1

    for level in sorted(unexpected):
        counts[level] = unexpected[level]

    return {
        "enabled": result.config.use_tournament_weights,
        "coefficients": dict(TOURNAMENT_COEFFICIENTS),
        "matches_by_level": counts,
        "unknown_matches": counts["unknown"],
        "unknown_tournaments": [
            {"season_year": year, "tournament": name, "matches": count}
            for (year, name), count in sorted(unknown_tournaments.items())
        ],
    }


def summary_dict(result: CalculationResult) -> dict:
    """JSON-serializable run summary with accounting and reset semantics.

    ``history_included`` reflects whether the result actually carries history
    entries. :func:`write_outputs` overrides it with the requested
    ``include_history`` flag so the summary matches the files it wrote.

    ``configuration`` records the model that produced the ratings, including
    whether tournament weighting was applied. ``tournament_weighting`` reports
    the fixed coefficient table and deterministic classification accounting.
    """

    load = result.load
    return {
        "seasons": list(result.seasons),
        "configuration": {
            "initial_rating": result.config.initial_rating,
            "k_factor": result.config.k_factor,
            "include_retirements": result.config.include_retirements,
            "use_tournament_weights": result.config.use_tournament_weights,
        },
        "input_files": list(load.input_files),
        "available_seasons": list(load.available_seasons),
        "rows_read": load.rows_read,
        "selected_rows": load.selected_rows,
        "matches_processed": result.ratings.matches_processed,
        "players_rated": len(result.ratings.players),
        "duplicate_rows": load.duplicate_rows,
        "excluded_counts": dict(load.excluded_counts),
        "tournament_weighting": _tournament_weighting_summary(result),
        "history_included": bool(result.ratings.history),
        "fresh_start": True,
        "fresh_start_note": (
            "Fresh start: every player is initialized at the configured "
            "initial_rating and only matches from the selected seasons are "
            "replayed. Ratings are not imported from, or carried over from, "
            "seasons outside the selection."
        ),
    }


def _prepare_output_dir(directory: Path) -> None:
    """Reject anything we must not write into before touching the filesystem."""

    if directory.exists():
        if not directory.is_dir():
            raise FileExistsError(f"output path is not a directory: {directory}")
        if any(directory.iterdir()):
            raise FileExistsError(
                f"output directory is not empty: {directory}; "
                "choose a fresh --output-dir instead of overwriting earlier runs"
            )
        return
    directory.mkdir(parents=True, exist_ok=True)


def _write_text(path: Path, text: str) -> None:
    # Mode "x" guarantees we never silently overwrite a partially written file.
    with path.open("x", encoding="utf-8", newline="") as handle:
        handle.write(text)


def write_outputs(
    result: CalculationResult,
    output_dir: str | Path,
    *,
    min_matches: int = 0,
    include_history: bool = False,
) -> dict[str, Path]:
    """Write rankings, optional history, and summary into a fresh directory.

    A non-empty or non-directory target is rejected before it is changed. The
    returned mapping uses the keys ``rankings``, ``history`` (only when
    requested), and ``summary``.

    Requesting ``include_history=True`` for a result that processed matches but
    carries no history entries is a mismatch: it would write a header-only
    history file and claim history was included. That raises ``ValueError``
    before the output directory is created or touched, so callers must
    recalculate with ``include_history=True``. A run with zero eligible matches
    is still allowed to request history and write the valid header-only file.

    The written summary records the presentation selection under ``reporting``
    (``min_matches`` and the actual ``ranking_rows`` exported) so a filtered
    export is reproducible. ``min_matches`` never changes Elo ratings.

    Raises:
        ValueError: when history is requested but was not calculated, or when
            ``min_matches`` is negative.
        FileExistsError: when ``output_dir`` is not an empty directory.
    """

    if min_matches < 0:
        raise ValueError("min_matches must be greater than or equal to zero")
    if include_history and result.ratings.matches_processed > 0 and not result.ratings.history:
        raise ValueError(
            "include_history=True but the calculation has no history entries; "
            "recalculate with calculate(..., include_history=True) before writing history"
        )

    directory = Path(output_dir)
    _prepare_output_dir(directory)

    rows = ranking_rows(result, min_matches=min_matches)
    written: dict[str, Path] = {}
    rankings_path = directory / "rankings.csv"
    _write_text(rankings_path, _rows_to_csv(RANKING_FIELDS, rows))
    written["rankings"] = rankings_path

    if include_history:
        history_path = directory / "history.csv"
        _write_text(history_path, history_csv(result))
        written["history"] = history_path

    summary = summary_dict(result)
    summary["history_included"] = include_history
    summary["reporting"] = {"min_matches": min_matches, "ranking_rows": len(rows)}
    summary_path = directory / "summary.json"
    _write_text(summary_path, json.dumps(summary, indent=2) + "\n")
    written["summary"] = summary_path

    return written
