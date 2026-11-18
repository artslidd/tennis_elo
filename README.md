# Tennis Elo

Reproducible, independently reset tennis Elo ratings from `*-atp-season.csv`
data, with a standard-library Python package, a command-line interface, and an
optional local Streamlit dashboard.

Ratings use standard base-10 Elo (scale 400, default K = 32). Players are keyed
by their string IDs, not names, and the latest observed name is displayed.

Matches are **tournament-weighted** by default: each match multiplies the base K
factor by a fixed coefficient for its tournament category. Pass `--unweighted`
for classic Elo. See [Tournament weighting](#tournament-weighting-on-by-default).

## Requirements

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) (recommended) or pip

## Setup

```bash
uv sync --dev
```

The base package and CLI use only the Python standard library. Streamlit and
pandas are an optional extra, installed only for the dashboard.

## Quick start

One, two, or three **distinct, consecutive** seasons:

```bash
uv run tennis-elo rank --seasons 2026
uv run tennis-elo rank --seasons 2025 2026
uv run tennis-elo rank --seasons 2024 2025 2026 --history
```

`--seasons` may be given in any order (it is normalized to ascending order), but
repeated years and non-consecutive years are rejected rather than silently
adjusted. At most three seasons are allowed.

By default the command reads `*-atp-season.csv` files from the current
directory and writes to `outputs/<selected-years>`:

```bash
uv run tennis-elo rank --seasons 2024 2025 2026 \
  --input-dir /path/to/data \
  --output-dir reports/2024-2026 \
  --history
```

Add `--unweighted` to compare against classic Elo, and `--k-factor` to change
the **base** K:

```bash
uv run tennis-elo rank --seasons 2024 2025 2026 --unweighted --k-factor 16
```

`python -m tennis_elo` works exactly like the `tennis-elo` console script:

```bash
uv run python -m tennis_elo rank --seasons 2025 2026 --history \
  --output-dir outputs/2025-2026-python-m
```

## Fresh-start reset semantics

Each calculation is a **fresh start**: every player begins at the configured
`--initial-rating` (default 1500), and only matches from the selected seasons
are replayed in chronological order. Ratings are carried between seasons *within*
the selection, but never imported from seasons outside it.

This means `--seasons 2026` and `--seasons 2024 2025 2026` are two independent
calculations that both start from the initial rating; the longer window is not a
continuation of the shorter one. The summary JSON marks this explicitly with
`fresh_start`, `fresh_start_note`, and the configuration used. Within one
selection every window uses the same current configuration (including the
tournament-weighting choice), but each window still starts fresh.

## Tournament weighting (on by default)

Each match updates both players with a tournament-scaled K factor, always
derived from the same pre-match ratings:

```text
effective K = base K x tournament coefficient
```

| Canonical level | Category | Coefficient | `effective K` at base K 32 |
| --- | --- | ---: | ---: |
| `challenger` | ATP Challenger | 0.75 | 24 |
| `atp_250` | ATP 250 | 1.00 | 32 |
| `atp_500` | ATP 500 | 1.25 | 40 |
| `masters_1000` | ATP Masters 1000 | 1.50 | 48 |
| `atp_finals` | ATP Finals | 1.75 | 56 |
| `grand_slam` | Grand Slam | 2.00 | 64 |
| `other` | Team, Olympic and other nonstandard events | 1.00 | 32 |
| `unknown` | Unclassified or unsupported name/year | 1.00 | 32 |

The coefficients are fixed. `--k-factor` always means the **base** K, and only
the K used for the update is scaled: ratings and expected scores are never
multiplied, so updates stay zero-sum and ordering, eligibility, deduplication
and the season windows are unchanged. The CLI prints the active model, the
`effective K = base K x coefficient` rule and the coefficient table; `--unweighted`
prints the classic model instead.

Qualifying inherits its parent tournament's category, including Grand Slam
qualifying, which therefore also uses 2.00. Team and nonstandard events (United
Cup, Davis Cup, Hopman/Laver Cup, Olympics, Asian Games, Next Gen Finals, US
Open WIC) use `other` at 1.00.

