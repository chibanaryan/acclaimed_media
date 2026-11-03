# Roadmap

What is left, why it matters, and what it costs. Ordered within each group.
`DEVLOG.md` records what has shipped; this file records what has not.

## Open bugs (found 2026-11-01)

Found while shipping v905's filter-engine work and the music metadata refresh
that followed. Four more from the same list were fixed on 2026-11-02, and
the three held back that day on 2026-11-03 (`DEVLOG.md`). The five older
bugs the 2026-11-03 reviews turned up were fixed the same day, and the two
filed then (the entity pages' Load More, an engine on a payload of another
version) later that day.
`music/static/music/js/album-client-filtering.js`'s `change` listener has
broken three times when given state, so keep any fix there stateless and pin
it in `scripts/browser_smoke.js` first.

1. **Never tested on real assistive tech or a real iPhone.** The year grid
   and the mobile sheet were checked in Chrome, WebKit and Firefox, plus
   Chrome's accessibility tree, but never with VoiceOver, NVDA or iOS Safari.
   `docs/ASSISTIVE_TECH_CHECKLIST.md` is the script: run it, record the
   results there, and file what fails here.

The browser harnesses used for v905 are in the ashgabat worktree's
`.context/ygrid/`, which is gitignored and so exists only there:
`matrix.js`, `musicrace.js`, `loadmore.js`, `round8.js`-`round10.js`, and
`xbrowser.js` for WebKit and Firefox.

## Open bugs (found 2026-11-03, second session)

2. **A `?highlight=` landing can miss when an import commits during the
   page's load.** The engine then renders from the new data
   (`followsPage()`), and lands on the album again only for a reader still at
   the landing: the first landing not yet scrolled, or the row's middle on
   screen. Three edges are left, each needing a page load to straddle an
   import as well: a landing's smooth scroll still in motion counts as moved
   on, so the album is flashed where the old row was; a phone's momentum
   fling begun before the render is not seen as moving; and a row whose
   middle sits under the sticky header still counts as on screen. Six review
   rounds went into this case, so weigh any fix against how rare it is.

## Music: after launch

The section is public at `music.acclaimedmedia.org`, beside the games site and
a landing page at the apex (2026-10-30; AGENTS.md, "Domain"). The pages keep a
"Beta" badge while `music.config.MUSIC_BETA` is on.

3. **New brand artwork.** The favicons still read "Acclaimed Video Games"
   (`games/static/games/brand/`), and a page without artwork of its own has
   no `og:image` since the old one was removed; every page title already
   says Acclaimed Media. A new default goes in `base.html`'s `og_image` block,
   and the five templates overriding that block need a `{{ block.super }}`
   branch for items with no art.

## Production memory

