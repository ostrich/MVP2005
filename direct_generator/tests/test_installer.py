import json
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import install_roster as installer
from mvp_rosters import digest


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.db, self.package, self.backup = root/'database', root/'package', root/'backup'
        self.db.mkdir()
        (self.package/'database').mkdir(parents=True)
        for name in installer.FILES | {'team.dat', 'org.dat', 'untouched.dat'}:
            (self.db/name).write_bytes(('original '+name).encode())
            (self.db/name).chmod(0o444)
        for name in installer.FILES:
            (self.package/'database'/name).write_bytes(('converted '+name).encode())
        self.original = {p.name: digest(p) for p in self.db.iterdir()}
        self.report = {'baseline_sha256': self.original,
                       'output_sha256': {n: digest(self.package/'database'/n) for n in installer.FILES}}
        (self.package/'report.json').write_text(json.dumps(self.report))

    def check_original(self):
        self.assertEqual({p.name: digest(p) for p in self.db.iterdir()}, self.original)
        self.assertTrue(all(stat.S_IMODE(p.stat().st_mode) == 0o444 for p in self.db.iterdir()))

    def test_dry_run_apply_restore_readonly_files(self):
        installer.install(self.package, self.db, self.backup)
        self.assertFalse(self.backup.exists())
        self.check_original()
        installer.install(self.package, self.db, self.backup, apply=True)
        for n, expected in self.report['output_sha256'].items():
            self.assertEqual(digest(self.db/n), expected)
        self.assertEqual(digest(self.db/'untouched.dat'), self.original['untouched.dat'])
        installer.restore(self.db, self.backup)
        installer.restore(self.db, self.backup, apply=True)
        self.check_original()

    def test_tampered_package_refused_before_backup(self):
        (self.package/'database'/'attrib.dat').write_bytes(b'bad')
        with self.assertRaisesRegex(ValueError, 'Package checksum'):
            installer.install(self.package, self.db, self.backup, apply=True)
        self.assertFalse(self.backup.exists())
        self.check_original()

    def test_write_failure_rolls_back_completed_files(self):
        real = installer.replace_file
        calls = 0
        def fail_once(source, target):
            nonlocal calls
            calls += 1
            if calls == 4:
                raise OSError('injected replacement failure')
            real(source, target)
        with patch.object(installer, 'replace_file', side_effect=fail_once):
            with self.assertRaisesRegex(OSError, 'injected'):
                installer.install(self.package, self.db, self.backup, apply=True)
        self.check_original()

    def test_interrupted_restore_can_be_retried(self):
        installer.install(self.package, self.db, self.backup, apply=True)
        real = installer.replace_file
        calls = 0
        def fail_once(source, target):
            nonlocal calls
            calls += 1
            if calls == 4:
                raise OSError('injected restore failure')
            real(source, target)
        with patch.object(installer, 'replace_file', side_effect=fail_once):
            with self.assertRaisesRegex(OSError, 'injected restore'):
                installer.restore(self.db, self.backup, apply=True)
        installer.restore(self.db, self.backup, apply=True)
        self.check_original()
        with patch.object(installer, 'replace_file') as replace:
            installer.restore(self.db, self.backup, apply=True)
            replace.assert_not_called()

    def test_failed_replace_preserves_readonly_target_and_cleans_temp(self):
        target = self.db/'attrib.dat'
        with patch.object(installer.os, 'replace', side_effect=OSError('replace failed')):
            with self.assertRaisesRegex(OSError, 'replace failed'):
                installer.replace_file(self.package/'database/attrib.dat', target)
        self.check_original()
        self.assertEqual(list(self.db.glob('.mvp-roster-*')), [])

    def test_corrupt_backup_refused_before_any_restore(self):
        installer.install(self.package, self.db, self.backup, apply=True)
        path = self.backup/'attrib.dat'
        path.chmod(0o644)
        path.write_bytes(b'corrupt backup')
        with patch.object(installer, 'replace_file') as replace:
            with self.assertRaisesRegex(ValueError, 'Backup checksum'):
                installer.restore(self.db, self.backup, apply=True)
            replace.assert_not_called()

    def test_changed_installation_is_not_overwritten_on_restore(self):
        installer.install(self.package, self.db, self.backup, apply=True)
        changed = self.db/'attrib.dat'
        changed.chmod(0o644)
        changed.write_bytes(b'new unrelated change')
        with self.assertRaisesRegex(ValueError, 'changed since installation'):
            installer.restore(self.db, self.backup, apply=True)
        self.assertEqual(changed.read_bytes(), b'new unrelated change')


if __name__ == '__main__':
    unittest.main()
