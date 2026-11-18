"""Tests for the pure Elo math in ``tennis_elo.elo``.

Contract: base-10 Elo with scale 400 (``expected_score``), K-factor default 32,
both players updated from their pre-match ratings.
"""

import math

import pytest

from tennis_elo.elo import expected_score, update_ratings


def test_expected_score_equal_ratings_is_one_half():
    assert expected_score(1500.0, 1500.0) == 0.5
    assert expected_score(0.0, 0.0) == 0.5
    assert expected_score(-750.5, -750.5) == 0.5


@pytest.mark.parametrize(
    ("rating", "opponent_rating"),
    [
        (1500.0, 1500.0),
        (1600.0, 1200.0),
        (1200.0, 1600.0),
        (2000.0, 1000.0),
        (1625.5, 1499.25),
        (0.0, 400.0),
    ],
)
def test_expected_score_is_symmetric(rating, opponent_rating):
    combined = expected_score(rating, opponent_rating) + expected_score(
        opponent_rating, rating
    )
    assert combined == pytest.approx(1.0, abs=1e-12)


def test_expected_score_uses_400_point_scale():
    assert expected_score(1600.0, 1200.0) == pytest.approx(10 / 11)
    assert expected_score(1200.0, 1600.0) == pytest.approx(1 / 11)
    assert expected_score(1900.0, 1500.0) == pytest.approx(10 / 11)
    assert expected_score(1500.0, 1900.0) == pytest.approx(1 / 11)


def test_expected_score_is_monotonic_in_rating():
    scores = [expected_score(rating, 1500.0) for rating in (1000, 1400, 1500, 1700, 2000)]
    assert scores == sorted(scores)
    assert scores[0] < 0.5 < scores[-1]


@pytest.mark.parametrize(
    ("rating", "opponent_rating", "expected"),
    [
        (1e308, -1e308, 1.0),
        (-1e308, 1e308, 0.0),
        (1e18, -1e18, 1.0),
        (-1e18, 1e18, 0.0),
        (1e9, -1e9, 1.0),
        (-1e9, 1e9, 0.0),
        (1e308, 0.0, 1.0),
        (0.0, 1e308, 0.0),
    ],
)
def test_expected_score_extreme_differences_do_not_overflow(rating, opponent_rating, expected):
    score = expected_score(rating, opponent_rating)
    assert score == expected
    assert 0.0 <= score <= 1.0


def test_expected_score_returns_finite_probability_for_huge_finite_inputs():
    for rating, opponent_rating in ((1e300, -1e300), (-1e300, 1e300), (1e300, 1e300)):
        score = expected_score(rating, opponent_rating)
        assert math.isfinite(score)
        assert 0.0 <= score <= 1.0


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_expected_score_rejects_non_finite_ratings(bad):
    with pytest.raises(ValueError):
        expected_score(bad, 1500.0)
    with pytest.raises(ValueError):
        expected_score(1500.0, bad)


@pytest.mark.parametrize("bad", [None, "1500", object(), 1 + 2j])
def test_expected_score_rejects_non_numeric_ratings(bad):
    with pytest.raises((TypeError, ValueError)):
        expected_score(bad, 1500.0)
    with pytest.raises((TypeError, ValueError)):
        expected_score(1500.0, bad)


@pytest.mark.parametrize("winner_code", [1, 2])
def test_update_ratings_equal_players_default_k(winner_code):
    home, away = update_ratings(1500.0, 1500.0, winner_code)
    if winner_code == 1:
        assert (home, away) == (1516.0, 1484.0)
    else:
        assert (home, away) == (1484.0, 1516.0)


def test_update_ratings_honours_custom_k_factor():
    assert update_ratings(1500.0, 1500.0, 1, k_factor=16.0) == (1508.0, 1492.0)
    assert update_ratings(1500.0, 1500.0, 2, k_factor=8.0) == (1496.0, 1504.0)
    assert update_ratings(1500.0, 1500.0, 1, k_factor=64) == (1532.0, 1468.0)


@pytest.mark.parametrize(
    ("home_rating", "away_rating", "winner_code"),
    [
        (1500.0, 1500.0, 1),
        (1500.0, 1500.0, 2),
        (1600.0, 1200.0, 1),
        (1600.0, 1200.0, 2),
        (1200.0, 1600.0, 1),
        (1234.5, 1876.25, 2),
    ],
)
def test_update_ratings_preserves_total_rating(home_rating, away_rating, winner_code):
    home, away = update_ratings(home_rating, away_rating, winner_code)
    assert home + away == pytest.approx(home_rating + away_rating, rel=1e-12)


def test_upset_gains_more_than_expected_result():
    expected_win_gain = update_ratings(1500.0, 1500.0, 1)[0] - 1500.0
    favourite_rating, underdog_rating = 1600.0, 1200.0
    home_after, away_after = update_ratings(favourite_rating, underdog_rating, 2)
    assert home_after < favourite_rating
    assert away_after > underdog_rating
    underdog_gain = away_after - underdog_rating
    assert underdog_gain == pytest.approx(32.0 * (1.0 - 1 / 11))
    assert underdog_gain > expected_win_gain


def test_favourite_win_gains_less_than_equal_match():
    home_after, away_after = update_ratings(1600.0, 1200.0, 1)
    assert home_after - 1600.0 == pytest.approx(32.0 * (1.0 - 10 / 11))
    assert away_after - 1200.0 == pytest.approx(-32.0 * (1.0 - 10 / 11))
    assert home_after - 1600.0 < 16.0


def test_update_ratings_uses_pre_match_ratings_for_both_players():
    home_after, away_after = update_ratings(1516.0, 1484.0, 1)
    expected_home = expected_score(1516.0, 1484.0)
    assert home_after == pytest.approx(1516.0 + 32.0 * (1.0 - expected_home))
    assert away_after == pytest.approx(1484.0 - 32.0 * (1.0 - expected_home))
    # The away player must not be updated against an already updated home rating.
    assert away_after != pytest.approx(1484.0 - 32.0 * (1.0 - expected_score(home_after, 1484.0)))


def test_update_ratings_extreme_differences_stay_finite():
    for home_rating, away_rating, winner_code in (
        (1e308, -1e308, 1),
        (1e308, -1e308, 2),
        (-1e308, 1e308, 1),
        (-1e308, 1e308, 2),
    ):
        home_after, away_after = update_ratings(home_rating, away_rating, winner_code)
        assert math.isfinite(home_after)
        assert math.isfinite(away_after)
        assert home_after + away_after == pytest.approx(home_rating + away_rating, rel=1e-12)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_update_ratings_rejects_non_finite_ratings(bad):
    with pytest.raises(ValueError):
        update_ratings(bad, 1500.0, 1)
    with pytest.raises(ValueError):
        update_ratings(1500.0, bad, 1)


@pytest.mark.parametrize("bad", [0, -1, float("nan"), float("inf"), float("-inf")])
def test_update_ratings_rejects_invalid_k_factor(bad):
    with pytest.raises(ValueError):
        update_ratings(1500.0, 1500.0, 1, k_factor=bad)


@pytest.mark.parametrize("winner_code", [0, 3, -1, 12, None, "1", 1.5])
def test_update_ratings_rejects_invalid_winner_code(winner_code):
    with pytest.raises(ValueError):
        update_ratings(1500.0, 1500.0, winner_code)


@pytest.mark.parametrize("winner_code", [True, False])
def test_update_ratings_rejects_boolean_winner_code(winner_code):
    with pytest.raises(ValueError):
        update_ratings(1500.0, 1500.0, winner_code)
