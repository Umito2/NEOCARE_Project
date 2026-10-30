"""Offline integration coverage for history, care workflow and shared screening."""

import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import api
import assessment
import auth_store
from tests.support import ApiTestCase, THRESHOLDS


class SharedAssessmentTests(unittest.TestCase):
    def test_active_existing_adjustments_apply_to_both_age_groups(self):
        for age, hr_max, rr_max in ((3, 155, 46), (4, 140, 38)):
            with self.subTest(age=age):
                normal = assessment.analyze_vitals(age, hr_max, 98, 37, rr_max, "Active")
                self.assertEqual(normal["risk_status"], "Normal")
                self.assertEqual(assessment.analyze_vitals(age, hr_max + 1, 98, 37, rr_max, "Active")["risk_status"], "Warning")
                self.assertEqual(assessment.analyze_vitals(age, hr_max, 98, 37, rr_max + 1, "Active")["risk_status"], "Warning")

    def test_configured_oxygen_limit_controls_classification_and_safety_together(self):
        normal = assessment.analyze_vitals(4, 100, 94, 37, 20, "Resting")
        critical = assessment.analyze_vitals(4, 100, 94, 37, 20, "Resting", THRESHOLDS)
        self.assertEqual(normal["risk_status"], "Normal")
        self.assertEqual(critical["risk_status"], "Critical")
        self.assertTrue(critical["safety_recommendations"])

    def test_missing_context_never_clears_a_measured_critical_alarm(self):
        result = assessment.analyze_vitals(4, 100, 90, 37, None, None)
        self.assertEqual(result["risk_status"], "Critical")
        self.assertEqual(assessment.analyze_vitals(4, 100, 98, 37, None, None)["risk_status"], "Incomplete reading")


