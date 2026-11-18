# Tournament levels and coefficients

`tennis_elo.tournaments.classify_tournament(tournament, season_year, tour_type_human)` turns one
season-CSV row into a canonical tournament level. `tennis_elo.data.load_matches` calls it for every
eligible row and stores the result in `Match.tournament_level`; `tennis_elo.weighting` turns that
level into the coefficient applied to the base K-factor. Nothing else classifies tournaments, and
classification never performs a network call or reads a file.

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

The coefficients live in `src/tennis_elo/weighting.py` (`TOURNAMENT_COEFFICIENTS`,
`coefficient_for_level`). This document describes the catalog in `src/tennis_elo/tournaments.py`.

## How a row is classified

`classify_tournament` applies these rules in order and returns at the first match:

1. `tour_type_human` contains `chall` (case-insensitive): `challenger`. The Challenger tour is a
   tour-level fact, so it wins over any event or city name and does not depend on the season. A
   Challenger in a city that also hosts an ATP Tour event (Hamburg, Lyon, Athens, Montreal, Dallas)
   stays `challenger`.
2. `tour_type_human` contains `exhib`: `other` (the loader already excludes those rows).
3. `season_year` is not 2023-2026: `unknown`. The bundled catalog only covers the supplied seasons.
4. The raw label contains the token `WIC`: `other`. This check runs **before** normalization so that
   `US Open ATP - WIC` is not mistaken for the US Open; it is not Grand Slam qualifying.
5. Otherwise the label is normalized, dropping only known decorations: `(indoor)`, a trailing
   `- Qualification`, `- Play Offs` or `- Preliminary` segment, and a trailing `ATP` marker.
   Matching is case-insensitive and whitespace is collapsed, but there is no fuzzy city or
   substring matching, and unknown suffixes make the label unknown. Because qualifying is stripped
   rather than mapped, ordinary qualifying inherits its parent event's category; Grand Slam
   qualifying therefore also weighs 2.00, while the ATP 250/500/1000 and ATP Finals qualifiers and
   play-offs inherit their own event.
6. An empty label (the optional `tournament` column is absent) is `unknown`.
7. A normalized label starting with `Davis Cup` is `other` (World Group, World Group I, World Group
   II, Play Offs, Qualification and Preliminary all share that prefix).
8. An exact catalog hit for that season is the level. Everything else is `unknown`; unsupported
   names are never guessed as ATP 250.

## Catalog by season

Every event below is listed for the seasons in which it was actually played at that level. `other`
additionally covers the Davis Cup prefix described above.

**2023**

- `grand_slam` (4): Australian Open, French Open, Wimbledon, US Open
- `masters_1000` (9): Cincinnati, Indian Wells, Madrid, Miami, Monte Carlo, Paris, Rome, Shanghai, Toronto
- `atp_500` (13): Acapulco, Barcelona, Basel, Beijing, Dubai, Halle, Hamburg, London, Rio de Janeiro, Rotterdam, Tokyo, Vienna, Washington
- `atp_250` (38): Adelaide, Adelaide 2, Antwerp, Astana, Atlanta, Auckland, Banja Luka, Bastad, Buenos Aires, Chengdu, Cordoba, Dallas, Delray Beach, Doha, Eastbourne, Estoril, Geneva, Gstaad, Hertogenbosch, Houston, Kitzbuhel, Los Cabos, Lyon, Mallorca, Marrakech, Marseille, Metz, Montpellier, Munich, Newport, Pune, Santiago, Sofia, Stockholm, Stuttgart, Umag, Winston-Salem, Zhuhai
- `atp_finals` (1): Finals - Turin
- `other` (5): Asian Games, Hopman Cup, Laver Cup, Next Gen Finals - Jeddah, United Cup

**2024**

- `grand_slam` (4): Australian Open, French Open, Wimbledon, US Open
- `masters_1000` (9): Cincinnati, Indian Wells, Madrid, Miami, Monte Carlo, Montreal, Paris, Rome, Shanghai
- `atp_500` (13): Acapulco, Barcelona, Basel, Beijing, Dubai, Halle, Hamburg, London, Rio de Janeiro, Rotterdam, Tokyo, Vienna, Washington
- `atp_250` (38): Adelaide, Almaty, Antwerp, Atlanta, Auckland, Bastad, Belgrade 2, Brisbane, Bucharest, Buenos Aires, Chengdu, Cordoba, Dallas, Delray Beach, Doha, Eastbourne, Estoril, Geneva, Gstaad, Hangzhou, Hertogenbosch, Hong Kong, Houston, Kitzbuhel, Los Cabos, Lyon, Mallorca, Marrakech, Marseille, Metz, Montpellier, Munich, Newport, Santiago, Stockholm, Stuttgart, Umag, Winston-Salem
- `atp_finals` (1): Finals - Turin
- `other` (5): Laver Cup, Next Gen Finals - Jeddah, Olympic Games, Six Kings Slam Exhibition Men, United Cup

