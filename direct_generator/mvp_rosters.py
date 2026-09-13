#!/usr/bin/env python3
"""Convert CollinErickson/MVP2005 roster CSVs to MVP Baseball 2005 PC DATs.

Only the Python standard library is required. See docs/FORMAT.md for evidence,
policies, and limitations. Input directories are never modified.
"""
from __future__ import annotations

import argparse
import csv
from copy import deepcopy
import hashlib
import json
import re
import sys
import tempfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path


@dataclass
class Table:
    fields: dict[int, str]
    rows: dict[str, dict[str, str]]

    @classmethod
    def read(cls, path: Path) -> Table:
        lines = path.read_bytes().decode('cp1252').splitlines()
        if not lines:
            raise ValueError(f'{path}: empty table')

        def pairs(text: str) -> dict[int, str]:
            if not text.endswith(',;'):
                raise ValueError(f'{path}: missing record terminator')
            result = {}
            for item in text[:-2].split(','):
                key, value = item.split(' ', 1)
                key = int(key)
                if key in result:
                    raise ValueError(f'{path}: duplicate field {key}')
                result[key] = value
            return result

        fields = pairs(lines[0])
        if len(set(fields.values())) != len(fields):
            raise ValueError(f'{path}: duplicate field name')
        rows = {}
        for line in lines[1:]:
            rid, text = line.split(',', 1)
            if not re.fullmatch(r'0[0-9a-fA-F]{8}', rid) or rid in rows:
                raise ValueError(f'{path}: invalid/duplicate record ID {rid}')
            values = pairs(text)
            if values.keys() != fields.keys():
                raise ValueError(f'{path}: fields differ for {rid}')
            rows[rid] = {fields[k]: v for k, v in values.items()}
        return cls(fields, rows)

    def write(self, path: Path) -> None:
        def line(values):
            for v in values.values():
                if any(c in str(v) for c in ',;\r\n'):
                    raise ValueError(f'Unsafe DAT value {v!r}')
            return ','.join(f'{k} {v}' for k, v in values.items()) + ',;\r\n'
        text = line(self.fields)
        for rid, row in self.rows.items():
            if set(row) != set(self.fields.values()):
                raise ValueError(f'{path}: fields differ for {rid}')
            text += rid + ',' + line({k: row[v] for k, v in self.fields.items()})
        path.write_bytes(text.encode('cp1252'))


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


DISCRETE = (0, 10, 20, 30, 40, 50, 55, 60, 65, 70, 75, 80, 85, 90, 95, 99)
POSITIONS = {'SP': 0, 'C': 1, '1B': 2, '2B': 3, '3B': 4, 'SS': 5,
             'LF': 6, 'CF': 7, 'RF': 8, 'DH': 9, 'RP': 10, 'OF': 11,
             'IF': 12, 'UTIL': 13}
FIELD_POSITIONS = ('C', '1B', '2B', '3B', 'SS', 'LF', 'CF', 'RF')
PITCHES = ('Changeup', 'Curveball', 'Knuckleball', 'Screwball', 'Sinker',
           'Slider', 'Splitter', '2-Seam Fastball', 'Cutter', 'Circle Change',
           'Forkball', 'Knucklecurve', 'Palmball', 'Slurve')
ORGS = ('BAL BOS NYY TBR TOR CHW CLE DET KCR MIN LAA OAK SEA TEX HOU '
        'ATL MIA NYM PHI WAS CHC CIN MIL PIT STL ARI COL LAD SDP SFG').split()
PC_ORGS = {'LAA': 'ANA', 'TBR': 'TB', 'CHW': 'CWS', 'KCR': 'KC',
           'MIA': 'FLA', 'WAS': 'WAS', 'CHC': 'CHC', 'LAD': 'LA',
           'SDP': 'SD', 'SFG': 'SF'}
