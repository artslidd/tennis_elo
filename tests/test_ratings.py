"""Tests for the defensive Elo replay in ``tennis_elo.ratings``.

Public assumptions: input matches are already validated, filtered and
deduplicated by the data lane (distinct player IDs, ``winner_code`` 1 or 2,
parsable integer timestamps). Replay itself only sorts, replays and aggregates.
"""

import pytest

from tennis_elo.elo import expected_score
from tennis_elo.models import Match, RatingConfig
from tennis_elo.ratings import rate_matches


def match(
    match_id: str,
    timestamp: int,
    home_id: str,
    away_id: str,
    winner_code: int,
    *,
    season: int = 2024,
    home_name: str | None = None,
    away_name: str | None = None,
    tournament: str = "",
    surface: str = "",
) -> Match:
    return Match(
        match_id=match_id,
        season_year=season,
        timestamp=timestamp,
        home_id=home_id,
        away_id=away_id,
        home_name=home_name if home_name is not None else home_id.upper(),
        away_name=away_name if away_name is not None else away_id.upper(),
        winner_code=winner_code,
        tournament=tournament,
        surface=surface,
    )


def by_id(result):
    return {player.player_id: player for player in result.players}


def test_empty_input_yields_empty_valid_result():
    result = rate_matches([])
    assert result.players == ()
    assert result.history == ()
    assert result.matches_processed == 0


def test_single_match_starts_from_1500_and_applies_k32():
    result = rate_matches([match("m1", 100, "p1", "p2", 1)])
    players = by_id(result)
    assert result.matches_processed == 1
    assert players["p1"].rating == 1516.0
    assert players["p2"].rating == 1484.0
    assert (players["p1"].matches, players["p1"].wins, players["p1"].losses) == (1, 1, 0)
    assert (players["p2"].matches, players["p2"].wins, players["p2"].losses) == (1, 0, 1)
    assert [player.player_id for player in result.players] == ["p1", "p2"]


def test_away_winner_gets_the_bonus():
    result = rate_matches([match("m1", 100, "p1", "p2", 2)])
    players = by_id(result)
    assert players["p2"].rating == 1516.0
    assert players["p1"].rating == 1484.0
    assert [player.player_id for player in result.players] == ["p2", "p1"]


def test_config_controls_initial_rating_and_k_factor():
    config = RatingConfig(initial_rating=1000.0, k_factor=16.0)
    result = rate_matches([match("m1", 100, "p1", "p2", 1)], config)
    players = by_id(result)
    assert players["p1"].rating == 1008.0
    assert players["p2"].rating == 992.0


def test_default_config_is_used_when_config_is_none():
    result = rate_matches([match("m1", 100, "p1", "p2", 1)], None)
    assert by_id(result)["p1"].rating == 1516.0


def test_replay_is_invariant_to_input_order():
    matches = [
        match("m1", 100, "p1", "p2", 1),
        match("m2", 200, "p2", "p3", 1),
        match("m3", 300, "p3", "p1", 2),
        match("m4", 400, "p1", "p3", 1),
    ]
    expected = rate_matches(matches, include_history=True)
    assert rate_matches(list(reversed(matches)), include_history=True) == expected
    shuffled = [matches[2], matches[0], matches[3], matches[1]]
    assert rate_matches(shuffled, include_history=True) == expected


def test_timestamps_define_order_then_match_id_breaks_ties():
    # "z" has the earlier timestamp, so it must be replayed first whatever the
    # input order; "a" and "b" share a timestamp and are ordered by match_id.
    early = match("z", 100, "p1", "p2", 1)
    tie_a = match("a", 200, "p1", "p2", 1)
    tie_b = match("b", 200, "p1", "p2", 2)
    explicit = rate_matches([early, tie_a, tie_b], include_history=True)
    assert rate_matches([tie_a, early, tie_b], include_history=True) == explicit
    assert rate_matches([tie_b, tie_a, early], include_history=True) == explicit
    assert [entry.match_id for entry in explicit.history] == ["z", "z", "a", "a", "b", "b"]
    # p1 wins twice then loses the final (tie-broken) match.
    after_two_wins = 1516.0 + 32.0 * (1.0 - expected_score(1516.0, 1484.0))
    assert by_id(explicit)["p1"].rating < after_two_wins


