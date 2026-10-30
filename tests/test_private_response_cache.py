"""API privacy headers across successful, rejected and failed responses."""

import os
from unittest.mock import patch

import auth_store
from tests.support import ApiTestCase


ORIGIN = "https://neocare-system.web.app"


class PrivateResponseCacheTests(ApiTestCase):
    def assert_private(self, response):
        self.assertEqual(response.headers.get("cache-control"), "private, no-store")

    def test_authenticated_json_responses_are_never_stored(self):
        child = self.signup()
        self.ingest(child)
        for path in ("/api/v1/auth/me", "/api/v1/alerts", "/api/v1/children", f"/api/v1/children/{child}/readings/latest", f"/api/v1/children/{child}/readings/history"):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assert_private(response)

    def test_error_and_pdf_responses_have_the_same_private_policy(self):
        self.assert_private(self.client.get("/api/v1/auth/me"))
        self.assert_private(self.client.post("/api/v1/auth/login", json={}))
        child = self.signup()
        missing = self.client.get(f"/api/v1/children/{child}/report/latest/pdf")
        self.assertEqual(missing.status_code, 409)
        self.assert_private(missing)
        self.assertEqual(self.ingest(child).status_code, 200)
        pdf = self.client.get(f"/api/v1/children/{child}/report/latest/pdf")
        self.assertEqual(pdf.status_code, 200)
        self.assertTrue(pdf.content.startswith(b"%PDF-"))
        self.assert_private(pdf)
        self.assert_private(self.client.get("/api/v1/alerts/999/pdf"))

    def test_early_origin_and_configuration_errors_are_private(self):
        rejected = self.client.get("/api/v1/alerts", headers={"Origin": "https://evil.example"})
        self.assertEqual(rejected.status_code, 403)
        self.assert_private(rejected)
        self.assertNotIn("access-control-allow-origin", rejected.headers)
        with patch.dict(os.environ, {"NEOCARE_WEB_ORIGINS": "*"}):
            invalid = self.client.get("/api/v1/auth/me")
        self.assertEqual(invalid.status_code, 503)
        self.assert_private(invalid)

    def test_generated_server_error_remains_private_with_trusted_cors_headers(self):
        with patch.dict(os.environ, {"NEOCARE_WEB_ORIGINS": ORIGIN}), patch.object(auth_store, "get_session", side_effect=RuntimeError("synthetic secret")):
            response = self.client.get("/api/v1/auth/me", headers={"Origin": ORIGIN})
        self.assertEqual(response.status_code, 500)
        self.assert_private(response)
        self.assertEqual(response.headers["access-control-allow-origin"], ORIGIN)
        self.assertEqual(response.headers["access-control-allow-credentials"], "true")
        self.assertNotIn("synthetic secret", response.text)

    def test_preflight_policy_preserves_cors_behavior(self):
        with patch.dict(os.environ, {"NEOCARE_WEB_ORIGINS": ORIGIN}):
            response = self.client.options("/api/v1/auth/login", headers={
                "Origin": ORIGIN, "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "Content-Type",
            })
        self.assertEqual(response.status_code, 204)
        self.assert_private(response)
        self.assertEqual(response.headers["access-control-allow-origin"], ORIGIN)
        self.assertEqual(response.headers["access-control-allow-credentials"], "true")
        self.assertEqual(response.headers["access-control-max-age"], "600")

    def test_public_health_response_is_not_misclassified_as_private_api_data(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("private", response.headers.get("cache-control", ""))
