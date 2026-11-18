"""Parent-owned contracts shared by the isolated weighting workers."""

from dataclasses import replace

import pytest

from tennis_elo.models import HistoryEntry, Match, RatingConfig


def test_weighting_is_default_and_can_be_disabled():
    assert RatingConfig().use_tournament_weights is True
    assert RatingConfig(use_tournament_weights=False).use_tournament_weights is False
    assert RatingConfig() != RatingConfig(use_tournament_weights=False)
    assert len({RatingConfig(), RatingConfig(use_tournament_weights=False)}) == 2


@pytest.mark.parametrize("value", [None, 0, 1, "false", [], ()])
def test_weighting_flag_requires_bool(value):
    with pytest.raises(ValueError, match="use_tournament_weights.*bool"):
        RatingConfig(use_tournament_weights=value)


def test_weighted_config_rejects_effective_k_overflow_before_replay():
    with pytest.raises(ValueError, match="k_factor.*effective K"):
        RatingConfig(k_factor=1e308)


def test_unweighted_config_keeps_finite_large_base_k_valid():
    config = RatingConfig(k_factor=1e308, use_tournament_weights=False)
    assert config.k_factor == 1e308


def test_match_category_is_backward_compatible_and_explicit():
    match = Match("m1", 2026, 1, "p1", "p2", "A", "B", 1)
    assert match.tournament_level == "unknown"
    assert replace(match, tournament_level="grand_slam").tournament_level == "grand_slam"


def test_history_contract_records_applied_weight_and_effective_k():
    entry = HistoryEntry("m1", 2026, 1, "p1", "A", "p2", "B", True, 1500, 1500, 0.5, 1516)
    assert (entry.tournament_level, entry.tournament_weight, entry.effective_k_factor) == (
        "unknown",
        1.0,
        32.0,
    )
    weighted = replace(
        entry,
        tournament_level="grand_slam",
        tournament_weight=2.0,
        effective_k_factor=64.0,
        rating_after=1532.0,
    )
    assert (weighted.tournament_level, weighted.tournament_weight, weighted.effective_k_factor) == (
        "grand_slam",
        2.0,
        64.0,
    )


@pytest.mark.parametrize(
    "level, coefficient",
    [
        ("challenger", 0.75),
        ("atp_250", 1.0),
        ("atp_500", 1.25),
        ("masters_1000", 1.5),
        ("atp_finals", 1.75),
        ("grand_slam", 2.0),
        ("other", 1.0),
        ("unknown", 1.0),
    ],
)
def test_approved_coefficients(level, coefficient):
    from tennis_elo.weighting import coefficient_for_level

    assert coefficient_for_level(level) == coefficient


def test_coefficient_table_is_read_only():
    from tennis_elo.weighting import TOURNAMENT_COEFFICIENTS

    with pytest.raises(TypeError):
        TOURNAMENT_COEFFICIENTS["grand_slam"] = 9.0


@pytest.mark.parametrize("level", ["ATP 500", "masters", "atp_1000", "grand slam", ""])
def test_invalid_category_keys_are_not_silent_fallbacks(level):
    from tennis_elo.weighting import coefficient_for_level

    with pytest.raises(ValueError, match="tournament level"):
        coefficient_for_level(level)
