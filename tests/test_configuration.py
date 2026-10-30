"""Configuration and mail transport tests with no real credentials or delivery."""

import os
import tempfile
import unittest
from email.message import EmailMessage
from pathlib import Path
from unittest.mock import Mock, patch

import api
import main


class FirebaseConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.dict(os.environ, {}, clear=True))
        folder = self.enterContext(tempfile.TemporaryDirectory(prefix="neocare-config-test-"))
        self.folder = Path(folder)
        self.enterContext(patch.object(main, "BASE_DIR", str(self.folder)))
        self.enterContext(patch.object(main, "SERVICE_ACCOUNT_FILE", str(self.folder / "serviceAccountKey.json")))
        self.enterContext(patch.object(main, "LEGACY_SERVICE_ACCOUNT_FILE", str(self.folder / "serviceAccountKey.json.json")))

    def test_absent_credentials_return_no_file(self):
        self.assertIsNone(main.find_service_account_file())

    def test_explicit_missing_credential_path_fails_clearly(self):
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(self.folder / "missing.json")
        with self.assertRaisesRegex(FileNotFoundError, "GOOGLE_APPLICATION_CREDENTIALS"):
            main.find_service_account_file()

    def test_explicit_credentials_take_precedence(self):
        local = self.folder / "serviceAccountKey.json"
        explicit = self.folder / "configured.json"
        local.write_text("{}", encoding="utf-8")
        explicit.write_text("{}", encoding="utf-8")
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(explicit)
        self.assertEqual(main.find_service_account_file(), str(explicit))

    def test_local_and_legacy_file_discovery(self):
        legacy = self.folder / "serviceAccountKey.json.json"
        legacy.write_text("{}", encoding="utf-8")
        self.assertEqual(main.find_service_account_file(), str(legacy))
        local = self.folder / "serviceAccountKey.json"
        local.write_text("{}", encoding="utf-8")
        self.assertEqual(main.find_service_account_file(), str(local))

    def test_initialization_without_credentials_fails_before_sdk_call(self):
        with patch.object(main.firebase_admin, "initialize_app") as initialize:
            with self.assertRaises(FileNotFoundError):
                main.init_firebase()
            initialize.assert_not_called()

    def test_initialization_passes_configured_database_to_sdk(self):
        credential = self.folder / "serviceAccountKey.json"
        credential.write_text("{}", encoding="utf-8")
        with patch.object(main.firebase_admin, "_apps", {}), \
             patch.object(main.credentials, "Certificate", return_value="test-credential") as certificate, \
             patch.object(main.firebase_admin, "initialize_app") as initialize, \
             patch("builtins.print"):
            main.init_firebase()
        certificate.assert_called_once_with(str(credential))
        initialize.assert_called_once_with("test-credential", {"databaseURL": main.DATABASE_URL})

    def test_existing_firebase_app_is_not_initialized_twice(self):
        (self.folder / "serviceAccountKey.json").write_text("{}", encoding="utf-8")
        with patch.object(main.firebase_admin, "_apps", {"[DEFAULT]": Mock()}), \
             patch.object(main.firebase_admin, "initialize_app") as initialize, \
             patch.object(main.credentials, "Certificate") as certificate, patch("builtins.print"):
            main.init_firebase()
        initialize.assert_not_called()
        certificate.assert_not_called()


class EmailTransportTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.dict(os.environ, {}, clear=True))
        self.smtp = self.enterContext(patch.object(api.smtplib, "SMTP"))
        self.ssl = self.enterContext(patch.object(api.smtplib, "SMTP_SSL"))
        self.message = EmailMessage()
        self.message["To"] = "parent@example.invalid"
        self.message["Subject"] = "Test only"
        self.message.set_content("Synthetic test content")

    def configure(self):
        os.environ.update({
            "SMTP_HOST": "smtp.example.invalid", "SMTP_FROM": "clinic@example.invalid",
            "SMTP_USERNAME": "test-user", "SMTP_PASSWORD": "test-only-password",
        })

    def test_missing_configuration_never_opens_connection(self):
        self.assertEqual(api.send_email_message(self.message), "not_configured")
        self.smtp.assert_not_called()
        self.ssl.assert_not_called()

    def test_starttls_transport_authenticates_and_sends(self):
        self.configure()
        self.assertEqual(api.send_email_message(self.message), "sent")
        self.smtp.assert_called_once_with("smtp.example.invalid", 587, timeout=10)
        transport = self.smtp.return_value.__enter__.return_value
        transport.starttls.assert_called_once()
        transport.login.assert_called_once_with("test-user", "test-only-password")
        transport.send_message.assert_called_once_with(self.message)
        self.assertEqual(self.message["From"], "clinic@example.invalid")
        self.ssl.assert_not_called()

    def test_ssl_transport_uses_configured_port(self):
        self.configure()
        os.environ.update({"SMTP_USE_SSL": "true", "SMTP_PORT": "465"})
        self.assertEqual(api.send_email_message(self.message), "sent")
        self.ssl.assert_called_once_with("smtp.example.invalid", 465, timeout=10)
        transport = self.ssl.return_value.__enter__.return_value
        transport.login.assert_called_once_with("test-user", "test-only-password")
        transport.send_message.assert_called_once_with(self.message)
        self.smtp.assert_not_called()

    def test_transport_error_propagates_to_callers_for_handling(self):
        self.configure()
        self.smtp.side_effect = OSError("Synthetic transport failure")
        with self.assertRaisesRegex(OSError, "Synthetic"):
            api.send_email_message(self.message)

    def test_invalid_port_fails_before_connecting(self):
        self.configure()
        os.environ["SMTP_PORT"] = "invalid"
        with self.assertRaises(ValueError):
            api.send_email_message(self.message)
        self.smtp.assert_not_called()
        self.ssl.assert_not_called()
