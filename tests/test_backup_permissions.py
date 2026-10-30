"""Private backup creation; no live Firebase, databases, or host access.

POSIX permission checks are skipped on Windows rather than treating chmod bits
as evidence of Windows ACL protection. Portable backup behavior is tested too.
"""

import json
import os
import sqlite3
import stat
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import Mock, patch

import backup_neocare


class BackupPermissionTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory(prefix="neocare-private-backup-")))
        self.database = self.directory / "source.sqlite3"
        self.output = self.directory / "backups"
        self.firebase = Mock()
        self.firebase.get.return_value = {"children_profiles": {"child_01": {"name": "Synthetic Child"}}}
        with closing(sqlite3.connect(self.database)) as database:
            database.execute("CREATE TABLE sample(value TEXT)")
            database.execute("INSERT INTO sample VALUES('synthetic private value')")
            database.commit()

    def create(self, **options):
        return backup_neocare.create_backup(self.database, self.firebase, self.output, **options)

    def test_sqlite_destination_is_reserved_before_private_data_is_copied(self):
        original_copy = backup_neocare._copy_sqlite

        def check_reserved_destination(source, destination, **options):
            self.assertTrue(destination.is_file())
            self.assertEqual(destination.stat().st_size, 0)
            return original_copy(source, destination, **options)

        with patch.object(backup_neocare, "_copy_sqlite", side_effect=check_reserved_destination):
            folder = self.create()
        backup_neocare.verify_backup(folder)
        with closing(sqlite3.connect(folder / "neocare.sqlite3")) as snapshot:
            self.assertEqual(snapshot.execute("SELECT value FROM sample").fetchone()[0], "synthetic private value")

    def test_private_json_creation_refuses_to_overwrite_an_existing_file(self):
        path = self.directory / "existing.json"
        path.write_text('{"keep":"original"}', encoding="utf-8")
        with self.assertRaises(FileExistsError):
            backup_neocare._write_private_json(path, {"replace": "unwanted"})
        self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"keep": "original"})

    @unittest.skipUnless(os.name == "posix", "POSIX mode bits are not Windows ACLs")
    def test_new_backup_is_owner_only_even_with_permissive_process_umask(self):
        previous = os.umask(0)
        try:
            folder = self.create()
        finally:
            os.umask(previous)
        self.assertEqual(stat.S_IMODE(self.output.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(folder.stat().st_mode), 0o700)
        for filename in ("neocare.sqlite3", "firebase.json", "manifest.json"):
            with self.subTest(filename=filename):
                self.assertEqual(stat.S_IMODE((folder / filename).stat().st_mode), 0o600)

    @unittest.skipUnless(os.name == "posix", "POSIX mode bits are not Windows ACLs")
    def test_snapshot_is_private_before_sqlite_copy_and_remains_private_after_failure(self):
        self.output.mkdir(mode=0o755)
        self.output.chmod(0o755)

        def inspect_and_fail(_source, destination, **_options):
            self.assertEqual(stat.S_IMODE(destination.parent.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(destination.stat().st_mode), 0o600)
            raise sqlite3.OperationalError("Synthetic snapshot failure")

        previous = os.umask(0)
        try:
            with patch.object(backup_neocare, "_copy_sqlite", side_effect=inspect_and_fail):
                with self.assertRaisesRegex(sqlite3.OperationalError, "Synthetic snapshot failure"):
                    self.create()
        finally:
            os.umask(previous)
        folder = next(self.output.iterdir())
        self.assertEqual(stat.S_IMODE(folder.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE((folder / "neocare.sqlite3").stat().st_mode), 0o600)
        self.firebase.get.assert_not_called()

    @unittest.skipUnless(os.name == "posix", "POSIX mode bits are not Windows ACLs")
    def test_json_files_are_private_before_their_contents_are_written(self):
        original_dump = json.dump
        seen = []

        def inspect_dump(value, output, **options):
            self.assertEqual(stat.S_IMODE(os.fstat(output.fileno()).st_mode), 0o600)
            seen.append(value)
            return original_dump(value, output, **options)

        previous = os.umask(0)
        try:
            with patch.object(backup_neocare.json, "dump", side_effect=inspect_dump):
                folder = self.create()
        finally:
            os.umask(previous)
        self.assertEqual(len(seen), 2)
        backup_neocare.verify_backup(folder)
