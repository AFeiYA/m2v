# Auto-Karaoke MV Generator
# 基础镜像: CUDA 12.6 + Ubuntu 22.04
FROM nvidia/cuda:12.6.3-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV HF_HOME=/app/models

# 系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.11 \
    python3.11-venv \
    python3.11-distutils \
    ffmpeg \
    libsndfile1 \
    git \
    curl \
    && ln -sf /usr/bin/python3.11 /usr/bin/python \
    && rm -rf /var/lib/apt/lists/*

# Bootstrap pip for python3.11 via get-pip.py
RUN curl -sS https://bootstrap.pypa.io/get-pip.py | python \
    && python -m pip install --no-cache-dir --upgrade pip setuptools wheel

# Python 依赖
WORKDIR /app

# 先安装 PyTorch (CUDA 12.6)
RUN python -m pip install --no-cache-dir \
    torch torchaudio \
    --index-url https://download.pytorch.org/whl/cu126

# 再安装项目依赖
COPY pyproject.toml .
RUN python -m pip install --no-cache-dir \
    --extra-index-url https://download.pytorch.org/whl/cu126 \
    .

# 复制源码
COPY src/ src/
COPY templates/ templates/
COPY assets/ assets/

# 创建输入/输出目录
RUN mkdir -p /app/input /app/output /app/models

ENTRYPOINT ["python", "-m", "src.main"]
CMD ["--input", "/app/input", "--output", "/app/output"]
