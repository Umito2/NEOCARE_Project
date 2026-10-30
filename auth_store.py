import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import time
import re
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path


DB_PATH = Path(os.getenv("NEOCARE_AUTH_DB", Path(__file__).with_name("neocare_auth.sqlite3")))
PBKDF2_ROUNDS = 480_000
SESSION_SECONDS = 12 * 60 * 60
SCHEMA_VERSION = 2
MAX_EMAIL_ATTEMPTS = 8


@contextmanager
def connect():
    journal_mode = os.getenv("NEOCARE_SQLITE_JOURNAL_MODE", "WAL").strip().upper()
    if journal_mode not in {"WAL", "DELETE"}:
        raise ValueError("NEOCARE_SQLITE_JOURNAL_MODE must be WAL or DELETE")
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH, timeout=15)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute(f"PRAGMA journal_mode={journal_mode}")
        connection.execute("PRAGMA foreign_keys=ON")
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _backup_before_migration():
    """Keep one verified snapshot per target schema version before changing data."""
    if not DB_PATH.exists() or DB_PATH.stat().st_size == 0:
        return
    with closing(sqlite3.connect(DB_PATH.resolve().as_uri() + "?mode=ro", uri=True)) as source:
        if source.execute("PRAGMA user_version").fetchone()[0] >= SCHEMA_VERSION:
            return
        if not source.execute("SELECT 1 FROM sqlite_master WHERE type='table' LIMIT 1").fetchone():
            return
        directory = DB_PATH.parent / ".backups"
        directory.mkdir(parents=True, exist_ok=True)
        database_id = hashlib.sha256(str(DB_PATH.resolve()).encode("utf-8")).hexdigest()[:12]
        destination = directory / f"pre-{database_id}-schema-v{SCHEMA_VERSION}.sqlite3"
        if destination.exists():
            with closing(sqlite3.connect(destination.resolve().as_uri() + "?mode=ro", uri=True)) as existing:
                if existing.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise RuntimeError("The existing pre-migration backup failed its integrity check")
            return
        temporary = directory / f"pre-schema-v{SCHEMA_VERSION}-{secrets.token_hex(6)}.tmp"
        try:
            with closing(sqlite3.connect(temporary)) as snapshot:
                source.backup(snapshot)
                if snapshot.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise RuntimeError("The pre-migration backup failed its integrity check")
            temporary.replace(destination)
        finally:
            if temporary.exists():
                temporary.unlink()


def initialize():
    _backup_before_migration()
    with connect() as db:
        db.executescript(
            """
            BEGIN IMMEDIATE;
            CREATE TABLE IF NOT EXISTS parents (
                parent_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                phone TEXT NOT NULL,
                password_salt BLOB NOT NULL,
                password_hash BLOB NOT NULL,
                created_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sessions (
                token_hash TEXT PRIMARY KEY,
                role TEXT NOT NULL,
                user_id TEXT NOT NULL,
                display_name TEXT NOT NULL,
                expires_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS alert_state (
                child_id TEXT PRIMARY KEY,
                severity INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS alerts (
                alert_id INTEGER PRIMARY KEY AUTOINCREMENT,
                child_id TEXT NOT NULL,
                parent_id TEXT NOT NULL,
                child_name TEXT NOT NULL,
                severity TEXT NOT NULL,
                subject TEXT NOT NULL,
                message TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                email_status TEXT NOT NULL,
                pdf_data BLOB
            );
            CREATE TABLE IF NOT EXISTS doctors (
                doctor_id TEXT PRIMARY KEY,
                username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                display_name TEXT NOT NULL,
                password_salt BLOB NOT NULL,
                password_hash BLOB NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS reading_history (
                reading_id INTEGER PRIMARY KEY AUTOINCREMENT,
                child_id TEXT NOT NULL,
                measured_at REAL NOT NULL,
                timestamp TEXT NOT NULL,
                payload TEXT NOT NULL,
                UNIQUE(child_id, timestamp)
            );
            CREATE INDEX IF NOT EXISTS reading_history_child_time ON reading_history(child_id, measured_at);
            CREATE TABLE IF NOT EXISTS audit_events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                actor_role TEXT NOT NULL,
                actor_id TEXT NOT NULL,
                action TEXT NOT NULL,
                target TEXT NOT NULL,
                details TEXT NOT NULL DEFAULT '{}',
                created_at INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS audit_events_time ON audit_events(created_at);
            CREATE TABLE IF NOT EXISTS alert_notes (
                note_id INTEGER PRIMARY KEY AUTOINCREMENT,
                alert_id INTEGER NOT NULL REFERENCES alerts(alert_id) ON DELETE CASCADE,
                actor_id TEXT NOT NULL,
                text TEXT NOT NULL,
                created_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS email_outbox (
                alert_id INTEGER PRIMARY KEY REFERENCES alerts(alert_id) ON DELETE CASCADE,
                recipient TEXT NOT NULL,
                subject TEXT NOT NULL,
                message TEXT NOT NULL,
                pdf_data BLOB,
                status TEXT NOT NULL DEFAULT 'pending',
                attempts INTEGER NOT NULL DEFAULT 0,
                next_attempt_at INTEGER NOT NULL,
                lease_until INTEGER,
                error_code TEXT,
                updated_at INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS email_outbox_due ON email_outbox(status, next_attempt_at);
            """
        )
        alert_columns = {
            row["name"] for row in db.execute("PRAGMA table_info(alerts)").fetchall()
        }
        if "pdf_data" not in alert_columns:
            db.execute("ALTER TABLE alerts ADD COLUMN pdf_data BLOB")
        for column, definition in {
            "workflow_status": "TEXT NOT NULL DEFAULT 'new'",
            "status_updated_at": "INTEGER",
            "status_updated_by": "TEXT",
        }.items():
            if column not in alert_columns:
                db.execute(f"ALTER TABLE alerts ADD COLUMN {column} {definition}")
        db.execute(f"PRAGMA user_version={SCHEMA_VERSION}")


