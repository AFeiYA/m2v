from pathlib import Path

import pytest

from src import hf_motion_runtime as runtime


def assets(tmp_path):
    for relative in ('frontend/local/motion/studio.js', 'frontend/local/remotion/index.html',
                     'frontend/motion/package-lock.json'):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{}')
    return tmp_path


def test_missing_deployment_assets_fail_before_install(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime, 'install_node', lambda _: pytest.fail('must not install'))
    with pytest.raises(RuntimeError, match='部署 CI'):
        runtime.prepare_motion_runtime(tmp_path)


def test_preparation_installs_once_and_refreshes_changed_lock(tmp_path, monkeypatch):
    root = assets(tmp_path)
    browser = tmp_path / 'chromium'
    browser.touch()
    monkeypatch.setenv('CHROME_PATH', str(browser))
    monkeypatch.setattr(runtime.shutil, 'which', lambda name: '/usr/bin/' + name)
    monkeypatch.setattr(runtime.subprocess, 'check_output', lambda *a, **kw: 'v22.23.3')
    commands = []
    def run(command, **kwargs):
        commands.append(command)
        if command[0] == 'npm':
            (root / 'frontend/motion/node_modules').mkdir(exist_ok=True)
    monkeypatch.setattr(runtime.subprocess, 'run', run)
    runtime.prepare_motion_runtime(root)
    runtime.prepare_motion_runtime(root)
    assert sum(command[0] == 'npm' for command in commands) == 1
    (root / 'frontend/motion/package-lock.json').write_text('{"changed": true}')
    runtime.prepare_motion_runtime(root)
    assert sum(command[0] == 'npm' for command in commands) == 2


def test_older_node_is_replaced_in_path(tmp_path, monkeypatch):
    root = assets(tmp_path)
    browser = tmp_path / 'chromium'
    browser.touch()
    monkeypatch.setenv('CHROME_PATH', str(browser))
    monkeypatch.setenv('PATH', '/usr/bin')
    monkeypatch.setattr(runtime.shutil, 'which', lambda name: '/usr/bin/' + name)
    monkeypatch.setattr(runtime.subprocess, 'check_output', lambda *a, **kw: 'v18.0.0')
    monkeypatch.setattr(runtime, 'install_node', lambda cache: Path('/cache/node/bin'))
    def run(command, **kwargs):
        if command[0] == 'npm':
            (root / 'frontend/motion/node_modules').mkdir(exist_ok=True)
    monkeypatch.setattr(runtime.subprocess, 'run', run)
    runtime.prepare_motion_runtime(root)
    assert runtime.os.environ['PATH'].startswith('/cache/node/bin:')


def test_failed_download_checksum_never_extracts(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime.platform, 'system', lambda: 'Linux')
    monkeypatch.setattr(runtime.platform, 'machine', lambda: 'x86_64')
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def raise_for_status(self): pass
        def iter_content(self, size): yield b'incorrect archive'
    monkeypatch.setattr(runtime.requests, 'get', lambda *a, **kw: Response())
    monkeypatch.setattr(runtime.subprocess, 'run', lambda *a, **kw: pytest.fail('must not extract'))
    with pytest.raises(RuntimeError, match='校验失败'):
        runtime.install_node(tmp_path)
    assert not list(tmp_path.iterdir())
