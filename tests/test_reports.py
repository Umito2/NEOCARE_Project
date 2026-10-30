"""Offline report/rule/AI-adapter regression tests.

These verify software behavior, not the clinical validity of thresholds.
Firebase is never initialized and the AI client is always mocked.
"""

import os
import re
import socket
import unittest
import zlib
from unittest.mock import patch

import api
import main
from fpdf import FPDF


def report_fixture(**changes):
    report = {
        "child_id": "child_01",
        "child_name": "Test Child",
        "age_years": 4,
        "timestamp": "2026-10-27T10:00:00+00:00",
        "activity_state": "Resting",
        "heart_rate_bpm": 90,
        "spo2_percent": 98,
        "temperature_c": 37,
        "respiratory_rate_br_min": 22,
        "risk_status": "Normal",
        "condition": "Test assessment",
        "causes": ["Test measurement summary."],
        "recommendations": ["Record the reading.", "Contact the clinician if concerned."],
        "safety_recommendations": [],
        "additional_recommendations": [],
    }
    report.update(changes)
    return report


def pdf_streams(pdf):
    """Read PDF content streams without adding a PDF-parser dependency."""
    streams = []
    for stream in re.findall(rb"stream\r?\n(.*?)\r?\nendstream", pdf, re.S):
        try:
            streams.append(zlib.decompress(stream))
        except zlib.error:
            streams.append(stream)
    return b"\n".join(streams)


class OfflineCase(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.dict(os.environ, {}, clear=True))
        self.enterContext(patch.object(socket.socket, "connect", side_effect=AssertionError("Network forbidden in offline tests")))
        self.enterContext(patch.object(socket, "create_connection", side_effect=AssertionError("Network forbidden in offline tests")))
        self.enterContext(patch.object(main, "init_firebase", side_effect=AssertionError("Firebase initialization forbidden in offline tests")))


class RuleTests(OfflineCase):
    def test_baseline_result_has_required_report_fields(self):
        result = main.analyze_pediatric_vitals(4, 90, 98, 37, 22, "Resting")
        self.assertEqual(result["risk_status"], "Normal")
        self.assertTrue(result["condition"])
        self.assertTrue(all(isinstance(item, str) for item in result["causes"]))
        self.assertTrue(result["recommendations"])

    def test_existing_temperature_boundaries(self):
        for temperature, expected in [(37.9, "Normal"), (38, "Warning"), (38.9, "Warning"), (39, "Critical")]:
            with self.subTest(temperature=temperature):
                self.assertEqual(main.analyze_pediatric_vitals(4, 90, 98, temperature, 22, "Resting")["risk_status"], expected)

    def test_low_oxygen_takes_precedence_over_other_branches(self):
        result = main.analyze_pediatric_vitals(4, 160, 91, 39, 40, "Resting")
        self.assertEqual(result["risk_status"], "Critical")
        self.assertIn("oxygen", result["causes"][0])

    def test_resting_heart_rate_boundaries_for_both_age_groups(self):
        for age, limit in [(3, 130), (4, 115)]:
            with self.subTest(age=age):
                self.assertEqual(main.analyze_pediatric_vitals(age, limit, 98, 37, 22, "Resting")["risk_status"], "Normal")
                self.assertEqual(main.analyze_pediatric_vitals(age, limit + 1, 98, 37, 22, "Resting")["risk_status"], "Warning")

    def test_respiratory_rate_over_defined_limit_is_not_normal(self):
        # The analyzer defines a respiratory limit of 26 for this age.
        result = main.analyze_pediatric_vitals(4, 90, 98, 37, 100, "Resting")
        self.assertNotEqual(result["risk_status"], "Normal", "Respiratory rate 100 is ignored despite the analyzer's defined limit of 26")

    def test_active_heart_rate_over_adjusted_limit_is_not_normal(self):
        # The analyzer computes an activity-adjusted limit of 115 + 25.
        result = main.analyze_pediatric_vitals(4, 240, 98, 37, 22, "Active")
        self.assertNotEqual(result["risk_status"], "Normal", "Active heart rate 240 bypasses the computed activity-adjusted limit")

    def test_critical_status_omits_additional_local_suggestions(self):
        self.assertEqual(main.get_additional_recommendations(4, 90, 91, 37, 22, "Resting", {"risk_status": "Critical"}), [])

    def test_local_suggestions_cover_fever_resting_and_activity(self):
        cases = [(38, 90, "Resting", "fever"), (37, 150, "Resting", "fit"), (37, 90, "Active", "activity"), (37, 90, "Sleeping", "time")]
        for temperature, heart_rate, activity, keyword in cases:
            with self.subTest(activity=activity, temperature=temperature, heart_rate=heart_rate):
                result = main.get_additional_recommendations(4, heart_rate, 98, temperature, 22, activity, {"risk_status": "Warning"})
                self.assertIn(keyword, " ".join(result).lower())


