"""Weighted replay tests for lane B (``tennis_elo.ratings`` replay/history).

Tournament levels are tagged directly on ``Match`` objects: classification is the
catalog lane's job, so these tests never touch CSV input. Replay must:

* resolve the coefficient with ``coefficient_for_level`` for every match in BOTH
  modes (weighted and disabled), so misspelled levels fail loudly;
* apply ``effective_k = config.k_factor * coefficient`` to BOTH players from
  their SAME pre-match ratings through the single existing pure Elo update;
* never multiply ratings or expected probabilities;
* record the actual level, the APPLIED coefficient and the effective K of that
  match on both ``HistoryEntry`` records.

At the initial 1500 rating and base K 32 an equal-rating winner gains exactly
``32 * coefficient * 0.5``: 12/16/20/24/28/32 for
Challenger/250/500/Masters/Finals/Slam. Unweighted mode keeps the classified
level but records coefficient 1.0 and the actual base K.
"""

import math
from dataclasses import replace

import pytest

from tennis_elo.elo import expected_score
from tennis_elo.models import Match, RatingConfig
from tennis_elo.ratings import rate_matches
from tennis_elo.weighting import TOURNAMENT_COEFFICIENTS, coefficient_for_level

# (canonical level, coefficient, exact winner gain and loser loss at 1500 / base K 32)
TIER_TARGETS = [
    ("challenger", 0.75, 12.0),
    ("atp_250", 1.0, 16.0),
    ("atp_500", 1.25, 20.0),
    ("masters_1000", 1.5, 24.0),
    ("atp_finals", 1.75, 28.0),
    ("grand_slam", 2.0, 32.0),
]


def match(
    match_id: str,
    timestamp: int,
    home_id: str,
    away_id: str,
    winner_code: int,
    *,
    tournament_level: str = "unknown",
    home_name: str | None = None,
    away_name: str | None = None,
) -> Match:
    return Match(
        match_id=match_id,
        season_year=2024,
        timestamp=timestamp,
        home_id=home_id,
        away_id=away_id,
        home_name=home_name if home_name is not None else home_id.upper(),
        away_name=away_name if away_name is not None else away_id.upper(),
        winner_code=winner_code,
        tournament_level=tournament_level,
    )


def by_id(result):
    return {player.player_id: player for player in result.players}


def pair_for(result, match_id):
    """The two history entries of one match, home first then away."""
    entries = [entry for entry in result.history if entry.match_id == match_id]
    assert len(entries) == 2
    return entries


def assert_metadata(result, match_id, level, coefficient, base_k=32.0):
    """Both player entries record the actual level, applied weight and effective K."""
    home, away = pair_for(result, match_id)
    effective_k = base_k * coefficient
    for entry in (home, away):
        assert entry.tournament_level == level
        assert entry.tournament_weight == coefficient
        assert entry.effective_k_factor == effective_k
    return home, away


def assert_entry_arithmetic(entry):
    """rating_after is one pure Elo step with this entry's own effective K."""
    expected = expected_score(entry.rating_before, entry.opponent_rating_before)
    assert entry.expected_score == expected
    score = 1.0 if entry.won else 0.0
    assert entry.rating_after == pytest.approx(
        entry.rating_before + entry.effective_k_factor * (score - expected),
        rel=1e-12,
        abs=1e-12,
    )


@pytest.mark.parametrize(("level", "coefficient", "gain"), TIER_TARGETS)
def test_equal_ratings_winner_gains_tier_target(level, coefficient, gain):
    result = rate_matches(
        [match("m1", 100, "p1", "p2", 1, tournament_level=level)], include_history=True
    )
    players = by_id(result)
    assert players["p1"].rating == 1500.0 + gain
    assert players["p2"].rating == 1500.0 - gain
    assert players["p1"].rating + players["p2"].rating == 3000.0
    home, away = assert_metadata(result, "m1", level, coefficient)
    assert home.won is True and away.won is False
    # The dataclass defaults (weight 1.0 / effective 32.0) are construction-only.
    if coefficient != 1.0:
        assert home.tournament_weight != 1.0
    assert home.rating_before == away.rating_before == 1500.0
    assert home.rating_after == 1500.0 + gain
    assert away.rating_after == 1500.0 - gain
    for entry in (home, away):
        assert entry.expected_score == 0.5
        assert_entry_arithmetic(entry)


