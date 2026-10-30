"""Storage migrations and workflows against disposable SQLite databases only."""

import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import auth_store


class StorageFeaturesTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory(prefix="neocare-storage-")))
        self.path = self.directory / "test.sqlite3"
        self.enterContext(patch.object(auth_store, "DB_PATH", self.path))
        auth_store.initialize()
        self.start = datetime(2026, 10, 27, tzinfo=timezone.utc)

    def reading(self, minute=0, **changes):
        value = {"timestamp": (self.start + timedelta(minutes=minute)).isoformat(), "heart_rate_bpm": 100, "spo2_percent": 98, "temperature_c": 37, "respiratory_rate_br_min": 20, "activity_state": "Resting"}
        value.update(changes)
        return value

    def alert(self):
        return auth_store.add_alert("child_01", "parent-1", "Synthetic Child", "Warning", "Synthetic alert", "Synthetic message", "pending")

    def test_delete_journal_persists_writes_and_rolls_back_failed_transactions(self):
        with patch.dict(os.environ, {"NEOCARE_SQLITE_JOURNAL_MODE": "DELETE"}):
            alert_id = self.alert()
            with auth_store.connect() as db:
                self.assertEqual(db.execute("PRAGMA journal_mode").fetchone()[0], "delete")
                self.assertEqual(db.execute("PRAGMA foreign_keys").fetchone()[0], 1)
            with self.assertRaisesRegex(RuntimeError, "synthetic failure"):
                with auth_store.connect() as db:
                    db.execute("DELETE FROM alerts WHERE alert_id=?", (alert_id,))
                    raise RuntimeError("synthetic failure")
            self.assertIsNotNone(auth_store.get_alert(alert_id))
            self.assertFalse(Path(str(self.path) + "-wal").exists())

    def test_unsafe_journal_settings_fail_before_opening_database(self):
        untouched_path = self.directory / "untouched.sqlite3"
        for value in ("OFF", "MEMORY", "", "WAL; DROP TABLE parents"):
            with self.subTest(value=value), \
                 patch.object(auth_store, "DB_PATH", untouched_path), \
                 patch.dict(os.environ, {"NEOCARE_SQLITE_JOURNAL_MODE": value}):
                with self.assertRaisesRegex(ValueError, "WAL or DELETE"):
                    with auth_store.connect():
                        self.fail("Invalid journal mode opened a connection")
                self.assertFalse(untouched_path.exists())

    def test_initialize_is_idempotent_and_preserves_existing_accounts_and_alerts(self):
        auth_store.create_parent("parent-1", "Synthetic Parent", "parent@example.invalid", "0000000000", "synthetic-password")
        alert_id = self.alert()
        auth_store.initialize()
        self.assertEqual(auth_store.parent_by_id("parent-1")["name"], "Synthetic Parent")
        self.assertEqual(auth_store.get_alert(alert_id)["workflow_status"], "new")
        with auth_store.connect() as db:
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], auth_store.SCHEMA_VERSION)

    def test_legacy_migration_creates_verified_snapshot_and_preserves_records(self):
        legacy = self.directory / "legacy.sqlite3"
        with closing(sqlite3.connect(legacy)) as db:
            db.execute("CREATE TABLE alerts(alert_id INTEGER PRIMARY KEY,child_id TEXT,parent_id TEXT,child_name TEXT,severity TEXT,subject TEXT,message TEXT,created_at INTEGER,email_status TEXT)")
            db.execute("INSERT INTO alerts VALUES(1,'child_01','parent-1','Synthetic Child','Warning','Notice','Keep this record',1,'failed')")
            db.commit()
        with patch.object(auth_store, "DB_PATH", legacy):
            auth_store.initialize()
            self.assertEqual(auth_store.get_alert(1)["message"], "Keep this record")
            self.assertEqual(auth_store.get_alert(1)["notes"], [])
            auth_store.initialize()
        snapshot = next((self.directory / ".backups").glob(f"pre-*-schema-v{auth_store.SCHEMA_VERSION}.sqlite3"))
        self.assertTrue(snapshot.exists())
        with closing(sqlite3.connect(snapshot)) as db:
            self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(db.execute("SELECT message FROM alerts").fetchone()[0], "Keep this record")
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 0)
        self.assertEqual(len(list(snapshot.parent.glob("*.sqlite3"))), 1)

    def test_individual_clinicians_authenticate_without_exposing_password_hashes(self):
        created = auth_store.create_doctor("doctor-1", " Test.Clinic ", "Synthetic Clinician", "synthetic-password")
        self.assertEqual(created["username"], "test.clinic")
        self.assertTrue(created["is_active"])
        self.assertEqual(auth_store.authenticate_doctor("TEST.CLINIC", "synthetic-password"), {"role": "doctor", "user_id": "doctor-1", "display_name": "Synthetic Clinician"})
        self.assertIsNone(auth_store.authenticate_doctor("test.clinic", "incorrect"))
        self.assertIsNone(auth_store.authenticate_doctor("missing", "incorrect"))
        self.assertNotIn("password", json.dumps(auth_store.list_doctors()))

    def test_migration_snapshots_for_distinct_databases_cannot_collide(self):
        for name in ("first.sqlite3", "second.sqlite3"):
            path = self.directory / name
            with closing(sqlite3.connect(path)) as db:
                db.execute("CREATE TABLE marker(value TEXT)")
                db.execute("INSERT INTO marker VALUES(?)", (name,))
                db.commit()
            with patch.object(auth_store, "DB_PATH", path):
                auth_store.initialize()
        snapshots = list((self.directory / ".backups").glob("pre-*-schema-v*.sqlite3"))
        self.assertEqual(len(snapshots), 2)
        markers = []
        for snapshot in snapshots:
            with closing(sqlite3.connect(snapshot)) as db:
                markers.append(db.execute("SELECT value FROM marker").fetchone()[0])
        self.assertEqual(set(markers), {"first.sqlite3", "second.sqlite3"})

    def test_clinician_username_uniqueness_and_password_validation(self):
        auth_store.create_doctor("doctor-1", "clinic", "Synthetic Clinician", "synthetic-password")
        with self.assertRaises(sqlite3.IntegrityError):
            auth_store.create_doctor("doctor-2", "CLINIC", "Another Clinician", "different-password")
        with self.assertRaises(ValueError):
            auth_store.create_doctor("doctor-3", "other", "Another Clinician", "short")

    def test_inactive_clinician_cannot_authenticate(self):
        auth_store.create_doctor("doctor-1", "clinic", "Synthetic Clinician", "synthetic-password")
        with auth_store.connect() as db:
            db.execute("UPDATE doctors SET is_active=0 WHERE doctor_id='doctor-1'")
        self.assertIsNone(auth_store.authenticate_doctor("clinic", "synthetic-password"))

    def test_readings_are_durable_ordered_and_scoped_to_child_and_window(self):
        for minute in (20, 0, 10):
            auth_store.record_reading("child_01", self.reading(minute))
        auth_store.record_reading("child_02", self.reading(15, heart_rate_bpm=130))
        cutoff = (self.start + timedelta(minutes=5)).isoformat()
        values = auth_store.list_readings("child_01", cutoff)
        self.assertEqual([value["timestamp"] for value in values], [self.reading(10)["timestamp"], self.reading(20)["timestamp"]])
        self.assertEqual(auth_store.count_readings("child_01", cutoff), 2)
        auth_store.initialize()
        self.assertEqual(auth_store.list_readings("child_01", cutoff), values)
        self.assertEqual(auth_store.list_readings("child_03", cutoff), [])

    def test_duplicate_reading_is_idempotent_and_does_not_store_names_or_secrets(self):
        reading = self.reading(child_name="Private synthetic name", password="never persist")
        first = auth_store.record_reading("child_01", reading)
        second = auth_store.record_reading("child_01", {**reading, "heart_rate_bpm": 222})
        self.assertEqual(first, second)
        rows = auth_store.list_readings("child_01", self.start.isoformat())
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["heart_rate_bpm"], 100)
        self.assertNotIn("Private synthetic name", json.dumps(rows))
        self.assertNotIn("password", json.dumps(rows))

    def test_sampling_is_bounded_preserves_window_endpoints_and_vital_extrema(self):
        for minute in range(120):
            changes = {47: {"heart_rate_bpm": 220}, 48: {"spo2_percent": 80}, 49: {"temperature_c": 40}, 50: {"respiratory_rate_br_min": 70}}.get(minute, {})
            auth_store.record_reading("child_01", self.reading(minute, **changes))
        rows = auth_store.list_readings("child_01", self.start.isoformat(), limit=18)
        self.assertLessEqual(len(rows), 18)
        self.assertEqual(rows[0]["timestamp"], self.reading(0)["timestamp"])
        self.assertEqual(rows[-1]["timestamp"], self.reading(119)["timestamp"])
        self.assertEqual(max(row["heart_rate_bpm"] for row in rows), 220)
        self.assertEqual(min(row["spo2_percent"] for row in rows), 80)
        self.assertEqual(max(row["temperature_c"] for row in rows), 40)
        self.assertEqual(max(row["respiratory_rate_br_min"] for row in rows), 70)

    def test_historic_child_identifiers_remain_reserved(self):
        auth_store.record_reading("child_01", self.reading())
        self.assertEqual(auth_store.used_history_child_ids(), {"child_01"})
        self.assertEqual(auth_store.list_readings("child_02", self.start.isoformat()), [])

    def test_timestamps_require_timezone_and_negative_query_limits_are_bounded(self):
        with self.assertRaises(ValueError):
            auth_store.record_reading("child_01", self.reading(timestamp="2026-10-27T00:00:00"))
        for minute in range(3):
            auth_store.record_reading("child_01", self.reading(minute))
        self.assertEqual(len(auth_store.list_readings("child_01", self.start.isoformat(), limit=-1)), 1)

    def test_audit_retains_actor_action_target_but_excludes_sensitive_payloads(self):
        auth_store.record_audit("doctor", "doctor-1", "thresholds.update", "clinic", {"status": "success", "count": 2, "password": "secret", "heart_rate_bpm": 100, "note": "private", "fields": ["spo2_min", "not valid"]})
        event = auth_store.list_audit()[0]
        self.assertEqual(event["actor_id"], "doctor-1")
        self.assertEqual(event["action"], "thresholds.update")
        self.assertEqual(event["details"], {"status": "success", "count": 2, "fields": ["spo2_min"]})
        self.assertNotIn("secret", json.dumps(event))

    def test_alert_workflow_and_clinician_notes_preserve_author_and_time(self):
        auth_store.create_doctor("doctor-1", "clinic", "Synthetic Clinician", "synthetic-password")
        alert_id = self.alert()
        self.assertTrue(auth_store.update_alert_status(alert_id, "acknowledged", "doctor-1"))
        self.assertTrue(auth_store.add_alert_note(alert_id, "doctor-1", "  Synthetic follow-up note  "))
        alert = auth_store.get_alert(alert_id)
        self.assertEqual(alert["workflow_status"], "acknowledged")
        self.assertEqual(alert["status_updated_by"], "doctor-1")
        self.assertEqual(alert["notes"][0]["text"], "Synthetic follow-up note")
        self.assertEqual(alert["notes"][0]["author"], "Synthetic Clinician")
        self.assertTrue(auth_store.update_alert_status(alert_id, "resolved", "doctor-1"))
        self.assertEqual(auth_store.list_alerts("parent", "parent-1")[0]["notes"], [], "Internal clinician notes are not sent to parent clients")
        self.assertFalse(auth_store.update_alert_status(999, "resolved", "doctor-1"))
        self.assertFalse(auth_store.add_alert_note(999, "doctor-1", "Synthetic note"))

    def test_invalid_alert_status_and_blank_note_are_rejected(self):
        alert_id = self.alert()
        with self.assertRaises(ValueError):
            auth_store.update_alert_status(alert_id, "anything", "doctor-1")
        with self.assertRaises(ValueError):
            auth_store.add_alert_note(alert_id, "doctor-1", " ")

    def test_outbox_claims_are_exclusive_and_failed_delivery_retries_with_backoff(self):
        alert_id = self.alert()
        with patch.object(auth_store.time, "time", return_value=1000):
            auth_store.enqueue_alert_email(alert_id, "parent@example.invalid", "Synthetic subject", "Synthetic message", b"test-pdf")
            self.assertEqual(len(auth_store.pending_alert_emails()), 1)
            self.assertEqual(auth_store.pending_alert_emails(), [])
            auth_store.complete_alert_email(alert_id, "failed", error="private SMTP detail")
            self.assertEqual(len(auth_store.pending_alert_emails()), 1, "First failure is eligible for one immediate retry")
            auth_store.complete_alert_email(alert_id, "failed", error="private SMTP detail")
            self.assertEqual(auth_store.pending_alert_emails(), [])
            alert = auth_store.get_alert(alert_id)
            self.assertEqual(alert["delivery_attempts"], 2)
            self.assertEqual(alert["next_retry_at"], 1060)
            self.assertNotIn("private SMTP detail", json.dumps({key: value for key, value in alert.items() if key != "pdf_data"}))
        with patch.object(auth_store.time, "time", return_value=1060):
            self.assertEqual(len(auth_store.pending_alert_emails()), 1)
            auth_store.complete_alert_email(alert_id, "sent")
            self.assertEqual(auth_store.pending_alert_emails(), [])
            self.assertEqual(auth_store.get_alert(alert_id)["email_status"], "sent")

    def test_unconfigured_smtp_does_not_consume_delivery_attempts(self):
        alert_id = self.alert()
        with patch.object(auth_store.time, "time", return_value=1000):
            auth_store.enqueue_alert_email(alert_id, "parent@example.invalid", "Synthetic subject", "Synthetic message")
            for _ in range(20):
                auth_store.complete_alert_email(alert_id, "not_configured")
            self.assertEqual(auth_store.get_alert(alert_id)["delivery_attempts"], 0)
            self.assertEqual(auth_store.pending_alert_emails(), [])
        with patch.object(auth_store.time, "time", return_value=1060):
            self.assertEqual(len(auth_store.pending_alert_emails()), 1)
            auth_store.complete_alert_email(alert_id, "sent")
            self.assertEqual(auth_store.get_alert(alert_id)["delivery_attempts"], 1)

    def test_outbox_retry_budget_stops_repeated_failures(self):
        alert_id = self.alert()
        auth_store.enqueue_alert_email(alert_id, "parent@example.invalid", "Subject", "Message")
        for _ in range(auth_store.MAX_EMAIL_ATTEMPTS):
            auth_store.complete_alert_email(alert_id, "failed")
        with patch.object(auth_store.time, "time", return_value=9999999999):
            self.assertEqual(auth_store.pending_alert_emails(), [])
        self.assertEqual(auth_store.get_alert(alert_id)["next_retry_at"], None)

    def test_expired_outbox_lease_can_be_recovered_after_worker_failure(self):
        alert_id = self.alert()
        with patch.object(auth_store.time, "time", return_value=1000):
            auth_store.enqueue_alert_email(alert_id, "parent@example.invalid", "Subject", "Message")
            self.assertEqual(len(auth_store.pending_alert_emails()), 1)
        with patch.object(auth_store.time, "time", return_value=1121):
            self.assertEqual(len(auth_store.pending_alert_emails()), 1)

    def test_alert_deletion_cascades_notes_and_outbox_only(self):
        removed, retained = self.alert(), self.alert()
        auth_store.add_alert_note(removed, "doctor-1", "Synthetic note")
        auth_store.enqueue_alert_email(removed, "parent@example.invalid", "Subject", "Message")
        auth_store.record_audit("doctor", "doctor-1", "alert.delete", str(removed))
        self.assertTrue(auth_store.delete_alert(removed))
        self.assertIsNone(auth_store.get_alert(removed))
        self.assertIsNotNone(auth_store.get_alert(retained))
        self.assertEqual(auth_store.pending_alert_emails(), [])
        self.assertEqual(len(auth_store.list_audit()), 1)

    def test_atomic_episode_creation_prevents_duplicate_alerts_across_workers(self):
        def create(_):
            return auth_store.record_alert_episode("child_01", "parent-1", "Synthetic Child", "Critical", 2, "Synthetic alert", "Synthetic message", "parent@example.invalid")
        with ThreadPoolExecutor(max_workers=4) as workers:
            results = list(workers.map(create, range(8)))
        self.assertEqual(sum(result["alert_id"] is not None for result in results), 1)
        self.assertEqual(len(auth_store.list_alerts("doctor", "clinic")), 1)
        self.assertEqual(len(auth_store.pending_alert_emails()), 1)
        self.assertEqual(auth_store.get_alert_severity("child_01"), 2)
        reset = auth_store.record_alert_episode("child_01", "parent-1", "Synthetic Child", "Normal", 0, "", "")
        self.assertEqual(reset["notification_status"], "recovered")
        self.assertIsNotNone(create(None)["alert_id"])

    def test_worker_can_exclude_already_attempted_alerts_from_same_batch(self):
        first, second = self.alert(), self.alert()
        auth_store.enqueue_alert_email(first, "parent@example.invalid", "First", "Message")
        auth_store.enqueue_alert_email(second, "parent@example.invalid", "Second", "Message")
        self.assertEqual(auth_store.pending_alert_emails(limit=1)[0]["alert_id"], first)
        auth_store.complete_alert_email(first, "failed")
        self.assertEqual(auth_store.pending_alert_emails(limit=1, exclude_alert_ids={first})[0]["alert_id"], second)
