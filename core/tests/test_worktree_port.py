"""`scripts/setup_worktree.sh --print-port`: the port Conductor's Run uses.

It asked `lsof` whether a port was taken, which shows only the user's own
sockets. macOS's launchd holds 8021 (ftp-proxy), so a worktree whose path
hashed to 8021 was given it, and `runserver` failed with "That port is
already in use". The script now tries to bind the port, as runserver will.
"""

import socket
import subprocess
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

SCRIPT = Path(settings.BASE_DIR) / "scripts" / "setup_worktree.sh"


def printed_port():
    result = subprocess.run(
        ["bash", str(SCRIPT), "--print-port"],
        capture_output=True,
        text=True,
        cwd=settings.BASE_DIR,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    return int(result.stdout.strip())


class PrintPortTests(SimpleTestCase):
    def test_the_port_is_one_that_can_be_bound(self):
        port = printed_port()
        with socket.socket() as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            probe.bind(("127.0.0.1", port))

    def test_a_port_something_holds_is_passed_over(self):
        first = printed_port()
        with socket.socket() as holder:
            holder.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                holder.bind(("127.0.0.1", first))
            except OSError:  # pragma: no cover - taken between the two lines
                self.skipTest("the port was taken before the test could hold it")
            holder.listen(1)
            self.assertGreater(printed_port(), first)

    def test_the_port_is_the_same_while_nothing_takes_it(self):
        self.assertEqual(printed_port(), printed_port())
