"""Prepare Remotion for the existing Gradio Space, without changing its SDK."""
from __future__ import annotations

import hashlib
import os
import platform
import shutil
import subprocess
import tempfile
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
NODE_VERSION = '22.23.3'
NODE_CHECKSUMS = {
    'x64': 'df450af89261115ef9f9e3830c3eeb2cc9213b63c720b1af623cb5dcbe2e02de',
    'arm64': 'a44aeb94849a299b22df10b9e622ec2f605c2183501bc40590705131de7c740f',
}


def install_node(cache: Path) -> Path:
    architecture = {'x86_64': 'x64', 'aarch64': 'arm64'}.get(platform.machine())
    if platform.system() != 'Linux' or architecture is None:
        raise RuntimeError('Gradio 自动安装 Node 仅支持 Linux x64/arm64；其他环境请安装 Node 22')
    name = f'node-v{NODE_VERSION}-linux-{architecture}'
    target = cache / name
    if (target / 'bin/node').is_file():
        return target / 'bin'
    cache.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=cache) as temporary:
        archive = Path(temporary) / 'node.tar.xz'
        digest = hashlib.sha256()
        with requests.get(f'https://nodejs.org/dist/v{NODE_VERSION}/{name}.tar.xz',
                          stream=True, timeout=(15, 180)) as response:
            response.raise_for_status()
            with archive.open('wb') as stream:
                for chunk in response.iter_content(1024 * 1024):
                    stream.write(chunk)
                    digest.update(chunk)
        if digest.hexdigest() != NODE_CHECKSUMS[architecture]:
            raise RuntimeError('Node 安装包校验失败，已取消安装')
        # Extract only the pinned, checksum-verified official distribution.
        subprocess.run(['tar', '-xJf', str(archive), '-C', temporary], check=True)
        (Path(temporary) / name).rename(target)
    return target / 'bin'


def prepare_motion_runtime(root: Path = ROOT) -> None:
    for relative in ('frontend/local/motion/studio.js', 'frontend/local/remotion/index.html'):
        if not (root / relative).is_file():
            raise RuntimeError(f'缺少已构建的动效资源 {relative}；请通过部署 CI 同步')
    node = shutil.which('node')
    major = 0
    if node:
        version = subprocess.check_output([node, '--version'], text=True).strip()
        major = int(version.lstrip('v').split('.')[0])
    if major < 22 or not shutil.which('npm'):
        node_bin = install_node(Path.home() / '.cache/m2v-node')
        os.environ['PATH'] = str(node_bin) + os.pathsep + os.environ.get('PATH', '')
    browser = os.environ.get('CHROME_PATH') or shutil.which('chromium')
    if not browser or not Path(browser).is_file():
        raise RuntimeError('缺少 Chromium；请检查 Space 的 packages.txt 安装日志')
    os.environ['CHROME_PATH'] = browser
    if not shutil.which('ffmpeg'):
        raise RuntimeError('缺少 FFmpeg；请检查 Space 的 packages.txt 安装日志')
    motion = root / 'frontend/motion'
    signature = hashlib.sha256((motion / 'package-lock.json').read_bytes()).hexdigest()
    stamp = motion / 'node_modules/.m2v-runtime-lock'
    if not stamp.exists() or stamp.read_text() != signature:
        print('正在准备 Motion Studio 渲染依赖…', flush=True)
        subprocess.run(['npm', 'ci', '--omit=dev', '--no-audit', '--no-fund'], cwd=motion, check=True)
        stamp.write_text(signature)
    subprocess.run(['node', '--input-type=module', '-e', 'import "@remotion/renderer";'],
                   cwd=motion, check=True)
    print('Motion Studio 渲染环境就绪（Gradio 入口保持不变）', flush=True)
    warmup_ai_models()


def warmup_ai_models() -> None:
    """在后台异步预缓存 Whisper 基础模型，杜绝在借调 ZeroGPU 期间耗用网络下载时间。"""
    import threading

    def _preload():
        try:
            import stable_whisper

            print('🚀 [预热] 正在预缓存 stable-ts Whisper base 模型…', flush=True)
            stable_whisper.load_model('base', device='cpu')
            print('✅ [预热] stable-ts Whisper base 模型预热就绪！', flush=True)
        except Exception as e:
            print(f'⚠️ [预热] Whisper 模型预热跳过: {e}', flush=True)

    threading.Thread(target=_preload, daemon=True).start()
