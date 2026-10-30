"""Railway-only entry point: persistent data, explicit secrets, no local AI."""

from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from urllib.parse import urlsplit


VOLUME_ROOT = Path("/data")


class CloudConfigurationError(ValueError):
    """A safe-to-display configuration error; never include secret values."""


def _has_volume_mount(path):
    """Recognize ordinary and bind mounts, including Railway's volume mount."""
    if path.is_mount():
        return True
    try:
        lines = Path("/proc/self/mountinfo").read_text(encoding="utf-8").splitlines()
    except OSError:
        return False
    for line in lines:
        fields = line.split()
        if len(fields) > 4:
            mount_path = re.sub(
                r"\\([0-7]{3})", lambda match: chr(int(match.group(1), 8)), fields[4]
            )
            if Path(mount_path) == path:
                return True
    return False


def validate_public_credentials(environ):
    """Validate public-server secrets and return (port, service_account_dict).

    The mapping contains string environment values. Validation has no filesystem,
    database or network side effects; storage validation belongs to each host.
    """
    username = environ.get("DOCTOR_USERNAME", "")
    password = environ.get("DOCTOR_PASSWORD", "")
    device_key = environ.get("ESP32_API_KEY", "")
    if not 3 <= len(username.strip()) <= 80 or username != username.strip():
        raise CloudConfigurationError("Set an explicit DOCTOR_USERNAME of 3–80 characters.")
    if not 12 <= len(password) <= 128 or not password.strip() or password == "123456789":
        raise CloudConfigurationError("Set a unique DOCTOR_PASSWORD of 12–128 characters.")
    if len(device_key) < 24 or device_key != device_key.strip():
        raise CloudConfigurationError("Set an ESP32_API_KEY of at least 24 characters.")

    try:
        port = int(environ.get("PORT", "8000"))
    except (TypeError, ValueError):
        raise CloudConfigurationError("PORT must be an integer from 1 to 65535.") from None
    if not 1 <= port <= 65535:
        raise CloudConfigurationError("PORT must be an integer from 1 to 65535.")

    try:
        database_url = urlsplit(environ.get("FIREBASE_DATABASE_URL", ""))
        hostname = database_url.hostname or ""
        valid_database = (
            database_url.scheme == "https"
            and hostname.endswith((".firebaseio.com", ".firebasedatabase.app"))
            and database_url.username is None
            and database_url.password is None
            and database_url.port in (None, 443)
            and database_url.path in ("", "/")
            and not database_url.query
            and not database_url.fragment
        )
    except ValueError:
        valid_database = False
    if not valid_database:
        raise CloudConfigurationError("Set FIREBASE_DATABASE_URL to the intended HTTPS Firebase database URL.")

    raw_credentials = environ.get("FIREBASE_SERVICE_ACCOUNT_JSON", "")
    if not raw_credentials or len(raw_credentials) > 65536:
        raise CloudConfigurationError("Set FIREBASE_SERVICE_ACCOUNT_JSON as a private server secret.")
    try:
        credentials = json.loads(raw_credentials)
    except (TypeError, ValueError):
        raise CloudConfigurationError("FIREBASE_SERVICE_ACCOUNT_JSON must contain valid JSON.") from None
    if not isinstance(credentials, dict):
        raise CloudConfigurationError("FIREBASE_SERVICE_ACCOUNT_JSON must contain a service-account object.")
    private_key = credentials.get("private_key", "")
    client_email = credentials.get("client_email", "")
    project_id = credentials.get("project_id", "")
    if (
        credentials.get("type") != "service_account"
        or not isinstance(project_id, str)
        or not project_id.strip()
        or not isinstance(client_email, str)
        or not re.fullmatch(r"[^\s@]+@[^\s@]+\.gserviceaccount\.com", client_email)
        or not isinstance(private_key, str)
        or not private_key.startswith("-----BEGIN PRIVATE KEY-----\n")
        or not private_key.rstrip().endswith("-----END PRIVATE KEY-----")
        or credentials.get("token_uri") != "https://oauth2.googleapis.com/token"
    ):
        raise CloudConfigurationError(
            "FIREBASE_SERVICE_ACCOUNT_JSON is not a supported Firebase service-account credential."
        )
    return port, credentials


def validate_configuration(environ):
    """Validate Railway secrets and storage before importing the application."""
    port, credentials = validate_public_credentials(environ)
    try:
        root = VOLUME_ROOT.resolve(strict=True)
        raw_database_path = environ.get("NEOCARE_AUTH_DB", "")
        database_path = Path(raw_database_path)
        valid_storage = (
            bool(raw_database_path)
            and database_path.is_absolute()
            and VOLUME_ROOT.is_dir()
            and not VOLUME_ROOT.is_symlink()
            and _has_volume_mount(root)
            and database_path.resolve().is_relative_to(root)
            and database_path.resolve() != root
            and not database_path.is_dir()
        )
    except (OSError, RuntimeError):
        valid_storage = False
    if not valid_storage:
        raise CloudConfigurationError(
            "Attach a persistent Railway volume at /data and set "
            "NEOCARE_AUTH_DB=/data/neocare_auth.sqlite3."
        )
    return port, database_path.resolve(), credentials


@contextmanager
def credential_file(credentials):
    """Keep SDK credentials in a private, ephemeral file outside application/data."""
    with tempfile.TemporaryDirectory(prefix="neocare-credentials-") as directory:
        os.chmod(directory, 0o700)
        path = Path(directory) / "firebase-service-account.json"
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(credentials, stream)
        yield path


def run():
    port, database_path, credentials = validate_configuration(os.environ)
    # This entry point deliberately has no model/runtime installation path.
    os.environ["NEOCARE_RECOMMENDATION_MODE"] = "rules"
    os.environ["NEOCARE_AUTH_DB"] = str(database_path)
    with credential_file(credentials) as path:
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(path)
        os.environ.pop("FIREBASE_SERVICE_ACCOUNT_JSON", None)
        import uvicorn

        # Railway's HTTPS edge is the sole public ingress for this container.
        # Trust its forwarded scheme so the app sets Secure session cookies.
        uvicorn.run(
            "api:app", host="0.0.0.0", port=port, workers=1,
            proxy_headers=True, forwarded_allow_ips="*", access_log=False,
        )


if __name__ == "__main__":
    try:
        run()
    except CloudConfigurationError as error:
        print(f"NEOCARE cloud configuration: {error}", file=sys.stderr)
        raise SystemExit(2) from None
