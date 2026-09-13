"""Integration boundaries: shared preparation, compatibility and atomic publication."""
import tempfile
import unittest
import os
from pathlib import Path
from unittest.mock import patch

import generate_rosters
from mvp_rosters import Table, prepare_source

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = ROOT.parent
SOURCE = REPOSITORY / 'data/MVProsters/MVProsters_2026-09-05.csv'
PC = Path(os.environ.get('MVP2005_PC_DATABASE', ROOT / 'work/pc-database'))
PS2 = Path(os.environ.get('MVP2005_PS2_DATABASE', ROOT / 'work/ps2-database'))
CARD = REPOSITORY / 'memcards/misc/MVP05Rosters-Nerf.ps2'
REFERENCE = ROOT / 'work/reference-output'


@unittest.skipUnless(all(p.exists() for p in (SOURCE, PC, PS2, CARD)), 'Local baselines required')
class DualPipelineTests(unittest.TestCase):
    def test_shared_preparation_and_animation_changes_are_local(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / 'combined'
            with patch('generate_rosters.prepare_source', wraps=prepare_source) as prepare:
                generate_rosters.build(SOURCE, PC, PS2, CARD, output, 2026, '20260905', progress=lambda _: None)
                prepare.assert_called_once_with(SOURCE, 2026)
            previous_pc = REFERENCE / '2026-09-05-role-capacity'
            if previous_pc.exists():
                for path in (previous_pc / 'database').iterdir():
                    current = output / 'pc/database' / path.name
                    if path.name not in ('attrib.dat', 'pitcher.dat'):
                        self.assertEqual(path.read_bytes(), current.read_bytes(), path.name)
                        continue
                    old, new = Table.read(path), Table.read(current)
                    allowed = {'attrib.dat': 'playerattrib_battingstance',
                               'pitcher.dat': 'pitchattrib_pitcher_delivery'}[path.name]
                    changes = []
                    for player_id in old.rows:
                        for field in old.rows[player_id]:
                            if old.rows[player_id][field] != new.rows[player_id][field]:
                                changes.append((player_id, field))
                    self.assertTrue(changes, path.name)
                    self.assertEqual({field for _, field in changes}, {allowed}, path.name)
                for name in ('id-map.json', 'players.csv'):
                    self.assertEqual((previous_pc / name).read_bytes(), (output / 'pc' / name).read_bytes(), name)

    def test_second_backend_failure_publishes_neither(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / 'combined'
            with patch('generate_rosters.build_ps2', side_effect=ValueError('backend failed')):
                with self.assertRaisesRegex(ValueError, 'backend failed'):
                    generate_rosters.build(SOURCE, PC, PS2, CARD, output, 2026, '20260905', progress=lambda _: None)
            self.assertFalse(output.exists())
            self.assertEqual(list(Path(temp).iterdir()), [])
