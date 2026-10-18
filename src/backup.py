"""Database backup and integrity verification utilities for SQLite and PostgreSQL."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from src.auth import get_current_user_flexible
from src.models import User
from src.settings import get_settings

router = APIRouter(prefix="/api/admin", tags=["Admin Backup"])


def now():
    return datetime.now(timezone.utc)


def compute_sha256(file_path: Path) -> str:
    hasher = hashlib.sha256()
    with file_path.open("rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def create_database_backup(db_url: str | None = None, output_dir: Path | str | None = None) -> dict:
    """Create a point-in-time database snapshot with checksum and manifest verification."""
    settings = get_settings()
    url = db_url or settings.DATABASE_URL
    out_dir = Path(output_dir) if output_dir else Path("./backups")
    out_dir.mkdir(parents=True, exist_ok=True, mode=0o700)

    timestamp = now().strftime("%Y%m%d_%H%M%S_%f")

    # SQLite backup logic
    if "sqlite" in url:
        # Extract path from sqlite+aiosqlite:///path or sqlite:///path
        clean_path = url.split(":///")[-1].split("?")[0]
        source_path = Path(clean_path).resolve()

        if not source_path.exists():
            raise FileNotFoundError(f"Source database file not found at {source_path}")

        backup_file = out_dir / f"db_backup_{timestamp}.sqlite3"

        # Online SQLite backup: safe during concurrent read/write
        source_conn = sqlite3.connect(str(source_path))
        dest_conn = sqlite3.connect(str(backup_file))
        try:
            source_conn.backup(dest_conn)
        finally:
            source_conn.close()
            dest_conn.close()

        # Compute checksum
        os.chmod(backup_file, 0o600)
        checksum = compute_sha256(backup_file)
        size_bytes = backup_file.stat().st_size

        # Query counts from backup copy
        verify_conn = sqlite3.connect(str(backup_file))
        cursor = verify_conn.cursor()
        cursor.execute("PRAGMA integrity_check;")
        integrity = cursor.fetchone()[0]

        table_counts = {}
        for table in ("users", "tasks", "credit_entries", "credit_reservations", "video_exports"):
            try:
                cursor.execute(f"SELECT COUNT(*) FROM {table}")
                table_counts[table] = cursor.fetchone()[0]
            except Exception:
                table_counts[table] = 0
        verify_conn.close()

        manifest = {
            "backup_file": str(backup_file.resolve()),
            "timestamp": timestamp,
            "created_at": now().isoformat(),
            "engine": "sqlite",
            "checksum_sha256": checksum,
            "size_bytes": size_bytes,
            "integrity": integrity,
            "table_counts": table_counts,
        }

        manifest_file = out_dir / f"db_backup_{timestamp}.manifest.json"
        manifest_file.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        manifest["manifest_file"] = str(manifest_file.resolve())
        return manifest
    else:
        # PostgreSQL managed database backup
        import shutil
        import subprocess

        pg_dump = shutil.which("pg_dump")
        if not pg_dump:
            raise NotImplementedError(
                "PostgreSQL backup requires 'pg_dump' utility installed on the system environment, "
                "or provider-managed automated snapshots."
            )

        backup_file = out_dir / f"pg_backup_{timestamp}.dump"
        from sqlalchemy.engine import make_url, URL
        parsed = make_url(url).set(drivername="postgresql")
        password = parsed.password
        clean_url = URL.create("postgresql", username=parsed.username, host=parsed.host,
                               port=parsed.port, database=parsed.database,
                               query={k: v for k, v in parsed.query.items() if k != "password"}).render_as_string(hide_password=False)
        environment = {**os.environ}
        if password:
            environment["PGPASSWORD"] = password
        try:
            proc = subprocess.run(
                [pg_dump, "--dbname", clean_url, "--format=custom", "-f", str(backup_file)],
                capture_output=True, text=True, env=environment, timeout=120,
            )
            if proc.returncode != 0:
                raise RuntimeError("PostgreSQL backup failed")
        except BaseException:
            backup_file.unlink(missing_ok=True)
            raise

        os.chmod(backup_file, 0o600)
        checksum = compute_sha256(backup_file)
        manifest = {
            "backup_file": str(backup_file.resolve()),
            "timestamp": timestamp,
            "created_at": now().isoformat(),
            "engine": "postgresql",
            "checksum_sha256": checksum,
            "size_bytes": backup_file.stat().st_size,
        }
        manifest_file = out_dir / f"pg_backup_{timestamp}.manifest.json"
        manifest_file.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        manifest["manifest_file"] = str(manifest_file.resolve())
        return manifest


def verify_database_backup(backup_file: Path | str) -> dict:
    """Verify an existing database backup file for integrity and checksum."""
    path = Path(backup_file).resolve()
    if not path.exists():
        raise FileNotFoundError(f"Backup file not found: {path}")

    if path.suffix == ".dump":
        import shutil
        import subprocess
        tool = shutil.which("pg_restore")
        if not tool:
            raise NotImplementedError("PostgreSQL archive verification requires pg_restore")
        checked = subprocess.run([tool, "--list", str(path)], capture_output=True, text=True, timeout=120)
        return {"valid": checked.returncode == 0, "checksum_sha256": compute_sha256(path),
                "size_bytes": path.stat().st_size, "verification": "archive listing; restore drill still required"}
    conn = sqlite3.connect(str(path))
    cursor = conn.cursor()
    cursor.execute("PRAGMA integrity_check;")
    check = cursor.fetchone()[0]

    tables = []
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    for row in cursor.fetchall():
        tables.append(row[0])
    conn.close()

    checksum = compute_sha256(path)
    return {
        "valid": check == "ok",
        "integrity_check": check,
        "tables": tables,
        "checksum_sha256": checksum,
        "size_bytes": path.stat().st_size,
    }


def require_admin_user(user: User = Depends(get_current_user_flexible)) -> User:
    """Enforce administrator-only access based on M2V_ADMIN_USERS configuration."""
    raw_admins = os.getenv("M2V_ADMIN_USERS", "")
    admin_list = [u.strip() for u in raw_admins.split(",") if u.strip()]
    if not admin_list:
        raise HTTPException(403, "Administrator access required: no admin users configured")
    if user.id not in admin_list:
        raise HTTPException(403, "Administrator access required: user is not an administrator")
    return user


@router.post("/backup")
async def trigger_database_backup(admin: User = Depends(require_admin_user)):
    """Admin-only endpoint to trigger a database backup."""
    manifest = await asyncio.to_thread(create_database_backup)
    return {"status": "success", "manifest": manifest}