# The original PC and PS2 DATs are byte-identical and use the same animation
# enums. Named values are corroborated by stock players; generic values below
# are repeated modal observations from the supplied UI-created PS2 saves.
# Keep this explicit so each label and value can be reviewed together.
STANCES = {
    'Generic': 0, 'Crouched': 2, 'Upright': 3, 'High': 5,
    'A. Jones': 7, 'M. Ramirez': 8, 'Sosa': 9, 'M. Ordonez': 10, 'Thome': 11,
    'V. Guerrero': 12, 'Piazza': 13, 'Ichiro': 14, 'Giambi': 15,
    'Garciaparra': 16, 'Griffey Jr.': 17, 'L. Gonzalez': 18, 'Sheffield': 19,
    'Bagwell': 20, 'A. Rodriguez': 21, 'Jeter': 22, 'Beltre': 24,
    'Everett': 25, 'D. Ortiz': 26, 'Generic 2': 27, 'B. Williams': 28,
    'Durham': 29, 'Fullmer': 30, 'Walker': 31, 'Counsell': 32,
    'J. Franco': 33, 'Vina': 34, 'Renteria': 35, 'B. Boone': 36,
    'Klesko': 37, 'Delgado': 38, 'Alou': 39, 'Lofton': 40, 'Sierra': 41,
    'Burnitz': 42, 'C. Jones': 43, 'Thomas': 44, 'Green': 45,
    'J. Gonzalez': 46, 'Floyd': 47, 'H. Matsui': 48, 'Helton': 49,
    'Giles': 50, 'Glaus': 51, 'A. Pujols': 52, 'B. Ruth': 53,
    'L. Gehrig': 54, 'R. Jackson': 55, 'J. Morgan': 56, 'R. Carew': 57,
    'T. Cobb': 58, 'Y. Berra': 59, 'H. Wagner': 60, 'Classic 1': 61,
    'Classic 2': 62, 'Classic 3': 63, 'K. Matsui': 64, 'E. Chavez': 65,
}
DELIVERIES = {
    **{f'Style {number}': number - 1 for number in range(1, 11)},
    'R. Johnson': 10, 'Nomo': 11, 'Ishii': 12, 'Maddux': 13, 'K. Brown': 14,
    'P. Martinez': 15, 'Kim': 16, 'Schmidt': 17, 'Nelson': 18,
    'Hasegawa': 19, 'O. Hernandez': 20, 'Park': 21, 'Mussina': 22,
    'Wakefield': 23, 'Style 11': 24, 'Lowe': 25, 'Weber': 26, 'Ohka': 27,
    'Smoltz': 28, 'Pettitte': 29, 'Rivera': 30, 'D. Wells': 31,
    'Schilling': 32, 'Glavine': 33, 'D. Willis': 34, 'E. Gagne': 35,
    'R. Halladay': 36, 'J. Seo': 37, 'B. Zito': 38, 'M. Mulder': 39,
    'M. Morris': 40, 'Moyer': 41, 'Hoffman': 42, 'M. Redman': 43,
    'Ol. Perez': 44, 'M. Prior': 45, 'W. Johnson': 46, 'J. Marichal': 47,
    'N. Ryan': 48, 'S. Paige': 49, 'B. Gibson': 50, 'C. Hunter': 51,
    'T. Seaver': 52, 'Classic 1': 53, 'Classic 2': 54, 'Classic 3': 55,
    'T. Hudson': 56, 'Foulke': 57, 'Oswalt': 58,
}
ALL_PLAYER_TABLES = ('attrib', 'lhattrib', 'rhattrib', 'bstats', 'career',
                     'fbstats', 'lhbstats', 'rhbstats')
PITCHER_TABLES = ('pitcher', 'careerp', 'pstats', 'lhpstats', 'rhpstats')
STAT_TABLES = set(ALL_PLAYER_TABLES + PITCHER_TABLES) - {
    'attrib', 'lhattrib', 'rhattrib', 'pitcher'}


def number(row, field, low=0, high=100):
    value = float(row[field])
    if not low <= value <= high or not value.is_integer():
        raise ValueError(f'{row.get("First")} {row.get("Last")}: invalid {field}: {value}')
    return int(value)


def discrete(value):
    if value not in DISCRETE:
        raise ValueError(f'{value} is not on the MVP discrete rating scale')
    return DISCRETE.index(value)


def is_pitcher(row):
    return row['First Position'] in ('SP', 'RP')


def identity(row):
    # Include role to keep the source's two Ohtanis distinct. Do not use team,
    # ratings, source row number, or snapshot year. The identity is stable;
    # assigned stock IDs are snapshot-local (see id-map.json).
    return '|'.join((row['bbrefminors_id'], row['Birth Year'], row['Birth Month'],
                     row['Birth Date'], 'pitcher' if is_pitcher(row) else 'batter'))


def player_id(row):
    if '_game_id' in row:
        return row['_game_id']
    return '0' + hashlib.sha256(('mvp-pc-v1|' + identity(row)).encode()).hexdigest()[:8]


def qualify(row, position):
    if position == row['First Position']:
        return 0
    secondary = row['Second Position']
    if position == secondary:
        return 1
    if secondary == 'OF' and position in ('LF', 'CF', 'RF'):
        return 1
    if secondary == 'IF' and position in ('1B', '2B', '3B', 'SS'):
        return 1
    if secondary == 'UTIL' and position in FIELD_POSITIONS:
        return 1
    return 1000000


