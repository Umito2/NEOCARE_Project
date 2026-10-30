"""Run real HTTP handlers and SQLite against an in-memory Firebase substitute.

No service-account file is read. Outbound connections, SMTP, and live AI calls
are blocked. Firebase transport/security rules are outside this suite's scope.
"""

import copy
import os
import socket
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

import httpx

from fastapi.testclient import TestClient

import api
import auth_store
import main


THRESHOLDS = {
    "spo2_min": 95,
    "temperature_warning_c": 38,
    "temperature_critical_c": 39,
    "heart_rate_max_age_0_3": 130,
    "heart_rate_max_age_over_3": 115,
    "respiratory_rate_max_age_0_3": 34,
    "respiratory_rate_max_age_over_3": 26,
}


class MemoryReference:
    def __init__(self, data, path=""):
        self.data = data
        self.path = tuple(part for part in path.split("/") if part)

    def child(self, path):
        return MemoryReference(self.data, "/".join((*self.path, path)))

    def get(self):
        node = self.data
        for key in self.path:
            if not isinstance(node, dict) or key not in node:
                return None
            node = node[key]
        return copy.deepcopy(node)

    def set(self, value):
        node = self.data
        for key in self.path[:-1]:
            node = node.setdefault(key, {})
        node[self.path[-1]] = copy.deepcopy(value)

    def delete(self):
        node = self.data
        for key in self.path[:-1]:
            node = node.get(key, {})
        node.pop(self.path[-1], None)


class ApiTestCase(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        temporary = self.stack.enter_context(tempfile.TemporaryDirectory(prefix="neocare-tests-"))
        self.stack.enter_context(patch.dict(os.environ, {
            "DOCTOR_USERNAME": "test-clinic",
            "DOCTOR_PASSWORD": "test-clinic-password-only",
            "ESP32_API_KEY": "test-device-key-only",
        }, clear=True))
        self.stack.enter_context(patch.object(auth_store, "DB_PATH", Path(temporary) / "auth.sqlite3"))
        self.data = {}
        self.reference = lambda path: MemoryReference(self.data, path)
        self.stack.enter_context(patch.object(main.db, "reference", side_effect=self.reference))
        self.firebase_init = self.stack.enter_context(patch.object(main, "init_firebase"))
        # Always intercept the local provider before constructing HTTP clients.
        # Even if Ollama happens to be running, broad tests use only this mock.
        self.ai_client = self.stack.enter_context(patch.object(api.httpx, "Client"))
        self.ai_transport = self.ai_client.return_value.__enter__.return_value
        self.ai_transport.post.side_effect = httpx.ConnectError("Synthetic offline Ollama")
        # Windows asyncio builds its internal socketpair using a loopback
        # connect. Permit that transport while blocking external destinations.
        real_connect = socket.socket.connect

        def connect_loopback_only(sock, address):
            if isinstance(address, tuple) and address[0] in ("127.0.0.1", "::1"):
                return real_connect(sock, address)
            raise AssertionError("External I/O is blocked")

        self.stack.enter_context(patch.object(socket.socket, "connect", connect_loopback_only))
        for target in ("socket.create_connection", "smtplib.SMTP", "smtplib.SMTP_SSL"):
            self.stack.enter_context(patch(target, side_effect=AssertionError("External I/O is blocked")))
        self.client = self.new_client()

    def new_client(self):
        return self.stack.enter_context(TestClient(
            api.app, base_url="https://testserver", raise_server_exceptions=False,
        ))

    def signup(self, client=None, **changes):
        payload = {
            "parent_name": "Test Parent", "email": "parent@example.invalid",
            "phone": "0000000000", "password": "test-parent-password-only",
            "child_name": "Test Child", "age_years": 4,
            "height_cm": 100, "weight_kg": 16,
        }
        payload.update(changes)
        response = (client or self.client).post("/api/v1/auth/signup", json=payload)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["child_id"]

    def doctor(self, client=None):
        response = (client or self.client).post("/api/v1/auth/login", json={
            "role": "doctor", "identifier": "test-clinic",
            "password": "test-clinic-password-only",
        })
        self.assertEqual(response.status_code, 200, response.text)

    def ingest(self, child_id, **changes):
        payload = {
            "child_id": child_id, "heart_rate_bpm": 100, "spo2_percent": 98,
            "temperature_c": 37, "resp_rate": 20, "activity": "Resting",
        }
        payload.update(changes)
        return self.client.post("/api/v1/readings", json=payload, headers={"X-API-Key": "test-device-key-only"})

    def thresholds(self):
        auth_store.save_thresholds(copy.deepcopy(THRESHOLDS))

    def profile_ref(self, child_id):
        return self.reference(f"neocare_system/children_profiles/{child_id}")

    def reading_ref(self, child_id):
        return self.reference(f"neocare_system/live_monitoring/{child_id}")
