import hmac
import ipaddress
import json
import logging
import math
import os
import re
import smtplib
import sqlite3
import threading
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from io import BytesIO
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

import httpx
from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

import auth_store
import assessment
import main

BASE_DIR = Path(__file__).resolve().parent
logger = logging.getLogger(__name__)
PARENT_ID_PATTERN = re.compile(r"^child_[0-9]{2}$")
SIGNUP_LOCK = threading.Lock()
EMAIL_LOCK = threading.Lock()


class SensorReading(BaseModel):
    model_config = ConfigDict(extra="forbid")

    child_id: str = Field(pattern=r"^child_[0-9]{2}$")
    heart_rate_bpm: float = Field(gt=0, le=250)
    spo2_percent: float = Field(ge=0, le=100)
    temperature_c: float = Field(ge=25, le=45)
    resp_rate: float | None = Field(default=None, gt=0, le=100)
    activity: Literal["Sleeping", "Resting", "Active"] | None = None


class ChildProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=80)
    age_years: float = Field(gt=0, le=18)
    height_cm: float = Field(gt=0, le=250)
    weight_kg: float = Field(gt=0, le=200)


class ParentSignup(BaseModel):
    model_config = ConfigDict(extra="forbid")

    parent_name: str = Field(min_length=1, max_length=80)
    email: str = Field(min_length=5, max_length=254)
    phone: str = Field(min_length=7, max_length=30)
    password: str = Field(min_length=12, max_length=128)
    child_name: str = Field(min_length=1, max_length=80)
    age_years: float = Field(gt=0, le=18)
    height_cm: float = Field(gt=0, le=250)
    weight_kg: float = Field(gt=0, le=200)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value):
        value = value.strip().lower()
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value):
            raise ValueError("Enter a valid email address.")
        return value

    @field_validator("parent_name", "child_name", "phone")
    @classmethod
    def strip_nonempty(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("This field cannot be blank.")
        return value


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["doctor", "parent"]
    identifier: str = Field(min_length=1, max_length=254)
    password: str = Field(min_length=1, max_length=128)


class AlertThresholds(BaseModel):
    model_config = ConfigDict(extra="forbid")

    spo2_min: float = Field(ge=75, le=100)
    temperature_warning_c: float = Field(ge=36, le=45)
    temperature_critical_c: float = Field(ge=36, le=45)
    heart_rate_max_age_0_3: float = Field(ge=30, le=250)
    heart_rate_max_age_over_3: float = Field(ge=30, le=250)
    respiratory_rate_max_age_0_3: float = Field(ge=10, le=100)
    respiratory_rate_max_age_over_3: float = Field(ge=10, le=100)

    @model_validator(mode="after")
    def warning_below_critical(self):
        if self.temperature_warning_c >= self.temperature_critical_c:
            raise ValueError("Warning temperature must be lower than critical temperature.")
        return self


class AIRecommendationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    recommendations: list[str] = Field(min_length=2, max_length=5)

    @field_validator("recommendations")
    @classmethod
    def validate_recommendations(cls, value):
        cleaned = [item.strip() for item in value]
        if any(not item or len(item) > 320 for item in cleaned):
            raise ValueError("Recommendations must be non-empty and concise.")
        return cleaned


class DoctorAccount(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=3, max_length=80)
    display_name: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=12, max_length=128)


class AlertUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workflow_status: Literal["new", "acknowledged", "resolved"] | None = None
    note: str | None = Field(default=None, min_length=1, max_length=2000)

    @model_validator(mode="after")
    def meaningful_update(self):
        if self.note is not None:
            self.note = self.note.strip()
            if not self.note:
                raise ValueError("Notes cannot be blank.")
        if self.workflow_status is None and self.note is None:
            raise ValueError("Provide a workflow status or note.")
        return self


@asynccontextmanager
async def lifespan(_app: FastAPI):
    auth_store.initialize()
    main.init_firebase()
    stop = threading.Event()
    worker = None
    if os.getenv("SMTP_HOST") and os.getenv("SMTP_FROM"):
        worker = threading.Thread(target=retry_email_worker, args=(stop,), daemon=True)
        worker.start()
    try:
        yield
    finally:
        stop.set()
        if worker:
            worker.join(timeout=1)


app = FastAPI(
    title="NEOCARE ESP32 Sensor API",
    description="Receives ESP32 sensor readings and stores the latest reading in Firebase.",
    lifespan=lifespan,
)


def verify_device_key(x_api_key: str | None) -> None:
    configured_key = os.getenv("ESP32_API_KEY")
    if not configured_key:
        raise HTTPException(
            status_code=503,
            detail="ESP32_API_KEY is not configured on the API server.",
        )
    if not x_api_key or not secure_equal(x_api_key, configured_key):
        raise HTTPException(status_code=401, detail="Invalid or missing API key.")


def secure_equal(first, second):
    return hmac.compare_digest(first.encode("utf-8"), second.encode("utf-8"))


def current_user(request: Request):
    session = auth_store.get_session(request.cookies.get("neocare_session"))
    if session is None:
        raise HTTPException(status_code=401, detail="Please sign in.")
    return session


def require_doctor(request: Request):
    user = current_user(request)
    if user["role"] != "doctor":
        raise HTTPException(status_code=403, detail="Doctor access is required.")
    return user


