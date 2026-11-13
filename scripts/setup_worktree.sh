#!/bin/bash
# Provision a git worktree so it can serve pages and run tests immediately.
#
# A worktree needs four things this repo does not track: the 243 MB venv, the
# 351 MB node_modules, the 100 MB SQLite database with its data, and the
# untracked .env / Claude settings files. The first two are shared with the
# main checkout, the rest are per-worktree copies.
#
# Idempotent, and a no-op in the main checkout, so it is safe to call from a
# worktree manager's setup hook or a SessionStart hook on every session. The
# exception is a Claude Code cloud session, whose main checkout starts with
# nothing to share: there scripts/setup_cloud.sh provisions it first.
#
#   scripts/setup_worktree.sh               provision the current worktree
#   scripts/setup_worktree.sh --no-migrate  skip applying this branch's migrations
#   scripts/setup_worktree.sh --migrate-new migrate a cloned database once, as
#                                           Conductor does at creation (retried
#                                           until it succeeds)
#   scripts/setup_worktree.sh --quiet       print only what was actually done
#   scripts/setup_worktree.sh --hook-input  provision the "cwd" a Claude Code hook
#                                           passes as JSON on stdin
#   scripts/setup_worktree.sh --print-port  the dev-server port for this worktree

# -u as well as -e, as the other scripts here have: a variable Claude Code
# sets and Conductor does not is read as "${NAME:-}". Under -e alone a
# misspelt name was an empty string, silently. No pipefail: this file has
# no pipeline whose first command's failure should end it.
set -eu

# Whether runserver could not bind a port, asked the way runserver will: by
# binding it. lsof was asked before, and shows only this user's sockets, so a
# system service's was invisible: macOS's launchd holds 8021 for ftp-proxy,
# a worktree whose path hashed to 8021 was told it was free, and runserver
# answered "That port is already in use". Parsing netstat instead would need
# net-tools on Linux, which cloud images lack. python3 is here already (the
# hook input is read with it); without it, lsof is the best there is.
port_in_use() {
    if command -v python3 >/dev/null 2>&1; then
        ! python3 -c '
import socket, sys
probe = socket.socket()
probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
probe.bind(("127.0.0.1", int(sys.argv[1])))
' "$1" >/dev/null 2>&1
        return
    fi
    lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1
}

# Dev-server port, derived from the path so a worktree keeps the same one
# across restarts, and nudged up while something else is already listening.
worktree_port() {
    local port=$((8001 + $(printf '%s' "$WORKTREE" | cksum | cut -d' ' -f1) % 99))

    while port_in_use "$port"; do
        port=$((port + 1))
    done

    echo "$port"
}

MIGRATE=1
QUIET=0
HOOK_INPUT=0
PRINT_PORT=0

while [ $# -gt 0 ]; do
    case "$1" in
        --print-port) PRINT_PORT=1 ;;
        --no-migrate) MIGRATE=0 ;;
        # A SessionStart hook runs on every start and resume. Migrating once,
        # when the worktree gets its database, is what Conductor's setup does;
        # every session after that would pay Django's boot for nothing.
        --migrate-new) MIGRATE=new ;;
        # Claude Code runs hooks in the main checkout's root, with
        # $CLAUDE_PROJECT_DIR pointing there too, even for a session in a
        # worktree (the desktop app's Worktree toggle, `claude --worktree`).
        # Only the hook's JSON input names the directory the session is in.
        --hook-input) HOOK_INPUT=1 ;;
        # For a SessionStart hook, whose output is read by every session:
        # say nothing unless something was actually provisioned.
        --quiet) QUIET=1 ;;
        *)
            echo "usage: $0 [--no-migrate | --migrate-new] [--quiet] [--hook-input] | --print-port" >&2
            exit 2
            ;;
    esac
    shift
done

# A checkout's shared .git directory, which every worktree of one repository
# has in common; empty outside a repository.
common_dir() {
    git -C "$1" rev-parse --path-format=absolute --git-common-dir 2>/dev/null || true
}

