#!/usr/bin/env python3
"""Replace one same-size file in a NEW PS2 card copy, updating page ECC.

FAT, directory entries, other files and unrelated spare bytes remain unchanged.
This deliberately does not support adding, deleting, or resizing files.
"""
import argparse
from pathlib import Path
try:
    from .ps2_card import Card
except ImportError:
    from ps2_card import Card

PARITY=[v.bit_count()&1 for v in range(256)]
COLUMN=[sum(PARITY[v&m]<<i for i,m in enumerate((0x55,0x33,0x0f,0,0xaa,0xcc,0xf0))) for v in range(256)]


def ecc128(block):
    if len(block)!=128:raise ValueError('ECC requires 128 bytes')
    column,low,high=0x77,0x7f,0x7f
    for i,v in enumerate(block):
        column^=COLUMN[v]
        if PARITY[v]:low^=~i;high^=i
    return bytes((column,low&127,high))


def page_ecc(page):
    if len(page)!=512:raise ValueError('ECC requires 512-byte page')
    return b''.join(ecc128(page[i:i+128]) for i in range(0,512,128))


def replace(data,path,replacement):
    card=Card(data);files=list(card.files())
    matches=[f for f in files if f[0].as_posix()==path]
    if len(matches)!=1:raise ValueError('Target file not found uniquely')
    _,old,first=matches[0]
    if len(old)!=len(replacement):raise ValueError('Replacement must have exactly the original length')
    out=bytearray(data);done=0
    for cluster in card.chain(first):
        for part in range(card.ppc):
            size=min(512,len(replacement)-done)
            if size<=0:break
            page=(cluster+card.alloc)*card.ppc+part;offset=page*card.stride
            before=data[offset:offset+512]
            after=replacement[done:done+size]+before[size:]
            if after!=before:
                if card.stride==528 and data[offset+512:offset+524]!=page_ecc(before):
                    raise ValueError(f'Original ECC invalid on changed page {page}')
                out[offset:offset+512]=after
                if card.stride==528:out[offset+512:offset+524]=page_ecc(after)
            done+=size
    if done!=len(replacement):raise ValueError('Short allocation chain')
    fresh={p.as_posix():b for p,b,_ in Card(bytes(out)).files()}
    expected={p.as_posix():(replacement if p.as_posix()==path else b) for p,b,_ in files}
    if fresh!=expected:raise ValueError('Post-write filesystem verification failed')
    return bytes(out)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('card',type=Path);p.add_argument('member');p.add_argument('replacement',type=Path);p.add_argument('output',type=Path)
    a=p.parse_args()
    try:
        result=replace(a.card.read_bytes(),a.member,a.replacement.read_bytes())
        with a.output.open('xb') as f:f.write(result)
        print(a.output)
    except (ValueError,OSError) as e:p.exit(1,f'Failed: {e}\n')