def get_child_profile(child_id, user):
    if not PARENT_ID_PATTERN.fullmatch(child_id):
        raise HTTPException(status_code=422, detail="child_id must use the format child_01.")
    profile = main.db.reference("neocare_system/children_profiles").child(child_id).get()
    if not profile:
        raise HTTPException(status_code=404, detail="Child profile not found.")
    if user["role"] == "parent" and profile.get("owner_parent_id") != user["user_id"]:
        raise HTTPException(status_code=404, detail="Child profile not found.")
    return profile


def allocate_child_id(root_ref, profiles):
    readings = root_ref.child("live_monitoring").get() or {}
    used_ids = set(profiles) | set(readings) | auth_store.used_history_child_ids()
    return next(
        (
            f"child_{number:02d}"
            for number in range(1, 100)
            if f"child_{number:02d}" not in used_ids
        ),
        None,
    )


def reading_freshness(reading, now=None):
    """Timestamp freshness is an operational data-quality limit, not a clinical rule."""
    try:
        maximum_age = int(os.getenv("NEOCARE_READING_MAX_AGE_SECONDS", "300"))
        if maximum_age <= 0:
            raise ValueError
    except ValueError:
        maximum_age = 300
    required = ("heart_rate_bpm", "spo2_percent", "temperature_c", "respiratory_rate_br_min", "activity_state")
    result = {
        "status": "missing", "last_received": None, "age_seconds": None,
        "missing_fields": list(required), "max_age_seconds": maximum_age,
    }
    if not isinstance(reading, dict) or not reading:
        return result
    result["missing_fields"] = [key for key in required if reading.get(key) is None]
    timestamp = reading.get("timestamp")
    if not timestamp:
        result["missing_fields"].append("timestamp")
        return result
    try:
        parsed = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError
        age = ((now or datetime.now(timezone.utc)) - parsed).total_seconds()
        if age < -30:
            raise ValueError
    except (TypeError, ValueError, OverflowError):
        result["status"] = "invalid"
        return result
    result["last_received"] = parsed.astimezone(timezone.utc).isoformat()
    result["age_seconds"] = max(0, int(age))
    if age > maximum_age:
        result["status"] = "stale"
        return result
    ranges = {"heart_rate_bpm": (0, 250), "spo2_percent": (0, 100), "temperature_c": (25, 45), "respiratory_rate_br_min": (0, 100)}
    for key in required[:-1]:
        if reading.get(key) is not None:
            try:
                value = float(reading[key])
                lower, upper = ranges[key]
                if isinstance(reading[key], bool) or not math.isfinite(value) or not lower <= value <= upper:
                    raise ValueError
                if key in ("heart_rate_bpm", "respiratory_rate_br_min") and value == 0:
                    raise ValueError
            except (TypeError, ValueError, OverflowError):
                result["status"] = "invalid"
                return result
    if reading.get("activity_state") not in (None, "Sleeping", "Resting", "Active"):
        result["status"] = "invalid"
    else:
        result["status"] = "incomplete" if result["missing_fields"] else "fresh"
    return result


def latest_child_status(profile, reading, thresholds=None):
    freshness = reading_freshness(reading)
    if not reading:
        return {"risk_status": "Waiting for readings", "condition": "No sensor data received", "freshness": freshness}
    quality_states = {
        "missing": ("Unknown reading time", "The reading has no timestamp; reconnect the device"),
        "invalid": ("Invalid reading", "The reading timestamp or measurements are invalid"),
        "stale": ("Stale reading", "No recent sensor reading; reconnect the device"),
    }
    if freshness["status"] in quality_states:
        risk, condition = quality_states[freshness["status"]]
        return {"risk_status": risk, "condition": condition, "freshness": freshness}
    evaluation = assessment.analyze_vitals(
        profile.get("age_years"), reading.get("heart_rate_bpm"), reading.get("spo2_percent"),
        reading.get("temperature_c"), reading.get("respiratory_rate_br_min"), reading.get("activity_state"), thresholds,
    )
    return {**evaluation, "freshness": freshness}


def get_local_fallback_recommendations(activity, risk_status):
    if risk_status == "Critical":
        return [
            "Follow the deterministic safety guidance shown separately; do not wait for AI recommendations.",
            "If the child's condition worsens, contact local emergency services.",
        ]

    recommendations = [
        "Check the wearable fit and repeat the measurement according to the device instructions.",
        "Record the reading, time, and activity to share with the child's clinician.",
        "Contact a pediatric clinician if unusual readings persist or the child seems unwell.",
    ]
    if activity == "Active":
        recommendations[0] = (
            "Let the child rest, then repeat the measurement according to the device instructions."
        )
    return recommendations


