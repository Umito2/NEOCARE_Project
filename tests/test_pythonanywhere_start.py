"""Exercise the PythonAnywhere launcher without Firebase, sockets, or real secrets."""

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import cloud_start
import pythonanywhere_start


class PythonAnywhereLauncherTests(unittest.TestCase):
    def setUp(self):
        self.home = Path(self.enterContext(tempfile.TemporaryDirectory(prefix="neocare-pa-test-")))
        self.directory = self.home / ".config" / "neocare"
        self.directory.mkdir(parents=True, mode=0o700)
        self.path = self.directory / "settings.json"
        self.credentials = {
            "type": "service_account",
            "project_id": "synthetic-project",
            "client_email": "test@synthetic-project.iam.gserviceaccount.com",
            "private_key": "-----BEGIN PRIVATE KEY-----\nSYNTHETIC-NOT-A-KEY\n-----END PRIVATE KEY-----\n",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
        self.settings = {
            "DOCTOR_USERNAME": "synthetic-clinic",
            "DOCTOR_PASSWORD": "synthetic-password-long",
            "ESP32_API_KEY": "synthetic-device-secret-long-enough",
            "FIREBASE_DATABASE_URL": "https://synthetic-project.firebaseio.com/",
            "FIREBASE_SERVICE_ACCOUNT_JSON": self.credentials,
        }
        self.write_settings(self.settings)
        self.socket = str(self.home / "managed.sock")
        self.enterContext(patch.object(Path, "home", return_value=self.home))

    def write_settings(self, settings):
        self.path.write_text(json.dumps(settings), encoding="utf-8")
        os.chmod(self.path, 0o600)

    def test_public_helper_does_not_require_railway_storage(self):
        settings = pythonanywhere_start.load_private_settings(self.home)
        with patch.object(cloud_start, "_has_volume_mount", side_effect=AssertionError("no mount lookup")):
            port, credentials = cloud_start.validate_public_credentials(settings)
        self.assertEqual(port, 8000)
        self.assertEqual(credentials, self.credentials)
        self.assertFalse((self.home / "neocare-data").exists())

    def test_string_and_nested_firebase_credentials_are_supported(self):
        for value in (self.credentials, json.dumps(self.credentials)):
            self.write_settings({**self.settings, "FIREBASE_SERVICE_ACCOUNT_JSON": value})
            result = pythonanywhere_start.load_private_settings(self.home)
            self.assertEqual(json.loads(result["FIREBASE_SERVICE_ACCOUNT_JSON"]), self.credentials)
            self.assertTrue(all(isinstance(item, str) for item in result.values()))

    def test_missing_config_fails_cleanly(self):
        self.path.unlink()
        with self.assertRaisesRegex(cloud_start.CloudConfigurationError, "private.*settings.json"):
            pythonanywhere_start.load_private_settings(self.home)

    def test_malformed_json_does_not_echo_contents(self):
        marker = "SYNTHETIC-SECRET-DO-NOT-ECHO"
        self.path.write_text(marker, encoding="utf-8")
        with self.assertRaises(cloud_start.CloudConfigurationError) as caught:
            pythonanywhere_start.load_private_settings(self.home)
        self.assertNotIn(marker, str(caught.exception))

    def test_exact_keys_and_string_values_are_required(self):
        invalid = [[], {}, {**self.settings, "EXTRA": "not-allowed"},
                   {**self.settings, "DOCTOR_PASSWORD": 123456789}]
        for settings in invalid:
            with self.subTest(settings_type=type(settings).__name__):
                self.write_settings(settings)
                with self.assertRaises(cloud_start.CloudConfigurationError):
                    pythonanywhere_start.load_private_settings(self.home)

    def test_symlinked_configuration_and_database_paths_are_rejected(self):
        # Mock detection because Windows often requires elevated symlink privileges.
        with patch.object(Path, "is_symlink", return_value=True):
            with self.assertRaisesRegex(cloud_start.CloudConfigurationError, "symlink"):
                pythonanywhere_start.load_private_settings(self.home)
            with self.assertRaisesRegex(cloud_start.CloudConfigurationError, "symlink"):
                pythonanywhere_start.prepare_database(self.home)

    @unittest.skipIf(os.name == "nt", "Unix permission bits are enforced on the Linux host")
    def test_world_readable_configuration_is_rejected(self):
        os.chmod(self.path, 0o644)
        with self.assertRaisesRegex(cloud_start.CloudConfigurationError, "mode 600"):
            pythonanywhere_start.load_private_settings(self.home)

    def test_missing_or_relative_socket_is_rejected_before_config_read(self):
        for value in ("", "relative.sock", "invalid\x00socket"):
            with self.subTest(socket=value), patch.object(pythonanywhere_start.os, "environ", {"DOMAIN_SOCKET": value}):
                with patch.object(pythonanywhere_start, "load_private_settings") as read_config:
                    with self.assertRaisesRegex(cloud_start.CloudConfigurationError, "DOMAIN_SOCKET"):
                        pythonanywhere_start.run()
                    read_config.assert_not_called()

    def test_weak_credentials_do_not_create_database_directory(self):
        self.write_settings({**self.settings, "DOCTOR_PASSWORD": "123456789"})
        with patch.dict(os.environ, {"DOMAIN_SOCKET": self.socket}, clear=True):
            with self.assertRaisesRegex(cloud_start.CloudConfigurationError, "DOCTOR_PASSWORD"):
                pythonanywhere_start.run()
        self.assertFalse((self.home / "neocare-data").exists())

    def test_database_cannot_be_a_directory(self):
        (self.home / "neocare-data" / "neocare_auth.sqlite3").mkdir(parents=True)
        with self.assertRaisesRegex(cloud_start.CloudConfigurationError, "database path"):
            pythonanywhere_start.prepare_database(self.home)

    def test_run_forces_private_persistent_storage_rules_and_managed_socket(self):
        observed_paths = []

        def fake_server(*args, **kwargs):
            path = Path(os.environ["GOOGLE_APPLICATION_CREDENTIALS"])
            observed_paths.append(path)
            self.assertTrue(path.is_file())
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), self.credentials)
            self.assertNotIn("FIREBASE_SERVICE_ACCOUNT_JSON", os.environ)
            self.assertEqual(os.environ["NEOCARE_RECOMMENDATION_MODE"], "rules")
            self.assertEqual(os.environ["NEOCARE_SQLITE_JOURNAL_MODE"], "DELETE")
            self.assertEqual(os.environ["NEOCARE_AUTH_DB"], str(self.home / "neocare-data" / "neocare_auth.sqlite3"))
            self.assertEqual(args, ("api:app",))
            self.assertEqual(kwargs, {
                "uds": self.socket, "workers": 1, "proxy_headers": True,
                "forwarded_allow_ips": "*", "access_log": False,
            })
            if os.name != "nt":
                self.assertEqual((self.home / "neocare-data").stat().st_mode & 0o777, 0o700)

        with patch.dict(os.environ, {
            "DOMAIN_SOCKET": self.socket, "NEOCARE_RECOMMENDATION_MODE": "ollama",
            "NEOCARE_AUTH_DB": "untrusted.sqlite3", "NEOCARE_SQLITE_JOURNAL_MODE": "WAL",
        }, clear=True), patch("uvicorn.run", side_effect=fake_server):
            pythonanywhere_start.run()
        self.assertEqual(len(observed_paths), 1)
        self.assertFalse(observed_paths[0].exists())
        self.assertFalse((self.home / "neocare-data" / "neocare_auth.sqlite3").exists())


if __name__ == "__main__":
    unittest.main()
