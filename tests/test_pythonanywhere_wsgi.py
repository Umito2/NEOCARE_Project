"""Real a2wsgi requests with a synthetic app, home and credentials only."""

import asyncio
from contextlib import asynccontextmanager
from contextvars import ContextVar
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from wsgiref.util import setup_testing_defaults

from fastapi import FastAPI, Request, Response

from cloud_start import CloudConfigurationError
import pythonanywhere_wsgi


class LazyApplicationTests(unittest.TestCase):
    def test_construction_is_lazy_and_concurrent_first_requests_build_once(self):
        calls = []

        def factory():
            calls.append(os.getpid())
            return lambda environ, start_response: [b"synthetic"]

        application = pythonanywhere_wsgi.LazyApplication(factory)
        self.assertEqual(calls, [])
        with ThreadPoolExecutor(max_workers=8) as pool:
            responses = list(pool.map(lambda _: application({}, None), range(24)))
        self.assertEqual(calls, [os.getpid()])
        self.assertEqual(responses, [[b"synthetic"]] * 24)

    def test_changed_pid_rebuilds_an_inherited_application(self):
        calls = []

        def factory():
            calls.append(os.getpid())
            return lambda environ, start_response: [str(calls[-1]).encode()]

        with patch("pythonanywhere_wsgi.os.getpid", return_value=100):
            application = pythonanywhere_wsgi.LazyApplication(factory)
            self.assertEqual(application({}, None), [b"100"])
        with patch("pythonanywhere_wsgi.os.getpid", return_value=200):
            self.assertEqual(application({}, None), [b"200"])
            self.assertEqual(application({}, None), [b"200"])
        self.assertEqual(calls, [100, 200])

    @unittest.skipUnless(hasattr(os, "fork"), "A real fork requires the Linux host")
    def test_forked_worker_initializes_its_own_application(self):
        def factory():
            created_in = os.getpid()
            return lambda environ, start_response: [str(created_in).encode()]

        application = pythonanywhere_wsgi.LazyApplication(factory)
        self.assertEqual(application({}, None), [str(os.getpid()).encode()])
        reader, writer = os.pipe()
        child = os.fork()
        if child == 0:
            os.close(reader)
            try:
                result = b"".join(application({}, None))
                os.write(writer, result)
            finally:
                os.close(writer)
                os._exit(0)
        os.close(writer)
        try:
            result = os.read(reader, 128)
        finally:
            os.close(reader)
            _, status = os.waitpid(child, 0)
        self.assertEqual(status, 0)
        self.assertEqual(result, str(child).encode())