def hash_password(password, salt=None):
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PBKDF2_ROUNDS
    )
    return salt, digest


def create_parent(parent_id, name, email, phone, password):
    salt, digest = hash_password(password)
    with connect() as db:
        db.execute(
            """
            INSERT INTO parents(parent_id, name, email, phone, password_salt, password_hash, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (parent_id, name, email, phone, salt, digest, int(time.time())),
        )


def authenticate_parent(email, password):
    with connect() as db:
        row = db.execute(
            "SELECT * FROM parents WHERE email = ?", (email,)
        ).fetchone()
    if row is None:
        hash_password(password, b"\0" * 16)
        return None
    _, candidate = hash_password(password, row["password_salt"])
    if not hmac.compare_digest(candidate, row["password_hash"]):
        return None
    return {
        "role": "parent",
        "user_id": row["parent_id"],
        "display_name": row["name"],
        "email": row["email"],
    }


def parent_by_id(parent_id):
    with connect() as db:
        row = db.execute(
            "SELECT parent_id, name, email, phone FROM parents WHERE parent_id = ?",
            (parent_id,),
        ).fetchone()
    return dict(row) if row else None


def parent_by_email(email):
    with connect() as db:
        row = db.execute(
            "SELECT parent_id, name, email, phone FROM parents WHERE email = ?",
            (email,),
        ).fetchone()
    return dict(row) if row else None


def create_session(role, user_id, display_name):
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    with connect() as db:
        db.execute("DELETE FROM sessions WHERE expires_at <= ?", (int(time.time()),))
        db.execute(
            "INSERT INTO sessions(token_hash, role, user_id, display_name, expires_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                token_hash,
                role,
                user_id,
                display_name,
                int(time.time()) + SESSION_SECONDS,
            ),
        )
    return token


def get_session(token):
    if not token:
        return None
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    with connect() as db:
        row = db.execute(
            "SELECT role, user_id, display_name, expires_at FROM sessions WHERE token_hash = ?",
            (token_hash,),
        ).fetchone()
        if row is None:
            return None
        if row["expires_at"] <= int(time.time()):
            db.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))
            return None
    return dict(row)


def delete_session(token):
    if not token:
        return
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    with connect() as db:
        db.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))


def save_alert_severity(child_id, severity):
    with connect() as db:
        db.execute(
            """
            INSERT INTO alert_state(child_id, severity, updated_at) VALUES (?, ?, ?)
            ON CONFLICT(child_id) DO UPDATE SET severity=excluded.severity, updated_at=excluded.updated_at
            """,
            (child_id, severity, int(time.time())),
        )


def get_alert_severity(child_id):
    with connect() as db:
        row = db.execute(
            "SELECT severity FROM alert_state WHERE child_id = ?", (child_id,)
        ).fetchone()
    return row["severity"] if row else 0


def add_alert(
    child_id, parent_id, child_name, severity, subject, message, email_status, pdf_data=None
):
    with connect() as db:
        cursor = db.execute(
            """
            INSERT INTO alerts(
                child_id, parent_id, child_name, severity, subject, message,
                created_at, email_status, pdf_data
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                child_id,
                parent_id,
                child_name,
                severity,
                subject,
                message,
                int(time.time()),
                email_status,
                pdf_data,
            ),
        )
        return cursor.lastrowid