def test_match_id_tie_break_is_reproducible():
    forward = rate_matches(
        [match("a", 100, "p1", "p2", 1), match("b", 100, "p1", "p2", 2)]
    )
    backward = rate_matches(
        [match("b", 100, "p1", "p2", 2), match("a", 100, "p1", "p2", 1)]
    )
    assert forward == backward
    # "a" (p1 wins) then "b" (p2 wins): the later result wins and moves both
    # players from their own pre-match rating.
    p2_pre_match_expected = 1.0 - expected_score(1516.0, 1484.0)
    assert by_id(forward)["p2"].rating == pytest.approx(
        1484.0 + 32.0 * (1.0 - p2_pre_match_expected)
    )
    assert by_id(forward)["p1"].rating == pytest.approx(
        1516.0 - 32.0 * (1.0 - p2_pre_match_expected)
    )


def test_updates_use_pre_match_ratings_for_both_players():
    result = rate_matches(
        [match("m1", 100, "p1", "p2", 1), match("m2", 200, "p1", "p2", 1)],
        include_history=True,
    )
    second_home, second_away = result.history[2], result.history[3]
    assert second_home.rating_before == 1516.0
    assert second_away.rating_before == 1484.0
    assert second_home.opponent_rating_before == 1484.0
    assert second_away.opponent_rating_before == 1516.0
    pre_match = expected_score(1516.0, 1484.0)
    assert second_home.rating_after == pytest.approx(1516.0 + 32.0 * (1.0 - pre_match))
    assert second_away.rating_after == pytest.approx(1484.0 - 32.0 * (1.0 - pre_match))
    players = by_id(result)
    assert players["p1"].rating == second_home.rating_after
    assert players["p2"].rating == second_away.rating_after


def test_latest_name_is_retained_per_player_id():
    result = rate_matches(
        [
            match("m1", 100, "p1", "p2", 1, home_name="Old Name"),
            match("m2", 200, "p1", "p3", 1, home_name="New Name"),
        ],
        include_history=True,
    )
    assert by_id(result)["p1"].name == "New Name"
    history_names = [entry.player_name for entry in result.history if entry.player_id == "p1"]
    assert history_names == ["Old Name", "New Name"]


def test_players_are_keyed_by_id_not_name():
    result = rate_matches(
        [
            match("m1", 100, "p1", "p9", 1, home_name="Same", away_name="Other"),
            match("m2", 200, "p2", "p8", 1, home_name="Same", away_name="Other2"),
        ]
    )
    players = by_id(result)
    assert set(players) == {"p1", "p2", "p9", "p8"}
    assert {player.name for player in result.players if player.player_id in {"p1", "p2"}} == {
        "Same"
    }
    assert players["p1"].matches == 1
    assert players["p2"].matches == 1


def test_statistics_and_timestamps_accumulate():
    result = rate_matches(
        [
            match("m3", 300, "p3", "p1", 1),
            match("m1", 100, "p1", "p2", 1),
            match("m2", 200, "p1", "p3", 1),
        ]
    )
    players = by_id(result)
    p1 = players["p1"]
    assert (p1.matches, p1.wins, p1.losses) == (3, 2, 1)
    assert (p1.first_match_timestamp, p1.last_match_timestamp) == (100, 300)
    p3 = players["p3"]
    assert (p3.matches, p3.wins, p3.losses) == (2, 1, 1)
    assert (p3.first_match_timestamp, p3.last_match_timestamp) == (200, 300)


def test_players_are_sorted_by_descending_rating_then_player_id():
    result = rate_matches(
        [
            match("m1", 100, "b", "x1", 1),
            match("m2", 100, "a", "x2", 1),
        ]
    )
    assert [player.player_id for player in result.players] == ["a", "b", "x1", "x2"]


def test_history_is_omitted_by_default():
    result = rate_matches([match("m1", 100, "p1", "p2", 1)])
    assert result.history == ()


