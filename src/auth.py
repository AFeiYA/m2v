"""
认证模块 — JWT 令牌 + 密码哈希 + FastAPI 依赖注入
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import bcrypt as _bcrypt

from fastapi import Depends, HTTPException, status
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


from src.utils import log
from src.models import User, UserPlan


def verify_firebase_id_token(token: str) -> dict | None:
    """尝试通过 firebase-admin 校验 Firebase ID Token"""
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
            "type": "access",
            "provider": "firebase",
        }
    except Exception as e:
        log.debug("Firebase ID Token 校验未通过或为本地令牌: %s", e)
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


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """从 Bearer token 解析当前用户，注入到路由；支持新 Firebase 用户自愈开户"""
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
                password_hash="FIREBASE_AUTH",
                avatar_url=payload.get("picture"),
                plan=UserPlan.FREE,
                credits=settings.FREE_MONTHLY_QUOTA,
                is_active=True,
                is_verified=True,
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

    return user
