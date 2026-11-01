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
#     acclaimedgames/test_input_files/: the games and album rankings
#
# The data is the rankings alone. Covers, genres, playtimes and accounts come
# from the metadata fetchers or `sync_from_prod`, neither of which runs here.
#
# scripts/setup_worktree.sh, the SessionStart hook, runs it whenever
# CLAUDE_CODE_REMOTE is true, before it puts the venv on PATH, so a cloud
# session needs no environment setup script. It provisions the checkout it is
# run in, not the one it lives in, as setup_worktree.sh does.
#
# Idempotent, and silent when there is nothing to do, because the hook runs on
# every start, resume, /clear and /compact: a venv that already has Django is
# kept, and each section is imported only while it is empty, so a re-run after
# a failure picks up where it stopped. About 2 s once provisioned.

set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

PY_VERSION="$(cat .python-version)"

if ! command -v uv >/dev/null 2>&1; then
    export PATH="$HOME/.local/bin:$PATH"
fi
if ! command -v uv >/dev/null 2>&1; then
    echo "Installing uv"
    python3 -m pip install --quiet --user uv
fi

if ! venv/bin/python -c 'import django' >/dev/null 2>&1; then
    echo "Building venv on Python $PY_VERSION"
    uv python install "$PY_VERSION"
    rm -rf venv
    uv venv --quiet --python "$PY_VERSION" venv
    uv pip install --quiet --python venv/bin/python \
        -r requirements.txt -r requirements-dev.txt
fi

export DEBUG=True

venv/bin/python manage.py migrate --noinput --skip-checks >/dev/null

venv/bin/python manage.py shell -v 0 <<'EOF'
from io import StringIO
from pathlib import Path

from django.core.management import call_command

from games.models import Game
from games.services.import_handler import import_batch
from music.models import Album

release = Path("acclaimedgames/test_input_files")

imported = False

if not Game.objects.exists():
    print("Importing the games release")
    imported = True
    files = {
        "platforms_file": "PlatformDB.txt",
        "lists_file": "SourceLists.txt",
        "games_file": "Top1400.txt",
        "memberships_file": "GamePositions.txt",
    }
    handles = {key: open(release / name, "rb") for key, name in files.items()}
    try:
        ok, message = import_batch(handles)
    finally:
        for handle in handles.values():
            handle.close()
    if not ok:
        raise SystemExit(f"Games import failed: {message}")

if not Album.objects.exists():
    print("Importing the music release")
    imported = True
    call_command("import_music_data", stdout=StringIO())

if imported:
    print(f"Ready: {Game.objects.count()} games, {Album.objects.count()} albums")
EOF
