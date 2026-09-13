import os
from pathlib import Path
import struct
import tempfile
import unittest

from tools.ps2_image import SECTOR, database_archive, database_input


def both(n, width):
    return n.to_bytes(width, 'little') + n.to_bytes(width, 'big')


def entry(name, block, length, flags=0):
    raw = bytearray(33 + len(name) + (len(name) % 2 == 0))
    raw[0] = len(raw)
    raw[2:10] = both(block, 4)
    raw[10:18] = both(length, 4)
    raw[25] = flags
    raw[28:32] = both(1, 2)
    raw[32] = len(name)
    raw[33:33+len(name)] = name
    return raw


def fixture():
    content = b'database fixture'
    header = 16 + 8 + len(b'attrib.dat\0')
    archive = (b'BIGF' + struct.pack('<I', header+len(content)) +
               struct.pack('>II', 1, header) + struct.pack('>II', header, len(content)) +
               b'attrib.dat\0' + content)
    image = bytearray(24 * SECTOR)
    pvd = 16 * SECTOR
    image[pvd:pvd+7] = b'\x01CD001\x01'
    image[pvd+80:pvd+88] = both(24, 4)
    image[pvd+128:pvd+132] = both(SECTOR, 2)
    root = entry(b'\0', 20, SECTOR, 2)
    image[pvd+156:pvd+156+len(root)] = root
    for block, raw in [(20, entry(b'DATA',21,SECTOR,2)),
                       (21, entry(b'DATABASE',22,SECTOR,2)),
                       (22, entry(b'DATABASE.BIG;1',23,len(archive)))]:
        image[block*SECTOR:block*SECTOR+len(raw)] = raw
    image[23*SECTOR:23*SECTOR+len(archive)] = archive
    return image, archive, content


class ImageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)/'game.iso'
        self.image, self.archive, self.content = fixture()
        self.path.write_bytes(self.image)

    def test_extract_and_cleanup(self):
        self.assertEqual(database_archive(self.path), self.archive)
        with database_input(image=self.path) as db:
            self.assertEqual((db/'attrib.dat').read_bytes(), self.content)
        self.assertFalse(db.exists())
        self.assertEqual(self.path.read_bytes(), self.image)

    def test_cleanup_on_conversion_failure(self):
        with self.assertRaisesRegex(ValueError, 'conversion failed'):
            with database_input(image=self.path) as db:
                raise ValueError('conversion failed')
        self.assertFalse(db.exists())

    def test_existing_database_and_mutually_exclusive_inputs(self):
        with database_input(baseline=self.path.parent) as db:
            self.assertEqual(db, self.path.parent)
        for args in ({}, {'baseline': self.path.parent, 'image': self.path}):
            with self.assertRaises(ValueError):
                with database_input(**args):
                    self.fail('should reject inputs')

    def test_bad_image_missing_file_and_bounds(self):
        for offset, replacement in [(16*SECTOR+1,b'XXXXX'),
                                    (22*SECTOR+33,b'X'),
                                    (22*SECTOR+2,both(99,4)),
                                    (22*SECTOR+25,b'\x80')]:
            with self.subTest(offset=offset):
                image = self.image.copy()
                image[offset:offset+len(replacement)] = replacement
                self.path.write_bytes(image)
                with self.assertRaises(ValueError):
                    database_archive(self.path)
        self.path.write_bytes(self.image[:23*SECTOR])
        with self.assertRaises(ValueError):
            database_archive(self.path)

    def test_duplicate_file_rejected(self):
        raw = entry(b'DATABASE.BIG;1',23,len(self.archive))
        image = self.image.copy()
        at = 22*SECTOR + len(raw)
        image[at:at+len(raw)] = raw
        self.path.write_bytes(image)
        with self.assertRaisesRegex(ValueError,'exactly one'):
            database_archive(self.path)


@unittest.skipUnless(os.environ.get('MVP2005_PS2_IMAGE') and
                     os.environ.get('MVP2005_PS2_DATABASE'), 'Local ISO and DAT fixtures required')
class RealImageTests(unittest.TestCase):
    def test_disc_database_matches_extracted_fixture(self):
        expected = Path(os.environ['MVP2005_PS2_DATABASE'])
        with database_input(image=Path(os.environ['MVP2005_PS2_IMAGE'])) as db:
            actual = {p.name:p.read_bytes() for p in db.iterdir()}
            wanted = {p.name:p.read_bytes() for p in expected.iterdir() if p.is_file()}
            self.assertEqual(actual, wanted)