Categories come from a deterministic, bundled, season-aware catalog that uses
explicit per-season aliases and makes no network calls at runtime; the package
stays standard-library-only. See `docs/tournament-levels.md` for the category
sources and the supported seasons.

Names or years the catalog does not cover fall back to `unknown` at coefficient
1.00. They are never silently labelled ATP 250, never excluded, and never an
error: `excluded_counts` and the exit status are unaffected. The run prints a
`Classification:` line listing the unknown tournaments (a missing name is shown
as `(blank tournament name)`, for example `2024 "(blank tournament name)" (2)`),
and `summary.json` keeps the complete sorted list under
`tournament_weighting`. The warning is printed in both modes; with
`--unweighted` it states that the fallback coefficient has no effect on ratings.

To compare against classic Elo, disable weighting explicitly:

```bash
uv run tennis-elo rank --seasons 2024 2025 2026 --unweighted
```

In unweighted mode every match uses `effective K = base K`, while history still
records the classified level with coefficient 1.00 and the actual base K.
Because the two modes produce different ratings, run them into separate
`--output-dir` directories.

## Options

| Option | Default | Meaning |
| --- | --- | --- |
| `--seasons YEAR [YEAR ...]` | required | One to three distinct consecutive seasons. |
| `--input-dir DIR` | `.` | Directory containing `*-atp-season.csv` files. |
| `--output-dir DIR` | `outputs/<selected-years>` | Fresh output directory. |
| `--initial-rating FLOAT` | `1500` | Starting rating for every player. |
| `--k-factor FLOAT` | `32` | Base Elo K; must be finite and positive. A weighted match uses `base K x tournament coefficient`. |
| `--unweighted` | off | Disable tournament weighting: classic Elo, `effective K = base K` for every match. |
| `--exclude-retirements` | off | Drop matches whose `status_extra` marks a retirement. |
| `--history` | off | Also export one row per player per match. |
| `--min-matches INT` | `0` | Only present players with at least this many matches. |
| `--top INT` | `20` | Rows shown in the terminal table. |

`--min-matches` and `--top` are presentation-only. A minimum-match filter never
changes Elo updates, and rank numbers always reflect the full ranking, so a
filtered row keeps its true position.

Expected validation and filesystem problems (bad seasons, invalid K, unavailable
seasons, an output directory that is not empty) print a short `error:` message
and exit with status 2, without a traceback.

## Match inclusion policies

The loader reads the selected seasons from `*-atp-season.csv` files, decodes
UTF-8 with BOM support, and handles quoted CSV correctly. `season_year` is
authoritative, so a 2024-season match played in December 2023 still belongs to
season 2024.

Included:

- `ATP Tour` and `ATP Chall`, including qualifying.
- Normally finished matches, plus retirements with `winner_code` 1 (home) or 2
  (away). Retirements can be dropped with `--exclude-retirements`.

Excluded, with reason counts recorded in the run summary: exhibitions and other
unsupported tours, walkovers, awarded matches, canceled matches, scheduled or
unfinished matches, and invalid winners. The loader uses `status_extra`, not
`status` alone, so canceled records that still say `FINISHED` are excluded. No
winner is ever inferred from a score or ranking.

Selected-season rows are deduplicated by `match_id`: exact duplicates are
ignored and counted, conflicting duplicates are rejected. Malformed eligible
rows are rejected with file/row context, and requesting a season that is not
present is an error rather than a silently shortened window.

## Exports

Each run writes into a fresh directory:

- `rankings.csv` — one row per player with `rank`, `player_id`, `name`,
  `rating`, `matches`, `wins`, `losses`, `first_match_date`, `last_match_date`.
  Rows are ordered by descending rating, then player ID. All players are
  exported by default.
- `history.csv` — written only with `--history`: one row per player per match
  with every history field plus a UTC `date` column. The last three columns are
  the applied `tournament_level`, `tournament_weight` and `effective_k_factor`
  for that match. They are the values replay actually used, exported verbatim:
  they are never re-derived from the current configuration and never
  overwritten, so an unweighted run shows weight `1.0` next to its classified
  level.
