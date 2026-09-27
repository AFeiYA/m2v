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

from src.settings import get_settings

settings = get_settings()

# ── 引擎 ─────────────────────────────────────────────────
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
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


# ── 表创建（开发用，生产应使用 Alembic 迁移）────────────
async def create_tables() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
