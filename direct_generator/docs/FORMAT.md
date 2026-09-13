# PC format and reproducible transformation

## Evidence and input boundaries

The PC baseline is a user-supplied installation database. It may include existing community updates that should be retained. `report.json` records its exact hashes, making the transformation reproducible without relying on a guessed patch version.

The roster CSV is the authoritative source for selected players and ratings. The project's `R/helpers.R`, `R/readcsv.R`, `R/make_player.R`, and `R/ootp.R` establish discrete rating values, DH conversion, birthday shifting, pitch creation order, and organization/level selection. The editor-driven workflow creates about 66 players per organization because it is limited by the players available to edit and create. The direct generators bypass those limits and include all 100 selected players per organization on both platforms.

## DAT containers

Most database DATs are Windows-1252 text, with CRLF lines. A header maps numeric field indices to names. Records begin with a literal `0` followed by eight hexadecimal digits, then indexed values. Both header and records end with `,;`.

```text
0 first_name,1 last_name,;
012345678,0 Aaron,1 Judge,;
```

Numeric column indices are **not portable between database versions**. The parser reads the header and transforms named fields, preserving the baseline's indices and order. Commas, semicolons, and newlines in values are rejected; names must be representable in Windows-1252. There is no guessed quoting/escaping convention.

| Files | Treatment |
| --- | --- |
| attrib, lhattrib, rhattrib | New player identity, appearance, ratings, and handedness splits |
| pitcher | New pitching attributes for pitchers only |
| bstats, career, fbstats, lhbstats, rhbstats | All-player stats tables; zero modern stats |
| careerp, pstats, lhpstats, rhpstats | Pitcher stats tables; zero modern stats |
| roster | Regenerate memberships, four batting orders, defensive assignments and pitching roles |
| hist | Filter binary history to preserved special/default players |
| team, org, other database files | Read as needed; do not replace |

`hist.dat` is a little-endian 32-bit count followed by that many 25-byte records. The first four bytes of each record are its player ID; the remaining 21 bytes are opaque and preserved verbatim. An unexpected length is rejected. Histories associated with old ordinary IDs must be removed because those IDs now refer to modern players.

The converter preserves 100 special-team players and the Default template, giving 3,101 total attribute records. All-Star teams reference 50 already existing modern players. Every ordinary stock ID is reused within its original pitcher/hitter type, then extra modern players receive hash-derived IDs. IDs are checked for collisions after assignment.

The `identity` key combines the source minor-league ID, actual date of birth, and pitcher/hitter role. It is independent of team and season; the two source Ohtani records remain distinct. **Assigned PC IDs can change between snapshots** because the donor pool is allocated in identity order. `id-map.json` is an audit, not an existing-dynasty migration map.

## Organization and lineup policy

1. Select rows whose `level_id` is 1–4. Require exactly 3,000: 50 pitchers and 50 hitters per organization. Other source rows are listed as excluded; the September CSV contains 10,877 total rows, so 7,877 are outside the selected roster.
2. Map source organizations to the PC `org.dat` by abbreviation, then resolve MLB/AAA/AA/A team IDs from that record. `org_id` follows the ordering in `ORGS`; it is not a PC team ID.
3. Map renamed codes: LAA→ANA, TBR→TB, CHW→CWS, KCR→KC, MIA→FLA, LAD→LA, SDP→SD, SFG→SF. Remaining codes match directly. Preserve 2005 franchise/affiliate/league structure.
4. Use minimum-cost matching within each organization to fill 25 players at every level, including all eight defensive positions and five SPs. Hitter counts are 13/12/13/12; pitcher counts are 12/13/12/13. Moving away from the source level costs much more than secondary-position use or overall-rating tie breaking. The current input requires 197 level changes, including some MLB changes; no organization loses a selected player. If the entire organization lacks positional coverage, fail.
5. Generate separate lineups versus LHP/RHP, with/without DH. Use qualified primary/secondary fielders; OF, IF, and UTIL expand to their relevant defensive positions. Favor contact+power, put a strong contact/discipline/speed hitter first, strongest remaining bat third and power fourth. This is a deterministic heuristic, not the real manager's lineup.
6. Choose the five strongest SPs, the strongest available RP as closer, two setup relievers, then middle/long relief. Generate 25-player All-Star rosters (14 hitters, 11 pitchers) from each baseline league's MLB pool.
7. Check every modern player's unique organization membership, all references and names across tables, pitcher-table consistency, all four nine-player batting orders, complete defenses, rotations and closers. Serialize and parse back every text table before publishing the package.

