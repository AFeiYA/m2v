"""
应用配置 — 通过环境变量 / .env 文件加载

所有可配置项都有合理默认值，本地开发零配置即可启动。
生产部署时通过环境变量或 .env 覆盖。
"""

from __future__ import annotations

import os
from pathlib import Path
from functools import lru_cache
from pydantic import Field

try:
    from pydantic_settings import BaseSettings, SettingsConfigDict
except ImportError:
    from pydantic import BaseModel
    class BaseSettings(BaseModel):  # type: ignore[no-redef]
        def __init__(self, **values):
            env_vals = {}
            for field in self.__class__.model_fields:
                val = os.getenv(field, os.getenv(field.upper()))
                if val is not None:
                    env_vals[field] = val
            env_vals.update(values)
            super().__init__(**env_vals)

    def SettingsConfigDict(**kwargs):  # type: ignore[no-redef]
        return kwargs


class Settings(BaseSettings):
    """全局应用设置（环境变量优先，再读 .env 文件）"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── 通用 ──────────────────────────────────────────────
    APP_NAME: str = "M2V — Auto-Karaoke MV Generator"
    DEBUG: bool = False
    SECRET_KEY: str = "CHANGE-ME-in-production-use-openssl-rand-hex-32"

    # ── 数据库 ────────────────────────────────────────────
    # 默认 SQLite (本地开发)；生产用 PostgreSQL
    DATABASE_URL: str = "sqlite+aiosqlite:///./m2v.db"
    # PostgreSQL 示例: "postgresql+asyncpg://m2v:password@localhost:5432/m2v"

    # Billing is opt-in; test mode must use an isolated deployment/database.
    BILLING_ENABLED: bool = False
    BILLING_ALLOW_TEST_TRANSACTIONS: bool = False
    LEMONSQUEEZY_API_KEY: str = ""
    LEMONSQUEEZY_WEBHOOK_SECRET: str = ""
    LEMONSQUEEZY_STORE_ID: str = ""
    LEMONSQUEEZY_TEST_MODE: bool = True
    LEMONSQUEEZY_ALLOWED_HOSTS: str = ""
    BILLING_SITE_URL: str = "https://mv.fovea.si"
    BILLING_PRODUCTS_JSON: str = "[]"

    # ── Redis ─────────────────────────────────────────────
    REDIS_URL: str = "redis://localhost:6379/0"

    # ── JWT ───────────────────────────────────────────────
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30

    # ── Firebase ──────────────────────────────────────────
    FIREBASE_PROJECT_ID: str = "dc-test-731fa"

    # ── 文件存储 ──────────────────────────────────────────
    # "local" | "s3" | "r2"
    STORAGE_BACKEND: str = "local"
    # 本地存储根目录
    UPLOAD_DIR: str = "./uploads"
    OUTPUT_DIR: str = "./output"
    # S3 / MinIO 配置
    S3_ENDPOINT_URL: str | None = None       # MinIO: "http://localhost:9000"
    S3_ACCESS_KEY: str = ""
    S3_SECRET_KEY: str = ""
    S3_BUCKET: str = "m2v"
    S3_REGION: str = "us-east-1"

    # Cloudflare R2 专用配置 (也可通过 S3_* 变量配置)
    R2_ACCOUNT_ID: str = ""
    R2_ACCESS_KEY_ID: str = ""
    R2_SECRET_ACCESS_KEY: str = ""
    R2_BUCKET_NAME: str = "suno2mv-media"
    R2_PUBLIC_DOMAIN: str = ""

    def model_post_init(self, __context: object) -> None:
        # 如果配置了 R2，自动对齐映射到 S3 兼容协议
        if self.R2_ACCOUNT_ID:
            if not self.S3_ENDPOINT_URL:
                self.S3_ENDPOINT_URL = f"https://{self.R2_ACCOUNT_ID}.r2.cloudflarestorage.com"
            if not self.S3_ACCESS_KEY and self.R2_ACCESS_KEY_ID:
                self.S3_ACCESS_KEY = self.R2_ACCESS_KEY_ID
            if not self.S3_SECRET_KEY and self.R2_SECRET_ACCESS_KEY:
                self.S3_SECRET_KEY = self.R2_SECRET_ACCESS_KEY
            if self.S3_BUCKET == "m2v" and self.R2_BUCKET_NAME:
                self.S3_BUCKET = self.R2_BUCKET_NAME
            if self.S3_REGION == "us-east-1":
                self.S3_REGION = "auto"
            if self.STORAGE_BACKEND == "local":
                self.STORAGE_BACKEND = "r2"

        # 自动纠正与归一化 DATABASE_URL (自动补充 asyncpg 驱动，并对密码中的特殊字符如 @、/ 进行 URL 编码)
        if self.DATABASE_URL:
            import urllib.parse
            url = self.DATABASE_URL.strip()
            if url.startswith("postgresql://"):
                url = "postgresql+asyncpg://" + url[len("postgresql://"):]
            elif url.startswith("postgres://"):
                url = "postgresql+asyncpg://" + url[len("postgres://"):]

            if "@" in url:
                scheme_part, sep, rest = url.partition("://")
                if sep and "@" in rest:
                    userpass_part, _, host_db_part = rest.rpartition("@")
                    if ":" in userpass_part:
                        user, _, raw_pwd = userpass_part.partition(":")
                        safe_pwd = urllib.parse.quote(urllib.parse.unquote(raw_pwd), safe="")
                        url = f"{scheme_part}://{user}:{safe_pwd}@{host_db_part}"
            self.DATABASE_URL = url

    # ── Celery ────────────────────────────────────────────
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"

    # ── 用户配额与积分定价 ──────────────────────────────────
    FREE_MONTHLY_QUOTA: int = 20         # 免费用户每月免费额度（初始永久积分消耗完毕后）
    NEW_USER_PERMANENT_CREDITS: int = 100 # 新用户注册赠送永久积分（永久有效不设到期）
    # Default to 0 in development/beta to keep exports free unless configured
    SEPARATION_CREDITS: int = Field(default=0, ge=0)
    LYRIC_EXPORT_CREDITS: int = Field(default=0, ge=0)
    MOTION_EXPORT_CREDITS: int = Field(default=0, ge=0)
    MOTION_WEBCODECS_CREDITS: int = Field(default=0, ge=0)
    DRAFT_EXPORT_CREDITS: int = Field(default=0, ge=0)
    CLIP_EXPORT_CREDITS: int = Field(default=0, ge=0)
    MAX_CONCURRENT_RENDERS_PER_USER: int = Field(default=2, ge=1)
    MAX_GLOBAL_CONCURRENT_RENDERS: int = Field(default=4, ge=1)
    PRO_MONTHLY_QUOTA: int = 100
    MAX_UPLOAD_SIZE_MB: int = 50        # 单文件最大上传 MB

    # ── 服务端口 ──────────────────────────────────────────
    HOST: str = "0.0.0.0"
    PORT: int = 8000


@lru_cache()
def get_settings() -> Settings:
    """单例获取设置（缓存实例）"""
    return Settings()
