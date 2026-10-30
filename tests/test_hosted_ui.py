"""Real handlers and temporary SQLite; hosted-origin tests perform no live I/O."""

import os
import unittest
from unittest.mock import patch

import api
import auth_store
from hosted_ui import CLOUD_SESSION_COOKIE, LOCAL_SESSION_COOKIE, allowed_web_origins
from tests.support import ApiTestCase


WEB_ORIGIN = "https://neocare-system.web.app"
SECOND_ORIGIN = "https://neocare-system.firebaseapp.com"


class HostedOriginConfigurationTests(unittest.TestCase):
    def test_only_explicit_https_origins_are_configurable(self):
        with patch.dict(os.environ, {"NEOCARE_WEB_ORIGINS": f" {WEB_ORIGIN}, {SECOND_ORIGIN} "}):
            self.assertEqual(allowed_web_origins(), {WEB_ORIGIN, SECOND_ORIGIN})
        for origin in ("*", "null", "http://example.com", "https://*.web.app", "https://web.app/", "https://web.app/path", "https://user:pass@web.app", "https://web.app?x=1", "https://web.app#x", "https://web.app:99999", WEB_ORIGIN + ","):
            with self.subTest(origin=origin), patch.dict(os.environ, {"NEOCARE_WEB_ORIGINS": origin}):
                with self.assertRaises(ValueError):
                    allowed_web_origins()


