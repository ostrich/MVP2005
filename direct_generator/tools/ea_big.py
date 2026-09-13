#!/usr/bin/env python3
"""Extract EA BIGF archives and RefPack 0x10fb members for local research."""
import argparse
import struct
from pathlib import Path


def refpack(data):
    if data[:2] != b'\x10\xfb':
        return data
    size=int.from_bytes(data[2:5],'big')
    p=5;out=bytearray()
    def take(n):
        nonlocal p
        if p+n>len(data):raise ValueError('Truncated RefPack stream')
        v=data[p:p+n];p+=n;return v
    while True:
        c=take(1)[0];length=distance=0;stop=False
        if c<0x80:
            d=take(1)[0];literal=c&3;length=((c>>2)&7)+3;distance=((c&0x60)<<3)+d+1
        elif c<0xc0:
            x,y=take(2);literal=x>>6;length=(c&63)+4;distance=((x&63)<<8)+y+1
        elif c<0xe0:
            x,y,z=take(3);literal=c&3;length=((c&12)<<6)+z+5;distance=((c&16)<<12)+(x<<8)+y+1
        elif c<0xfc:
            literal=((c&31)<<2)+4
        else:
            literal=c&3;stop=True
        out.extend(take(literal))
        if length:
            if distance>len(out):raise ValueError('Invalid RefPack backreference')
            for _ in range(length):out.append(out[-distance])
        if len(out)>size:raise ValueError('RefPack output exceeds declared length')
        if stop:break
    if len(out)!=size:raise ValueError('RefPack length mismatch')
    return bytes(out)


def extract(source,target):
    b=source.read_bytes()
    if b[:4]!=b'BIGF':raise ValueError('Unsupported BIG signature')
    if struct.unpack_from('<I',b,4)[0]!=len(b):raise ValueError('BIG length mismatch')
    count,header=struct.unpack_from('>II',b,8);p=16;files={}
    for _ in range(count):
        off,size=struct.unpack_from('>II',b,p);p+=8;end=b.index(0,p)
        name=b[p:end].decode('ascii');p=end+1
        if not name or '/' in name or '\\' in name or name in ('.','..') or name in files:raise ValueError('Unsafe/duplicate BIG member')
        if off<header or off+size>len(b):raise ValueError('Invalid BIG member range')
        files[name]=refpack(b[off:off+size])
    if p>header:raise ValueError('BIG header overlaps data')
    target.mkdir(parents=True,exist_ok=False)
    for name,data in files.items():(target/name).write_bytes(data)
    return files

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('archive',type=Path);p.add_argument('output',type=Path);a=p.parse_args()
    for name,b in extract(a.archive,a.output).items():print(name,len(b))
