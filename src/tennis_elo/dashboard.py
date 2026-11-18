"""Local Streamlit dashboard for the Tennis Elo package.

Start it with ``uv run --extra dashboard tennis-elo-dashboard`` (or
``streamlit run src/tennis_elo/dashboard.py``). The launcher binds localhost by
default and the app has no authentication: it is a local presentation layer over
the P0 API. ``--address`` and forwarded Streamlit flags can change the bind, so
only expose it on trusted networks.

Data loading, rating and export logic stay in the P0 modules
(:mod:`tennis_elo.api` and :mod:`tennis_elo.export`). They are imported inside
the ``_runtime_*`` helpers so this module only needs those imports when the user
actually calculates something, which keeps the base package free of Streamlit
and pandas (see the design spec).
"""

from __future__ import annotations

import os
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from tennis_elo import telemetry
from tennis_elo.dashboard_views import (
    CLASSIFICATION_COLUMNS,
    COEFFICIENT_COLUMNS,
    COMPARISON_COLUMNS,
    DATA_DIR_ENV,
    DEFAULT_INITIAL_RATING,
    DEFAULT_K_FACTOR,
    FRESH_START_NOTICE,
    HISTORY_COLUMNS,
    LEADERBOARD_COLUMNS,
    MAX_TOP_PLAYERS,
    PLAYER_COMPARISON_COLUMNS,
    TOP_PLAYERS_ENV,
    UNKNOWN_TOURNAMENT_COLUMNS,
    build_player_options,
    build_rating_config,
    coefficient_rows,
    comparison_entry,
    comparison_rows,
    control_error,
    display_ranking_rows,
    elo_chart_rows,
    error_message,
    escape_markdown,
    exclusion_rows,
    filter_player_options,
    filter_ranking_rows,
    merge_player_rows,
    plain_text,
    player_comparison_rows,
    player_history_rows,
    player_option_label,
    player_stat_rows,
    raw_player_id,
    run_metadata_rows,
    safe_download_filename,
    season_selection_problem,
    season_window_plan,
    sort_ranking_rows,
    top_players_chart_rows,
    top_players_limit,
    tournament_weighting_report,
    window_label,
    window_plans,
)

# Errors the P0 API/export contracts raise for invalid input or unavailable files, plus a
# missing package module. Anything else is a bug and should surface instead of being hidden.
RUNTIME_ERRORS = (OSError, ValueError, ImportError)

PRESET_SIZES: dict[str, int] = {"1 season": 1, "2 seasons": 2, "3 seasons": 3}
DATAFRAME_WIDTH = "stretch"


# --------------------------------------------------------------------------- #
# Runtime seams: the only places that touch the P0 modules
# --------------------------------------------------------------------------- #


def _available_seasons(input_dir: str | Path) -> tuple[int, ...]:
    from tennis_elo.api import available_seasons

    return available_seasons(input_dir)


def _calculate(
    input_dir: str | Path,
    seasons: Sequence[int],
    *,
    config: Any,
    include_history: bool,
) -> Any:
    from tennis_elo.api import calculate

    return calculate(input_dir, seasons, config=config, include_history=include_history)


def _ranking_rows(result: Any) -> tuple[dict[str, Any], ...]:
    from tennis_elo.export import ranking_rows

    return tuple(ranking_rows(result))


def _history_rows(result: Any) -> tuple[dict[str, Any], ...]:
    from tennis_elo.export import history_rows

    return tuple(history_rows(result))


def _rankings_csv(result: Any, *, min_matches: int) -> str:
    from tennis_elo.export import rankings_csv

    return rankings_csv(result, min_matches=min_matches)


def _history_csv(result: Any) -> str:
    from tennis_elo.export import history_csv

    return history_csv(result)


def _summary_dict(result: Any) -> Mapping[str, Any] | None:
    """Fetch the run summary when the export lane provides one.

    The summary carries the optional ``tournament_weighting`` classification section.
    It is presentation-only metadata: if an older export module (or a test fake) has no
    ``summary_dict``, or the call fails, the run still renders and the weighting report
    just reports that the section is unavailable.
    """
    try:
        from tennis_elo.export import summary_dict
    except RUNTIME_ERRORS:
        return None
    try:
        summary = summary_dict(result)
    except RUNTIME_ERRORS:
        return None
    return summary if isinstance(summary, Mapping) else None


