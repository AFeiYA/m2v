"""Browser origin allow-list. Does not call a deployed server."""
import pytest
from starlette.middleware.cors import CORSMiddleware

from src.api_server import PUBLIC_SITE_ORIGINS, app, install_public_cors, origin_is_allowed


@pytest.mark.parametrize("origin", [
    "https://fovea.si",
    "https://www.fovea.si",
    "https://mv.fovea.si",
    "https://m2v-bdb.pages.dev",
    "https://staging.m2v-bdb.pages.dev",
    "https://abc123.m2v-bdb.pages.dev",
    "http://localhost",
    "http://localhost:8000",
    "http://127.0.0.1:7860",
])
def test_public_and_local_origins_are_allowed(origin):
    assert origin_is_allowed(origin)


@pytest.mark.parametrize("origin", [
    None,
    "*",
    "https://evil.example",
    "https://mv.fovea.si.evil.example",
    "https://not-m2v-bdb.pages.dev",
    "https://m2v-bdb.pages.dev.evil.com",
    "http://localhost.evil.com",
    "http://evil.localhost",
    "https://localhost:8000",
])
def test_unlisted_origins_are_rejected(origin):
    assert origin_is_allowed(origin) is False


def test_standalone_api_does_not_allow_every_origin():
    cors = [item for item in app.user_middleware if item.cls is CORSMiddleware]
    assert len(cors) == 1
    options = cors[0].kwargs
    assert options["allow_credentials"] is True
    assert options["allow_origins"] == list(PUBLIC_SITE_ORIGINS)
    assert "*" not in options["allow_origins"]
    assert "m2v-bdb" in options["allow_origin_regex"]


def test_gradio_reflection_is_replaced_by_the_public_list():
    pytest.importorskip("gradio")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from gradio.route_utils import CustomCORSMiddleware

    app = FastAPI()

    @app.get("/ping")
    def ping():
        return {"ok": True}

    # Gradio's middleware reflects any origin when the host is not localhost.
    app.add_middleware(CustomCORSMiddleware)
    with TestClient(app) as client:
        reflected = client.get("/ping", headers={"Origin": "https://evil.example", "Host": "lucazhou-suno2mv-api.hf.space"})
        assert reflected.headers.get("access-control-allow-origin") == "https://evil.example"

    install_public_cors(app)
    with TestClient(app) as client:
        evil = client.get("/ping", headers={"Origin": "https://evil.example", "Host": "lucazhou-suno2mv-api.hf.space"})
        assert evil.headers.get("access-control-allow-origin") in (None, "")
        site = client.get("/ping", headers={"Origin": "https://mv.fovea.si", "Host": "lucazhou-suno2mv-api.hf.space"})
        assert site.headers.get("access-control-allow-origin") == "https://mv.fovea.si"
        preview = client.get("/ping", headers={"Origin": "https://abc.m2v-bdb.pages.dev", "Host": "lucazhou-suno2mv-api.hf.space"})
        assert preview.headers.get("access-control-allow-origin") == "https://abc.m2v-bdb.pages.dev"
