"""Running a JavaScript harness under Node, for the tests that need the real files."""

import json
import shutil
import subprocess
from pathlib import Path

from django.conf import settings

HARNESS_DIR = Path(settings.BASE_DIR) / "core" / "tests" / "js"


def node_available():
    return shutil.which("node") is not None


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
