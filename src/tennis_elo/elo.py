"""Pure Elo arithmetic.

Base-10 Elo with a 400-point scale: a rating difference of 400 points maps to a
10:1 expected score. The default K-factor is 32. Nothing here keeps state or
touches the filesystem, so the same numbers come out of any caller.
"""

from math import isfinite

SCALE = 400.0
DEFAULT_K_FACTOR = 32.0
HOME_WIN = 1
AWAY_WIN = 2
WINNER_CODES = (HOME_WIN, AWAY_WIN)


def _finite_number(value: float, name: str) -> float:
    """Return ``value`` as a float, rejecting non-numbers and non-finite values."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a number")
    try:
        number = float(value)
    except OverflowError as exc:  # an int too large to represent as a float
        raise ValueError(f"{name} must be a finite number") from exc
    if not isfinite(number):
        raise ValueError(f"{name} must be a finite number")
    return number


def expected_score(rating: float, opponent_rating: float) -> float:
    """Probability-like expected score of ``rating`` against ``opponent_rating``.

    Equal ratings give exactly 0.5. The result is always in [0, 1], including for
    rating differences whose exponent would overflow a naive ``10 ** difference``.
    """
    player = _finite_number(rating, "rating")
    opponent = _finite_number(opponent_rating, "opponent_rating")
    difference = (opponent - player) / SCALE
    if difference >= 0.0:
        # 1 / (1 + 10 ** difference) rewritten so the exponent is never positive.
        inverse = 10.0 ** (-difference)
        return inverse / (1.0 + inverse)
    return 1.0 / (1.0 + 10.0 ** difference)


def update_ratings(
    home_rating: float,
    away_rating: float,
    winner_code: int,
    *,
    k_factor: float = DEFAULT_K_FACTOR,
) -> tuple[float, float]:
    """Return ``(home_after, away_after)`` from both pre-match ratings.

    ``winner_code`` is 1 for a home win and 2 for an away win. The update is
    zero-sum apart from floating-point rounding. Raises TypeError for a
    non-numeric argument and ValueError for non-finite ratings or K, for
    K <= 0, and for any other winner code.
    """
    home = _finite_number(home_rating, "home_rating")
    away = _finite_number(away_rating, "away_rating")
    k = _finite_number(k_factor, "k_factor")
    if k <= 0.0:
        raise ValueError("k_factor must be finite and greater than zero")
    if isinstance(winner_code, bool) or winner_code not in WINNER_CODES:
        raise ValueError("winner_code must be 1 (home win) or 2 (away win)")

    expected_home = expected_score(home, away)
    expected_away = 1.0 - expected_home
    home_score = 1.0 if winner_code == HOME_WIN else 0.0
    away_score = 1.0 - home_score
    return (
        home + k * (home_score - expected_home),
        away + k * (away_score - expected_away),
    )
