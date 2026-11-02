# Roadmap

What is left, why it matters, and what it costs. Ordered within each group.
`DEVLOG.md` records what has shipped; this file records what has not.

## Open bugs (found 2026-11-01)

Found while shipping v905's filter-engine work and the music metadata refresh
that followed. None is a regression from v905. Most are on music's rankings
page, in `music/static/music/js/album-client-filtering.js`. That file's
`change` listener has broken three times when given state, so keep any fix
there stateless and pin it in `scripts/browser_smoke.js` first.

1. **Clicking out of the music search box can swallow the click.** The search
   input's native `change` fires on blur and reaches the form's `change`
   listener, which re-renders the list during the mousedown. Type "love", wait
   for results, then click Load More or an album: the first click does nothing.
   Likely fix: ignore a `change` with no `detail`, since `mediaListControls`'
   `commit()` is the path that should render. Small.
2. **Each music search renders twice.** Alpine's `@input.debounce.350ms`
   commit and the bundle's own typing timer (`search.addEventListener('input',
   ...)`) both answer it. `pushUrl` skips the second history entry since v905,
   but the 100-row render, the facet counts and the chart morph still run
   twice. Likely fix: drop the typing timer, which matters only if Alpine fails
   to load. Small.
3. **Marking an album under a status filter resets the list.** On
   `/?listened=no`, Load More to row 300, then mark #250 (or use quick-mark):
   `album-status-changed` re-renders the first 100 rows and the reader loses
   their place. With `?highlight=N` still in the URL it also scrolls back to N.
   Fix: remove just the row that left the filter. Medium.
4. **A failed music filter request leaves the form ahead of the list.** If an
   HTMX filter request fails (429, 500, network) before the engine is ready,
   the form holds the new filters while the URL and list hold the old. The next
   Load More runs `_syncRendererWithPage`, which adopts the form's filters at
   the server's row count and appends another filter's rows. Fix: re-render, or
   reset the form, on `htmx:responseError` / `htmx:sendError`. Medium.
5. **Back onto an entry HTMX pushed may detach music's engine.** Unreproduced,
   from reading htmx 1.9.10. Click a decade before the engine loads, so HTMX
   pushes the entry; once the engine is ready, press Back. htmx's
   `restoreHistory` swaps the body, and the bundle's listeners stay on the old,
   detached form, so later changes would not reach the engine and Load More
   could fire twice. Reproduce first. A likely fix is turning off htmx's
   history snapshot once the engine owns the page. Medium.
6. **Music's jump box does nothing if the bundle fails.** `initAlbumJumpToRank`
   runs only after the engine loads, so with no data the box takes input and
   ignores Enter. Hide or disable it until the engine is ready. Small.
7. **Games: Clear All from a jumped list adds a duplicate history entry**
   (`/` pushed over `/`). Fix: `_writeHistory` in `filter-component.js` skips a
   push whose key equals `_urlFilterKey`. Small.
8. **Games: a server Load More is dropped if the list/grid toggle re-renders
   meanwhile.** On a bare `/`, Load More before the engine loads, then toggle
   the view as it lands: the button is replaced, so `appendPageResults` drops
   the page and the click goes unanswered. Rare, and a second click works.
   Small.
9. **Games: jump to rank filters the whole corpus three times**
   (`getCurrentState` twice and `jumpToRankClientSide` once, in
   `utils-loadmore.js`). Have `getCurrentState` return the games it filtered.
   Small.
10. **The music Wikidata pass logs an error for 'Old Nobody' on every run.** It
    is the one album with no QID, and `metadata_service` logs "Wikidata pass
    failed" with a traceback instead of skipping it, so every Sunday job
    reports a failure and may file a Sentry issue (not checked). Skip albums
    without a QID in the pass. Small.
11. **Ten genre labels are unclassified**, so they add nothing until they are:
    Neue Deutsche Welle (Wikidata and MusicBrainz) and Euro House (Discogs and
    MusicBrainz) each come from two sources; German rock, urban contemporary
    and Memphis soul from Wikidata; stoner metal and bubblegum bass from
    MusicBrainz; Political from Discogs. Classify each in
    `music/services/genre_normalizer.py` and add it to `RealVocabularyTests`'
    lists, then check `rebuild_album_genres --dry-run --report`. Small.
12. **Nine albums have no Discogs data.** Seven have no Discogs master on
    Wikidata (I Never Loved a Man the Way I Love You, On the Beach, Damn,
    Freedom, DS2, Old Nobody, Ella Fitzgerald Sings the George and Ira Gershwin
    Song Book). Two point at masters that now 404: The Raincoats (87851) and
    The Magnolia Electric Co. (365195). All nine still have genres. The fix is
    on Wikidata, or a per-album override. Small.
13. **37 albums have no release date.** The year still shows and filters; they
    sort last within their year under Release Date. Neither Wikidata P577 nor
    MusicBrainz gave a day or month. Check whether the sources have improved.
    Small.
14. **Cleanups left in `album-client-filtering.js`.**
    - `loadedAlbumCount`'s `viewMode` parameter, the zero-offset branch in
      `scrollToAlbumPosition`, and `applyFilters`' `return { total }` are dead.
    - `matchCount` has no `isInitialized` guard, unlike its neighbours.
    - The takeover finds in-flight requests by the `htmx-request` class on
      `#album-loading` and `.load-more-button`, so moving the spinner silently
      disables it.
    - The landing path and search are rendered twice in `music/home.html`
      (`window.albumLanding*` and `mediaListControls`' settings), and read by
      two copies of one rule (`albumUrlParams`, `_syncFromUrl`).
15. **Never tested on real assistive tech or a real iPhone.** The year grid
    and the mobile sheet were checked in Chrome, WebKit and Firefox, plus
    Chrome's accessibility tree, but never with VoiceOver, NVDA or iOS Safari.

The browser harnesses used for v905 are in the ashgabat worktree's
`.context/ygrid/`, which is gitignored and so exists only there:
`matrix.js`, `musicrace.js`, `loadmore.js`, `round8.js`-`round10.js`, and
`xbrowser.js` for WebKit and Firefox.

## Music: after launch

The section is public at `music.acclaimedmedia.org`, beside the games site and
a landing page at the apex (2026-10-30; AGENTS.md, "Domain"). The pages keep a
"Beta" badge while `music.config.MUSIC_BETA` is on.

1. **Redirects for renamed artist slugs.** Every import and Wikidata pass
   rebuilds artist slugs from the current names, and nothing redirects the
   old ones, so a renamed act's inbound links 404. Launched without them by decision; an `ArtistSlugHistory` written by
   `rebuild_artist_slugs` and read by `ArtistDetailView` would fix it.
2. **An anonymous page cache for music.** Games' rankings and landing pages
   use `AnonymousResponseCacheMixin`; music's have none. Every cached page
   spends from the 512 MB budget, so measure before adding it.
3. **New brand artwork.** The favicons still read "Acclaimed Video Games"
   (`games/static/games/brand/`), and a page without artwork of its own has
   no `og:image` since the old one was removed; every page title already
   says Acclaimed Media. A new default goes in `base.html`'s `og_image` block,
   and the five templates overriding that block need a `{{ block.super }}`
   branch for items with no art.

## Production memory

The rankings page is 690 KB anonymous and 833 KB logged in, and the dyno
runs gthread with two threads per worker (AGENTS.md, "Production memory
budget").

4. **Measure gthread on the dyno.** `memory.rss.bytes.max` and swap over a
   day of traffic decide whether `--threads 3` fits, or whether the next
   step is Standard-2X (1 GB, $50/mo vs Basic's $7).

## Housekeeping

5. `BOOKS_ENABLED` is two flags that never meet: the setting is read by
   nothing, and `games.context_processors.feature_flags` reads the raw env
   var instead. Make the setting read the env var, with `env.bool`, and
   point the context processor at it.

## Music: not worth doing as parity

- **Artist detail has no related-acts panel** where developer detail has a
  subsidiary filter. 0 of 629 artists in this corpus have sub-acts, so the
  panel would always be empty. Revisit only if the metadata pass starts
  filling `Artist.parent`.
- **Games' source-lists page still carries its own inline sort control**
  rather than `core/includes/_entity_sort_controls.html`. It looks identical;
  it is the last un-shared duplicate, so it is tidying, not parity.
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
  errors per page load). Deprioritized by the owner.
