# Tennis Elo design

## Approved scope

P0 is a reusable Python package plus CLI. P1 is a local Streamlit web dashboard.
The operator approved implementing both using parallel DeepSeek V4.1 Flash workers
in separate project-local `.worktrees/` directories. The parent integrates P0
before P1, reviews the combined changes, and performs final validation.

## Rating semantics

- Select one, two, or three distinct seasons explicitly; years must be consecutive.
- `season_year` is authoritative: some 2024-season matches took place in December 2023.
- Start every player at 1500 independently for each calculation. Carry ratings
  between selected seasons only. Never import ratings from outside the selection.
- Standard base-10 Elo with scale 400, constant K=32 by default, configurable.
- Update both players from their pre-match ratings; retain full internal precision.
- No inactivity decay, surface weighting, tournament weighting, or score weighting.
- Use string player IDs, not names, as identities. Display the latest observed name.
- Chronological order is `(timestamp, match_id)`; string match IDs break ties
  reproducibly but do not claim to recover unknown actual match order.
- Rankings include every player in an eligible match in the supplied data, not
  every professional worldwide. Reporting-only minimum-match filters never alter
  Elo updates. Sort rankings by descending Elo then player ID.

## Data policies

Read `*-atp-season.csv` from an explicit input directory (default current directory).
The supplied data contains 45,190 raw records across seasons 2024, 2025, and 2026.
Required CSV columns are match_id, season_year, date_timestamp, tour_type_human,
status, status_extra, home_id, away_id, home_name, away_name, winner_code.
Tournament, round, and surface are optional descriptive fields.

Include ATP Tour and ATP Chall, including qualifying. Include normally finished
matches and retirements with winner code 1 (home) or 2 (away). Allow retirements to
be excluded. Exclude exhibitions, unsupported tours, walkovers, awarded, canceled,
scheduled, unfinished, and invalid-winner records with explicit reason counts.
Use status_extra when populated, not status alone: some canceled records have
status FINISHED. If status_extra is blank, fall back to status. No inferred winner
from score or ATP rank. Surface can be unknown.

Deduplicate selected-season rows by match_id using all Elo-relevant columns
(required and optional descriptive fields). Ignore identical signatures, count
them, and reject conflicting signatures; differences solely in unused betting,
ranking or score statistics do not change the Elo input. Reject malformed
eligible rows with file/row context (bad timestamp, missing IDs, same player on
both sides, etc.). Timestamps must be integer seconds representable as a UTC
Python datetime; reject millisecond epochs and out-of-range values rather than
letting later exports fail. Season selections must contain actual integers, not
booleans or coerced/truncated floats.
Detect unavailable requested seasons rather than silently shortening a window.
Decode UTF-8 with BOM support, and handle quoted CSV correctly.

For accounting, rows_read counts all physical records read, selected_rows counts
raw selected-season records before deduplication, and duplicate_rows counts
ignored selected-season duplicates. For a successful load:

`selected_rows == len(matches) + sum(excluded_counts.values()) + duplicate_rows`.

## Architecture

The immutable contracts in `src/tennis_elo/models.py` are shared by all lanes.
Data loading and Elo replay do not import CLI or dashboard packages. P0 uses only
Python's standard library at runtime. Streamlit and pandas are optional extras.

- data.py: discover CSVs, discover available seasons, load/validate/filter/sort.
- elo.py: pure expected-score and two-player update functions.
- ratings.py: replay eligible matches, player aggregates, optional history.
- api.py: orchestrate loading and replay; public calculation entry point.
- export.py: ranking/history rows, CSV text, JSON summary, output files.
- cli.py + __main__.py: argparse entry point, friendly errors, terminal rankings.
- dashboard.py + dashboard_launcher.py: optional Streamlit UI and console launcher.
- dashboard_views.py: pure dashboard filtering/comparison helpers if needed.

## Shared public interfaces

Exact model fields are defined in models.py. Implement the following signatures
without adding competing alternative APIs:

