"""CI change detection must not skip render changes or require a browser itself."""
import subprocess

import pytest

from scripts.ci_render_scope import needs_render, render_scope


@pytest.mark.parametrize('path', [
    'frontend/motion/src/webcodecs-exporter.ts', 'frontend/motion/package-lock.json',
    'src/motion_api.py', 'src/subtitle.py', 'tests/test_motion_studio_api.py',
    'packages.txt', 'requirements.txt', 'assets/fonts/song.ttf',
])
def test_render_changes_require_smoke_test(path):
    assert needs_render([path])


def test_ordinary_changes_do_not_require_real_rendering():
    assert not needs_render(['docs/credits.md', 'src/settings.py', 'src/payments.py',
                             '.github/workflows/ci.yml', 'frontend/dashboard.css'])


@pytest.mark.parametrize('value,expected', [('true', True), (True, True), ('false', False), (False, False)])
def test_manual_render_choice(value, expected):
    assert render_scope('workflow_dispatch', {'inputs': {'run_render_tests': value}}) is expected


def test_all_commits_in_push_and_pr_are_checked():
    calls = []
    def diff(base, head):
        calls.append((base, head))
        return ['src/subtitle.py']
    assert render_scope('push', {'before': 'base', 'after': 'head'}, diff)
    assert render_scope('pull_request', {'pull_request': {'base': {'sha': 'pr-base'},
                                                       'head': {'sha': 'pr-head'}}}, diff)
    assert calls == [('base', 'head'), ('pr-base', 'pr-head')]


def test_missing_history_defaults_to_running_render_tests():
    assert render_scope('push', {'before': '0' * 40, 'after': 'head'})
    def unavailable(*args):
        raise subprocess.CalledProcessError(128, 'git diff')
    assert render_scope('push', {'before': 'base', 'after': 'head'}, unavailable)