def get_ollama_config():
    """Allow the local inference service only; never resolve arbitrary hosts."""
    configured_url = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").strip()
    try:
        parsed = urlsplit(configured_url)
        host = parsed.hostname
        port = parsed.port
        if (
            parsed.scheme != "http"
            or not host
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in ("", "/")
            or parsed.query
            or parsed.fragment
            or port == 0
        ):
            raise ValueError("Invalid local service URL")
        # Canonicalize localhost rather than depending on host-file or DNS rules.
        address = ipaddress.ip_address("127.0.0.1" if host == "localhost" else host)
        if not address.is_loopback:
            raise ValueError("Remote service URLs are not allowed")
        host = f"[{address.compressed}]" if address.version == 6 else address.compressed
        base_url = f"http://{host}" + (f":{port}" if port is not None else "")
    except ValueError:
        raise HTTPException(
            status_code=503,
            detail="Local AI requires OLLAMA_BASE_URL to be an HTTP loopback address on this computer.",
        ) from None

    model = os.getenv("OLLAMA_MODEL", "qwen3.5:4b").strip()
    if (
        not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*(?::[A-Za-z0-9][A-Za-z0-9._-]*)?", model)
        or len(model) > 128
        or "cloud" in model.lower()
    ):
        raise HTTPException(
            status_code=503,
            detail="Choose a downloaded local Ollama model. Cloud models and model URLs are not allowed.",
        )
    return base_url, model


def read_ollama_response(response):
    """Reject errors without disclosing provider bodies or measurement data."""
    if response.status_code == 404:
        raise HTTPException(
            status_code=503,
            detail="The local AI model is not available. Download the configured model in Ollama, then try again.",
        )
    if not 200 <= response.status_code < 300:
        logger.error("Local AI returned HTTP %s.", response.status_code)
        raise HTTPException(
            status_code=502,
            detail="The local AI service could not complete the request. Check that Ollama and its model are ready.",
        )
    try:
        if len(response.content) > 1024 * 1024:
            raise ValueError("Response too large")
        result = response.json()
        if not isinstance(result, dict) or result.get("error"):
            raise ValueError("Invalid response object")
        return result
    except (ValueError, TypeError):
        logger.error("Local AI returned invalid response data.")
        raise HTTPException(
            status_code=502,
            detail="The local AI service returned an invalid response. Showing the rule-based guidance is still available.",
        ) from None


def generate_ai_recommendations(
    age_years, heart_rate, spo2, temperature, resp_rate, activity, status
):
    base_url, model = get_ollama_config()
    readings = {
        "age_years": age_years,
        "heart_rate_bpm": heart_rate,
        "spo2_percent": spo2,
        "temperature_c": temperature,
        "respiratory_rate_br_min": resp_rate,
        "activity": activity,
        "rule_based_risk_status": status["risk_status"],
        "rule_based_condition": status["condition"],
        "approved_recommendations": get_local_fallback_recommendations(activity, status["risk_status"]),
    }
    schema = AIRecommendationResponse.model_json_schema()
    schema["properties"]["recommendations"]["items"].update({"minLength": 1, "maxLength": 320})
    try:
        with httpx.Client(timeout=120.0, trust_env=False, follow_redirects=False) as client:
            # This request contains no readings. A renamed cloud model must be
            # rejected before any measurements are handed to the inference API.
            metadata = read_ollama_response(client.post(
                f"{base_url}/api/show", json={"model": model}, timeout=10.0,
            ))
            if metadata.get("remote_host") or metadata.get("remote_model"):
                raise HTTPException(
                    status_code=503,
                    detail="The configured Ollama model uses a remote service. Select a downloaded local model.",
                )
            if (
                not isinstance(metadata.get("model_info"), dict)
                or not metadata["model_info"]
                or not isinstance(metadata.get("capabilities"), list)
                or "completion" not in metadata["capabilities"]
            ):
                raise HTTPException(
                    status_code=502,
                    detail="Ollama could not verify a downloaded text model. Check the local model installation.",
                )
            completion = read_ollama_response(client.post(
                f"{base_url}/api/chat",
                json={
                    "model": model,
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "Rewrite the supplied approved_recommendations checklist in clear, concise English. "
                                "The checklist is the complete set of allowed actions: preserve every action, "
                                "condition, and urgency without adding medical advice. The measurements are context "
                                "only, not evidence from which to invent interpretations or diagnoses. Do not add "
                                "causes, medicines, doses, treatment changes, thresholds, waiting times, or reassurance "
                                "that the child is healthy or safe. Never contradict or delay the separate rule-based "
                                "safety guidance. For Critical status, preserve the instruction to follow that guidance "
                                "without waiting for AI. Use plain ASCII punctuation. Return only a JSON object with "
                                "a recommendations array containing 2 to 5 short strings."
                            ),
                        },
                        {"role": "user", "content": json.dumps(readings, separators=(",", ":"))},
                    ],
                    "format": schema,
                    "think": False,
                    "stream": False,
                    "options": {"temperature": 0, "num_predict": 512, "num_ctx": 4096},
                    "keep_alive": "5m",
                },
            ))
    except httpx.RequestError as exc:
        logger.warning("Local AI request failed (%s).", type(exc).__name__)
        raise HTTPException(
            status_code=503,
            detail="Local AI is unavailable. Start Ollama and make sure the configured model is downloaded, then try again.",
        ) from None

    message = completion.get("message")
    if (
        completion.get("done") is not True
        or completion.get("done_reason") != "stop"
        or not isinstance(message, dict)
        or not isinstance(message.get("content"), str)
        or not message["content"].strip()
        or len(message["content"]) > 8192
        or message.get("tool_calls")
        or completion.get("remote_host")
        or completion.get("remote_model")
    ):
        logger.error("Local AI returned an incomplete or unsupported recommendation response.")
        raise HTTPException(
            status_code=502,
            detail="The local AI service returned an incomplete recommendation. Try again when the model is ready.",
        )
    try:
        return AIRecommendationResponse.model_validate_json(message["content"]).recommendations
    except ValidationError:
        logger.error("Local AI returned invalid recommendation data.")
        raise HTTPException(
            status_code=502,
            detail="The local AI service returned invalid recommendations. Try again when the model is ready.",
        ) from None


