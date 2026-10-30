"""Validate cloud boundaries using invented credentials and temporary files only."""

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import cloud_start


class CloudLauncherTests(unittest.TestCase):
    def setUp(self):
        self.folder = Path(self.enterContext(tempfile.TemporaryDirectory(prefix="neocare-cloud-test-")))
        self.volume = self.folder / "data"
        self.volume.mkdir()
        self.enterContext(patch.object(cloud_start, "VOLUME_ROOT", self.volume))
        self.mount_check = self.enterContext(patch.object(cloud_start, "_has_volume_mount", return_value=True))
        self.credentials = {
            "type": "service_account",
            "project_id": "synthetic-project",
            "client_email": "test@synthetic-project.iam.gserviceaccount.com",
            "private_key": "-----BEGIN PRIVATE KEY-----\nSYNTHETIC-NOT-A-KEY\n-----END PRIVATE KEY-----\n",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
        self.environment = {
            "DOCTOR_USERNAME": "synthetic-clinic",
            "DOCTOR_PASSWORD": "synthetic-password-long",
            "ESP32_API_KEY": "synthetic-device-secret-long-enough",
            "FIREBASE_DATABASE_URL": "https://synthetic-project.firebaseio.com/",
            "FIREBASE_SERVICE_ACCOUNT_JSON": json.dumps(self.credentials),
            "NEOCARE_AUTH_DB": str(self.volume / "neocare_auth.sqlite3"),
            "PORT": "8123",
        }

    def test_valid_config_does_not_create_or_open_database(self):
        port, database, credentials = cloud_start.validate_configuration(self.environment)
        self.assertEqual(port, 8123)
        self.assertEqual(database, (self.volume / "neocare_auth.sqlite3").resolve())
        self.assertEqual(credentials, self.credentials)
        self.assertFalse(database.exists())

    def test_missing_or_legacy_credentials_fail_closed(self):
        for field, value in (
            ("DOCTOR_USERNAME", ""), ("DOCTOR_PASSWORD", ""),
            ("DOCTOR_PASSWORD", "123456789"), ("DOCTOR_PASSWORD", " " * 12),
            ("ESP32_API_KEY", "short"),
        ):
            with self.subTest(field=field, value=value):
                with self.assertRaises(cloud_start.CloudConfigurationError):
                    cloud_start.validate_configuration({**self.environment, field: value})

    def test_database_outside_volume_is_rejected(self):
        for value in (str(self.folder / "outside.sqlite3"), "relative.sqlite3", str(self.volume), ""):
            with self.subTest(path=value):
                with self.assertRaisesRegex(cloud_start.CloudConfigurationError, "persistent Railway volume"):
                    cloud_start.validate_configuration({**self.environment, "NEOCARE_AUTH_DB": value})

    def test_ordinary_ephemeral_directory_is_not_a_volume(self):
        self.mount_check.return_value = False
        with self.assertRaisesRegex(cloud_start.CloudConfigurationError, "persistent Railway volume"):
            cloud_start.validate_configuration(self.environment)

    def test_database_url_rejects_http_credentials_or_unrelated_host(self):
        for url in (
            "", "http://synthetic-project.firebaseio.com/",
            "https://unrelated.example.invalid/", "https://synthetic-project.firebaseio.com.evil.invalid/",
            "https://user:secret@synthetic-project.firebaseio.com/",
            "https://synthetic-project.firebaseio.com/?auth=synthetic",
        ):
            with self.subTest(url=url):
                with self.assertRaisesRegex(cloud_start.CloudConfigurationError, "FIREBASE_DATABASE_URL"):
                    cloud_start.validate_configuration({**self.environment, "FIREBASE_DATABASE_URL": url})

    def test_alternate_firebase_database_hostname_is_accepted(self):
        cloud_start.validate_configuration({
            **self.environment,
            "FIREBASE_DATABASE_URL": "https://synthetic-project.europe-west1.firebasedatabase.app/",
        })

    def test_bad_ports_are_rejected(self):
        for value in ("bad", "0", "65536", "-2"):
            with self.subTest(port=value):
                with self.assertRaisesRegex(cloud_start.CloudConfigurationError, "PORT"):
                    cloud_start.validate_configuration({**self.environment, "PORT": value})

    def test_invalid_json_or_credential_fields_do_not_echo_secret(self):
        secret_marker = "DO-NOT-ECHO-SYNTHETIC-SECRET"
        invalid = [secret_marker, "[]", json.dumps({**self.credentials, "private_key": secret_marker}),
                   json.dumps({**self.credentials, "token_uri": "https://unrelated.example.invalid/token"})]
        for raw in invalid:
            with self.subTest(length=len(raw)):
                with self.assertRaises(cloud_start.CloudConfigurationError) as caught:
                    cloud_start.validate_configuration({**self.environment, "FIREBASE_SERVICE_ACCOUNT_JSON": raw})
                self.assertNotIn(secret_marker, str(caught.exception))

    def test_ephemeral_credential_file_is_removed_even_after_failure(self):
        with self.assertRaisesRegex(RuntimeError, "synthetic startup failure"):
            with cloud_start.credential_file(self.credentials) as path:
                self.assertEqual(json.loads(path.read_text(encoding="utf-8")), self.credentials)
                if os.name != "nt":
                    self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                    self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)
                raise RuntimeError("synthetic startup failure")
        self.assertFalse(path.exists())

    def test_run_forces_rules_and_keeps_secret_file_only_for_server_lifetime(self):
        observed_paths = []

        def fake_server(*args, **kwargs):
            path = Path(os.environ["GOOGLE_APPLICATION_CREDENTIALS"])
            observed_paths.append(path)
            self.assertTrue(path.is_file())
            self.assertEqual(os.environ["NEOCARE_RECOMMENDATION_MODE"], "rules")
            self.assertNotIn("FIREBASE_SERVICE_ACCOUNT_JSON", os.environ)
            self.assertEqual(args, ("api:app",))
            self.assertEqual(kwargs["host"], "0.0.0.0")
            self.assertEqual(kwargs["port"], 8123)
            self.assertEqual(kwargs["workers"], 1)
            self.assertTrue(kwargs["proxy_headers"])

        with patch.dict(os.environ, {**self.environment, "NEOCARE_RECOMMENDATION_MODE": "ollama"}, clear=True), \
             patch("uvicorn.run", side_effect=fake_server):
            cloud_start.run()
        self.assertEqual(len(observed_paths), 1)
        self.assertFalse(observed_paths[0].exists())


if __name__ == "__main__":
    unittest.main()
