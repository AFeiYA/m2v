"""Run real rendering only for relevant changes or an explicit workflow dispatch."""
from __future__ import annotations

import fnmatch
import json
import os
from pathlib import Path
import subprocess


RENDER_PATHS = (
    'frontend/motion/**', 'frontend/local/motion*', 'frontend/local/remotion/**',
    'src/motion_api.py', 'src/motion_cloud.py', 'src/motion_director.py',
    'src/song_cover.py', 'src/song_identity.py', 'src/subtitle.py',
    'src/storyboard_renderer.py', 'src/hf_motion_runtime.py',
    'src/export_jobs.py', 'src/export_library.py',
    'tests/test_motion_studio_api.py', 'tests/test_hf_motion_runtime.py',
    'requirements.txt', 'pyproject.toml', 'packages.txt', 'Dockerfile',
    'fonts/**', 'assets/fonts/**',
)


def needs_render(paths):
    return any(fnmatch.fnmatchcase(path, pattern) for path in paths for pattern in RENDER_PATHS)


def render_scope(event_name, event, diff=None):
    if event_name == 'workflow_dispatch':
        return str(event.get('inputs', {}).get('run_render_tests', False)).lower() == 'true'
    if event_name == 'pull_request':
        request = event.get('pull_request', {})
        base, head = request.get('base', {}).get('sha'), request.get('head', {}).get('sha')
    elif event_name == 'push':
        base, head = event.get('before'), event.get('after')
    else:
        return True
    if not base or not head or set(base) == {'0'}:
        return True
    if diff is None:
        def diff(base, head):
            return subprocess.check_output(
                ['git', 'diff', '--name-only', '-z', base, head], text=True,
            ).split('\0')
    try:
        return needs_render(diff(base, head))
    except (OSError, subprocess.CalledProcessError):
        # Missing history must not accidentally skip a render regression.
        return True


def main():
    event = json.loads(Path(os.environ['GITHUB_EVENT_PATH']).read_text())
    enabled = render_scope(os.environ['GITHUB_EVENT_NAME'], event)
    with Path(os.environ['GITHUB_OUTPUT']).open('a') as output:
        output.write(f'run_render_tests={int(enabled)}\n')
    print('Real rendering: ' + ('enabled' if enabled else 'skipped; no render-related changes'))


if __name__ == '__main__':
    main()
