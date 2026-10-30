"""Backup/restore tests use disposable databases and an in-memory Firebase reference."""

import copy
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import backup_neocare
import auth_store


class FakeFirebase:
    def __init__(self, value):
        self.value = copy.deepcopy(value)
        self.set_calls = 0

    def get(self):
        return copy.deepcopy(self.value)

    def set(self, value):
        if value is None:
            raise ValueError("Value must not be None")
        self.set_calls += 1
        self.value = copy.deepcopy(value)

    def delete(self):
        self.set_calls += 1
        self.value = None


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory(prefix="neocare-backup-")))
        self.database = self.directory / "test.sqlite3"
        self.backups = self.directory / ".backups"
        self.firebase = FakeFirebase({"children_profiles": {"child_01": {"name": "Synthetic Child"}}, "live_monitoring": {"child_01": {"heart_rate_bpm": 100}}})
        with closing(sqlite3.connect(self.database)) as db:
            db.execute("CREATE TABLE sample(value TEXT)")
            db.execute("INSERT INTO sample VALUES('original')")
            db.commit()
        self.url = "https://synthetic.example.invalid/"

    def create(self):
        return backup_neocare.create_backup(self.database, self.firebase, self.backups, firebase_url=self.url)

    def value(self):
        with closing(sqlite3.connect(self.database)) as db:
            return db.execute("SELECT value FROM sample").fetchone()[0]

    def change(self):
        with closing(sqlite3.connect(self.database)) as db:
            db.execute("UPDATE sample SET value='changed'")
            db.commit()
        self.firebase.value = {"children_profiles": {"child_02": {"name": "Another Synthetic Child"}}}

    def test_snapshot_contains_verified_sqlite_and_firebase_without_modifying_either(self):
        folder = self.create()
        manifest = backup_neocare.verify_backup(folder)
        self.assertEqual(manifest["firebase_subtree"], "neocare_system")
        self.assertEqual(set(manifest["files"]), {"sqlite", "firebase"})
        self.assertEqual(self.value(), "original")
        self.assertEqual(self.firebase.set_calls, 0)
        self.assertEqual(json.loads((folder / "firebase.json").read_text()), self.firebase.value)

    def test_sqlite_backup_includes_committed_wal_data(self):
        with closing(sqlite3.connect(self.database)) as live:
            live.execute("PRAGMA journal_mode=WAL")
            live.execute("UPDATE sample SET value='wal-value'")
            live.commit()
            folder = self.create()
            with closing(sqlite3.connect(folder / "neocare.sqlite3")) as snapshot:
                self.assertEqual(snapshot.execute("SELECT value FROM sample").fetchone()[0], "wal-value")

    def test_tampered_firebase_snapshot_is_rejected(self):
        folder = self.create()
        (folder / "firebase.json").write_text('{}')
        with self.assertRaisesRegex(ValueError, "checksum"):
            backup_neocare.verify_backup(folder)

    def test_manifest_cannot_redirect_to_files_outside_backup(self):
        folder = self.create()
        path = folder / "manifest.json"
        manifest = json.loads(path.read_text())
        manifest["files"]["sqlite"]["name"] = "../test.sqlite3"
        path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, "filename"):
            backup_neocare.verify_backup(folder)

    def test_restore_requires_both_explicit_confirmations(self):
        folder = self.create()
        for confirmed, maintenance in ((False, False), (True, False), (False, True)):
            with self.subTest(confirmed=confirmed, maintenance=maintenance):
                with self.assertRaises(ValueError):
                    backup_neocare.restore_backup(folder, self.database, self.firebase, self.backups, firebase_url=self.url, confirmed=confirmed, maintenance_confirmed=maintenance)
        self.assertEqual(self.firebase.set_calls, 0)

    def test_restore_rejects_wrong_firebase_target_before_writes(self):
        folder = self.create()
        with self.assertRaisesRegex(ValueError, "different Firebase"):
            backup_neocare.restore_backup(folder, self.database, self.firebase, self.backups, firebase_url="https://other.example.invalid", confirmed=True, maintenance_confirmed=True)
        self.assertEqual(self.firebase.set_calls, 0)

    def test_explicit_restore_restores_both_stores_and_saves_previous_state(self):
        folder = self.create()
        original_firebase = copy.deepcopy(self.firebase.value)
        self.change()
        changed_firebase = copy.deepcopy(self.firebase.value)
        safety = backup_neocare.restore_backup(folder, self.database, self.firebase, self.backups, firebase_url=self.url, confirmed=True, maintenance_confirmed=True)
        self.assertEqual(self.value(), "original")
        self.assertEqual(self.firebase.value, original_firebase)
        self.assertEqual(backup_neocare.verify_backup(safety)["kind"], "pre-restore")
        self.assertEqual(json.loads((safety / "firebase.json").read_text()), changed_firebase)
        with closing(sqlite3.connect(safety / "neocare.sqlite3")) as previous:
            self.assertEqual(previous.execute("SELECT value FROM sample").fetchone()[0], "changed")

    def test_sqlite_restore_failure_rolls_back_both_stores(self):
        folder = self.create()
        self.change()
        expected_firebase = copy.deepcopy(self.firebase.value)
        real_restore = backup_neocare._restore_sqlite
        calls = 0

        def fail_once(source, destination):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise sqlite3.OperationalError("synthetic restore failure")
            return real_restore(source, destination)

        with patch.object(backup_neocare, "_restore_sqlite", side_effect=fail_once):
            with self.assertRaisesRegex(RuntimeError, "both stores were rolled back"):
                backup_neocare.restore_backup(folder, self.database, self.firebase, self.backups, firebase_url=self.url, confirmed=True, maintenance_confirmed=True)
        self.assertEqual(self.value(), "changed")
        self.assertEqual(self.firebase.value, expected_firebase)

    def test_restore_does_not_overwrite_its_source_snapshot(self):
        folder = self.create()
        with self.assertRaisesRegex(ValueError, "source backup"):
            backup_neocare.restore_backup(folder, folder / "neocare.sqlite3", self.firebase, self.backups, firebase_url=self.url, confirmed=True, maintenance_confirmed=True)
        self.assertEqual(self.firebase.set_calls, 0)

    def test_empty_firebase_snapshot_restores_with_delete_not_set_none(self):
        self.firebase.value = None
        folder = self.create()
        self.change()
        backup_neocare.restore_backup(folder, self.database, self.firebase, self.backups, firebase_url=self.url, confirmed=True, maintenance_confirmed=True)
        self.assertIsNone(self.firebase.value)
        self.assertEqual(self.value(), "original")

    def test_successful_restore_does_not_resurrect_revoked_sessions(self):
        with patch.object(auth_store, "DB_PATH", self.database):
            auth_store.initialize()
            token = auth_store.create_session("doctor", "doctor-1", "Synthetic Clinician")
            folder = self.create()
            auth_store.delete_session(token)
            backup_neocare.restore_backup(folder, self.database, self.firebase, self.backups, firebase_url=self.url, confirmed=True, maintenance_confirmed=True)
            self.assertIsNone(auth_store.get_session(token))

    def test_verify_command_needs_no_firebase_connection(self):
        folder = self.create()
        with patch("builtins.print") as output:
            self.assertEqual(backup_neocare.main(["verify", str(folder)]), 0)
        self.assertEqual(json.loads(output.call_args.args[0])["status"], "verified")
