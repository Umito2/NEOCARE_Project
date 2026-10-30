"""Verified local backups of BOTH SQLite and the Firebase neocare_system subtree.

Create and verify are non-destructive. Restore is an explicit maintenance command,
requires two confirmation flags, and makes a complete pre-restore safety backup.
Backups contain private application data and must stay outside version control.
"""

import argparse
import hashlib
import json
import os
import secrets
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

import auth_store


BACKUP_FORMAT = 1
APP_SUBTREE = "neocare_system"


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _check_sqlite(path):
    with closing(sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)) as connection:
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("SQLite backup failed its integrity check")
        if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise ValueError("SQLite backup contains broken foreign-key references")


def _copy_sqlite(source, destination, allow_missing=False):
    source, destination = Path(source), Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not source.is_file():
        if not allow_missing:
            raise FileNotFoundError("The SQLite database does not exist")
        with closing(sqlite3.connect(destination)) as empty:
            empty.execute("PRAGMA user_version=0")
            empty.commit()
        return
    with closing(sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)) as original:
        with closing(sqlite3.connect(destination)) as snapshot:
            original.backup(snapshot)
    _check_sqlite(destination)


def _write_private_json(path, value, **options):
    # Restrict permissions at creation, before any private content is written.
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as output:
        json.dump(value, output, **options)


def create_backup(db_path, firebase_ref, output_dir, *, firebase_url="", kind="manual", allow_missing_sqlite=False):
    db_path = Path(db_path).resolve()
    output_dir = Path(output_dir).resolve()
    timestamp = datetime.now(timezone.utc)
    folder = output_dir / f"{timestamp:%Y%m%dT%H%M%S.%fZ}-{secrets.token_hex(3)}"
    output_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    folder.mkdir(mode=0o700, exist_ok=False)
    sqlite_path = folder / "neocare.sqlite3"
    firebase_path = folder / "firebase.json"
    # SQLite normally creates files using the process umask. Reserve the empty
    # destination with owner-only permissions before SQLite writes the snapshot.
    os.close(os.open(sqlite_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))
    _copy_sqlite(db_path, sqlite_path, allow_missing=allow_missing_sqlite)
    firebase_data = firebase_ref.get()
    if firebase_data is not None and not isinstance(firebase_data, dict):
        raise ValueError("The Firebase application subtree must be an object or empty")
    _write_private_json(firebase_path, firebase_data, ensure_ascii=False, allow_nan=False)
    manifest = {
        "format_version": BACKUP_FORMAT,
        "created_at": timestamp.isoformat(),
        "kind": kind,
        "firebase_subtree": APP_SUBTREE,
        "firebase_database_url": firebase_url.rstrip("/"),
        "sqlite_existed": db_path.is_file(),
        "consistency": "Independent SQLite and Firebase snapshots; pause application writes for a coordinated recovery point.",
        "files": {
            "sqlite": {"name": sqlite_path.name, "sha256": _sha256(sqlite_path)},
            "firebase": {"name": firebase_path.name, "sha256": _sha256(firebase_path)},
        },
    }
    _write_private_json(folder / "manifest.json", manifest, indent=2)
    verify_backup(folder)
    return folder


def verify_backup(folder):
    folder = Path(folder).resolve()
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("format_version") != BACKUP_FORMAT or manifest.get("firebase_subtree") != APP_SUBTREE:
        raise ValueError("Unsupported backup format or Firebase subtree")
    for key, expected_name in (("sqlite", "neocare.sqlite3"), ("firebase", "firebase.json")):
        record = manifest.get("files", {}).get(key, {})
        if record.get("name") != expected_name:
            raise ValueError("Unexpected backup filename")
        path = folder / expected_name
        if path.is_symlink() or path.resolve().parent != folder:
            raise ValueError("Backup files must remain inside their backup directory")
        if _sha256(path) != record.get("sha256"):
            raise ValueError(f"The {key} backup checksum does not match")
    _check_sqlite(folder / "neocare.sqlite3")
    firebase_data = json.loads((folder / "firebase.json").read_text(encoding="utf-8"))
    if firebase_data is not None and not isinstance(firebase_data, dict):
        raise ValueError("The Firebase snapshot is invalid")
    return manifest