if [ "$HOOK_INPUT" = 1 ]; then
    HOOK_CWD="$(python3 -c \
        'import json, sys; print(json.load(sys.stdin).get("cwd") or "")' 2>/dev/null || true)"
    # The session's cwd is wherever Claude last cd'd: /tmp, or another
    # repository, by the time a /compact or /clear fires the hook. Only a
    # directory in this repository names a worktree to provision; otherwise
    # provision the project, as the hook did before it read its input.
    HOME_REPO="$(common_dir "${CLAUDE_PROJECT_DIR:-.}")"
    if [ -n "$HOOK_CWD" ] && [ -d "$HOOK_CWD" ] && [ -n "$HOME_REPO" ] \
        && [ "$(common_dir "$HOOK_CWD")" = "$HOME_REPO" ]; then
        cd "$HOOK_CWD"
    elif [ -n "${CLAUDE_PROJECT_DIR:-}" ]; then
        cd "$CLAUDE_PROJECT_DIR"
    fi
fi

# The worktree to provision is the one we are standing in, not the one this
# script lives in: a worktree manager's setup hook runs before the new branch
# necessarily has this file, so it has to be able to call the main checkout's
# copy from inside the new worktree.
WORKTREE="$(git rev-parse --show-toplevel)"
cd "$WORKTREE"

# The main checkout owns the shared venv, node_modules and reference database.
# --git-common-dir points into it from a worktree, and at .git from the
# checkout itself - which is also how we detect there is nothing to do.
ROOT="$(cd "$(git rev-parse --git-common-dir)/.." && pwd)"

if [ "$PRINT_PORT" = 1 ]; then
    if [ "$WORKTREE" = "$ROOT" ]; then echo 8000; else worktree_port; fi
    exit 0
fi

say() {
    if [ "$QUIET" = 0 ]; then
        echo "$1"
    fi
}

# Put the venv first on PATH for the rest of a Claude Code session, as an
# activated venv would be: Claude Code sources $CLAUDE_ENV_FILE before each
# Bash command, so `python`, `pytest` and `pre-commit` are the venv's in the
# main checkout and every worktree alike. Done at the end, once the link
# exists, but registered here so the main checkout's early exit runs it too.
activate_venv() {
    if [ -n "${CLAUDE_ENV_FILE:-}" ] && [ -x "$WORKTREE/venv/bin/python" ]; then
        # Guarded, because every start, resume, /clear and /compact runs the
        # hook again and the file runs before every Bash command.
        local bin
        bin="$(printf '%q' "$WORKTREE/venv/bin")"
        {
            printf 'export VIRTUAL_ENV=%q\n' "$WORKTREE/venv"
            printf 'case ":$PATH:" in *:%s:*) ;; *) export PATH=%s:"$PATH" ;; esac\n' \
                "$bin" "$bin"
        } >>"$CLAUDE_ENV_FILE"
    fi
}
trap activate_venv EXIT

# A Claude Code cloud session is a fresh Linux clone, so its main checkout has
# no venv or database for a worktree to link or copy. Build them there first:
# before the main-checkout exit below, before a worktree links to them, and
# before activate_venv looks for the venv.
#
# A failure warns rather than aborting, so the rest still runs, and the
# warning goes to stdout: a SessionStart hook's stdout reaches the session,
# while its stderr is not shown when it exits 0.
if [ "${CLAUDE_CODE_REMOTE:-}" = true ]; then
    if cloud_output="$(cd "$ROOT" && "$ROOT/scripts/setup_cloud.sh" 2>&1)"; then
        if [ -n "$cloud_output" ]; then
            echo "$cloud_output"
        fi
    else
        echo "WARNING: scripts/setup_cloud.sh failed, so the venv or the" \
            "database may be missing. Its last output:"
        echo "$cloud_output" | tail -n 20
    fi
fi

if [ "$WORKTREE" = "$ROOT" ]; then
    say "Main checkout - nothing to provision."
    exit 0
fi

say "Provisioning $WORKTREE"