def alert_severity(profile, reading, thresholds):
    status = latest_child_status(profile, reading, thresholds)["risk_status"]
    return {"Normal": 0, "Warning": 1, "Critical": 2}.get(status)


def send_email_message(message):
    required = ("SMTP_HOST", "SMTP_FROM")
    if any(not os.getenv(key) for key in required):
        return "not_configured"

    message["From"] = os.environ["SMTP_FROM"]
    host = os.environ["SMTP_HOST"]
    port = int(os.getenv("SMTP_PORT", "587"))
    username = os.getenv("SMTP_USERNAME")
    password = os.getenv("SMTP_PASSWORD")
    timeout = 10
    if os.getenv("SMTP_USE_SSL", "").lower() == "true":
        with smtplib.SMTP_SSL(host, port, timeout=timeout) as smtp:
            if username and password:
                smtp.login(username, password)
            smtp.send_message(message)
    else:
        with smtplib.SMTP(host, port, timeout=timeout) as smtp:
            smtp.starttls()
            if username and password:
                smtp.login(username, password)
            smtp.send_message(message)
    return "sent"


def send_parent_alert(profile, reading, status):
    recipient = profile.get("parent_email")
    if not recipient:
        return "no_parent_email"

    message = EmailMessage()
    message["Subject"] = f"NEOCARE {status['risk_status']} reading alert for {profile['name']}"
    message["To"] = recipient
    message.set_content(
        f"""Automated NEOCARE reading alert for {profile['name']} ({reading['child_id']}).

The latest device reading crossed a clinic-configured alert threshold:
Status: {status['risk_status']}
Reading time: {reading.get('timestamp', 'unknown')}
Heart rate: {reading.get('heart_rate_bpm')} bpm
SpO2: {reading.get('spo2_percent')}%
Temperature: {reading.get('temperature_c')} C
Respiratory rate: {reading.get('respiratory_rate_br_min')} breaths/min
Activity: {reading.get('activity_state')}

This automated notice is not a diagnosis or medical advice. Recheck the device reading and contact a qualified clinician if you are concerned. For an emergency, contact local emergency services.
"""
    )
    return send_email_message(message)


def deliver_pending_alert_emails(limit=20):
    """Claim persisted notices and retry independently of new sensor readings."""
    results = {}
    if not EMAIL_LOCK.acquire(blocking=False):
        return results
    try:
        for _ in range(min(max(int(limit), 1), 100)):
            # Lease only the notice being sent now. Pre-leasing a whole batch
            # lets later leases expire while earlier SMTP calls are still busy.
            pending = auth_store.pending_alert_emails(1, exclude_alert_ids=list(results))
            if not pending:
                break
            item = pending[0]
            message = EmailMessage()
            try:
                message["To"] = item["recipient"]
                message["Subject"] = item["subject"]
                message.set_content(item["message"])
                if item.get("pdf_data"):
                    message.add_attachment(
                        item["pdf_data"], maintype="application", subtype="pdf",
                        filename=f"NEOCARE_Alert_{item['alert_id']}_Report.pdf",
                    )
                status = send_email_message(message)
            except (OSError, smtplib.SMTPException, ValueError):
                status = "failed"
                logger.warning("Email delivery failed for alert %s; retry remains tracked in the outbox.", item["alert_id"])
            auth_store.complete_alert_email(item["alert_id"], status)
            results[item["alert_id"]] = status
    finally:
        EMAIL_LOCK.release()
    return results


def retry_email_worker(stop):
    while not stop.wait(60):
        try:
            deliver_pending_alert_emails()
        except (OSError, sqlite3.Error):
            logger.warning("The notification retry worker could not access its outbox; it will retry.")


@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.get("/")
def dashboard():
    return FileResponse(
        BASE_DIR / "index.html",
        headers={"Cache-Control": "no-store"},
    )


@app.get("/assets/neocare-i18n.js")
def translation_script():
    return FileResponse(BASE_DIR / "neocare-i18n.js", media_type="application/javascript", headers={"Cache-Control": "no-store"})


