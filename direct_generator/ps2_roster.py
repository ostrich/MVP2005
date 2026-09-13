#!/usr/bin/env python3
"""Inspect MVP 2005 PS2 saves and make bounded, checksum-correct research edits.

Writes only new files; source saves stay unchanged.
See docs/FORMAT.md and docs/VALIDATION.md for format notes and validation scope.
"""
import argparse
import hashlib
import json
import struct
from pathlib import Path

from ps2_teams import Teams

POLY=0x04c11db7
CRC_TABLE=[]
for i in range(256):
    v=i<<24
    for _ in range(8):v=((v<<1)^(POLY if v&0x80000000 else 0))&0xffffffff
    CRC_TABLE.append(v)


def ea_crc(data):
    """EA non-reflected, direct-byte CRC (not zlib.crc32).

Algorithm corroborated against zyzalfors/EAPS2SaveChecksumFixer and all supplied saves.
    """
    if len(data)<4:return 0
    crc=int.from_bytes(data[:4],'big')^0xffffffff
    for b in data[4:]:crc=(((crc<<8)|b)^CRC_TABLE[crc>>24])&0xffffffff
    return crc^0xffffffff


# Bit positions relative to the beginning of the 60-byte player record.
# Widths are established from observed ranges and adjacent fields; gaps stay opaque.
ATTR={
 'audioid':(0,16),'birthday':(16,16),'height':(32,6),'weight':(38,8),'jerseynum':(46,7),
 'primary_position':(53,4),'secondary_position':(57,5),'photo':(62,2),
 'bats':(64,2),'throws':(66,1),'ditty':(67,3),'hidden':(70,1),
 'bunting':(71,4),'speed':(75,7),'throwstrength':(82,4),'throwaccuracy':(86,4),
 'fielding':(90,4),'range':(96,4),'durability':(100,4),'platediscipline':(104,4),
 'stealing_aggressive':(108,4),'baserunning':(112,4),'starpower':(116,3),
 'topprospect':(119,1),'salary':(120,8),'contract_length':(128,3),
 'offercount':(131,2),'personality':(133,2),'playedtoday':(135,8),
 'energylevel':(143,7),'injurytype':(150,7),'injuryduration':(160,8),
 'swingtype':(168,1),'bodytype':(216,2),'promisedrole':(231,5),
 'tooinjured':(236,1),'contractvalueadj':(237,2),'contractyearadj':(239,2),
 'contractroleadj':(241,3),
 'battingstance':(169,7),'catchermask':(176,1),'hairstyle':(177,4),
 'skin_tone':(181,4),'haircolour':(185,3),'fieldglovecolour':(188,3),
 'batcolour':(192,3),'facialhair':(195,3),'elbowguard':(198,2),
 'shinguard':(200,2),'wristband':(202,3),'face':(205,10),'face2004style':(215,1),
 'socks':(218,2),'batglove':(220,1),'boneprofile':(224,7),
}
BATTING={'contact':(0,7),'power':(7,7)}
for j,zone in enumerate(('ul','cl','ll','um','cm','lm','ur','cr','lr')):BATTING['hit_'+zone]=(14+j*2,2)
for j,name in enumerate(('chasefb','chaseslowbreak','chasehardbreak','takefb','takeslowbreak','takehardbreak','missfb','missslowbreak','misshardbreak')):BATTING[name]=(32+j*4,4)
for j,name in enumerate(('lf_pct','cf_pct','rf_pct','hr_pct','fb_pct','ld_pct','gb_pct')):BATTING[name]=(68+j*7,7)
PITCHING={'fastball_movement':(11,1),'fastball_description':(12,1),'stamina':(0,7),'pickoff':(7,4),'fastball_control':(13,7),
          'fastball_velocity':(20,7),'pitcher_delivery':(128,7),'current_stamina_nl':(135,7)}
for slot,base in ((2,27),(3,53),(4,78),(5,103)):
    PITCHING[f'pitch{slot}_type']=(base,4)
    # Slot two has one additional bit before movement, unlike slots three-five.
    at=base+5 if slot==2 else base+4
    for name,width in (('movement',4),('description',3),('control',7),('velocity',7)):
        PITCHING[f'pitch{slot}_{name}']=(at,width);at+=width


def decode(raw,fields):
    n=int.from_bytes(raw,'little')
    return {f:n>>bit&((1<<width)-1) for f,(bit,width) in fields.items()}


