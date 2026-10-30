"""Local AI contract tests; every Ollama HTTP request is intercepted.

These exercise the actual adapter and report routes using synthetic readings.
They never contact Ollama, a cloud provider, Firebase, or real patient storage.
"""

import json
import os
from pathlib import Path
from unittest.mock import patch

import httpx
from fastapi import HTTPException

import api
from tests.support import ApiTestCase
from tests.test_reports import OfflineCase


RECOMMENDATIONS = ["Record the reading.", "Discuss concerns with the clinician."]


def ollama_response(*, content=None, status=200, envelope=None, raw=None):
    if envelope is None:
        envelope = {
            "model": "qwen3.5:4b",
            "message": {"role": "assistant", "content": content if content is not None else json.dumps({"recommendations": RECOMMENDATIONS})},
            "done": True,
            "done_reason": "stop",
        }
    request = httpx.Request("POST", "http://127.0.0.1:11434/api/chat")
    if raw is not None:
        return httpx.Response(status, request=request, content=raw)
    return httpx.Response(status, request=request, json=envelope)


def local_model_response():
    return ollama_response(envelope={
        "model_info": {"general.architecture": "qwen"},
        "capabilities": ["completion"],
    })


def mock_local_model_transport(transport):
    """Return a local-model preflight and the configured chat response."""
    transport.post.side_effect = lambda url, **kwargs: (
        local_model_response() if url.endswith("/api/show") else transport.post.return_value
    )


