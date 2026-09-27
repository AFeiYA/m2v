FROM python:3.11-slim

# 安装 FFmpeg (含 libass 完整字幕支持) 与 中文字体
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libass-dev \
    fonts-noto-cjk \
    fonts-wqy-zenhei \
    curl \
    git \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# 创建普通用户 (Hugging Face Spaces 规范 UID 1000)
RUN useradd -m -u 1000 user
WORKDIR /app

# 安装 PyTorch CPU 版本 (避免拉取 CUDA 权重，轻量且构建快)
RUN pip install --no-cache-dir torch torchaudio --index-url https://download.pytorch.org/whl/cpu

# 安装 Python 依赖
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir demucs librosa

# 拷贝代码与静态资源
COPY --chown=user:user . /app

# 确保输出目录权限
RUN mkdir -p /app/output /app/input /app/assets && chown -R user:user /app

USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    PYTHONUNBUFFERED=1

# 暴露端口 (Hugging Face 默认 7860，亦支持自定义 PORT)
EXPOSE 7860

CMD ["sh", "-c", "uvicorn src.local_editor:app --host 0.0.0.0 --port ${PORT:-7860}"]