@pytest.mark.parametrize("winner_code", [1, 2])
def test_both_winner_sides_get_the_weighted_update(winner_code):
    result = rate_matches(
        [match("m1", 100, "p1", "p2", winner_code, tournament_level="grand_slam")],
        include_history=True,
    )
    players = by_id(result)
    winner_id, loser_id = ("p1", "p2") if winner_code == 1 else ("p2", "p1")
    assert players[winner_id].rating == 1532.0
    assert players[loser_id].rating == 1468.0
    home, away = assert_metadata(result, "m1", "grand_slam", 2.0)
    assert (home.won, away.won) == (winner_code == 1, winner_code == 2)
    for entry in (home, away):
        assert entry.effective_k_factor == 64.0
        assert_entry_arithmetic(entry)


def test_both_players_share_the_same_pre_match_ratings_and_effective_k():
    result = rate_matches(
        [
            match("m1", 100, "p1", "p2", 1, tournament_level="masters_1000"),
            match("m2", 200, "p1", "p2", 2, tournament_level="masters_1000"),
        ],
        include_history=True,
    )
    first_home, first_away = pair_for(result, "m1")
    second_home, second_away = pair_for(result, "m2")
    # The second match starts from the first match's result on both sides.
    assert (second_home.rating_before, second_away.rating_before) == (
        first_home.rating_after,
        first_away.rating_after,
    )
    assert second_home.opponent_rating_before == second_away.rating_before
    assert second_away.opponent_rating_before == second_home.rating_before
    assert second_home.effective_k_factor == second_away.effective_k_factor == 48.0
    # Both deltas are zero-sum and use their own pre-match expected scores.
    for home, away in ((first_home, first_away), (second_home, second_away)):
        assert home.rating_after + away.rating_after == home.rating_before + away.rating_before
        assert home.expected_score + away.expected_score == pytest.approx(1.0, abs=1e-12)
        assert_entry_arithmetic(home)
        assert_entry_arithmetic(away)


@pytest.mark.parametrize(("level", "coefficient"), sorted(TOURNAMENT_COEFFICIENTS.items()))
def test_applied_coefficient_matches_the_canonical_table(level, coefficient):
    result = rate_matches(
        [match("m1", 100, "p1", "p2", 1, tournament_level=level)], include_history=True
    )
    for entry in result.history:
        assert entry.tournament_level == level
        assert entry.tournament_weight == coefficient
        assert entry.effective_k_factor == 32.0 * coefficient


@pytest.mark.parametrize("level", ["other", "unknown"])
def test_unit_coefficient_levels_keep_their_own_level(level):
    result = rate_matches(
        [match("m1", 100, "p1", "p2", 1, tournament_level=level)], include_history=True
    )
    assert by_id(result)["p1"].rating == 1516.0
    for entry in result.history:
        assert entry.tournament_level == level
        assert entry.tournament_weight == 1.0
        assert entry.effective_k_factor == 32.0


@pytest.mark.parametrize(("level", "coefficient"), [("challenger", 0.75), ("grand_slam", 2.0)])
def test_custom_base_k_scales_the_coefficient(level, coefficient):
    config = RatingConfig(k_factor=16.0)
    result = rate_matches(
        [match("m1", 100, "p1", "p2", 1, tournament_level=level)],
        config,
        include_history=True,
    )
    effective_k = 16.0 * coefficient
    gain = effective_k * 0.5
    players = by_id(result)
    assert players["p1"].rating == pytest.approx(1500.0 + gain)
    assert players["p2"].rating == pytest.approx(1500.0 - gain)
    for entry in result.history:
        assert entry.tournament_weight == coefficient
        assert entry.effective_k_factor == effective_k


