"""Running a JavaScript harness under Node, for the tests that need the real files."""

import json
import os
import shutil
import subprocess
import unittest
from pathlib import Path

from django.conf import settings

HARNESS_DIR = Path(settings.BASE_DIR) / "core" / "tests" / "js"


def node_available():
    return shutil.which("node") is not None


def require_node():
    """Skip the test where Node is not installed - but not in CI.

    These tests run the real JavaScript files, and are the only check that
    the client and the server agree. On a laptop without Node they skip. In
    CI a skip would be a pass nobody saw: the jobs install Node
    (.github/workflows/ci.yml), and this fails if it has gone missing.
    """
    if node_available():
        return
    if os.environ.get("CI", "").lower() in ("true", "1"):
        raise AssertionError("Node is not installed, and CI must run these tests")
    raise unittest.SkipTest("Node is not installed")


def run_node(harness, *args):
    """Run ``core/tests/js/<harness>`` and parse the JSON it prints."""
    result = subprocess.run(
        ["node", str(HARNESS_DIR / harness), *map(str, args)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode:
        raise AssertionError(f"{harness} failed:\n{result.stderr}")
    return json.loads(result.stdout)
