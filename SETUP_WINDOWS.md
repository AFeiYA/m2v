# Windows 本地开发环境安装指南

> **适用环境:** Windows 10/11 + NVIDIA GPU + Conda
>
> **实测环境:** RTX 2080 (8GB) / CUDA 12.1 / Miniconda / Windows

---

## 〇、前置条件检查

开始前请确认以下组件已安装：

| 组件 | 最低版本 | 检查命令 |
|------|---------|---------|
| NVIDIA 驱动 | 530+ | `nvidia-smi` |
| CUDA Toolkit | 12.x | `nvcc --version` |
| Conda | 任意 | `conda --version` |
| Git | 任意 | `git --version` |

> 如果 `nvidia-smi` 能看到 GPU 但没装 CUDA Toolkit，可以跳过 —— PyTorch 自带 CUDA Runtime。

---

## 一、创建 Conda 环境

项目使用了 `str | None` 等 Python 3.10+ 语法，**必须 Python ≥ 3.11**。

```powershell
# 如果已有旧的 m2v_app 环境 (Python 3.9)，先删除重建
conda deactivate
conda remove -n m2v_app --all -y

# 创建新环境 (Python 3.11)
conda create -n m2v_app python=3.11 -y

# 激活环境
conda activate m2v_app
```

验证：
```powershell
python --version
# 应输出: Python 3.11.x
```

---

## 二、安装 FFmpeg

FFmpeg 是视频合成的核心依赖，通过 Conda 安装最省事：

```powershell
conda install -c conda-forge ffmpeg -y
```

验证：
```powershell
ffmpeg -version
# 应输出版本号，确认 --enable-libass 存在（ASS 字幕渲染需要）
```

