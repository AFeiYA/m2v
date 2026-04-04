# Auto-Karaoke MV Generator
# 基础镜像: CUDA 12.6 + Ubuntu 22.04
FROM nvidia/cuda:12.6.3-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV HF_HOME=/app/models
ENV LD_LIBRARY_PATH=/usr/lib/x86_64-linux-gnu:${LD_LIBRARY_PATH}

# 系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.11 \
    python3.11-venv \
    python3.11-distutils \
    python3.11-dev \
    ffmpeg \
    libavutil-dev \
    libavcodec-dev \
    libavformat-dev \
    libavdevice-dev \
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

# 先安装 PyTorch (CUDA 12.6) — 版本须匹配 whisperx 的 torch~=2.8.0
RUN --mount=type=cache,target=/root/.cache/pip \
    python -m pip install \
    "torch>=2.8.0,<2.9.0" "torchaudio>=2.8.0,<2.9.0" \
    --index-url https://download.pytorch.org/whl/cu126

# 冻结 torch 版本，防止后续安装时被 PyPI CPU 版覆盖
RUN python -m pip freeze | grep -iE "^torch" > /tmp/torch-constraints.txt

# 先单独装重依赖（避免 pip resolution-too-deep）
RUN --mount=type=cache,target=/root/.cache/pip \
    python -m pip install -c /tmp/torch-constraints.txt \
    "whisperx>=3.8.4" "demucs>=4.0.0"

# 再安装项目其余依赖
COPY pyproject.toml .
RUN --mount=type=cache,target=/root/.cache/pip \
    python -m pip install -c /tmp/torch-constraints.txt --no-deps .
RUN --mount=type=cache,target=/root/.cache/pip \
    python -m pip install -c /tmp/torch-constraints.txt \
    "pyyaml>=6.0" "librosa>=0.11.0" "cn2an>=0.5.22" \
    "opencc-python-reimplemented>=0.1.7" "chardet>=5.0.0" \
    "moviepy>=2.0.0" "pypinyin>=0.50.0"

# 复制源码
COPY src/ src/
COPY templates/ templates/
COPY assets/ assets/

# 创建输入/输出目录
RUN mkdir -p /app/input /app/output /app/models

ENTRYPOINT ["python", "-m", "src.main"]
CMD ["--input", "/app/input", "--output", "/app/output"]
