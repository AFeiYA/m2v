"""
Alembic env.py — 数据库迁移配置

自动从 src.models 读取所有 ORM 模型，
支持 async 引擎 (SQLite / PostgreSQL)。
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool, create_engine

from src.database import Base
from src.models import User, Task  # noqa: F401 — 确保模型被导入
from src.settings import get_settings

config = context.config
settings = get_settings()

# 用 settings 中的 URL 覆盖 alembic.ini
# Alembic 迁移使用同步引擎
sync_url = settings.DATABASE_URL
sync_url = sync_url.replace("sqlite+aiosqlite", "sqlite")
sync_url = sync_url.replace("postgresql+asyncpg", "postgresql+psycopg2")
config.set_main_option("sqlalchemy.url", sync_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """离线模式: 生成 SQL 脚本"""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """在线模式: 连接数据库执行迁移"""
    connectable = create_engine(
        config.get_main_option("sqlalchemy.url"),
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
