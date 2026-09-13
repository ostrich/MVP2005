"""MVP 2005 team serialization, established from the US PS2 executable and saves.

Offsets are located from a validated 126-entry registry, not absolute addresses.
Unknown bytes and inactive slots remain visible and are preserved during edits.
"""
import struct

VARIANTS=('rh_al','rh_nl','lh_al','lh_nl')
POSITIONS=('P','C','1B','2B','3B','SS','LF','CF','RF','DH')
ROLE_CAPACITIES={'SP':5,'LR':3,'MR':4,'SU':2,'CP':1}


def parse_team(data, start, player_ids):
    at=start
    def take(n):
        nonlocal at
        if n<0 or at+n>len(data):raise ValueError('Truncated team record')
        raw=data[at:at+n];at+=n
        return raw
    lineup_raw=take(192)
    fixed_offset=at
    fixed=list(struct.unpack('<25I',take(100)))
    count,metadata=struct.unpack('<II',take(8))
    if count>25:raise ValueError('Team exceeds 25-player capacity')
    players_offset=at
    players=list(struct.unpack(f'<{count}I',take(count*4)))
    if len(set(players))!=count or any(k not in player_ids for k in players):
        raise ValueError('Invalid team player IDs')
    if fixed[:count]!=players:raise ValueError('Team player copies disagree')
    roles={}
    for role,capacity in ROLE_CAPACITIES.items():
        fixed_at=at;fixed_role=list(take(capacity))
        n,meta=struct.unpack('<II',take(8))
        if n>capacity:raise ValueError('Pitching role exceeds capacity')
        vector_at=at;values=list(take(n))
        # Empty-team source saves retain 255 placeholders in these vectors.
        if any(v!=255 and v>=count for v in values):raise ValueError('Invalid pitching role index')
        if fixed_role[:n]!=values:raise ValueError('Pitching role copies disagree')
        roles[role]={'fixed_offset':fixed_at,'fixed':fixed_role,'metadata':meta,
                     'offset':vector_at,'slots':values}
    tail=take(44)
    lineups={}
    for v,variant in enumerate(VARIANTS):
        raw=lineup_raw[v*48:(v+1)*48]
        positions=list(raw[:10]);order=list(struct.unpack_from('<9I',raw,12))
        if any(i!=255 and i>=count for i in positions):raise ValueError('Invalid lineup slot')
        # Empty source teams use 0xffffffff for absent batting-order positions.
        if any(i!=0xffffffff and i>=10 for i in order):raise ValueError('Invalid batting position')
        lineups[variant]={'offset':start+v*48,'position_slots':dict(zip(POSITIONS,positions)),
                         'padding_hex':raw[10:12].hex(),'batting_positions':order,
                         'batting_player_ids':[f'{players[positions[i]]:08x}'
                             if i<10 and positions[i]<count else None for i in order]}
    return {'offset':start,'end':at,'fixed_offset':fixed_offset,'fixed_player_ids':[f'{k:08x}' for k in fixed],
            'players_offset':players_offset,'player_ids':[f'{k:08x}' for k in players],
            'metadata':metadata,'lineups':lineups,'pitching_roles':roles,'tail_hex':tail.hex()}


class Teams:
    CAPACITY=126
    def __init__(self,data,player_ids):
        candidates=[];at=200
        marker=struct.pack('<II',self.CAPACITY,self.CAPACITY)
        while (at:=data.find(marker,at))>=0:
            try:
                candidate=self._parse(data,at,player_ids)
                candidates.append((at,candidate))
            except (ValueError,struct.error,UnicodeDecodeError):pass
            at+=1
        if len(candidates)!=1:raise ValueError('Cannot uniquely locate team registry')
        self.map_offset,(self.records,self.start,self.end)=candidates[0]

    def _parse(self,data,at,player_ids):
        map_at=at+8;records_at=map_at+self.CAPACITY*12+4
        mapping={};keys=set()
        for n in range(self.CAPACITY):
            key,i,j=struct.unpack_from('<III',data,map_at+n*12)
            if i!=j or i>=self.CAPACITY or i in mapping or key in keys:
                raise ValueError('Invalid team index')
            mapping[i]=key;keys.add(key)
        at=records_at+self.CAPACITY*60
        if struct.unpack_from('<I',data,at)[0]!=self.CAPACITY:raise ValueError('Invalid team roster count')
        start=at+4;at=start;records=[]
        for slot in range(self.CAPACITY):
            r=parse_team(data,at,player_ids);at=r['end']
            raw=data[records_at+slot*60:records_at+(slot+1)*60]
            def name(lo,hi):return raw[lo:hi].split(b'\0')[0].decode('cp1252')
            r.update(slot=slot,id=f'{mapping[slot]:08x}',unique_team=name(16,20),
                     name=name(20,40),abbreviation=name(40,44),location=name(44,60))
            records.append(r)
        return records,start,at

    def swap_batting_order(self,data,team_id,variant,first,second):
        """Exchange two batting positions (1-based), preserving all other bytes."""
        if variant not in VARIANTS:raise ValueError('Unknown lineup variant')
        if not 1<=first<=9 or not 1<=second<=9:raise ValueError('Batting slots must be 1 through 9')
        matches=[r for r in self.records if r['id']==f'{int(team_id,16):08x}']
        if len(matches)!=1:raise ValueError('Unknown team ID')
        lineup=matches[0]['lineups'][variant]
        if any(p is None for p in lineup['batting_player_ids']):raise ValueError('Cannot edit an incomplete lineup')
        at=lineup['offset']+12
        a,b=at+(first-1)*4,at+(second-1)*4
        result=bytearray(data)
        result[a:a+4],result[b:b+4]=data[b:b+4],data[a:a+4]
        return result


def serialize_team(record, player_ids):
    """Encode one team record, preserving opaque fields and inactive fixed slots.

This does not splice variable-sized records into a save container. Callers must
update both copies of membership/roles and all referring indices consistently.
    """
    parts=[]
    try:
        for variant in VARIANTS:
            lineup=record['lineups'][variant]
            padding=bytes.fromhex(lineup['padding_hex'])
            if len(padding)!=2:raise ValueError('Lineup padding must be two bytes')
            parts.extend((bytes(lineup['position_slots'][p] for p in POSITIONS),padding,
                          struct.pack('<9I',*lineup['batting_positions'])))
        fixed=[int(k,16) for k in record['fixed_player_ids']]
        players=[int(k,16) for k in record['player_ids']]
        parts.extend((struct.pack('<25I',*fixed),struct.pack('<II',len(players),record['metadata']),
                      struct.pack(f'<{len(players)}I',*players)))
        for role,capacity in ROLE_CAPACITIES.items():
            group=record['pitching_roles'][role]
            if len(group['fixed'])!=capacity:raise ValueError('Invalid fixed role array length')
            parts.extend((bytes(group['fixed']),struct.pack('<II',len(group['slots']),group['metadata']),
                          bytes(group['slots'])))
        tail=bytes.fromhex(record['tail_hex'])
        if len(tail)!=44:raise ValueError('Team tail must be 44 bytes')
        parts.append(tail)
        data=b''.join(parts)
        parsed=parse_team(data,0,player_ids)
        if parsed['end']!=len(data):raise ValueError('Team serializer length mismatch')
        return data
    except (KeyError,TypeError,struct.error,OverflowError) as e:
        raise ValueError(f'Invalid team serialization input: {e}') from e
