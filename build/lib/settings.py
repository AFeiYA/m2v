"""
应用配置 — 通过环境变量 / .env 文件加载

所有可配置项都有合理默认值，本地开发零配置即可启动。
生产部署时通过环境变量或 .env 覆盖。
"""

from __future__ import annotations

from pathlib import Path
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """全局应用设置（环境变量优先，再读 .env 文件）"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # ── 通用 ──────────────────────────────────────────────
    APP_NAME: str = "M2V — Auto-Karaoke MV Generator"
    DEBUG: bool = False
    SECRET_KEY: str = "CHANGE-ME-in-production-use-openssl-rand-hex-32"

    # ── 数据库 ────────────────────────────────────────────
    # 默认 SQLite (本地开发)；生产用 PostgreSQL
    DATABASE_URL: str = "sqlite+aiosqlite:///./m2v.db"
    # PostgreSQL 示例: "postgresql+asyncpg://m2v:password@localhost:5432/m2v"

    # ── Redis ─────────────────────────────────────────────
    REDIS_URL: str = "redis://localhost:6379/0"

    # ── JWT ───────────────────────────────────────────────
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30

    # ── 文件存储 ──────────────────────────────────────────
    # "local" | "s3"
    STORAGE_BACKEND: str = "local"
    # 本地存储根目录
    UPLOAD_DIR: str = "./uploads"
    OUTPUT_DIR: str = "./output"
    # S3 配置 (STORAGE_BACKEND="s3" 时生效)
    S3_ENDPOINT_URL: str | None = None       # MinIO: "http://localhost:9000"
    S3_ACCESS_KEY: str = ""
    S3_SECRET_KEY: str = ""
    S3_BUCKET: str = "m2v"
    S3_REGION: str = "us-east-1"

    # ── Celery ────────────────────────────────────────────
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"

    # ── 用户配额 ──────────────────────────────────────────
    FREE_MONTHLY_QUOTA: int = 5         # 免费用户每月可生成次数
    PRO_MONTHLY_QUOTA: int = 100
    MAX_UPLOAD_SIZE_MB: int = 50        # 单文件最大上传 MB

    # ── 服务端口 ──────────────────────────────────────────
    HOST: str = "0.0.0.0"
    PORT: int = 8000


@lru_cache()
def get_settings() -> Settings:
    """单例获取设置（缓存实例）"""
    return Settings()
