#!/usr/bin/env python3
"""Compare serialized team membership, lineups and pitching roles with a roster DAT."""
import argparse
import json
import sys
from pathlib import Path

if __package__ in (None, ''):sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from mvp_rosters import Table
from ps2_roster import Roster
from ps2_teams import VARIANTS, POSITIONS, ROLE_CAPACITIES


def compare(save,dat):
    teams=Roster(save).teams();source={}
    for row in dat.rows.values():
        source.setdefault(f"{int(row['roster_teamid'],16):08x}",{})[
            f"{int(row['roster_playerid'],16):08x}"]=row
    checks=0;differences=[];overflows=[]
    def check(actual,expected,**where):
        nonlocal checks
        checks+=1
        if actual!=expected:differences.append(dict(where,actual=actual,expected=expected))
    for team in teams.records:
        rows=source.get(team['id'],{});ids=team['player_ids'];tid=team['id']
        check(sorted(ids),sorted(rows),team=tid,field='membership')
        for variant in VARIANTS:
            side,rules=variant.split('_');prefix=f'{side}_roster_{rules}'
            lineup=team['lineups'][variant]
            for position,slot in lineup['position_slots'].items():
                if slot==255:continue
                row=rows.get(ids[slot],{})
                # P is the current starter; SP1 in the supplied DAT export.
                check(row.get(prefix+'_position'),'SP1' if position=='P' else position,
                      team=tid,variant=variant,field='position',player=ids[slot])
            for i,key in enumerate(lineup['batting_player_ids'],1):
                check(rows.get(key,{}).get(prefix+'_battingorder'),str(i),
                      team=tid,variant=variant,field='batting_order',order=i)
        for role,capacity in ROLE_CAPACITIES.items():
            expected=[i for i,k in enumerate(ids)
                      if rows.get(k,{}).get('rh_roster_al_position','').startswith(role)]
            actual=team['pitching_roles'][role]['slots']
            check(actual,expected,team=tid,field='pitching_role',role=role)
            if len(expected)>capacity:
                overflows.append({'team':tid,'abbreviation':team['abbreviation'],'role':role,
                                  'capacity':capacity,'dat_slots':expected,'saved_slots':actual,
                                  'omitted_ids':[ids[i] for i in expected if i not in actual]})
    return {'teams':len(teams.records),'comparisons':checks,'differences':differences,
            'role_overflows':overflows,'runtime_validated':False}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('save',type=Path);p.add_argument('roster_dat',type=Path)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();report=compare(a.save.read_bytes(),Table.read(a.roster_dat))
    with a.output.open('x') as f:json.dump(report,f,indent=2);f.write('\n')
    print(f"{report['comparisons']} comparisons; {len(report['differences'])} differences; "
          f"{len(report['role_overflows'])} role overflows")
    return bool(report['differences'])

if __name__=='__main__':sys.exit(main())
