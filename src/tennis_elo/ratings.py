"""Replay already-validated matches into Elo ratings, aggregates and history.

Public assumptions
------------------
``rate_matches`` expects matches that the data lane has already validated,
filtered and deduplicated:

* ``winner_code`` is 1 (home) or 2 (away) -- a malformed code raises ValueError
  instead of silently corrupting the replayed state;
* the two player IDs are distinct and non-empty;
* ``timestamp`` is a sortable integer and ``match_id`` a string.

Replay itself only sorts, replays and aggregates. It never re-validates or drops
rows (that would hide accounting errors) and never mutates the caller's matches,
list or configuration. Every call starts fresh at ``config.initial_rating``; no
module-level state is shared between calls.

Every match's ``tournament_level`` is validated against the canonical table with
``coefficient_for_level`` in both weighted and unweighted modes, so a misspelled
level fails loudly instead of silently behaving like the fallback. Replay then
performs one pure Elo update per match with
``config.k_factor * applied_coefficient`` for both players, where the applied
coefficient is the level's coefficient when ``config.use_tournament_weights`` is
enabled and 1.0 when it is disabled (classic Elo). Ratings and expected scores
are never multiplied by the coefficient.
"""

from collections.abc import Iterable
from dataclasses import dataclass

from .elo import expected_score, update_ratings
from .models import HistoryEntry, Match, PlayerRating, RatingConfig, RatingResult
from .weighting import coefficient_for_level


@dataclass
class _PlayerState:
    """Mutable accumulator local to one ``rate_matches`` call."""

    player_id: str
    name: str
    rating: float
    matches: int = 0
    wins: int = 0
    losses: int = 0
    first_match_timestamp: int | None = None
    last_match_timestamp: int | None = None

    def record(self, timestamp: int, won: bool) -> None:
        self.matches += 1
        if won:
            self.wins += 1
        else:
            self.losses += 1
        if self.first_match_timestamp is None or timestamp < self.first_match_timestamp:
            self.first_match_timestamp = timestamp
        if self.last_match_timestamp is None or timestamp > self.last_match_timestamp:
            self.last_match_timestamp = timestamp


def _replay_key(match: Match) -> tuple[int, str]:
    """Chronological key: timestamp first, string match_id to break ties."""
    return (match.timestamp, match.match_id)


def _history_entry(
    match: Match,
    *,
    player_id: str,
    player_name: str,
    opponent_id: str,
    opponent_name: str,
    won: bool,
    rating_before: float,
    opponent_rating_before: float,
    expected: float,
    rating_after: float,
    tournament_level: str,
    tournament_weight: float,
    effective_k_factor: float,
) -> HistoryEntry:
    return HistoryEntry(
        match_id=match.match_id,
        season_year=match.season_year,
        timestamp=match.timestamp,
        player_id=player_id,
        player_name=player_name,
        opponent_id=opponent_id,
        opponent_name=opponent_name,
        won=won,
        rating_before=rating_before,
        opponent_rating_before=opponent_rating_before,
        expected_score=expected,
        rating_after=rating_after,
        tournament=match.tournament,
        surface=match.surface,
        tournament_level=tournament_level,
        tournament_weight=tournament_weight,
        effective_k_factor=effective_k_factor,
    )


def rate_matches(
    matches: Iterable[Match],
    config: RatingConfig | None = None,
    *,
    include_history: bool = False,
) -> RatingResult:
    """Replay ``matches`` in ``(timestamp, match_id)`` order and return ratings.

    Every player in an eligible match starts at ``config.initial_rating``
    (1500 by default), keeps a full-precision rating, and is keyed by player ID.
    The latest observed name is reported. Players come out sorted by descending
    rating and then ascending player ID. With ``include_history`` each match
    contributes two entries, home first then away, carrying the pre-match
    ratings, the public ``expected_score``, the outcome, the new rating and the
    match's actual tournament level, applied coefficient and effective K-factor.
    An empty input yields an empty, valid result.
    """
    rating_config = RatingConfig() if config is None else config
    initial_rating = rating_config.initial_rating
    base_k_factor = rating_config.k_factor
    use_tournament_weights = rating_config.use_tournament_weights

    ordered_matches = sorted(matches, key=_replay_key)

    states: dict[str, _PlayerState] = {}
    history: list[HistoryEntry] = []

    for match in ordered_matches:
        home = states.get(match.home_id)
        if home is None:
            home = _PlayerState(match.home_id, match.home_name, initial_rating)
            states[match.home_id] = home
        away = states.get(match.away_id)
        if away is None:
            away = _PlayerState(match.away_id, match.away_name, initial_rating)
            states[match.away_id] = away

        home.name = match.home_name
        away.name = match.away_name

        home_before = home.rating
        away_before = away.rating
        expected_home = expected_score(home_before, away_before)
        expected_away = expected_score(away_before, home_before)
        home_won = match.winner_code == 1
        # Validate the canonical level even when weighting is disabled, then
        # scale base K by the applied coefficient for both players at once.
        coefficient = coefficient_for_level(match.tournament_level)
        applied_coefficient = coefficient if use_tournament_weights else 1.0
        effective_k_factor = base_k_factor * applied_coefficient
        # Both new ratings come from the two pre-match ratings, never from a
        # partially updated pairing.
        home_after, away_after = update_ratings(
            home_before, away_before, match.winner_code, k_factor=effective_k_factor
        )
        home.rating = home_after
        away.rating = away_after
        home.record(match.timestamp, home_won)
        away.record(match.timestamp, not home_won)

        if include_history:
            history.append(
                _history_entry(
                    match,
                    player_id=match.home_id,
                    player_name=match.home_name,
                    opponent_id=match.away_id,
                    opponent_name=match.away_name,
                    won=home_won,
                    rating_before=home_before,
                    opponent_rating_before=away_before,
                    expected=expected_home,
                    rating_after=home_after,
                    tournament_level=match.tournament_level,
                    tournament_weight=applied_coefficient,
                    effective_k_factor=effective_k_factor,
                )
            )
            history.append(
                _history_entry(
                    match,
                    player_id=match.away_id,
                    player_name=match.away_name,
                    opponent_id=match.home_id,
                    opponent_name=match.home_name,
                    won=not home_won,
                    rating_before=away_before,
                    opponent_rating_before=home_before,
                    expected=expected_away,
                    rating_after=away_after,
                    tournament_level=match.tournament_level,
                    tournament_weight=applied_coefficient,
                    effective_k_factor=effective_k_factor,
                )
            )

    players = tuple(
        PlayerRating(
            player_id=state.player_id,
            name=state.name,
            rating=state.rating,
            matches=state.matches,
            wins=state.wins,
            losses=state.losses,
            first_match_timestamp=state.first_match_timestamp,
            last_match_timestamp=state.last_match_timestamp,
        )
        for state in sorted(states.values(), key=lambda state: (-state.rating, state.player_id))
    )
    return RatingResult(
        players=players,
        history=tuple(history),
        matches_processed=len(ordered_matches),
    )