class PythonAnywhereWSGITests(unittest.TestCase):
    def setUp(self):
        self.home = Path(self.enterContext(tempfile.TemporaryDirectory(prefix="neocare-wsgi-test-")))
        self.directory = self.home / ".config" / "neocare"
        self.directory.mkdir(parents=True, mode=0o700)
        self.path = self.directory / "settings.json"
        self.settings = {
            "DOCTOR_USERNAME": "synthetic-clinic",
            "DOCTOR_PASSWORD": "synthetic-password-long",
            "ESP32_API_KEY": "synthetic-device-secret-long-enough",
            "FIREBASE_DATABASE_URL": "https://synthetic-project.firebaseio.com/",
            "FIREBASE_SERVICE_ACCOUNT_JSON": {
                "type": "service_account", "project_id": "synthetic-project",
                "client_email": "test@synthetic-project.iam.gserviceaccount.com",
                "private_key": "-----BEGIN PRIVATE KEY-----\nSYNTHETIC-NOT-A-KEY\n-----END PRIVATE KEY-----\n",
                "token_uri": "https://oauth2.googleapis.com/token",
            },
        }
        self.path.write_text(json.dumps(self.settings), encoding="utf-8")
        os.chmod(self.path, 0o600)
        self.enterContext(patch.object(Path, "home", return_value=self.home))
        self.enterContext(patch.dict(os.environ, {}, clear=True))

    def request(self, application, scheme):
        environ = {}
        setup_testing_defaults(environ)
        environ.update({
            "wsgi.url_scheme": scheme, "SERVER_PORT": "443" if scheme == "https" else "80",
            "wsgi.input": BytesIO(), "HTTP_X_FORWARDED_PROTO": "http",
        })
        result = {}

        def start_response(status, headers, exc_info=None):
            result.update(status=status, headers=headers)

        response = application(environ, start_response)
        try:
            result["body"] = b"".join(response)
        finally:
            if hasattr(response, "close"):
                response.close()
        return result

    def test_https_cookie_and_lifespan_use_real_adapter_with_clean_shutdown(self):
        events, paths, tasks, loops = [], [], [], []
        marker = ContextVar("synthetic_lifespan_marker")

        @asynccontextmanager
        async def lifespan(app):
            token = marker.set("started")
            events.append("startup")
            tasks.append(asyncio.current_task())
            loops.append(asyncio.get_running_loop())
            path = Path(os.environ["GOOGLE_APPLICATION_CREDENTIALS"])
            paths.append(path)
            self.assertTrue(path.is_file())
            self.assertNotIn("FIREBASE_SERVICE_ACCOUNT_JSON", os.environ)
            self.assertEqual(os.environ["NEOCARE_RECOMMENDATION_MODE"], "rules")
            self.assertEqual(os.environ["NEOCARE_SQLITE_JOURNAL_MODE"], "DELETE")
            self.assertEqual(os.environ["NEOCARE_AUTH_DB"], str(self.home / "neocare-data" / "neocare_auth.sqlite3"))
            try:
                yield
            finally:
                self.assertTrue(path.is_file())
                self.assertEqual(marker.get(), "started")
                marker.reset(token)
                tasks.append(asyncio.current_task())
                events.append("shutdown")

        app = FastAPI(lifespan=lifespan)

        @app.get("/")
        async def login(request: Request, response: Response):
            self.assertEqual(events, ["startup"])
            self.assertIs(asyncio.get_running_loop(), loops[0])
            response.set_cookie("synthetic_session", "invented", secure=request.url.scheme == "https", httponly=True)
            return {"scheme": request.url.scheme}

        with patch.dict(sys.modules, {"api": SimpleNamespace(app=app)}):
            application = pythonanywhere_wsgi.build_application()
        self.addCleanup(application.close)
        secure = self.request(application, "https")
        self.assertEqual(secure["status"], "200 OK")
        self.assertEqual(json.loads(secure["body"]), {"scheme": "https"})
        cookie = next(value for name, value in secure["headers"] if name.lower() == "set-cookie")
        self.assertIn("Secure", cookie)
        self.assertIn("HttpOnly", cookie)
        plain = self.request(application, "http")
        self.assertEqual(json.loads(plain["body"]), {"scheme": "http"})
        application.close()
        application.close()
        self.assertEqual(events, ["startup", "shutdown"])
        self.assertIs(tasks[0], tasks[1])
        self.assertFalse(paths[0].exists())
        self.assertTrue(application.loop.is_closed())

    def test_startup_failure_removes_credentials_and_hides_secret_error(self):
        paths = []

        @asynccontextmanager
        async def lifespan(app):
            paths.append(Path(os.environ["GOOGLE_APPLICATION_CREDENTIALS"]))
            raise RuntimeError("SYNTHETIC-SECRET-DO-NOT-ECHO")
            yield

        app = FastAPI(lifespan=lifespan)
        with patch.dict(sys.modules, {"api": SimpleNamespace(app=app)}):
            with self.assertRaises(CloudConfigurationError) as caught:
                pythonanywhere_wsgi.build_application()
        self.assertNotIn("SYNTHETIC-SECRET-DO-NOT-ECHO", str(caught.exception))
        self.assertEqual(len(paths), 1)
        self.assertFalse(paths[0].exists())

    def test_missing_private_settings_rejected_before_app_start(self):
        self.path.unlink()
        with self.assertRaises(CloudConfigurationError):
            pythonanywhere_wsgi.build_application()
        self.assertFalse((self.home / "neocare-data").exists())


if __name__ == "__main__":
    unittest.main()