The rankings page is 690 KB anonymous and 833 KB logged in, and the dyno
runs gthread with three threads per worker (AGENTS.md, "Production memory
budget").

4. **Check `--threads 3` after a week.** The `Procfile` went from two
   threads per worker to three on 2026-11-03, on a week of gthread at two
   (2026-10-27 to 11-02) that peaked at 342 MiB RSS of the 512 MiB quota,
   with swap never above 13 MiB. Around 2026-11-10, re-read
   `memory.rss.bytes.max` and `memory.swap.bytes.max` from the metrics API
   (AGENTS.md, "Production memory budget"); back to two if the peak nears
   the quota or swap climbs. Since v914 an import's metadata fetch spends
   ~85 MB in one worker while it runs, so read a week that held one.

## Imports and their metadata fetch (found 2026-11-03, v914)

An import now starts its metadata fetch (AGENTS.md, "Imports start their
metadata fetch"). Its six review rounds left these, none caused by it.

5. **A games import drops every game's slug, developers and series.**
   `import_games` recreates every `Game` and reattaches the stored IGDB rows,
   but those fields live on `Game`, so every link reads `/games/None/` until
   the forced IGDB pass restores them, 2-3 minutes after each import, or
   until Sunday if the fetch is off or dies. Carry them across the import by
   `igdb_id` from the old rows before the delete; then the post-import IGDB
   pass can go missing-only like Wikipedia and HLTB, and the window closes.
   Do this first: it also takes most of the weight off 6 and 7.
6. **A fetch killed with its worker is not resumed.** It runs on a daemon
   thread in a web worker, so a deploy or a `--max-requests 500` recycle
   mid-fetch ends it silently, and the rest waits for the Sunday job. Cheap
   fix: record a pending marker when it starts, clear it when done, and have
   the import page's GET restart a fetch whose marker outlived its lock
   (staff are told to reload that page anyway).
7. **The fetch's lock is not shared** with the import page's IGDB and
   Wikipedia buttons or the Sunday jobs (`refresh_all_metadata`,
   `fetch_album_metadata --weekly`), so either can run a second pass beside
   it: twice the IGDB rate limit and the connections. The page asks staff to
   wait; have the buttons and the weekly commands take
   `core.services.post_import`'s lock instead. On the shared DatabaseCache
   `cache.add` over an expired row is also not atomic, so two imports in the
   same instant after a lapse could both take it.
8. **The 24-hour series and genre lists are never invalidated.**
   `SERIES_CACHE_KEY` and `GENRES_CACHE_KEY` (`games/views/rankings.py`) are
   dropped by nothing, so a page rendered just after a games import, before
   IGDB restores the series, caches an empty series filter for a day. Drop
   them when the games data version moves, or key them on it.
9. **The `cache_page`'d games API ignores imports.** `/api/games/` (15 min),
   `/api/games/<slug>/` and `/api/developers/<slug>/` (30 min) and
   `/api/genres/` (24 h) are keyed on the release, not the data version, so
   they serve pre-import rows, null slugs included, until they lapse.
10. **The IGDB pool's connections outlive it.** `IGDBImportService` runs a
    pool of 8 threads, and nothing closes their connections, so in a web
    worker (the post-import fetch, or the IGDB button) they linger until the
    garbage collector reaches the threads. Close them as each pool thread
    finishes, as `start_background_thread` does for its own.

## Music: not worth doing as parity

- **Artist detail has no related-acts panel** where developer detail has a
  subsidiary filter. 0 of 629 artists in this corpus have sub-acts, so the
  panel would always be empty. Revisit only if the metadata pass starts
  filling `Artist.parent`.
- **Migrating games and books onto the shared `core/includes/` partials** -
  `_tracking_button.html`, `_status_filter.html`,
  `_saved_filters_dropdown.html`, `_saved_filter_modals.html` and
  `_mobile_saved_filters.html`. All are parameterised for it, and the
  saved-filter three were lifted from games' own markup against the method
  names games already exposes, so that migration is a template change. But
  games' versions are working code with sizeable suites behind them, and the
  duplication costs nothing until one of them changes. The argument for doing
  it eventually: games' `applySavedFilter` never restored `sortDirection` for
  as long as the feature existed, and the shared copy never had that bug.

## Known divergences, deliberate for now

- **The games rankings heading ignores the search query, on both sides.**
  `_build_filter_title` and `_buildDynamicTitle` both leave `?q=` out, so
  searching does not change the heading; music names the query instead
  ("Albums matching ..."). The two games halves agree with each other, which
  is the property that matters, so this is a wording difference rather than
  a bug. Align only if the album phrasing is judged better.
- **The album page's sub-heading counts are corpus-wide, not filtered.**
  "The top 1,000 most recommended albums across 54 critic lists" stays put
  while the heading above it narrows to a genre. Games has no filtered
  equivalent either, and the filtered count is already shown on the results
  line.

## Explicitly not doing

- **Books.** The client-side filtering stack was repaired on 2026-10-17 so it
  runs, but books still has no filter UI at all, and its sort controls
  reference an Alpine `filters` variable no component provides (5 console
  errors per page load). An author's page renders a Load More button that
  nothing answers (`author_detail.html`), and the authors list pushes its own
  history entry beside htmx's on every search and sort, so Back takes two
  presses (AGENTS.md, "A page never pushes an entry of its own"). Deprioritized
  by the owner.
