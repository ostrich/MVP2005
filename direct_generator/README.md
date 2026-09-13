# Direct roster generator

This optional Python generator converts an existing `data/MVProsters/*.csv`
snapshot directly into two outputs:

- a PS2 memory card containing 100 modern players per organization; and
- replacement PC `data/database/*.dat` files using the same selected players,
  ratings, affiliate assignments, and lineups.

It bypasses the roster editor. It does not need AutoHotkey, OCR, PCSX2, or the
50-hour player-creation and nerfing process. The original R workflow remains
available and unchanged.

Python 3.10 or newer is required. The generator itself uses only the standard
library. Supply a PC database directory and either a PS2 ISO or an extracted PS2
database directory.

See [Generating rosters](docs/GENERATING.md) for setup and commands. The binary
stage boundaries and validation evidence are described in
[Format notes](docs/FORMAT.md) and [Validation](docs/VALIDATION.md).

## Design

`generate_rosters.py` prepares the CSV once and sends a platform-neutral roster
selection to separate PC and PS2 adapters:

1. validate the source and select 3,000 modern players;
2. assign 25 players to each MLB, AAA, AA, and A roster;
3. build four lineup variants and capacity-safe pitching roles;
4. write and round-trip the PC DAT tables;
5. normalize, allocate, encode, independently decode, and verify the PS2 save;
6. replace the save inside a copy of the template card and recompute card ECC.

Every stage refuses to overwrite its output. Source CSVs, game databases, and
template cards are read-only inputs. A failed combined build publishes neither
platform.

## Tests

From this directory:

```bash
python3 -m unittest discover -s tests -v
```

Tests that require extracted game databases skip when those private fixtures are
absent. Set `MVP2005_PC_DATABASE` and `MVP2005_PS2_DATABASE` to run the complete
database integration suite. Set `MVP2005_PS2_IMAGE` as well to check ISO extraction
against the extracted PS2 database.
