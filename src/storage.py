"""
文件存储抽象层 — 本地文件 / S3 兼容

通过 STORAGE_BACKEND 环境变量切换:
  - "local" (默认): 文件存储在本地磁盘 UPLOAD_DIR / OUTPUT_DIR
  - "s3": 存储到 S3 / MinIO / 阿里云 OSS 等兼容服务
"""

from __future__ import annotations

import shutil
from abc import ABC, abstractmethod
from pathlib import Path

from src.settings import get_settings
from src.utils import log

settings = get_settings()


class StorageBackend(ABC):
    """存储后端抽象基类"""

    @abstractmethod
    async def save(self, key: str, local_path: Path) -> str:
        """保存本地文件到存储，返回存储 key"""
        ...

    @abstractmethod
    async def load(self, key: str, local_path: Path) -> Path:
        """从存储下载到本地路径，返回本地路径"""
        ...

    @abstractmethod
    async def delete(self, key: str) -> None:
        """删除存储中的文件"""
        ...

    @abstractmethod
    async def get_url(self, key: str, expires: int = 3600) -> str:
        """获取文件的访问 URL（签名 URL 或本地路径）"""
        ...

    @abstractmethod
    async def exists(self, key: str) -> bool:
        """检查文件是否存在"""
        ...


# ======================================================================
# 本地文件存储
# ======================================================================

class LocalStorage(StorageBackend):
    """本地磁盘存储"""

    def __init__(self, base_dir: str | Path | None = None):
        self.base_dir = Path(base_dir or settings.UPLOAD_DIR).resolve()
        self.base_dir.mkdir(parents=True, exist_ok=True)

    async def save(self, key: str, local_path: Path) -> str:
        dst = self.base_dir / key
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(local_path), str(dst))
        log.debug("LocalStorage: saved %s → %s", local_path.name, key)
        return key

    async def load(self, key: str, local_path: Path) -> Path:
        src = self.base_dir / key
        if not src.exists():
            raise FileNotFoundError(f"存储文件不存在: {key}")
        local_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(src), str(local_path))
        return local_path

    async def delete(self, key: str) -> None:
        path = self.base_dir / key
        if path.exists():
            path.unlink()
            log.debug("LocalStorage: deleted %s", key)

    async def get_url(self, key: str, expires: int = 3600) -> str:
        # 本地模式返回 API 路由路径
        return f"/api/files/{key}"

    async def exists(self, key: str) -> bool:
        return (self.base_dir / key).exists()

    def get_local_path(self, key: str) -> Path:
        """本地模式特有：直接返回磁盘路径（避免复制）"""
        return self.base_dir / key


# ======================================================================
# S3 兼容存储
# ======================================================================

class S3Storage(StorageBackend):
    """S3 / MinIO / 阿里云 OSS 兼容存储"""

    def __init__(self):
        import boto3
        self.bucket = settings.S3_BUCKET
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.S3_ENDPOINT_URL,
            aws_access_key_id=settings.S3_ACCESS_KEY,
            aws_secret_access_key=settings.S3_SECRET_KEY,
            region_name=settings.S3_REGION,
        )

    async def save(self, key: str, local_path: Path) -> str:
        self.client.upload_file(str(local_path), self.bucket, key)
        log.debug("S3Storage: uploaded %s → s3://%s/%s", local_path.name, self.bucket, key)
        return key

    async def load(self, key: str, local_path: Path) -> Path:
        local_path.parent.mkdir(parents=True, exist_ok=True)
        self.client.download_file(self.bucket, key, str(local_path))
        return local_path

    async def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=key)
        log.debug("S3Storage: deleted s3://%s/%s", self.bucket, key)

    async def get_url(self, key: str, expires: int = 3600) -> str:
        url = self.client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=expires,
        )
        return url

    async def exists(self, key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except Exception:
            return False


# ======================================================================
# 工厂函数
# ======================================================================

_storage_instance: StorageBackend | None = None


def get_storage() -> StorageBackend:
    """获取存储后端单例"""
    global _storage_instance
    if _storage_instance is None:
        if settings.STORAGE_BACKEND == "s3":
            _storage_instance = S3Storage()
            log.info("存储后端: S3 (bucket=%s)", settings.S3_BUCKET)
        else:
            _storage_instance = LocalStorage()
            log.info("存储后端: 本地磁盘 (%s)", settings.UPLOAD_DIR)
    return _storage_instance
