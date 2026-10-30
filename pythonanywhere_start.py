"""PythonAnywhere ASGI entry point using private home storage and no local AI."""

import json
import os
from pathlib import Path
import stat
import sys

from cloud_start import (
    CloudConfigurationError,
    credential_file,
    validate_public_credentials,
)


SETTINGS_KEYS = frozenset({
    "DOCTOR_USERNAME", "DOCTOR_PASSWORD", "ESP32_API_KEY",
    "FIREBASE_DATABASE_URL", "FIREBASE_SERVICE_ACCOUNT_JSON",
})


def load_private_settings(home):
    """Read the fixed private config path; never echo its contents in errors."""
    directory = home / ".config" / "neocare"
    path = directory / "settings.json"
    try:
        if any(candidate.is_symlink() for candidate in (home / ".config", directory, path)):
            raise CloudConfigurationError("NEOCARE private configuration must not use symlinks.")
        directory_info = directory.stat()
        if not stat.S_ISDIR(directory_info.st_mode):
            raise CloudConfigurationError("NEOCARE private configuration directory is invalid.")
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "r", encoding="utf-8") as stream:
            file_info = os.fstat(stream.fileno())
            if not stat.S_ISREG(file_info.st_mode):
                raise CloudConfigurationError("NEOCARE settings must be a regular private file.")
            if os.name != "nt" and (
                stat.S_IMODE(file_info.st_mode) != 0o600
                or stat.S_IMODE(directory_info.st_mode) != 0o700
                or file_info.st_uid != os.getuid()
                or directory_info.st_uid != os.getuid()
            ):
                raise CloudConfigurationError(
                    "Set the private settings directory to mode 700 and settings.json to mode 600, owned by this account."
                )
            raw = stream.read(131073)
        if len(raw) > 131072:
            raise CloudConfigurationError("NEOCARE private configuration is too large.")
        settings = json.loads(raw)
    except (OSError, UnicodeError, ValueError) as error:
        if isinstance(error, CloudConfigurationError):
            raise
        raise CloudConfigurationError(
            "Create a valid private ~/.config/neocare/settings.json before starting NEOCARE."
        ) from None

    if not isinstance(settings, dict) or set(settings) != SETTINGS_KEYS:
        raise CloudConfigurationError("NEOCARE settings must contain exactly the five documented configuration keys.")
    if isinstance(settings["FIREBASE_SERVICE_ACCOUNT_JSON"], dict):
        settings["FIREBASE_SERVICE_ACCOUNT_JSON"] = json.dumps(settings["FIREBASE_SERVICE_ACCOUNT_JSON"])
    if any(not isinstance(value, str) for value in settings.values()):
        raise CloudConfigurationError("NEOCARE settings values must be strings; only the Firebase credential may be a JSON object.")
    return settings


def prepare_database(home):
    """Keep SQLite in PythonAnywhere's persistent, private account home."""
    directory = home / "neocare-data"
    path = directory / "neocare_auth.sqlite3"
    try:
        if directory.is_symlink() or path.is_symlink():
            raise CloudConfigurationError("NEOCARE private database paths must not use symlinks.")
        directory.mkdir(mode=0o700, exist_ok=True)
        if not directory.is_dir() or (path.exists() and not path.is_file()):
            raise CloudConfigurationError("NEOCARE private database path is invalid.")
        os.chmod(directory, 0o700)
        if path.exists():
            os.chmod(path, 0o600)
    except OSError:
        raise CloudConfigurationError("Could not prepare NEOCARE private persistent database storage.") from None
    return path


def run():
    raw_socket = os.environ.get("DOMAIN_SOCKET", "")
    socket_path = Path(raw_socket)
    if not raw_socket or "\x00" in raw_socket or not socket_path.is_absolute() or socket_path.is_symlink():
        raise CloudConfigurationError("PythonAnywhere must provide an absolute DOMAIN_SOCKET path.")

    home = Path.home()
    settings = load_private_settings(home)
    _, credentials = validate_public_credentials(settings)
    database_path = prepare_database(home)
    os.environ.update(settings)
    os.environ["NEOCARE_RECOMMENDATION_MODE"] = "rules"
    os.environ["NEOCARE_SQLITE_JOURNAL_MODE"] = "DELETE"
    os.environ["NEOCARE_AUTH_DB"] = str(database_path)

    previous_umask = os.umask(0o077)
    try:
        with credential_file(credentials) as path:
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(path)
            os.environ.pop("FIREBASE_SERVICE_ACCOUNT_JSON", None)
            import uvicorn

            # The managed Unix socket is reached through PythonAnywhere's HTTPS proxy.
            uvicorn.run(
                "api:app", uds=str(socket_path), workers=1,
                proxy_headers=True, forwarded_allow_ips="*", access_log=False,
            )
    except OSError:
        raise CloudConfigurationError("Could not start NEOCARE with private credentials and the managed socket.") from None
    finally:
        os.umask(previous_umask)


if __name__ == "__main__":
    try:
        run()
    except CloudConfigurationError as error:
        print(f"NEOCARE cloud configuration: {error}", file=sys.stderr)
        raise SystemExit(2) from None