def test_disabled_weights_use_base_k_and_keep_the_classified_level():
    config = RatingConfig(k_factor=16.0, use_tournament_weights=False)
    result = rate_matches(
        [match("m1", 100, "p1", "p2", 1, tournament_level="grand_slam")],
        config,
        include_history=True,
    )
    players = by_id(result)
    assert players["p1"].rating == 1508.0
    assert players["p2"].rating == 1492.0
    for entry in result.history:
        assert entry.tournament_level == "grand_slam"
        assert entry.tournament_weight == 1.0
        assert entry.effective_k_factor == 16.0


def test_disabled_weights_reproduce_classic_replay_with_level_kept():
    matches = [
        match("m1", 100, "p1", "p2", 1, tournament_level="grand_slam"),
        match("m2", 200, "p2", "p3", 2, tournament_level="challenger"),
    ]
    classic = rate_matches(
        [replace(item, tournament_level="unknown") for item in matches],
        include_history=True,
    )
    unweighted = rate_matches(
        matches, RatingConfig(use_tournament_weights=False), include_history=True
    )
    assert unweighted.players == classic.players
    assert unweighted.matches_processed == classic.matches_processed
    for tagged, plain in zip(unweighted.history, classic.history):
        assert tagged.rating_before == plain.rating_before
        assert tagged.opponent_rating_before == plain.opponent_rating_before
        assert tagged.rating_after == plain.rating_after
        assert tagged.expected_score == plain.expected_score
        assert tagged.tournament_weight == 1.0
        assert tagged.effective_k_factor == 32.0
    assert [entry.tournament_level for entry in unweighted.history] == [
        "grand_slam",
        "grand_slam",
        "challenger",
        "challenger",
    ]


def test_default_unknown_matches_are_identical_weighted_and_unweighted():
    matches = [
        match("m1", 100, "p1", "p2", 1),
        match("m2", 200, "p2", "p3", 2),
        match("m3", 300, "p1", "p3", 1),
    ]
    weighted = rate_matches(matches, include_history=True)
    unweighted = rate_matches(
        matches, RatingConfig(use_tournament_weights=False), include_history=True
    )
    assert weighted == unweighted
    for entry in weighted.history:
        assert entry.tournament_level == "unknown"
        assert entry.tournament_weight == 1.0
        assert entry.effective_k_factor == 32.0


def test_mixed_level_sequence_reconciles_history_and_final_ratings():
    matches = [
        match("m1", 100, "p1", "p2", 1, tournament_level="atp_250"),
        match("m2", 200, "p2", "p3", 1, tournament_level="grand_slam"),
        match("m3", 300, "p3", "p1", 2, tournament_level="challenger"),
    ]
    result = rate_matches(matches, include_history=True)

    # Independent reference replay: one Elo step per match with that match's
    # effective K and both pre-match ratings.
    ratings = {"p1": 1500.0, "p2": 1500.0, "p3": 1500.0}
    expected_levels = {"m1": "atp_250", "m2": "grand_slam", "m3": "challenger"}
    for item in matches:
        level = expected_levels[item.match_id]
        effective_k = 32.0 * coefficient_for_level(level)
        home_before, away_before = ratings[item.home_id], ratings[item.away_id]
        expected_home = expected_score(home_before, away_before)
        home_score = 1.0 if item.winner_code == 1 else 0.0
        ratings[item.home_id] = home_before + effective_k * (home_score - expected_home)
        ratings[item.away_id] = away_before + effective_k * (
            (1.0 - home_score) - (1.0 - expected_home)
        )
        home, away = assert_metadata(result, item.match_id, level, coefficient_for_level(level))
        assert home.rating_before == home_before
        assert away.rating_before == away_before
        assert home.rating_after == pytest.approx(ratings[item.home_id], rel=1e-12)
        assert away.rating_after == pytest.approx(ratings[item.away_id], rel=1e-12)
        assert_entry_arithmetic(home)
        assert_entry_arithmetic(away)

    players = by_id(result)
    for player_id, expected_rating in ratings.items():
        assert players[player_id].rating == pytest.approx(expected_rating, rel=1e-12)


