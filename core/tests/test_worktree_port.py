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

import os
import socket
import subprocess
import tempfile
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


def between(start, end):
    """The script's source from ``start`` up to and including ``end``."""
    source = SCRIPT.read_text()
    at = source.index(start)
    return source[at : source.index(end, at) + len(end)]


def without_claude(**extra):
    """This environment as Conductor's setup runs the script: no CLAUDE_*."""
    env = {key: value for key, value in os.environ.items() if "CLAUDE" not in key}
    env.update(extra)
    return env


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


class UnsetVariablesTests(SimpleTestCase):
    """The script runs under `set -eu`, in sessions that set Claude Code's
    variables and in ones that do not (Conductor's setup, a terminal).

    Its parts are run here as the script defines them, not the script
    itself, which provisions the worktree it stands in. An unset variable
    read bare is "unbound variable" and exit 1 under `-u`, and the EXIT
    trap runs on every path out, so a slip there fails every run.
    """

    def run_bash(self, script, **kwargs):
        return subprocess.run(
            ["bash", "-c", "set -eu\n" + script],
            capture_output=True,
            text=True,
            timeout=60,
            env=without_claude(),
            **kwargs,
        )

    def test_the_script_is_strict_about_unset_variables(self):
        self.assertIn("\nset -eu\n", SCRIPT.read_text())

    def test_the_exit_trap_runs_with_no_env_file(self):
        """Outside Claude Code there is no $CLAUDE_ENV_FILE to write to."""
        trap = between("activate_venv() {", "\ntrap activate_venv EXIT\n")
        result = self.run_bash(f'WORKTREE="{settings.BASE_DIR}"\n{trap}\nexit 0\n')
        self.assertEqual((result.returncode, result.stderr), (0, ""))

    def test_the_exit_trap_writes_the_venv_when_there_is_one(self):
        """The other branch: the file Claude Code sources before each command."""
        trap = between("activate_venv() {", "\ntrap activate_venv EXIT\n")
        with tempfile.TemporaryDirectory() as scratch:
            fake = Path(scratch) / "tree"
            (fake / "venv" / "bin").mkdir(parents=True)
            python = fake / "venv" / "bin" / "python"
            python.write_text("#!/bin/sh\n")
            python.chmod(0o755)
            env_file = Path(scratch) / "env"
            result = subprocess.run(
                ["bash", "-c", f'set -eu\nWORKTREE="{fake}"\n{trap}\nexit 0\n'],
                capture_output=True,
                text=True,
                timeout=60,
                env=without_claude(CLAUDE_ENV_FILE=str(env_file)),
            )
            self.assertEqual((result.returncode, result.stderr), (0, ""))
            written = env_file.read_text()
        self.assertIn(f"export VIRTUAL_ENV={fake}/venv", written)
        self.assertIn(f"export PATH={fake}/venv/bin:", written)

    def test_the_hook_branch_runs_with_no_project_dir(self):
        """A hook whose input names no directory, in a session that set no
        $CLAUDE_PROJECT_DIR: it stays where it is."""
        functions = between("common_dir() {", "\n}\n")
        branch = between('if [ "$HOOK_INPUT" = 1 ]; then', "\nfi\n")
        result = self.run_bash(
            f"HOOK_INPUT=1\n{functions}\n{branch}\npwd\n",
            input="{}",
            cwd=settings.BASE_DIR,
        )
        self.assertEqual(result.stderr, "")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(
            Path(result.stdout.strip()).resolve(), Path(settings.BASE_DIR).resolve()
        )
