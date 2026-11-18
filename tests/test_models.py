from dataclasses import FrozenInstanceError

import pytest


def test_default_config():
    from tennis_elo.models import RatingConfig

    config = RatingConfig()
    assert (config.initial_rating, config.k_factor, config.include_retirements) == (1500, 32, True)


@pytest.mark.parametrize("value", [0, -1, float("inf"), float("-inf"), float("nan")])
def test_invalid_k(value):
    from tennis_elo.models import RatingConfig

    with pytest.raises(ValueError, match="[Kk]"):
        RatingConfig(k_factor=value)


@pytest.mark.parametrize("value", [float("inf"), float("-inf"), float("nan")])
def test_invalid_initial_rating(value):
    from tennis_elo.models import RatingConfig

    with pytest.raises(ValueError, match="initial_rating"):
        RatingConfig(initial_rating=value)


def test_config_is_immutable():
    from tennis_elo.models import RatingConfig

    config = RatingConfig()
    with pytest.raises(FrozenInstanceError):
        config.k_factor = 10


def test_contracts_construct_a_complete_result():
    from tennis_elo.models import (
        CalculationResult,
        HistoryEntry,
        LoadResult,
        Match,
        PlayerRating,
        RatingConfig,
        RatingResult,
    )

    match = Match("m1", 2024, 1703815800, "p1", "p2", "A", "B", 1)
    load = LoadResult((match,), ("2024-atp-season.csv",), (2024,), 1, 1, {}, 0)
    player = PlayerRating("p1", "A", 1516.0, 1, 1, 0, match.timestamp, match.timestamp)
    entry = HistoryEntry(
        "m1", 2024, match.timestamp, "p1", "A", "p2", "B", True, 1500, 1500, 0.5, 1516
    )
    ratings = RatingResult((player,), (entry,), 1)
    result = CalculationResult((2024,), RatingConfig(), load, ratings)
    assert result.load.matches == (match,)
    assert result.ratings.history[0].rating_after == 1516
    assert match.surface == ""
    with pytest.raises(FrozenInstanceError):
        match.match_id = "changed"
