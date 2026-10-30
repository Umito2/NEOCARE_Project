"""HTTP integration tests, including failing regressions for observed defects.

Threshold numbers here are fixture values copied from the existing application;
passing these tests does not establish medical validity.
"""

import os
from unittest.mock import patch

import api
import auth_store
from tests.support import ApiTestCase, THRESHOLDS


class AuthenticationTests(ApiTestCase):
    def test_health_and_dashboard_serve(self):
        self.assertEqual(self.client.get("/health").json(), {"status": "ok"})
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("NEOCARE", response.text)
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.firebase_init.assert_called_once()

    def test_protected_routes_require_login(self):
        for method, url in [
            ("GET", "/api/v1/auth/me"), ("GET", "/api/v1/children"),
            ("GET", "/api/v1/children/child_01/readings/latest"),
            ("GET", "/api/v1/children/child_01/report/latest"),
            ("GET", "/api/v1/children/child_01/report/latest/pdf"),
            ("POST", "/api/v1/children/child_01/report/latest/send"),
            ("DELETE", "/api/v1/children/child_01"),
            ("GET", "/api/v1/alerts"), ("GET", "/api/v1/alerts/1/pdf"),
            ("GET", "/api/v1/doctor/alert-thresholds"),
        ]:
            with self.subTest(url=url):
                self.assertEqual(self.client.request(method, url).status_code, 401)

    def test_signup_cookie_login_logout(self):
        child = self.signup(email="  Parent@Example.invalid  ")
        self.assertEqual(child, "child_01")
        self.assertEqual(self.client.get("/api/v1/auth/me").json()["role"], "parent")
        cookie = next(iter(self.client.cookies.jar))
        self.assertTrue(cookie.secure)
        self.assertIn("HttpOnly", cookie._rest)
        self.assertEqual(cookie._rest["SameSite"], "lax")
        self.assertEqual(self.client.post("/api/v1/auth/logout").status_code, 200)
        self.assertEqual(self.client.get("/api/v1/auth/me").status_code, 401)
        response = self.client.post("/api/v1/auth/login", json={
            "role": "parent", "identifier": "PARENT@example.invalid",
            "password": "test-parent-password-only",
        })
        self.assertEqual(response.status_code, 200, response.text)

    def test_duplicate_signup_rolls_back_extra_firebase_profile(self):
        child = self.signup()
        response = self.client.post("/api/v1/auth/signup", json={
            "parent_name": "Duplicate", "email": "PARENT@example.invalid",
            "phone": "0000000000", "password": "test-parent-password-only",
            "child_name": "Duplicate Child", "age_years": 4, "height_cm": 100, "weight_kg": 16,
        })
        self.assertEqual(response.status_code, 409)
        self.assertEqual(list(self.reference("neocare_system/children_profiles").get()), [child])

    def test_invalid_signup_payloads_rejected(self):
        payload = {
            "parent_name": "Test", "email": "test@example.invalid", "phone": "0000000000",
            "password": "test-parent-password-only", "child_name": "Test",
            "age_years": 4, "height_cm": 100, "weight_kg": 16,
        }
        for change in [{"email": "invalid"}, {"password": "short"}, {"age_years": 0},
                       {"age_years": 19}, {"child_name": "  "}, {"parent_name": "  "},
                       {"weight_kg": -1}, {"unknown": "field"}]:
            with self.subTest(change=change):
                self.assertEqual(self.client.post("/api/v1/auth/signup", json={**payload, **change}).status_code, 422)
        self.assertIsNone(self.reference("neocare_system/children_profiles").get())

    def test_wrong_credentials_are_rejected(self):
        self.signup()
        for role, identifier in [("parent", "parent@example.invalid"), ("parent", "missing@example.invalid"),
                                 ("doctor", "test-clinic")]:
            with self.subTest(role=role, identifier=identifier):
                response = self.client.post("/api/v1/auth/login", json={
                    "role": role, "identifier": identifier, "password": "wrong-password",
                })
                self.assertEqual(response.status_code, 401)

    def test_unconfigured_doctor_reports_503(self):
        with patch.dict(os.environ, {"DOCTOR_PASSWORD": ""}):
            response = self.client.post("/api/v1/auth/login", json={
                "role": "doctor", "identifier": "test-clinic", "password": "wrong",
            })
        self.assertEqual(response.status_code, 503)

    def test_default_doctor_credentials_create_authenticated_session_when_env_absent(self):
        with patch.dict(os.environ, {}, clear=True):
            rejected = self.client.post("/api/v1/auth/login", json={
                "role": "doctor", "identifier": "NEOCARE", "password": "wrong-password",
            })
            self.assertEqual(rejected.status_code, 401)
            self.assertEqual(self.client.get("/api/v1/auth/me").status_code, 401)

            response = self.client.post("/api/v1/auth/login", json={
                "role": "doctor", "identifier": "NEOCARE", "password": "123456789",
            })
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json(), {"role": "doctor", "display_name": "Clinic"})
            token = self.client.cookies.get("neocare_session")
            self.assertTrue(token)
            session = auth_store.get_session(token)
            self.assertEqual(session["role"], "doctor")
            self.assertEqual(session["user_id"], "NEOCARE")
            me = self.client.get("/api/v1/auth/me")
            self.assertEqual(me.status_code, 200)
            self.assertEqual(me.json(), {"role": "doctor", "display_name": "Clinic"})
            self.assertEqual(self.client.get("/api/v1/doctor/alert-thresholds").status_code, 200)

    def test_custom_doctor_credentials_override_both_defaults(self):
        with patch.dict(os.environ, {
            "DOCTOR_USERNAME": "custom-clinic",
            "DOCTOR_PASSWORD": "custom-clinic-password-only",
        }):
            for identifier, password in [
                ("NEOCARE", "123456789"),
                ("NEOCARE", "custom-clinic-password-only"),
                ("custom-clinic", "123456789"),
            ]:
                with self.subTest(identifier=identifier, password=password):
                    response = self.client.post("/api/v1/auth/login", json={
                        "role": "doctor", "identifier": identifier, "password": password,
                    })
                    self.assertEqual(response.status_code, 401)
                    self.assertIsNone(self.client.cookies.get("neocare_session"))

            response = self.client.post("/api/v1/auth/login", json={
                "role": "doctor", "identifier": "custom-clinic",
                "password": "custom-clinic-password-only",
            })
            self.assertEqual(response.status_code, 200, response.text)
            session = auth_store.get_session(self.client.cookies.get("neocare_session"))
            self.assertEqual(session["user_id"], "custom-clinic")
            me = self.client.get("/api/v1/auth/me")
            self.assertEqual(me.status_code, 200)
            self.assertEqual(me.json(), {"role": "doctor", "display_name": "Clinic"})

    def test_unicode_wrong_doctor_credentials_do_not_crash(self):
        response = self.client.post("/api/v1/auth/login", json={
            "role": "doctor", "identifier": "عيادة", "password": "wrong-password",
        })
        self.assertEqual(response.status_code, 401, "Non-ASCII credentials should be rejected without HTTP 500")

    def test_expired_session_is_rejected(self):
        self.signup()
        with auth_store.connect() as database:
            database.execute("UPDATE sessions SET expires_at=0")
        self.assertEqual(self.client.get("/api/v1/auth/me").status_code, 401)


