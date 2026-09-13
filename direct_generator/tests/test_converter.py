import itertools
import tempfile
import unittest
from pathlib import Path

from mvp_rosters import (DELIVERIES, DISCRETE, STANCES, Table, assignment, discrete, filter_history,
                         identity, player_id, qualify, bullpen_roles)


class DatTests(unittest.TestCase):
    def test_shared_animation_enum_regressions(self):
        self.assertEqual(STANCES["Walker"], 31)
        self.assertEqual(STANCES["Generic 2"], 27)
        self.assertEqual(STANCES["Crouched"], 2)
        self.assertEqual(DELIVERIES["Style 1"], 0)
        self.assertEqual(DELIVERIES["Style 10"], 9)
        self.assertEqual(DELIVERIES["Style 11"], 24)

    def test_named_fields_and_arbitrary_column_order(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)/'attrib.dat'
            p.write_bytes(b'7 last_name,2 first_name,44 playerattrib_starpower,;\r\n'
                          b'012345678,44 4,2 Aaron,7 Judge,;\r\n')
            table = Table.read(p)
            self.assertEqual(table.rows['012345678']['first_name'], 'Aaron')
            self.assertEqual(table.rows['012345678']['playerattrib_starpower'], '4')
            table.write(p)
            self.assertEqual(Table.read(p), table)

    def test_rejects_duplicate_or_missing_fields(self):
        bad = [b'0 first_name,0 last_name,;\n',
               b'0 first_name,1 last_name,;\n012345678,0 Aaron,;\n',
               b'0 first_name,1 last_name,;\n012345678,0 Aaron,1 Judge\n',
               b'0 first_name,;\n012345678,0 A,;\n012345678,0 B,;\n']
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)/'bad.dat'
            for data in bad:
                with self.subTest(data=data):
                    p.write_bytes(data)
                    with self.assertRaises(ValueError):
                        Table.read(p)

    def test_discrete_scale_is_not_linear(self):
        self.assertEqual(discrete(50), 5)
        self.assertEqual(discrete(55), 6)
        self.assertEqual(discrete(95), 14)
        self.assertEqual(discrete(99), 15)
        with self.assertRaises(ValueError):
            discrete(100)
        self.assertEqual([DISCRETE[discrete(x)] for x in DISCRETE], list(DISCRETE))

    def test_hist_filter_preserves_opaque_payload(self):
        a = bytes.fromhex('78563412') + bytes(range(21))
        b = bytes.fromhex('efcdab09') + b'x'*21
        raw = (2).to_bytes(4, 'little') + a + b
        self.assertEqual(filter_history(raw, {'012345678'}), (1).to_bytes(4, 'little')+a)
        with self.assertRaises(ValueError):
            filter_history(raw[:-1], set())


class SelectionTests(unittest.TestCase):
    def test_bullpen_overflow_uses_other_relief_role(self):
        self.assertEqual(bullpen_roles([{'First Position': 'SP'}]*8),
                         ['CP', 'SU', 'SU', 'LR', 'LR', 'LR', 'MR', 'MR'])
        self.assertEqual(bullpen_roles([{'First Position': 'RP'}]*8),
                         ['CP', 'SU', 'SU', 'MR', 'MR', 'MR', 'MR', 'LR'])
        with self.assertRaises(ValueError):
            bullpen_roles([{'First Position': 'RP'}]*11)

    def test_assignment_matches_exhaustive_optimum(self):
        # Greedily selecting row one's cheapest slot blocks row two.
        costs = [[1, 2, 30, 40], [1, 100, 100, 100], [100, 100, 1, 2], [100, 100, 1, 100]]
        result = assignment(costs)
        expected = min(sum(costs[i][j] for i, j in enumerate(p))
                       for p in itertools.permutations(range(4)))
        self.assertEqual(sum(costs[i][j] for i, j in enumerate(result)), expected)
        self.assertEqual(len(set(result)), 4)

    def test_only_qualified_secondary_positions(self):
        r = {'First Position': 'SS', 'Second Position': 'IF'}
        self.assertEqual(qualify(r, 'SS'), 0)
        self.assertEqual(qualify(r, '2B'), 1)
        self.assertGreater(qualify(r, 'C'), 10000)

    def test_ohtani_roles_distinct_and_team_does_not_change_identity(self):
        r = {'bbrefminors_id': 'otani-000sho', 'Birth Year': '1994',
             'Birth Month': '7', 'Birth Date': '5', 'First Position': 'SP', 'org_id': '28'}
        other = dict(r, **{'First Position': 'RF'})
        self.assertNotEqual(player_id(r), player_id(other))
        self.assertEqual(identity(r), identity(dict(r, org_id='1')))


if __name__ == '__main__':
    unittest.main()