**2025**

- `grand_slam` (4): Australian Open, French Open, Wimbledon, US Open
- `masters_1000` (9): Cincinnati, Indian Wells, Madrid, Miami, Monte Carlo, Paris, Rome, Shanghai, Toronto
- `atp_500` (16): Acapulco, Barcelona, Basel, Beijing, Dallas, Doha, Dubai, Halle, Hamburg, London, Munich, Rio de Janeiro, Rotterdam, Tokyo, Vienna, Washington
- `atp_250` (30): Adelaide, Almaty, Athens, Auckland, Bastad, Brisbane, Brussels, Bucharest, Buenos Aires, Chengdu, Delray Beach, Eastbourne, Geneva, Gstaad, Hangzhou, Hertogenbosch, Hong Kong, Houston, Kitzbuhel, Los Cabos, Mallorca, Marrakech, Marseille, Metz, Montpellier, Santiago, Stockholm, Stuttgart, Umag, Winston-Salem
- `atp_finals` (1): Finals - Turin
- `other` (4): Hopman Cup, Laver Cup, Next Gen Finals - Jeddah, United Cup

**2026**

- `grand_slam` (4): Australian Open, French Open, Wimbledon, US Open
- `masters_1000` (9): Cincinnati, Indian Wells, Madrid, Miami, Monte Carlo, Montreal, Paris, Rome, Shanghai
- `atp_500` (16): Acapulco, Barcelona, Basel, Beijing, Dallas, Doha, Dubai, Halle, Hamburg, London, Munich, Rio de Janeiro, Rotterdam, Tokyo, Vienna, Washington
- `atp_250` (29): Adelaide, Almaty, Auckland, Bastad, Brisbane, Brussels, Bucharest, Buenos Aires, Chengdu, Delray Beach, Eastbourne, Estoril, Geneva, Gstaad, Hangzhou, Hertogenbosch, Hong Kong, Houston, Kitzbuhel, Los Cabos, Lyon, Mallorca, Marrakech, Montpellier, Santiago, Stockholm, Stuttgart, Umag, Winston-Salem
- `atp_finals` (1): Finals - Turin
- `other` (2): Laver Cup, United Cup

## Season changes the catalog encodes

| Change | Seasons | Effect |
|---|---|---|
| Dallas, Doha, Munich upgraded ATP 250 -> ATP 500 | 250 in 2023-24, 500 in 2025-26 | The same label maps to different levels in different seasons, so `classify_tournament` needs `season_year`. |
| Toronto / Montreal alternation (shared Masters 1000 slot) | Toronto 2023 & 2025, Montreal 2024 & 2026 | The city that did not host is `unknown`, not `masters_1000`. |
| Astana -> Almaty relocation | Astana 2023, Almaty 2024-26 | `Astana ATP` after 2023 is `unknown`. |
| Antwerp -> Brussels relocation | Antwerp 2023-24, Brussels 2025-26 | `Antwerp ATP` after 2024 is `unknown`. |
| Sofia -> Belgrade -> Athens relocation | Sofia 2023, Belgrade 2 2024, Athens 2025 | One ATP 250 licence, three names; each only in its own season. |
| Marseille -> Lyon relocation (moved to an indoor October slot) | Marseille 2023-25, Lyon (indoor) 2026 | `Lyon ATP` in 2023-24 is the May outdoor event, `Lyon ATP (indoor)` in 2026 is the relocated one; both are 250. `Marseille ATP` in 2026 is `unknown`. |
| Metz dropped | 2023-25 only | `Metz ATP` in 2026 is `unknown`. |
| Estoril not held (Challenger 175 in 2025) | 2023, 2024 and 2026 | `Estoril ATP` in 2025 is `unknown`; the 2025 Challenger rows are `challenger` by tour. |
| Cordoba, Atlanta, Newport ended as ATP events | 2023-24 only (Newport became a Challenger) | Later seasons are `unknown`; 2025-26 `Newport Chall. Men` rows are `challenger`. |
| One-season events | Adelaide 2, Banja Luka, Pune, Sofia, Zhuhai (2023); Belgrade 2 (2024); Athens (2025) | Absent seasons are `unknown`. |
| New ATP 250 events | Hangzhou, Hong Kong, Bucharest, Brisbane from 2024; Brussels from 2025 | 2023 is `unknown`. |
| Hopman Cup | 2023 and 2025 | 2024 and 2026 are `unknown`. |
| Next Gen ATP Finals | Jeddah 2023-25 | `other`, never `atp_finals`. |
| Davis Cup format change | World Group through 2025, World Group I/II with Preliminary from 2026 | Both are `other` via the `Davis Cup` prefix. |
| US Open `WIC` appears | 2026 | `other`, checked before normalization so it can not inherit `grand_slam`. |

## Intentionally `other` (coefficient 1.00)

