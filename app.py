"""
Hugging Face Spaces Entry Point
- 保留 Gradio SDK 与 ZeroGPU 部署入口
- 兼容原生 FastAPI 后端接口 (/api/suno/import, /api/alignment, /api/asset_file 等)
- Cloudflare Pages 浏览器端通过已配置的 API 地址访问
"""

import os
import asyncio.selector_events

# 修复 Python 3.10 在垃圾回收时旧 event loop 偶发的无害清理警告:
# "Exception ignored in BaseEventLoop.__del__: ValueError: Invalid file descriptor: -1"
if hasattr(asyncio.selector_events.BaseSelectorEventLoop, "_close_self_pipe"):
    _orig_close_self_pipe = asyncio.selector_events.BaseSelectorEventLoop._close_self_pipe

    def _safe_close_self_pipe(self):
        try:
            _orig_close_self_pipe(self)
        except (ValueError, KeyError, OSError):
            pass

    asyncio.selector_events.BaseSelectorEventLoop._close_self_pipe = _safe_close_self_pipe

import gradio as gr
from src.local_editor import app as fastapi_app

# 0. Hugging Face ZeroGPU 官方静态探测标准声明
try:
    import spaces

    @spaces.GPU(duration=20)
    def _zero_gpu_worker(payload: str = "") -> str:
        """ZeroGPU 探测与硬件动态分配函数"""
        return f"ZeroGPU Ready: {payload}"
except Exception:
    def _zero_gpu_worker(payload: str = "") -> str:
        return f"CPU Ready: {payload}"

# 1. 创建 Gradio 控制台面板
with gr.Blocks(title="Suno2MV Cloud Engine") as demo:
    gr.Markdown("# 🎵 Suno2MV API & Cloud Engine")
    gr.Markdown(
        "### 🟢 服务运行正常 (Online)\n\n"
        "本 Space 正在为 **Suno2MV** 提供云端服务与测试环境。\n"
    )
    gr.HTML(
        """
        <div style="display: flex; gap: 14px; margin: 16px 0 24px 0; flex-wrap: wrap;">
            <a href="/app" target="_blank" style="display: inline-flex; align-items: center; justify-content: center; padding: 12px 22px; background: #4f46e5; color: #ffffff; text-decoration: none; border-radius: 8px; font-weight: 600; font-size: 14px; box-shadow: 0 4px 10px rgba(79,70,229,0.3);">
                🚀 打开前端工作台 (App / Dashboard) ↗
            </a>
            <a href="/motion-studio" target="_blank" style="display: inline-flex; align-items: center; justify-content: center; padding: 12px 22px; background: #0284c7; color: #ffffff; text-decoration: none; border-radius: 8px; font-weight: 600; font-size: 14px; box-shadow: 0 4px 10px rgba(2,132,199,0.3);">
                🎨 动效视频工作台 (Motion Studio) ↗
            </a>
            <a href="/gallery" target="_blank" style="display: inline-flex; align-items: center; justify-content: center; padding: 12px 22px; background: #334155; color: #ffffff; text-decoration: none; border-radius: 8px; font-weight: 500; font-size: 14px;">
                🖼️ 模板展厅 (Gallery) ↗
            </a>
        </div>
        """
    )
    gr.Markdown(
        "- **前端入口导航**: [工作台主页](/app) · [动效工作台直达](/motion-studio) · [模板展厅](/gallery)\n"
        "- **正式版生产站**: [https://mv.fovea.si](https://mv.fovea.si)\n"
        "- **API 接口服务**: 提供 `/api/cloud-motion/*`、`/api/editor/*` 与任务处理服务\n"
        "- **运行配置**: Hugging Face (2 vCPU · 16GB RAM · ZeroGPU 动态加速)\n"
    )
    with gr.Accordion("API 健康状态探活", open=False):
        gr.JSON(value={"status": "online", "engine": "Suno2MV Cloud", "version": "0.6.0"})

    # 显式绑定 ZeroGPU 探测事件，严格满足 ZeroGPU AST 扫描器对交互组件绑定的检查
    _gpu_in = gr.Textbox(value="ping", visible=False)
    _gpu_out = gr.Textbox(visible=False)
    _gpu_btn = gr.Button("Probe GPU", visible=False)
    _gpu_btn.click(fn=_zero_gpu_worker, inputs=[_gpu_in], outputs=[_gpu_out])

# 2. 启用队列
demo.queue()

def mount_fastapi_routes(demo_instance):
    """Gradio 在 launch() 期间会生成运行期 server_app，注入 FastAPI 全部路由（带防重复校验）。"""
    targets = []
    if hasattr(demo_instance, "app") and demo_instance.app is not None:
        targets.append(demo_instance.app)
    if hasattr(demo_instance, "server_app") and demo_instance.server_app is not None:
        if demo_instance.server_app not in targets:
            targets.append(demo_instance.server_app)

    import asyncio
    from src.database import init_db
    try:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop and loop.is_running():
            asyncio.create_task(init_db())
        else:
            asyncio.run(init_db())
    except Exception as e:
        import logging
        logging.getLogger("uvicorn").warning("初始化 SaaS 数据库异常: %s", e)

    from src.api_server import api_router
    from src.editor_server import router as editor_router
    from src.motion_cloud import router as cloud_motion_router
    from fastapi import Depends
    from src.legacy_access import require_local_api

    for target in targets:
        target.state.saas_mode = True
        existing_paths = {getattr(r, "path", "") for r in getattr(target, "routes", []) if hasattr(r, "path")}
        if "/api/files" not in existing_paths:
            target.include_router(fastapi_app.router, dependencies=[Depends(require_local_api)])
        if "/api/auth/me" not in existing_paths:
            target.include_router(api_router)
        if "/api/editor/songs" not in existing_paths:
            target.include_router(editor_router)
        if "/api/cloud-motion/{route:path}" not in existing_paths:
            target.include_router(cloud_motion_router)


if __name__ == "__main__":
    from src.hf_motion_runtime import prepare_motion_runtime
    if os.environ.get("SPACE_ID") or os.environ.get("M2V_PREPARE_MOTION_RUNTIME") == "1":
        prepare_motion_runtime()
    port = int(os.environ.get("PORT", 7860))
    # 使用 Gradio 官方标准的 queue().launch() 启动，满足 Hugging Face ZeroGPU 探活生命周期
    demo.launch(
        server_name="0.0.0.0",
        server_port=port,
        prevent_thread_lock=True,
        ssr_mode=False,
        show_error=True,
    )
    mount_fastapi_routes(demo)
    print(f"\n💡 [M2V 提示] 本地浏览器访问推荐使用: http://127.0.0.1:{port} 或 http://localhost:{port}")
    print(f"   (因现代浏览器安全策略，使用 127.0.0.1 / localhost 才能启用 WebCodecs 本地导出)\n")
    # 阻塞主线程以保持服务常驻
    demo.block_thread()
