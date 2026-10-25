#!/bin/bash
# Provision a git worktree so it can serve pages and run tests immediately.
#
# A worktree needs four things this repo does not track: the 243 MB venv, the
# 351 MB node_modules, the 100 MB SQLite database with its data, and the
# untracked .env / Claude settings files. The first two are shared with the
# main checkout, the rest are per-worktree copies.
#
# Idempotent, and a no-op in the main checkout, so it is safe to call from a
# worktree manager's setup hook or a SessionStart hook on every session.
#
#   scripts/setup_worktree.sh               provision the current worktree
#   scripts/setup_worktree.sh --no-migrate  skip applying this branch's migrations
#   scripts/setup_worktree.sh --quiet       print only what was actually done
#   scripts/setup_worktree.sh --print-port  the dev-server port for this worktree

set -e

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

# Dev-server port, derived from the path so a worktree keeps the same one
# across restarts, and nudged up while something else is already listening.
worktree_port() {
    local port=$((8001 + $(printf '%s' "$WORKTREE" | cksum | cut -d' ' -f1) % 99))

    while lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; do
        port=$((port + 1))
    done

    echo "$port"
}

MIGRATE=1
QUIET=0

while [ $# -gt 0 ]; do
    case "$1" in
        --print-port)
            if [ "$WORKTREE" = "$ROOT" ]; then echo 8000; else worktree_port; fi
            exit 0
            ;;
        --no-migrate) MIGRATE=0 ;;
        # For a SessionStart hook, whose output is read by every session:
        # say nothing unless something was actually provisioned.
        --quiet) QUIET=1 ;;
        *)
            echo "usage: $0 [--no-migrate] [--quiet] | --print-port" >&2
            exit 2
            ;;
    esac
    shift
done

say() {
    if [ "$QUIET" = 0 ]; then
        echo "$1"
    fi
}

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
fi

# Use the venv's interpreter, not bare python3: the venv is on Homebrew's
# python@3.11 with the locked packages, matching production, while the
# framework python3 is 3.14.
if [ "$MIGRATE" = 1 ] && [ -f db.sqlite3 ]; then
    if venv/bin/python manage.py migrate --noinput >/dev/null; then
        echo "  migrated db.sqlite3 onto this branch"
    else
        echo "  WARNING: migrate failed - run it yourself to see why" >&2
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
  PY="\$(brew --prefix python@3.11)/bin/python3.11"; test -x "\$PY" \
    && rm venv && "\$PY" -m venv venv && venv/bin/python -m pip install -r requirements.txt -r requirements-dev.txt
EOF