# --------------------------------------------------------------------------- #
# Sidebar
# --------------------------------------------------------------------------- #


def _apply_preset() -> None:
    """Widget callback: mirror the selected window preset into the season list."""
    seasons = tuple(st.session_state.get("_season_options") or ())
    size = PRESET_SIZES.get(st.session_state.get("preset_size"), 1)
    end_year = st.session_state.get("end_season")
    if not seasons or end_year is None:
        st.session_state["seasons"] = []
        return
    plan = season_window_plan(seasons, end_year=int(end_year), size=size)
    st.session_state["seasons"] = list(plan.years or ())


def _discover_seasons(directory: str) -> dict[str, Any]:
    """Discover seasons for one directory, never raising at the UI boundary."""
    path = Path(directory)
    if not path.is_dir():
        return {
            "path": directory,
            "seasons": (),
            "error": f"Data directory not found: {plain_text(directory)}",
        }
    try:
        seasons = tuple(int(season) for season in _available_seasons(path))
    except RUNTIME_ERRORS as exc:  # user-facing message instead of a traceback
        return {"path": directory, "seasons": (), "error": error_message(exc)}
    return {"path": directory, "seasons": seasons, "error": None}


def _sidebar() -> dict[str, Any]:
    st.sidebar.header("Data")
    fixed_directory = plain_text(os.environ.get(DATA_DIR_ENV))
    if fixed_directory:
        # Hosted mode: never let visitors choose server-side paths.
        directory = fixed_directory
        st.sidebar.caption("Season CSVs: fixed by this deployment.")
    else:
        entered = st.sidebar.text_input(
            "Season CSV directory",
            value=str(Path.cwd()),
            key="input_dir",
            help="Directory that contains the *-atp-season.csv files.",
        )
        directory = plain_text(entered) or str(Path.cwd())
    try:
        canonical = str(Path(directory).expanduser().resolve())
    except OSError:
        canonical = directory

    discovery = st.session_state["discovery"]
    reload_clicked = st.sidebar.button("Reload seasons", key="reload_seasons")
    if reload_clicked or discovery.get("path") != canonical:
        st.session_state["discovery"] = _discover_seasons(canonical)
        # A different directory invalidates season-derived widget state, so the
        # preset is reapplied below instead of leaving a stale subset selected.
        st.session_state.pop("seasons", None)
        st.session_state.pop("end_season", None)
    discovery = st.session_state["discovery"]
    if discovery["error"]:
        st.sidebar.error(discovery["error"])
    seasons: tuple[int, ...] = tuple(discovery["seasons"])

    st.sidebar.header("Seasons")
    selected: tuple[int, ...] = ()
    end_year: int | None = None
    if not seasons:
        st.sidebar.warning("No seasons discovered in this directory yet.")
    else:
        st.session_state["_season_options"] = seasons
        end_year = int(
            st.sidebar.selectbox(
                "Ending season",
                options=list(seasons),
                index=len(seasons) - 1,
                key="end_season",
                on_change=_apply_preset,
            )
        )
        preset = st.sidebar.radio(
            "Window preset",
            options=tuple(PRESET_SIZES),
            index=0,
            key="preset_size",
            on_change=_apply_preset,
            help="Presets keep one, two or three consecutive seasons. A window whose "
            "earlier seasons are missing is reported as unavailable, never shortened.",
        )
        plan = season_window_plan(seasons, end_year=end_year, size=PRESET_SIZES[preset])
        if "seasons" not in st.session_state:
            st.session_state["seasons"] = list(plan.years or ())
        chosen = st.sidebar.multiselect(
            "Seasons to rate",
            options=list(seasons),
            key="seasons",
            help="One to three consecutive seasons. This explicit selection overrides "
            "the preset and is validated by the same API.",
        )
        if not plan.available:
            st.sidebar.info(f"Preset unavailable - {plan.reason}")
        selected = tuple(sorted(int(season) for season in chosen))

    st.sidebar.header("Rating")
    initial_rating = st.sidebar.number_input(
        "Initial rating",
        min_value=0.0,
        max_value=100000.0,
        value=DEFAULT_INITIAL_RATING,
        step=10.0,
        key="initial_rating",
        help="Each calculation starts every player from this rating. Within a run ratings "
        "carry from the first selected season to the next.",
    )
    k_factor = st.sidebar.number_input(
        "K-factor",
        min_value=0.1,
        max_value=1000.0,
        value=DEFAULT_K_FACTOR,
        step=0.5,
        key="k_factor",
        help="Base K-factor. With tournament weights on, each match's effective K is "
        "this base K x the tournament coefficient.",
    )
    include_retirements = st.sidebar.checkbox(
        "Include retirements", value=True, key="include_retirements"
    )
    use_tournament_weights = st.sidebar.checkbox(
        "Use tournament weights",
        value=True,
        key="use_tournament_weights",
        help="On (default): each match's effective K = base K x the tournament coefficient "
        "(Challenger 0.75, ATP 250 1.00, ATP 500 1.25, Masters 1000 1.50, ATP Finals "
        "1.75, Grand Slam 2.00; team/nonstandard and unknown 1.00). Off: classic Elo, "
        "where every match uses the base K as its effective K.",
    )
    min_matches = st.sidebar.number_input(
        "Minimum matches (leaderboard only)",
        min_value=0,
        max_value=100000,
        value=0,
        step=1,
        key="min_matches",
        help="Hides players from the leaderboard and its CSV export. It never changes "
        "Elo updates, which always include every eligible match.",
    )

    top_players = st.sidebar.number_input(
        "Top players in chart",
        min_value=1,
        max_value=MAX_TOP_PLAYERS,
        value=top_players_limit(os.environ.get(TOP_PLAYERS_ENV)),
        step=1,
        key="top_players",
        help="How many of the best-ranked players the rating-over-time chart shows. "
        "Set the startup value with `tennis-elo-dashboard --top-players N`. "
        "Presentation only: changing it never recalculates ratings.",
    )

    control_problem = control_error(initial_rating=initial_rating, k_factor=k_factor)
    if control_problem:
        st.sidebar.error(control_problem)
    config = (
        None
        if control_problem
        else build_rating_config(
            initial_rating=float(initial_rating),
            k_factor=float(k_factor),
            include_retirements=bool(include_retirements),
            use_tournament_weights=bool(use_tournament_weights),
        )
    )

    calculate_clicked = st.sidebar.button(
        "Calculate ratings",
        type="primary",
        key="calculate",
        disabled=not selected or config is None,
    )
    return {
        "input_dir": canonical,
        "seasons": seasons,
        "selected": selected,
        "end_year": end_year,
        "config": config,
        "min_matches": int(min_matches),
        "top_players": int(top_players),
        "calculate": calculate_clicked,
    }


