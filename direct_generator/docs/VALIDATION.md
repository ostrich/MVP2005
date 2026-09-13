# Validation

The September 5, 2026 snapshot passes the complete generation pipeline.
Runtime and binary checks cover the artifacts identified below.

- All tracked PS2 cards decode and round-trip.
- The stock PS2 roster agrees with its extracted DAT team structures in 10,080
  membership, lineup, and pitching-role checks.
- The generated save and card pass 444,333 structural and semantic checks.
- The card contains 3,000 modern players, 100 retained special players, one
  Default template, and 149 hidden inactive slots.
- PC and PS2 use the same selected modern players and shared rating conversions.
- The season-test card loaded, saved, and reloaded in MVP Baseball 2005 under
  PCSX2. A Dynasty completed a regular season and postseason without an observed
  roster-related failure.

The season-test card and the animation-audited card have different hashes, recorded
in [validation-artifacts.json](validation-artifacts.json). The audited card differs
in 225 decoded batting stances and 320 pitching deliveries; no other decoded player
fields differ. The audited card reproduces exactly from the generator, but has not
completed a separate season test.

The direct output was also compared with the UI-created September 5 reference.
Names duplicated in the complete CSV and records with conflicting birthday or
position anchors were excluded rather than guessed. After removing the internal
top-prospect policy field, 113,764 of 114,187 source-related values agreed
(99.63%). This is an agreement rate: the UI-created reference contains observable
entry drift and is not assumed to be correct in every field.

Animation codes are shared by PC and PS2; their original `attrib.dat` files are
byte-identical. Repeated UI-save observations establish every animation label used
by this snapshot. Four unused batting labels (`Generic 3`, `Bent`, `Closed`, and
`Open`) remain explicit fallbacks rather than guesses.

The verifier establishes binary structure, checksums, decoded player values,
membership, lineups, pitching roles, memory-card allocation, and changed-page
ECC. It cannot establish the visual quality of generated faces, subjective rating
quality, or compatibility with every third-party game mod.
