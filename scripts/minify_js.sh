#!/bin/bash
# Minify JavaScript sources and rebuild the client-side filtering bundles.
# Run during deploy/commit to keep the minified files and bundles current.
#
#   scripts/minify_js.sh          rewrite and stage whatever is out of date
#   scripts/minify_js.sh --check  change nothing; exit 1 naming what is stale
#
# Staleness is decided by content, not timestamps: every source is minified
# to a temporary file and compared with the committed .min.js. A checkout
# gives every file the same mtime, so the old `-nt` test reported a stale
# file as up to date in any fresh clone or worktree - including CI's.
#
# terser is pinned because the output is committed: an unpinned `npx terser`
# took whatever release was newest that day, so two people minifying the
# same source could commit different bytes. 5.51.2 reproduces every
# committed .min.js exactly; bump it deliberately and commit the rebuild.

set -e

TERSER="terser@5.51.2"
CHECK=0
if [ "${1:-}" = "--check" ]; then
    CHECK=1
fi

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

# Resolved once: npx costs about a second a call, and there are 25 sources.
TERSER_BIN="$(npx --yes -p "$TERSER" -c 'command -v terser')"

GAMES_JS_DIR="games/static/games/js"
BOOKS_JS_DIR="books/static/books/js"
MUSIC_JS_DIR="music/static/music/js"
CORE_JS_DIR="core/static/core/js"

CHANGED=0

# Put $2 in place at $1 if it differs, or in --check mode report that it does.
update_if_changed() {
    local target="$1"
    local candidate="$2"

    if [ -f "$target" ] && cmp -s "$candidate" "$target"; then
        return
    fi
    CHANGED=1
    if [ $CHECK -eq 1 ]; then
        echo "Stale: $target"
    else
        echo "Updating $(basename "$target")..."
        cp "$candidate" "$target"
        git add "$target"
    fi
}

# Minify every source in a directory whose .min.js is missing or stale.
#
# The loop is driven by the *sources*, not by the existing .min.js files: it
# used to be the other way round, which meant a newly added source was never
# minified until someone hand-created a .min.js beside it.
minify_dir() {
    local dir="$1"

    if [ ! -d "$dir" ]; then
        return
    fi

    for src in "$dir"/*.js; do
        [ -e "$src" ] || continue

        # Skip the minified files and bundles themselves.
        case "$src" in
            *.min.js) continue ;;
        esac

        local min="${src%.js}.min.js"
        # Mirrors the repo path: two directories hold a
        # filter-subcomponents.min.js.
        local out="$TMP_DIR/$min"
        mkdir -p "$(dirname "$out")"

        "$TERSER_BIN" "$src" -o "$out" -c -m
        update_if_changed "$min" "$out"
    done
}

# Concatenate minified files into a bundle when the result differs from it.
#
# Order matters: base-renderer.min.js must come before any renderer that
# extends BaseMediaListRenderer, or the bundle throws a ReferenceError as it
# loads and nothing declared after that point registers. A bundle missing one
# of its members is worse than no bundle at all - the failure is invisible
# until the browser runs it - so an incomplete set is skipped loudly.
build_bundle() {
    local bundle="$1"
    shift
    local sources=("$@")
    local src

    for src in "${sources[@]}"; do
        if [ ! -f "$src" ]; then
            echo "Skipping $(basename "$bundle"): missing $src"
            return
        fi
    done

    # In --check mode the members were left alone, so build from what each
    # member would be: the fresh minification if it differs from the file.
    local parts=()
    for src in "${sources[@]}"; do
        if [ $CHECK -eq 1 ] && [ -f "$TMP_DIR/$src" ]; then
            parts+=("$TMP_DIR/$src")
        else
            parts+=("$src")
        fi
    done

    local out="$TMP_DIR/$bundle"
    mkdir -p "$(dirname "$out")"
    cat "${parts[@]}" > "$out"
    update_if_changed "$bundle" "$out"
}

minify_dir "$GAMES_JS_DIR"
minify_dir "$BOOKS_JS_DIR"
minify_dir "$MUSIC_JS_DIR"
minify_dir "$CORE_JS_DIR"

build_bundle "$GAMES_JS_DIR/client-side-filtering.bundle.min.js" \
    "$CORE_JS_DIR/base-renderer.min.js" \
    "$GAMES_JS_DIR/game-cache.min.js" \
    "$GAMES_JS_DIR/client-filter.min.js" \
    "$GAMES_JS_DIR/game-list-renderer.min.js" \
    "$GAMES_JS_DIR/client-filtering.min.js"

build_bundle "$BOOKS_JS_DIR/book-client-side-filtering.bundle.min.js" \
    "$CORE_JS_DIR/base-renderer.min.js" \
    "$BOOKS_JS_DIR/book-cache.min.js" \
    "$BOOKS_JS_DIR/book-client-filter.min.js" \
    "$BOOKS_JS_DIR/book-list-renderer.min.js" \
    "$BOOKS_JS_DIR/book-client-filtering.min.js"

build_bundle "$MUSIC_JS_DIR/music-client-side-filtering.bundle.min.js" \
    "$CORE_JS_DIR/base-renderer.min.js" \
    "$MUSIC_JS_DIR/album-filter.min.js" \
    "$MUSIC_JS_DIR/album-list-renderer.min.js" \
    "$MUSIC_JS_DIR/album-client-filtering.min.js"

if [ $CHANGED -eq 0 ]; then
    echo "All minified JS files are up to date."
elif [ $CHECK -eq 1 ]; then
    echo "Run scripts/minify_js.sh and commit the result."
    exit 1
else
    echo "Minified JS files updated and staged."
fi
