"""Keep directory-based local APIs out of the shared SaaS surface."""

from fastapi import HTTPException, WebSocketException
from starlette.requests import HTTPConnection


async def require_local_api(connection: HTTPConnection) -> None:
    if getattr(connection.app.state, "saas_mode", False):
        path = connection.url.path
        if path.startswith(("/api/", "/ws/")):
            if connection.scope["type"] == "websocket":
                raise WebSocketException(code=1008)

            # 1. 公开元数据探测与隐私政策接口放行
            if path in ("/api/suno/publish_status", "/privacy/extension"):
                return

            # Stateless public-song audio retrieval only. Video work now uses
            # owned SaaS tasks; a valid token cannot authorize global local jobs.
            if path in (
                "/api/suno/download_mp3",
            ):
                token = connection.query_params.get("token")
                if not token:
                    auth_header = connection.headers.get("authorization", "")
                    if auth_header.startswith("Bearer "):
                        token = auth_header[7:].strip()
                if not token and hasattr(connection, "cookies"):
                    token = connection.cookies.get("m2v_token")
                if not token:
                    raise HTTPException(401, "请先在 Chrome 插件中同步或配置登录凭据")
                try:
                    from src.auth import decode_token

                    payload = decode_token(token)
                    if payload.get("type") != "access" or not payload.get("sub"):
                        raise ValueError("缺少用户标识或令牌类型无效")
                except Exception:  # noqa: BLE001
                    raise HTTPException(401, "插件登录凭据无效或已过期，请重新在插件中同步")
                from src.auth import require_verified_email
                require_verified_email(payload)
                return

            # 3. 其他单机本地目录接口在云端一律拦截
            raise HTTPException(403, "本地目录接口不对云端开放，请使用登录后的任务与编辑接口")