def assignment(costs):
    """Minimum-cost matching: return a column for each row (Hungarian method)."""
    n = len(costs)
    m = len(costs[0])
    if n > m or any(len(r) != m for r in costs):
        raise ValueError('Invalid assignment dimensions')
    u, v, p, way = [0]*(n+1), [0]*(m+1), [0]*(m+1), [0]*(m+1)
    for i in range(1, n+1):
        p[0] = i
        j0 = 0
        mins, used = [float('inf')]*(m+1), [False]*(m+1)
        while True:
            used[j0] = True
            i0, delta, j1 = p[j0], float('inf'), 0
            for j in range(1, m+1):
                if not used[j]:
                    cur = costs[i0-1][j-1] - u[i0] - v[j]
                    if cur < mins[j]:
                        mins[j], way[j] = cur, j0
                    if mins[j] < delta:
                        delta, j1 = mins[j], j
            for j in range(m+1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    mins[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while True:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1
            if j0 == 0:
                break
    result = [-1]*n
    for j in range(1, m+1):
        if p[j]:
            result[p[j]-1] = j-1
    return result


def offense(row, side='R'):
    return (number(row, f'Contact vs {side}HP') + number(row, f'Power vs {side}HP'))


def build_levels(players, report):
    """Respect CSV levels; swap within an org only to cover mandatory positions."""
    result = defaultdict(list)
    for org in range(1, 31):
        for pitching in (False, True):
            group = sorted((r for r in players if int(r['org_id']) == org and
                            is_pitcher(r) == pitching), key=identity)
            if len(group) != 50:
                raise ValueError(f'Org {org}: expected 50 players of each type')
            slots = []
            for level in range(1, 5):
                size = (12 if level % 2 else 13) if pitching else (13 if level % 2 else 12)
                roles = ['SP']*5 + ['RP']*(size-5) if pitching else list(FIELD_POSITIONS)+['B']*(size-8)
                slots.extend((level, role) for role in roles)
            costs = []
            for level, role in slots:
                costs.append([])
                for r in group:
                    fit = (0 if role != 'SP' or r['First Position'] == 'SP' else 1000000) if pitching else (0 if role == 'B' else qualify(r, role)*100)
                    costs[-1].append(fit + abs(int(r['level_id'])-level)*100000
                                     + level*int(float(r['OverallEst'])*10))
            for i, j in enumerate(assignment(costs)):
                level, role = slots[i]
                if (pitching and role == 'SP' and group[j]['First Position'] != 'SP') or (
                        not pitching and role != 'B' and qualify(group[j], role) >= 1000000):
                    raise ValueError(f'Org {org}: cannot fill {role} at level {level}')
                row = group[j]
                result[org, level].append(row)
                if int(row['level_id']) != level:
                    report['level_changes'].append({'id': player_id(row), 'name': row['First']+' '+row['Last'],
                        'org': ORGS[org-1], 'from': int(row['level_id']), 'to': level,
                        'reason': 'cover required field positions / five starting pitchers'})
    return result


# Fixed game role arrays, confirmed in PS2 serializer and exported PC saves.
BULLPEN_CAPACITIES = {'CP': 1, 'SU': 2, 'LR': 3, 'MR': 4}


def bullpen_roles(pen):
    if len(pen) > sum(BULLPEN_CAPACITIES.values()):
        raise ValueError('Bullpen exceeds game role capacity')
    used = Counter()
    result = []
    for i, row in enumerate(pen):
        role = 'CP' if i == 0 else ('SU' if i <= 2 else (
            'LR' if row['First Position'] == 'SP' else 'MR'))
        if used[role] == BULLPEN_CAPACITIES[role]:
            role = 'MR' if role == 'LR' else 'LR'
        if used[role] == BULLPEN_CAPACITIES[role]:
            raise ValueError('No available bullpen role')
        used[role] += 1
        result.append(role)
    return result


def lineup(players, side, dh):
    hitters = sorted((r for r in players if not is_pitcher(r)), key=identity)
    roles = list(FIELD_POSITIONS) + (['DH'] if dh else [])
    costs = [[(0 if pos == 'DH' else qualify(r, pos)*1000) + 200-offense(r, side)
              for r in hitters] for pos in roles]
    matched = assignment(costs)
    starters = []
    result = {player_id(r): ['B', '-1'] for r in hitters}
    for i, j in enumerate(matched):
        if costs[i][j] >= 1000000:
            raise ValueError(f'No qualified {roles[i]} in lineup')
        starters.append((hitters[j], roles[i]))
    # Deterministic batting order: best on-base/contact hitter leads off,
    # strongest remaining hitter bats third, strongest power bats cleanup.
    batting = sorted(starters, key=lambda x: (-offense(x[0], side), identity(x[0])))
    third = batting.pop(0)
    cleanup = max(batting, key=lambda x: (number(x[0], f'Power vs {side}HP'), offense(x[0], side)))
    batting.remove(cleanup)
    leadoff = max(batting, key=lambda x: (number(x[0], f'Contact vs {side}HP') + number(x[0], 'Plate Discipline') + number(x[0], 'Speed')/2))
    batting.remove(leadoff)
    batting = [leadoff, batting[0], third, cleanup] + batting[1:]
    for order, (row, role) in enumerate(batting, 1):
        result[player_id(row)] = [role, str(order)]
    pitchers = sorted((r for r in players if is_pitcher(r)),
                      key=lambda r: (-float(r['OverallEst']), identity(r)))
    rotation = [r for r in pitchers if r['First Position'] == 'SP'][:5]
    if len(rotation) != 5:
        raise ValueError('Team does not have five starting pitchers')
    for i, r in enumerate(rotation, 1):
        result[player_id(r)] = ['SP'+str(i), '9' if not dh and i == 1 else '-1']
    pen = [r for r in pitchers if r not in rotation]
    pen.sort(key=lambda r: (r['First Position'] != 'RP', -float(r['OverallEst']), identity(r)))
    for r, role in zip(pen, bullpen_roles(pen)):
        result[player_id(r)] = [role, '-1']
    return result


def attributes(src, template, year, report):
    r = template.copy()
    def put(name, value):
        key = 'playerattrib_'+name
        if key not in r:
            raise ValueError(f'Baseline lacks {key}')
        r[key] = str(value)
    r['first_name'], r['last_name'] = src['First'], src['Last']
    put('jerseynum', number(src, 'Jersey Number', 0, 99))
    put('bats', {'R': 0, 'L': 1, 'S': 2}[src['Bats']])
    put('throws', {'R': 0, 'L': 1}[src['Throws']])
    primary = src['First Position']
    secondary = src['Second Position']
    if secondary in ('', 'NA', 'NONE'):
        secondary = {'SP': 'RP', 'RP': 'SP'}.get(primary, primary)
    put('primary_position', POSITIONS[primary])
    put('secondary_position', POSITIONS[secondary])
    height = number(src, 'Height', 48, 90)
    weight = number(src, 'Weight', 100, 400)
    put('height', height-48)
    put('weight', weight-100)
    put('bodytype', {'Skinny': 0, 'Athletic': 1, 'Heavy': 2}[src['Body Type']])
    face = number(src, 'Face', 1, 15)
    put('face', 900+face)
    put('face2004style', 0)
    put('skin_tone', (0, 1, 1, 2, 2, 3, 4, 5, 5, 6, 7, 8, 9, 9, 10)[face-1])
    for f, dest, maximum in [('Hair Style', 'hairstyle', 10), ('Hair Color', 'haircolour', 7),
                              ('Facial Hair', 'facialhair', 8)]:
        put(dest, number(src, f, 1, maximum)-1)
    put('audioid', 0)
    put('photo', 2)
    put('hidden', 0)
    put('starpower', number(src, 'Career Potential', 1, 5)-1)
    put('topprospect', 0)
    put('salary', 3)  # Source has no contracts: $300,000 / one year, not donor contracts.
    put('contract_length', 1)
    put('ditty', number(src, 'Batter Ditty Type', 1, 7)-1)
    shifted_year = number(src, 'Birth Year', 1900, 2100) - year + 2005
    month = number(src, 'Birth Month', 1, 12)
    day = number(src, 'Birth Date', 1, 31)
    try:
        birthday = date(shifted_year, month, day)
    except ValueError:
        if (month, day) != (2, 29):
            raise
        birthday = date(shifted_year, 2, 28)
        report['adjustments'].append({'id': player_id(src), 'field': 'birthday',
                                       'reason': 'Feb 29 becomes Feb 28 in shifted non-leap year'})
    put('birthday', (birthday-date(1947, 12, 31)).days)
    for dest, field in {
        'platediscipline': 'Plate Discipline', 'bunting': 'Bunting',
        'stealing_aggressive': 'Stealing Tendency', 'baserunning': 'Baserunning Ability',
        'fielding': 'Fielding', 'range': 'Range', 'throwstrength': 'Throwing Strength',
        'throwaccuracy': 'Throwing Accuracy', 'durability': 'Durability',
    }.items():
        put(dest, discrete(number(src, field, 0, 99)))
    put('speed', number(src, 'Speed', 0, 99))
    stance = src['Batter Stance']
    if stance not in STANCES:
        if stance not in ('Generic 3', 'Bent', 'Closed', 'Open'):
            raise ValueError(f'Unknown batting stance: {stance}')
        report['generic_stance_fallbacks'][stance] += 1
    put('battingstance', STANCES.get(stance, 0))
    return r


def batting_attributes(src, template, side):
    r = template.copy()
    r['first_name'], r['last_name'] = src['First'], src['Last']
    r['lrattrib_contact'] = str(number(src, f'Contact vs {side}HP', 0, 100))
    r['lrattrib_power'] = str(number(src, f'Power vs {side}HP', 0, 100))
    heat = src['heatmap_v'+side]
    if len(heat) != 9 or set(heat)-set('HNC'):
        raise ValueError(f'Invalid hot/cold zones: {heat}')
    for zone, value in zip(('ul', 'um', 'ur', 'cl', 'cm', 'cr', 'll', 'lm', 'lr'), heat):
        r['lrattrib_hit_'+zone] = str({'C': 0, 'N': 1, 'H': 2}[value])
    for source, dest in [('Fastball', 'fb'), ('Curveball', 'slowbreak'), ('Slider', 'hardbreak')]:
        for kind in ('Take', 'Miss', 'Chase'):
            key = 'lrattrib_'+kind.lower()+dest
            if key in r:
                value = number(src, f'{source} {kind} vs {side}HP', 0, 99)
                r[key] = str(discrete(value))
    return r


def pitching_attributes(src, template, descriptions, report):
    r = template.copy()
    r['first_name'], r['last_name'] = src['First'], src['Last']
    def put(field, value):
        r['pitchattrib_'+field] = str(value)
    put('stamina', number(src, 'Stamina', 0, 99))
    put('pickoff', discrete(number(src, 'Pickoff', 0, 99)))
    put('fastball_movement', 0)
    put('fastball_description', 0)
    put('fastball_control', number(src, 'Fastball Control', 0, 100))
    put('fastball_velocity', number(src, 'Fastball Velocity', 40, 110))
    pitches = [(i+1, p) for i, p in enumerate(PITCHES) if src.get(p+' Control', 'NA') not in ('NA', '')]
    if len(pitches) > 4:
        report['adjustments'].append({'id': player_id(src), 'field': 'pitches',
            'reason': 'five-pitch limit; kept source creation order', 'omitted': [p for _, p in pitches[4:]]})
    for slot in range(2, 6):
        for field in ('type', 'movement', 'description', 'control', 'velocity'):
            put(f'pitch{slot}_{field}', '-')
    for slot, (code, pitch) in enumerate(pitches[:4], 2):
        put(f'pitch{slot}_type', code)
        put(f'pitch{slot}_movement', discrete(number(src, pitch+' Movement', 0, 99)))
        put(f'pitch{slot}_description', descriptions[code])
        put(f'pitch{slot}_control', number(src, pitch+' Control', 0, 100))
        put(f'pitch{slot}_velocity', number(src, pitch+' Velocity', 40, 110))
    delivery = src['Pitcher Delivery']
    if delivery not in DELIVERIES:
        raise ValueError(f'Unknown pitcher delivery: {delivery}')
    put('pitcher_delivery', DELIVERIES[delivery])
    return r


def filter_history(raw, keep):
    if len(raw) < 4:
        raise ValueError('Truncated hist.dat')
    count = int.from_bytes(raw[:4], 'little')
    if len(raw) != 4 + count*25:
        raise ValueError('Unknown hist.dat layout; expected count plus 25-byte records')
    records = [raw[i:i+25] for i in range(4, len(raw), 25)
               if f'0{int.from_bytes(raw[i:i+4], "little"):08x}' in keep]
    return len(records).to_bytes(4, 'little') + b''.join(records)


def allstar_roster(pool):
    selected = []
    for pitching in (False, True):
        group = sorted((r for r in pool if is_pitcher(r) == pitching), key=identity)
        roles = ['SP']*5 + ['RP']*6 if pitching else list(FIELD_POSITIONS)+['B']*6
        costs = [[(0 if role in ('RP', 'B') or (pitching and r['First Position'] == 'SP')
                    else (1000000 if pitching else qualify(r, role)*1000))
                  + 1000 - (int(float(r['OverallEst'])*10) if pitching else offense(r))
                  for r in group] for role in roles]
        for i, j in enumerate(assignment(costs)):
            if costs[i][j] >= 1000000:
                raise ValueError('Cannot fill all-star roster')
            selected.append(group[j])
    return selected


def convert(source: Path, baseline: Path, output: Path, year: int):
    """Publish only a fully serialized and validated package."""
    if output.exists():
        raise ValueError(f'Output already exists: {output}; choose a new directory')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.mvp-convert-', dir=output.parent) as tmp:
        staged = Path(tmp)/'package'
        report = _convert(source, baseline, staged, year)
        staged.rename(output)
    return report


def prepare_source(source: Path, year: int):
    """Read and select CSV once, then assign affiliate levels independently of a platform."""
    with source.open(newline='', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames or len(set(reader.fieldnames)) != len(reader.fieldnames):
            raise ValueError('Invalid CSV header')
        raw = list(reader)
    selected = []
    omitted = []
    for i, r in enumerate(raw, 2):
        if None in r or None in r.values():
            raise ValueError(f'CSV row {i}: field count differs from header')
        if r['level_id'] not in ('', 'NA'):
            number(r, 'level_id', 1, 4)
            number(r, 'org_id', 1, 30)
            if r['First Position'] == 'DH':
                r['First Position'] = 'RF' if r['First'] == 'Ohtani' else '1B'
            selected.append(r)
        else:
            omitted.append({'source_row': i, 'name': r['First']+' '+r['Last'],
                            'reason': 'no source level assignment (outside selected 100/org or free agent)'})
    if len(selected) != 3000:
        raise ValueError(f'Expected 3000 selected players, found {len(selected)}; source selection changed')
    ids = [player_id(r) for r in selected]
    if len(set(ids)) != len(ids):
        raise ValueError('Duplicate player identity or ID collision')
    report = {'format_version': 1, 'source': source.name, 'source_sha256': digest(source),
              'source_year': year, 'game_year': 2005, 'baseline_sha256': {},
              'source_records': len(raw), 'modern_players': len(selected),
              'level_changes': [], 'adjustments': [], 'omitted': omitted,
              'generic_stance_fallbacks': Counter(), 'generic_delivery_fallbacks': Counter(),
              'runtime_validation': 'not performed by converter'}
    levels = build_levels(selected, report)
    source_identity = {player_id(r): identity(r) for r in selected}
    lineups = {f'{org}:{level}': {
        f'{side}:{rules}': {source_identity[rid]: value for rid, value in
                          lineup(rows, side.upper(), rules == 'al').items()}
        for side in ('r', 'l') for rules in ('al', 'nl')}
        for (org, level), rows in levels.items()}
    return {'schema': 'mvp-shared-roster/v1', 'selected': selected, 'report': report,
            'lineups': lineups,
            'levels': {f'{org}:{level}': [identity(r) for r in rows]
                       for (org, level), rows in levels.items()}}


def build_database(source: Path, baseline: Path, year: int, prepared=None):
    """Build validated logical tables; no DAT serialization or filesystem writes."""
    tables = {n: Table.read(baseline/(n+'.dat')) for n in
              ALL_PLAYER_TABLES + PITCHER_TABLES + ('team', 'org', 'roster')}
    baseline_hashes = {p.name: digest(p) for p in sorted(baseline.iterdir()) if p.is_file()}
    prepared = deepcopy(prepared if prepared is not None else prepare_source(source, year))
    selected, report = prepared['selected'], prepared['report']
    if report['source_year'] != year or report['source'] != source.name:
        raise ValueError('Prepared source metadata does not match requested source/year')
    report['baseline_sha256'] = baseline_hashes
    source_ids = {player_id(r): identity(r) for r in selected}
    if set(source_ids) & tables['attrib'].rows.keys():
        raise ValueError('Duplicate player identity or ID collision')
    by_code = {r['unique_team'].upper(): r for r in tables['org'].rows.values() if r['org_is_franchise'] == '1'}
    # Reuse every ordinary stock ID: the executable/demo may refer to those IDs
    # even when they no longer appear in an active roster. New IDs fill only the
    # additional slots needed for 100 players per organization.
    regular_team_ids = {f'0{int(row[f]):08x}' for row in by_code.values()
                        for f in ('org_team_mlb', 'org_team_aaa', 'org_team_aa', 'org_team_a')}
    ordinary_ids = {r['roster_playerid'] for r in tables['roster'].rows.values()
                    if r['roster_teamid'] in regular_team_ids}
    special_ids = {r['roster_playerid'] for r in tables['roster'].rows.values()
                  if r['roster_teamid'] not in regular_team_ids and
                  tables['team'].rows[r['roster_teamid']]['unique_team'] not in ('AL', 'NL')}
    donors = ordinary_ids-special_ids
    for pitching in (False, True):
        donor_group = sorted(rid for rid in donors if
                             (rid in tables['pitcher'].rows) == pitching)
        source_group = sorted((r for r in selected if is_pitcher(r) == pitching), key=identity)
        if len(donor_group) > len(source_group):
            raise ValueError('Not enough modern players to populate the stock ID space')
        for src, rid in zip(source_group, donor_group):
            src['_game_id'] = rid
    ids = [player_id(r) for r in selected]
    report['stock_ids_reused'] = len(donors)
    if len(set(ids)) != len(ids) or set(ids) & (tables['attrib'].rows.keys()-donors):
        raise ValueError('Assigned player ID collision')
    by_identity = {identity(r): r for r in selected}
    for change in report['level_changes']:
        change['id'] = player_id(by_identity[source_ids[change['id']]])
    levels = {tuple(map(int, key.split(':'))): [by_identity[i] for i in members]
              for key, members in prepared['levels'].items()}
    team_players = {}
    planned_lineups = {}
    leagues = {}
    for (org, level), players in sorted(levels.items()):
        code = PC_ORGS.get(ORGS[org-1], ORGS[org-1])
        org_row = by_code[code]
        team_id = f'0{int(org_row[("org_team_mlb", "org_team_aaa", "org_team_aa", "org_team_a")[level-1]]):08x}'
        if team_id not in tables['team'].rows:
            raise ValueError(f'Missing affiliate team {team_id}')
        team_players[team_id] = players
        planned_lineups[team_id] = {
            tuple(key.split(':')): {player_id(by_identity[i]): value for i, value in mapping.items()}
            for key, mapping in prepared['lineups'][f'{org}:{level}'].items()}
        if level == 1:
            leagues[team_id] = tables['team'].rows[team_id]['team_league']
    for team_id, row in tables['team'].rows.items():
        if row['unique_team'] in ('AL', 'NL'):
            league = '0' if row['unique_team'] == 'AL' else '1'
            pool = [p for tid, players in team_players.items() if leagues.get(tid) == league for p in players]
            team_players[team_id] = allstar_roster(pool)
    untouched_rosters = [r for r in tables['roster'].rows.values() if r['roster_teamid'] not in team_players]
    keep = {r['roster_playerid'] for r in untouched_rosters}
    defaults = [rid for rid, r in tables['attrib'].rows.items()
                if r['first_name'] == 'Default' and r['last_name'] == 'Default']
    if len(defaults) != 1:
        raise ValueError('Expected one Default player template')
    default_id = defaults[0]
    keep.add(default_id)
    report['retained_special_players'] = len(keep)-1
    # Keep a full baseline record for appearance geometry and unspecified values.
    templates = {n: t.rows[default_id].copy() for n, t in tables.items()
                 if n in ALL_PLAYER_TABLES + PITCHER_TABLES}
    descriptions = defaultdict(Counter)
    for r in tables['pitcher'].rows.values():
        for slot in range(2, 6):
            code = r[f'pitchattrib_pitch{slot}_type']
            if code != '-':
                descriptions[int(code)][int(r[f'pitchattrib_pitch{slot}_description'])] += 1
    descriptions = {code: c.most_common(1)[0][0] for code, c in descriptions.items()}
    report['pitch_trajectory_defaults'] = descriptions
    # Patched PC lhattrib omits hard-break chase. Add a named field, preserving
    # all original column numbers; the same attribute exists in rhattrib.
    lh = tables['lhattrib']
    chase = 'lrattrib_chasehardbreak'
    if chase not in lh.fields.values():
        lh.fields[max(lh.fields)+1] = chase
        for rid, r in lh.rows.items():
            r[chase] = tables['rhattrib'].rows[rid][chase]
        templates['lhattrib'][chase] = templates['rhattrib'][chase]
        report['adjustments'].append({'field': chase, 'reason': 'added missing LH column; retained players use RH chase'})
    for n in ALL_PLAYER_TABLES + PITCHER_TABLES:
        tables[n].rows = {rid: r for rid, r in tables[n].rows.items() if rid in keep}
    for src in sorted(selected, key=identity):
        rid = player_id(src)
        for n in ALL_PLAYER_TABLES + (PITCHER_TABLES if is_pitcher(src) else ()):
            if n == 'attrib':
                row = attributes(src, templates[n], year, report)
            elif n in ('lhattrib', 'rhattrib'):
                row = batting_attributes(src, templates[n], n[0].upper())
            elif n == 'pitcher':
                row = pitching_attributes(src, templates[n], descriptions, report)
            else:
                row = {f: '0' for f in tables[n].fields.values()}
                row['first_name'], row['last_name'] = src['First'], src['Last']
            tables[n].rows[rid] = row
    roster_rows = []
    assignments = []
    for tid in tables['team'].rows:
        if tid not in team_players:
            roster_rows.extend(r for r in untouched_rosters if r['roster_teamid'] == tid)
            continue
        players = team_players[tid]
        lineups = planned_lineups.get(tid)
        if lineups is None:
            lineups = {(side, rules): lineup(players, side.upper(), rules == 'al')
                       for side in ('r', 'l') for rules in ('al', 'nl')}
        def roster_order(src):
            role = lineups['r', 'al'][player_id(src)][0]
            if is_pitcher(src):
                return (1, ['SP1', 'SP2', 'SP3', 'SP4', 'SP5', 'LR', 'MR', 'SU', 'CP'].index(role), identity(src))
            return (0, POSITIONS[src['First Position']], identity(src))
        for src in sorted(players, key=roster_order):
            rid = player_id(src)
            row = {'roster_teamid': tid, 'roster_playerid': rid}
            for (side, rules), mapping in lineups.items():
                role, order = mapping[rid]
                row[f'{side}h_roster_{rules}_position'] = role
                row[f'{side}h_roster_{rules}_battingorder'] = order
            roster_rows.append(row)
            assignments.append({'id': rid, 'identity': identity(src), 'name': src['First']+' '+src['Last'],
                                'org': ORGS[int(src['org_id'])-1], 'source_level': src['level_id'],
                                'team': tables['team'].rows[tid]['unique_team'], **row})
    tables['roster'].rows = {f'0{i:08x}': r for i, r in enumerate(roster_rows)}
    validate_tables(tables, set(ids))
    return tables, report, assignments, selected, keep


def _convert(source: Path, baseline: Path, output: Path, year: int, prepared=None):
    if output.exists():
        raise ValueError(f'Output already exists: {output}; choose a new directory')
    tables, report, assignments, selected, keep = build_database(source, baseline, year, prepared)
    history = filter_history((baseline/'hist.dat').read_bytes(), keep)
    # Nothing is written until parsing, conversion, and relational checks succeed.
    output.mkdir(parents=True)
    db = output/'database'
    db.mkdir()
    for n in ALL_PLAYER_TABLES + PITCHER_TABLES + ('roster',):
        tables[n].write(db/(n+'.dat'))
        if Table.read(db/(n+'.dat')) != tables[n]:
            raise ValueError(f'{n}: output failed round-trip validation')
    (db/'hist.dat').write_bytes(history)
    with (output/'players.csv').open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=list(assignments[0]))
        writer.writeheader()
        writer.writerows(assignments)
    report['output_sha256'] = {p.name: digest(p) for p in sorted(db.iterdir())}
    report['validation'] = {'tables': 'passed', 'modern_organizations': 30,
                            'modern_teams': 120, 'allstar_teams': 2,
                            'players_per_team': 25, 'round_trip': 'passed'}
    (output/'report.json').write_text(json.dumps(report, indent=2, sort_keys=True)+'\n')
    (output/'id-map.json').write_text(json.dumps({identity(r): player_id(r) for r in selected},
                                                indent=2, sort_keys=True)+'\n')
    return report


def validate_tables(tables, modern_ids):
    a = tables['attrib'].rows
    for n in ALL_PLAYER_TABLES:
        if tables[n].rows.keys() != a.keys():
            raise ValueError(f'{n}: player IDs differ from attrib')
    for n in PITCHER_TABLES:
        if tables[n].rows.keys() != tables['pitcher'].rows.keys():
            raise ValueError(f'{n}: pitcher IDs differ')
    if tables['pitcher'].rows.keys()-a.keys():
        raise ValueError('Pitcher without player attributes')
    for n in ALL_PLAYER_TABLES + PITCHER_TABLES:
        for rid, row in tables[n].rows.items():
            for name in ('first_name', 'last_name'):
                if row[name] != a[rid][name]:
                    raise ValueError(f'{n}: inconsistent name for {rid}')
    teams = defaultdict(list)
    for row in tables['roster'].rows.values():
        if row['roster_playerid'] not in a or row['roster_teamid'] not in tables['team'].rows:
            raise ValueError('Dangling roster reference')
        teams[row['roster_teamid']].append(row)
    appearances = Counter()
    for tid, roster in teams.items():
        if len(roster) != 25 or len({r['roster_playerid'] for r in roster}) != 25:
            raise ValueError(f'{tid}: roster must contain 25 distinct players')
        for side in ('lh', 'rh'):
            for rules in ('al', 'nl'):
                prefix = f'{side}_roster_{rules}_'
                roles = Counter(r[prefix+'position'] for r in roster)
                if any(roles[k] > limit for k, limit in BULLPEN_CAPACITIES.items()):
                    raise ValueError(f'{tid}: pitching role exceeds game capacity')
                needed = FIELD_POSITIONS + tuple('SP'+str(i) for i in range(1, 6)) + ('CP',)
                if any(roles[k] != 1 for k in needed):
                    raise ValueError(f'{tid}: incomplete field/rotation/closer')
                orders = sorted(int(r[prefix+'battingorder']) for r in roster if r[prefix+'battingorder'] != '-1')
                if orders != list(range(1, 10)):
                    raise ValueError(f'{tid}: invalid batting order {orders}')
        code = tables['team'].rows[tid]['unique_team']
        if code not in ('AL', 'NL'):
            appearances.update(r['roster_playerid'] for r in roster if r['roster_playerid'] in modern_ids)
    if set(appearances) != modern_ids or any(v != 1 for v in appearances.values()):
        raise ValueError('Modern player is missing or belongs to multiple organizations')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True, help='MVProsters_YYYY-MM-DD.csv')
    parser.add_argument('--baseline', type=Path, required=True, help='Updated PC data/database directory')
    parser.add_argument('--output', type=Path, required=True, help='New output package directory')
    parser.add_argument('--source-year', type=int, help='Roster season; defaults to year in CSV filename')
    args = parser.parse_args()
    match = re.search(r'(20\d\d)-\d\d-\d\d', args.source.name)
    year = args.source_year or (int(match[1]) if match else None)
    if year is None:
        parser.error('Cannot infer roster season; supply --source-year')
    try:
        report = convert(args.source, args.baseline, args.output, year)
    except (ValueError, KeyError, OSError) as exc:
        parser.exit(1, f'Conversion failed: {exc}\n')
    print(f'Converted {report["modern_players"]} modern players to {args.output}')
    print(f'Validation passed; {len(report["level_changes"])} level changes. See report.json.')


if __name__ == '__main__':
    main()
