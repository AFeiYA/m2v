"""Existing billing inboxes survive the additive retry scheduling migration."""
import asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from src import database
from src.database import Base
import src.billing_models  # noqa: F401


def test_existing_inbox_gets_nullable_retry_timestamp_without_losing_events(tmp_path,monkeypatch):
    engine=create_async_engine('sqlite+aiosqlite:///'+str(tmp_path/'legacy.db'))
    monkeypatch.setattr(database,'engine',engine)
    async def run():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await conn.execute(text('ALTER TABLE billing_events DROP COLUMN next_attempt_at'))
            await conn.execute(text("INSERT INTO billing_events (id,event_name,status,attempts,resource_id,created_at) VALUES ('retained','transaction.completed','pending',2,'paddle:sandbox:transactions/txn_fixture','2026-10-24')"))
        await database.init_db()
        await database.init_db()  # Repeated startup must remain safe.
        async with engine.connect() as conn:
            row=(await conn.execute(text("SELECT status,attempts,next_attempt_at FROM billing_events WHERE id='retained'"))).one()
            assert tuple(row)==('pending',2,None)
        await engine.dispose()
    asyncio.run(run())
