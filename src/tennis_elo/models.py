"""Shared, immutable contracts for loading, rating, and presenting matches."""

from dataclasses import dataclass
from math import isfinite

from .weighting import TOURNAMENT_COEFFICIENTS


@dataclass(frozen=True, slots=True)
class RatingConfig:
    initial_rating: float = 1500.0
    k_factor: float = 32.0
    include_retirements: bool = True
    use_tournament_weights: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.use_tournament_weights, bool):
            # Keep the public configuration-validation contract: ValueError.
            raise ValueError("use_tournament_weights must be a bool")  # noqa: TRY004
        if not isfinite(self.initial_rating):
            raise ValueError("initial_rating must be finite")
        if not isfinite(self.k_factor) or self.k_factor <= 0:
            raise ValueError("k_factor must be finite and greater than zero")
        if self.use_tournament_weights and not isfinite(
            self.k_factor * max(TOURNAMENT_COEFFICIENTS.values())
        ):
            raise ValueError("k_factor produces a non-finite effective K with tournament weighting")


@dataclass(frozen=True, slots=True)
class Match:
    match_id: str
    season_year: int
    timestamp: int
    home_id: str
    away_id: str
    home_name: str
    away_name: str
    winner_code: int
    tournament: str = ""
    round: str = ""
    surface: str = ""
    tournament_level: str = "unknown"


@dataclass(frozen=True, slots=True)
class LoadResult:
    matches: tuple[Match, ...]
    input_files: tuple[str, ...]
    available_seasons: tuple[int, ...]
    rows_read: int
    selected_rows: int
    excluded_counts: dict[str, int]
    duplicate_rows: int


@dataclass(frozen=True, slots=True)
class PlayerRating:
    player_id: str
    name: str
    rating: float
    matches: int
    wins: int
    losses: int
    first_match_timestamp: int
    last_match_timestamp: int


@dataclass(frozen=True, slots=True)
class HistoryEntry:
    match_id: str
    season_year: int
    timestamp: int
    player_id: str
    player_name: str
    opponent_id: str
    opponent_name: str
    won: bool
    rating_before: float
    opponent_rating_before: float
    expected_score: float
    rating_after: float
    tournament: str = ""
    surface: str = ""
    tournament_level: str = "unknown"
    tournament_weight: float = 1.0
    effective_k_factor: float = 32.0


@dataclass(frozen=True, slots=True)
class RatingResult:
    players: tuple[PlayerRating, ...]
    history: tuple[HistoryEntry, ...]
    matches_processed: int


@dataclass(frozen=True, slots=True)
class CalculationResult:
    seasons: tuple[int, ...]
    config: RatingConfig
    load: LoadResult
    ratings: RatingResult