class FreshnessAndHistoryTests(ApiTestCase):
    def test_timestamp_data_quality_blocks_dashboard_normal_and_report_generation(self):
        child = self.signup()
        self.assertEqual(self.ingest(child).status_code, 200)
        baseline = self.reading_ref(child).get()
        timestamps = {
            "stale": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
            "missing": None,
            "invalid": "not-a-time",
            "future": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
            "naive": datetime.now().isoformat(),
        }
        for label, timestamp in timestamps.items():
            with self.subTest(label=label):
                self.reading_ref(child).set({**baseline, "timestamp": timestamp})
                latest = self.client.get(f"/api/v1/children/{child}/readings/latest").json()
                self.assertNotEqual(latest["freshness"]["status"], "fresh")
                self.assertNotEqual(self.client.get("/api/v1/children").json()[0]["risk_status"], "Normal")
                self.assertEqual(self.client.get(f"/api/v1/children/{child}/report/latest").status_code, 409)
        self.ai_client.assert_not_called()

    def test_freshness_limit_is_configurable_without_changing_measurements(self):
        child = self.signup()
        self.ingest(child)
        original = self.reading_ref(child).get()
        original["timestamp"] = (datetime.now(timezone.utc) - timedelta(seconds=100)).isoformat()
        self.reading_ref(child).set(original)
        with patch.dict(os.environ, {"NEOCARE_READING_MAX_AGE_SECONDS": "60"}):
            stale = self.client.get(f"/api/v1/children/{child}/readings/latest").json()
        self.assertEqual(stale["freshness"]["status"], "stale")
        self.assertEqual(stale["heart_rate_bpm"], original["heart_rate_bpm"])

    def test_malformed_stored_measurements_do_not_produce_normal_or_a_report(self):
        child = self.signup()
        self.ingest(child)
        original = self.reading_ref(child).get()
        for value in ("invalid", 150, None):
            with self.subTest(spo2=value):
                self.reading_ref(child).set({**original, "spo2_percent": value})
                self.assertNotEqual(self.client.get("/api/v1/children").json()[0]["risk_status"], "Normal")
                self.assertEqual(self.client.get(f"/api/v1/children/{child}/report/latest").status_code, 409)

    def test_history_accumulates_real_sensor_values_in_time_order(self):
        child = self.signup()
        for rate in (90, 100, 105):
            self.assertEqual(self.ingest(child, heart_rate_bpm=rate).status_code, 200)
        history = self.client.get(f"/api/v1/children/{child}/readings/history?period=24h")
        self.assertEqual(history.status_code, 200, history.text)
        data = history.json()
        self.assertEqual([row["heart_rate_bpm"] for row in data["readings"]], [90, 100, 105])
        self.assertEqual(data["total_count"], 3)
        self.assertFalse(data["sampled"])
        self.assertTrue(all("child_name" not in row for row in data["readings"]))
        self.assertEqual(self.client.get(f"/api/v1/children/{child}/readings/latest").json()["heart_rate_bpm"], 105)

    def test_history_windows_and_permissions_are_enforced(self):
        child = self.signup()
        now = datetime.now(timezone.utc)
        for days in (8, 3, 0):
            auth_store.record_reading(child, {"timestamp": (now - timedelta(days=days)).isoformat(), "heart_rate_bpm": 90 + days})
        self.assertEqual(len(self.client.get(f"/api/v1/children/{child}/readings/history?period=24h").json()["readings"]), 1)
        self.assertEqual(len(self.client.get(f"/api/v1/children/{child}/readings/history?period=7d").json()["readings"]), 2)
        self.assertEqual(self.client.get(f"/api/v1/children/{child}/readings/history?period=all").status_code, 422)
        stranger = self.new_client()
        self.assertEqual(stranger.get(f"/api/v1/children/{child}/readings/history").status_code, 401)
        self.signup(stranger, email="other@example.invalid")
        self.assertEqual(stranger.get(f"/api/v1/children/{child}/readings/history").status_code, 404)
        self.doctor(stranger)
        self.assertEqual(stranger.get(f"/api/v1/children/{child}/readings/history").status_code, 200)

    def test_deleted_profile_id_is_not_reused_for_unrelated_history(self):
        child = self.signup()
        self.ingest(child)
        doctor = self.new_client()
        self.doctor(doctor)
        self.assertEqual(doctor.delete(f"/api/v1/children/{child}").status_code, 200)
        self.reading_ref(child).delete()
        next_child = self.signup(self.new_client(), email="second@example.invalid")
        self.assertNotEqual(next_child, child)

    def test_dashboard_report_alert_severity_share_active_and_respiratory_rules(self):
        child = self.signup()
        self.thresholds()
        for changes in ({"heart_rate_bpm": 141, "activity": "Active"}, {"resp_rate": 27}, {"spo2_percent": 94}):
            with self.subTest(changes=changes), patch.object(api, "send_email_message", return_value="sent"):
                self.ingest(child)
                self.assertEqual(self.ingest(child, **changes).status_code, 200)
                dashboard = self.client.get("/api/v1/children").json()[0]
                report = self.client.get(f"/api/v1/children/{child}/report/latest").json()
                alert = self.client.get("/api/v1/alerts").json()[0]
                self.assertEqual(dashboard["risk_status"], report["risk_status"])
                self.assertEqual(alert["severity"], report["risk_status"])


