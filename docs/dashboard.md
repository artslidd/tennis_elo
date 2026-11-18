# Tennis Elo dashboard (P1)

The optional local Streamlit dashboard presents the P0 ratings. It reads the
season CSVs, calls the public API, and shows the leaderboard, exclusions and
player detail. There is no authentication and the launcher binds localhost by
default; `--address` or forwarded Streamlit flags can change the bind, so only
expose it on trusted networks.

## Install and launch

```bash
uv sync --extra dashboard                  # streamlit + pandas (optional extra)
uv run --extra dashboard tennis-elo-dashboard
```

The console script starts the installed Streamlit CLI against
`src/tennis_elo/dashboard.py` on `http://localhost:8501`. Options:

```bash
uv run --extra dashboard tennis-elo-dashboard --port 8600 --headless
uv run --extra dashboard tennis-elo-dashboard -- --theme.base=dark
```

`--address` defaults to `localhost`; pass `--address 127.0.0.1` for the explicit
loopback form, or `0.0.0.0` to expose the dashboard to your network (no
authentication is provided). Everything after `--` is forwarded to `streamlit
run`. The
launcher blocks while the server runs - stop it with Ctrl-C. Without the extra it
exits with code 1 and prints the `uv sync --extra dashboard` instruction instead
of a traceback.

`streamlit run src/tennis_elo/dashboard.py` also works directly.

## What the UI does

- **Data**: a local directory field plus `Reload seasons`. Seasons come from
  `tennis_elo.api.available_seasons` (real `season_year` values in the CSVs, not
  calendar years). Missing or unreadable directories and malformed data produce a
  clear error message, never a traceback.
- **Seasons**: an end-season picker, one/two/three-season presets that end at
  that season, and an explicit multi-select that overrides the preset. Selection
  rules (one to three distinct consecutive seasons) are validated before
  `tennis_elo.api.calculate` is called.
- **Controls**: initial rating, K-factor, retirement policy, a **Use tournament
  weights** checkbox and a minimum-match field. The K-factor field is the BASE K:
  with tournament weights on, each match's effective K is the base K times the
  tournament coefficient. Unchecking `Use tournament weights` (or using the API/
  CLI equivalent) gives classic Elo, where the effective K is always the base K.
  The minimum-match value is a presentation filter only: it changes the
  leaderboard and the rankings CSV, never the Elo replay.
- **Run metadata**: seasons, configuration, input files, available seasons,
  physical rows read, selected rows, matches rated, players rated, ignored
  duplicates, excluded rows and the load accounting identity. The configuration
  rows name the base K-factor and state whether tournament weighting is enabled.
- **Tournament weighting**: the model notice states whether the run is weighted
  and repeats that effective K = base K x coefficient; the coefficient policy
  table and the classification policy are always shown. Match counts per
  tournament level and the unclassified-tournament detail come from the run
  summary's `tournament_weighting` section. When that section is missing (an
  older export module), the section says so explicitly instead of showing
  invented numbers. Unclassified matches use the explicit `unknown` fallback
  coefficient 1.00, are rated (never excluded) and raise a visible warning with
  the affected tournaments listed.
- **Leaderboard**: searchable by name or player ID, sortable by any column, Elo
  rounded to one decimal for display only.
- **Player detail**: a selector whose state is the raw player ID and whose label
  is `Name (player ID)`, so equal names stay distinguishable and a player keeps
  its selection when the latest name changes between windows. It shows key
  statistics, an Elo chart with one temporal point per match (UTC timestamps, so
  several matches on one date stay distinct and ordered) and the match history
  (newest last), including the recorded tournament level, applied coefficient and
  effective K-factor for every match. Legacy history rows that do not carry those
  fields render as empty cells; the UI never invents a coefficient or K.
- **Downloads**: rankings and match-history CSV come from `tennis_elo.export`
  (`rankings_csv` / `history_csv`). The full match-history export is behind an
  opt-in toggle and is built once per run.

`api.calculate` is always called with `include_history=True`.

## Tournament weighting

The checkbox is on by default, matching the shared `RatingConfig` default. The
operator-selected coefficient scale is fixed:

