"""Local Streamlit dashboard for the Tennis Elo package.

Start it with ``uv run --extra dashboard tennis-elo-dashboard`` (or
``streamlit run src/tennis_elo/dashboard.py``). The app binds loopback only, has
no authentication and hosts nothing remotely: it is a local presentation layer
over the P0 API.

Data loading, rating and export logic stay in the P0 modules
(:mod:`tennis_elo.api` and :mod:`tennis_elo.export`). They are imported inside
the ``_runtime_*`` helpers so this module only needs those imports when the user
actually calculates something, which keeps the base package free of Streamlit
and pandas (see the design spec).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from tennis_elo.dashboard_views import (
    COMPARISON_COLUMNS,
    DEFAULT_INITIAL_RATING,
    DEFAULT_K_FACTOR,
    FRESH_START_NOTICE,
    HISTORY_COLUMNS,
    LEADERBOARD_COLUMNS,
    build_player_options,
    build_rating_config,
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
    plain_text,
    player_history_rows,
    player_stat_rows,
    run_metadata_rows,
    safe_download_filename,
    safe_label,
    season_selection_problem,
    season_window_plan,
    sort_ranking_rows,
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
        help="Every selected season starts every player from this rating.",
    )
    k_factor = st.sidebar.number_input(
        "K-factor",
        min_value=0.1,
        max_value=1000.0,
        value=DEFAULT_K_FACTOR,
        step=0.5,
        key="k_factor",
    )
    include_retirements = st.sidebar.checkbox(
        "Include retirements", value=True, key="include_retirements"
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
        "calculate": calculate_clicked,
    }


# --------------------------------------------------------------------------- #
# Calculation and rendering
# --------------------------------------------------------------------------- #


def _signature(state: Mapping[str, Any]) -> tuple[Any, ...]:
    return (state["input_dir"], state["selected"], state["config"])


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
            result = _calculate(
                state["input_dir"],
                state["selected"],
                config=state["config"],
                include_history=True,
            )
            ranking_rows = _ranking_rows(result)
            history_rows = _history_rows(result)
    except RUNTIME_ERRORS as exc:  # user-facing message instead of a traceback
        st.session_state["run_error"] = error_message(exc)
        return

    st.session_state["run_error"] = None
    st.session_state["run"] = {
        "result": result,
        "signature": _signature(state),
        "ranking_rows": ranking_rows,
        "history_rows": history_rows,
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


def _render_player(run: Mapping[str, Any]) -> None:
    rows = run["ranking_rows"]
    history = run["history_rows"]
    st.subheader("Player detail")
    options = build_player_options(rows)
    if not options:
        st.info("No players were rated for this selection.")
        return

    query = st.text_input(
        "Search players",
        key="player_search",
        placeholder="Filter by player name or player ID",
    )
    matching = filter_player_options(options, query)
    if not matching:
        st.info("No player matches that search.")
        return

    labels = [option.label for option in matching]
    if st.session_state.get("player_label") not in labels:
        st.session_state["player_label"] = labels[0]
    picked_label = st.selectbox("Player", options=labels, key="player_label")
    option = next(option for option in matching if option.label == picked_label)

    st.subheader(escape_markdown(option.label))
    ranking_row = next(
        (row for row in rows if safe_label(row.get("player_id")) == option.player_id), None
    )
    if ranking_row is not None:
        stats = pd.DataFrame(list(player_stat_rows(ranking_row)), columns=["stat", "value"])
        st.dataframe(stats.astype(str), key="player_stats", hide_index=True, width=DATAFRAME_WIDTH)

    chart_rows = elo_chart_rows(history, option.player_id)
    if chart_rows:
        st.markdown("**Elo rating after every match**")
        st.line_chart(
            pd.DataFrame(list(chart_rows)),
            x="date",
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
    _render_leaderboard(run, state)
    _render_player(run)


def _compute_comparison(
    state: Mapping[str, Any], plans: Sequence[Any], end_year: int
) -> dict[str, Any]:
    entries: dict[int, Any] = {}
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
        except RUNTIME_ERRORS as exc:  # user-facing message instead of a traceback
            entries[plan.size] = error_message(exc)
            continue
        entries[plan.size] = comparison_entry(result)
    return {"signature": (state["input_dir"], state["config"], end_year), "entries": entries}


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

    table = pd.DataFrame(
        list(comparison_rows(plans, stored["entries"])), columns=list(COMPARISON_COLUMNS)
    )
    st.dataframe(table.astype(str), key="comparison", hide_index=True, width=DATAFRAME_WIDTH)


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

    st.title("Tennis Elo")
    st.caption(
        "Local, reproducible Elo over the supplied ATP season CSVs. Nothing is uploaded "
        "and the server binds loopback only."
    )
    st.info(FRESH_START_NOTICE)

    state = _sidebar()
    if state["calculate"]:
        _run_calculation(state)
    _render_run(state)
    _render_comparison(state)


if __name__ == "__main__":  # Streamlit executes this file as the ``__main__`` script
    main()
