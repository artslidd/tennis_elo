# Tournament Weighting Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Apply the operator-approved tournament coefficients to Elo K, with reproducible category metadata and explicit classic-Elo mode.

**Architecture:** Parent freezes backward-compatible dataclass additions and the coefficient table first. Four DeepSeek workers implement catalog/loader, replay/history, CLI/exports, and dashboard in isolated `.worktrees/weights-*` branches; parent cherry-picks bounded commits, verifies integration, and obtains independent Opus 5.5 spec and quality approval.

**Tech Stack:** Python 3.12+, standard library runtime, uv/pytest/Ruff; optional Streamlit/pandas dashboard.

**Spec:** `docs/superpowers/specs/2026-11-18-tournament-weighting.md` (authoritative). Existing P0/P1 rules continue unless explicitly changed there.

---

## Chunk 1: Contracts and parallel implementation

### Task 1: Parent-owned shared foundation

**Files:** modify `src/tennis_elo/models.py`, `tests/test_models.py`; create `src/tennis_elo/weighting.py`, `tests/test_weighting.py`.

- [x] Add failing tests for the default/disabled weighting flag and bool validation; appended Match/HistoryEntry fields; all eight canonical coefficients; rejection of invalid level keys. Added two config-overflow tests after Opus's suggestion.
- [x] Run `uv run --locked --extra dashboard pytest tests/test_models.py tests/test_weighting.py -q`: 11 existing tests passed, 23 new contract tests failed for missing features. Both added overflow tests also failed for the expected reasons before implementation.
- [x] Append contracts exactly as in the spec; implement a read-only coefficient mapping and exact lookup (plus proactive weighted effective-K overflow validation):

```python
TOURNAMENT_COEFFICIENTS = MappingProxyType({
    "challenger": 0.75, "atp_250": 1.0, "atp_500": 1.25,
    "masters_1000": 1.5, "atp_finals": 1.75, "grand_slam": 2.0,
    "other": 1.0, "unknown": 1.0,
})

def coefficient_for_level(level: str) -> float:
    try:
        return TOURNAMENT_COEFFICIENTS[level]
    except KeyError:
        raise ValueError(f"unknown tournament level: {level!r}") from None
```

- [x] Full `uv run --locked --extra dashboard pytest -q`: 340 passed; `uv run --locked --extra dashboard ruff check .`: clean. Commit only explicit foundation/doc paths. Existing replay is temporarily unweighted until Task 3.
- [x] Created `.worktrees/weights-catalog`, `weights-engine`, `weights-cli`, `weights-dashboard` at foundation `9f4f1ad` on corresponding `workers/weights-*` branches. Each exact worktree passed 340 tests and Ruff before its DeepSeek worker launched. Old worktrees and user CSVs untouched.

### Task 2: Catalog + loader (DeepSeek worker A)

**Exclusive files:** create `src/tennis_elo/tournaments.py`, `tests/test_tournaments.py`, `docs/tournament-levels.md`; modify `src/tennis_elo/data.py`, `tests/test_data.py`.

- [x] Classification tests first: all levels, year upgrades, normalization, nonstandard events, unsupported name/year, Challenger precedence. RED: missing `tournaments` module; loader subset 12 failed / 3 passed before tagging.
- [x] Implemented `classify_tournament(tournament: str, season_year: int, tour_type_human: str) -> str`, returning only canonical levels. Season-specific official sources and unsupported-year policy documented.
- [x] Loader adds classification only to eligible Match construction; filtering, structural validation and accounting unchanged.
- [x] Added 269 classifier + 16 loader tests; worker full suite 625 passed and Ruff clean. Parent integrated suite 727 passed / 0 skipped.
- [x] Audited all supplied 2023–2026 eligible labels: zero unknowns; intentional other events documented. `6d72ee0` integrated as `d2d6981`. All CSVs unmodified; 2023 read in place and remains untracked.

### Task 3: Replay + weighted history (DeepSeek worker B)

**Exclusive files:** modify `src/tennis_elo/ratings.py`, `tests/test_ratings.py`; optionally create `tests/test_weighted_ratings.py`. Do not modify `elo.py` unless a demonstrated weighted bug requires it and parent agrees.

- [x] Write equal-rating tier tests (winner gains 12/16/20/24/28/32 for Challenger/250/500/Masters/Finals/Slam at baseK32) and record RED: worker observed 43 failed / 7 existing-regression guards passed before implementation.
- [x] Per match ALWAYS validate with `coefficient_for_level(match.tournament_level)`, then use that coefficient when enabled or 1.0 when disabled; call the existing pure Elo update once with `config.k_factor * coefficient` for both sides. Test invalid categories in both modes. Shared config already rejects max-coefficient overflow before replay.
- [x] Fill classified level, APPLIED coefficient and actual effective K in both HistoryEntry records. Preserve raw IDs, precision, expected probabilities, chronology, names and counts.
- [x] Test mixed levels, custom base K, unweighted mode, history symmetry, conservation, deterministic/shuffled replay, fresh calls, invalid categories and effective-K overflow.
- [x] Worker `33230b5` integrated as `0fbd230`; parent reran `uv run --locked --extra dashboard pytest tests/test_elo.py tests/test_ratings.py tests/test_weighted_ratings.py -q`: 130 passed; Ruff clean. Worker full suite: 390 passed. Opus 5.5 APPROVED foundation/math spec and quality at frozen `0fbd230`: independent random-tier real-data replay (K32/R01500 and K20/R01200), max rating difference ≤4.5e-13, identical ordering, history K/weight/deltas and zero-sum verified; six classic windows bitwise equal to pre-feature core. Catalog acceptance remains pending. Optional nits left out of scope.

