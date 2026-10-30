"""Reproduced backend regressions; synthetic fixtures and temporary SQLite only."""

from unittest.mock import patch

import api
import auth_store
from tests.support import ApiTestCase


class SensorValueValidationTests(ApiTestCase):
    def test_boolean_measurements_are_rejected_before_any_storage(self):
        child = self.signup()
        for field, value in (("heart_rate_bpm", True), ("spo2_percent", False), ("resp_rate", True)):
            with self.subTest(field=field):
                response = self.ingest(child, **{field: value})
                self.assertEqual(response.status_code, 422, response.text)
        self.assertIsNone(self.reading_ref(child).get())
        self.assertEqual(auth_store.count_readings(child, "2000-01-01T00:00:00+00:00"), 0)


class ReportDeliveryAtomicityTests(ApiTestCase):
    def test_report_share_does_not_leave_an_orphan_notice_if_outbox_insert_fails(self):
        child = self.signup()
        self.assertEqual(self.ingest(child).status_code, 200)
        self.doctor()
        with auth_store.connect() as db:
            db.execute("CREATE TRIGGER synthetic_outbox_failure BEFORE INSERT ON email_outbox BEGIN SELECT RAISE(ABORT, 'synthetic outbox failure'); END")
        response = self.client.post(f"/api/v1/children/{child}/report/latest/send")
        self.assertEqual(response.status_code, 500)
        self.assertEqual(self.client.get("/api/v1/alerts").json(), [], "Failed delivery-job creation must roll back its notice and PDF too")
        with auth_store.connect() as db:
            db.execute("DROP TRIGGER synthetic_outbox_failure")
        retried = self.client.post(f"/api/v1/children/{child}/report/latest/send")
        self.assertEqual(retried.status_code, 200, retried.text)
        self.assertEqual(len(self.client.get("/api/v1/alerts").json()), 1)
        self.assertEqual(self.client.get(f"/api/v1/alerts/{retried.json()['alert_id']}/pdf").status_code, 200)


class DeliveryCompletionRaceTests(ApiTestCase):
    def test_late_failure_cannot_requeue_a_notice_already_delivered_by_new_worker(self):
        with patch.object(auth_store.time, "time", return_value=1000):
            alert_id = auth_store.add_alert("child_01", "synthetic-parent", "Synthetic", "Warning", "Synthetic notice", "Synthetic text", "queued")
            auth_store.enqueue_alert_email(alert_id, "parent@example.invalid", "Synthetic notice", "Synthetic text")
            self.assertEqual(auth_store.pending_alert_emails()[0]["alert_id"], alert_id)
        # A second worker acquires the expired lease and succeeds. The original
        # worker's failure then arrives late and must not undo that success.
        with patch.object(auth_store.time, "time", return_value=1121):
            self.assertEqual(auth_store.pending_alert_emails()[0]["alert_id"], alert_id)
            self.assertTrue(auth_store.complete_alert_email(alert_id, "sent"))
            self.assertFalse(auth_store.complete_alert_email(alert_id, "failed"))
        alert = auth_store.get_alert(alert_id)
        self.assertEqual(alert["email_status"], "sent")
        self.assertEqual(alert["delivery_attempts"], 1)
        with patch.object(auth_store.time, "time", return_value=5000):
            self.assertEqual(auth_store.pending_alert_emails(), [])
