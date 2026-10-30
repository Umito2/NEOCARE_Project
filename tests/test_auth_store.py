"""Storage tests using isolated databases; no application services are contacted."""

import hashlib
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import auth_store


class AuthStoreTests(unittest.TestCase):
    def setUp(self):
        temporary_directory = tempfile.TemporaryDirectory(prefix="neocare-auth-test-")
        self.addCleanup(temporary_directory.cleanup)
        self.database_path = Path(temporary_directory.name) / "nested" / "auth.sqlite3"
        database_patch = patch.object(auth_store, "DB_PATH", self.database_path)
        database_patch.start()
        self.addCleanup(database_patch.stop)
        auth_store.initialize()

    def create_parent(self, parent_id="parent-a", email="parent@example.test"):
        auth_store.create_parent(
            parent_id, "Test Parent", email, "+201000000000", "test-password-123"
        )

    def add_alert(self, parent_id="parent-a", child_id="child_01", pdf_data=None):
        return auth_store.add_alert(
            child_id=child_id,
            parent_id=parent_id,
            child_name="Test Child",
            severity="Warning",
            subject="Test alert",
            message="Synthetic test reading",
            email_status="pending",
            pdf_data=pdf_data,
        )

    def test_password_hashes_use_distinct_salts_and_verify_with_original_salt(self):
        password = "test-password-123"
        salt_a, digest_a = auth_store.hash_password(password)
        salt_b, digest_b = auth_store.hash_password(password)
        self.assertEqual(len(salt_a), 16)
        self.assertEqual(len(digest_a), 32)
        self.assertNotEqual(salt_a, salt_b)
        self.assertNotEqual(digest_a, digest_b)
        self.assertEqual(auth_store.hash_password(password, salt_a), (salt_a, digest_a))
        self.assertNotEqual(auth_store.hash_password("wrong-password", salt_a)[1], digest_a)

    def test_authentication_checks_password_and_returns_only_public_account_fields(self):
        self.create_parent()
        self.assertEqual(
            auth_store.authenticate_parent("PARENT@EXAMPLE.TEST", "test-password-123"),
            {
                "role": "parent",
                "user_id": "parent-a",
                "display_name": "Test Parent",
                "email": "parent@example.test",
            },
        )
        self.assertIsNone(auth_store.authenticate_parent("parent@example.test", "wrong"))
        self.assertIsNone(auth_store.authenticate_parent("missing@example.test", "wrong"))

    def test_duplicate_email_is_rejected_regardless_of_case(self):
        self.create_parent()
        with self.assertRaises(sqlite3.IntegrityError):
            self.create_parent(parent_id="parent-b", email="PARENT@EXAMPLE.TEST")
        self.assertIsNone(auth_store.parent_by_id("parent-b"))
        self.assertEqual(auth_store.parent_by_email("parent@example.test")["parent_id"], "parent-a")

    def test_parent_lookup_does_not_expose_credentials_or_interpret_sql(self):
        self.create_parent()
        expected = {
            "parent_id": "parent-a",
            "name": "Test Parent",
            "email": "parent@example.test",
            "phone": "+201000000000",
        }
        self.assertEqual(auth_store.parent_by_id("parent-a"), expected)
        self.assertEqual(auth_store.parent_by_email("PARENT@EXAMPLE.TEST"), expected)
        self.assertIsNone(auth_store.parent_by_id("' OR 1=1 --"))
        self.assertIsNone(auth_store.parent_by_email("' OR 1=1 --"))

    def test_session_tokens_are_hashed_at_rest_and_resolve_to_the_correct_user(self):
        with patch.object(auth_store.time, "time", return_value=1000):
            token = auth_store.create_session("parent", "parent-a", "Test Parent")
            session = auth_store.get_session(token)
        self.assertGreaterEqual(len(token), 40)
        self.assertEqual(
            session,
            {
                "role": "parent",
                "user_id": "parent-a",
                "display_name": "Test Parent",
                "expires_at": 1000 + auth_store.SESSION_SECONDS,
            },
        )
        with auth_store.connect() as database:
            stored = dict(database.execute("SELECT * FROM sessions").fetchone())
        self.assertEqual(stored["token_hash"], hashlib.sha256(token.encode("utf-8")).hexdigest())
        self.assertNotIn(token, stored.values())

    def test_session_expires_at_deadline_and_is_removed_from_storage(self):
        with patch.object(auth_store.time, "time", return_value=1000):
            token = auth_store.create_session("parent", "parent-a", "Test Parent")
        expires_at = 1000 + auth_store.SESSION_SECONDS
        with patch.object(auth_store.time, "time", return_value=expires_at - 1):
            self.assertIsNotNone(auth_store.get_session(token))
        with patch.object(auth_store.time, "time", return_value=expires_at):
            self.assertIsNone(auth_store.get_session(token))
        with auth_store.connect() as database:
            self.assertEqual(database.execute("SELECT COUNT(*) FROM sessions").fetchone()[0], 0)

    def test_creating_session_cleans_expired_sessions_but_keeps_active_sessions(self):
        with patch.object(auth_store.time, "time", return_value=1000):
            expired_token = auth_store.create_session("parent", "expired", "Old session")
        with patch.object(auth_store.time, "time", return_value=2000):
            active_token = auth_store.create_session("parent", "active", "Active session")
        with patch.object(auth_store.time, "time", return_value=1000 + auth_store.SESSION_SECONDS):
            new_token = auth_store.create_session("doctor", "clinic", "Clinic")
            self.assertIsNone(auth_store.get_session(expired_token))
            self.assertEqual(auth_store.get_session(active_token)["user_id"], "active")
            self.assertEqual(auth_store.get_session(new_token)["role"], "doctor")
        with auth_store.connect() as database:
            self.assertEqual(database.execute("SELECT COUNT(*) FROM sessions").fetchone()[0], 2)

    def test_logout_revokes_only_the_requested_session_and_is_idempotent(self):
        token_a = auth_store.create_session("parent", "parent-a", "Parent A")
        token_b = auth_store.create_session("parent", "parent-b", "Parent B")
        self.assertNotEqual(token_a, token_b)
        auth_store.delete_session(token_a)
        auth_store.delete_session(token_a)
        auth_store.delete_session(None)
        self.assertIsNone(auth_store.get_session(token_a))
        self.assertEqual(auth_store.get_session(token_b)["user_id"], "parent-b")

    def test_missing_or_forged_session_tokens_are_rejected(self):
        token = auth_store.create_session("parent", "parent-a", "Parent A")
        for candidate in (None, "", "unknown-token", "' OR 1=1 --", token + "x"):
            with self.subTest(candidate=candidate):
                self.assertIsNone(auth_store.get_session(candidate))

    def test_alert_lists_enforce_parent_ownership_order_and_limit_without_pdf_blobs(self):
        with patch.object(auth_store.time, "time", return_value=1000):
            first_id = self.add_alert(pdf_data=b"%PDF-test-only")
        with patch.object(auth_store.time, "time", return_value=2000):
            other_id = self.add_alert(parent_id="parent-b", child_id="child_02")
        with patch.object(auth_store.time, "time", return_value=3000):
            latest_id = self.add_alert()

        parent_alerts = auth_store.list_alerts("parent", "parent-a")
        self.assertEqual([alert["alert_id"] for alert in parent_alerts], [latest_id, first_id])
        self.assertEqual([alert["pdf_available"] for alert in parent_alerts], [0, 1])
        self.assertTrue(all("pdf_data" not in alert for alert in parent_alerts))
        self.assertEqual(
            [alert["alert_id"] for alert in auth_store.list_alerts("doctor", "clinic", limit=2)],
            [latest_id, other_id],
        )
        self.assertEqual(auth_store.list_alerts("parent", "unknown-parent"), [])

    def test_alert_pdf_downloads_are_scoped_to_parent_and_available_to_doctor(self):
        pdf_bytes = b"%PDF-1.7\nsynthetic test document\n%%EOF"
        alert_id = self.add_alert(pdf_data=pdf_bytes)
        expected = {"child_id": "child_01", "pdf_data": pdf_bytes}
        self.assertEqual(auth_store.get_alert_pdf(alert_id, "parent", "parent-a"), expected)
        self.assertEqual(auth_store.get_alert_pdf(alert_id, "doctor", "clinic"), expected)
        self.assertIsNone(auth_store.get_alert_pdf(alert_id, "parent", "parent-b"))
        self.assertIsNone(auth_store.get_alert_pdf(alert_id + 100, "doctor", "clinic"))
        no_pdf_alert_id = self.add_alert()
        self.assertEqual(
            auth_store.get_alert_pdf(no_pdf_alert_id, "parent", "parent-a"),
            {"child_id": "child_01", "pdf_data": None},
        )

    def test_email_status_update_changes_only_the_selected_alert(self):
        first_id = self.add_alert()
        second_id = self.add_alert()
        auth_store.update_alert_email_status(first_id, "sent")
        rows = {row["alert_id"]: row for row in auth_store.list_alerts("parent", "parent-a")}
        self.assertEqual(rows[first_id]["email_status"], "sent")
        self.assertEqual(rows[second_id]["email_status"], "pending")
        self.assertEqual(rows[first_id]["message"], "Synthetic test reading")

    def test_alert_severity_updates_are_persistent_and_isolated_per_child(self):
        self.assertEqual(auth_store.get_alert_severity("child_01"), 0)
        auth_store.save_alert_severity("child_01", 2)
        auth_store.save_alert_severity("child_02", 1)
        auth_store.save_alert_severity("child_01", 0)
        self.assertEqual(auth_store.get_alert_severity("child_01"), 0)
        self.assertEqual(auth_store.get_alert_severity("child_02"), 1)
        with auth_store.connect() as database:
            self.assertEqual(database.execute("SELECT COUNT(*) FROM alert_state").fetchone()[0], 2)

    def test_threshold_settings_round_trip_and_replace_previous_value(self):
        self.assertIsNone(auth_store.get_thresholds())
        original = {"spo2_min": 94.0, "temperature_warning_c": 37.5}
        replacement = {"spo2_min": 95.0, "temperature_warning_c": 38.0}
        auth_store.save_thresholds(original)
        self.assertEqual(auth_store.get_thresholds(), original)
        auth_store.save_thresholds(replacement)
        self.assertEqual(auth_store.get_thresholds(), replacement)
        with auth_store.connect() as database:
            count = database.execute(
                "SELECT COUNT(*) FROM settings WHERE key = 'alert_thresholds'"
            ).fetchone()[0]
        self.assertEqual(count, 1)

    def test_failed_transaction_rolls_back_partial_writes(self):
        with self.assertRaisesRegex(RuntimeError, "synthetic failure"):
            with auth_store.connect() as database:
                database.execute("INSERT INTO settings(key, value) VALUES (?, ?)", ("test", "value"))
                raise RuntimeError("synthetic failure")
        with auth_store.connect() as database:
            self.assertIsNone(database.execute("SELECT value FROM settings WHERE key = 'test'").fetchone())
            database.execute("INSERT INTO settings(key, value) VALUES (?, ?)", ("test", "recovered"))
        with auth_store.connect() as database:
            self.assertEqual(
                database.execute("SELECT value FROM settings WHERE key = 'test'").fetchone()[0],
                "recovered",
            )

    def test_reinitialization_preserves_existing_accounts_sessions_and_alerts(self):
        self.create_parent()
        token = auth_store.create_session("parent", "parent-a", "Test Parent")
        alert_id = self.add_alert(pdf_data=b"saved-pdf")
        auth_store.initialize()
        self.assertEqual(auth_store.parent_by_id("parent-a")["email"], "parent@example.test")
        self.assertEqual(auth_store.get_session(token)["user_id"], "parent-a")
        self.assertEqual(auth_store.get_alert_pdf(alert_id, "parent", "parent-a")["pdf_data"], b"saved-pdf")

    def test_initialization_migrates_legacy_alerts_without_losing_records(self):
        with auth_store.connect() as database:
            database.execute("DROP TABLE alerts")
            database.execute(
                "CREATE TABLE alerts ("
                "alert_id INTEGER PRIMARY KEY AUTOINCREMENT, child_id TEXT NOT NULL, "
                "parent_id TEXT NOT NULL, child_name TEXT NOT NULL, severity TEXT NOT NULL, "
                "subject TEXT NOT NULL, message TEXT NOT NULL, created_at INTEGER NOT NULL, "
                "email_status TEXT NOT NULL)"
            )
            database.execute(
                "INSERT INTO alerts(child_id, parent_id, child_name, severity, subject, "
                "message, created_at, email_status) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                ("child_01", "parent-a", "Test Child", "Warning", "Legacy", "Keep me", 1000, "sent"),
            )
        auth_store.initialize()
        alerts = auth_store.list_alerts("parent", "parent-a")
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["message"], "Keep me")
        self.assertEqual(alerts[0]["pdf_available"], 0)
        new_id = self.add_alert(pdf_data=b"new-pdf")
        self.assertEqual(auth_store.get_alert_pdf(new_id, "parent", "parent-a")["pdf_data"], b"new-pdf")


if __name__ == "__main__":
    unittest.main()
