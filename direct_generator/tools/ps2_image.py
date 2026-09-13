"""Read the MVP database from a plain 2048-byte-sector ISO, without mounting it.

ISO directory layout: ECMA-119 sections 8.4 and 9.1.
https://ecma-international.org/publications-and-standards/standards/ecma-119/
Only contiguous, non-interleaved files in the primary volume are supported.
"""
from contextlib import contextmanager
from pathlib import Path
import tempfile

from .ea_big import extract

SECTOR = 2048
DATABASE = ('DATA', 'DATABASE', 'DATABASE.BIG')


def both(data, offset, width):
    little = int.from_bytes(data[offset:offset+width], 'little')
    big = int.from_bytes(data[offset+width:offset+2*width], 'big')
    if little != big:
        raise ValueError('ISO byte-order copies disagree')
    return little


def database_archive(image):
    """Return only DATABASE.BIG; do not read the whole DVD into memory."""
    with Path(image).open('rb') as stream:
        size = stream.seek(0, 2)
        def read(offset, length):
            if offset < 0 or length < 0 or offset + length > size:
                raise ValueError('ISO extent exceeds image size')
            stream.seek(offset)
            data = stream.read(length)
            if len(data) != length:
                raise ValueError('Truncated ISO image')
            return data

        primary = None
        for sector in range(16, min(size // SECTOR, 256)):
            descriptor = read(sector * SECTOR, SECTOR)
            if descriptor[1:7] != b'CD001\x01':
                raise ValueError('Expected a plain ISO image with 2048-byte sectors')
            if descriptor[0] == 1:
                primary = descriptor
                break
            if descriptor[0] == 255:
                break
        if primary is None:
            raise ValueError('ISO primary volume not found; supply an uncompressed .iso')
        if both(primary, 128, 2) != SECTOR:
            raise ValueError('Unsupported ISO logical block size')
        volume_size = both(primary, 80, 4) * SECTOR
        if volume_size > size:
            raise ValueError('Truncated ISO volume')

        def record(raw):
            if len(raw) < 34 or raw[0] != len(raw) or 33 + raw[32] > len(raw):
                raise ValueError('Invalid ISO directory record')
            offset = both(raw, 2, 4) * SECTOR
            length = both(raw, 10, 4)
            if offset + length > volume_size:
                raise ValueError('ISO record exceeds volume')
            return raw, offset, length

        current = record(primary[156:156+primary[156]])
        for component in DATABASE:
            raw, offset, length = current
            if not raw[25] & 2:
                raise ValueError('Expected ISO directory')
            if raw[1] or raw[25] & 128 or raw[26] or raw[27]:
                raise ValueError('Unsupported ISO extended/interleaved/multi-extent record')
            if length > 16 * 1024 * 1024:
                raise ValueError('ISO directory is too large')
            directory = read(offset, length)
            matches = []
            at = 0
            while at < len(directory):
                count = directory[at]
                if count == 0:
                    at = (at // SECTOR + 1) * SECTOR
                    continue
                if at + count > len(directory) or at % SECTOR + count > SECTOR:
                    raise ValueError('ISO directory record crosses a boundary')
                entry = record(directory[at:at+count])
                name = entry[0][33:33+entry[0][32]]
                if name.split(b';')[0].upper() == component.encode('ascii'):
                    matches.append(entry)
                at += count
            if len(matches) != 1:
                raise ValueError('ISO must contain exactly one DATA/DATABASE/DATABASE.BIG')
            current = matches[0]
        raw, offset, length = current
        if raw[1] or raw[25] & (2 | 128) or raw[26] or raw[27]:
            raise ValueError('Unsupported ISO database file layout')
        if length > 128 * 1024 * 1024:
            raise ValueError('DATABASE.BIG exceeds supported size')
        return read(offset, length)


@contextmanager
def database_input(baseline=None, image=None):
    """Resolve existing DATs or extract an ISO into an automatically cleaned directory."""
    if (baseline is None) == (image is None):
        raise ValueError('Supply exactly one PS2 database directory or image')
    if baseline is not None:
        yield Path(baseline)
        return
    with tempfile.TemporaryDirectory(prefix='mvp-ps2-database-') as temp:
        root = Path(temp)
        archive = root / 'DATABASE.BIG'
        archive.write_bytes(database_archive(image))
        database = root / 'database'
        extract(archive, database)
        yield database
