"""Public orchestration API for reproducible one-, two-, and three-season Elo.

The data and rating lanes are imported lazily inside the orchestration
functions. That keeps ``import tennis_elo.api`` lightweight (standard library
only) and lets export/CLI unit tests run before those lanes are integrated.
"""

from __future__ import annotations

import itertools
from collections.abc import Iterable
from pathlib import Path
from typing import TYPE_CHECKING

from .models import CalculationResult, RatingConfig

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .models import LoadResult, RatingResult

_MAX_SEASONS = 4


def _normalize_seasons(seasons: Iterable[int]) -> tuple[int, ...]:
    """Validate one to three distinct consecutive seasons and sort them.

    Duplicates are rejected explicitly rather than silently discarded, and the
    returned tuple is always in ascending order so callers and output paths are
    deterministic regardless of the order the user typed.
    """

    try:
        values = tuple(seasons)
    except TypeError as exc:
        raise ValueError("seasons must be an iterable of integer years") from exc

    if not values:
        raise ValueError("select at least one season")
    if len(values) > _MAX_SEASONS:
        raise ValueError(f"select at most three seasons, got {len(values)}")

    for value in values:
        if isinstance(value, bool) or not isinstance(value, int):
            # The public API and CLI treat bad selections as ValueError, not TypeError.
            raise ValueError(f"season must be an integer, got {value!r}")  # noqa: TRY004

    if len(set(values)) != len(values):
        raise ValueError("seasons must be distinct; do not repeat a year")

    ordered = tuple(sorted(values))
    for previous, current in itertools.pairwise(ordered):
        if current != previous + 1:
            raise ValueError("seasons must be consecutive")
    return ordered


def calculate(
    input_dir: str | Path,
    seasons: Iterable[int],
    *,
    config: RatingConfig | None = None,
    include_history: bool = False,
) -> CalculationResult:
    """Load the selected seasons and replay them from a fresh starting rating.

    Every call starts each player at the configured ``initial_rating``; only
    matches from the selected consecutive seasons are replayed. Ratings are
    never imported from seasons outside the selection.
    """

    ordered = _normalize_seasons(seasons)
    if config is None:
        config = RatingConfig()
    elif not isinstance(config, RatingConfig):
        raise ValueError("config must be a RatingConfig instance or None")

    from .data import discover_csv_files, load_matches
    from .ratings import rate_matches

    paths = discover_csv_files(input_dir)
    load: LoadResult = load_matches(paths, ordered, include_retirements=config.include_retirements)
    ratings: RatingResult = rate_matches(load.matches, config, include_history=include_history)
    return CalculationResult(ordered, config, load, ratings)


def available_seasons(input_dir: str | Path) -> tuple[int, ...]:
    """Return the seasons present in ``input_dir`` (delegates to the data lane)."""

    from .data import available_seasons as _available_seasons

    return _available_seasons(input_dir)