@app.post("/api/v1/auth/signup")
def parent_signup(signup: ParentSignup, request: Request, response: Response):
    if len(signup.password) < 12:
        raise HTTPException(status_code=422, detail="Password must be at least 12 characters.")

    parent_id = str(uuid.uuid4())
    root_ref = main.db.reference("neocare_system")
    profiles_ref = root_ref.child("children_profiles")
    with SIGNUP_LOCK:
        profiles = profiles_ref.get() or {}
        child_id = allocate_child_id(root_ref, profiles)
        if child_id is None:
            raise HTTPException(status_code=409, detail="No available child IDs remain.")

        profile = {
            "name": signup.child_name,
            "age_years": signup.age_years,
            "height_cm": signup.height_cm,
            "weight_kg": signup.weight_kg,
            "parent_id": parent_id,
            "parent_email": signup.email,
            "parent_phone": signup.phone,
            "owner_parent_id": parent_id,
        }
        child_ref = profiles_ref.child(child_id)
        child_ref.set(profile)
        try:
            auth_store.create_parent(
                parent_id, signup.parent_name, signup.email, signup.phone, signup.password
            )
        except sqlite3.IntegrityError:
            child_ref.delete()
            raise HTTPException(
                status_code=409, detail="An account with this email already exists."
            ) from None
        except Exception:
            child_ref.delete()
            raise

    token = auth_store.create_session("parent", parent_id, signup.parent_name)
    response.set_cookie(
        "neocare_session",
        token,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="lax",
        max_age=auth_store.SESSION_SECONDS,
        path="/",
    )
    return {
        "role": "parent",
        "display_name": signup.parent_name,
        "child_id": child_id,
    }


@app.post("/api/v1/auth/login")
def login(payload: LoginRequest, request: Request, response: Response):
    if payload.role == "doctor":
        individual = auth_store.doctor_by_username(payload.identifier)
        if individual is not None:
            # A named account takes precedence over the shared fallback, including
            # when its password is wrong or the account is inactive.
            user = auth_store.authenticate_doctor(payload.identifier, payload.password)
            if user is None:
                raise HTTPException(status_code=401, detail="Invalid doctor username or password.")
        else:
            doctor_username = os.getenv("DOCTOR_USERNAME", "NEOCARE")
            doctor_password = os.getenv("DOCTOR_PASSWORD", "123456789")
            if not doctor_username or not doctor_password:
                raise HTTPException(
                    status_code=503,
                    detail="Doctor login is not configured. Set DOCTOR_USERNAME and DOCTOR_PASSWORD on the server.",
                )
            valid = secure_equal(payload.identifier, doctor_username) and secure_equal(payload.password, doctor_password)
            if not valid:
                raise HTTPException(status_code=401, detail="Invalid doctor username or password.")
            user = {"role": "doctor", "user_id": doctor_username, "display_name": "Clinic"}
    else:
        user = auth_store.authenticate_parent(payload.identifier.strip().lower(), payload.password)
        if user is None:
            raise HTTPException(status_code=401, detail="Invalid email or password.")

    token = auth_store.create_session(user["role"], user["user_id"], user["display_name"])
    if user["role"] == "doctor":
        auth_store.record_audit("doctor", user["user_id"], "doctor.login", user["user_id"])
    response.set_cookie(
        "neocare_session",
        token,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="lax",
        max_age=auth_store.SESSION_SECONDS,
        path="/",
    )
    return {"role": user["role"], "display_name": user["display_name"]}


@app.get("/api/v1/auth/me")
def who_am_i(request: Request):
    user = current_user(request)
    return {"role": user["role"], "display_name": user["display_name"]}


@app.post("/api/v1/auth/logout")
def logout(request: Request, response: Response):
    auth_store.delete_session(request.cookies.get("neocare_session"))
    response.delete_cookie("neocare_session", path="/", httponly=True, samesite="lax")
    return {"status": "signed_out"}


@app.get("/api/v1/children")
def list_children(request: Request):
    user = current_user(request)
    profiles = main.db.reference("neocare_system/children_profiles").get() or {}
    readings = main.db.reference("neocare_system/live_monitoring").get() or {}
    thresholds = auth_store.get_thresholds()
    result = []
    for child_id, profile in sorted(profiles.items()):
        if not isinstance(profile, dict):
            continue
        if user["role"] == "parent" and profile.get("owner_parent_id") != user["user_id"]:
            continue
        reading = readings.get(child_id)
        status = latest_child_status(profile, reading, thresholds)
        child_data = {
            "child_id": child_id,
            **profile,
            **status,
            "latest_reading": reading,
        }
        if user["role"] == "parent":
            child_data.pop("owner_parent_id", None)
            child_data.pop("parent_id", None)
            child_data.pop("parent_email", None)
            child_data.pop("parent_phone", None)
        result.append(child_data)
    return result


@app.put("/api/v1/children/{child_id}")
def save_child(child_id: str, profile: ChildProfile, request: Request):
    user = current_user(request)
    existing = get_child_profile(child_id, user)
    if user["role"] not in ("parent", "doctor"):
        raise HTTPException(status_code=403, detail="Profile editing is not allowed for this account.")
    profile_data = {
        **existing,
        **profile.model_dump(),
        "name": profile.name.strip(),
    }
    if not profile_data["name"]:
        raise HTTPException(status_code=422, detail="Child name cannot be blank.")
    main.db.reference("neocare_system/children_profiles").child(child_id).set(profile_data)
    return {"status": "saved", "child_id": child_id, **profile_data}