class OllamaAdapterTests(OfflineCase):
    def setUp(self):
        super().setUp()
        self.provider = self.enterContext(patch.object(api.httpx, "Client"))
        self.transport = self.provider.return_value.__enter__.return_value
        self.transport.post.return_value = ollama_response()
        mock_local_model_transport(self.transport)

    def invoke(self):
        return api.generate_ai_recommendations(
            4, 90, 98, 37, 22, "Resting",
            {"risk_status": "Normal", "condition": "Synthetic test assessment", "recommendations": RECOMMENDATIONS},
        )

    def assert_provider_error(self, expected_status):
        with self.assertRaises(HTTPException) as error:
            self.invoke()
        self.assertEqual(error.exception.status_code, expected_status)
        return error.exception

    def test_defaults_use_local_ollama_and_qwen_without_api_key(self):
        self.assertEqual(self.invoke(), RECOMMENDATIONS)
        args, kwargs = self.transport.post.call_args
        self.assertEqual(args[0], "http://127.0.0.1:11434/api/chat")
        self.assertEqual(kwargs["json"]["model"], "qwen3.5:4b")
        self.assertFalse(kwargs["json"]["stream"])
        self.assertFalse(kwargs["json"]["think"])

    def test_transport_disables_proxy_environment_and_redirects(self):
        os.environ["HTTP_PROXY"] = "http://cloud-proxy.example.invalid:8080"
        os.environ["HTTPS_PROXY"] = "http://cloud-proxy.example.invalid:8080"
        self.invoke()
        settings = self.provider.call_args.kwargs
        self.assertIs(settings["trust_env"], False)
        self.assertIs(settings["follow_redirects"], False)
        self.assertGreater(settings["timeout"], 0)

    def test_request_uses_strict_recommendation_schema(self):
        self.invoke()
        schema = self.transport.post.call_args.kwargs["json"]["format"]
        self.assertEqual(schema["type"], "object")
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(schema["required"], ["recommendations"])
        self.assertEqual(schema["properties"]["recommendations"]["items"]["type"], "string")

    def test_payload_contains_measurements_without_patient_identifiers(self):
        self.invoke()
        request = self.transport.post.call_args.kwargs["json"]
        payload = json.loads(next(message["content"] for message in request["messages"] if message["role"] == "user"))
        self.assertEqual(set(payload), {
            "age_years", "heart_rate_bpm", "spo2_percent", "temperature_c",
            "respiratory_rate_br_min", "activity", "rule_based_risk_status", "rule_based_condition",
            "approved_recommendations",
        })
        self.assertEqual(payload["age_years"], 4)
        self.assertEqual(payload["rule_based_risk_status"], "Normal")
        self.assertEqual(payload["approved_recommendations"], api.get_local_fallback_recommendations("Resting", "Normal"))

    def test_successful_recommendations_are_trimmed(self):
        self.transport.post.return_value = ollama_response(content=json.dumps({
            "recommendations": [" Record the reading. ", " Discuss concerns with the clinician.\n"],
        }))
        self.assertEqual(self.invoke(), RECOMMENDATIONS)

    def test_legacy_cloud_configuration_is_ignored_without_file_reads(self):
        os.environ["OPENAI_API_KEY"] = "synthetic-legacy-secret"
        os.environ["OPENAI_MODEL"] = "synthetic-cloud-model"
        os.environ["OPENAI_BASE_URL"] = "https://cloud.example.invalid"
        with patch.object(Path, "read_text", side_effect=AssertionError("Secret files must not be read")):
            self.assertEqual(self.invoke(), RECOMMENDATIONS)
        args, kwargs = self.transport.post.call_args
        self.assertEqual(args[0], "http://127.0.0.1:11434/api/chat")
        self.assertNotIn("synthetic-legacy-secret", repr(kwargs))
        self.assertNotIn("synthetic-cloud-model", repr(kwargs))

    def test_all_supported_loopback_hosts_are_accepted(self):
        for address, canonical in (
            ("http://127.0.0.1:11434", "http://127.0.0.1:11434"),
            ("http://localhost:11434/", "http://127.0.0.1:11434"),
            ("http://[::1]:11434", "http://[::1]:11434"),
        ):
            with self.subTest(address=address):
                os.environ["OLLAMA_BASE_URL"] = address
                self.assertEqual(self.invoke(), RECOMMENDATIONS)
                self.assertEqual(self.transport.post.call_args.args[0], canonical + "/api/chat")

    def test_only_model_name_is_sent_before_local_weights_are_verified(self):
        self.invoke()
        calls = self.transport.post.call_args_list
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0].args[0], "http://127.0.0.1:11434/api/show")
        self.assertEqual(calls[0].kwargs["json"], {"model": "qwen3.5:4b"})
        self.assertEqual(calls[1].args[0], "http://127.0.0.1:11434/api/chat")

    def test_remote_model_metadata_prevents_sending_readings(self):
        for remote in ({"remote_host": "https://cloud.example.invalid"}, {"remote_model": "remote-qwen"}):
            with self.subTest(remote=remote):
                self.transport.post.reset_mock()
                self.transport.post.side_effect = None
                self.transport.post.return_value = ollama_response(envelope={
                    "model_info": {"general.architecture": "qwen"},
                    "capabilities": ["completion"], **remote,
                })
                self.assert_provider_error(503)
                self.transport.post.assert_called_once()
                self.assertTrue(self.transport.post.call_args.args[0].endswith("/api/show"))

    def test_model_must_have_local_weights_and_completion_capability(self):
        for envelope in ({"capabilities": ["completion"]}, {"model_info": {}}, {"model_info": {"general.architecture": "qwen"}, "capabilities": ["embedding"]}):
            with self.subTest(envelope=envelope):
                self.transport.post.reset_mock()
                self.transport.post.side_effect = None
                self.transport.post.return_value = ollama_response(envelope=envelope)
                self.assert_provider_error(502)
                self.transport.post.assert_called_once()

    def test_nonlocal_and_ambiguous_urls_are_rejected_before_transport(self):
        invalid = [
            "https://ollama.com", "http://192.168.1.4:11434", "http://0.0.0.0:11434",
            "http://localhost.example.invalid:11434", "http://user:secret@127.0.0.1:11434",
            "http://127.0.0.1:11434/api", "http://127.0.0.1:11434?target=remote",
            "http://127.0.0.1:11434#fragment", "file:///tmp/ollama", "http://127.0.0.1:invalid",
        ]
        for address in invalid:
            with self.subTest(address=address):
                self.provider.reset_mock()
                os.environ["OLLAMA_BASE_URL"] = address
                self.assert_provider_error(503)
                self.provider.assert_not_called()

    def test_cloud_model_tags_are_rejected_before_transport(self):
        for model in ("qwen3.5:cloud", "qwen3.5:397b-cloud"):
            with self.subTest(model=model):
                self.provider.reset_mock()
                os.environ["OLLAMA_MODEL"] = model
                self.assert_provider_error(503)
                self.provider.assert_not_called()

    def test_missing_local_service_returns_503_without_private_transport_details(self):
        self.transport.post.side_effect = httpx.ConnectError("synthetic-private-transport-detail")
        error = self.assert_provider_error(503)
        self.assertNotIn("synthetic-private-transport-detail", error.detail)
        self.assertIn("Ollama", error.detail)

    def test_model_timeout_returns_503(self):
        self.transport.post.side_effect = httpx.ReadTimeout("synthetic timeout")
        self.assert_provider_error(503)

    def test_missing_model_returns_503(self):
        self.transport.post.return_value = ollama_response(status=404, envelope={"error": "model qwen3.5:4b not found"})
        error = self.assert_provider_error(503)
        self.assertIn("model", error.detail.lower())

    def test_provider_error_status_returns_gateway_error(self):
        self.transport.post.return_value = ollama_response(status=500, envelope={"error": "synthetic provider failure"})
        self.assert_provider_error(502)

    def test_redirect_is_not_followed_to_another_provider(self):
        self.transport.post.return_value = httpx.Response(
            307, headers={"Location": "https://cloud.example.invalid/api/chat"},
            request=httpx.Request("POST", "http://127.0.0.1:11434/api/chat"),
        )
        self.assert_provider_error(502)
        self.assertEqual(self.transport.post.call_count, 2)
        self.assertFalse(self.provider.call_args.kwargs["follow_redirects"])

    def test_malformed_http_json_returns_502(self):
        self.transport.post.return_value = ollama_response(raw=b"not JSON")
        self.assert_provider_error(502)

    def test_oversized_http_response_returns_502(self):
        self.transport.post.return_value = ollama_response(raw=b" " * (1024 * 1024 + 1))
        self.assert_provider_error(502)

    def test_oversized_model_content_returns_502(self):
        self.transport.post.return_value = ollama_response(content=" " * 8193)
        self.assert_provider_error(502)

    def test_invalid_response_envelopes_return_502(self):
        for envelope in ([], {}, {"done": True}, {"done": True, "message": None}, {"done": True, "message": {"content": ""}}, {"done": True, "message": {"content": 12}}):
            with self.subTest(envelope=envelope):
                self.transport.post.return_value = ollama_response(envelope=envelope)
                self.assert_provider_error(502)

    def test_malformed_model_json_returns_502(self):
        self.transport.post.return_value = ollama_response(content="The model did not return JSON")
        self.assert_provider_error(502)

    def test_incomplete_generation_is_rejected_even_with_parseable_content(self):
        self.transport.post.return_value = ollama_response(envelope={
            "done": False, "message": {"content": json.dumps({"recommendations": RECOMMENDATIONS})},
        })
        self.assert_provider_error(502)

    def test_token_limit_truncation_is_rejected_even_with_parseable_content(self):
        self.transport.post.return_value = ollama_response(envelope={
            "done": True, "done_reason": "length", "message": {"content": json.dumps({"recommendations": RECOMMENDATIONS})},
        })
        self.assert_provider_error(502)

    def test_schema_invalid_recommendations_are_rejected(self):
        invalid = [[], ["only one"], ["valid", "   "], ["valid", 12], ["valid", "x" * 321], ["valid"] * 6]
        for recommendations in invalid:
            with self.subTest(recommendations=repr(recommendations)[:80]):
                self.transport.post.return_value = ollama_response(content=json.dumps({"recommendations": recommendations}))
                self.assert_provider_error(502)

    def test_provider_cannot_replace_deterministic_risk_status(self):
        self.transport.post.return_value = ollama_response(content=json.dumps({
            "recommendations": RECOMMENDATIONS, "risk_status": "Normal",
        }))
        self.assert_provider_error(502)


class OllamaReportIntegrationTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.child_id = self.signup(child_name="Synthetic Private Child")
        self.assertEqual(self.ingest(self.child_id).status_code, 200)
        self.report_url = f"/api/v1/children/{self.child_id}/report/latest"

    def assert_fallback(self):
        response = self.client.get(self.report_url)
        self.assertEqual(response.status_code, 200, response.text)
        report = response.json()
        self.assertEqual(report["recommendation_source"], "Rule-based fallback")
        self.assertTrue(report["recommendations"])
        self.assertTrue(report["recommendation_notice"])
        self.assertNotIn("OpenAI", report["recommendation_notice"])
        return report

    def test_successful_local_recommendations_have_local_source(self):
        mock_local_model_transport(self.ai_transport)
        self.ai_transport.post.return_value = ollama_response()
        response = self.client.get(self.report_url)
        self.assertEqual(response.status_code, 200, response.text)
        report = response.json()
        self.assertEqual(report["recommendation_source"], "Local AI (Ollama)")
        self.assertEqual(report["recommendations"], RECOMMENDATIONS)
        self.assertIsNone(report["recommendation_notice"])
        payload = json.dumps(self.ai_transport.post.call_args.kwargs)
        self.assertNotIn("Synthetic Private Child", payload)
        self.assertNotIn("parent@example.invalid", payload)
        self.assertNotIn(self.child_id, payload)

    def test_network_failure_uses_local_rule_fallback(self):
        self.assert_fallback()

    def test_rules_mode_never_contacts_ai_for_normal_or_warning_report(self):
        with patch.dict(os.environ, {"NEOCARE_RECOMMENDATION_MODE": "rules"}):
            for temperature, expected_status in ((36.8, "Normal"), (38.5, "Warning")):
                with self.subTest(status=expected_status):
                    self.assertEqual(self.ingest(self.child_id, temperature_c=temperature).status_code, 200)
                    response = self.client.get(self.report_url)
                    self.assertEqual(response.status_code, 200, response.text)
                    report = response.json()
                    self.assertEqual(report["risk_status"], expected_status)
                    self.assertEqual(report["recommendation_source"], "Rule-based recommendations")
                    self.assertIsNone(report["recommendation_notice"])
                    self.assertTrue(report["recommendations"])
        self.ai_client.assert_not_called()

    def test_rules_mode_keeps_critical_guidance_and_can_download_pdf(self):
        with patch.dict(os.environ, {"NEOCARE_RECOMMENDATION_MODE": "rules"}):
            self.assertEqual(self.ingest(self.child_id, spo2_percent=90).status_code, 200)
            response = self.client.get(self.report_url)
            self.assertEqual(response.status_code, 200, response.text)
            report = response.json()
            self.assertEqual(report["risk_status"], "Critical")
            self.assertEqual(report["recommendation_source"], "Rule-based safety guidance")
            self.assertTrue(report["safety_recommendations"])
            pdf = self.client.get(self.report_url + "/pdf")
            self.assertEqual(pdf.status_code, 200)
            self.assertTrue(pdf.content.startswith(b"%PDF-"))
        self.ai_client.assert_not_called()

    def test_timeout_uses_local_rule_fallback(self):
        self.ai_transport.post.side_effect = httpx.ReadTimeout("synthetic timeout")
        self.assert_fallback()

    def test_missing_model_uses_local_rule_fallback(self):
        mock_local_model_transport(self.ai_transport)
        self.ai_transport.post.return_value = ollama_response(status=404, envelope={"error": "model not found"})
        self.assert_fallback()

    def test_malformed_response_uses_local_rule_fallback(self):
        mock_local_model_transport(self.ai_transport)
        self.ai_transport.post.return_value = ollama_response(raw=b"invalid HTTP body")
        self.assert_fallback()

    def test_truncated_generation_uses_local_rule_fallback(self):
        mock_local_model_transport(self.ai_transport)
        self.ai_transport.post.return_value = ollama_response(envelope={
            "done": True, "done_reason": "length", "message": {"content": '{"recommendations":['},
        })
        self.assert_fallback()

    def test_schema_invalid_output_uses_local_rule_fallback(self):
        mock_local_model_transport(self.ai_transport)
        self.ai_transport.post.return_value = ollama_response(content=json.dumps({"recommendations": [" ", " "]}))
        self.assert_fallback()

    def test_critical_deterministic_safety_does_not_wait_for_provider(self):
        self.assertEqual(self.ingest(self.child_id, spo2_percent=90).status_code, 200)
        response = self.client.get(self.report_url)
        self.assertEqual(response.status_code, 200, response.text)
        report = response.json()
        self.assertEqual(report["risk_status"], "Critical")
        self.assertTrue(report["safety_recommendations"])
        self.assertEqual(report["recommendation_source"], "Rule-based safety guidance")
        self.assertIn("without waiting for AI", report["recommendation_notice"])
        self.ai_client.assert_not_called()

    def test_critical_report_never_uses_available_local_model(self):
        self.assertEqual(self.ingest(self.child_id, temperature_c=39.5).status_code, 200)
        mock_local_model_transport(self.ai_transport)
        self.ai_transport.post.return_value = ollama_response()
        response = self.client.get(self.report_url)
        self.assertEqual(response.status_code, 200, response.text)
        report = response.json()
        self.assertEqual(report["risk_status"], "Critical")
        self.assertTrue(report["safety_recommendations"])
        self.assertEqual(report["recommendation_source"], "Rule-based safety guidance")
        self.ai_client.assert_not_called()
