"""Discover season CSVs, validate their schema, and load eligible matches.

The loader is deliberately conservative: it never infers a winner, never widens a
requested season window, and reports every excluded row through a reason count so
that the load accounting always reconciles.
"""

from __future__ import annotations

import csv
import itertools
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Final

from tennis_elo.models import LoadResult, Match

CSV_GLOB: Final = "*-atp-season.csv"

REQUIRED_COLUMNS: Final = (
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

OPTIONAL_COLUMNS: Final = ("tournament", "round", "surface")

# Row-content signature used for duplicate detection (required + optional columns).
SIGNATURE_COLUMNS: Final = REQUIRED_COLUMNS + OPTIONAL_COLUMNS

SUPPORTED_TOURS: Final = frozenset({"atp tour", "atp chall", "atp challenger"})

# Exclusion reason keys exposed through LoadResult.excluded_counts.
REASON_EXHIBITION: Final = "exhibition"
REASON_UNSUPPORTED_TOUR: Final = "unsupported_tour"
REASON_WALKOVER: Final = "walkover"
REASON_AWARDED: Final = "awarded"
REASON_CANCELED: Final = "canceled"
REASON_SCHEDULED: Final = "scheduled"
REASON_UNFINISHED: Final = "unfinished"
REASON_INVALID_WINNER: Final = "invalid_winner"
REASON_RETIREMENT: Final = "retirement"

_WALKOVER_STATUSES: Final = frozenset({"WALKOVER"})
_AWARDED_STATUSES: Final = frozenset({"AWARDED"})
_CANCELED_STATUSES: Final = frozenset({"CANCELED", "CANCELLED"})
_SCHEDULED_STATUSES: Final = frozenset({"SCHEDULED"})
_FINISHED_STATUSES: Final = frozenset({"FINISHED"})
_RETIRED_STATUSES: Final = frozenset({"RETIRED"})


def discover_csv_files(input_dir: str | Path) -> tuple[Path, ...]:
    """Return the ``*-atp-season.csv`` files in *input_dir*, sorted by name."""
    directory = Path(input_dir)
    if not directory.exists():
        raise FileNotFoundError(f"input directory does not exist: {directory}")
    if not directory.is_dir():
        raise NotADirectoryError(f"input path is not a directory: {directory}")
    files = tuple(
        sorted(
            (path for path in directory.glob(CSV_GLOB) if path.is_file()),
            key=lambda path: path.name,
        )
    )
    if not files:
        raise ValueError(f"no {CSV_GLOB} files found in {directory}")
    return files


def available_seasons(input_dir: str | Path) -> tuple[int, ...]:
    """Return every ``season_year`` observed across the discovered CSV files."""
    seasons: set[int] = set()
    for path in discover_csv_files(input_dir):
        seasons.update(_read_season_years(path))
    return tuple(sorted(seasons))


def load_matches(
    paths: Iterable[str | Path],
    seasons: Iterable[int],
    *,
    include_retirements: bool = True,
) -> LoadResult:
    """Load, validate, filter, deduplicate, and chronologically sort matches.

    ``rows_read`` counts every physical data row across ``paths``, while
    ``selected_rows`` counts only rows whose authoritative ``season_year`` is in
    ``seasons`` and is measured before deduplication. Duplicate detection covers
    all selected-season rows keyed by ``match_id``: byte-for-byte identical
    signatures (the required plus optional columns) are ignored and counted in
    ``duplicate_rows``, while differing signatures are rejected as conflicts.
    Excluded rows are counted once per distinct ``match_id``.

    A successful load always satisfies
    ``selected_rows == len(matches) + sum(excluded_counts.values()) + duplicate_rows``.

    Raises ``ValueError`` for invalid data or selections (including unavailable
    seasons) and ``OSError`` for filesystem problems.
    """
    path_list = _normalize_paths(paths)
    selected = _normalize_seasons(seasons)

    rows_read = 0
    selected_rows = 0
    duplicate_rows = 0
    available: set[int] = set()
    excluded: dict[str, int] = {}
    seen_signatures: dict[str, tuple[str, ...]] = {}
    seen_context: dict[str, str] = {}
    matches: list[Match] = []

    for path in path_list:
        with _open_csv(path) as reader:
            for row in reader:
                rows_read += 1
                line = reader.line_num
                season = _parse_season_year(row, path, line)
                available.add(season)
                if season not in selected:
                    continue

                selected_rows += 1
                context = f"{path}:{line}"
                signature = _row_signature(row)
                match_id = signature[0]
                if not match_id:
                    raise ValueError(f"{context}: malformed eligible row: missing match_id")

                previous = seen_signatures.get(match_id)
                if previous is not None:
                    if previous == signature:
                        duplicate_rows += 1
                        continue
                    raise ValueError(
                        f"{context}: conflicting duplicate match_id {match_id!r} "
                        f"(first seen at {seen_context[match_id]})"
                    )
                seen_signatures[match_id] = signature
                seen_context[match_id] = context

                reason = _exclusion_reason(row, include_retirements=include_retirements)
                if reason is not None:
                    excluded[reason] = excluded.get(reason, 0) + 1
                    continue

                matches.append(_build_match(row, season, path, line))

    missing = sorted(set(selected) - available)
    if missing:
        raise ValueError(
            f"requested season(s) unavailable: {missing}; available seasons: {sorted(available)}"
        )

    matches.sort(key=lambda match: (match.timestamp, match.match_id))
    excluded_counts = {reason: excluded[reason] for reason in sorted(excluded)}

    result = LoadResult(
        matches=tuple(matches),
        input_files=tuple(str(path) for path in path_list),
        available_seasons=tuple(sorted(available)),
        rows_read=rows_read,
        selected_rows=selected_rows,
        excluded_counts=excluded_counts,
        duplicate_rows=duplicate_rows,
    )
    assert result.selected_rows == (
        len(result.matches) + sum(result.excluded_counts.values()) + result.duplicate_rows
    ), "load accounting must reconcile"
    return result


# --------------------------------------------------------------------------- #
# Internal helpers
# --------------------------------------------------------------------------- #


@contextmanager
def _open_csv(path: Path) -> Iterator[csv.DictReader]:
    """Open *path* as UTF-8 (with BOM support) and validate the header."""
    try:
        handle = path.open("r", encoding="utf-8-sig", newline="")
    except OSError as exc:
        raise OSError(f"cannot read {path}: {exc}") from exc

    with handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames
        if fieldnames is None:
            raise ValueError(f"{path}:1: malformed schema: empty CSV file, missing header row")
        missing = [column for column in REQUIRED_COLUMNS if column not in fieldnames]
        if missing:
            raise ValueError(
                f"{path}:1: malformed schema: missing required column(s): {', '.join(missing)}"
            )
        yield reader


def _read_season_years(path: Path) -> list[int]:
    years: list[int] = []
    with _open_csv(path) as reader:
        for row in reader:
            years.append(_parse_season_year(row, path, reader.line_num))
    return years


def _parse_season_year(row: dict[str, str], path: Path, line: int) -> int:
    raw = _field(row, "season_year")
    try:
        return int(raw)
    except ValueError:
        raise ValueError(f"{path}:{line}: malformed row: invalid season_year {raw!r}") from None


def _normalize_paths(paths: Iterable[str | Path]) -> tuple[Path, ...]:
    if isinstance(paths, (str, Path)):
        candidates: list[str | Path] = [paths]
    elif isinstance(paths, bytes):
        raise TypeError("paths must be filesystem paths, not bytes")
    else:
        candidates = list(paths)

    normalized: list[Path] = []
    seen: set[str] = set()
    for value in candidates:
        path = Path(value)
        key = str(path)
        if key not in seen:
            seen.add(key)
            normalized.append(path)
    if not normalized:
        raise ValueError("at least one CSV path is required")
    return tuple(normalized)


def _normalize_seasons(seasons: Iterable[int]) -> frozenset[int]:
    if isinstance(seasons, (str, bytes)):
        raise TypeError("seasons must be a non-string iterable of integers")
    raw = list(seasons)
    if not raw:
        raise ValueError("at least one season must be selected")

    parsed: list[int] = []
    for value in raw:
        try:
            parsed.append(int(value))
        except (TypeError, ValueError):
            raise ValueError(f"season must be an integer, got {value!r}") from None

    if len(set(parsed)) != len(parsed):
        raise ValueError("selected seasons must be distinct")
    if len(parsed) > 3:
        raise ValueError("at most three seasons may be selected; select one, two, or three")

    ordered = sorted(parsed)
    for earlier, later in itertools.pairwise(ordered):
        if later != earlier + 1:
            raise ValueError(f"selected seasons must be consecutive, got {ordered}")
    return frozenset(ordered)


def _field(row: dict[str, str], key: str) -> str:
    value = row.get(key)
    return "" if value is None else value.strip()


def _row_signature(row: dict[str, str]) -> tuple[str, ...]:
    return tuple(_field(row, column) for column in SIGNATURE_COLUMNS)


def _exclusion_reason(row: dict[str, str], *, include_retirements: bool) -> str | None:
    tour = _field(row, "tour_type_human").casefold()
    if "exhib" in tour:
        return REASON_EXHIBITION
    if tour not in SUPPORTED_TOURS:
        return REASON_UNSUPPORTED_TOUR

    # status_extra is authoritative: some canceled rows still carry status FINISHED.
    status_extra = _field(row, "status_extra").upper()
    status = _field(row, "status").upper()
    effective_status = status_extra or status

    if effective_status in _FINISHED_STATUSES:
        pass
    elif effective_status in _RETIRED_STATUSES:
        if not include_retirements:
            return REASON_RETIREMENT
    elif effective_status in _WALKOVER_STATUSES:
        return REASON_WALKOVER
    elif effective_status in _AWARDED_STATUSES:
        return REASON_AWARDED
    elif effective_status in _CANCELED_STATUSES:
        return REASON_CANCELED
    elif effective_status in _SCHEDULED_STATUSES:
        return REASON_SCHEDULED
    else:
        return REASON_UNFINISHED

    if _field(row, "winner_code") not in {"1", "2"}:
        return REASON_INVALID_WINNER
    return None


def _build_match(row: dict[str, str], season: int, path: Path, line: int) -> Match:
    context = f"{path}:{line}"
    match_id = _field(row, "match_id")
    if not match_id:
        raise ValueError(f"{context}: malformed eligible row: missing match_id")

    timestamp_raw = _field(row, "date_timestamp")
    try:
        timestamp = int(timestamp_raw)
    except ValueError:
        raise ValueError(
            f"{context}: malformed eligible row: invalid date_timestamp {timestamp_raw!r}"
        ) from None

    home_id = _field(row, "home_id")
    away_id = _field(row, "away_id")
    if not home_id or not away_id:
        raise ValueError(
            f"{context}: malformed eligible row: missing player id "
            f"(home_id={home_id!r}, away_id={away_id!r})"
        )
    if home_id == away_id:
        raise ValueError(
            f"{context}: malformed eligible row: same player on both sides ({home_id!r})"
        )

    return Match(
        match_id=match_id,
        season_year=season,
        timestamp=timestamp,
        home_id=home_id,
        away_id=away_id,
        home_name=_field(row, "home_name"),
        away_name=_field(row, "away_name"),
        winner_code=int(_field(row, "winner_code")),
        tournament=_field(row, "tournament"),
        round=_field(row, "round"),
        surface=_field(row, "surface"),
    )
