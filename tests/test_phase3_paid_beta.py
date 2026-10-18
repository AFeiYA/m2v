"""
Phase 3 Paid Beta Gates Integration and Verification Tests:
- Real-account lifecycle: registration, checkout, idempotent webhook, grant, export, re-login, download, refund
- Strict owner isolation: tasks, versions, exports, order history, storage accounting, scoped tickets
- Unified entitlement and credit reservations across lyric video and motion exports
- Queue admission & per-user concurrency limits (429 Too Many Requests)
- Storage accounting and visible retention policy (no silent deletion)
- Database backup creation and PRAGMA integrity verification
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import types
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from src import api_server, auth, database, storage
from src.database import Base, get_db
from src.models import (
    CreditEntry,
    CreditReservation,
    ExportJob,
    PaymentOrder,
    Task,
    TaskStatus,
    TaskStep,
    User,
    UserPlan,
    VideoExport,
)
from src.payments import PACKAGES, verify_signature
from src.queue_limiter import check_render_admission
from src.backup import create_database_backup, verify_database_backup


@pytest.fixture
def phase3_env(tmp_path, monkeypatch):
    db_file = tmp_path / "phase3.db"
    url = f"sqlite+aiosqlite:///{db_file}"
    engine = create_async_engine(url, poolclass=NullPool)
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    monkeypatch.setattr(database.settings, "DATABASE_URL", url)
    monkeypatch.setattr(auth.settings, "SECRET_KEY", "phase3-test-secret-key-32chars")
    monkeypatch.setattr(auth, "verify_firebase_id_token", lambda token: None)
    monkeypatch.setattr(api_server, "async_session", sessions)

    local_storage = storage.LocalStorage(tmp_path / "storage")
    monkeypatch.setattr(storage, "_storage_instance", local_storage)

    # Initialize tables
    async def init():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with sessions() as db:
            carol = User(id="carol", email="carol@example.com", username="carol", credits=5, plan=UserPlan.FREE)
            dave = User(id="dave", email="dave@example.com", username="dave", credits=10, plan=UserPlan.FREE)
            db.add_all([carol, dave])
            await db.commit()

    asyncio.run(init())

    async def test_db():
        async with sessions() as db:
            try:
                yield db
                await db.commit()
            except Exception:
                await db.rollback()
                raise

    async def noop_init():
        pass
    monkeypatch.setattr(database, "init_db", noop_init)

    from src.editor_server import router as editor_router
    from src.motion_cloud import router as cloud_motion_router

    app = FastAPI()
    app.include_router(api_server.api_router)
    app.include_router(editor_router)
    app.include_router(cloud_motion_router)
    app.dependency_overrides[get_db] = test_db

    with TestClient(app) as client:

        yield types.SimpleNamespace(
            client=client,
            sessions=sessions,
            storage=local_storage,
            db_file=db_file,
            tmp_path=tmp_path,
        )

    app.dependency_overrides.clear()
    asyncio.run(engine.dispose())


def auth_header(uid: str) -> dict:
    token = auth.create_access_token(uid)
    return {"Authorization": f"Bearer {token}"}


# ==============================================================================
# 1. Real-Account Lifecycle: Checkout, Idempotent Webhook, Grant & History
# ==============================================================================

def test_payment_checkout_idempotency_and_webhook_grant(phase3_env):
    client = phase3_env.client
    headers = auth_header("carol")

    # 1. Packages catalog
    resp = client.get("/api/payments/packages")
    assert resp.status_code == 200
    packages = resp.json()["packages"]
    assert len(packages) >= 3
    creator_pkg = next(p for p in packages if p["id"] == "creator")
    assert creator_pkg["credits"] == 60
    assert creator_pkg["amount_cents"] == 1299

    # 2. Create Checkout with Idempotency Key
    idem_key = "idem_order_carol_001"
    payload = {"package_id": "creator", "provider": "mock", "idempotency_key": idem_key}
    checkout_resp = client.post("/api/payments/checkout", json=payload, headers=headers)
    assert checkout_resp.status_code == 200
    order_data = checkout_resp.json()
    order_id = order_data["order_id"]
    assert order_data["reused"] is False
    assert order_data["credits"] == 60

    # 3. Resubmitting with same idempotency key returns the SAME order (no duplicate charge)
    checkout_dup = client.post("/api/payments/checkout", json=payload, headers=headers)
    assert checkout_dup.status_code == 200
    assert checkout_dup.json()["order_id"] == order_id
    assert checkout_dup.json()["reused"] is True

    # 4. Another user using the same idempotency key is rejected with 409
    dave_dup = client.post("/api/payments/checkout", json=payload, headers=auth_header("dave"))
    assert dave_dup.status_code == 409

    # 5. Process Webhook callback (simulating payment provider event)
    webhook_payload = {
        "event": "payment.succeeded",
        "order_id": order_id,
        "provider_order_id": "pi_mock_123456",
    }
    raw_bytes = json.dumps(webhook_payload).encode()
    signature = hmac.new("payment-dev-webhook-secret".encode(), raw_bytes, hashlib.sha256).hexdigest()

    # Invalid secret/signature is rejected
    bad_resp = client.post(
        "/api/payments/webhook/mock",
        data=raw_bytes,
        headers={"Content-Type": "application/json", "X-Webhook-Secret": "wrong-secret"},
    )
    assert bad_resp.status_code == 401

    # Valid secret marks order paid and grants credits
    wh_resp = client.post(
        "/api/payments/webhook/mock",
        data=raw_bytes,
        headers={"Content-Type": "application/json", "X-Webhook-Signature": signature},
    )
    assert wh_resp.status_code == 200
    assert wh_resp.json()["status"] == "paid"
    assert wh_resp.json()["credits_granted"] == 60

    # 6. Duplicate webhook callback is strictly IDEMPOTENT (no double-grant)
    wh_dup = client.post(
        "/api/payments/webhook/mock",
        data=raw_bytes,
        headers={"Content-Type": "application/json", "X-Webhook-Signature": signature},
    )
    assert wh_dup.status_code == 200
    assert wh_dup.json()["status"] == "already_paid"

    # 7. Check user's balance: starting 5 + 60 granted = 65
    cred_resp = client.get("/api/credits", headers=headers)
    assert cred_resp.status_code == 200
    assert cred_resp.json()["available"] == 65

    # 8. Order history shows order completed
    orders_resp = client.get("/api/payments/orders", headers=headers)
    assert orders_resp.status_code == 200
    orders = orders_resp.json()["orders"]
    assert len(orders) == 1
    assert orders[0]["id"] == order_id
    assert orders[0]["status"] == "paid"
    assert orders[0]["credits"] == 60


# ==============================================================================
# 2. Refund Flow & Ledger Deduction
# ==============================================================================

def test_order_refund_flow_and_ledger_entry(phase3_env):
    client = phase3_env.client
    headers = auth_header("carol")

    # Create & mock-complete an order
    checkout = client.post(
        "/api/payments/checkout",
        json={"package_id": "starter", "provider": "mock"},
        headers=headers,
    ).json()
    order_id = checkout["order_id"]

    client.post(f"/api/payments/mock-complete/{order_id}")

    # Balance before refund: 5 (initial) + 20 (starter) = 25
    assert client.get("/api/credits", headers=headers).json()["available"] == 25

    # Dave cannot refund Carol's order
    dave_refund = client.post(
        f"/api/payments/orders/{order_id}/refund",
        json={"reason": "Unauthorized attempt"},
        headers=auth_header("dave"),
    )
    assert dave_refund.status_code == 403

    # Carol refunds her order
    refund_resp = client.post(
        f"/api/payments/orders/{order_id}/refund",
        json={"reason": "Accidental purchase"},
        headers=headers,
    )
    assert refund_resp.status_code == 200
    data = refund_resp.json()
    assert data["status"] == "refunded"
    assert data["deducted_credits"] == 20
    assert data["new_balance"] == 5

    # Cannot refund twice
    refund_dup = client.post(
        f"/api/payments/orders/{order_id}/refund",
        json={"reason": "Second try"},
        headers=headers,
    )
    assert refund_dup.status_code == 400

    # Ledger verifies negative adjustment
    cred_history = client.get("/api/credits", headers=headers).json()
    assert cred_history["available"] == 5
    refund_entry = next(e for e in cred_history["entries"] if e["event"] == "refund")
    assert refund_entry["amount"] == -20


# ==============================================================================
# 3. Strict Owner Isolation Across Accounts
# ==============================================================================

def test_strict_owner_isolation_across_all_routes(phase3_env):
    client = phase3_env.client
    carol_headers = auth_header("carol")
    dave_headers = auth_header("dave")

    # Seed task and export for Carol
    async def seed():
        async with phase3_env.sessions() as db:
            task = Task(
                id="task_carol_secret",
                user_id="carol",
                title="Carol Secret Track",
                song_title="Carol Secret Song",
                input_mp3_key="uploads/carol/secret.mp3",
                input_lyrics_key="uploads/carol/secret.txt",
                alignment_json_key="results/carol/secret_alignment.json",
                status=TaskStatus.COMPLETED,
                current_step=TaskStep.DONE,
            )
            export = VideoExport(
                id="exp_carol_video",
                user_id="carol",
                task_id=task.id,
                title=task.song_title,
                kind="lyric",
                storage_key="exports/carol_video.mp4",
                details={"size_bytes": 1048576},
            )
            order = PaymentOrder(
                id="ord_carol_private",
                user_id="carol",
                package_id="starter",
                credits=20,
                amount_cents=499,
                currency="USD",
                provider="mock",
                status="paid",
            )
            db.add_all([task, export, order])
            await db.commit()

    video_path = phase3_env.storage.get_local_path("exports/carol_video.mp4")
    video_path.parent.mkdir(parents=True, exist_ok=True)
    video_path.write_bytes(b"dummy mp4 video bytes")

    asyncio.run(seed())

    # Dave queries Carol's task -> 404
    assert client.get("/api/editor/tasks/task_carol_secret/info", headers=dave_headers).status_code == 404
    # Dave queries Carol's export access ticket -> 404
    assert client.get("/api/exports/exp_carol_video/access", headers=dave_headers).status_code == 404
    # Dave queries Carol's order history -> sees only Dave's orders (0 orders)
    dave_orders = client.get("/api/payments/orders", headers=dave_headers).json()["orders"]
    assert len(dave_orders) == 0
    # Dave queries storage accounting -> sees only Dave's usage (0 bytes)
    dave_storage = client.get("/api/storage/accounting", headers=dave_headers).json()
    assert dave_storage["user_id"] == "dave"
    assert dave_storage["counts"]["exports"] == 0

    # Carol accesses her own assets -> all 200
    assert client.get("/api/editor/tasks/task_carol_secret/info", headers=carol_headers).status_code == 200
    assert client.get("/api/exports/exp_carol_video/access", headers=carol_headers).status_code == 200
    carol_orders = client.get("/api/payments/orders", headers=carol_headers).json()["orders"]
    assert len(carol_orders) == 1
    assert carol_orders[0]["id"] == "ord_carol_private"



# ==============================================================================
# 4. Storage Accounting & Visible Retention Policy
# ==============================================================================

def test_storage_accounting_and_retention_policy(phase3_env):
    client = phase3_env.client
    headers = auth_header("carol")

    # Seed Carol's items: 1 task, 1 export
    async def seed():
        async with phase3_env.sessions() as db:
            task = Task(
                id="task_carol_storage",
                user_id="carol",
                title="Storage Test Song",
                song_title="Storage Test Song",
                input_mp3_key="uploads/carol/song.mp3",
                input_lyrics_key="uploads/carol/song.txt",
                status=TaskStatus.COMPLETED,
                current_step=TaskStep.DONE,
            )
            export = VideoExport(
                id="exp_carol_storage_vid",
                user_id="carol",
                task_id=task.id,
                title=task.song_title,
                kind="lyric",
                storage_key="exports/test.mp4",
                details={"size_bytes": 5242880},  # 5 MB
            )
            db.add_all([task, export])
            await db.commit()

    asyncio.run(seed())

    resp = client.get("/api/storage/accounting", headers=headers)
    assert resp.status_code == 200
    data = resp.json()

    assert data["user_id"] == "carol"
    assert data["plan"] == "free"
    assert data["usage"]["video_bytes"] == 5242880
    assert data["usage"]["quota_bytes"] == 5 * 1024 * 1024 * 1024
    assert data["counts"]["active_versions"] >= 1
    assert data["counts"]["exports"] >= 1

    # Verify visible retention policy guarantees: no silent deletion
    policy = data["retention_policy"]
    assert policy["policy_version"] == "1.0"
    assert policy["silent_deletion_forbidden"] is True
    assert "permanently retained" in policy["summary"]
    assert "ever silently deleted" in policy["summary"]



# ==============================================================================
# 5. Queue Admission & Concurrency Limits (429 Enforcement)
# ==============================================================================

def test_queue_admission_concurrency_limits(phase3_env, monkeypatch):
    client = phase3_env.client
    headers = auth_header("carol")

    from src.settings import get_settings
    monkeypatch.setattr(get_settings(), "MAX_CONCURRENT_RENDERS_PER_USER", 2)

    # Seed 2 active render jobs for Carol
    async def seed():
        async with phase3_env.sessions() as db:
            for i in range(2):
                db.add(ExportJob(
                    id=f"job_active_{i}",
                    user_id="carol",
                    task_id="task_active",
                    title="Active Job",
                    status="running",
                    options={},
                    fingerprint=f"fp_{i}",
                    alignment_key="key",
                    audio_key="key",
                    lease_until=datetime.now(timezone.utc),
                ))
            await db.commit()

    asyncio.run(seed())

    # Directly verify check_render_admission raises 429
    async def test_admission():
        async with phase3_env.sessions() as db:
            with pytest.raises(Exception) as exc_info:
                await check_render_admission(db, "carol")
            assert "429" in str(exc_info.value) or exc_info.value.status_code == 429

    asyncio.run(test_admission())


# ==============================================================================
# 6. Database Backup & PRAGMA Integrity Verification
# ==============================================================================

def test_database_backup_and_integrity_check(phase3_env, tmp_path):
    backup_dir = tmp_path / "backups_test"
    manifest = create_database_backup(db_url=f"sqlite:///{phase3_env.db_file}", output_dir=backup_dir)

    assert manifest["engine"] == "sqlite"
    assert manifest["integrity"] == "ok"
    assert manifest["checksum_sha256"] is not None
    assert Path(manifest["backup_file"]).exists()

    # Table counts verify real data captured
    assert manifest["table_counts"]["users"] >= 2

    # Verification function validates backup integrity
    verify_result = verify_database_backup(manifest["backup_file"])
    assert verify_result["valid"] is True
    assert verify_result["integrity_check"] == "ok"
    assert "users" in verify_result["tables"]
    assert "credit_entries" in verify_result["tables"]
    assert "payment_orders" in verify_result["tables"]