@app.post("/api/v1/children", status_code=201)
def create_child(profile: ChildProfile, request: Request):
    user = current_user(request)
    if user["role"] != "parent":
        raise HTTPException(status_code=403, detail="Only a parent can create a child profile.")
    parent = auth_store.parent_by_id(user["user_id"])
    if parent is None:
        raise HTTPException(status_code=401, detail="Parent account is no longer available.")

    profiles_ref = main.db.reference("neocare_system/children_profiles")
    root_ref = main.db.reference("neocare_system")
    with SIGNUP_LOCK:
        profiles = profiles_ref.get() or {}
        child_id = allocate_child_id(root_ref, profiles)
        if child_id is None:
            raise HTTPException(status_code=409, detail="No available child IDs remain.")
        data = {
            **profile.model_dump(),
            "name": profile.name.strip(),
            "parent_id": user["user_id"],
            "parent_email": parent["email"],
            "parent_phone": parent["phone"],
            "owner_parent_id": user["user_id"],
        }
        if not data["name"]:
            raise HTTPException(status_code=422, detail="Child name cannot be blank.")
        profiles_ref.child(child_id).set(data)
    return {"status": "saved", "child_id": child_id, **data}


@app.get("/api/v1/children/{child_id}/readings/latest")
def latest_reading(child_id: str, request: Request):
    user = current_user(request)
    get_child_profile(child_id, user)
    root_ref = main.db.reference("neocare_system")
    reading = root_ref.child("live_monitoring").child(child_id).get()
    if not reading:
        return {"status": "waiting", "child_id": child_id, "freshness": reading_freshness(None)}
    return {"status": "available", **reading, "freshness": reading_freshness(reading)}


@app.get("/api/v1/children/{child_id}/readings/history")
def reading_history(child_id: str, request: Request, period: Literal["24h", "7d"] = "24h"):
    get_child_profile(child_id, current_user(request))
    since = (datetime.now(timezone.utc) - timedelta(hours=24 if period == "24h" else 168)).isoformat()
    readings = auth_store.list_readings(child_id, since, limit=1000)
    total = auth_store.count_readings(child_id, since)
    return {
        "child_id": child_id, "period": period, "since": since,
        "readings": readings, "sample_limit": 1000, "total_count": total,
        "sampled": total > len(readings),
    }


def build_latest_reading_report(child_id, request):
    user = current_user(request)
    root_ref = main.db.reference("neocare_system")
    profile = get_child_profile(child_id, user)
    reading = root_ref.child("live_monitoring").child(child_id).get()
    if not reading:
        raise HTTPException(status_code=409, detail="No sensor reading is available yet.")
    freshness = reading_freshness(reading)
    if freshness["status"] in ("missing", "invalid", "stale"):
        raise HTTPException(status_code=409, detail="A recent reading with a valid timestamp and measurements is required. Reconnect the device and receive a new reading.")
    resp_rate = reading.get("respiratory_rate_br_min")
    activity = reading.get("activity_state")
    if freshness["status"] == "incomplete" or resp_rate is None or activity is None:
        raise HTTPException(
            status_code=409,
            detail="The ESP32 must send resp_rate and activity to generate a recommendation report.",
        )

    age_years = profile["age_years"]
    heart_rate = reading["heart_rate_bpm"]
    spo2 = reading["spo2_percent"]
    temperature = reading["temperature_c"]
    evaluation = assessment.analyze_vitals(
        age_years, heart_rate, spo2, temperature, resp_rate, activity, auth_store.get_thresholds()
    )
    if evaluation["risk_status"] not in ("Normal", "Warning", "Critical"):
        raise HTTPException(status_code=409, detail="The latest reading cannot be assessed. Receive a complete valid reading.")
    if evaluation["risk_status"] == "Critical":
        # Urgent deterministic guidance must not wait for model loading/inference.
        evaluation["recommendations"] = get_local_fallback_recommendations(
            activity, evaluation["risk_status"]
        )
        evaluation["recommendation_source"] = "Rule-based safety guidance"
        evaluation["recommendation_notice"] = (
            "Urgent guidance is provided immediately without waiting for AI."
        )
    elif os.getenv("NEOCARE_RECOMMENDATION_MODE", "local").strip().lower() == "rules":
        evaluation["recommendations"] = get_local_fallback_recommendations(
            activity, evaluation["risk_status"]
        )
        evaluation["recommendation_source"] = "Rule-based recommendations"
        evaluation["recommendation_notice"] = None
    else:
        try:
            evaluation["recommendations"] = generate_ai_recommendations(
                age_years,
                heart_rate,
                spo2,
                temperature,
                resp_rate,
                activity,
                evaluation,
            )
            evaluation["recommendation_source"] = "Local AI (Ollama)"
            evaluation["recommendation_notice"] = None
        except HTTPException as exc:
            if exc.status_code not in (502, 503):
                raise
            logger.warning("Using rule-based recommendations because local AI is unavailable: %s", exc.detail)
            evaluation["recommendations"] = get_local_fallback_recommendations(
                activity, evaluation["risk_status"]
            )
            evaluation["recommendation_source"] = "Rule-based fallback"
            evaluation["recommendation_notice"] = (
                f"{exc.detail} Showing rule-based guidance instead."
            )
    additional_recommendations = main.get_additional_recommendations(
        age_years, heart_rate, spo2, temperature, resp_rate, activity, evaluation
    )
    return {
        "child_id": child_id,
        "child_name": profile["name"],
        "age_years": age_years,
        "timestamp": reading.get("timestamp", ""),
        "activity_state": activity,
        "heart_rate_bpm": heart_rate,
        "spo2_percent": spo2,
        "temperature_c": temperature,
        "respiratory_rate_br_min": resp_rate,
        "freshness": freshness,
        **evaluation,
        "additional_recommendations": additional_recommendations,
    }


