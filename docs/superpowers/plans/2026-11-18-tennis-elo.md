# Tennis Elo Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement independently reset one-, two-, and three-season tennis Elo, a P0 Python package/CLI, and a P1 local dashboard.

**Architecture:** Immutable shared dataclasses define component boundaries. Four independent Git worktrees own CSV ingestion, pure Elo replay, API/CLI/exports, and dashboard presentation. The parent integrates P0 before P1 and runs end-to-end verification; workers never merge other lanes or touch the parent checkout.

**Tech Stack:** Python 3.12+, standard-library P0, uv, pytest, ruff; optional Streamlit and pandas for P1.

**Specification:** `docs/superpowers/specs/2026-11-18-tennis-elo-design.md`.

---

## Execution status

- [x] Baseline and shared contracts committed; four isolated implementation worktrees created.
- [x] DeepSeek V4.1 Flash workers implemented data, engine, API/CLI, and dashboard lanes.
- [x] P0 integrated before P1; strict season/timestamp validation regressions fixed.
- [x] Initial integrated verification: 279 tests passed, Ruff clean, source/wheel builds passed.
- [x] Real-data CLI and interactive dashboard checks passed for all three window sizes.
- [x] Isolated base install and bounded localhost server health/cleanup checks passed.
- [x] P0 review follow-ups integrated: structural CSV validation, history-export guard, and reporting metadata; 303 integrated tests passed.
- [x] Opus 5.5 API/CLI/export spec and quality approval at `4e16e0d`; all findings resolved.
- [x] Opus 5.5 core/data/math spec and quality approval at `4e16e0d`; P0 has no blocking findings. Parent rerun: 251 P0 tests passed, Ruff clean, wheel/source builds passed.
- [x] P1 revisions integrated at `a1b9823`: stable-ID selection, carry/reset wording, selected-player window comparison, directory presets, and temporal chart. Parent verification: 315 tests passed, Ruff clean, real-API synthetic UI scenarios passed.
- [x] Opus 5.5 dashboard spec and quality approval at `a1b9823`: 315 tests, Ruff/format clean, independent real-API AppTest regressions and bounded launcher health/cleanup passed; no blocking findings. Subsequent tournament-weighting feature is tracked in its separate plan.
- [ ] Final full-suite/build/smoke verification and delivery report.

Reviewer policy: implementation workers stay on DeepSeek V4.1 Flash; independent
acceptance reviewers must use Opus 5.5. Superseded DeepSeek approvals do not count.

## Chunk 1: Baseline and parallel foundations

### Task 1: Parent-owned immutable contracts and baseline

**Files:** models.py, tests/test_models.py, pyproject.toml, .gitignore, this plan, design spec.

- [ ] Add model tests for default/invalid configuration, dataclass construction, immutability, and tuple collections.
- [ ] Run `uv run pytest tests/test_models.py -q` and confirm failure because contracts are missing.
- [ ] Implement only the immutable contracts described by the spec, including finite initial rating and finite positive K validation.
- [ ] Run `uv run pytest tests/test_models.py -q` and `uv run ruff check src/tennis_elo/models.py tests/test_models.py`.
- [ ] Commit a baseline snapshot of the existing project, data, contracts, tests, and optional dependency configuration.
- [ ] Verify `.worktrees/` is ignored, then create branches/worktrees `workers/data`, `workers/engine`, `workers/cli`, `workers/dashboard`.
- [ ] Launch all four workers as Studio conversation sessions on exact provider/model `ai-gw-logical/deepseek-v4-1-flash`, with each cwd its worktree. No nested delegation.

### Task 2: Data worker — P0 CSV ingestion

**Create:** src/tennis_elo/data.py, tests/test_data.py.
**Read only:** models.py, design spec, existing CSVs.
**Do not modify:** shared models, pyproject.toml, uv.lock, other lanes' files.

- [ ] Write fixtures and failing discovery, schema, and season-selection tests first.
- [ ] Implement discover_csv_files and available_seasons from actual season_year values.
- [ ] Test December 2023 rows assigned to season 2024; no filtering by calendar date.
- [ ] Add fail-first tests for each match status, tour, valid/invalid winner, retirement toggle, malformed eligible row, and source context.
- [ ] Implement selected-season deduplication and reject conflicting match IDs.
- [ ] Check `selected_rows == len(matches) + sum(excluded_counts.values()) + duplicate_rows`.
- [ ] Assert shuffled CSV paths and rows yield the same sorted matches.
- [ ] Run `uv run pytest tests/test_models.py tests/test_data.py -q` and scoped ruff.
- [ ] Smoke-load real CSVs without modifying them and report eligible/excluded counts.
- [ ] Self-review for spec compliance and quality, commit only owned files, and message parent with SHA, tests, counts, concerns.

### Task 3: Engine worker — P0 pure math and replay

**Create:** src/tennis_elo/elo.py, src/tennis_elo/ratings.py, tests/test_elo.py, tests/test_ratings.py.
**Read only:** models.py, design spec.

