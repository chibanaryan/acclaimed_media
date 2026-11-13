<!-- Part of the agent documentation. AGENTS.md keeps each section's rules
     and points here for the reasoning, history and measurements behind
     them. Moved out of AGENTS.md, word for word, on 2026-11-12. -->

# The rankings heading and the tab title

Both sections compose a heading from the filter state. The document title
reuses it only where search engines read it: an unfiltered page and a
landing page. A filtered page's tab lists its facets and names its section
instead ("Rock · 1990s | Music | Acclaimed Media", `_tab_title` /
`_build_tab_title` and `buildTabTitle` / `_buildTabTitle`), since its URL
canonicalizes to the bare path and "Most Acclaimed ... Albums of" only
pushed the facets out of a narrow tab (2026-11-02, at James's request). The
client titles each state as a reload of the URL it goes to would: music's
filter changes land on `/?...`, so only Back to a landing page's own path
gets that page's heading, and games titles a state it pushes as a clean
landing URL (`/games/1990s/`) by its heading. Nothing is kept from the
page's load. A first version restored the served title whenever the facets
matched the served ones, which put a landing page's heading on
`/?genres=...` and, after a bfcache Back, a cleared filter's facets on the
unfiltered page. `scripts/browser_smoke.js` compares each step's tab with a
reload's. The section suffix is the context processor's `tab_title_suffix`,
published as `window.tabTitleSuffix`. Two traps, both of which have bitten:

- **A genre clicked in a row does not go through the filter component.**
  `album-client-filtering.js` answers `add-genre` by writing the hidden
  select and re-rendering from the engine. `filters` lives on
  `mediaListControls`, and the heading and the sidebar genre tree are both
  built from it, so the row handler announces `genres-selected` and the
  component listens. Without that the list filtered while the heading went
  on naming the unfiltered page, and a reload "fixed" it because the server
  composes the heading from the URL. Games has no such bug: it routes
  `add-genre` through `component.addGenre`.
  `core/tests/test_static_bundles.py` pins the event name from both ends,
  minified copies included.
- **The document title is not free on either path.** `games/home.html` used
  `seo_title`, which only the SEO landing views set, so the tab title never
  moved. It now falls back to `filter_title`, as music's always did. Nothing
  set `document.title` during client-side filtering in either section;
  `base.html` publishes one `window.documentTitleSuffix` and both filter
  components rebuild `heading + suffix`.

There are no `?v=N` cache-busters to bump. Production's manifest storage
hashes every static name, so changed JS is a new URL, and development
serves static files with `WHITENOISE_MAX_AGE = 0`. Until 2026-10-26, 22
hand-maintained literals did nothing in production; in development the
one-year max-age was what made them necessary.
`core/tests/test_static_assets.py` keeps them from coming back.
