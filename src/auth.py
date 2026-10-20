"""
认证模块 — JWT 令牌 + 密码哈希 + FastAPI 依赖注入
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import bcrypt as _bcrypt

from fastapi import Depends, HTTPException, Query, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db
from src.models import User
from src.settings import get_settings

settings = get_settings()

# ── 密码哈希 (直接使用 bcrypt，兼容 4.x/5.x) ────────────


def hash_password(password: str) -> str:
    return _bcrypt.hashpw(password.encode(), _bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return _bcrypt.checkpw(plain.encode(), hashed.encode())


# ── JWT 令牌 ─────────────────────────────────────────────

def create_access_token(user_id: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
    )
    payload = {"sub": user_id, "exp": expire, "type": "access"}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_refresh_token(user_id: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(
        days=settings.REFRESH_TOKEN_EXPIRE_DAYS
    )
    payload = {"sub": user_id, "exp": expire, "type": "refresh"}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


import os
import jwt as pyjwt
from jwt import PyJWKClient

from src.utils import log
from src.models import User, UserPlan

_jwks_client: PyJWKClient | None = None


def _get_jwks_client() -> PyJWKClient:
    global _jwks_client
    if _jwks_client is None:
        _jwks_client = PyJWKClient(
            "https://www.googleapis.com/service_accounts/v1/jwk/securetoken@system.gserviceaccount.com",
            cache_keys=True,
            max_cached_keys=16,
        )
    return _jwks_client


def verify_firebase_id_token(token: str) -> dict | None:
    """验证 Firebase ID Token（优先使用 Google 官方 JWKS 公钥验签，兼容 firebase-admin）"""
    # 方式 1: 使用 Google 官方 JWKS 公钥直接验签（云端容器/第三方托管首选，免 GCP 服务账号密钥）
    try:
        unverified_header = pyjwt.get_unverified_header(token)
        if unverified_header.get("alg") == "RS256":
            client = _get_jwks_client()
            signing_key = client.get_signing_key_from_jwt(token)
            decoded = pyjwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                options={"verify_aud": False},
            )

            aud = decoded.get("aud")
            iss = decoded.get("iss")
            if iss != f"https://securetoken.google.com/{aud}":
                log.warning("Firebase ID Token 签发者不匹配: iss=%s, aud=%s", iss, aud)
                return None

            allowed_projects = {"dc-test-731fa"}
            for proj in [
                getattr(settings, "FIREBASE_PROJECT_ID", ""),
                os.getenv("FIREBASE_PROJECT_ID", ""),
                os.getenv("GOOGLE_CLOUD_PROJECT", ""),
            ]:
                if proj:
                    for p in proj.split(","):
                        p_clean = p.strip()
                        if p_clean:
                            allowed_projects.add(p_clean)

            if allowed_projects and aud not in allowed_projects:
                log.warning(
                    "Firebase ID Token 项目 ID 不在白名单中: aud=%s, allowed=%s",
                    aud,
                    allowed_projects,
                )
                return None

            return {
                "sub": decoded.get("user_id") or decoded.get("sub"),
                "email": decoded.get("email"),
                "name": decoded.get("name"),
                "picture": decoded.get("picture"),
                "email_verified": decoded.get("email_verified", False),
                "type": "access",
                "provider": "firebase",
            }
    except Exception as e:
        log.debug("Google JWKS 公钥验签未通过: %s", e)

    # 方式 2: 尝试 firebase-admin (若部署在 GCP 或配置了 service account)
    try:
        import firebase_admin
        from firebase_admin import auth as fb_auth

        try:
            firebase_admin.get_app()
        except ValueError:
            firebase_admin.initialize_app()

        decoded = fb_auth.verify_id_token(token)
        return {
            "sub": decoded["uid"],
            "email": decoded.get("email"),
            "name": decoded.get("name"),
            "picture": decoded.get("picture"),
            "email_verified": decoded.get("email_verified", False),
            "type": "access",
            "provider": "firebase",
        }
    except Exception as e:
        log.debug("firebase_admin 校验未通过或为本地令牌: %s", e)
        return None


def decode_token(token: str) -> dict:
    """解码 JWT，支持 Firebase ID Token 与本地开发 JWT，失败抛 HTTPException 401"""
    # 1. 优先尝试 Firebase ID Token 验签
    fb_payload = verify_firebase_id_token(token)
    if fb_payload:
        return fb_payload

    # 2. 回退到本地 JWT 验签 (用于测试及离线开发)
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
        )
        return payload
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效或过期的令牌",
            headers={"WWW-Authenticate": "Bearer"},
        )


# ── FastAPI 依赖 ─────────────────────────────────────────

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")
oauth2_scheme_optional = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)


async def get_user_from_token(token: str, db: AsyncSession) -> User:
    """从 token 解析当前用户并校验有效性；支持新 Firebase 用户自愈开户"""
    payload = decode_token(token)

    if payload.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="需要 access_token",
        )

    user_id: str | None = payload.get("sub")
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="令牌缺少用户标识",
        )

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if user is None:
        if payload.get("provider") == "firebase":
            # Firebase 用户首次请求：自动激活初始化用户记录与初始配额
            email = payload.get("email") or f"{user_id}@firebase.user"
            raw_name = payload.get("name") or email.split("@")[0]
            username = f"{raw_name}_{user_id[:6]}"
            user = User(
                id=user_id,
                email=email,
                username=username,
                display_name=payload.get("name") or raw_name,
                password_hash="FIREBASE_AUTH",
                avatar_url=payload.get("picture"),
                plan=UserPlan.FREE,
                credits=settings.NEW_USER_PERMANENT_CREDITS,
                is_active=True,
                is_verified=bool(payload.get("email_verified", False)),
            )
            db.add(user)
            await db.commit()
            await db.refresh(user)
            log.info("🎉 自动开户新 Firebase 用户: %s (%s)", user_id, email)
        else:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="用户不存在或已禁用",
            )
    elif not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户已禁用",
        )

    if payload.get("provider") == "firebase":
        # Email/password users are not verified until Firebase confirms the email.
        user.is_verified = bool(payload.get("email_verified", False))
        if not user.display_name and payload.get("name"):
            user.display_name = payload.get("name")
    return user


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """从 Bearer token 解析当前用户，注入到路由"""
    return await get_user_from_token(token, db)


async def get_current_user_flexible(
    token_header: str | None = Depends(oauth2_scheme_optional),
    token_query: str | None = Query(None, alias="token"),
    db: AsyncSession = Depends(get_db),
) -> User:
    """从 Bearer header 或 URL query ?token=xxx 解析当前用户，用于文件下载与特殊请求"""
    token = token_header or token_query
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="缺少访问令牌",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return await get_user_from_token(token, db)
