# Tennis Elo

Reproducible, independently reset tennis Elo ratings from `*-atp-season.csv`
data, with a standard-library Python package, a command-line interface, and an
optional local Streamlit dashboard.

Ratings use standard base-10 Elo (scale 400, default K = 32). Players are keyed
by their string IDs, not names, and the latest observed name is displayed.

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

`python -m tennis_elo` works exactly like the `tennis-elo` console script:

```bash
uv run python -m tennis_elo rank --seasons 2025 2026 --history
```

## Fresh-start reset semantics

Each calculation is a **fresh start**: every player begins at the configured
`--initial-rating` (default 1500), and only matches from the selected seasons
are replayed in chronological order. Ratings are carried between seasons *within*
the selection, but never imported from seasons outside it.

This means `--seasons 2026` and `--seasons 2024 2025 2026` are two independent
calculations that both start from the initial rating; the longer window is not a
continuation of the shorter one. The summary JSON marks this explicitly with
`fresh_start`, `fresh_start_note`, and the configuration used.

## Options

| Option | Default | Meaning |
| --- | --- | --- |
| `--seasons YEAR [YEAR ...]` | required | One to three distinct consecutive seasons. |
| `--input-dir DIR` | `.` | Directory containing `*-atp-season.csv` files. |
| `--output-dir DIR` | `outputs/<selected-years>` | Fresh output directory. |
| `--initial-rating FLOAT` | `1500` | Starting rating for every player. |
| `--k-factor FLOAT` | `32` | Elo K factor; must be finite and positive. |
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
  with every history field plus a UTC `date` column.
- `summary.json` — `seasons`, `configuration`, `input_files`,
  `available_seasons`, `rows_read`, `selected_rows`, `matches_processed`,
  `players_rated`, `duplicate_rows`, `excluded_counts`, `history_included`, and
  the explicit fresh-start fields.

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

print(available_seasons("data"))          # (2024, 2025, 2026)

result = calculate(
    "data",
    [2025, 2026],
    config=RatingConfig(initial_rating=1500, k_factor=32, include_retirements=True),
    include_history=True,
)

for player in result.ratings.players[:5]:
    print(player.player_id, player.name, round(player.rating, 1))

write_outputs(result, "reports/2025-2026", include_history=True)
```

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
Streamlit or pandas.

## Development

```bash
uv run --locked pytest -q
uv run --locked ruff check .
```
