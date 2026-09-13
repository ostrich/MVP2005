#!/usr/bin/env python3
"""One source preparation, two baseline adapters, atomic PC and PS2 publication."""
import argparse
import json
from pathlib import Path
import re

from mvp_rosters import prepare_source, _convert
from mvp_ps2.pipeline import build as build_ps2, new_directory, json_bytes, source_hashes
from mvp_ps2.model import sha
from tools.ps2_image import database_input


def build(source, pc_baseline, ps2_baseline, template_card, output, year, name,
          member=None, reference_cards=None, progress=print):
    with new_directory(output) as staged:
        progress('Preparing shared player selection, affiliate assignments and lineups...')
        prepared = prepare_source(source, year)
        (staged / 'shared-roster.json').write_bytes(json_bytes(prepared))
        progress('Materializing PC database using the PC baseline...')
        _convert(source, pc_baseline, staged / 'pc', year, prepared)
        build_ps2(source, ps2_baseline, template_card, staged / 'ps2', year, name,
                  member, reference_cards, progress, prepared)
        pc_ids = json.loads((staged / 'pc/id-map.json').read_text())
        ps2_ids = json.loads((staged / 'ps2/model.json').read_text())['identity_map']
        if pc_ids.keys() != ps2_ids.keys():
            raise ValueError('PC and PS2 player selections differ')
        (staged / 'identity-map.json').write_bytes(json_bytes({
            key: {'pc': pc_ids[key], 'ps2': ps2_ids[key]} for key in pc_ids}))
        (staged / 'README.md').write_text(
            '# MVP 2005 dual-platform rosters\n\n'
            'Both outputs use shared-roster.json for the 3000-player selection, '
            'affiliate assignments and four lineup variants. identity-map.json links platform IDs.\n\n'
            '* PC: pc/database contains the installable DAT package; pc/report.json records checks. '
            'A native PC save still requires loading and saving in the game.\n'
            '* PS2: ps2/card/roster.ps2 is the memory card; ps2/card/verification.json records checks.\n\n'
            'Neither output has been runtime validated by this build.\n')
        manifest = {'schema': 'mvp-dual-build/v1', 'modern_players': len(pc_ids),
                    'runtime_validated': False, 'generator_source_sha256': source_hashes(),
                    'files': {p.relative_to(staged).as_posix(): sha(p.read_bytes())
                              for p in sorted(staged.rglob('*')) if p.is_file()}}
        (staged / 'manifest.json').write_bytes(json_bytes(manifest))
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ('source', 'pc-baseline', 'template-card', 'output'):
        parser.add_argument('--' + arg, type=Path, required=True)
    ps2 = parser.add_mutually_exclusive_group(required=True)
    ps2.add_argument('--ps2-baseline', type=Path, help='Extracted PS2 DAT directory')
    ps2.add_argument('--ps2-image', type=Path, help='MVP Baseball 2005 (USA) plain ISO image')
    parser.add_argument('--source-year', type=int)
    parser.add_argument('--save-name')
    parser.add_argument('--member')
    parser.add_argument('--reference-cards', type=Path)
    args = parser.parse_args()
    date = re.search(r'(\d{4})-(\d{2})-(\d{2})', args.source.name)
    year = args.source_year or (int(date[1]) if date else None)
    name = args.save_name or (''.join(date.groups()) if date else None)
    if year is None or name is None:
        parser.error('Supply --source-year and --save-name when the source filename has no date')
    if not re.fullmatch(r'[A-Za-z0-9]{1,15}', name):
        parser.error('Save name must be 1–15 ASCII letters/digits')
    try:
        with database_input(args.ps2_baseline, args.ps2_image) as baseline:
            build(args.source, args.pc_baseline, baseline, args.template_card,
                  args.output, year, name, args.member, args.reference_cards)
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(1, f'Failed: {error}\n')
    print(args.output)


if __name__ == '__main__':
    main()
