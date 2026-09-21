---
name: activate-m2v
description: "激活 m2v 开发环境。Use when: 运行项目前需要激活 conda 环境、安装依赖、启动本地编辑器、运行测试或任何需要 Python 环境的操作。Triggers: conda activate m2v, 激活环境, 开发环境, 启动编辑器, 运行项目"
argument-hint: "可选：要在环境中执行的命令"
---

# 激活 m2v 开发环境

## 环境信息

- **Conda 环境**: `m2v`
- **Python**: miniconda3（位于 `C:\tools\miniconda3`）
- **项目根目录**: `E:\m2v`
- **主要入口**: `python -m src.local_editor`

## 激活步骤

### 1. 激活 Conda 环境

```powershell
conda activate m2v
```

如果 `conda` 不在 PATH 中，先初始化：

```powershell
(C:\tools\miniconda3\shell\condabin\conda-hook.ps1) ; (conda activate m2v)
```

### 2. 验证环境

```powershell
python --version
python -c "import uvicorn; print('uvicorn OK')"
```

### 3. 启动本地编辑器

```powershell
cd E:\m2v
python -m src.local_editor
```

可选参数：
- `--dir E:/m2v/output` — 指定 alignment.json 扫描目录
- `--port 8765` — 指定端口（默认 8765）
- `--no-browser` — 不自动打开浏览器

## 常用命令

| 任务 | 命令 |
|------|------|
| 激活环境 | `conda activate m2v` |
| 启动编辑器 | `python -m src.local_editor` |
| 运行测试 | `pytest tests/` |
| 安装依赖 | `pip install -e .` |
| 检查依赖 | `pip list` |

## 注意事项

- 每次打开新终端都需要重新激活环境
- 若遇到 `ModuleNotFoundError`，先确认已激活 `m2v` 环境
- 编辑器默认监听 `http://127.0.0.1:8765`