### Task 4: CLI + exports (DeepSeek worker C)

**Exclusive files:** `src/tennis_elo/cli.py`, `src/tennis_elo/export.py`, `tests/test_cli.py`, `tests/test_export.py`, `README.md`; `src/tennis_elo/api.py`/`tests/test_api.py` only if necessary.

- [x] Added tests for `--unweighted`, summary metadata, history columns and unknown notices; RED: 30 failed / 53 passed before implementation.
- [x] CLI creates `RatingConfig(use_tournament_weights=not args.unweighted)`, describes base/effective K and identifies the active model.
- [x] Appended actual history level/weight/effective-K keys; ranking columns, history guards and pre-filesystem validation preserved.
- [x] Added deterministic configuration and `tournament_weighting` metadata, canonical count keys, and year/name-sorted unknown records from eligible matches.
- [x] Visible unknown/fallback1 notices go to stdout, not exclusions/errors; README documents coefficients, catalog, default model, fresh comparisons and classic API/CLI examples.
- [x] Worker and parent owned tests: 83 passed; worker full suite 372 passed; Ruff clean. `7ee36d0` integrated as `01ed775`. No API source change necessary.

### Task 5: Dashboard (DeepSeek worker D)

**Exclusive files:** `src/tennis_elo/dashboard.py`, `src/tennis_elo/dashboard_views.py`, `tests/test_dashboard.py`, `docs/dashboard.md`. Launcher changes only if genuinely required; no CSS/assets/refactor.

- [ ] Write failing tests for a default-on weighting checkbox, config/signature changes, metadata/help, unknown warnings, history fields; record RED.
- [x] Config builder has default-on `use_tournament_weights`; sidebar sets it explicitly. Coefficient policy, base/effective K, raw-ID selection and prior P1 behavior preserved.
- [x] Frozen-config signatures include the mode; switching visibly stales the main run and hides old comparisons until recomputed.
- [x] Actual summary model/counts, unknown warnings and history level/weight/K shown. Missing legacy metadata is explicit, never fabricated.
- [x] Independent windows share the selected config; changing players reads cached rankings without recalculation. Verified with real-API spy assertions.
- [x] Parent 80 dashboard tests passed and Ruff clean; worker full suite 356 passed. `f9984f5` integrated as `2436b0e`; both additional parent real-API AppTests pass after catalog integration.

## Chunk 2: Integration, independent reviews and delivery

### Task 6: Parent integration

**Files:** parent-owned `tests/test_integration.py`; this plan/status; shared contracts only for coordinated fixes.

- [x] Inspected bounded worker diffs and cherry-picked all four. Targeted checks passed after each; integrated 727 passed / 0 skipped and Ruff clean at `50f1028`.
- [x] Added weighted/classic all-tier CLI subprocess cases; actual history/summary/unknown reporting and prior filesystem/error regressions pass.
- [x] All nine windows: classic full-precision players, rankings bytes and legacy history hashes exactly match pre-feature baselines. Independent weighted reference max error ≤4.55e-13; history/delta/K, conservation, accounting and unchanged input SHA256 verified.
- [x] Real-API AppTests prove Slam K64 vs classic K32, stale-state/cache invalidation, independent same-config windows, cached player switching, unknown warnings and actual history metadata; prior I1–I3/M1–M3 remain green.
- [x] Wheel/sdist built. Isolated no-dependency wheel install passes API/catalog and weighted/classic 2026 CLI/history/summary; classic rankings byte-identical. Missing dashboard extra gives actionable exit 1 without traceback. Bounded public launcher headless health HTTP200/ok, default loopback listener and complete process-group/IPv4/IPv6 port cleanup verified.

### Task 7: Independent acceptance

- [ ] Opus 5.5 reviews catalog/data/math/model changes against the spec, then quality; separate Opus 5.5 reviews CLI/export and dashboard integration, spec then quality. Reviewers are read-only; fresh snapshots must be explicit.
  - [x] Foundation/math approval at `0fbd230`.
  - [ ] Catalog/data and end-to-end weighted reference approval.
  - [ ] CLI/export approval.
  - [ ] Weighting dashboard approval.
- [ ] Address concrete Important findings test-first in owned worker lanes; integrate and obtain re-approval. Optional nits do not expand scope without justification.
- [ ] Fresh full tests, Ruff, builds and final working-tree inspection. Record exact results/approvals here and commit documentation explicitly, leaving the user's untracked 2023 CSV alone.
- [ ] Deliver usage, model semantics and results. No push, PR, merge to master, cleanup or remote changes.

