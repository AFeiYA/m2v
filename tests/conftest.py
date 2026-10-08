"""Shared CI policy for explicitly local integration tests."""
import os

import pytest


def pytest_collection_modifyitems(items):
    is_ci = any(os.getenv(name, "").lower() in {"true", "1"} for name in ("CI", "GITHUB_ACTIONS"))
    if not is_ci:
        return
    skip_local = pytest.mark.skip(reason="local_only: requires local assets/environment; not run in CI")
    for item in items:
        if item.get_closest_marker("local_only"):
            item.add_marker(skip_local)
