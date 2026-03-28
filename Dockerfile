# Auto-Karaoke MV Generator
# 基础镜像: CUDA 12.8 + Ubuntu 22.04
FROM nvidia/cuda:12.8.0-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV HF_HOME=/app/models

# 系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.11 \
    python3.11-venv \
    python3-pip \
    ffmpeg \
    libsndfile1 \
    git \
    && ln -sf /usr/bin/python3.11 /usr/bin/python \
    && rm -rf /var/lib/apt/lists/*

# Python 依赖
WORKDIR /app

# 先安装 PyTorch (CUDA 12.8)
RUN pip install --no-cache-dir \
    torch==2.7.1 torchaudio==2.7.1 \
    --index-url https://download.pytorch.org/whl/cu128

# 再安装项目依赖
COPY pyproject.toml .
RUN pip install --no-cache-dir .

# 复制源码
COPY src/ src/
COPY templates/ templates/
COPY assets/ assets/

# 创建输入/输出目录
RUN mkdir -p /app/input /app/output /app/models

ENTRYPOINT ["python", "-m", "src.main"]
CMD ["--input", "/app/input", "--output", "/app/output"]
