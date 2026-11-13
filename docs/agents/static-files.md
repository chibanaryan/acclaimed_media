<!-- Part of the agent documentation. AGENTS.md keeps each section's rules
     and points here for the reasoning, history and measurements behind
     them. Moved out of AGENTS.md, word for word, on 2026-11-12. -->

# Static Files

- Django collectstatic copies static files from apps to `staticfiles/`
- WhiteNoise serves static files in production
- Static files are located in:
  - `games/static/` - Game app static files (icons, fonts, images, JS)
  - `core/static/`, `music/static/` - Each app's own JS, and music's images
  - `theme/static/` - Tailwind CSS compiled output

### CSS Workflow (Tailwind CSS)

The site uses django-tailwind with Tailwind CSS v4 and DaisyUI v5 for styling.

**Development:**
```bash
# Start Tailwind CSS watcher (rebuilds CSS on file changes)
python manage.py tailwind start

# Run Django dev server (in separate terminal)
python manage.py runserver
```

**Production Build:**
```bash
# Build minified CSS for production
python manage.py tailwind build

# Collect static files
python manage.py collectstatic --noinput
```

**The build reads class names from every `.html`, `.py` and `.js` file**
(`@source "../../../**/*.{html,py,js}"` in `styles.css`), tests included. A
Tailwind class written anywhere in one, a comment in a test too, is a class
built: on 2026-11-12 a test's comment naming an opacity variant of
`text-primary` added a rule to the stylesheet, and CI's `css` job would have
failed on the difference. Rebuild after any change that names a class, and
do not spell out one the pages do not use.

**File Locations:**
- `theme/static_src/src/styles.css` - Main Tailwind CSS source file with custom components
- `theme/static/css/dist/styles.css` - Compiled CSS output (auto-generated)
- `games/static/games/css/mdi-subset.css` - Material Design Icons (self-hosted subset)
- `games/static/games/fonts/materialdesignicons-webfont.woff2` - Generated MDI subset font

**Adding Custom Styles:**
Edit `theme/static_src/src/styles.css` and use Tailwind's `@layer` directive:
```css
@layer components {
  .my-component {
    @apply flex items-center gap-2;
  }
}
```

**DaisyUI Components:**
Common components used: `btn`, `card`, `table`, `alert`, `badge`, `input`, `select`, `checkbox`, `dropdown`, `modal`, `link`

**Theme Configuration:**
Themes are defined in `theme/static_src/src/styles.css` using DaisyUI's `@plugin` directive:
```css
@plugin "daisyui" {
  themes: ["lofi", "forest"];
}
```
The theme switcher in the navigation allows users to change themes, with the selection persisted in localStorage.

### MDI Subset Workflow

Material Design Icons are shipped as a local WOFF2 subset to reduce transfer size.

**Rebuild command:**
```bash
./scripts/build_mdi_subset.sh
```

**Dependencies:**
- `pyftsubset` (from `fonttools`, in the dev lock since 2026-11-09)
- `brotli` (in the production lock)

Both come with the usual install:
```bash
pip install -r requirements.txt -r requirements-dev.txt
```

The script scans icon codepoints from `games/templates/base.html` and `games/static/games/css/mdi-subset.css`, then rewrites `games/static/games/fonts/materialdesignicons-webfont.woff2` in place.

`core/tests/test_icons_defined.py` fails on an `mdi-` class a template or
script uses that no mapping defines. Until 2026-11-10 fourteen rendered as
nothing (the signup button's, the email-status screens'), and nine more were
mapped to another icon's codepoint: the Platforms heading showed a calendar.
Take codepoints from the official CSS, as the `/icons` skill says.

### JavaScript Workflow

JavaScript files in each app's `static/<app>/js/` (`games`, `core`, `music`)
follow a specific workflow:

**Source and Minified Files:**
- Source files (e.g., `game-list-renderer.js`) contain the readable code
- Minified files (e.g., `game-list-renderer.min.js`) are generated from source files
- **Always edit the source `.js` file, never the `.min.js` file directly**

**Bundle Files:** two, each built by `scripts/minify_js.sh` from minified
sources in dependency order, and each starting with
`core/static/core/js/base-renderer.min.js` - a bundle whose renderer extends
`BaseMediaListRenderer` without it throws a `ReferenceError` as it loads, so
nothing declared after that point registers either:

- `games/static/games/js/client-side-filtering.bundle.min.js` - `base-renderer`, `game-cache`, `client-filter`, `game-list-renderer`, `client-filtering`
- `music/static/music/js/music-client-side-filtering.bundle.min.js` - `base-renderer`, `album-filter`, `album-list-renderer`, `album-client-filtering`

`core/static/core/js/` also holds three files loaded on their own rather than
bundled, because they have to run before Alpine initialises:
`filter-subcomponents.min.js`, `media-list-controls.min.js` and
`media-search.min.js`. Pages push them onto `window.alpineScripts` in
`{% block pre_alpine %}`.