class DoctorAndWorkflowTests(ApiTestCase):
    def create_named_doctor(self, **changes):
        payload = {"username": "dr.smith", "display_name": "Doctor Smith", "password": "individual-test-password"}
        payload.update(changes)
        response = self.client.post("/api/v1/doctor/accounts", json=payload)
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["doctor_id"]

    def test_named_clinician_signs_in_and_has_attributable_audit(self):
        self.doctor()
        doctor_id = self.create_named_doctor()
        clinician = self.new_client()
        response = clinician.post("/api/v1/auth/login", json={"role": "doctor", "identifier": "DR.SMITH", "password": "individual-test-password"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(clinician.get("/api/v1/auth/me").json()["display_name"], "Doctor Smith")
        self.assertEqual(clinician.put("/api/v1/doctor/alert-thresholds", json=THRESHOLDS).status_code, 200)
        events = clinician.get("/api/v1/doctor/audit").json()["events"]
        event = next(event for event in events if event["action"] == "thresholds.updated")
        self.assertEqual(event["actor_id"], doctor_id)
        self.assertNotIn("individual-test-password", str(events))
        accounts = clinician.get("/api/v1/doctor/accounts").json()["doctors"]
        self.assertEqual(accounts[0]["doctor_id"], doctor_id)
        self.assertFalse(any("password" in key or "salt" in key for key in accounts[0]))

    def test_individual_account_overrides_shared_password_for_same_username(self):
        self.doctor()
        self.create_named_doctor(username="test-clinic")
        other = self.new_client()
        rejected = other.post("/api/v1/auth/login", json={"role": "doctor", "identifier": "test-clinic", "password": "test-clinic-password-only"})
        self.assertEqual(rejected.status_code, 401)
        accepted = other.post("/api/v1/auth/login", json={"role": "doctor", "identifier": "test-clinic", "password": "individual-test-password"})
        self.assertEqual(accepted.status_code, 200)

    def test_unicode_configured_credentials_are_compared_safely(self):
        with patch.dict(os.environ, {"DOCTOR_USERNAME": "طبيب", "DOCTOR_PASSWORD": "كلمة-مرور-طويلة"}):
            response = self.client.post("/api/v1/auth/login", json={"role": "doctor", "identifier": "طبيب", "password": "كلمة-مرور-طويلة"})
        self.assertEqual(response.status_code, 200, response.text)

    def test_account_validation_duplicate_and_authorization(self):
        self.signup()
        for route in ("/api/v1/doctor/accounts", "/api/v1/doctor/audit"):
            self.assertEqual(self.client.get(route).status_code, 403)
        payload = {"username": "dr.smith", "display_name": "Doctor Smith", "password": "individual-test-password"}
        self.assertEqual(self.client.post("/api/v1/doctor/accounts", json=payload).status_code, 403)
        self.doctor()
        self.create_named_doctor()
        self.assertEqual(self.client.post("/api/v1/doctor/accounts", json={**payload, "username": "DR.SMITH"}).status_code, 409)
        for changes in ({"password": "short"}, {"display_name": "  "}, {"username": "bad/name"}):
            self.assertEqual(self.client.post("/api/v1/doctor/accounts", json={**payload, **changes}).status_code, 422)

    def make_alert(self):
        child = self.signup()
        self.thresholds()
        self.assertEqual(self.ingest(child, spo2_percent=90).status_code, 200)
        return self.client.get("/api/v1/alerts").json()[0]["alert_id"]

    def test_doctor_acknowledges_resolves_and_notes_are_private_to_clinicians(self):
        alert_id = self.make_alert()
        parent = self.client
        doctor = self.new_client()
        self.doctor(doctor)
        url = f"/api/v1/alerts/{alert_id}"
        response = doctor.patch(url, json={"workflow_status": "acknowledged", "note": "Synthetic clinician-only note"})
        self.assertEqual(response.status_code, 200, response.text)
        alert = doctor.get("/api/v1/alerts").json()[0]
        self.assertEqual(alert["workflow_status"], "acknowledged")
        self.assertEqual(alert["notes"][0]["text"], "Synthetic clinician-only note")
        self.assertEqual(alert["notes"][0]["actor_id"], "test-clinic")
        self.assertNotIn("Synthetic clinician-only note", parent.get("/api/v1/alerts").text)
        self.assertEqual(doctor.patch(url, json={"workflow_status": "resolved"}).status_code, 200)
        self.assertEqual(parent.get("/api/v1/alerts").json()[0]["workflow_status"], "resolved")
        events = doctor.get("/api/v1/doctor/audit").json()["events"]
        self.assertTrue(any(event["action"] == "alert.note_added" for event in events))
        self.assertNotIn("Synthetic clinician-only note", str(events))

    def test_alert_update_validates_and_denies_parents_and_anonymous_users(self):
        alert_id = self.make_alert()
        url = f"/api/v1/alerts/{alert_id}"
        self.assertEqual(self.client.patch(url, json={"workflow_status": "resolved"}).status_code, 403)
        anonymous = self.new_client()
        self.assertEqual(anonymous.patch(url, json={"workflow_status": "resolved"}).status_code, 401)
        self.doctor(anonymous)
        for body in ({}, {"note": "   "}, {"workflow_status": "unknown"}, {"note": "x" * 2001}):
            self.assertEqual(anonymous.patch(url, json=body).status_code, 422)
        self.assertEqual(anonymous.patch("/api/v1/alerts/999", json={"workflow_status": "resolved"}).status_code, 404)

    def test_alert_deletion_is_audited_without_retaining_note_content(self):
        alert_id = self.make_alert()
        self.doctor()
        self.assertEqual(self.client.delete(f"/api/v1/alerts/{alert_id}").status_code, 200)
        events = self.client.get("/api/v1/doctor/audit").json()["events"]
        event = next(event for event in events if event["action"] == "alert.deleted")
        self.assertEqual(event["target"], str(alert_id))


class NotificationRetryTests(ApiTestCase):
    def test_slow_batch_claims_each_notice_only_when_it_can_send(self):
        now = [1000]
        alert_ids = []
        with patch.object(auth_store.time, "time", side_effect=lambda: now[0]):
            for number in range(3):
                alert_id = auth_store.add_alert("child_01", "synthetic-parent", "Synthetic", "Warning", "Synthetic notice", "Synthetic text", "queued")
                alert_ids.append(alert_id)
                auth_store.enqueue_alert_email(alert_id, "parent@example.invalid", "Synthetic notice", "Synthetic text")
            claimed = []
            real_claim = auth_store.pending_alert_emails

            def claim(*args, **kwargs):
                rows = real_claim(*args, **kwargs)
                for row in rows:
                    claimed.append((row["alert_id"], now[0]))
                return rows

            def slow_send(_message):
                # Cumulative elapsed time exceeds the120s lease before third
                # message; that third notice must still be unclaimed until now.
                now[0] += 70
                return "sent"

            with patch.object(auth_store, "pending_alert_emails", side_effect=claim), patch.object(api, "send_email_message", side_effect=slow_send):
                results = api.deliver_pending_alert_emails()
        self.assertEqual(results, dict.fromkeys(alert_ids, "sent"))
        self.assertEqual(claimed, list(zip(alert_ids, (1000, 1070, 1140))))

    def test_failed_notice_is_attempted_once_per_batch_without_leasing_it_again(self):
        with patch.object(auth_store.time, "time", return_value=1000):
            alert_id = auth_store.add_alert("child_01", "synthetic-parent", "Synthetic", "Warning", "Synthetic notice", "Synthetic text", "queued")
            auth_store.enqueue_alert_email(alert_id, "parent@example.invalid", "Synthetic notice", "Synthetic text")
            with patch.object(api, "send_email_message", side_effect=OSError("synthetic outage")) as send:
                self.assertEqual(api.deliver_pending_alert_emails(), {alert_id: "failed"})
                send.assert_called_once()
            # The immediate retry remains available for a later worker/request;
            # the just-finished batch did not claim and abandon its lease.
            self.assertEqual(auth_store.pending_alert_emails()[0]["alert_id"], alert_id)

    def test_failed_notice_can_retry_without_another_sensor_reading(self):
        child = self.signup()
        self.thresholds()
        with patch.object(api, "send_email_message", side_effect=[OSError("synthetic outage"), "sent"]) as send:
            first = self.ingest(child, temperature_c=38.5)
            self.assertEqual(first.json()["notification_status"], "failed")
            self.assertEqual(list(api.deliver_pending_alert_emails().values()), ["sent"])
            self.assertEqual(send.call_count, 2)
        alerts = self.client.get("/api/v1/alerts").json()
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["email_status"], "sent")
        self.assertEqual(alerts[0]["delivery_attempts"], 2)

    def test_background_retry_worker_processes_due_queue_without_real_sleep(self):
        class Stop:
            waits = 0
            def wait(self, seconds):
                self.waits += 1
                return self.waits > 1
        with patch.object(api, "deliver_pending_alert_emails") as deliver:
            api.retry_email_worker(Stop())
        deliver.assert_called_once_with()

    def test_deleted_alert_cannot_be_delivered_by_retry_queue(self):
        child = self.signup()
        self.thresholds()
        with patch.object(api, "send_email_message", side_effect=OSError("synthetic outage")):
            self.ingest(child, temperature_c=38.5)
        alert_id = self.client.get("/api/v1/alerts").json()[0]["alert_id"]
        self.doctor()
        self.client.delete(f"/api/v1/alerts/{alert_id}")
        with patch.object(api, "send_email_message") as send:
            self.assertEqual(api.deliver_pending_alert_emails(), {})
        send.assert_not_called()
