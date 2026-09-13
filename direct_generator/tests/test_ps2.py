import struct
import unittest
import os
from pathlib import Path

from ps2_roster import Roster, ea_crc
from ps2_teams import serialize_team
from tools.ea_big import refpack
from tools.ps2_card import Card
from tools.ps2_patch_card import replace, page_ecc

ROOT=Path(__file__).resolve().parents[1]
REPOSITORY=ROOT.parent
CARDS=REPOSITORY/'memcards'
PS2_DATABASE=Path(os.environ.get('MVP2005_PS2_DATABASE', ROOT/'work/ps2-database'))


class EncodingTests(unittest.TestCase):
    def test_refpack_literal_and_overlapping_backreference(self):
        # Three literals followed by six copied bytes at distance three.
        self.assertEqual(refpack(bytes.fromhex('10fb0000090f02')+b'abc'+b'\xfc'),b'abcabcabc')
        with self.assertRaises(ValueError):refpack(bytes.fromhex('10fb0000090f02')+b'ab')
        with self.assertRaises(ValueError):refpack(bytes.fromhex('10fb0000030001fc'))

    def test_ecc_zero_page_and_single_bit(self):
        self.assertEqual(page_ecc(bytes(512)),bytes.fromhex('777f7f')*4)
        changed=bytearray(512);changed[0]=1
        self.assertEqual(page_ecc(changed),bytes.fromhex('70007f')+bytes.fromhex('777f7f')*3)


@unittest.skipUnless(CARDS.exists(),'Local reference memory-card fixtures required')
class SaveFixtureTests(unittest.TestCase):
    def test_all_supplied_save_and_icon_checksums(self):
        count=0
        for path in sorted(CARDS.rglob('*.ps2')):
            files={p.as_posix():data for p,data,_ in Card(path.read_bytes()).files()}
            for name,data in files.items():
                if not name.endswith('.sav'):continue
                with self.subTest(card=path.name,save=name):
                    r=Roster(data)
                    self.assertEqual(len(list(r.players())),3250)
                    teams=r.teams()
                    self.assertEqual(len(teams.records),126)
                    rebuilt=b''.join(serialize_team(t,r.index) for t in teams.records)
                    self.assertEqual(rebuilt,data[teams.start:teams.end])
                    parent=name.rsplit('/',1)[0]
                    self.assertEqual(struct.unpack_from('<I',data,8)[0],ea_crc(files[parent+'/title.ico']))
                    self.assertEqual(struct.unpack_from('<I',data,12)[0],ea_crc(files[parent+'/icon.sys']))
                    count+=1
        self.assertEqual(count,9)

    def test_probe_changes_only_target_field_and_is_exactly_reversible(self):
        card=(CARDS/'releases/MVP05Rosters-20260905.ps2').read_bytes()
        files=list(Card(card).files())
        name,original,_=next(f for f in files if f[0].suffix=='.sav')
        r=Roster(original);players=list(r.players())
        judge=next(p for p in players if (p['first'],p['last'])==('Aaron','Judge'))
        self.assertEqual(judge['attributes']['jerseynum'],99)
        patched=r.patch(judge['id'],'attributes.jerseynum',98)
        edited=list(Roster(patched).players())
        import copy
        expected=copy.deepcopy(players)
        expected[judge['index']]['attributes']['jerseynum']=98
        self.assertEqual(edited,expected)
        self.assertEqual(Roster(patched).patch(judge['id'],'attributes.jerseynum',99),original)
        image=replace(card,name.as_posix(),patched)
        restored=replace(image,name.as_posix(),original)
        self.assertEqual(restored,card)
        before={p.as_posix():data for p,data,_ in files}
        after={p.as_posix():data for p,data,_ in Card(image).files()}
        before[name.as_posix()]=patched
        self.assertEqual(after,before)
        for page in range(len(card)//528):
            a,b=card[page*528:(page+1)*528],image[page*528:(page+1)*528]
            if a!=b:self.assertEqual(b[512:524],page_ecc(b[:512]))

    def test_lineup_edit_is_local_and_reversible(self):
        card=(CARDS/'releases/MVP05Rosters-20260905.ps2').read_bytes()
        member,data,_=next(f for f in Card(card).files() if f[0].suffix=='.sav')
        r=Roster(data);teams=r.teams()
        team=next(t for t in teams.records if t['abbreviation']=='NYY')
        edited=r.swap_batting_order(team['id'],'rh_al',1,2)
        after=Roster(edited).teams()
        import copy
        expected=copy.deepcopy(teams.records)
        lineup=expected[team['slot']]['lineups']['rh_al']
        for key in ('batting_positions','batting_player_ids'):
            lineup[key][0],lineup[key][1]=lineup[key][1],lineup[key][0]
        self.assertEqual(after.records,expected)
        at=team['lineups']['rh_al']['offset']+12
        allowed=set(range(4,8))|set(range(at,at+8))
        self.assertTrue(all(i in allowed for i,(a,b) in enumerate(zip(data,edited)) if a!=b))
        self.assertEqual(list(Roster(edited).players()),list(r.players()))
        self.assertEqual(Roster(edited).swap_batting_order(team['id'],'rh_al',1,2),data)
        image=replace(card,member.as_posix(),edited)
        self.assertEqual(replace(image,member.as_posix(),data),card)
        with self.assertRaises(ValueError):r.swap_batting_order(team['id'],'rh_al',0,2)

    def test_bad_team_count_and_duplicate_copy_rejected(self):
        card=Card((CARDS/'releases/MVP05Rosters-20260905.ps2').read_bytes())
        data=next(b for p,b,_ in card.files() if p.suffix=='.sav')
        r=Roster(data);team=r.teams().records[0]
        for offset in (team['players_offset']-8,team['fixed_offset']):
            bad=bytearray(data)
            struct.pack_into('<I',bad,offset,26)
            struct.pack_into('<I',bad,4,ea_crc(bad[200:]))
            with self.assertRaisesRegex(ValueError,'team registry'):Roster(bytes(bad)).teams()

    @unittest.skipUnless((PS2_DATABASE/'roster.dat').exists(),
                         'Extracted stock PS2 DAT required for independent comparison')
    def test_nerf_teams_match_stock_dat(self):
        from mvp_rosters import Table
        from tools.verify_save_teams import compare
        card=next(CARDS.rglob('MVP05Rosters-Nerf.ps2'))
        data=next(b for p,b,_ in Card(card.read_bytes()).files() if p.name=='Nerf.sav')
        report=compare(data,Table.read(PS2_DATABASE/'roster.dat'))
        self.assertEqual(report['comparisons'],10080)
        self.assertEqual(report['differences'],[])

    def test_corrupt_save_rejected(self):
        card=Card((CARDS/'releases/MVP05Rosters-20260905.ps2').read_bytes())
        data=bytearray(next(b for p,b,_ in card.files() if p.suffix=='.sav'))
        data[500]^=1
        with self.assertRaisesRegex(ValueError,'checksum'):Roster(bytes(data))


if __name__=='__main__':unittest.main()