# Shared with the main checkout: large, and identical on every branch.
link_shared() {
    local path="$1"

    if [ -e "$path" ] || [ -L "$path" ] || [ ! -e "$ROOT/$path" ]; then
        return
    fi

    mkdir -p "$(dirname "$path")"
    ln -s "$ROOT/$path" "$path"
    echo "  linked   $path"
}

# Copied: small, untracked, and a branch may want to change its own copy.
copy_untracked() {
    local path="$1"

    if [ -e "$path" ] || [ ! -e "$ROOT/$path" ]; then
        return
    fi

    mkdir -p "$(dirname "$path")"
    cp -R "$ROOT/$path" "$path"
    echo "  copied   $path"
}

link_shared venv
link_shared theme/static_src/node_modules

# The main checkout's venv lags a .python-version bump until it is rebuilt,
# and a worktree linked to it would quietly test a stack production has left.
# Compared on major.minor, as scripts/setup_cloud.sh does: a patch-pinned
# .python-version (3.14.6) would otherwise never match. The warning goes to
# stdout, like the cloud one above: on exit 0 a hook's stderr is not shown.
want_py="$(cut -d. -f1,2 .python-version 2>/dev/null || true)"
have_py="$(venv/bin/python -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || true)"
if [ -n "$want_py" ] && [ -n "$have_py" ] && [ "$want_py" != "$have_py" ]; then
    echo "  WARNING: venv is Python $have_py but .python-version says $want_py;" \
        "rebuild it (AGENTS.md \"Dependencies\")"
fi

copy_untracked .env
copy_untracked .env.development.local
copy_untracked .claude/settings.local.json
copy_untracked media

# APFS clones the database in milliseconds and shares its blocks until one
# side writes, so a worktree gets its own 100 MB copy for free - including the
# staff users the music section needs. -c is macOS-only; fall back elsewhere.
# The database is in journal_mode=delete, so there are no -wal/-shm siblings
# to carry across.
if [ ! -f db.sqlite3 ] && [ -f "$ROOT/db.sqlite3" ]; then
    cp -c "$ROOT/db.sqlite3" db.sqlite3 2>/dev/null || cp "$ROOT/db.sqlite3" db.sqlite3
    echo "  cloned   db.sqlite3"
    # Kept in the worktree's own git directory, out of the checkout, until a
    # migrate succeeds: --migrate-new retries a first migrate that failed, or
    # that had no venv to run with, rather than skipping it from then on.
    touch "$(git rev-parse --absolute-git-dir)/setup-migrate-pending"
fi

MIGRATE_PENDING="$(git rev-parse --absolute-git-dir)/setup-migrate-pending"
if [ "$MIGRATE" = new ] && [ ! -f "$MIGRATE_PENDING" ]; then
    MIGRATE=0
fi

# Use the venv's interpreter, not bare python3: the venv is on Homebrew's
# Python at .python-version's release, with the locked packages, matching
# production, while bare python3 can be any interpreter on PATH.
if [ "$MIGRATE" != 0 ] && [ -f db.sqlite3 ] && [ -x venv/bin/python ]; then
    if venv/bin/python manage.py migrate --noinput >/dev/null; then
        rm -f "$MIGRATE_PENDING"
        echo "  migrated db.sqlite3 onto this branch"
    else
        # To stdout, as above: this script exits 0 either way
        echo "  WARNING: migrate failed - run it yourself to see why"
    fi
fi

if [ "$QUIET" = 1 ]; then
    exit 0
fi

PORT="$(worktree_port)"

cat <<EOF

Ready. From $WORKTREE:
  serve  DEBUG=True venv/bin/python manage.py runserver $PORT   -> http://localhost:$PORT/
  test   DATABASE_URL=sqlite:///db.sqlite3 CACHE_URL=locmemcache:// CORS_ALLOWED_ORIGINS=http://localhost pytest

The venv is shared. If this branch changes requirements*.txt, give it its own:
  V=\$(cat .python-version); PY="\$(brew --prefix python@\$V)/bin/python\$V"; test -x "\$PY" \
    && rm venv && "\$PY" -m venv venv && venv/bin/python -m pip install -r requirements.txt -r requirements-dev.txt
EOF
