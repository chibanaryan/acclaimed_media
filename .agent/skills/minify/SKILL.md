---
name: minify
description: Minify JavaScript files and regenerate bundles. Use when asked to minify JS, update bundles, or after editing JavaScript source files.
---

# JavaScript Minification

Minify JavaScript source files and regenerate bundles for production.

## Command

```bash
./scripts/minify_js.sh
```

## What It Does

1. **Minifies source files**: every `.js` file in `games/static/games/js/`,
   `books/static/books/js/`, `music/static/music/js/` and
   `core/static/core/js/` whose `.min.js` is missing or older than the source

2. **Regenerates the three bundles**, in dependency order:

   | Bundle | Members |
   |---|---|
   | `games/static/games/js/client-side-filtering.bundle.min.js` | `core/base-renderer`, `game-cache`, `client-filter`, `game-list-renderer`, `client-filtering` |
   | `books/static/books/js/book-client-side-filtering.bundle.min.js` | `core/base-renderer`, `book-cache`, `book-client-filter`, `book-list-renderer`, `book-client-filtering` |
   | `music/static/music/js/music-client-side-filtering.bundle.min.js` | `core/base-renderer`, `album-filter`, `album-list-renderer`, `album-client-filtering` |

3. **Stages files for git**: Automatically runs `git add` on updated files

## Rules that have bitten before

- **`core/base-renderer.min.js` must come first** in any bundle whose renderer
  extends `BaseMediaListRenderer`. Omit it and the bundle throws a
  `ReferenceError` as it loads, so nothing declared after that point registers
  either - the books bundle shipped that way and its whole client layer was
  dead.
- **The bundle filename in the template must match the one the script writes.**
  Under production's manifest static storage a `{% static %}` name that is not
  in the manifest raises while rendering rather than 404ing.
  `core/tests/test_static_assets.py` now asserts both of these.
- A bundle is skipped loudly if any member is missing, rather than written
  incomplete.

## File Locations

| Type | Location |
|------|----------|
| Source files | `{games,books,music}/static/*/js/*.js`, `core/static/core/js/*.js` |
| Minified files | the same paths with `.min.js` |
| Bundles | see the table above |
| Script | `scripts/minify_js.sh` |

## Note

The `/commit` skill already includes minification as step 3. Use `/minify` when you want to minify without committing.