def update_alert_email_status(alert_id, email_status):
    with connect() as db:
        db.execute(
            "UPDATE alerts SET email_status = ? WHERE alert_id = ?",
            (email_status, alert_id),
        )


def delete_alert(alert_id):
    with connect() as db:
        db.execute("DELETE FROM email_outbox WHERE alert_id = ?", (alert_id,))
        db.execute("DELETE FROM alert_notes WHERE alert_id = ?", (alert_id,))
        cursor = db.execute("DELETE FROM alerts WHERE alert_id = ?", (alert_id,))
        return cursor.rowcount == 1


def get_alert_pdf(alert_id, role, user_id):
    query = "SELECT child_id, pdf_data FROM alerts WHERE alert_id = ?"
    parameters = [alert_id]
    if role == "parent":
        query += " AND parent_id = ?"
        parameters.append(user_id)
    with connect() as db:
        row = db.execute(query, parameters).fetchone()
    if row is None:
        return None
    return {"child_id": row["child_id"], "pdf_data": row["pdf_data"]}


def list_alerts(role, user_id, limit=100):
    query = (
        "SELECT alert_id, child_id, parent_id, child_name, severity, subject, "
        "message, created_at, email_status, workflow_status, status_updated_at, status_updated_by, "
        "pdf_data IS NOT NULL AS pdf_available "
        "FROM alerts "
    )
    parameters = []
    if role == "parent":
        query += "WHERE parent_id = ? "
        parameters.append(user_id)
    query += "ORDER BY created_at DESC, alert_id DESC LIMIT ?"
    parameters.append(_bounded_limit(limit, 1000))
    with connect() as db:
        rows = db.execute(query, parameters).fetchall()
        return [_alert_details(db, row, include_notes=role == "doctor") for row in rows]


def get_thresholds():
    with connect() as db:
        row = db.execute(
            "SELECT value FROM settings WHERE key = 'alert_thresholds'"
        ).fetchone()
    return json.loads(row["value"]) if row else None


def save_thresholds(value):
    with connect() as db:
        db.execute(
            "INSERT INTO settings(key, value) VALUES ('alert_thresholds', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (json.dumps(value),),
        )


def _bounded_limit(limit, maximum):
    return max(1, min(int(limit), maximum))


def _doctor_dict(row):
    if row is None:
        return None
    value = dict(row)
    value["id"] = value["doctor_id"]
    value["is_active"] = bool(value["is_active"])
    return value


def create_doctor(doctor_id, username, display_name, password):
    username = username.strip().lower()
    display_name = display_name.strip()
    if not re.fullmatch(r"[a-z0-9][a-z0-9._@-]{2,79}", username):
        raise ValueError("Clinician username must contain 3 to 80 letters, numbers, or . _ @ -")
    if not display_name or len(display_name) > 80:
        raise ValueError("Clinician display name must contain 1 to 80 characters")
    if not 12 <= len(password) <= 128:
        raise ValueError("Clinician password must contain 12 to 128 characters")
    salt, digest = hash_password(password)
    with connect() as db:
        db.execute(
            "INSERT INTO doctors(doctor_id,username,display_name,password_salt,password_hash,created_at) VALUES (?,?,?,?,?,?)",
            (doctor_id, username, display_name, salt, digest, int(time.time())),
        )
    return doctor_by_username(username)


def doctor_by_username(username):
    with connect() as db:
        row = db.execute(
            "SELECT doctor_id,username,display_name,is_active,created_at FROM doctors WHERE username=?",
            (username.strip().lower(),),
        ).fetchone()
    return _doctor_dict(row)


def list_doctors():
    with connect() as db:
        rows = db.execute(
            "SELECT doctor_id,username,display_name,is_active,created_at FROM doctors ORDER BY display_name,doctor_id LIMIT 1000"
        ).fetchall()
    return [_doctor_dict(row) for row in rows]


def authenticate_doctor(username, password):
    with connect() as db:
        row = db.execute("SELECT * FROM doctors WHERE username=?", (username.strip().lower(),)).fetchone()
    if row is None:
        hash_password(password, b"\0" * 16)
        return None
    _, candidate = hash_password(password, row["password_salt"])
    if not hmac.compare_digest(candidate, row["password_hash"]) or not row["is_active"]:
        return None
    return {"role": "doctor", "user_id": row["doctor_id"], "display_name": row["display_name"]}


