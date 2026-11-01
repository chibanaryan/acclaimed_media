#!/bin/bash
# Provision a Claude Code cloud session so it can serve pages and run tests.
#
# A cloud session starts from a fresh clone on Linux, with none of what a
# local checkout keeps untracked, and it cannot reach the Mac that has them.
# The Mac's venv would not run here anyway (macOS wheels, an interpreter
# linked into Homebrew), so this builds its own:
#
#   - venv/ on .python-version's Python, from both locks, with uv
#   - db.sqlite3, migrated, holding the release files checked into
#     acclaimedgames/test_input_files/ (import_games_data, import_music_data)
#
# The data is the rankings alone. Covers, genres, playtimes and accounts come
# from the metadata fetchers or `sync_from_prod`, neither of which runs here.
#
# scripts/setup_worktree.sh, the SessionStart hook, runs it in the main
# checkout whenever CLAUDE_CODE_REMOTE is true, before it links a worktree to
# that venv and copies it that database, and before it puts the venv on PATH.
# It provisions the checkout it is run in, not the one it lives in.
#
# The hook runs on every start, resume, /clear and /compact, so once
# provisioned this boots nothing and prints nothing:
#   - the venv is rebuilt when its Python is not .python-version's, and
#     synced to the locks when either lock or .python-version changes (a
#     stamp in the venv records the last sync);
#   - the database is set up once, recorded by a marker in the git directory.
#     A branch that adds a migration later needs `manage.py migrate`, as a
#     worktree does.

set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

PY_VERSION="$(cat .python-version)"
# The venv is compared on major.minor, which is all a patch-pinned
# .python-version (3.14.6) can be checked against without a rebuild per start.
PY_MINOR="$(echo "$PY_VERSION" | cut -d. -f1,2)"
STAMP=venv/.setup-cloud-stamp
WANT_STAMP="$(cat .python-version requirements.txt requirements-dev.txt | sha256sum | cut -d' ' -f1)"
DONE="$(git rev-parse --absolute-git-dir)/setup-cloud-done"

ensure_uv() {
    if ! command -v uv >/dev/null 2>&1; then
        export PATH="$HOME/.local/bin:$PATH"
    fi
    if ! command -v uv >/dev/null 2>&1; then
        echo "Installing uv"
        # A distro's Python refuses --user installs (PEP 668) unless told to.
        python3 -m pip install --quiet --user uv 2>/dev/null \
            || python3 -m pip install --quiet --user --break-system-packages uv
    fi
}

venv_python="$(venv/bin/python -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || true)"

if [ "$venv_python" != "$PY_MINOR" ]; then
    echo "Building venv on Python $PY_VERSION"
    ensure_uv
    uv python install --quiet "$PY_VERSION"
    rm -rf venv
    uv venv --quiet --python "$PY_VERSION" venv
fi

if [ "$(cat "$STAMP" 2>/dev/null || true)" != "$WANT_STAMP" ]; then
    echo "Syncing the venv to requirements.txt and requirements-dev.txt"
    ensure_uv
    # sync, not install: a package the locks dropped is removed, as a fresh
    # Heroku build would not have it either.
    uv pip sync --quiet --python venv/bin/python \
        requirements.txt requirements-dev.txt
    echo "$WANT_STAMP" >"$STAMP"
fi

if [ -f db.sqlite3 ] && [ -f "$DONE" ]; then
    exit 0
fi
# Cleared first: a failed run leaves a migrated db.sqlite3 behind, which with
# an old marker would read as finished and never be retried.
rm -f "$DONE"

# One Django boot for all three steps. DEBUG gives settings its development
# SECRET_KEY, as runserver's DEBUG=True does.
DEBUG=True venv/bin/python manage.py shell -v 0 <<'EOF'
from contextlib import redirect_stdout
from io import StringIO

from django.core.management import call_command

from games.models import Game
from music.models import Album

# Data migrations print() their progress past `stdout=`, so catch that too.
with redirect_stdout(StringIO()):
    call_command("migrate", interactive=False, skip_checks=True, stdout=StringIO())

# Each section is imported only while it is empty, so a re-run after a failure
# picks up where it stopped.
if not Game.objects.exists():
    print("Importing the games release")
    call_command("import_games_data", stdout=StringIO())
if not Album.objects.exists():
    print("Importing the music release")
    call_command("import_music_data", stdout=StringIO())

print(f"Database ready: {Game.objects.count()} games, {Album.objects.count()} albums")
EOF

touch "$DONE"