# --------------------------------------------------------------------------- #
# Calculation and rendering
# --------------------------------------------------------------------------- #


def _signature(state: Mapping[str, Any]) -> tuple[Any, ...]:
    return (state["input_dir"], state["selected"], state["config"])


def _telemetry_tags() -> list[str]:
    """Per-session Datadog tags; telemetry is a no-op without a DD API key."""
    session_id = st.session_state.get("telemetry_session_id", "")
    return [f"session_id:{session_id}"] if session_id else []


def _track_session() -> None:
    """Emit one session-start log and a page-view metric on every rerun."""
    if "telemetry_session_id" not in st.session_state:
        st.session_state["telemetry_session_id"] = uuid.uuid4().hex
        telemetry.send_log("dashboard session started", tags=_telemetry_tags())
        telemetry.count("tennis_elo.sessions", tags=_telemetry_tags())
    telemetry.count("tennis_elo.page_views", tags=_telemetry_tags())


def _run_calculation(state: Mapping[str, Any]) -> None:
    st.session_state["run"] = None
    st.session_state["comparison"] = None
    st.session_state["text_cache"] = {}

    problem = season_selection_problem(state["selected"])
    if problem:
        st.session_state["run_error"] = problem
        return
    if state["config"] is None:
        st.session_state["run_error"] = "Fix the rating controls before calculating."
        return

    try:
        with st.spinner("Loading matches and replaying Elo..."):
            started = time.monotonic()
            result = _calculate(
                state["input_dir"],
                state["selected"],
                config=state["config"],
                include_history=True,
            )
            ranking_rows = _ranking_rows(result)
            history_rows = _history_rows(result)
    except RUNTIME_ERRORS as exc:  # user-facing message instead of a traceback
        telemetry.count("tennis_elo.run_errors", tags=_telemetry_tags())
        telemetry.send_log(
            f"calculation failed: {exc}",
            status="warning",
            tags=_telemetry_tags(),
            attrs={
                "seasons": list(state["selected"]),
                "error_type": type(exc).__name__,
            },
        )
        st.session_state["run_error"] = error_message(exc)
        return

    telemetry.count("tennis_elo.runs", tags=_telemetry_tags())
    telemetry.send_log(
        "calculation finished",
        tags=_telemetry_tags(),
        attrs={
            "seasons": list(result.seasons),
            "matches": result.ratings.matches_processed,
            "players": len(result.ratings.players),
            "min_matches": state["min_matches"],
            "duration_seconds": round(time.monotonic() - started, 3),
        },
    )

    st.session_state["run_error"] = None
    st.session_state["run"] = {
        "result": result,
        "signature": _signature(state),
        "ranking_rows": ranking_rows,
        "history_rows": history_rows,
        # Optional presentation metadata; ``None`` when the export lane has none.
        "summary": _summary_dict(result),
    }