class Roster:
    CAPACITY=3250
    def __init__(self,data):
        self.data=data
        if len(data)<200:raise ValueError('Truncated save')
        self.header_size,self.body_size=struct.unpack_from('<II',data,16)
        if self.header_size!=200 or len(data)!=200+self.body_size or self.body_size!=936960:
            raise ValueError('Unsupported MVP roster container')
        expected=struct.unpack_from('<II',data)
        if expected!=(ea_crc(data[16:200]),ea_crc(data[200:])):
            raise ValueError('Save checksum mismatch')
        self.platform='ps2' if data[168:175]==b'BASLUS-' else 'pc'
        self.name_offset=31 if self.platform=='ps2' else 32
        marker=b'Default'+b'\0'*5+b'Default'+b'\0'*5
        candidates=[];off=0
        while (off:=data.find(marker,off))>=0:
            base=off-self.name_offset
            if base>=4 and data[base-4:base]==bytes.fromhex('1b3c8ff5'):candidates.append(base)
            off+=1
        if len(candidates)!=1:raise ValueError('Cannot uniquely locate player array')
        self.attrib=candidates[0]
        start=self.attrib-4-self.CAPACITY*12
        self.ids={};self.index={}
        for n in range(self.CAPACITY):
            key,i,j=struct.unpack_from('<III',data,start+n*12)
            if i!=j or i>=self.CAPACITY or i in self.ids or key in self.index:raise ValueError('Invalid player index')
            self.ids[i]=key;self.index[key]=i
        self.lh=self.attrib+self.CAPACITY*60+4
        self.rh=self.lh+self.CAPACITY*16+4
        for at in (self.lh,self.rh):
            if data[at-4:at]!=bytes.fromhex('1b3c8ff5'):raise ValueError('Missing batting array marker')
        # Fixed relative offset observed in all nine supplied PS2 rosters and PC export.
        self.pitch_header=self.attrib+0x92028
        capacity,count=struct.unpack_from('<II',data,self.pitch_header)
        if capacity!=1800 or count>capacity:raise ValueError('Unsupported pitcher index layout')
        self.pitch_index={}
        for n in range(count):
            key,i,j=struct.unpack_from('<III',data,self.pitch_header+8+n*12)
            if i!=j or i>=capacity or key in self.pitch_index or key not in self.index:raise ValueError('Invalid pitcher index')
            self.pitch_index[key]=i
        if len(set(self.pitch_index.values()))!=count:raise ValueError('Duplicate pitcher index')
        self.pitch=self.pitch_header+8+capacity*12+4

    def teams(self):
        return Teams(self.data, self.index)

    def swap_batting_order(self, team_id, variant, first, second):
        if self.platform != 'ps2':
            raise ValueError('Research patching currently supports PS2 only')
        result = self.teams().swap_batting_order(self.data, team_id, variant, first, second)
        struct.pack_into('<I', result, 4, ea_crc(result[200:]))
        result = bytes(result)
        Roster(result).teams()
        return result

    def players(self):
        for i in range(self.CAPACITY):
            at=self.attrib+i*60;raw=self.data[at:at+60];name=self.name_offset
            first=raw[name:name+12].split(b'\0')[0].decode('cp1252')
            last=raw[name+12:name+28].split(b'\0')[0].decode('cp1252')
            key=self.ids[i]
            r={'index':i,'id':f'{key:08x}','first':first,'last':last,
               'attributes':decode(raw[:self.name_offset],ATTR),
               'vs_lhp':decode(self.data[self.lh+i*16:self.lh+(i+1)*16],BATTING),
               'vs_rhp':decode(self.data[self.rh+i*16:self.rh+(i+1)*16],BATTING)}
            if key in self.pitch_index:
                pi=self.pitch_index[key]
                r['pitching']=decode(self.data[self.pitch+pi*20:self.pitch+(pi+1)*20],PITCHING)
            yield r

    def patch(self,player_id,field,value):
        if self.platform!='ps2':raise ValueError('Research patching currently supports PS2 only')
        key=int(player_id,16)
        if key not in self.index:raise ValueError('Unknown player ID')
        i=self.index[key]
        group,name=field.split('.',1)
        if group=='attributes':fields=ATTR;at=self.attrib+i*60;size=self.name_offset
        elif group in ('vs_lhp','vs_rhp'):
            fields=BATTING;at=(self.lh if group=='vs_lhp' else self.rh)+i*16;size=16
        elif group=='pitching' and key in self.pitch_index:
            fields=PITCHING;at=self.pitch+self.pitch_index[key]*20;size=20
        else:raise ValueError('Unknown group or player has no pitching record')
        if name not in fields:raise ValueError('Unknown or unresolved field')
        bit,width=fields[name]
        if not 0<=value<1<<width:raise ValueError('Value outside encoded bit width')
        b=bytearray(self.data);n=int.from_bytes(b[at:at+size],'little');mask=((1<<width)-1)<<bit
        n=(n&~mask)|(value<<bit);b[at:at+size]=n.to_bytes(size,'little')
        struct.pack_into('<I',b,4,ea_crc(b[200:]))
        struct.pack_into('<I',b,0,ea_crc(b[16:200]))
        result=bytes(b);Roster(result)
        return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('save',type=Path);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--player-id');p.add_argument('--field');p.add_argument('--value',type=int)
    p.add_argument('--team-id')
    p.add_argument('--lineup', choices=('rh_al','rh_nl','lh_al','lh_nl'))
    p.add_argument('--swap-order', nargs=2, type=int, metavar=('FIRST','SECOND'))
    a=p.parse_args()
    try:
        r=Roster(a.save.read_bytes())
        player_edit=a.player_id is not None or a.field is not None or a.value is not None
        team_edit=a.team_id is not None or a.lineup is not None or a.swap_order is not None
        if player_edit and team_edit:p.error('Choose a player edit or a lineup edit')
        if team_edit:
            if a.team_id is None or a.lineup is None or a.swap_order is None:
                p.error('Lineup editing requires --team-id, --lineup, --swap-order')
            data=r.swap_batting_order(a.team_id,a.lineup,*a.swap_order)
        elif player_edit:
            if a.player_id is None or a.field is None or a.value is None:p.error('Patching requires --player-id, --field, --value')
            data=r.patch(a.player_id,a.field,a.value)
        else:
            data=(json.dumps({'source_sha256':hashlib.sha256(r.data).hexdigest(),
                             'platform':r.platform,'checksums':'passed','in_game_validated':False,
                             'offsets':{'attrib':r.attrib,'lhattrib':r.lh,'rhattrib':r.rh,'pitcher':r.pitch},
                             'capacity':r.CAPACITY,'players':list(r.players()),
                             'teams':r.teams().records},indent=2)+'\n').encode()
        with a.output.open('xb') as f:f.write(data)
        print(a.output)
    except (OSError,ValueError,KeyError) as e:p.exit(1,f'Failed: {e}\n')

if __name__=='__main__':main()