```python
# data.py
# Raise ValueError for invalid data/selections and OSError for filesystem errors.
def discover_csv_files(input_dir: str | Path) -> tuple[Path, ...]: ...
def available_seasons(input_dir: str | Path) -> tuple[int, ...]: ...
def load_matches(paths: Iterable[str | Path], seasons: Iterable[int], *,
                 include_retirements: bool = True) -> LoadResult: ...

# elo.py
# Validate finite ratings, positive finite K, and winner_code in {1, 2}.
def expected_score(rating: float, opponent_rating: float) -> float: ...
def update_ratings(home_rating: float, away_rating: float, winner_code: int, *,
                   k_factor: float = 32.0) -> tuple[float, float]: ...

# ratings.py
# Return fresh state each call, defensively sort matches; do not mutate inputs.
def rate_matches(matches: Iterable[Match], config: RatingConfig | None = None, *,
                 include_history: bool = False) -> RatingResult: ...

# api.py
# Normalize and validate one to three distinct consecutive selected seasons.
def calculate(input_dir: str | Path, seasons: Iterable[int], *,
              config: RatingConfig | None = None,
              include_history: bool = False) -> CalculationResult: ...
def available_seasons(input_dir: str | Path) -> tuple[int, ...]: ...

# export.py
# All player rows contain rank, player_id, name, rating, matches, wins, losses,
# first_match_date, last_match_date (UTC ISO dates). Round Elo only in presentation.
def ranking_rows(result: CalculationResult, *, min_matches: int = 0) -> list[dict]: ...
def history_rows(result: CalculationResult) -> list[dict]: ...
def rankings_csv(result: CalculationResult, *, min_matches: int = 0) -> str: ...
def history_csv(result: CalculationResult) -> str: ...
def summary_dict(result: CalculationResult) -> dict: ...
def write_outputs(result: CalculationResult, output_dir: str | Path, *,
                  min_matches: int = 0, include_history: bool = False
                  ) -> dict[str, Path]: ...
```

History CSV includes every HistoryEntry field and a UTC ISO `date` column.
Summary JSON contains seasons, configuration, input_files, available_seasons,
rows_read, selected_rows, matches_processed, players_rated, duplicate_rows,
excluded_counts, history_included. Mark fresh-start semantics explicitly.

## P0 user experience

```
uv run tennis-elo rank --seasons 2026
uv run tennis-elo rank --seasons 2025 2026
uv run tennis-elo rank --seasons 2024 2025 2026 --history
```

Options: --input-dir, --output-dir, --initial-rating, --k-factor,
--exclude-retirements, --history, --min-matches, --top (default 20).
Default output: outputs/<selected-years>; reject non-empty output directories
rather than silently overwriting earlier runs. Empty directories are usable.
Export all players by default. Header-only exports for zero eligible matches are
valid and summaries explain exclusions. CLI errors return nonzero without a
traceback for expected validation/filesystem problems. `python -m tennis_elo`
also works. Importing tennis_elo must not import Streamlit or pandas.

## P1 user experience

Launch: `uv run --extra dashboard tennis-elo-dashboard` (localhost by default).
Support data-directory input, discovered-season selection, one/two/three season
presets, and explicit season selection validated by the same API. Controls for
K, initial rating, retirement policy, and minimum matches. Show searchable,
sortable leaderboard, exclusion summary, player selector keyed by stable ID,
player rating chart and match history, downloadable rankings/history.

Compare independent one-, two-, and three-season calculations ending at a chosen
season. If earlier seasons are unavailable, label those windows unavailable;
do not mislabel a shorter calculation as a longer window. Explain that all
windows independently start from the initial rating, not continuous annual Elo
changes. No remote deployment or authentication in P1. Avoid HTML injection from
CSV names; rely on safe Streamlit widgets. Do not launch a long-lived server
while implementing; use Streamlit AppTest and a bounded headless smoke test.

## Verification and acceptance

Use test-first development with synthetic, small CSV fixtures. Cover Elo 1516 /
1484 from equal players; zero-sum updates; extreme rating differences; sorting;
season boundaries; resets; aliases; duplicate/conflicting matches; status_extra
filtering; malformed schema/rows; missing seasons; CLI exports and error paths;
optional-dependency isolation; dashboard helpers and AppTest where available.

After integration, run pytest and ruff, build the package, compute real-data
rankings for 2026, 2025–2026, and 2024–2026 into a temporary directory, inspect
summaries and count accounting, test installed entry points, and check the
headless dashboard responds without leaking a running process.