## Execution status

- [x] Operator chose simple tiers and Challenger coefficient 0.75.
- [x] Season-upgrade and 2026-calendar source evidence collected from official ATP publications.
- [x] Opus 5.5 approved plan/spec and shared foundation design. Incorporated canonical validation in both modes, proactive effective-K overflow validation, and explicit Slam-qualifying coefficient 2.00 (already part of the selected parent-category policy).
- [x] Shared foundation committed at `9f4f1ad`; 340 tests and Ruff clean.
- [x] Four DeepSeek V4.1 Flash workers launched via Studio: catalog `e7aa36ec-e3d7-43c3-a43f-dd8c29ae013c`; engine `d95747c3-7e78-4ab4-ae97-517cad11978e`; CLI `e0abc52f-f5bb-4bd8-8abe-0653c1cf6cbe`; dashboard `05003d6d-b4f2-40e1-b560-6cac96ea6566`.
- [x] Parent-owned all-tier subprocess regressions added to `tests/test_integration.py` and observed RED before lane integration: weighted mode lacks warnings/weighted metadata; classic mode lacks `--unweighted`. Existing five malformed-CSV subprocess tests remain green. These expected interim failures are now resolved at `50f1028`. Interim full suite after engine+CLI integration: 422 passed / 2 expected failures, both now at classification counts (all rows still unknown before catalog); no other failures.
- [x] Captured pre-feature classic-Elo baselines for all nine windows at `.worktrees/weighting-baseline-2eie9qqp`: full-precision players, rankings CSVs, legacy history hashes, and input SHA256 manifest.
- [x] Interim check after replay/CLI integration (`01ed775`, before catalog): unweighted full-precision player records, rankings bytes and legacy-history hashes are EXACT for all nine windows; applied weight1/K32 and summary flag false verified. Input hashes unchanged. Post-catalog repetition and weighted reference now passed below; acceptance scripts/results are in the same artifact directory.
- [x] Four isolated implementation workers complete.
  - [x] Engine worker `01a1ee39-4457-72cf-8a5f-be0cb60c69e4`: `33230b5` → integrated `0fbd230`; parent 130 target tests/Ruff passed; Opus foundation/math spec+quality APPROVED at `0fbd230` (no Important findings).
  - [x] CLI worker `01a1ee39-43a3-73c9-8cc8-096c478443fd`: `7ee36d0` → integrated `01ed775`; parent 83 CLI/export tests/Ruff passed; Opus CLI/export review requested. Classification notices use stdout, with visible unknown/fallback1 content; no literal 'warning' prefix required.
  - [x] Catalog/loader worker `01a1ee39-44e9-74bc-a002-7f22438bbb74`: `6d72ee0` → integrated `d2d6981`; 285 new tests, 85 ATP Tour base names audited using season-specific ATP sources. All supplied 2023–26 eligible matches classified with zero unknowns. New 2023 CSV read in place, unchanged and untracked.
  - [x] Dashboard worker `01a1ee39-4443-774a-a9c9-98b01f172994`: `f9984f5` → integrated `2436b0e`; parent 80 dashboard tests/Ruff passed against integrated engine/export. Parent observed the known-tier AppTest RED at Slam winner 1516 vs required1532 before the classifier; both real-API cases now GREEN after catalog integration. Opus final weighting UI/config/cache/history/unknown-warning review requested at `50f1028`. README default-on checkbox wording matches final `Use tournament weights` control.
- [ ] Integration and independent Opus acceptance complete.
- [x] All four lanes integrated: parent full suite 727 passed / 0 skipped; Ruff clean. All four new parent CLI/AppTest integration cases now GREEN, including real Slam K64 versus classic K32, mode/cache invalidation, per-player comparisons and visible unknown fallback.
- [x] Post-catalog all-nine-window acceptance passed: classic full-precision players/rankings bytes/legacy history hashes EXACT; independent weighted reference max difference ≤4.55e-13; history pair weight/effective-K/delta consistency, accounting, zero-sum totals and input SHA256 unchanged. Results artifact `.worktrees/weighting-baseline-2eie9qqp/weighted-verification.json`.
- [x] Six additional retirement-excluded real-data cases passed: weighted/classic at K20/R01200 for 2026, 2025–26 and 2024–26. Original excluded-retirement match/player counts preserved (15042/1846, 28960/2259, 42728/2635); every paired history entry checked against independent pre-match probabilities, deltas, actual K/weight and final ratings. Max difference ≤2.28e-13; accounting, summary and conservation pass.
- [x] Packaging/base-install/public-launcher verification passed at `50f1028`; isolated wheel harness `.worktrees/weighting-baseline-2eie9qqp/verify_installed_package.py`. Fresh final acceptance still awaits three Opus verdicts (catalog/data, CLI/export, weighting UI); foundation/math is approved.
- [x] Original P1 UI received final Opus 5.5 spec/quality approval at `a1b9823` (315 tests, no skips, real-API scenarios, headless health/cleanup); original P0/P1 acceptance gates now pass. This is not acceptance of the new weighting deltas.