class PDFTests(OfflineCase):
    def assert_pdf(self, report):
        result = main.generate_pdf_report(report, filename=None)
        self.assertIsInstance(result, bytes)
        self.assertTrue(result.startswith(b"%PDF-"))
        self.assertTrue(result.rstrip().endswith(b"%%EOF"))
        self.assertGreater(len(result), 1000)
        return result

    def test_ascii_report_generates_complete_pdf_in_memory(self):
        result = self.assert_pdf(report_fixture())
        content = pdf_streams(result)
        self.assertIn(b"Test Child", content)
        self.assertIn(b"Test measurement summary", content)
        self.assertIn(b"Record the reading", content)

    def test_pdf_includes_safety_and_additional_guidance(self):
        result = self.assert_pdf(report_fixture(risk_status="Critical", safety_recommendations=["SAFETY TEST CONTENT"], additional_recommendations=["LOCAL TEST CONTENT"]))
        content = pdf_streams(result)
        self.assertIn(b"SAFETY TEST CONTENT", content)
        self.assertIn(b"LOCAL TEST CONTENT", content)

    def test_ai_report_identifies_ai_source(self):
        result = self.assert_pdf(report_fixture(recommendation_source="Local AI (Ollama)"))
        self.assertIn(b"AI-generated recommendations", pdf_streams(result))
        self.assertIn(b"Ollama", pdf_streams(result))

    def test_fallback_report_identifies_unavailable_ai(self):
        result = self.assert_pdf(report_fixture(recommendation_source="Rule-based fallback"))
        self.assertIn(b"AI recommendations were unavailable", pdf_streams(result))

    def test_long_recommendations_paginate_without_losing_final_content(self):
        recommendations = [f"Recommendation {number}: " + "Record this test observation. " * 8 for number in range(40)]
        result = self.assert_pdf(report_fixture(recommendations=recommendations))
        self.assertGreater(len(re.findall(rb"/Type /Page\b", result)), 1)
        self.assertIn(b"Recommendation 39:", pdf_streams(result))

    def test_arabic_child_name_accepted_by_api_can_be_exported(self):
        report = report_fixture(child_name="طفل تجريبي")
        api.ChildProfile(name=report["child_name"], age_years=4, height_cm=100, weight_kg=16)
        self.assert_pdf(report)

    def test_ai_recommendations_with_unicode_punctuation_can_be_exported(self):
        recommendations = ["Check the child\u2019s wearable fit.", "Record the reading \u2014 discuss concerns with the clinician."]
        api.AIRecommendationResponse(recommendations=recommendations)
        self.assert_pdf(report_fixture(recommendations=recommendations, recommendation_source="Local AI (Ollama)"))

    def test_maximum_accepted_child_name_stays_inside_page(self):
        class MeasuringPDF(FPDF):
            def __init__(self):
                super().__init__()
                self.overflowing_patient_cells = []

            def cell(self, w=None, h=None, text="", *args, **kwargs):
                if text.startswith("Patient Name:"):
                    available = self.w - self.r_margin - self.x if w == 0 else w
                    if self.get_string_width(text) + 2 * self.c_margin > available:
                        self.overflowing_patient_cells.append(text)
                return super().cell(w, h, text, *args, **kwargs)

        pdf = MeasuringPDF()
        report = report_fixture(child_name="W" * 80)
        api.ChildProfile(name=report["child_name"], age_years=4, height_cm=100, weight_kg=16)
        with patch.object(main, "FPDF", return_value=pdf):
            self.assert_pdf(report)
        self.assertEqual(pdf.overflowing_patient_cells, [], "The accepted 80-character child name extends beyond the PDF page margin")


if __name__ == "__main__":
    unittest.main(verbosity=2)