Team and non-standard competitions are not Tour-level singles events: United Cup (including
Play Offs), Davis Cup (World Group, World Group I, World Group II, Play Offs, Qualification,
Preliminary), Hopman Cup, Laver Cup, Olympic Games, Asian Games, Next Gen ATP Finals - Jeddah
(including Play Offs), US Open `- WIC`, and rows from an exhibition tour (for example
`Six Kings Slam Exhibition Men (indoor)`, which the loader already excludes as `ATP Exhib`).

## Intentionally `unknown` (coefficient 1.00)

- A `tournament` label the bundled calendar does not contain, for example `Fictional City ATP`.
- A supported event in a season in which it was not held (see the table above).
- Any season outside 2023-2026, even for a known event name (for example `Rotterdam ATP` in 2027).
- Rows whose optional `tournament` column is empty or whitespace only; those remain valid matches.

Unknowns are reported by the summary/CLI/dashboard layer with their season context. They are never
silently relabeled ATP 250.

## Audit of the supplied 2023-2026 input

`tests/test_tournaments.py::test_supplied_season_labels_classify_without_unknowns` re-runs the
classification over every tracked `*-atp-season.csv` in the checkout and requires zero unknowns.
Adding a new season file or a new event label is expected to fail that audit until the catalog and
this document are extended; the failure is the maintenance tripwire, not a bug. The same audit was
run over the operator-supplied 2023 file in place (untracked, unmodified, never
copied into Git):

| Season | Eligible matches loaded | Tagged `unknown` |
|---|---:|---:|
| 2023 | 13631 | 0 |
| 2024 | 14236 | 0 |
| 2025 | 14446 | 0 |
| 2026 | 15575 | 0 |

Eligible matches per level in 2026: `atp_250` 1152, `atp_500` 696, `atp_finals` 6, `challenger`
11465, `grand_slam` 950, `masters_1000` 1041, `other` 265. Loader eligibility, deduplication,
validation and accounting are unchanged by this catalog: the same windows produce byte-identical
`LoadResult` counts before and after the change (including 15575/1852 for 2026 and 44257/2642 for
2024-2026).

## Sources

Category and calendar evidence, per season:

- 2023 calendar (categories, Astana/Sofia/Zhuhai/Pune/Banja Luka/Adelaide 2):
  <https://www.atptour.com/-/media/files/media-guide/2023/2023-atp-media-guide-full.pdf>
- 2024 calendar (13 ATP 500s, Astana -> Almaty):
  <https://www.atptour.com/-/media/files/final-2024-atp-calendar.pdf> and
  <https://www.atptour.com/en/news/2024-atp-calendar-update-gijon-almaty>
- 2024 media guide: <https://www.atptour.com/-/media/files/media-guide/2024/2024-atp-media-guide-full.pdf>
- 2025 ATP 500 upgrades (Dallas, Doha, Munich; 16 ATP 500s from 13) and calendar:
  <https://www.atptour.com/en/news/atp-500-upgrades-from-2025> and
  <https://www.atptour.com/en/news/2025-atp-tour-calendar-announced>
- 2025 ATP media guide: <https://www.atptour.com/-/media/files/media-guide/2025/2025-atp-media-guide-full-final.pdf>
- 2025 Estoril not held (Challenger 175) and Athens/Brussels ATP 250s:
  <https://www.atptour.com/en/news/antwerp-brussels-relocation-2025> and
  <https://www.atptour.com/en/tournaments/hellenic-championship/5100/overview>
- 2026 calendar (Lyon indoor replaces Marseille, Metz dropped, Estoril returns):
  <https://www.atptour.com/en/news/what-is-the-2026-atp-tour-calendar/>,
  <https://www.atptour.com/en/news/2026-atp-tour-calendar-announced>,
  <https://www.atptour.com/-/media/sites/atp-tour/press/press-releases/2026-atp-tour-calendar-announced.pdf>
  and <https://www.atptour.com/en/news/marseille-lyon-relocation>
- 2026 ATP media guide calendar:
  <https://www.atptour.com/-/media/files/media-guide/2026/2026-atp-media-guide-intro-administration-tournament-updated.pdf>

## Maintenance

The catalog is deliberately explicit rather than derived: a new season or a category change needs a
code change, a citation above, and a test.

1. Add or move the event in the tables in `src/tennis_elo/tournaments.py` for the seasons it was
   actually played at that level. Keys are the normalized label (for example `Munich`), and the
   `_ATP_500_BY_SEASON` / `_ATP_250_BY_SEASON` maps carry the season sets.
2. Extend `_SUPPORTED_SEASONS` and this document when a new season CSV is supplied; until then the
   new season classifies as `unknown`.
3. Add the public source to **Sources** and a regression case to `tests/test_tournaments.py`.
4. Keep the `challenger`, `atp_250`, `atp_500`, `masters_1000`, `atp_finals`, `grand_slam`, `other`
   and `unknown` keys only; `weighting.coefficient_for_level` rejects anything else.