## Field transformations

| Source | PC representation / policy |
| --- | --- |
| First, Last, jersey number | Direct; no invented modern audio name |
| Bats R/L/S; Throws R/L | 0/1/2; 0/1 |
| SP, C, 1B, 2B, 3B, SS, LF, CF, RF, DH, RP, OF, IF, UTIL | 0–13 in that order; C=1 and 1B=2 corroborated with stock catchers/first basemen |
| DH primary | Upstream R policy: RF for `First == Ohtani`, otherwise 1B |
| Missing secondary | Same as hitter primary; opposite SP/RP for pitchers |
| Height, weight | Inches minus 48; pounds minus 100 |
| DOB | Shift birth year by `2005 - source season`; encode days since 1947-12-31. Shifted non-leap Feb 29 becomes Feb 28 and is reported |
| Body Skinny/Athletic/Heavy | 0/1/2; retain Default skeleton/bone profile |
| Face 1–15 | Generic face 901–915, with skin-tone map `(0,1,1,2,2,3,4,5,5,6,7,8,9,9,10)` from baseline generic faces |
| Hair style/color/facial hair | Source one-based choice minus one |
| Career Potential 1–5 | `starpower` 0–4 |
| Ditty Type 1–7 | 0–6 |
| Contact, power, speed | Direct numeric values (contact/power allow 100) |
| Fielding, range, arm strength/accuracy, durability, plate discipline, bunting, stealing tendency, baserunning ability | Discrete 0–15 index, as below |
| Take/Miss/Chase split tendencies | Same discrete scale, independently versus LHP and RHP |
| Nine hot/cold zones | Row-major upper-left through lower-right; C=0, N=1, H=2 |
| Pitch stamina/control/velocity | Direct; velocity is MPH |
| Pitch movement and pickoff | Discrete 0–15 index |
| Salary and contract | Uniform code 3 (intended $300,000), one year; no financial data in CSV |
| Historical/current stats | Zero modern stats; preserve special-team records |
| Hidden/top prospect | 0; career potential still imported |
| Audio/photo | Audio ID 0, photo code 2; generic appearances, no modern likeness pack |

The discrete scale is **not linear**:

```text
index:  0  1  2  3  4  5  6  7  8  9 10 11 12 13 14 15
rating: 0 10 20 30 40 50 55 60 65 70 75 80 85 90 95 99
```

When the baseline's `lhattrib.dat` omits `lrattrib_chasehardbreak`, the converter appends that named column without renumbering existing columns. It uses source LH values for modern players and RH values for preserved records.

## Pitch and animation limitations

Fastball is always present. Additional pitch codes 1–14 follow the source order: Changeup, Curveball, Knuckleball, Screwball, Sinker, Slider, Splitter, 2-Seam Fastball, Cutter, Circle Change, Forkball, Knucklecurve, Palmball, Slurve. Keep the first four present types, giving the game's five-pitch limit; report omitted types. Empty slots use `-`.

The CSV does not contain pitch trajectory variants: the original R workflow chooses those randomly. The converter uses the most frequent baseline trajectory code for each pitch type. Fastball movement/description are zero. Unspecified spray/hit-distribution values retain the Default template.

Named batting stances and pitching deliveries are mapped using corresponding stock players; exact tables live in `STANCES` and `DELIVERIES`. Repeated observations from the UI-created reference establish the generic labels used in the September 2026 snapshot. `Generic 3`, `Bent`, `Closed`, and `Open` remain reported code-0 fallbacks until independently observed; this snapshot uses none of them. Modern photographic likenesses, accurate player-specific contracts, historical career statistics, and new animations are not supplied by this CSV conversion.

## Future-update changes

Change parsing/mapping in code, add a focused regression for the affected rule, regenerate to a new directory, inspect `report.json`, and perform an in-game save/load and gameplay check before replacing a working roster. Do not alter generated DATs by hand: that loses reproducibility and the installer rejects their changed hashes.

## Pitching-role capacities

Each team supports 5 SP, 3 LR, 4 MR, 2 SU, and 1 CP. The assignment policy chooses the strongest available reliever as closer, assigns two setup pitchers, prefers remaining starters for long relief and remaining relievers for middle relief, and uses the other relief role when necessary. Validation rejects any roster that exceeds these capacities.