def _restore_sqlite(snapshot, destination):
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(Path(snapshot).resolve().as_uri() + "?mode=ro", uri=True)) as source:
        with closing(sqlite3.connect(destination, timeout=15)) as target:
            source.backup(target)
    _check_sqlite(destination)


def _write_firebase(firebase_ref, value):
    # Firebase's SDK rejects set(None); deleting the fixed app subtree restores
    # an explicitly empty snapshot without touching any other database nodes.
    if value is None:
        firebase_ref.delete()
    else:
        firebase_ref.set(value)


def restore_backup(folder, db_path, firebase_ref, output_dir, *, firebase_url="", confirmed=False, maintenance_confirmed=False):
    if not confirmed or not maintenance_confirmed:
        raise ValueError("Restore requires explicit confirmation and a stopped application")
    folder, db_path = Path(folder).resolve(), Path(db_path).resolve()
    manifest = verify_backup(folder)
    if db_path == folder / "neocare.sqlite3" or folder in db_path.parents:
        raise ValueError("The restore destination must not overwrite the source backup")
    if manifest.get("firebase_database_url", "") != firebase_url.rstrip("/"):
        raise ValueError("The backup belongs to a different Firebase database")
    safety_backup = create_backup(
        db_path, firebase_ref, output_dir, firebase_url=firebase_url,
        kind="pre-restore", allow_missing_sqlite=True,
    )
    restored_data = json.loads((folder / "firebase.json").read_text(encoding="utf-8"))
    try:
        _write_firebase(firebase_ref, restored_data)
        _restore_sqlite(folder / "neocare.sqlite3", db_path)
        # A read-back catches incomplete/incorrect remote restores before success.
        if firebase_ref.get() != restored_data:
            raise RuntimeError("Firebase restore verification failed")
        # A snapshot may contain tokens revoked after it was created. Force a
        # fresh sign-in rather than resurrecting those old authenticated sessions.
        with closing(sqlite3.connect(db_path)) as restored:
            if restored.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='sessions'").fetchone():
                restored.execute("DELETE FROM sessions")
                restored.commit()
    except Exception as failure:
        try:
            original_data = json.loads((safety_backup / "firebase.json").read_text(encoding="utf-8"))
            _write_firebase(firebase_ref, original_data)
            _restore_sqlite(safety_backup / "neocare.sqlite3", db_path)
        except Exception:
            raise RuntimeError(f"Restore failed and automatic rollback was incomplete. Recover using {safety_backup}") from None
        raise RuntimeError(f"Restore failed; both stores were rolled back. Safety backup: {safety_backup}") from failure
    return safety_backup


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    create = subparsers.add_parser("create", help="Back up SQLite and the Firebase application subtree")
    create.add_argument("--db", type=Path, default=auth_store.DB_PATH)
    create.add_argument("--output-dir", type=Path, default=Path(__file__).with_name(".backups"))
    verify = subparsers.add_parser("verify", help="Verify checksums and SQLite integrity without connecting to Firebase")
    verify.add_argument("backup", type=Path)
    restore = subparsers.add_parser("restore", help="Restore both stores after stopping the application")
    restore.add_argument("backup", type=Path)
    restore.add_argument("--db", type=Path, default=auth_store.DB_PATH)
    restore.add_argument("--output-dir", type=Path, default=Path(__file__).with_name(".backups"))
    restore.add_argument("--confirm-restore", action="store_true")
    restore.add_argument("--maintenance-confirmed", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "verify":
        manifest = verify_backup(args.backup)
        print(json.dumps({"status": "verified", "backup": str(args.backup.resolve()), "created_at": manifest["created_at"]}))
        return 0
    if args.command == "restore" and (not args.confirm_restore or not args.maintenance_confirmed):
        parser.error("Stop the application, then supply both --confirm-restore and --maintenance-confirmed")
    import main as application
    application.init_firebase()
    firebase_ref = application.db.reference(APP_SUBTREE)
    if args.command == "create":
        folder = create_backup(args.db, firebase_ref, args.output_dir, firebase_url=application.DATABASE_URL)
        print(json.dumps({"status": "created_and_verified", "backup": str(folder)}))
    else:
        safety = restore_backup(args.backup, args.db, firebase_ref, args.output_dir, firebase_url=application.DATABASE_URL, confirmed=True, maintenance_confirmed=True)
        print(json.dumps({"status": "restored_and_verified", "pre_restore_backup": str(safety)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
