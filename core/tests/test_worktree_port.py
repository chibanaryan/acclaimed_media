"""`scripts/setup_worktree.sh --print-port`: the port Conductor's Run uses.

A worktree's port is derived from its path and nudged up while it is taken.
"Taken" was asked of `lsof`, which shows only the user's own sockets.
macOS's launchd holds 8021 (ftp-proxy), so a worktree whose path hashed to
8021 was given it, and `runserver` failed with "That port is already in
use". The script now tries to bind the port, as runserver will.

The main checkout always answers 8000, and CI's clone is one, so the two
functions are run here as the script defines them, with a path of the
test's own, rather than through `--print-port`.
"""

import socket
import subprocess
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

SCRIPT = Path(settings.BASE_DIR) / "scripts" / "setup_worktree.sh"


def port_functions():
    """`port_in_use` and `worktree_port`, as the script defines them."""
    source = SCRIPT.read_text()
    start = source.index("port_in_use() {")
    end = source.index("\n}\n", source.index("worktree_port() {")) + len("\n}\n")
    return source[start:end]


def worktree_port(name):
    """The port for a worktree at a path of the test's own.

    Each test names its own path: they hash to ports well apart (8066,
    8088, 8046), so one test holding its port does not move another's
    when the suite runs in parallel.
    """
    path = f"/tmp/acclaimed-media-test-{name}"
    script = f'WORKTREE="{path}"\n{port_functions()}\nworktree_port\n'
    result = subprocess.run(
        ["bash", "-c", script], capture_output=True, text=True, timeout=60
    )
    assert result.returncode == 0, result.stderr
    return int(result.stdout.strip())


class WorktreePortTests(SimpleTestCase):
    def test_the_port_is_one_that_can_be_bound(self):
        port = worktree_port("bound")
        self.assertGreater(port, 8000)
        with socket.socket() as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            probe.bind(("127.0.0.1", port))

    def test_a_port_something_holds_is_passed_over(self):
        first = worktree_port("held")
        with socket.socket() as holder:
            holder.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                holder.bind(("127.0.0.1", first))
            except OSError:  # pragma: no cover - taken between the two lines
                self.skipTest("the port was taken before the test could hold it")
            holder.listen(1)
            self.assertGreater(worktree_port("held"), first)

    def test_a_path_keeps_its_port_while_nothing_takes_it(self):
        self.assertEqual(worktree_port("steady"), worktree_port("steady"))

    def test_the_script_prints_a_port(self):
        """8000 in the main checkout, which CI's clone is; a worktree's own
        elsewhere."""
        result = subprocess.run(
            ["bash", str(SCRIPT), "--print-port"],
            capture_output=True,
            text=True,
            cwd=settings.BASE_DIR,
            timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertGreaterEqual(int(result.stdout.strip()), 8000)