- `summary.json` — `seasons`, `configuration`, `input_files`,
  `available_seasons`, `rows_read`, `selected_rows`, `matches_processed`,
  `players_rated`, `duplicate_rows`, `excluded_counts`, `tournament_weighting`,
  `history_included`, `reporting`, and the explicit fresh-start fields.
  `configuration` records `use_tournament_weights` next to `initial_rating`,
  `k_factor` and `include_retirements`, so a run always states which model
  produced it. `tournament_weighting` holds `enabled`, the fixed `coefficients`
  table, `matches_by_level` (every canonical level, counted over the eligible
  loaded matches), `unknown_matches`, and `unknown_tournaments` as
  `{season_year, tournament, matches}` records sorted by
  `(season_year, tournament)`. Counting is deterministic and never changes the
  ratings.

`reporting` records the presentation selection actually written: `min_matches`
and the real `ranking_rows` exported. It makes a filtered export reproducible
and never affects Elo ratings.

Elo keeps full precision while matches are replayed; rounding to two decimals
for ratings (and four for expected scores in history) happens only when writing
outputs. Dates are rendered as UTC ISO dates, independent of the local
timezone.

A run refuses to write into a non-empty or non-directory output path instead of
overwriting an earlier run. Empty directories are fine, and header-only exports
are valid when no match qualifies.

History must be requested on the calculation itself. In the Python API, call
`calculate(..., include_history=True)` before `write_outputs(...,
include_history=True)`; the writer rejects a result that processed matches but
was calculated without history, rather than writing a misleading header-only
`history.csv`. A run with zero eligible matches may still request history and
write the valid header-only file.

## Python API

```python
from tennis_elo import RatingConfig, available_seasons, calculate, write_outputs

print(available_seasons("."))          # (2024, 2025, 2026) in the repo root

result = calculate(
    ".",
    [2025, 2026],
    config=RatingConfig(initial_rating=1500, k_factor=32, include_retirements=True),
    include_history=True,
)

for player in result.ratings.players[:5]:
    print(player.player_id, player.name, round(player.rating, 1))

write_outputs(result, "reports/2025-2026", include_history=True)
```

Tournament weighting is on by default, so the example above is weighted; the
base K is `k_factor` and each match uses `k_factor * coefficient`. For classic
Elo, opt out explicitly:

```python
from tennis_elo import RatingConfig

weighted = RatingConfig(k_factor=32)                            # default
unweighted = RatingConfig(k_factor=32, use_tournament_weights=False)
```

`use_tournament_weights` must be a `bool`. A base K whose weighted maximum
(`base K x 2.0`) is not finite is rejected before any data is read; unweighted
mode only requires a finite, positive base K.

`calculate(input_dir, seasons, *, config=None, include_history=False)` validates
and normalizes the seasons, loads the data, and replays the matches from a fresh
start. `available_seasons(input_dir)` returns the seasons found in a directory.
See `src/tennis_elo/export.py` for `ranking_rows`, `history_rows`,
`rankings_csv`, `history_csv`, `summary_dict`, and `write_outputs`.

## Optional dashboard

The local dashboard is an optional extra and is not required for the package or
CLI:

```bash
uv run --extra dashboard tennis-elo-dashboard
```

It serves on localhost by default. Importing `tennis_elo` never imports
Streamlit or pandas. The dashboard offers the same model choice as the CLI: a
tournament-weighting checkbox that is on by default, alongside the base K
factor, and switching it marks earlier calculations stale until they are
recalculated.

A chart shows the Elo rating over time of the top-ranked players (20 by
default). Set the startup count with `--top-players N` (1-50) or the
`TENNIS_ELO_TOP_PLAYERS` environment variable, and adjust it live with the
"Top players in chart" sidebar control (presentation only, no recalculation):

```bash
uv run --extra dashboard tennis-elo-dashboard --top-players 10
```

## Development

```bash
uv run --locked pytest -q
uv run --locked ruff check .
```