`games/js/rank-distribution.min.js`, the chart's script, is queued the same
way by the four pages that draw a chart (both rankings pages, developer
detail, artist detail). `base.html` queued it on every page until
2026-11-12, ahead of Alpine. A page that includes
`core/includes/_rank_distribution.html` has to queue it:
`ChartScriptIsQueuedWhereThereIsAChartTests` lists the pages, and the smoke
test fails on a chart with no script.

`core/tests/test_static_bundles.py` asserts that every bundle a template
references exists and that each defines the base classes its members extend.
Both of those failed silently in the books bundle until 2026-10-17. Books
has had no bundle since 2026-11-12: its page loaded one that nothing
started, with a renderer that posted to routes that do not exist, and the
whole client stack (four scripts, three `<template>`s) was removed. The
server renders the books list.

**After Editing JavaScript:**
Run `/minify` or `./scripts/minify_js.sh`

The minify skill/script:
1. Minifies every source `.js` file with terser pinned at 5.51.2, replacing any `.min.js` whose content differs (`--check` reports instead, and CI's `js` job runs it)
2. Regenerates the bundle if any of its source files changed
3. Stages updated files for git

**Important:** When modifying client-side game rendering (e.g., `game-list-renderer.js`), changes must be reflected in both:
- The Django template (server-side rendering)
- The JavaScript file (client-side rendering on home page)

**What `utils-base.js` gives every script** (it loads on every page, before
Alpine and the bundles), each because the bare form failed for someone
(2026-11-09, `core/tests/test_utils_base_js.py`, run under Node):

- **Stored preferences go through `readStoredPreference`, `readStoredJson`,
  `storePreference` and `removeStoredPreference`**, never `localStorage` or
  `sessionStorage` unguarded. With cookies blocked Chrome throws on the
  property itself, and the games filter component read six preferences in
  its data literal, so for those readers it never started. A script that
  runs ahead of `utils-base.js` (the head's theme script, a pre-paint
  script) wraps its own read in `try`, as `quick-mark.js` and the album
  engine already did theirs.
- **A scripted scroll asks `scrollBehavior()`**, not `'smooth'`: the
  stylesheet turns smooth scrolling off under `prefers-reduced-motion`, but
  a script that names `smooth` overrides a stylesheet.
- **`fetchHtml` throws on an error status.** It returned the body whatever
  the status, and the filter component set the results to a 500's page.
- **A result count the server swaps in is said through `announce()`**, which
  writes to the one persistent live region (`#live-announcer` in
  `base.html`). A count that arrives inside a swapped list is a live region
  inserted with its text, which is usually not read out. Do not call it for
  a count the client renderer rewrites in place: that region stayed put and
  announces itself. The rankings' count carries no `role` in its markup;
  `markResultCountsLive` gives it `role="status"` once it is on the page
  (2026-11-10). With the role in the template, a count the server swapped
  in was a region inserted with its text, which the readers that do read
  those then heard again from the announcer.
- **A search box is a combobox** (`searchComboboxState`, spread into both
  search components; 2026-11-10; its markup is one include since
  2026-11-12, `core/includes/_search_combobox.html`, where the sidebar and
  the mobile bar each carried two copies): the arrow keys move an active option the
  field names with `aria-activedescendant`, Enter follows it, and Enter
  with none is the full search, as it was. The results are `role="option"`
  links in a `role="group"` per kind inside a `role="listbox"`; the hints
  are a list of their own, since a listbox owns options alone. A keystroke,
  a new query or the clear button forgets the active option: a keyed loop
  reuses elements, and Enter within the search's 300 ms debounce would
  otherwise follow the last query's option. Checked against Chrome's accessibility tree, not yet on
  a screen reader (`docs/ASSISTIVE_TECH_CHECKLIST.md`).
- **A script's POST reads the CSRF token through `readCsrfToken()`**, and
  a script asking whether the page is at desktop width through
  `isDesktopWidth()` (2026-11-11): three cookie readers had drifted (one
  cached the token, one did not decode it) and the breakpoint was spelt
  seven times.
- **An engine's Load More replaces its button through
  `replaceKeepingFocus`**, which puts a keyboard reader's focus on the new
  button, or the "all loaded" line, rather than at the top of the page.
  Choosing a status does the same for the item's new button
  (`media-tracking.js`, `played-menu.js`). A Load More the server answers
  (music's, before its engine loads) replaces `#load-more-container` out
  of band, and a listener here puts focus on the new one (2026-11-12).
- **A failed search says "Search failed"** (`failed` on both search
  components), where it read as "No results found".
- **A search box aborts the request it overtakes** (`FetchManager`), in
  `createUnifiedSearchData` and `core/js/media-search.js`: a slow answer
  for "be" replaced the results for "beatles".

**`_escapeHtml` (`base-renderer.js`) escapes as Django's `escape` does**,
quotes included, since the renderers write names into attributes as well as
text (`core/tests/test_escape_html.py`). It went through `textContent`,
which leaves quotes alone: 'Bonnie "Prince" Billy' ended its `title` early.

**A mobile row card's title is a link** (`title-link`; music's
`title-link-mobile`), in the server's rows and the renderers' alike. The
card still goes to its item on a click anywhere (`data-href`), but that
alone gave the keyboard no way in. smoke: "mobile row opens by keyboard".