- [ ] Write failing expected_score and update_ratings tests, including 1500/1500 -> 1516/1484, upset/expected wins, finite checks, zero-sum, overflow-safe extreme differences, invalid winners/K.
- [ ] Implement stable standard Elo arithmetic and run math tests.
- [ ] Write failing replay tests: order invariance, independent resets, pre-match paired updates, aliases keyed by ID, statistics, optional history, zero matches, no input mutation.
- [ ] Implement local mutable accumulators with immutable output; sort defensively and return players sorted by rating then ID.
- [ ] History uses one entry per player per match, storing opponent pre-rating, expected score, outcome, and final rating.
- [ ] Run `uv run pytest tests/test_models.py tests/test_elo.py tests/test_ratings.py -q` and scoped ruff.
- [ ] Self-review for spec compliance and quality, commit only owned files, and message parent with SHA, tests, concerns.

## Chunk 2: Parallel application surfaces

### Task 4: API/CLI worker — P0 orchestration and exports

**Create:** src/tennis_elo/api.py, cli.py, export.py, __main__.py; tests/test_api.py, test_cli.py, test_export.py; README.md.
**May modify:** src/tennis_elo/__init__.py to remove the placeholder and expose lightweight public types.
**Do not modify:** models.py, pyproject.toml, uv.lock, dashboard or other lanes' code.

- [ ] Build small CalculationResult fixtures with the shared models; write failing ranking/history/summary serialization tests.
- [ ] Implement export functions and UTC presentation, deterministic order, safe non-overwriting output directories, all-player defaults and optional history.
- [ ] Write validation tests for empty/duplicate/nonconsecutive/more-than-three selections, bad config, unavailable seasons, directory errors.
- [ ] Implement calculate and available_seasons; import engine/data dependencies inside orchestration functions so isolated export/CLI unit tests can run before sibling integration.
- [ ] Write CLI tests using main(argv=None) -> int and monkeypatch api.calculate for isolated unit tests; no fake replacement modules.
- [ ] Implement argparse rank command, all documented options, friendly errors, top-20 table, output summary; __main__ raises SystemExit(main()).
- [ ] Test that base package/API/CLI imports do not require Streamlit/pandas.
- [ ] Add integration tests on synthetic CSVs. They may remain pending sibling availability in the isolated lane; report this transparently and run them after integration.
- [ ] README covers setup, exact 1/2/3-season commands, reset semantics, match policies, outputs, custom K, Python API and optional dashboard install/run.
- [ ] Run independently executable tests and scoped ruff; self-review, commit only owned files, message parent with SHA and any integration-only tests pending.

### Task 5: Dashboard worker — P1 optional local UI

**Create:** src/tennis_elo/dashboard.py, dashboard_launcher.py, optional dashboard_views.py; tests/test_dashboard.py; optional docs/dashboard.md.
**Read only:** models.py, design spec, pyproject.toml.
**Do not modify:** README.md, API/CLI/export/data/engine/shared files, dependencies or lockfile.

- [ ] Read current Streamlit API docs when necessary; use installed APIs and AppTest rather than guessing.
- [ ] Write failing pure view-helper tests for search/min-match filtering, player-ID disambiguation and window availability/labeling.
- [ ] Implement pure helpers and UI state defaults; keep sibling API/export imports inside runtime calculation functions to avoid import-time dependency failures in isolated tests.
- [ ] Add sidebar data path, discovered season selection/presets, initial rating, K, retirement toggle, and min matches.
- [ ] Call public api.calculate with history enabled; show clear errors, run metadata, exclusions, leaderboard, selected-player statistics/chart/history and CSV downloads.
- [ ] Window comparison uses separate calculations ending at chosen season; missing windows unavailable and fresh-start caveat visible.
- [ ] Add launcher using Streamlit CLI with package file path and localhost default; missing optional dependencies yield an actionable installation message.
- [ ] Test safe launcher argument construction and no import-time Streamlit dependency in the base package. Add AppTest when dependencies/sibling API are available; no long-lived server left running.
- [ ] Run standalone tests and scoped ruff, report integration tests pending sibling code honestly, self-review, commit only owned files, message parent SHA and results.

## Chunk 3: Parent integration and independent acceptance

### Task 6: Integrate and validate P0

- [ ] Read each worker diff and verify edit boundaries and commits before integration.
- [ ] Cherry-pick data, engine, CLI commits onto an integration branch (not master).
- [ ] Run `uv run pytest tests/test_models.py tests/test_data.py tests/test_elo.py tests/test_ratings.py tests/test_api.py tests/test_cli.py tests/test_export.py -q`.
- [ ] For an integration defect: reproduce with a failing regression test, fix its root cause, rerun affected and full tests.
- [ ] Run real-data CLI for 2026, 2025–2026, 2024–2026 with history into fresh temporary paths; inspect JSON accounting, ratings/rows, reproducibility and independent resets.
- [ ] Run `uv build`; verify help and `python -m tennis_elo` entry points, and a minimal base install without dashboard dependencies.
- [ ] Do not declare P0 complete until tests and real-data commands pass.

### Task 7: Integrate and validate P1

- [ ] Cherry-pick dashboard worker commit after P0 acceptance.
- [ ] Run `uv sync --extra dashboard --dev`, `uv run pytest -q`, `uv run ruff check .`, and `uv build`.
- [ ] Run Streamlit AppTest over the integrated app using synthetic fixtures and at least a real-data smoke case if feasible.
- [ ] Launch a bounded localhost headless dashboard, request its health endpoint, terminate the exact child process and wait for it to exit.
- [ ] Obtain independent spec compliance review, address findings, then independent quality review; no reviewer edits production files.
- [ ] Record actual results and remaining limitations. Preserve worker worktrees unless the operator requests cleanup; do not push or open a PR without authorization.
