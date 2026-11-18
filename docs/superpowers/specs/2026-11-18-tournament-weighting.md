# Tournament-weighted Elo

## Approved behavior

The operator requested tournament weights, then selected the simple tier scale and Challenger coefficient 0.75. Apply `effective_k = config.k_factor * coefficient` to BOTH players using the same pre-match ratings. Do not multiply ratings or expected probabilities. Preserve zero-sum updates, ordering, eligibility, deduplication, fresh-state season windows and full internal precision.

| Canonical level | Coefficient |
|---|---:|
| `challenger` | 0.75 |
| `atp_250` | 1.00 |
| `atp_500` | 1.25 |
| `masters_1000` | 1.50 |
| `atp_finals` | 1.75 |
| `grand_slam` | 2.00 |
| `other` | 1.00 |
| `unknown` | 1.00 |

Weighting is enabled by default. `RatingConfig(use_tournament_weights=False)`, CLI `--unweighted`, and a dashboard checkbox provide an explicit classic-Elo comparison. `k_factor` always means BASE K. Each comparison window uses the same current configuration, but starts fresh.

## Classification

The CSV has no category column. Use a deterministic, bundled, dependency-free, SEASON-AWARE catalog for the supplied 2023–2026 seasons; no network calls during calculation. Tour classification comes first: ATP Challenger matches always use `challenger`, even when their city also has an ATP Tour event. Qualifying inherits the parent tournament category, as included in the operator-selected policy. This intentionally gives Grand Slam qualifying the same 2.00 coefficient as its main draw. Normalize only known label decorations (Qualification, Play Offs, Preliminary, indoor); use explicit aliases, not fuzzy city matching or 'anything not a Slam is ATP 250'.

Classify Dallas, Doha and Munich as ATP 250 in 2023–24 and ATP 500 in 2025–26. Distinguish ATP Finals (Turin) from Next Gen Finals. Team/nonstandard events (United Cup, Davis Cup, Hopman/Laver Cup, Olympics, Asian Games, Next Gen Finals, US Open WIC) use `other` coefficient 1.00. WIC is not ordinary Grand Slam qualifying. Unsupported names/years use `unknown` coefficient 1.00 and MUST be reported in summaries and user-facing CLI/dashboard warnings; never silently label them ATP 250. Missing optional tournament names remain valid unknowns.

Document category sources and supported years. Prefer official ATP calendars and event/category announcements. All eligible supplied events should be explicitly mapped or intentionally identified as other; do not guess solely to reach zero unknowns. New user-added `2023-atp-season.csv` is untracked input: read it, do not change or commit it.

Initial public evidence:
- https://www.atptour.com/en/news/atp-500-upgrades-from-2025 (Dallas/Doha/Munich upgrades)
- https://www.atptour.com/-/media/files/media-guide/2025/2025-atp-media-guide-full-final.pdf
- https://www.atptour.com/en/news/what-is-the-2026-atp-tour-calendar/
- https://www.atptour.com/-/media/sites/atp-tour/press/press-releases/2026-atp-tour-calendar-announced.pdf

## Shared contracts (parent-owned)

- Append `RatingConfig.use_tournament_weights: bool = True`; validate that this option is bool. When weighting is enabled, reject a base K whose product with the maximum coefficient is non-finite before reading data; unweighted mode only requires finite positive base K.
- Append `Match.tournament_level: str = "unknown"`. Existing manually constructed Match objects retain coefficient 1 unless tagged explicitly.
- Append HistoryEntry fields `tournament_level: str = "unknown"`, `tournament_weight: float = 1.0`, `effective_k_factor: float = 32.0`. Replay ALWAYS fills actual values; default values only preserve construction compatibility. Unweighted history retains the classified level but records weight 1.0 and actual base K.
- `weighting.TOURNAMENT_COEFFICIENTS`: read-only mapping of the canonical levels above.
- `weighting.coefficient_for_level(level: str) -> float`: exact canonical lookup; reject invalid level keys with contextual ValueError rather than quietly accepting typos. The canonical `unknown` level is the explicit fallback. Replay validates canonical levels in both weighted and unweighted modes, then uses applied coefficient 1.0 when disabled.
- `tournaments.classify_tournament(tournament: str, season_year: int, tour_type_human: str) -> str`: returns a canonical level. Loader sets it on each eligible Match; no new eligibility/exclusion policy.

## Reporting

History CSV/API rows and the dashboard history show tournament level, applied coefficient and effective K. Rankings columns remain unchanged. Summary configuration includes the weighting flag; a `tournament_weighting` section records enabled status, the coefficient table, match counts by level, unknown match count, and sorted unknown tournament names (include season context). Reporting is deterministic and does not alter replay.

CLI help/output and dashboard explain base versus effective K and show whether weighting is enabled. Unknown classification warnings must remain visible; the JSON summary retains full details. History export guards and safe filesystem behavior remain intact. Base package remains standard-library-only; dashboard remains optional. Do not bundle or edit input CSVs for this feature.

## Acceptance

- Equal initial ratings, base K32: winner gains 12 at Challenger, 16 at ATP250, 20 at ATP500, 24 at Masters, 28 at Finals and 32 at Slam; loser loses exactly the same amount.
- Unweighted mode reproduces pre-feature results (within floating-point tolerance and identical ordering/counts) for all original 1/2/3-season windows; recent baseline match/player counts 15575/1852, 30021/2265, 44257/2642.
- Mixed-level histories reconcile applied coefficient, K and deltas for both players; deterministic repeat/shuffled replay and fresh windows remain true.
- Category regression tests cover season upgrades, Toronto/Montreal, qualification/indoor/playoff suffixes, Finals versus Next Gen, Challenger precedence, unknown/missing labels and unsupported years.
- CLI/API/summary/history and dashboard configure/report the same model. Dashboard cache signatures distinguish weighted from unweighted; switching the mode makes prior calculations stale and recalculation refreshes comparisons.
- All supplied 2023–2026 inputs are audited without edits; match eligibility counts must not change.
- DeepSeek V4.1 Flash implementation workers, separate local ignored worktrees, Opus 5.5 independent spec and quality review. Current P0/P1 approvals only cover their earlier snapshots; new weighting changes need fresh approval.
- No push, PR, merge to master or worktree deletion without operator permission.