def test_weighted_replay_conserves_total_rating():
    matches = [
        match("m1", 100, "p1", "p2", 1, tournament_level="grand_slam"),
        match("m2", 200, "p1", "p3", 2, tournament_level="challenger"),
        match("m3", 300, "p2", "p3", 1, tournament_level="masters_1000"),
    ]
    result = rate_matches(matches)
    total = sum(player.rating for player in result.players)
    assert total == pytest.approx(1500.0 * len(result.players), rel=1e-12)


def test_history_expected_scores_are_independent_of_the_weight():
    matches = [
        match("m1", 100, "p1", "p2", 1, tournament_level="challenger"),
        match("m2", 200, "p1", "p2", 1, tournament_level="grand_slam"),
    ]
    result = rate_matches(matches, include_history=True)
    for entry in result.history:
        assert entry.expected_score == expected_score(
            entry.rating_before, entry.opponent_rating_before
        )
        # A heavier tournament changes K, never the expected probability.
        assert_entry_arithmetic(entry)
    first_pair = pair_for(result, "m1")
    second_pair = pair_for(result, "m2")
    assert first_pair[0].expected_score == 0.5
    assert second_pair[0].expected_score == expected_score(1512.0, 1488.0)


def test_weighted_history_keeps_full_internal_precision():
    result = rate_matches(
        [
            match("m1", 100, "p1", "p2", 1, tournament_level="challenger"),
            match("m2", 200, "p1", "p2", 1, tournament_level="atp_finals"),
        ],
        include_history=True,
    )
    home, away = pair_for(result, "m2")
    assert (home.rating_before, away.rating_before) == (1512.0, 1488.0)
    effective_k = 32.0 * coefficient_for_level("atp_finals")
    assert home.effective_k_factor == effective_k
    expected = expected_score(1512.0, 1488.0)
    assert home.rating_after == pytest.approx(
        1512.0 + effective_k * (1.0 - expected), rel=1e-15, abs=0.0
    )
    assert home.rating_after != round(home.rating_after, 6)


def test_timestamp_then_match_id_order_with_mixed_levels():
    early = match("z", 100, "p1", "p2", 1, tournament_level="grand_slam")
    tie_a = match("a", 200, "p1", "p2", 1, tournament_level="atp_finals")
    tie_b = match("b", 200, "p1", "p2", 2, tournament_level="challenger")
    explicit = rate_matches([early, tie_a, tie_b], include_history=True)
    assert rate_matches([tie_a, early, tie_b], include_history=True) == explicit
    assert rate_matches([tie_b, tie_a, early], include_history=True) == explicit
    assert [entry.match_id for entry in explicit.history] == ["z", "z", "a", "a", "b", "b"]
    # z: grand slam (k=64) from equal ratings.
    assert explicit.history[0].rating_after == 1532.0
    assert explicit.history[1].rating_after == 1468.0
    # a: atp finals (k=56); b: challenger (k=24) decides the tie-break order.
    a_home, a_away = assert_metadata(explicit, "a", "atp_finals", 1.75)
    b_home, b_away = assert_metadata(explicit, "b", "challenger", 0.75)
    expected_a = expected_score(a_home.rating_before, a_away.rating_before)
    assert a_home.rating_after == pytest.approx(1532.0 + 56.0 * (1.0 - expected_a))
    expected_b = expected_score(b_home.rating_before, b_away.rating_before)
    assert b_home.rating_after == pytest.approx(b_home.rating_before - 24.0 * expected_b)
    assert b_away.rating_after == pytest.approx(b_away.rating_before + 24.0 * expected_b)


def test_weighted_replay_is_deterministic_across_input_order():
    matches = [
        match("m1", 100, "p1", "p2", 1, tournament_level="challenger"),
        match("m2", 200, "p2", "p3", 1, tournament_level="grand_slam"),
        match("m3", 300, "p3", "p1", 2, tournament_level="atp_500"),
        match("m4", 400, "p1", "p3", 1, tournament_level="unknown"),
    ]
    expected = rate_matches(matches, include_history=True)
    assert rate_matches(list(reversed(matches)), include_history=True) == expected
    shuffled = [matches[2], matches[0], matches[3], matches[1]]
    assert rate_matches(shuffled, include_history=True) == expected