def _cached_text(key: tuple[Any, ...], builder: Callable[[], str]) -> str:
    cache = st.session_state.setdefault("text_cache", {})
    if key not in cache:
        cache[key] = builder()
    return cache[key]


def _render_metadata(run: Mapping[str, Any]) -> None:
    result = run["result"]
    st.subheader("Run metadata")
    metrics = st.columns(4)
    metrics[0].metric("Seasons", window_label(result.seasons))
    metrics[1].metric("Matches rated", f"{result.ratings.matches_processed:,}")
    metrics[2].metric("Players rated", f"{len(result.ratings.players):,}")
    metrics[3].metric("Rows read", f"{result.load.rows_read:,}")

    with st.expander("Eligibility and exclusion metadata"):
        metadata = pd.DataFrame(list(run_metadata_rows(result)), columns=["field", "value"])
        st.dataframe(metadata.astype(str), key="metadata", hide_index=True, width=DATAFRAME_WIDTH)
        st.markdown("**Excluded rows by reason**")
        exclusions = pd.DataFrame(list(exclusion_rows(result.load.excluded_counts)))
        st.dataframe(exclusions, key="exclusions", hide_index=True, width=DATAFRAME_WIDTH)
        st.markdown(
            "Consistency check: selected-season rows must equal rated matches plus "
            "excluded rows plus ignored duplicates."
        )


def _render_weighting(run: Mapping[str, Any]) -> None:
    """Show the active weighting model, its policy and any unknown fallback.

    The mode, coefficient table and policy are always shown. Classification counts and
    the unknown-tournament detail come from the run summary when it reports them; an
    older summary is acknowledged explicitly instead of showing invented numbers.
    """
    report = tournament_weighting_report(run["result"], run.get("summary"))
    st.subheader("Tournament weighting")
    st.caption(report.mode_notice)
    if report.unknown_notice:
        st.warning(report.unknown_notice)

    with st.expander("Coefficient policy and classification detail"):
        st.markdown(report.policy_note)
        coefficients = pd.DataFrame(list(coefficient_rows()), columns=list(COEFFICIENT_COLUMNS))
        st.dataframe(
            coefficients, key="weighting_coefficients", hide_index=True, width=DATAFRAME_WIDTH
        )
        if not report.reported:
            st.info(report.absent_notice)
            return
        if report.matches_by_level:
            st.markdown("**Matches by tournament level**")
            st.dataframe(
                pd.DataFrame(list(report.matches_by_level), columns=list(CLASSIFICATION_COLUMNS)),
                key="weighting_levels",
                hide_index=True,
                width=DATAFRAME_WIDTH,
            )
        if report.unknown_tournaments:
            st.markdown("**Unclassified tournaments (explicit `unknown` fallback)**")
            st.dataframe(
                pd.DataFrame(
                    list(report.unknown_tournaments), columns=list(UNKNOWN_TOURNAMENT_COLUMNS)
                ),
                key="weighting_unknowns",
                hide_index=True,
                width=DATAFRAME_WIDTH,
            )