@app.get("/api/v1/children/{child_id}/report/latest")
def latest_reading_report(child_id: str, request: Request):
    return build_latest_reading_report(child_id, request)


@app.get("/api/v1/children/{child_id}/report/latest/pdf")
def latest_reading_report_pdf(child_id: str, request: Request):
    report = build_latest_reading_report(child_id, request)
    pdf_bytes = main.generate_pdf_report(report, filename=None)
    return StreamingResponse(
        BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="NEOCARE_{child_id}_Report.pdf"',
            "Cache-Control": "no-store",
        },
    )


@app.post("/api/v1/children/{child_id}/report/latest/send")
def send_latest_reading_report(child_id: str, request: Request):
    user = require_doctor(request)
    report = build_latest_reading_report(child_id, request)
    profile = get_child_profile(child_id, user)
    parent_email = profile.get("parent_email")
    linked_parent_id = profile.get("owner_parent_id") or profile.get("parent_id")
    if not parent_email:
        raise HTTPException(
            status_code=409,
            detail="This child profile has no parent contact email. Add a contact email before sending the report.",
        )
    parent_linked = bool(linked_parent_id)
    alert_parent_id = linked_parent_id or f"unlinked:{child_id}:{parent_email.strip().lower()}"

    pdf_bytes = main.generate_pdf_report(report, filename=None)
    subject = f"NEOCARE recommendation report for {report['child_name']}"
    message = (
        "The clinic has shared the latest NEOCARE recommendation report for "
        f"{report['child_name']}. The PDF is attached to this email.\n\n"
        "This report is informational only and is not a diagnosis or medical advice. "
        "Please contact a qualified pediatric clinician if you have concerns."
    )
    if parent_linked:
        message += "\nThe report is also available in the Recent Alerts section of your NEOCARE account."
    else:
        message += (
            "\nThis report is saved in the clinic's Recent Parent Alerts. "
            "Create and link a parent account to access reports in the parent portal."
        )
    alert_id = auth_store.add_alert(
        child_id=child_id,
        parent_id=alert_parent_id,
        child_name=report["child_name"],
        severity=report["risk_status"],
        subject=subject,
        message=message,
        email_status="not_configured",
        pdf_data=pdf_bytes,
    )

    auth_store.enqueue_alert_email(alert_id, parent_email, subject, message, pdf_bytes)
    email_status = deliver_pending_alert_emails(limit=1).get(alert_id, "queued")
    auth_store.record_audit("doctor", user["user_id"], "report.shared", str(alert_id), {"result": email_status})

    if email_status == "sent":
        result_message = f"PDF report emailed to {parent_email} and saved in clinic Recent Parent Alerts."
        if parent_linked:
            result_message += " It is also available in the parent's Recent Alerts."
        else:
            result_message += " The parent needs an account linked to this child to access it in the parent portal."
    elif email_status == "queued":
        result_message = "PDF report was saved in clinic Recent Parent Alerts and queued for email delivery."
    elif email_status == "not_configured":
        result_message = (
            "PDF report was saved in clinic Recent Parent Alerts, but email is not configured. "
            "Set SMTP_HOST and SMTP_FROM on the server to send email."
        )
    else:
        result_message = (
            "PDF report was saved in clinic Recent Parent Alerts, but email delivery failed. "
            "A retry is queued; the clinic can check delivery status in Recent Parent Alerts."
        )
    if not parent_linked:
        result_message += (
            " This child has no linked parent account, so the parent portal cannot show this alert yet."
        )
    return {
        "status": "saved",
        "alert_id": alert_id,
        "email_status": email_status,
        "message": result_message,
    }


@app.delete("/api/v1/children/{child_id}")
def delete_child(child_id: str, request: Request):
    user = current_user(request)
    if user["role"] != "doctor":
        raise HTTPException(status_code=403, detail="Only clinic accounts can delete child profiles.")
    get_child_profile(child_id, user)
    main.db.reference("neocare_system/children_profiles").child(child_id).delete()
    auth_store.record_audit("doctor", user["user_id"], "child.deleted", child_id)
    return {"status": "deleted", "child_id": child_id}


@app.get("/api/v1/alerts")
def list_alerts(request: Request):
    user = current_user(request)
    return auth_store.list_alerts(user["role"], user["user_id"])


@app.delete("/api/v1/alerts/{alert_id}")
def delete_alert(alert_id: int, request: Request):
    user = require_doctor(request)
    if not auth_store.delete_alert(alert_id):
        raise HTTPException(status_code=404, detail="Alert not found.")
    auth_store.record_audit("doctor", user["user_id"], "alert.deleted", str(alert_id))
    return {"status": "deleted", "alert_id": alert_id}


@app.patch("/api/v1/alerts/{alert_id}")
def update_alert(alert_id: int, payload: AlertUpdate, request: Request):
    user = require_doctor(request)
    if auth_store.get_alert(alert_id) is None:
        raise HTTPException(status_code=404, detail="Alert not found.")
    if payload.workflow_status is not None:
        if not auth_store.update_alert_status(alert_id, payload.workflow_status, user["user_id"]):
            raise HTTPException(status_code=404, detail="Alert not found.")
        auth_store.record_audit("doctor", user["user_id"], "alert.status_changed", str(alert_id), {"status": payload.workflow_status})
    if payload.note is not None:
        if not auth_store.add_alert_note(alert_id, user["user_id"], payload.note):
            raise HTTPException(status_code=404, detail="Alert not found.")
        auth_store.record_audit("doctor", user["user_id"], "alert.note_added", str(alert_id))
    return {"status": "updated", "alert_id": alert_id}


