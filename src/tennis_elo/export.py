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


def summary_dict(result: CalculationResult) -> dict:
    """JSON-serializable run summary with accounting and reset semantics.

    ``history_included`` reflects whether the result actually carries history
    entries. :func:`write_outputs` overrides it with the requested
    ``include_history`` flag so the summary matches the files it wrote.
    """

    load = result.load
    return {
        "seasons": list(result.seasons),
        "configuration": {
            "initial_rating": result.config.initial_rating,
            "k_factor": result.config.k_factor,
            "include_retirements": result.config.include_retirements,
        },
        "input_files": list(load.input_files),
        "available_seasons": list(load.available_seasons),
        "rows_read": load.rows_read,
        "selected_rows": load.selected_rows,
        "matches_processed": result.ratings.matches_processed,
        "players_rated": len(result.ratings.players),
        "duplicate_rows": load.duplicate_rows,
        "excluded_counts": dict(load.excluded_counts),
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
    """

    directory = Path(output_dir)
    _prepare_output_dir(directory)

    written: dict[str, Path] = {}
    rankings_path = directory / "rankings.csv"
    _write_text(rankings_path, rankings_csv(result, min_matches=min_matches))
    written["rankings"] = rankings_path

    if include_history:
        history_path = directory / "history.csv"
        _write_text(history_path, history_csv(result))
        written["history"] = history_path

    summary = summary_dict(result)
    summary["history_included"] = include_history
    summary_path = directory / "summary.json"
    _write_text(summary_path, json.dumps(summary, indent=2) + "\n")
    written["summary"] = summary_path

    return written