def _render_leaderboard(run: Mapping[str, Any], state: Mapping[str, Any]) -> None:
    result = run["result"]
    rows = run["ranking_rows"]
    st.subheader("Leaderboard")
    search = st.text_input(
        "Search the leaderboard",
        key="leaderboard_search",
        placeholder="Filter by player name or player ID",
    )
    controls = st.columns(3)
    sort_column = controls[0].selectbox(
        "Sort by", options=list(LEADERBOARD_COLUMNS), index=0, key="leaderboard_sort"
    )
    descending = controls[1].checkbox("Descending", value=False, key="leaderboard_desc")

    shown = filter_ranking_rows(rows, query=search, min_matches=state["min_matches"])
    shown = sort_ranking_rows(shown, column=sort_column, descending=descending)
    st.caption(
        f"{len(shown):,} of {len(rows):,} players shown. Minimum-match filtering is a "
        "presentation filter: Elo updates always use every eligible match."
    )
    st.dataframe(
        pd.DataFrame(list(display_ranking_rows(shown)), columns=list(LEADERBOARD_COLUMNS)),
        key="leaderboard",
        hide_index=True,
        width=DATAFRAME_WIDTH,
    )

    downloads = st.columns(2)
    seasons_label = window_label(result.seasons)
    downloads[0].download_button(
        "Download rankings CSV",
        data=_cached_text(
            ("rankings_csv", id(result), state["min_matches"]),
            lambda: _rankings_csv(result, min_matches=state["min_matches"]),
        ),
        file_name=safe_download_filename(f"tennis-elo-rankings-{seasons_label}.csv"),
        mime="text/csv",
        key="download_rankings",
    )
    downloads[1].toggle(
        "Prepare full match-history CSV",
        key="prepare_history",
        help="One row per player per match, so this file can be large.",
    )
    if st.session_state.get("prepare_history"):
        downloads[1].download_button(
            "Download match-history CSV",
            data=_cached_text(("history_csv", id(result)), lambda: _history_csv(result)),
            file_name=safe_download_filename(f"tennis-elo-history-{seasons_label}.csv"),
            mime="text/csv",
            key="download_history",
        )


def _render_top_players_chart(run: Mapping[str, Any], state: Mapping[str, Any]) -> None:
    """Elo timeseries of the top-ranked players, one coloured line per player."""
    points = top_players_chart_rows(
        run["ranking_rows"],
        run["history_rows"],
        limit=state["top_players"],
        min_matches=state["min_matches"],
    )
    st.markdown(f"**Top {state['top_players']} players: Elo rating over time**")
    if not points:
        st.info("No match history is available for the top-ranked players.")
        return
    st.caption(
        "Current top players by rank (after the minimum-match filter), with their rating "
        "after every match in the selected seasons. Legend entries are prefixed by rank."
    )
    frame = pd.DataFrame(list(points))
    # Timezone-aware UTC timestamps keep one temporal point per match.
    frame["match_date"] = pd.to_datetime(frame["match_date"], utc=True)
    st.line_chart(
        frame,
        x="match_date",
        y="rating",
        color="player",
        x_label="Match date",
        y_label="Elo rating",
        height=480,
    )


def _label_formatter(labels: Mapping[str, str]) -> Callable[[str], str]:
    """Build a selectbox label formatter for the current run's player labels.

    The widget state stays the raw player ID; only the display label changes when
    a player's latest name changes. The map is captured per run so the formatter
    also works when Streamlit re-serializes widget state outside the script run
    (for example in AppTest).
    """

    def format_player_id(player_id: str) -> str:
        return labels.get(player_id, player_id)

    return format_player_id