def _timestamp_epoch(value):
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Reading timestamps must include a timezone")
    return parsed.timestamp()


def record_reading(child_id, reading):
    timestamp = reading["timestamp"]
    measured_at = _timestamp_epoch(timestamp)
    allowed = {
        "timestamp", "heart_rate_bpm", "spo2_percent", "temperature_c",
        "respiratory_rate_br_min", "activity_state", "age_years", "source_sensors",
        "signal_quality", "device_id",
    }
    payload = {key: value for key, value in reading.items() if key in allowed}
    payload["child_id"] = child_id
    with connect() as db:
        db.execute(
            "INSERT OR IGNORE INTO reading_history(child_id,measured_at,timestamp,payload) VALUES (?,?,?,?)",
            (child_id, measured_at, timestamp, json.dumps(payload, allow_nan=False)),
        )
        return db.execute("SELECT reading_id FROM reading_history WHERE child_id=? AND timestamp=?", (child_id, timestamp)).fetchone()["reading_id"]


def list_readings(child_id, since_timestamp, limit=1000):
    """Return real samples across the window, preserving extrema when sampling is needed."""
    cutoff = _timestamp_epoch(since_timestamp)
    limit = _bounded_limit(limit, 1000)
    with connect() as db:
        # Count and sample one consistent WAL snapshot while ingestion continues.
        db.execute("BEGIN")
        count = db.execute("SELECT COUNT(*) FROM reading_history WHERE child_id=? AND measured_at>=?", (child_id, cutoff)).fetchone()[0]
        if count <= limit:
            rows = db.execute(
                "SELECT payload FROM reading_history WHERE child_id=? AND measured_at>=? ORDER BY measured_at,reading_id LIMIT ?",
                (child_id, cutoff, limit),
            ).fetchall()
        else:
            indices = _sample_reading_indices(db, child_id, cutoff, count, limit)
            placeholders = ",".join("?" for _ in indices)
            rows = db.execute(
                "WITH ranked AS (SELECT payload,ROW_NUMBER() OVER(ORDER BY measured_at,reading_id) AS rn "
                "FROM reading_history WHERE child_id=? AND measured_at>=?) "
                f"SELECT payload FROM ranked WHERE rn IN ({placeholders}) ORDER BY rn",
                [child_id, cutoff, *indices],
            ).fetchall()
    return [json.loads(row["payload"]) for row in rows]


def count_readings(child_id, since_timestamp):
    with connect() as db:
        return db.execute("SELECT COUNT(*) FROM reading_history WHERE child_id=? AND measured_at>=?", (child_id, _timestamp_epoch(since_timestamp))).fetchone()[0]


def used_history_child_ids():
    """Reserve historic identifiers so a recreated profile cannot inherit another child's data."""
    with connect() as db:
        return {row[0] for row in db.execute("SELECT DISTINCT child_id FROM reading_history")}


