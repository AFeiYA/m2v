"""Model asyncpg's loop affinity across Gradio init and request event loops."""
import asyncio

from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src import database
from src.models import User


def test_gradio_init_connection_is_not_reused_by_request_loop(tmp_path, monkeypatch):
    # Use the production engine's configured pool policy. No real PostgreSQL
    # credentials are required: checkout enforces asyncpg's loop-affinity rule.
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path}/loop-test.db",
        poolclass=type(database.engine.pool),
    )
    opened = []

    @event.listens_for(engine.sync_engine, "connect")
    def bind_loop(connection, record):
        record.info["owner_loop"] = asyncio.get_running_loop()
        opened.append(connection)

    @event.listens_for(engine.sync_engine, "checkout")
    def enforce_loop(connection, record, proxy):
        if record.info["owner_loop"] is not asyncio.get_running_loop():
            raise RuntimeError("connection attached to a different loop")

    monkeypatch.setattr(database, "engine", engine)
    # Exactly the separate loops used by mount_fastapi_routes and ASGI requests.
    asyncio.run(database.init_db())

    async def request():
        async with async_sessionmaker(engine)() as db:
            return (await db.execute(select(User.id))).all()

    try:
        assert asyncio.run(request()) == []
        assert asyncio.run(request()) == []
        assert len(opened) == 3
    finally:
        asyncio.run(engine.dispose())