| Canonical level | Coefficient |
|---|---:|
| `challenger` | 0.75 |
| `atp_250` | 1.00 |
| `atp_500` | 1.25 |
| `masters_1000` | 1.50 |
| `atp_finals` | 1.75 |
| `grand_slam` | 2.00 |
| `other` (team/nonstandard) | 1.00 |
| `unknown` (fallback) | 1.00 |

`effective K = base K x coefficient`, applied identically to both players with
their pre-match ratings: ratings, expected scores and zero-sum updates are never
scaled. Qualifying inherits its parent tournament's category (Grand Slam
qualifying therefore also uses 2.00); team/nonstandard events use `other` = 1.00;
and a label that cannot be classified uses the explicit `unknown` fallback 1.00
and is reported instead of being silently treated as ATP 250. The classification
metadata is read from `tennis_elo.export.summary_dict`'s `tournament_weighting`
section (`enabled`, `coefficients`, `matches_by_level`, `unknown_matches`,
`unknown_tournaments`); the dashboard does not classify tournaments itself.

Unchecking the box is classic Elo: every match uses the base K as its effective
K, while the classified level and weight 1.00 stay recorded in history.

## Fresh-start and window semantics

Each calculation independently starts every player at the configured initial
rating and replays only the selected seasons; ratings are not continuous annual
changes. The same caveat is visible in the UI.

The window comparison recomputes the one-, two- and three-season windows that end
at the chosen season, each with its own calculation from the same initial rating
and all with the same current configuration. If a window needs a season that is
not in the data directory, the row is marked `unavailable`, lists the missing
seasons, and is never replaced by a shorter calculation.

The tournament-weighting flag is part of the frozen configuration, so it is part
of the calculation signature: changing it marks the main calculation as stale and
requires **Calculate ratings** again, and it invalidates a stored window
comparison until **Compare windows** is pressed again. Switching the selected
player never recomputes any window; the cached per-window rows are re-rendered.

The primary comparison table is per player: for the selected player ID it shows
the rating, global rank, matches, wins and losses in each window; a window where
the player has no eligible match is marked `not rated` with empty numbers and no
invented (initial) rating. The per-window player tables are cached with the
comparison, so changing the selected player re-renders without recomputing any
window. Before any main calculation there is no selected player, so a picker over
the union of the compared windows' players drives the table. The dataset summary
per window remains available as a secondary table.

## Text safety

Player names, tournaments and surfaces come from CSV files, so every value that
reaches Markdown is escaped (`escape_markdown`) and every value that reaches a
plain widget label or table is stripped of angle brackets and control characters
(`safe_label`). Download file names are sanitised (`safe_download_filename`).
Streamlit's default HTML escaping is kept on; the app uses no custom CSS,
`unsafe_allow_html` or remote assets.

## Tests

```bash
uv run --locked --extra dashboard pytest tests/test_models.py tests/test_dashboard.py -q
uv run --locked --extra dashboard ruff check src/tennis_elo/dashboard.py \
    src/tennis_elo/dashboard_launcher.py src/tennis_elo/dashboard_views.py \
    tests/test_dashboard.py
```

`--extra dashboard` matters: a plain `uv run` removes the optional Streamlit and
pandas dependencies from the environment, which makes the `AppTest` cases skip.

`tests/test_dashboard.py` covers the pure helpers (search, sorting, player-ID
disambiguation, window availability, text safety, errors), the tournament
weighting presentation (coefficient policy, base/effective K wording,
classification metadata, the unknown fallback warning, graceful handling of a
summary without the `tournament_weighting` section, and the new history
columns), the launcher (argument construction, missing extra, invalid port, no
import-time Streamlit), and Streamlit `AppTest` runs. The `AppTest` UI tests
inject stub `tennis_elo.api` / `tennis_elo.export` modules through the import
system, so they run in an isolated dashboard worktree. The test
`test_app_integration_with_real_p0_modules_and_data` skips until the P0 modules
and the season CSVs are present, and then runs a real 2026-season calculation
through the UI; the integrated parent checkout runs it for real.

A bounded manual smoke test of the launcher (start headless, request
`/_stcore/health`, terminate, confirm the port is free) leaves no server behind.