def _sample_reading_indices(db, child_id, cutoff, count, limit):
    if limit == 1:
        return [count]
    if limit < 10:
        return [round(index * (count - 1) / (limit - 1)) + 1 for index in range(limit)]
    # Each bucket contributes at most eight actual measurements: the min/max
    # of four vital signs. This retains spikes that uniform sampling can miss.
    buckets = max(1, (limit - 2) // 8)
    bucket_size = (count + buckets - 1) // buckets
    metrics = {"hr": "heart_rate_bpm", "spo2": "spo2_percent", "temp": "temperature_c", "rr": "respiratory_rate_br_min"}
    values = ",".join(f"CAST(json_extract(payload,'$.{field}') AS REAL) AS {alias}" for alias, field in metrics.items())
    extrema = ",".join(f"MIN({alias}) AS {alias}_min,MAX({alias}) AS {alias}_max" for alias in metrics)
    indices = ",".join(f"MIN(CASE WHEN r.{alias}=e.{alias}_{bound} THEN rn END) AS {alias}_{bound}_rn" for alias in metrics for bound in ("min", "max"))
    rows = db.execute(
        f"WITH ranked AS (SELECT ROW_NUMBER() OVER(ORDER BY measured_at,reading_id) AS rn,{values} "
        "FROM reading_history WHERE child_id=? AND measured_at>=?), "
        f"buckets AS (SELECT *,CAST((rn-1)/? AS INTEGER) AS bucket FROM ranked), "
        f"extrema AS (SELECT bucket,{extrema} FROM buckets GROUP BY bucket) "
        f"SELECT {indices} FROM buckets r JOIN extrema e ON r.bucket=e.bucket GROUP BY r.bucket",
        (child_id, cutoff, bucket_size),
    ).fetchall()
    chosen = {1, count}
    for row in rows:
        chosen.update(value for value in row if value is not None)
    for index in range(limit):
        if len(chosen) >= limit:
            break
        chosen.add(round(index * (count - 1) / (limit - 1)) + 1)
    return sorted(chosen)


def record_audit(actor_role, actor_id, action, target, details=None):
    """Store event identities and limited metadata, never free-form request/health payloads."""
    safe = {}
    if isinstance(details, dict):
        states = {"new", "acknowledged", "resolved", "sent", "failed", "created", "deleted", "success", "error", "rejected", "not_configured"}
        for key in ("status", "result"):
            if isinstance(details.get(key), str) and details[key] in states:
                safe[key] = details[key]
        if isinstance(details.get("count"), int) and 0 <= details["count"] <= 1000000:
            safe["count"] = details["count"]
        if isinstance(details.get("fields"), list):
            safe["fields"] = [field for field in details["fields"][:30] if isinstance(field, str) and re.fullmatch(r"[a-z][a-z0-9_]{0,49}", field)]
    with connect() as db:
        cursor = db.execute(
            "INSERT INTO audit_events(actor_role,actor_id,action,target,details,created_at) VALUES (?,?,?,?,?,?)",
            (str(actor_role)[:30], str(actor_id)[:128], str(action)[:100], str(target)[:160], json.dumps(safe), int(time.time())),
        )
        return cursor.lastrowid


def list_audit(limit=100):
    with connect() as db:
        rows = db.execute("SELECT * FROM audit_events ORDER BY created_at DESC,event_id DESC LIMIT ?", (_bounded_limit(limit, 1000),)).fetchall()
    return [{**dict(row), "details": json.loads(row["details"])} for row in rows]


def _alert_details(db, row, include_notes=True):
    alert = dict(row)
    alert["lifecycle_status"] = alert["workflow_status"]
    notes = db.execute(
        "SELECT n.text,n.actor_id,n.created_at,COALESCE(d.display_name,n.actor_id) AS author "
        "FROM alert_notes n LEFT JOIN doctors d ON d.doctor_id=n.actor_id WHERE alert_id=? ORDER BY note_id",
        (alert["alert_id"],),
    ).fetchall() if include_notes else []
    alert["notes"] = [dict(note) for note in notes]
    outbox = db.execute("SELECT attempts,next_attempt_at,status,error_code FROM email_outbox WHERE alert_id=?", (alert["alert_id"],)).fetchone()
    alert["delivery_attempts"] = outbox["attempts"] if outbox else 0
    alert["next_retry_at"] = outbox["next_attempt_at"] if outbox and outbox["status"] in ("pending", "retry", "processing") else None
    alert["delivery_error"] = outbox["error_code"] if outbox else None
    return alert


def get_alert(alert_id):
    with connect() as db:
        row = db.execute("SELECT *,pdf_data IS NOT NULL AS pdf_available FROM alerts WHERE alert_id=?", (alert_id,)).fetchone()
        return _alert_details(db, row) if row else None


def update_alert_status(alert_id, status, actor_id):
    status = "new" if status == "open" else status
    if status not in ("new", "acknowledged", "resolved"):
        raise ValueError("Invalid alert workflow status")
    with connect() as db:
        cursor = db.execute("UPDATE alerts SET workflow_status=?,status_updated_at=?,status_updated_by=? WHERE alert_id=?", (status, int(time.time()), actor_id, alert_id))
        return cursor.rowcount == 1


def add_alert_note(alert_id, actor_id, note):
    note = note.strip()
    if not note or len(note) > 2000:
        raise ValueError("Clinician notes must contain 1 to 2000 characters")
    with connect() as db:
        if not db.execute("SELECT 1 FROM alerts WHERE alert_id=?", (alert_id,)).fetchone():
            return False
        db.execute("INSERT INTO alert_notes(alert_id,actor_id,text,created_at) VALUES (?,?,?,?)", (alert_id, actor_id, note, int(time.time())))
        return True


def enqueue_alert_email(alert_id, recipient, subject, message, pdf_data=None):
    now = int(time.time())
    with connect() as db:
        if not db.execute("SELECT 1 FROM alerts WHERE alert_id=?", (alert_id,)).fetchone():
            return False
        db.execute(
            "INSERT OR IGNORE INTO email_outbox(alert_id,recipient,subject,message,pdf_data,next_attempt_at,updated_at) VALUES (?,?,?,?,?,?,?)",
            (alert_id, recipient, subject, message, pdf_data, now, now),
        )
        return True


def pending_alert_emails(limit=20, exclude_alert_ids=None):
    """Claim due messages with a lease so simultaneous workers do not duplicate delivery."""
    now = int(time.time())
    excluded = list({int(value) for value in (exclude_alert_ids or [])})[:1000]
    exclusion = " AND alert_id NOT IN (" + ",".join("?" for _ in excluded) + ")" if excluded else ""
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        rows = db.execute(
            "SELECT * FROM email_outbox WHERE attempts<? AND next_attempt_at<=? "
            "AND (status IN ('pending','retry') OR (status='processing' AND lease_until<=?)) "
            + exclusion + " ORDER BY next_attempt_at,alert_id LIMIT ?",
            (MAX_EMAIL_ATTEMPTS, now, now, *excluded, _bounded_limit(limit, 100)),
        ).fetchall()
        for row in rows:
            db.execute("UPDATE email_outbox SET status='processing',lease_until=?,updated_at=? WHERE alert_id=?", (now + 120, now, row["alert_id"]))
    return [dict(row) for row in rows]


def record_alert_episode(child_id, parent_id, child_name, severity_name, severity, subject, message, recipient=None):
    """Atomically create a notice, delivery job, and severity transition across workers."""
    if severity is None:
        return {"alert_id": None, "notification_status": "incomplete_reading_no_alert"}
    if severity not in (0, 1, 2):
        raise ValueError("Invalid alert severity")
    now = int(time.time())
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        previous = db.execute("SELECT severity FROM alert_state WHERE child_id=?", (child_id,)).fetchone()
        previous_severity = previous["severity"] if previous else 0
        if severity == 0:
            db.execute("INSERT INTO alert_state(child_id,severity,updated_at) VALUES (?,0,?) ON CONFLICT(child_id) DO UPDATE SET severity=0,updated_at=excluded.updated_at", (child_id, now))
            return {"alert_id": None, "notification_status": "recovered"}
        if severity <= previous_severity:
            return {"alert_id": None, "notification_status": "same_episode_no_repeat"}
        status = "queued" if recipient else "no_parent_email"
        cursor = db.execute(
            "INSERT INTO alerts(child_id,parent_id,child_name,severity,subject,message,created_at,email_status) VALUES (?,?,?,?,?,?,?,?)",
            (child_id, parent_id, child_name, severity_name, subject, message, now, status),
        )
        alert_id = cursor.lastrowid
        if recipient:
            db.execute(
                "INSERT INTO email_outbox(alert_id,recipient,subject,message,next_attempt_at,updated_at) VALUES (?,?,?,?,?,?)",
                (alert_id, recipient, subject, message, now, now),
            )
        db.execute(
            "INSERT INTO alert_state(child_id,severity,updated_at) VALUES (?,?,?) "
            "ON CONFLICT(child_id) DO UPDATE SET severity=excluded.severity,updated_at=excluded.updated_at",
            (child_id, severity, now),
        )
        return {"alert_id": alert_id, "notification_status": status}


def complete_alert_email(alert_id, status, error=None):
    if status not in ("sent", "failed", "not_configured"):
        raise ValueError("Invalid email delivery result")
    now = int(time.time())
    with connect() as db:
        row = db.execute("SELECT attempts FROM email_outbox WHERE alert_id=?", (alert_id,)).fetchone()
        if row is None:
            return False
        attempts = row["attempts"] + (status != "not_configured")
        state = "sent" if status == "sent" else "failed" if attempts >= MAX_EMAIL_ATTEMPTS else "retry"
        delay = 60 if status == "not_configured" else 0 if attempts == 1 else min(60 * (2 ** (attempts - 2)), 3600)
        error_code = None if status == "sent" else "not_configured" if status == "not_configured" else "delivery_failed"
        db.execute(
            "UPDATE email_outbox SET status=?,attempts=?,next_attempt_at=?,lease_until=NULL,error_code=?,updated_at=? WHERE alert_id=?",
            (state, attempts, now + delay, error_code, now, alert_id),
        )
        db.execute("UPDATE alerts SET email_status=? WHERE alert_id=?", (status, alert_id))
        return True