class ProfilePermissionTests(ApiTestCase):
    def test_parent_cannot_access_another_parents_child(self):
        own = self.signup()
        other_client = self.new_client()
        other = self.signup(other_client, email="other@example.invalid")
        visible = self.client.get("/api/v1/children").json()
        self.assertEqual([row["child_id"] for row in visible], [own])
        for key in ("owner_parent_id", "parent_id", "parent_email", "parent_phone"):
            self.assertNotIn(key, visible[0])
        for suffix in ("readings/latest", "report/latest", "report/latest/pdf"):
            self.assertEqual(self.client.get(f"/api/v1/children/{other}/{suffix}").status_code, 404)
        response = self.client.put(f"/api/v1/children/{other}", json={
            "name": "Changed", "age_years": 5, "height_cm": 110, "weight_kg": 20,
        })
        self.assertEqual(response.status_code, 404)

    def test_parent_can_create_and_update_own_child(self):
        self.signup()
        payload = {"name": "Second Child", "age_years": 5, "height_cm": 110, "weight_kg": 20}
        response = self.client.post("/api/v1/children", json=payload)
        self.assertEqual(response.status_code, 201, response.text)
        child = response.json()["child_id"]
        owner = self.profile_ref(child).get()["owner_parent_id"]
        response = self.client.put(f"/api/v1/children/{child}", json={**payload, "name": " Edited "})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.profile_ref(child).get()["name"], "Edited")
        self.assertEqual(self.profile_ref(child).get()["owner_parent_id"], owner)

    def test_parent_cannot_delete_send_report_or_manage_thresholds(self):
        child = self.signup()
        self.assertEqual(self.client.delete(f"/api/v1/children/{child}").status_code, 403)
        self.assertEqual(self.client.post(f"/api/v1/children/{child}/report/latest/send").status_code, 403)
        self.assertEqual(self.client.get("/api/v1/doctor/alert-thresholds").status_code, 403)
        self.assertEqual(self.client.put("/api/v1/doctor/alert-thresholds", json=THRESHOLDS).status_code, 403)

    def test_doctor_can_view_update_and_delete_child(self):
        child = self.signup()
        self.doctor()
        self.assertEqual(len(self.client.get("/api/v1/children").json()), 1)
        response = self.client.put(f"/api/v1/children/{child}", json={
            "name": "Clinic Updated", "age_years": 5, "height_cm": 110, "weight_kg": 20,
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.delete(f"/api/v1/children/{child}").status_code, 200)
        self.assertIsNone(self.profile_ref(child).get())

    def test_invalid_child_id_rejected(self):
        self.signup()
        self.assertEqual(self.client.get("/api/v1/children/not-a-child/readings/latest").status_code, 422)

    def test_blank_profile_name_rejected(self):
        child = self.signup()
        payload = {"name": "   ", "age_years": 5, "height_cm": 110, "weight_kg": 20}
        self.assertEqual(self.client.put(f"/api/v1/children/{child}", json=payload).status_code, 422)
        self.assertEqual(self.client.post("/api/v1/children", json=payload).status_code, 422)

    def test_child_id_capacity_is_reported(self):
        self.signup()
        for number in range(2, 100):
            self.profile_ref(f"child_{number:02d}").set({"name": "Fixture"})
        response = self.client.post("/api/v1/children", json={
            "name": "Overflow", "age_years": 5, "height_cm": 110, "weight_kg": 20,
        })
        self.assertEqual(response.status_code, 409)


class SensorAndThresholdTests(ApiTestCase):
    def test_valid_reading_is_saved_and_retrieved(self):
        child = self.signup()
        response = self.ingest(child)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["notification_status"], "thresholds_not_configured")
        reading = self.client.get(f"/api/v1/children/{child}/readings/latest").json()
        self.assertEqual(reading["status"], "available")
        self.assertEqual(reading["heart_rate_bpm"], 100)
        self.assertEqual(reading["respiratory_rate_br_min"], 20)
        self.assertIn("timestamp", reading)

    def test_reading_requires_device_key(self):
        child = self.signup()
        payload = {"child_id": child, "heart_rate_bpm": 100, "spo2_percent": 98, "temperature_c": 37}
        for headers in ({}, {"X-API-Key": "wrong"}):
            self.assertEqual(self.client.post("/api/v1/readings", json=payload, headers=headers).status_code, 401)
        self.assertIsNone(self.reading_ref(child).get())

    def test_unconfigured_device_key_returns_503(self):
        child = self.signup()
        with patch.dict(os.environ, {"ESP32_API_KEY": ""}):
            self.assertEqual(self.ingest(child).status_code, 503)

    def test_unknown_child_reading_rejected(self):
        self.assertEqual(self.ingest("child_99").status_code, 404)

    def test_invalid_reading_values_rejected(self):
        child = self.signup()
        for changes in ({"heart_rate_bpm": 0}, {"heart_rate_bpm": 251}, {"spo2_percent": -1},
                        {"spo2_percent": 101}, {"temperature_c": 46}, {"resp_rate": 0},
                        {"activity": "Running"}, {"unexpected": 1}):
            with self.subTest(changes=changes):
                self.assertEqual(self.ingest(child, **changes).status_code, 422)
        self.assertIsNone(self.reading_ref(child).get())

    def test_missing_optional_fields_are_marked_incomplete(self):
        child = self.signup()
        self.thresholds()
        response = self.ingest(child, activity=None, resp_rate=None)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["notification_status"], "incomplete_reading_no_alert")
        self.assertEqual(self.client.get("/api/v1/children").json()[0]["risk_status"], "Incomplete reading")
        self.assertEqual(self.client.get(f"/api/v1/children/{child}/report/latest").status_code, 409)

    def test_child_without_readings_waits(self):
        child = self.signup()
        self.assertEqual(self.client.get(f"/api/v1/children/{child}/readings/latest").json()["status"], "waiting")
        self.assertEqual(self.client.get("/api/v1/children").json()[0]["risk_status"], "Waiting for readings")
        self.assertEqual(self.client.get(f"/api/v1/children/{child}/report/latest").status_code, 409)

    def test_thresholds_can_be_saved_and_invalid_order_rejected(self):
        self.doctor()
        response = self.client.put("/api/v1/doctor/alert-thresholds", json=THRESHOLDS)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get("/api/v1/doctor/alert-thresholds").json()["thresholds"], THRESHOLDS)
        invalid = {**THRESHOLDS, "temperature_warning_c": 40}
        self.assertEqual(self.client.put("/api/v1/doctor/alert-thresholds", json=invalid).status_code, 422)
        self.assertEqual(auth_store.get_thresholds(), THRESHOLDS)

    def test_stale_reading_is_not_presented_as_current_normal(self):
        child = self.signup()
        self.thresholds()
        self.assertEqual(self.ingest(child).status_code, 200)
        reading = self.reading_ref(child).get()
        reading["timestamp"] = "2000-01-01T00:00:00+00:00"
        self.reading_ref(child).set(reading)
        status = self.client.get("/api/v1/children").json()[0]["risk_status"]
        self.assertNotEqual(status, "Normal", "A decades-old reading needs a stale/offline state")


