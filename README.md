# Auto-Karaoke MV Generator

将 Suno 生成的 MP3 音频 + 本地歌词文件，通过全自动 Python 管线，产出具有专业卡拉OK逐字变色效果的宣传视频。

## 快速开始

### 方式 1: Docker (推荐)

```bash
# 构建镜像
docker compose build

# 将 MP3 和同名 TXT/LRC 放入 input/ 目录
cp song.mp3 song.txt input/

# 运行
docker compose up
# 输出在 output/ 目录
```

### 方式 2: 本地运行

```bash
# 安装依赖 (需要 Python 3.11+, CUDA, FFmpeg)
pip install -e .

# 批量处理
python -m src.main --input ./input --output ./output

# 单文件处理
python -m src.main -i song.mp3 -l song.txt -o ./output

# 使用背景图
python -m src.main -i ./input -o ./output -bg background.jpg

# CPU 模式 (无 GPU)
python -m src.main -i ./input -o ./output --cpu

# 启用节奏动画
python -m src.main -i ./input -o ./output --beat-effects

# 已经是纯人声，跳过 Demucs
python -m src.main -i ./input -o ./output --skip-separation

# 只生成 ASS 字幕 + 对齐 JSON
python -m src.main -i ./input -o ./output --ass-only

# 复用已有对齐结果，直接生成 ASS/视频
python -m src.main -i ./input -o ./output --alignment-json ./output/{stem}_alignment.json

# 使用配置文件控制流程
python -m src.main -i ./input -o ./output --config-file ./pipeline.toml
```

## CLI 参数

| 参数 | 说明 |
|------|------|
| `--input, -i` | 输入目录 (批量) 或 MP3 文件路径 (单文件) |
| `--lyrics, -l` | 歌词文件路径，单文件模式使用 |
| `--output, -o` | 输出目录，默认 `./output` |
| `--background, -bg` | 背景素材 (.jpg/.png/.mp4)，不指定则纯黑 |
| `--language` | 语言代码，默认 `zh` |
| `--cpu` | 强制 CPU 模式 |
| `--beat-effects` | 启用节奏同步字幕动画 |
| `--keep-temp` | 保留中间文件 (调试用) |
| `--skip-separation` | 跳过 Demucs 人声分离，直接用原音频对齐 |
| `--alignment-json` | 复用已有对齐 JSON（支持 `{stem}` 占位符） |
| `--ass-only` | 只生成 ASS + 对齐 JSON，不生成 MP4 |
| `--config-file` | 加载 `.toml/.json` 配置文件控制步骤 |

### 配置文件示例

pipeline.toml:

```toml
[pipeline]
skip_separation = true
ass_only = true
alignment_json = "./output/{stem}_alignment.json"
```

## 输出文件

```
output/
├── song.mp4              # 最终卡拉OK视频
├── song.ass              # ASS 字幕文件 (可单独使用)
└── song_alignment.json   # 词级对齐数据 (可复用)
```

## 管线流程

```
MP3 + TXT/LRC
    → [歌词预处理] 数字转文字/繁简转换/符号清理
    → [Demucs] 人声分离 → vocals.wav
    → [WhisperX] 词级对齐 → timestamps.json
    → [ASS生成] 卡拉OK \k 标签 → karaoke.ass
    → [FFmpeg] 视频合成 → final.mp4
```

## 技术栈

- **Demucs v4**: 人声分离 (htdemucs_ft)
- **WhisperX**: 词级 forced alignment
- **ASS**: 卡拉OK `\k` 变色标签
- **FFmpeg**: 视频合成
- **Librosa**: 节奏检测 (可选)
