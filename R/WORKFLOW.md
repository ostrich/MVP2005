# Preparing an update

Set `roster_date` near the top of `ootp.R` to the snapshot date and select the
corresponding OOTP export. Set `csv_date` in `readcsv.R` to the same date before
running the player editor scripts. Player ages are calculated relative to that
snapshot year. Direct calls to `make_player_from_row()` or
`morph_player_from_row()` can also supply `roster_year` explicitly.

Run `ootp.R` from the beginning to reset the random sequence. Repeated complete
runs use the same random choices when the input files, code, and relevant R
package versions are unchanged. Equipment and pitch trajectories use player
identity seeds, so those choices are independent of which other players have
already been processed. This does not reconstruct random choices from previously
unseeded releases.

Backups contain the memory card, player log, and progress CSV. A fresh run writes
an empty player log before its initial backup. Missing files or failed copies
stop the operation. Restore all three files from the same backup together;
completion of an AutoHotkey script does not establish that every game action was
accepted, and interrupted UI operations still require checking the game state.

## Regression checks

From the repository root:

```sh
Rscript tests/test_backups.R
Rscript tests/test_randomness.R
```

These checks use base R and local temporary files. They test backup handling and
random choices without starting AutoHotkey or PCSX2. They do not replace testing
the Windows UI workflow or a complete build with the raw OOTP inputs.