class AlertAndReportTests(ApiTestCase):
    def test_new_child_threshold_crossing_stores_alert_without_crashing(self):
        child = self.signup()
        self.thresholds()
        response = self.ingest(child, spo2_percent=90)
        self.assertEqual(response.status_code, 200, "Alert creation for a normal signup must not return HTTP 500")
        self.assertEqual(len(self.client.get("/api/v1/alerts").json()), 1)

    def test_alert_episode_deduplication_and_recovery(self):
        child = self.signup()
        self.thresholds()
        # Legacy fixture includes child_id to isolate episode behavior from the
        # separately tested signup-profile/alert formatting defect.
        self.profile_ref(child).set({**self.profile_ref(child).get(), "child_id": child})
        with patch.object(api, "send_email_message", return_value="sent") as email:
            first = self.ingest(child, temperature_c=38.5)
            self.assertEqual(first.status_code, 200)
            self.assertEqual(first.json()["notification_status"], "sent")
            self.assertEqual(self.ingest(child, temperature_c=38.5).json()["notification_status"], "same_episode_no_repeat")
            self.assertEqual(self.ingest(child, temperature_c=39.5).json()["notification_status"], "sent")
            self.assertEqual(self.ingest(child).json()["notification_status"], "recovered")
            self.assertEqual(self.ingest(child, temperature_c=38.5).json()["notification_status"], "sent")
            self.assertEqual(email.call_count, 3)
        self.assertEqual(len(self.client.get("/api/v1/alerts").json()), 3)

    def test_failed_alert_delivery_is_retried_on_next_reading(self):
        child = self.signup()
        self.thresholds()
        self.profile_ref(child).set({**self.profile_ref(child).get(), "child_id": child})
        with patch.object(api, "send_email_message", side_effect=[OSError("Test SMTP outage"), "sent"]) as email:
            self.assertEqual(self.ingest(child, temperature_c=38.5).json()["notification_status"], "failed")
            self.assertEqual(self.ingest(child, temperature_c=38.5).status_code, 200)
            self.assertEqual(email.call_count, 2, "A failed delivery must not be suppressed as already notified")

    def test_report_and_dashboard_use_same_clinic_thresholds(self):
        child = self.signup()
        self.assertEqual(self.ingest(child, spo2_percent=94).status_code, 200)
        self.thresholds()
        dashboard = self.client.get("/api/v1/children").json()[0]
        report = self.client.get(f"/api/v1/children/{child}/report/latest")
        self.assertEqual(report.status_code, 200, report.text)
        self.assertEqual(report.json()["risk_status"], dashboard["risk_status"],
                         "Same child and reading must use the same configured assessment rules")

    def test_report_falls_back_when_local_ai_unavailable(self):
        child = self.signup()
        self.assertEqual(self.ingest(child).status_code, 200)
        response = self.client.get(f"/api/v1/children/{child}/report/latest")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["recommendation_source"], "Rule-based fallback")
        self.assertTrue(response.json()["recommendations"])
        self.assertEqual(response.json()["child_id"], child)

    def test_critical_report_provides_safety_guidance_without_waiting_for_ai(self):
        child = self.signup()
        self.assertEqual(self.ingest(child, spo2_percent=90).status_code, 200)
        report = self.client.get(f"/api/v1/children/{child}/report/latest").json()
        self.assertEqual(report["risk_status"], "Critical")
        self.assertTrue(report["safety_recommendations"])
        self.assertEqual(report["recommendation_source"], "Rule-based safety guidance")
        self.assertIn("without waiting for AI", report["recommendation_notice"])
        self.ai_client.assert_not_called()

    def test_pdf_download_returns_valid_pdf(self):
        child = self.signup()
        self.assertEqual(self.ingest(child).status_code, 200)
        response = self.client.get(f"/api/v1/children/{child}/report/latest/pdf")
        self.assertEqual(response.status_code, 200, response.text[:100])
        self.assertEqual(response.headers["content-type"], "application/pdf")
        self.assertTrue(response.content.startswith(b"%PDF-"))
        self.assertIn(b"%%EOF", response.content[-100:])
        self.assertEqual(response.headers["cache-control"], "no-store")

    def test_clinic_shares_saved_pdf_only_with_owner(self):
        child = self.signup()
        self.assertEqual(self.ingest(child).status_code, 200)
        other = self.new_client()
        self.signup(other, email="other@example.invalid")
        doctor = self.new_client()
        self.doctor(doctor)
        response = doctor.post(f"/api/v1/children/{child}/report/latest/send")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["email_status"], "not_configured")
        alert_id = response.json()["alert_id"]
        self.assertEqual(len(self.client.get("/api/v1/alerts").json()), 1)
        self.assertEqual(other.get("/api/v1/alerts").json(), [])
        pdf_url = f"/api/v1/alerts/{alert_id}/pdf"
        self.assertTrue(self.client.get(pdf_url).content.startswith(b"%PDF-"))
        self.assertEqual(other.get(pdf_url).status_code, 404)
        self.assertEqual(doctor.get(pdf_url).status_code, 200)

    def test_report_email_failure_still_preserves_parent_pdf(self):
        child = self.signup()
        self.assertEqual(self.ingest(child).status_code, 200)
        self.doctor()
        with patch.object(api, "send_email_message", side_effect=OSError("Test SMTP outage")):
            response = self.client.post(f"/api/v1/children/{child}/report/latest/send")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["email_status"], "failed")
        alert_id = response.json()["alert_id"]
        self.assertEqual(self.client.get(f"/api/v1/alerts/{alert_id}/pdf").status_code, 200)

    def test_report_send_requires_parent_email(self):
        child = self.signup()
        self.assertEqual(self.ingest(child).status_code, 200)
        profile = self.profile_ref(child).get()
        profile.pop("parent_email")
        self.profile_ref(child).set(profile)
        self.doctor()
        self.assertEqual(self.client.post(f"/api/v1/children/{child}/report/latest/send").status_code, 409)

    def test_unknown_alert_pdf_is_not_found(self):
        self.signup()
        self.assertEqual(self.client.get("/api/v1/alerts/999/pdf").status_code, 404)