> ⚠️ 如果 Conda 版 FFmpeg 缺少 `libass` 支持，备选方案：
> 从 [gyan.dev](https://www.gyan.dev/ffmpeg/builds/) 下载 `ffmpeg-release-full` 版本，解压后将 `bin/` 加入系统 PATH。

---

## 三、安装 PyTorch (GPU 版)

**根据你的 CUDA 版本选择对应的 PyTorch 安装命令。**

查看 CUDA 版本：
```powershell
nvidia-smi
# 看右上角 "CUDA Version: 12.x" 即为驱动支持的最高 CUDA 版本
```

### CUDA 12.1 (本机实测)

```powershell
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu121
```

### CUDA 12.4 / 12.6 / 12.8 (较新驱动)

```powershell
# CUDA 12.4
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu124
```

### 无 GPU (纯 CPU 回退)

```powershell
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu
```

验证 GPU 可用：
```powershell
python -c "import torch; print(f'PyTorch {torch.__version__}'); print(f'CUDA available: {torch.cuda.is_available()}'); print(f'GPU: {torch.cuda.get_device_name(0)}' if torch.cuda.is_available() else 'CPU mode')"
```

预期输出：
```
PyTorch 2.x.x+cu121
CUDA available: True
GPU: NVIDIA GeForce RTX 2080
```

---

## 四、安装项目 Python 依赖

### 4.1 核心依赖 (逐步安装，方便排错)

```powershell
# 进入项目目录
cd E:\m2v

# WhisperX — 对齐引擎 (会自动安装 faster-whisper, transformers 等)
pip install whisperx

# Demucs — 人声分离
pip install demucs

# Librosa — 音频分析 / 节奏检测
pip install librosa

# 歌词预处理
pip install cn2an opencc-python-reimplemented chardet

# MoviePy (可选，Phase 2+ 使用)
pip install moviepy
```

### 4.2 开发依赖

```powershell
pip install pytest pytest-cov
```

### 4.3 一键安装 (上述全部)

```powershell
cd E:\m2v
pip install -e ".[dev]"
```

> ⚠️ **踩坑提醒:** 如果 `pip install whisperx` 报错，尝试从 GitHub 安装：
> ```powershell
> pip install git+https://github.com/m-bain/whisperX.git
> ```

---

## 五、验证安装

### 5.1 逐一验证核心模块

```powershell
python -c "import whisperx; print(f'WhisperX OK')"
python -c "import demucs; print(f'Demucs OK')"
python -c "import librosa; print(f'Librosa {librosa.__version__}')"
python -c "import cn2an; print(f'cn2an OK')"
python -c "import opencc; print(f'OpenCC OK')"
python -c "import chardet; print(f'chardet OK')"
python -c "from src.config import PipelineConfig; print('项目模块加载 OK')"
```

### 5.2 运行单元测试

```powershell
cd E:\m2v
pytest tests/ -v
```

预期输出：
```
tests/test_preprocessor.py::TestParseTxt::test_basic PASSED
tests/test_preprocessor.py::TestParseLrc::test_basic_lrc PASSED
tests/test_subtitle.py::TestTimeFormatting::test_basic PASSED
tests/test_subtitle.py::TestDialogueLine::test_k_duration PASSED
tests/test_aligner.py::TestFallbackEvenSplit::test_basic PASSED
...
```

### 5.3 端到端快速验证

```powershell
# 准备测试文件
mkdir input -Force
# 将一个 Suno MP3 和对应歌词 TXT 放入 input/
# 例: input/test.mp3 + input/test.txt

# 运行 (CPU 模式快速验证，不需要下载大模型)
python -m src.main -i input/test.mp3 -l input/test.txt -o output --cpu --keep-temp
```

---

## 六、模型下载 (首次运行)

首次运行会自动从 HuggingFace 下载模型，**共约 6-8 GB**：

| 模型 | 大小 | 用途 |
|------|------|------|
| `whisper-large-v3` | ~3 GB | 语音识别 (ASR) |
| `wav2vec2-xlsr` (中文) | ~1.2 GB | 音素级对齐 |
| `htdemucs_ft` | ~160 MB | 人声分离 |

### 设置模型缓存目录 (可选)

默认缓存在 `C:\Users\<你的用户名>\.cache\huggingface\`。如果 C 盘空间紧张：

```powershell
# 加到你的 PowerShell profile 或 conda env 环境变量
$env:HF_HOME = "D:\models\huggingface"
$env:TORCH_HOME = "D:\models\torch"

# 永久设置 (写入 conda 环境)
conda env config vars set HF_HOME=D:\models\huggingface -n m2v_app
conda env config vars set TORCH_HOME=D:\models\torch -n m2v_app
conda activate m2v_app
```

### 网络问题 (国内用户)

如果 HuggingFace 下载缓慢，设置镜像：

```powershell
$env:HF_ENDPOINT = "https://hf-mirror.com"

# 永久设置
conda env config vars set HF_ENDPOINT=https://hf-mirror.com -n m2v_app
```

---

## 七、RTX 2080 (8GB) 专项配置

RTX 2080 的 8GB 显存偏紧，建议按以下配置运行：

### 7.1 修改默认配置 (减少显存占用)

编辑 `src/config.py`，将 AlignerConfig 中的默认值调整为：

```python
@dataclass
class AlignerConfig:
    whisper_model: str = "large-v3"
    device: str = "cuda"
    compute_type: str = "int8"       # ← float16 改为 int8，省约 2GB 显存
    language: str = "zh"
    batch_size: int = 8              # ← 16 改为 8，省约 1GB 显存
```

### 7.2 运行时指定 (不改代码)

如果运行时遇到 `CUDA out of memory`，使用 CPU 跑对齐、GPU 跑分离：

```powershell
# 最保险: 全 CPU
python -m src.main -i ./input -o ./output --cpu

# 或: 先手动分步执行，分离用 GPU，对齐用 CPU (后续可加 --align-cpu 参数)
```

---

## 八、常见问题

### Q1: `pip install whisperx` 报 `No matching distribution`

WhisperX 可能还没发到 PyPI，从 GitHub 安装：
```powershell
pip install git+https://github.com/m-bain/whisperX.git
```

### Q2: `import torch` 报 `DLL load failed`

CUDA 版本不匹配。确认安装了对应 CUDA 版本的 PyTorch：
```powershell
pip uninstall torch torchaudio -y
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu121
```

### Q3: FFmpeg 报 `Unrecognized option 'vf subtitles'`

FFmpeg 缺少 `libass` 库。换用完整版 FFmpeg：
- 从 [gyan.dev](https://www.gyan.dev/ffmpeg/builds/) 下载 **full_build**
- 解压到 `C:\tools\ffmpeg\`，将 `C:\tools\ffmpeg\bin` 加入 PATH

### Q4: Demucs 运行时报 `torch.cuda.OutOfMemoryError`

RTX 2080 跑 Demucs 通常没问题，但如果同时有其他 GPU 程序：
```powershell
# 关闭其他占 GPU 的程序，或使用 CPU
$env:DEMUCS_DEVICE = "cpu"
```

### Q5: 中文对齐效果差 / 很多字没有时间戳

1. 确认已跑 Demucs 分离人声（直接用混音对齐效果很差）
2. 确认歌词与音频匹配（不是别首歌的歌词）
3. 查看 `output/xxx_alignment.json`，检查 fallback 行数

### Q6: `cn2an` 转换报错

某些非标准数字格式可能导致 cn2an 崩溃，已在代码中做了 try/except 兜底。
如果频繁出错，可关闭数字转换：
```python
config.preprocessor.convert_numbers = False
```

---

## 九、开发常用命令速查

```powershell
# 激活环境
conda activate m2v_app

# 运行单元测试
pytest tests/ -v

# 单文件处理
python -m src.main -i song.mp3 -l song.txt -o output

# 批量处理 (input/ 目录下所有 mp3+txt 配对)
python -m src.main -i ./input -o ./output

# 带背景图
python -m src.main -i ./input -o ./output -bg background.jpg

# 启用节奏动画
python -m src.main -i ./input -o ./output --beat-effects

# 保留中间文件 (调试)
python -m src.main -i ./input -o ./output --keep-temp

# CPU 模式
python -m src.main -i ./input -o ./output --cpu
```

---

## 十、安装顺序总结 (TL;DR)

```powershell
# 1. 创建环境
conda create -n m2v_app python=3.11 -y
conda activate m2v_app

# 2. FFmpeg
conda install -c conda-forge ffmpeg -y

# 3. PyTorch GPU (根据你的 CUDA 版本选)
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu121

# 4. 项目依赖
cd E:\m2v
pip install -e ".[dev]"

# 5. 验证
python -c "import torch; print(torch.cuda.is_available())"
pytest tests/ -v

# 6. 运行
python -m src.main -i ./input -o ./output
```
