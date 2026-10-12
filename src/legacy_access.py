"""Keep directory-based local APIs out of the shared SaaS surface."""

from fastapi import HTTPException, WebSocketException
from starlette.requests import HTTPConnection


async def require_local_api(connection: HTTPConnection) -> None:
    if getattr(connection.app.state, "saas_mode", False) and connection.url.path.startswith(("/api/", "/ws/")):
        if connection.scope["type"] == "websocket":
            raise WebSocketException(code=1008)
        raise HTTPException(403, "本地目录接口不对云端开放，请使用登录后的任务与编辑接口")