def test_weighted_replay_starts_from_fresh_state_every_call():
    single = rate_matches([match("m1", 100, "p1", "p2", 1, tournament_level="grand_slam")])
    repeated = rate_matches([match("m1", 100, "p1", "p2", 1, tournament_level="grand_slam")])
    assert single == repeated
    longer = rate_matches(
        [
            match("m1", 100, "p1", "p2", 1, tournament_level="grand_slam"),
            match("m2", 200, "p1", "p2", 1, tournament_level="grand_slam"),
        ]
    )
    assert by_id(longer)["p1"].rating != by_id(single)["p1"].rating
    assert (
        rate_matches([match("m1", 100, "p1", "p2", 1, tournament_level="grand_slam")]) == single
    )


def test_weighted_replay_preserves_ids_names_and_counts():
    matches = [
        match("m1", 100, "p1", "p2", 1, tournament_level="grand_slam", home_name="Old Name"),
        match("m2", 200, "p1", "p3", 1, tournament_level="challenger", home_name="New Name"),
        match("m3", 300, "p2", "p1", 1, tournament_level="masters_1000", away_name="Latest Name"),
    ]
    result = rate_matches(matches, include_history=True)
    players = by_id(result)
    assert set(players) == {"p1", "p2", "p3"}
    assert players["p1"].name == "Latest Name"
    p1 = players["p1"]
    assert (p1.matches, p1.wins, p1.losses) == (3, 2, 1)
    assert (players["p2"].matches, players["p2"].wins, players["p2"].losses) == (2, 1, 1)
    assert (players["p3"].matches, players["p3"].wins, players["p3"].losses) == (1, 0, 1)
    names = [entry.player_name for entry in result.history if entry.player_id == "p1"]
    assert names == ["Old Name", "New Name", "Latest Name"]


def test_weighted_replay_does_not_mutate_caller_inputs():
    matches = [
        match("m2", 200, "p1", "p2", 2, tournament_level="atp_500"),
        match("m1", 100, "p1", "p2", 1, tournament_level="grand_slam"),
    ]
    snapshot = list(matches)
    config = RatingConfig(use_tournament_weights=True)
    rate_matches(matches, config, include_history=True)
    assert matches == snapshot
    assert [id(item) for item in matches] == [id(item) for item in snapshot]
    assert config == RatingConfig()


@pytest.mark.parametrize("use_weights", [True, False])
@pytest.mark.parametrize("level", ["atp_1000", "grand slam", "Master 1000", "", None, 5, True])
def test_invalid_level_keys_raise_in_both_modes(level, use_weights):
    config = RatingConfig(use_tournament_weights=use_weights)
    with pytest.raises(ValueError, match="tournament level"):
        rate_matches([match("m1", 100, "p1", "p2", 1, tournament_level=level)], config)


def test_invalid_level_leaves_fresh_replay_intact():
    good = [match("m1", 100, "p1", "p2", 1, tournament_level="grand_slam")]
    expected = rate_matches(good, include_history=True)
    with pytest.raises(ValueError):
        rate_matches([*good, match("m2", 200, "p1", "p2", 1, tournament_level="typo")])
    assert rate_matches(good, include_history=True) == expected


def test_largest_valid_weighted_effective_k_stays_finite():
    config = RatingConfig(k_factor=8e307)
    assert config.k_factor * coefficient_for_level("grand_slam") == 1.6e308
    result = rate_matches(
        [match("m1", 100, "p1", "p2", 1, tournament_level="grand_slam")], config
    )
    players = by_id(result)
    assert all(math.isfinite(player.rating) for player in result.players)
    assert players["p1"].rating == pytest.approx(8e307, rel=1e-15)


def test_unweighted_replay_keeps_large_base_k_finite():
    config = RatingConfig(k_factor=1e308, use_tournament_weights=False)
    result = rate_matches(
        [match("m1", 100, "p1", "p2", 1, tournament_level="grand_slam")],
        config,
        include_history=True,
    )
    assert all(math.isfinite(player.rating) for player in result.players)
    for entry in result.history:
        assert entry.tournament_level == "grand_slam"
        assert entry.tournament_weight == 1.0
        assert entry.effective_k_factor == 1e308
