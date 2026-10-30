"""Doctor alert deletion against real handlers and isolated SQLite storage."""

import auth_store
from tests.support import ApiTestCase


class AlertDeletionTests(ApiTestCase):
    def add_alert(self, child_id="child_01", parent_id="parent-a", pdf_data=None):
        return auth_store.add_alert(
            child_id=child_id,
            parent_id=parent_id,
            child_name="Synthetic Child",
            severity="Warning",
            subject="Synthetic test alert",
            message="Synthetic test reading only",
            email_status="not_configured",
            pdf_data=pdf_data,
        )

    def test_doctor_deletes_alert_and_pdf_from_parent_history(self):
        child_id = self.signup()
        parent_id = self.profile_ref(child_id).get()["owner_parent_id"]
        pdf_data = b"%PDF-1.7\nSynthetic report\n%%EOF"
        alert_id = self.add_alert(child_id, parent_id, pdf_data)
        pdf_url = f"/api/v1/alerts/{alert_id}/pdf"
        self.assertEqual(self.client.get(pdf_url).content, pdf_data)
        self.assertEqual(
            [row["alert_id"] for row in self.client.get("/api/v1/alerts").json()],
            [alert_id],
        )

        doctor = self.new_client()
        self.doctor(doctor)
        response = doctor.delete(f"/api/v1/alerts/{alert_id}")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {"status": "deleted", "alert_id": alert_id})
        self.assertEqual(self.client.get("/api/v1/alerts").json(), [])
        self.assertEqual(doctor.get("/api/v1/alerts").json(), [])
        self.assertEqual(self.client.get(pdf_url).status_code, 404)
        self.assertEqual(doctor.get(pdf_url).status_code, 404)

    def test_deleting_one_alert_preserves_other_alerts_pdfs_and_episode_state(self):
        child_id = self.signup()
        parent_id = self.profile_ref(child_id).get()["owner_parent_id"]
        removed_id = self.add_alert(child_id, parent_id, b"removed-pdf")
        same_child_id = self.add_alert(child_id, parent_id, b"same-child-pdf")
        other_child_id = self.add_alert("child_02", "parent-b", b"other-child-pdf")
        auth_store.save_alert_severity(child_id, 2)
        auth_store.save_alert_severity("child_02", 1)

        doctor = self.new_client()
        self.doctor(doctor)
        self.assertEqual(doctor.delete(f"/api/v1/alerts/{removed_id}").status_code, 200)
        self.assertEqual(
            {row["alert_id"] for row in doctor.get("/api/v1/alerts").json()},
            {same_child_id, other_child_id},
        )
        self.assertEqual(
            [row["alert_id"] for row in self.client.get("/api/v1/alerts").json()],
            [same_child_id],
        )
        self.assertEqual(doctor.get(f"/api/v1/alerts/{same_child_id}/pdf").content, b"same-child-pdf")
        self.assertEqual(doctor.get(f"/api/v1/alerts/{other_child_id}/pdf").content, b"other-child-pdf")
        self.assertEqual(auth_store.get_alert_severity(child_id), 2)
        self.assertEqual(auth_store.get_alert_severity("child_02"), 1)

    def test_owner_and_unrelated_parent_cannot_delete_alert(self):
        child_id = self.signup()
        parent_id = self.profile_ref(child_id).get()["owner_parent_id"]
        alert_id = self.add_alert(child_id, parent_id, b"protected-pdf")
        other_parent = self.new_client()
        self.signup(other_parent, email="other@example.invalid")

        for label, client in (("owner", self.client), ("unrelated parent", other_parent)):
            with self.subTest(account=label):
                response = client.delete(f"/api/v1/alerts/{alert_id}")
                self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(
            [row["alert_id"] for row in self.client.get("/api/v1/alerts").json()],
            [alert_id],
        )
        self.assertEqual(self.client.get(f"/api/v1/alerts/{alert_id}/pdf").content, b"protected-pdf")

    def test_anonymous_delete_is_rejected_without_removing_alert(self):
        child_id = self.signup()
        parent_id = self.profile_ref(child_id).get()["owner_parent_id"]
        alert_id = self.add_alert(child_id, parent_id, b"protected-pdf")
        anonymous = self.new_client()
        response = anonymous.delete(f"/api/v1/alerts/{alert_id}")
        self.assertEqual(response.status_code, 401, response.text)
        self.assertEqual(
            [row["alert_id"] for row in self.client.get("/api/v1/alerts").json()],
            [alert_id],
        )
        self.assertEqual(self.client.get(f"/api/v1/alerts/{alert_id}/pdf").content, b"protected-pdf")

    def test_unknown_and_repeated_deletions_return_not_found(self):
        alert_id = self.add_alert(pdf_data=b"test-pdf")
        self.doctor()
        missing = self.client.delete(f"/api/v1/alerts/{alert_id + 1000}")
        self.assertEqual(missing.status_code, 404, missing.text)
        self.assertEqual(
            [row["alert_id"] for row in self.client.get("/api/v1/alerts").json()],
            [alert_id],
        )
        self.assertEqual(self.client.delete(f"/api/v1/alerts/{alert_id}").status_code, 200)
        repeated = self.client.delete(f"/api/v1/alerts/{alert_id}")
        self.assertEqual(repeated.status_code, 404, repeated.text)
        self.assertEqual(self.client.get("/api/v1/alerts").json(), [])

    def test_doctor_can_delete_alert_without_pdf(self):
        alert_id = self.add_alert()
        self.doctor()
        existing_alerts = self.client.get("/api/v1/alerts").json()
        self.assertEqual(len(existing_alerts), 1)
        self.assertFalse(existing_alerts[0]["pdf_available"])
        response = self.client.delete(f"/api/v1/alerts/{alert_id}")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.client.get("/api/v1/alerts").json(), [])
