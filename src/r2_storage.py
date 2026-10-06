"""Cloudflare R2 / S3 兼容对象存储管理模块。

支持免出网流量费用的 Cloudflare R2 自动化上传与 CDN 分发。
未配置凭证时平滑降级为本地存储模式，保证现有业务零中断。
"""
from __future__ import annotations
import os
from pathlib import Path
from typing import Any
from dotenv import load_dotenv
from src.utils import log

# 加载环境变量
load_dotenv()


class R2StorageManager:
    """Cloudflare R2 存储客户端"""

    def __init__(self) -> None:
        self.account_id = os.getenv("R2_ACCOUNT_ID", "").strip()
        self.access_key_id = os.getenv("R2_ACCESS_KEY_ID", "").strip()
        self.secret_access_key = os.getenv("R2_SECRET_ACCESS_KEY", "").strip()
        self.bucket = os.getenv("R2_BUCKET_NAME", os.getenv("R2_BUCKET", "suno2mv-videos")).strip()
        self.public_domain = os.getenv("R2_PUBLIC_DOMAIN", os.getenv("R2_CUSTOM_DOMAIN", "")).strip().rstrip("/")
        self.endpoint_url = os.getenv("R2_ENDPOINT_URL", "").strip()

        if not self.endpoint_url and self.account_id:
            self.endpoint_url = f"https://{self.account_id}.r2.cloudflarestorage.com"

        self._client: Any = None

    def is_configured(self) -> bool:
        """检查 R2 是否配置了必要凭证"""
        return bool(
            self.endpoint_url
            and self.access_key_id
            and self.secret_access_key
            and self.bucket
        )

    def get_client(self) -> Any:
        """延迟初始化 boto3 s3 client"""
        if self._client is not None:
            return self._client
        if not self.is_configured():
            return None
        try:
            import boto3
            from botocore.config import Config

            self._client = boto3.client(
                "s3",
                endpoint_url=self.endpoint_url,
                aws_access_key_id=self.access_key_id,
                aws_secret_access_key=self.secret_access_key,
                region_name="auto",
                config=Config(
                    signature_version="s3v4",
                    retries={"max_attempts": 3, "mode": "standard"},
                ),
            )
            return self._client
        except Exception as exc:
            log.warning(f"R2 客户端初始化异常: {exc}")
            return None

    def upload_video(
        self,
        file_path: Path | str,
        object_key: str | None = None,
        content_type: str = "video/mp4",
    ) -> dict[str, Any] | None:
        """上传本地 MP4 文件到 Cloudflare R2 并返回公开访问链接。"""
        path = Path(file_path).resolve()
        if not path.exists():
            log.warning(f"R2 上传跳过，文件不存在: {path}")
            return None

        client = self.get_client()
        if client is None:
            return None

        key = object_key or f"exports/{path.name}"
        try:
            log.info(f"开始上传视频至 Cloudflare R2 [{self.bucket}]: {key} ({path.stat().st_size / 1024 / 1024:.2f} MB)")
            client.upload_file(
                str(path),
                self.bucket,
                key,
                ExtraArgs={
                    "ContentType": content_type,
                    "CacheControl": "public, max-age=31536000, immutable",
                },
            )

            # 构建公开 URL
            if self.public_domain:
                url = f"{self.public_domain}/{key.lstrip('/')}"
            else:
                # 默认生成长期签名链接（有效 7 天）
                url = client.generate_presigned_url(
                    "get_object",
                    Params={"Bucket": self.bucket, "Key": key},
                    ExpiresIn=86400 * 7,
                )

            log.info(f"Cloudflare R2 视频上传完成: {url}")
            return {
                "key": key,
                "url": url,
                "bucket": self.bucket,
                "size": path.stat().st_size,
            }
        except Exception as exc:
            log.warning(f"Cloudflare R2 上传失败: {exc}")
            return None

    def delete_video(self, object_key: str) -> bool:
        """从 R2 中删除指定的视频"""
        client = self.get_client()
        if client is None:
            return False
        try:
            client.delete_object(Bucket=self.bucket, Key=object_key)
            log.info(f"R2 文件已删除: {object_key}")
            return True
        except Exception as exc:
            log.warning(f"R2 删除文件失败: {exc}")
            return False

    def get_status_info(self) -> dict[str, Any]:
        """返回当前 R2 的配置与联通状态信息"""
        configured = self.is_configured()
        return {
            "configured": configured,
            "provider": "Cloudflare R2",
            "bucket": self.bucket if configured else "",
            "public_domain": self.public_domain if configured else "",
            "has_endpoint": bool(self.endpoint_url),
            "custom_cdn": bool(self.public_domain),
        }


# 全局单例
r2_storage = R2StorageManager()