def _render_player(run: Mapping[str, Any]) -> None:
    rows = run["ranking_rows"]
    history = run["history_rows"]
    st.subheader("Player detail")
    options = build_player_options(rows)
    if not options:
        st.info("No players were rated for this selection.")
        return
    # The widget state is the raw player ID; labels are display-only, so a player
    # whose latest name changes between windows keeps its selection.
    st.session_state["_player_labels"] = {option.player_id: option.label for option in options}

    query = st.text_input(
        "Search players",
        key="player_search",
        placeholder="Filter by player name or player ID",
    )
    matching = filter_player_options(options, query)
    if not matching:
        st.info("No player matches that search.")
        return

    player_ids = [option.player_id for option in matching]
    if st.session_state.get("player_id") not in player_ids:
        st.session_state["player_id"] = player_ids[0]
    picked_id = st.selectbox(
        "Player",
        options=player_ids,
        format_func=_label_formatter({option.player_id: option.label for option in matching}),
        key="player_id",
    )
    option = next(option for option in matching if option.player_id == picked_id)

    st.subheader(escape_markdown(option.label))
    ranking_row = next(
        (row for row in rows if raw_player_id(row.get("player_id")) == option.player_id), None
    )
    if ranking_row is not None:
        stats = pd.DataFrame(list(player_stat_rows(ranking_row)), columns=["stat", "value"])
        st.dataframe(stats.astype(str), key="player_stats", hide_index=True, width=DATAFRAME_WIDTH)

    chart_rows = elo_chart_rows(history, option.player_id)
    if chart_rows:
        st.markdown("**Elo rating after every match**")
        chart_frame = pd.DataFrame(list(chart_rows))
        # Timezone-aware UTC timestamps: one temporal point per match, so several
        # matches on the same date stay distinct and correctly ordered.
        chart_frame["match_date"] = pd.to_datetime(chart_frame["match_date"], utc=True)
        st.line_chart(
            chart_frame,
            x="match_date",
            y="rating",
            x_label="Match date",
            y_label="Elo rating",
        )
    else:
        st.info("No match history is available for this player in the selected seasons.")

    table = player_history_rows(history, option.player_id)
    if table:
        st.markdown("**Match history**")
        st.dataframe(
            pd.DataFrame(list(table), columns=list(HISTORY_COLUMNS)),
            key="player_history",
            hide_index=True,
            width=DATAFRAME_WIDTH,
        )


def _render_run(state: Mapping[str, Any]) -> None:
    error = st.session_state.get("run_error")
    if error:
        st.error(error)
    run = st.session_state.get("run")
    if not run:
        st.info(
            "Choose the directory that holds the season CSVs, pick one to three "
            "consecutive seasons, then press **Calculate ratings**."
        )
        return
    if run["signature"] != _signature(state):
        st.warning(
            "The controls changed since this calculation - press Calculate ratings to refresh."
        )
    _render_metadata(run)
    _render_weighting(run)
    _render_leaderboard(run, state)
    _render_top_players_chart(run, state)
    _render_player(run)


def _compute_comparison(
    state: Mapping[str, Any], plans: Sequence[Any], end_year: int
) -> dict[str, Any]:
    """Recompute every available window independently and cache per-window players.

    The per-window ranking rows are stored so that changing the selected player
    re-renders the comparison without recomputing any window.
    """
    entries: dict[int, Any] = {}
    players: dict[int, dict[str, dict[str, Any]]] = {}
    errors: dict[int, str] = {}
    for plan in plans:
        if not plan.available:
            continue
        try:
            with st.spinner(f"Replaying the {plan.label}..."):
                result = _calculate(
                    state["input_dir"],
                    plan.years,
                    config=state["config"],
                    include_history=False,
                )
                rows = _ranking_rows(result)
        except RUNTIME_ERRORS as exc:  # user-facing message instead of a traceback
            message = error_message(exc)
            errors[plan.size] = message
            entries[plan.size] = message
            continue
        entries[plan.size] = comparison_entry(result)
        players[plan.size] = {
            player_id: dict(row)
            for row in rows
            if (player_id := raw_player_id(row.get("player_id")))
        }
    return {
        "signature": (state["input_dir"], state["config"], end_year),
        "entries": entries,
        "players": players,
        "errors": errors,
    }


