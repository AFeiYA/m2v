"""
集成测试：Hugging Face 容器入口 (app.py) 路由挂载完整性测试
防止 Gradio launch 覆盖 FastAPI server_app 导致线上 404 故障。
"""
import socket
from contextlib import closing
import pytest
import requests


def find_free_port() -> int:
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind(('', 0))
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return s.getsockname()[1]


def get_all_router_paths(obj):
    """递归获取 FastAPI / Starlette 路由表中的所有路径"""
    paths = set()
    routes = getattr(obj, "routes", [])
    for r in routes:
        if hasattr(r, "path"):
            paths.add(r.path)
        if hasattr(r, "original_router"):
            paths.update(get_all_router_paths(r.original_router))
        if hasattr(r, "routes"):
            paths.update(get_all_router_paths(r))
    return paths


def test_hf_app_entrypoint_routes():
    """验证 app.py 启动后，FastAPI 的所有后端路由均完整注册到 Gradio server_app"""
    pytest.importorskip("gradio", reason="需要安装 Gradio 才能运行 Hugging Face 容器入口测试")
    import app

    port = find_free_port()
    app.demo.launch(
        server_name="127.0.0.1",
        server_port=port,
        prevent_thread_lock=True,
        ssr_mode=False,
        show_error=True,
    )
    app.mount_fastapi_routes(app.demo)

    base_url = f"http://127.0.0.1:{port}"

    # 1. 结构比对：FastAPI 注册的所有路由必须 100% 存在于 Gradio server_app
    expected_paths = get_all_router_paths(app.fastapi_app)
    actual_paths = get_all_router_paths(app.demo.server_app)
    missing = expected_paths - actual_paths
    assert not missing, f"致命错误：Gradio server_app 遗漏了以下 API 路由：{missing}"

    # 2. 网络真实链路探活：关键业务接口绝对不能返回 404 Not Found
    endpoints = [
        ("GET", "/api/files"),
        ("GET", "/motion_studio"),
        ("GET", "/motion_lab"),
        ("GET", "/api/motion/projects"),
        ("GET", "/api/motion/director/config"),
        ("POST", "/api/suno/import"),
        ("GET", "/api/suno/task_status"),
        ("GET", "/api/suno/download_mp3"),
        ("GET", "/api/download/original_mp3"),
        ("GET", "/api/lyric_video/templates"),
        ("POST", "/api/lyric_video/export"),
        ("GET", "/api/lyric_video/task_status"),
        ("GET", "/api/alignment"),
        ("POST", "/api/regen"),
        ("GET", "/api/comfyui/status"),
        ("GET", "/api/gpu/status"),
    ]

    for method, path in endpoints:
        if method == "GET":
            resp = requests.get(f"{base_url}{path}")
        else:
            resp = requests.post(f"{base_url}{path}", json={})

        assert resp.status_code != 404, (
            f"生产入口路由缺失: {method} {path} 返回了 404 Not Found! 检查 app.py 路由挂载。"
        )

    # 3. 业务功能端到端响应校验
    res_files = requests.get(f"{base_url}/api/files")
    assert res_files.status_code == 200
    assert isinstance(res_files.json(), list)

    res_suno = requests.post(f"{base_url}/api/suno/import", json={"url": ""})
    assert res_suno.status_code == 400
    assert "Suno URL" in res_suno.json().get("detail", "")

    # 已构建资源也必须通过 Gradio 的运行期路由提供。
    from pathlib import Path
    if (Path(app.__file__).parent / "frontend/local/motion/studio.js").exists():
        response = requests.get(f"{base_url}/motion/studio.js")
        assert response.status_code == 200
        assert "javascript" in response.headers.get("content-type", "")

    # 关闭当前测试实例
    app.demo.close()