class HostedUITests(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {"NEOCARE_WEB_ORIGINS": f"{WEB_ORIGIN},{SECOND_ORIGIN}"}))

    def login_hosted(self, client=None, origin=WEB_ORIGIN):
        return (client or self.client).post("/api/v1/auth/login", headers={"Origin": origin}, json={
            "role": "doctor", "identifier": "test-clinic", "password": "test-clinic-password-only",
        })

    def assert_cors(self, response, origin=WEB_ORIGIN):
        self.assertEqual(response.headers.get("access-control-allow-origin"), origin)
        self.assertEqual(response.headers.get("access-control-allow-credentials"), "true")
        self.assertIn("origin", response.headers.get("vary", "").lower())

    def assert_cloud_cookie(self, response, deleted=False):
        cookies = response.headers.get_list("set-cookie")
        self.assertEqual(len(cookies), 1)
        cookie = cookies[0]
        self.assertTrue(cookie.startswith(CLOUD_SESSION_COOKIE + "="), cookie)
        for attribute in ("Secure", "HttpOnly", "SameSite=none", "Path=/", "Partitioned"):
            self.assertIn(attribute, cookie)
        self.assertNotIn("Domain=", cookie)
        self.assertEqual(cookie.count("Partitioned"), 1)
        self.assertIn("Max-Age=0" if deleted else f"Max-Age={auth_store.SESSION_SECONDS}", cookie)

    def test_allowed_preflight_is_explicit_and_does_not_require_login(self):
        response = self.client.options("/api/v1/auth/login", headers={
            "Origin": WEB_ORIGIN, "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "content-type",
        })
        self.assertEqual(response.status_code, 204)
        self.assert_cors(response)
        self.assertEqual(response.headers["access-control-allow-headers"], "Content-Type")
        self.assertNotIn("*", response.headers["access-control-allow-methods"])
        self.assertNotIn("set-cookie", response.headers)

    def test_unexpected_origins_cannot_preflight_or_sign_in(self):
        for origin in ("https://evil.example", WEB_ORIGIN + ".evil.example", WEB_ORIGIN + "/", "http://neocare-system.web.app", "null"):
            with self.subTest(origin=origin):
                preflight = self.client.options("/api/v1/auth/login", headers={"Origin": origin, "Access-Control-Request-Method": "POST"})
                self.assertEqual(preflight.status_code, 403)
                response = self.login_hosted(origin=origin)
                self.assertEqual(response.status_code, 403)
                self.assertNotIn("set-cookie", response.headers)
                self.assertNotIn("access-control-allow-origin", response.headers)

    def test_preflight_rejects_device_keys_authorization_and_unnecessary_methods(self):
        for method, requested_headers in (("POST", "X-API-Key"), ("GET", "Authorization"), ("POST", "Content-Type, X-Custom"), ("TRACE", "Content-Type")):
            with self.subTest(method=method, headers=requested_headers):
                response = self.client.options("/api/v1/children", headers={
                    "Origin": WEB_ORIGIN, "Access-Control-Request-Method": method,
                    "Access-Control-Request-Headers": requested_headers,
                })
                self.assertEqual(response.status_code, 403)
                self.assert_cors(response)

    def test_cloud_login_sets_partitioned_httponly_cookie_and_authenticates(self):
        response = self.login_hosted()
        self.assertEqual(response.status_code, 200, response.text)
        self.assert_cors(response)
        self.assert_cloud_cookie(response)
        self.assertNotIn("token", response.json())
        token = self.client.cookies.get(CLOUD_SESSION_COOKIE)
        self.assertTrue(token)
        self.assertEqual(auth_store.get_session(token)["role"], "doctor")
        me = self.client.get("/api/v1/auth/me", headers={"Origin": WEB_ORIGIN})
        self.assertEqual(me.json()["role"], "doctor")
        self.assert_cors(me)

    def test_second_explicit_origin_is_allowed_without_wildcard_matching(self):
        response = self.login_hosted(origin=SECOND_ORIGIN)
        self.assertEqual(response.status_code, 200)
        self.assert_cors(response, SECOND_ORIGIN)
        self.assert_cloud_cookie(response)

    def test_cloud_requests_do_not_fall_back_to_local_cookie(self):
        self.doctor()
        response = self.client.get("/api/v1/auth/me", headers={"Origin": WEB_ORIGIN})
        self.assertEqual(response.status_code, 401)
        self.assert_cors(response)
        self.assertEqual(self.client.get("/api/v1/auth/me").status_code, 200)

    def test_local_requests_do_not_use_cloud_cookie(self):
        self.assertEqual(self.login_hosted().status_code, 200)
        self.assertEqual(self.client.get("/api/v1/auth/me").status_code, 401)
        self.assertEqual(self.client.get("/api/v1/auth/me", headers={"Origin": "https://testserver"}).status_code, 401)

    def test_cloud_logout_revokes_only_cloud_session_and_clears_partitioned_cookie(self):
        self.doctor()
        local_token = self.client.cookies.get(LOCAL_SESSION_COOKIE)
        self.login_hosted()
        cloud_token = self.client.cookies.get(CLOUD_SESSION_COOKIE)
        response = self.client.post("/api/v1/auth/logout", headers={"Origin": WEB_ORIGIN})
        self.assertEqual(response.status_code, 200)
        self.assert_cors(response)
        self.assert_cloud_cookie(response, deleted=True)
        self.assertIsNone(auth_store.get_session(cloud_token))
        self.assertIsNotNone(auth_store.get_session(local_token))
        self.assertEqual(self.client.get("/api/v1/auth/me", headers={"Origin": WEB_ORIGIN}).status_code, 401)
        self.assertEqual(self.client.get("/api/v1/auth/me").status_code, 200)

    def test_no_origin_and_same_origin_keep_existing_local_cookie(self):
        response = self.login_hosted(origin="https://testserver")
        self.assertEqual(response.status_code, 200)
        cookie = response.headers["set-cookie"]
        self.assertTrue(cookie.startswith(LOCAL_SESSION_COOKIE + "="))
        self.assertIn("SameSite=lax", cookie)
        self.assertNotIn("Partitioned", cookie)
        self.assertNotIn("access-control-allow-origin", response.headers)
        self.assertEqual(self.client.get("/api/v1/auth/me").status_code, 200)
        self.assertEqual(self.client.post("/api/v1/auth/logout", headers={"Origin": "https://testserver"}).status_code, 200)
        self.assertEqual(self.client.get("/api/v1/auth/me").status_code, 401)

    def test_disallowed_origin_cannot_logout_or_mutate_using_either_cookie(self):
        self.doctor()
        self.login_hosted()
        tokens = [self.client.cookies.get(name) for name in (LOCAL_SESSION_COOKIE, CLOUD_SESSION_COOKIE)]
        for path, body in (("/api/v1/auth/logout", {}), ("/api/v1/auth/signup", {}), ("/api/v1/doctor/accounts", {})):
            response = self.client.post(path, headers={"Origin": "https://evil.example"}, json=body)
            self.assertEqual(response.status_code, 403)
        self.assertTrue(all(auth_store.get_session(token) for token in tokens))
        self.assertEqual(self.client.get("/api/v1/auth/me", headers={"Origin": "https://evil.example"}).status_code, 403)

    def test_validation_auth_and_internal_errors_have_cors_for_trusted_origin(self):
        invalid = self.client.post("/api/v1/auth/login", headers={"Origin": WEB_ORIGIN}, json={})
        self.assertEqual(invalid.status_code, 422)
        self.assert_cors(invalid)
        unauthenticated = self.client.get("/api/v1/children", headers={"Origin": WEB_ORIGIN})
        self.assertEqual(unauthenticated.status_code, 401)
        self.assert_cors(unauthenticated)
        self.login_hosted()
        with patch.object(auth_store, "get_session", side_effect=RuntimeError("synthetic internal secret")):
            failure = self.client.get("/api/v1/auth/me", headers={"Origin": WEB_ORIGIN})
        self.assertEqual(failure.status_code, 500)
        self.assert_cors(failure)
        self.assertNotIn("synthetic internal secret", failure.text)

    def test_hosted_parent_signup_and_ownership_are_preserved(self):
        self.client.headers["Origin"] = WEB_ORIGIN
        child = self.signup()
        self.assertTrue(self.client.cookies.get(CLOUD_SESSION_COOKIE))
        self.assertIsNone(self.client.cookies.get(LOCAL_SESSION_COOKIE))
        self.assertEqual(self.client.get("/api/v1/auth/me").json()["role"], "parent")
        stranger = self.new_client()
        stranger.headers["Origin"] = WEB_ORIGIN
        self.signup(stranger, email="stranger@example.invalid")
        self.assertEqual(stranger.get(f"/api/v1/children/{child}/readings/latest").status_code, 404)
        self.assertEqual(self.client.get(f"/api/v1/children/{child}/readings/latest").status_code, 200)
        self.assertEqual(self.client.get("/api/v1/doctor/accounts").status_code, 403)

    def test_multiple_origin_headers_are_rejected_before_sign_in(self):
        response = self.client.post("/api/v1/auth/login", headers=[("Origin", WEB_ORIGIN), ("Origin", "https://evil.example")], json={})
        self.assertEqual(response.status_code, 403)
        self.assertNotIn("set-cookie", response.headers)

    def test_configuration_changes_are_not_frozen_at_module_import(self):
        with patch.dict(os.environ, {"NEOCARE_WEB_ORIGINS": ""}):
            self.assertEqual(self.login_hosted().status_code, 403)
        self.assertEqual(self.login_hosted().status_code, 200)

    def test_invalid_configuration_fails_closed(self):
        with patch.dict(os.environ, {"NEOCARE_WEB_ORIGINS": "*"}):
            response = self.login_hosted()
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("set-cookie", response.headers)

    def test_only_relevant_cookie_receives_partitioned_attribute(self):
        from starlette.requests import Request
        from starlette.responses import Response
        from hosted_ui import set_session_cookie
        request = Request({"type": "http", "scheme": "https", "server": ("testserver", 443), "path": "/", "headers": [], "neocare_cloud_origin": WEB_ORIGIN})
        response = Response()
        response.set_cookie("unrelated", "keep")
        set_session_cookie(response, request, "synthetic-token", 60)
        cookies = response.headers.getlist("set-cookie")
        self.assertNotIn("Partitioned", cookies[0])
        self.assertTrue(cookies[1].endswith("; Partitioned"))
