#!/bin/bash
# Minify JavaScript sources and rebuild the client-side filtering bundles.
# Run during deploy/commit to keep the minified files and bundles current.

set -e

GAMES_JS_DIR="games/static/games/js"
BOOKS_JS_DIR="books/static/books/js"
MUSIC_JS_DIR="music/static/music/js"
CORE_JS_DIR="core/static/core/js"

CHANGED=0

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

        if [ ! -f "$min" ] || [ "$src" -nt "$min" ]; then
            echo "Minifying $(basename "$src")..."
            npx terser "$src" -o "$min" -c -m
            git add "$min"
            CHANGED=1
        fi
    done
}

# Concatenate minified files into a bundle when any member is newer than it.
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

    local needs=0
    for src in "${sources[@]}"; do
        if [ ! -f "$bundle" ] || [ "$src" -nt "$bundle" ]; then
            needs=1
            break
        fi
    done

    if [ $needs -eq 1 ]; then
        echo "Creating $(basename "$bundle")..."
        cat "${sources[@]}" > "$bundle"
        git add "$bundle"
        CHANGED=1
    fi
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

if [ $CHANGED -eq 1 ]; then
    echo "Minified JS files updated and staged."
else
    echo "All minified JS files are up to date."
fi
