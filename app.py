"""
Hugging Face Spaces Entry Point
- 适配 Hugging Face 免费 Gradio SDK (永久免费 16GB 内存，无需绑卡)
- 兼容原生 FastAPI 后端接口 (/api/suno/import, /api/alignment, /api/asset_file 等)
- 支持 Vercel 前端无缝代理请求
"""

import os
import gradio as gr
from src.local_editor import app as fastapi_app

# 0. 自动兼容 Hugging Face ZeroGPU 硬件探测机制
try:
    import spaces

    @spaces.GPU
    def _gpu_probe():
        return "ZeroGPU Ready"
except Exception:
    def _gpu_probe():
        return "CPU Ready"

# 1. 创建漂亮的 Gradio 状态面板
with gr.Blocks(title="Suno2MV Cloud Engine") as demo:
    gr.Markdown("# 🎵 Suno2MV API & Cloud Engine")
    gr.Markdown(
        "### 🟢 服务运行正常 (Online)\n\n"
        "本 Space 正在为 **Suno2MV** 提供云端免费 AI 算力（音频流解密、Demucs 人声分离、卡拉OK词级时间轴对齐）。\n\n"
        "- **前端 Web 访问地址**: [https://mv.fovea.si](https://mv.fovea.si)\n"
        "- **API 接口服务**: `/api/suno/import` 等接口已全天候就绪\n"
        "- **硬件配置**: Hugging Face 免费算力 (2 vCPU · 16GB RAM · 50GB Disk)\n"
    )
    with gr.Accordion("API 健康状态探活", open=False):
        gr.JSON(value={"status": "online", "engine": "Suno2MV Cloud", "version": "0.6.0"})

    # 注册事件以便 ZeroGPU 启动扫描器能够正确识别 GPU 函数
    demo.load(_gpu_probe, inputs=[], outputs=[])

# 2. 将 fastapi_app 中的所有路由与端点无缝注入到 Gradio 的内部 FastAPI 引擎中
demo.app.include_router(fastapi_app.router)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 7860))
    # 使用 Gradio 官方标准的 queue().launch() 保持服务常驻，满足 Hugging Face 平台健康探活
    demo.queue().launch(
        server_name="0.0.0.0",
        server_port=port,
        ssr_mode=False,
        show_error=True,
    )