@app.get("/api/v1/doctor/accounts")
def doctor_accounts(request: Request):
    require_doctor(request)
    return {"doctors": auth_store.list_doctors()}


@app.post("/api/v1/doctor/accounts", status_code=201)
def create_doctor_account(payload: DoctorAccount, request: Request):
    user = require_doctor(request)
    doctor_id = f"doctor_{uuid.uuid4().hex}"
    try:
        auth_store.create_doctor(doctor_id, payload.username, payload.display_name, payload.password)
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="That clinician username is already registered.") from None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    auth_store.record_audit("doctor", user["user_id"], "doctor.created", doctor_id)
    return {"status": "created", "doctor_id": doctor_id}


@app.get("/api/v1/doctor/audit")
def doctor_audit(request: Request):
    require_doctor(request)
    return {"events": auth_store.list_audit()}


@app.get("/api/v1/alerts/{alert_id}/pdf")
def download_alert_pdf(alert_id: int, request: Request):
    user = current_user(request)
    alert_pdf = auth_store.get_alert_pdf(alert_id, user["role"], user["user_id"])
    if alert_pdf is None or alert_pdf["pdf_data"] is None:
        raise HTTPException(status_code=404, detail="Alert PDF not found.")
    return StreamingResponse(
        BytesIO(alert_pdf["pdf_data"]),
        media_type="application/pdf",
        headers={
            "Content-Disposition": (
                f'attachment; filename="NEOCARE_{alert_pdf["child_id"]}_Alert_{alert_id}.pdf"'
            ),
            "Cache-Control": "no-store",
        },
    )


@app.get("/api/v1/doctor/alert-thresholds")
def get_doctor_thresholds(request: Request):
    require_doctor(request)
    return {"thresholds": auth_store.get_thresholds()}


@app.put("/api/v1/doctor/alert-thresholds")
def set_doctor_thresholds(thresholds: AlertThresholds, request: Request):
    user = require_doctor(request)
    values = thresholds.model_dump()
    auth_store.save_thresholds(values)
    auth_store.record_audit("doctor", user["user_id"], "thresholds.updated", "clinic", {"fields": list(values)})
    return {"status": "saved", "thresholds": values}


@app.post("/api/v1/readings")
def receive_reading(
    reading: SensorReading,
    x_api_key: str | None = Header(default=None),
):
    verify_device_key(x_api_key)

    root_ref = main.db.reference("neocare_system")
    profile = root_ref.child("children_profiles").child(reading.child_id).get()
    if not profile:
        raise HTTPException(status_code=404, detail="Unknown child_id.")

    record = {
        "child_id": reading.child_id,
        "child_name": profile["name"],
        "age_years": profile["age_years"],
        "heart_rate_bpm": reading.heart_rate_bpm,
        "spo2_percent": reading.spo2_percent,
        "temperature_c": reading.temperature_c,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source_sensors": ["MAX30102", "MAX30205"],
    }
    if reading.resp_rate is not None:
        record["respiratory_rate_br_min"] = reading.resp_rate
    if reading.activity is not None:
        record["activity_state"] = reading.activity
    auth_store.record_reading(reading.child_id, record)
    root_ref.child("live_monitoring").child(reading.child_id).set(record)
    thresholds = auth_store.get_thresholds()
    status = latest_child_status(profile, record, thresholds)
    status_severity = alert_severity(profile, record, thresholds)
    notification_status = "thresholds_not_configured"
    alert_id = None
    if thresholds is not None:
        severity_name = status["risk_status"]
        subject = f"NEOCARE {severity_name} reading alert for {profile['name']}"
        alert_message = (
            f"Latest readings for {reading.child_id} crossed a clinic-configured {severity_name.lower()} "
            f"threshold at {record['timestamp']}. {status['condition']}. "
            "This automated notice is not a diagnosis. "
            + " ".join(status.get("safety_recommendations", []))
        )
        parent_id = profile.get("owner_parent_id") or profile.get("parent_id") or f"unlinked:{reading.child_id}"
        # The comparison, notice, outbox and new episode severity commit together
        # so crashes and concurrent API workers cannot split the transition.
        episode = auth_store.record_alert_episode(
            reading.child_id, parent_id, profile["name"], severity_name,
            status_severity, subject, alert_message, profile.get("parent_email"),
        )
        alert_id = episode["alert_id"]
        notification_status = episode["notification_status"]
    # One attempt per request bounds the ingestion delay. The background worker
    # also retries notices when no further sensor readings arrive.
    delivery_results = deliver_pending_alert_emails(limit=1)
    if alert_id in delivery_results:
        notification_status = delivery_results[alert_id]

    return {
        "status": "stored",
        "child_id": reading.child_id,
        "timestamp": record["timestamp"],
        "measurements_received": ["heart_rate_bpm", "spo2_percent", "temperature_c"],
        "notification_status": notification_status,
    }