def test_history_records_pre_match_state_for_both_players():
    result = rate_matches(
        [match("m1", 100, "p1", "p2", 2, tournament="Tour X", surface="Clay")],
        include_history=True,
    )
    assert len(result.history) == 2
    home, away = result.history
    assert (home.match_id, home.season_year, home.timestamp) == ("m1", 2024, 100)
    assert (home.player_id, home.player_name) == ("p1", "P1")
    assert (home.opponent_id, home.opponent_name) == ("p2", "P2")
    assert home.won is False
    assert (home.rating_before, home.opponent_rating_before) == (1500.0, 1500.0)
    assert home.expected_score == 0.5
    assert home.rating_after == 1484.0
    assert (home.tournament, home.surface) == ("Tour X", "Clay")
    assert (away.player_id, away.player_name) == ("p2", "P2")
    assert away.won is True
    assert (away.rating_before, away.opponent_rating_before) == (1500.0, 1500.0)
    assert away.expected_score == 0.5
    assert away.rating_after == 1516.0
    assert (away.tournament, away.surface) == ("Tour X", "Clay")


def test_history_expected_score_is_the_public_expected_score():
    result = rate_matches(
        [
            match("m1", 100, "p1", "p2", 1),
            match("m2", 200, "p1", "p2", 2),
        ],
        include_history=True,
    )
    for entry in result.history:
        assert entry.expected_score == expected_score(
            entry.rating_before, entry.opponent_rating_before
        )


def test_history_is_chronological_two_entries_per_match():
    result = rate_matches(
        [
            match("m2", 200, "p2", "p3", 2),
            match("m1", 100, "p1", "p2", 1),
        ],
        include_history=True,
    )
    assert [entry.match_id for entry in result.history] == ["m1", "m1", "m2", "m2"]
    assert [entry.player_id for entry in result.history] == ["p1", "p2", "p2", "p3"]


def test_early_history_rating_after_is_not_the_final_rating():
    result = rate_matches(
        [
            match("m1", 100, "p1", "p2", 1),
            match("m2", 200, "p1", "p2", 1),
        ],
        include_history=True,
    )
    assert result.history[0].rating_after == 1516.0
    assert by_id(result)["p1"].rating > result.history[0].rating_after


def test_total_rating_is_conserved_across_replay():
    matches = [
        match("m1", 100, "p1", "p2", 1),
        match("m2", 200, "p1", "p3", 2),
        match("m3", 300, "p2", "p3", 1),
    ]
    result = rate_matches(matches)
    total = sum(player.rating for player in result.players)
    assert total == pytest.approx(1500.0 * len(result.players), rel=1e-12)


def test_replay_does_not_mutate_caller_inputs():
    matches = [match("m2", 200, "p1", "p2", 2), match("m1", 100, "p1", "p2", 1)]
    snapshot = list(matches)
    config = RatingConfig()
    rate_matches(matches, config, include_history=True)
    assert matches == snapshot
    assert [id(item) for item in matches] == [id(item) for item in snapshot]
    assert config == RatingConfig()


def test_accepts_any_iterable_of_matches():
    result = rate_matches(item for item in [match("m1", 100, "p1", "p2", 1)])
    assert result.matches_processed == 1
    assert by_id(result)["p1"].rating == 1516.0


def test_each_call_starts_from_a_fresh_state():
    single = rate_matches([match("m1", 100, "p1", "p2", 1)])
    repeated = rate_matches([match("m1", 100, "p1", "p2", 1)])
    assert single == repeated
    longer = rate_matches(
        [match("m1", 100, "p1", "p2", 1), match("m2", 200, "p1", "p2", 1)]
    )
    assert by_id(longer)["p1"].rating != by_id(single)["p1"].rating
    # A second call after a longer one still begins at the initial rating.
    assert rate_matches([match("m1", 100, "p1", "p2", 1)]) == single


def test_surface_and_tournament_do_not_weight_the_update():
    plain = rate_matches([match("m1", 100, "p1", "p2", 1)])
    described = rate_matches(
        [match("m1", 100, "p1", "p2", 1, tournament="Grand Slam", surface="Grass")]
    )
    assert plain == described


def test_inactivity_does_not_decay_ratings():
    quick = rate_matches(
        [match("m1", 100, "p1", "p2", 1), match("m2", 200, "p1", "p2", 2)]
    )
    long_gap = rate_matches(
        [match("m1", 100, "p1", "p2", 1), match("m2", 100_000_000, "p1", "p2", 2)]
    )
    assert by_id(quick)["p1"].rating == by_id(long_gap)["p1"].rating
    assert by_id(quick)["p2"].rating == by_id(long_gap)["p2"].rating


def test_invalid_winner_code_fails_loudly_instead_of_corrupting_state():
    with pytest.raises(ValueError):
        rate_matches([match("m1", 100, "p1", "p2", 3)])