def _render_comparison(state: Mapping[str, Any]) -> None:
    st.subheader("Window comparison")
    st.caption(FRESH_START_NOTICE)
    if not state["seasons"] or state["config"] is None:
        st.info(
            "Choose a data directory with seasons to compare the 1-, 2- and 3-season "
            "windows ending at the chosen season."
        )
        return

    end_year = int(state["end_year"] or max(state["seasons"]))
    plans = window_plans(state["seasons"], end_year=end_year)
    if st.button("Compare windows", key="compare_windows"):
        st.session_state["comparison"] = _compute_comparison(state, plans, end_year)

    stored = st.session_state.get("comparison")
    current_signature = (state["input_dir"], state["config"], end_year)
    if not stored or stored.get("signature") != current_signature:
        st.info(
            "Press **Compare windows** to recompute each window independently from the "
            "same initial rating. Missing earlier seasons are reported as unavailable."
        )
        return

    players_by_window: Mapping[int, Mapping[str, Mapping[str, Any]]] = stored.get("players") or {}
    label_map: Mapping[str, str] = st.session_state.get("_player_labels") or {}
    selected_id = st.session_state.get("player_id")
    if not selected_id:
        # No main-run selection yet: offer the union of players seen in any window.
        union_rows = merge_player_rows(
            [list((players_by_window.get(size) or {}).values()) for size in (1, 2, 3)]
        )
        if not union_rows:
            st.info("No players were rated in the compared windows.")
            return
        union_labels = {
            row["player_id"]: player_option_label(row.get("name"), row["player_id"])
            for row in union_rows
        }
        union_ids = [row["player_id"] for row in union_rows]
        if st.session_state.get("comparison_player") not in union_ids:
            st.session_state["comparison_player"] = union_ids[0]
        st.caption("No player is selected in Player detail yet, so this picker drives the table.")
        selected_id = st.selectbox(
            "Comparison player",
            options=union_ids,
            format_func=_label_formatter(union_labels),
            key="comparison_player",
        )
        label_map = union_labels

    player_label = label_map.get(selected_id) or player_option_label(selected_id, selected_id)
    st.markdown(f"**Per-player comparison for {escape_markdown(player_label)}**")
    per_player = player_comparison_rows(
        plans,
        players_by_window,
        player_id=selected_id,
        player_label=player_label,
        errors=stored.get("errors") or {},
    )
    st.dataframe(
        pd.DataFrame(list(per_player), columns=list(PLAYER_COMPARISON_COLUMNS)).astype(str),
        key="player_comparison",
        hide_index=True,
        width=DATAFRAME_WIDTH,
    )

    st.markdown("**Dataset summary per window**")
    dataset = pd.DataFrame(
        list(comparison_rows(plans, stored["entries"])), columns=list(COMPARISON_COLUMNS)
    )
    st.dataframe(dataset.astype(str), key="comparison", hide_index=True, width=DATAFRAME_WIDTH)


def _initialise_state() -> None:
    st.session_state.setdefault("discovery", {"path": None, "seasons": (), "error": None})
    st.session_state.setdefault("run", None)
    st.session_state.setdefault("run_error", None)
    st.session_state.setdefault("comparison", None)
    st.session_state.setdefault("text_cache", {})


def main() -> None:
    """Render the dashboard (Streamlit executes this file top to bottom)."""
    st.set_page_config(page_title="Tennis Elo dashboard", page_icon="🎾", layout="wide")
    _initialise_state()
    _track_session()

    st.title("Tennis Elo")
    st.caption(
        "Local, reproducible Elo over the supplied ATP season CSVs. Nothing is uploaded, "
        "and the launcher binds localhost by default."
    )
    st.info(FRESH_START_NOTICE)

    state = _sidebar()
    if state["calculate"]:
        _run_calculation(state)
    _render_run(state)
    _render_comparison(state)


if __name__ == "__main__":  # Streamlit executes this file as the ``__main__`` script
    main()
