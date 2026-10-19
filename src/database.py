"""
数据库引擎 & 会话管理 — SQLAlchemy 2.0 async

本地开发默认使用 SQLite + aiosqlite，
生产部署切换 PostgreSQL + asyncpg（只需改 DATABASE_URL）。
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

from src.settings import get_settings

settings = get_settings()

# ── 引擎 ─────────────────────────────────────────────────
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    # Gradio initializes tables in a separate asyncio.run() from its ASGI loop.
    # asyncpg connections cannot cross event loops; never retain those connections.
    poolclass=NullPool,
    # SQLite 需要 check_same_thread=False
    connect_args=(
        {"check_same_thread": False}
        if settings.DATABASE_URL.startswith("sqlite")
        else {}
    ),
)

# ── 会话工厂 ─────────────────────────────────────────────
async_session = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


# ── ORM 基类 ─────────────────────────────────────────────
class Base(DeclarativeBase):
    pass


# ── FastAPI 依赖 ─────────────────────────────────────────
async def get_db() -> AsyncSession:  # type: ignore[misc]
    """FastAPI Depends 注入数据库会话"""
    async with async_session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# ── 表创建与自愈迁移 ────────────────────────────────────
async def create_tables() -> None:
    await init_db()


async def init_db() -> None:
    """初始化数据库：确保模型注册，创建表，并平滑增加缺失字段"""
    import src.models  # noqa: F401
    import src.billing_models  # noqa: F401
    import src.credit_lots  # noqa: F401
    from sqlalchemy import inspect, text

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

        def _migrate_columns(sync_conn):
            inspector = inspect(sync_conn)
            tables = inspector.get_table_names()
            is_pg = sync_conn.dialect.name == "postgresql"
            if "tasks" in tables:
                cols = {c["name"] for c in inspector.get_columns("tasks")}
                if "song_title" not in cols:
                    sql = "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS song_title VARCHAR(255);" if is_pg else "ALTER TABLE tasks ADD COLUMN song_title VARCHAR(255);"
                    sync_conn.execute(text(sql))
                if "suno_url" not in cols:
                    sql = "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS suno_url VARCHAR(1024);" if is_pg else "ALTER TABLE tasks ADD COLUMN suno_url VARCHAR(1024);"
                    sync_conn.execute(text(sql))
                if "updated_at" not in cols:
                    sql = "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE;" if is_pg else "ALTER TABLE tasks ADD COLUMN updated_at DATETIME;"
                    sync_conn.execute(text(sql))
            if "users" in tables:
                user_cols = {c["name"] for c in inspector.get_columns("users")}
                if "display_name" not in user_cols:
                    sql = "ALTER TABLE users ADD COLUMN IF NOT EXISTS display_name VARCHAR(128);" if is_pg else "ALTER TABLE users ADD COLUMN display_name VARCHAR(128);"
                    sync_conn.execute(text(sql))

        await conn.run_sync(_migrate_columns)
