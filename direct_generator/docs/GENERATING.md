# Generating rosters

Run these commands from `direct_generator/`.

## Inputs

The PS2 generator accepts the original US game disc as an uncompressed `.iso`
file, plus the tracked `../memcards/misc/MVP05Rosters-Nerf.ps2` template. Pass
`--ps2-image /path/to/MVP2005.iso`; the generator finds `DATA/DATABASE/DATABASE.BIG`,
extracts its DAT files into a temporary directory, and removes that directory when
finished. The image is opened read-only. No mounting or extraction software is
needed. Compressed images such as `.iso.gz`, `.zip`, and `.chd` must first be
converted or extracted to a plain ISO.

If you already have the extracted DAT files, use `--ps2-baseline` instead of
`--ps2-image`. To extract DATs manually from an existing BIG archive:

```bash
python3 tools/ea_big.py DATABASE.BIG work/ps2-database
```

The PC generator needs a copy of the PC installation's `data/database`
directory. An installation with community updates may be used when those team,
stadium, and database changes should be retained. Keep an untouched backup and
do not use a previously generated roster as the next baseline.

## Generate both platforms

```bash
python3 generate_rosters.py \
  --source ../data/MVProsters/MVProsters_2026-09-05.csv \
  --pc-baseline /path/to/pc/data/database \
  --ps2-image /path/to/MVP2005.iso \
  --template-card ../memcards/misc/MVP05Rosters-Nerf.ps2 \
  --reference-cards ../memcards \
  --output output/2026-09-05
```

The CSV date supplies the roster year and save name. Use `--source-year` and
`--save-name` when the filename has no date. Choose a new output directory for
every run.

The final files are:

- `output/2026-09-05/ps2/card/roster.ps2`
- `output/2026-09-05/pc/database/*.dat`
- `output/2026-09-05/shared-roster.json`
- `output/2026-09-05/identity-map.json`
- per-platform manifests and verification reports

The PC DAT package becomes active after replacing the installation database and
choosing **Manage Rosters -> Reset Rosters**. Use `install_roster.py` to verify,
back up, install, and later restore the files. Run without `--apply` first:

```bash
python3 install_roster.py \
  --package output/2026-09-05/pc \
  --game-dir /path/to/MVP\ Baseball\ 2005 \
  --backup work/pc-backup
```

Add `--apply` to perform the installation. Load and save the roster in game if a
native PC `.sav` is wanted.

To restore the original database, use the same game and backup paths with
`--restore --apply` (omit `--package`). A restore interrupted by a file error can
be retried: files already restored are skipped, while unrelated changes and
corrupted backups are rejected.

Attach the generated PS2 card as a separate memory card in PCSX2, then choose
**Manage Rosters -> Load Rosters**. Do not replace a personal card without a
backup.

## Separate PS2 stages

`ps2_generate.py` also exposes `normalize`, `plan`, `encode`, `verify`,
`package`, and `build` commands. Run `python3 ps2_generate.py COMMAND --help`
for their inputs. The intermediate JSON documents make allocation and binary
encoding reviewable independently.

The separate `normalize` and `build` commands also accept `--ps2-image` as an
alternative to `--baseline`. Later stages operate on their existing JSON/save inputs.
