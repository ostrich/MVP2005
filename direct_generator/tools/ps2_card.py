#!/usr/bin/env python3
"""Read-only PS2 memory card extraction. Layout: ps2dev/mymc ps2mc{,_dir}.py.

Never writes to the input card. Supports standard 512+16 and spare-free pages.
ECC is not validated yet; extraction is for format research, not card repair.
"""
import argparse
import hashlib
import json
import struct
from pathlib import Path


class Card:
    def __init__(self, data):
        self.raw = data
        if not data.startswith(b'Sony PS2 Memory Card Format '):
            raise ValueError('Not a PS2 memory card')
        sb = struct.unpack_from('<28s12sHHHHLLLLLL8x128s128sbbxx', data)
        self.page, self.ppc, self.total, self.alloc, self.end, self.root = sb[2], sb[3], sb[6], sb[7], sb[8], sb[9]
        if self.page != 512 or self.ppc != 2:
            raise ValueError('Unsupported card geometry')
        pages = self.total*self.ppc
        self.stride = len(data)//pages
        if len(data) != pages*self.stride or self.stride not in (512,528):
            raise ValueError('Unexpected card length')
        self.ifc = struct.unpack('<32I', sb[12])
        self.size = self.page*self.ppc

    def cluster(self, n):
        if not 0 <= n < self.total:
            raise ValueError(f'Cluster out of range: {n}')
        return b''.join(self.raw[(n*self.ppc+i)*self.stride:(n*self.ppc+i)*self.stride+self.page] for i in range(self.ppc))

    def next(self, n):
        epc = self.size//4
        fc, off = divmod(n, epc)
        indirect, index = divmod(fc, epc)
        fat = struct.unpack_from('<I', self.cluster(self.ifc[indirect]), index*4)[0]
        return struct.unpack_from('<I', self.cluster(fat), off*4)[0]

    def chain(self, n):
        seen = set()
        while n != 0x7fffffff:
            if not 0 <= n < self.end or n in seen:
                raise ValueError('Invalid or cyclic FAT chain')
            seen.add(n)
            yield n
            link = self.next(n)
            if not link & 0x80000000:
                raise ValueError('Unallocated FAT link')
            n = link & 0x7fffffff

    def read(self, n, length):
        data = b''.join(self.cluster(c+self.alloc) for c in self.chain(n))
        if len(data) < length:
            raise ValueError('Truncated file chain')
        return data[:length]

    def files(self):
        visited = set()
        def directory(cluster, count, prefix):
            if cluster in visited:
                raise ValueError('Directory cycle')
            visited.add(cluster)
            data = self.read(cluster, count*512)
            for offset in range(0,len(data),512):
                mode, _, length, _, first, _, _, _, name = struct.unpack_from('<HHL8sLL8sL28x448s',data,offset)
                name = name.split(b'\0')[0].decode('ascii')
                if not mode & 0x8000 or name in ('.','..'):
                    continue
                if not name or '/' in name or '\\' in name:
                    raise ValueError('Unsafe filename')
                path = prefix/name
                if mode & 0x20:
                    yield from directory(first,length,path)
                elif mode & 0x10:
                    yield path,self.read(first,length),first
        rootdata = self.cluster(self.root+self.alloc)
        count = struct.unpack_from('<I',rootdata,4)[0]
        yield from directory(self.root,count,Path())


def extract(source, target):
    card = Card(source.read_bytes())
    files = list(card.files())
    if target.exists():
        raise ValueError('Output already exists')
    target.mkdir(parents=True)
    manifest = {'source':str(source),'sha256':hashlib.sha256(card.raw).hexdigest(),
                'page_stride':card.stride,'ecc_validated':False,'files':[]}
    for path,data,cluster in files:
        out = target/path
        out.parent.mkdir(parents=True,exist_ok=True)
        out.write_bytes(data)
        manifest['files'].append({'path':str(path),'size':len(data),'first_cluster':cluster,'sha256':hashlib.sha256(data).hexdigest()})
    (target/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    return manifest

if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('card',type=Path)
    p.add_argument('output',type=Path)
    a=p.parse_args()
    for f in extract(a.card,a.output)['files']:
        print(f['size'],f['path'])
