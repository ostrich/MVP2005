#!/usr/bin/env python3
"""Install a generated DAT package with checksum checks and a complete backup.

Without --apply this only checks and prints the proposed installation.
Close the game before applying. Never install into a running game.
"""
import argparse
import json
import os
import shutil
import stat
import tempfile
from pathlib import Path

from mvp_rosters import ALL_PLAYER_TABLES, PITCHER_TABLES, digest

FILES = {n+'.dat' for n in ALL_PLAYER_TABLES+PITCHER_TABLES+('roster', 'hist')}


def replace_file(source, target):
    """Replace a possibly read-only owned file without changing its permissions."""
    mode = stat.S_IMODE(target.stat().st_mode)
    fd, name = tempfile.mkstemp(prefix='.mvp-roster-', dir=target.parent)
    writable_target = False
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(source.read_bytes())
            f.flush()
            os.fsync(f.fileno())
        os.chmod(name, mode)
        if os.name == 'nt' and not mode & stat.S_IWRITE:
            os.chmod(target, mode | stat.S_IWRITE)
            writable_target = True
        os.replace(name, target)
    finally:
        try:
            if writable_target:
                os.chmod(target, mode)
        finally:
            if os.path.exists(name):
                os.chmod(name, stat.S_IREAD | stat.S_IWRITE)
                os.unlink(name)


def install(package, database, backup, apply=False):
    report = json.loads((package/'report.json').read_text())
    expected = report['output_sha256']
    if set(expected) != FILES:
        raise ValueError('Package contains an unexpected file set')
    for name in sorted(FILES):
        src, dst = package/'database'/name, database/name
        if src.is_symlink() or dst.is_symlink():
            raise ValueError(f'Refusing symlink: {name}')
        if digest(src) != expected[name]:
            raise ValueError(f'Package checksum mismatch: {name}')
        if digest(dst) != report['baseline_sha256'][name]:
            raise ValueError(f'Installed baseline differs: {name}; regenerate against the intended baseline')
    for name in ('team.dat', 'org.dat'):
        if digest(database/name) != report['baseline_sha256'][name]:
            raise ValueError(f'Installed team structure differs: {name}')
    if backup.exists():
        raise ValueError(f'Backup path already exists: {backup}')
    if backup.resolve().is_relative_to(database.resolve()):
        raise ValueError('Backup must be outside the database directory')
    if not apply:
        return f'Checks passed: would replace {len(FILES)} DAT files; backup: {backup}'
    shutil.copytree(database, backup)
    receipt = {'installed_sha256': expected,
               'original_sha256': {name: digest(backup/name) for name in sorted(FILES)}}
    (backup/'installation.json').write_text(json.dumps(receipt, indent=2)+'\n')
    completed = []
    try:
        for name in sorted(FILES):
            replace_file(package/'database'/name, database/name)
            completed.append(name)
        for name in FILES:
            if digest(database/name) != expected[name]:
                raise ValueError(f'Post-install checksum mismatch: {name}')
    except Exception:
        for name in completed:
            replace_file(backup/name, database/name)
        raise
    return f'Installed {len(FILES)} files. Original database backed up at {backup}'


def restore(database, backup, apply=False):
    receipt = json.loads((backup/'installation.json').read_text())
    if set(receipt['installed_sha256']) != FILES or set(receipt['original_sha256']) != FILES:
        raise ValueError('Invalid installation receipt')
    pending = []
    for name in sorted(FILES):
        if (database/name).is_symlink() or (backup/name).is_symlink():
            raise ValueError(f'Refusing symlink: {name}')
        current = digest(database/name)
        if current not in (receipt['installed_sha256'][name], receipt['original_sha256'][name]):
            raise ValueError(f'Installed file has changed since installation: {name}')
        if digest(backup/name) != receipt['original_sha256'][name]:
            raise ValueError(f'Backup checksum mismatch: {name}')
        if current != receipt['original_sha256'][name]:
            pending.append(name)
    if apply:
        # All originals are verified before the first replacement. A partial
        # restore after an OS/I/O failure can be completed from this backup.
        for name in pending:
            replace_file(backup/name, database/name)
        for name in FILES:
            if digest(database/name) != receipt['original_sha256'][name]:
                raise ValueError(f'Post-restore checksum mismatch: {name}')
    return 'Original DAT files restored.' if apply else 'Restore checks passed; use --apply to restore.'


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--package', type=Path)
    p.add_argument('--game-dir', type=Path, required=True)
    p.add_argument('--backup', type=Path, required=True)
    p.add_argument('--apply', action='store_true')
    p.add_argument('--restore', action='store_true')
    args = p.parse_args()
    if not args.restore and args.package is None:
        p.error('--package is required for installation')
    try:
        db = args.game_dir/'data'/'database'
        print(restore(db, args.backup, args.apply) if args.restore else
              install(args.package, db, args.backup, args.apply))
    except (OSError, ValueError, KeyError) as e:
        p.exit(1, f'Install/restore failed: {e}\n')


if __name__ == '__main__':
    main()
