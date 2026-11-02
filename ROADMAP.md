# Roadmap

What is left, why it matters, and what it costs. Ordered within each group.
`DEVLOG.md` records what has shipped; this file records what has not.

## Open bugs (found 2026-11-01)

Found while shipping v905's filter-engine work and the music metadata refresh
that followed, and in fixing the first list (2026-11-02, `DEVLOG.md`). None
is a regression from v905.
`music/static/music/js/album-client-filtering.js`'s `change` listener has
broken three times when given state, so keep any fix there stateless and pin
it in `scripts/browser_smoke.js` first.

1. **Never tested on real assistive tech or a real iPhone.** The year grid
   and the mobile sheet were checked in Chrome, WebKit and Firefox, plus
   Chrome's accessibility tree, but never with VoiceOver, NVDA or iOS Safari.
   `docs/ASSISTIVE_TECH_CHECKLIST.md` is the script: run it, record the
   results there, and file what fails here.
2. **The music Wikidata pass reads only English labels** (found 2026-11-02).
   Wikidata has moved some names to the language-neutral `mul` label, and
   `music/wikidata.py` reads `labels.en` alone. So `fetch_labels` drops
   punk rock (Q3071), rapcore and Reprise Records from every album's
   Wikidata genres and label, and `fetch_artists` skips 27 artists outright -
   Radiohead, Rihanna, 50 Cent, Lil Wayne - which therefore have no
   `musicbrainz_id` or `wikipedia_title`. Fall back to `mul` (request
   `languages=en|mul`), then check `rebuild_album_genres --dry-run --report`.
   Small.
3. **Games: a server jump overtaken by a filter change still jumps.** Before
   the engine is ready, jump to 500, so the server fetches pages 2-5; the
   engine loads and a genre is picked, re-rendering at #1. When the pages
   land, `jumpToRankServerSide` finds its button gone and calls
   `jumpToRankClientSide(csf, 500)` on the genre's list, undoing the reset to
   the top. Drop it, as a late Load More page is dropped, unless whatever
   replaced the list knows it is the same one. Found in review, 2026-11-02.
   Small.
4. **Games: other re-renders still drop an in-flight server Load More.** The
   engine's takeover and a view toggle answer it; a client jump
   (`refreshClientLoadMore` replaces the button) and the played-filter
   re-render on `game-status-changed` do not, so the page is dropped and the
   click goes unanswered. Both answers also restart from 100 rows, so a click
   for rows 201-300 gets 101-200. One owner for the hand-off, around
   `performClientUpdate`, would cover every caller. Found in review,
   2026-11-02. Small.
5. **The mobile sheet's decade buttons do not say which is selected.** In
   `core/includes/_mobile_filter_time.html` the Decade / Year / Range switch
   and the decade buttons show their state by colour alone (`btn-primary`),
   with no `aria-pressed`, where the sidebar's year grid and the sheet's genre
   rows carry it. Found by reading the markup, not with a screen reader;
   item 1's checklist expects it to fail. Small.
6. **A music filter change does not cancel a Load More in flight.** Without
   the engine (before it loads, or if it fails), click Load More and then
   change a filter before the page arrives: the filter render lands, then the
   stale page appends into the detached old list, and its out-of-band
   `#load-more-container` replaces the new filter's button with the old
   one's, e.g. "All 120 results loaded" over a list of 100. Found reviewing
   the takeover fix; the engine aborts it if it is still in flight when the
   engine takes over (`scripts/browser_smoke.js`, "Load More swapped out").
   Likely fix: a shared `hx-sync` scope on the form and the Load More button,
   so a filter request replaces the page request. Small.
7. **htmx's snapshot restore may break Alpine on other pages too** (found
   2026-11-02, unverified). On music's rankings page, Back onto an entry htmx
   pushed restored a snapshot of the DOM Alpine had built and threw an
   Alpine error per `x-for` clone, the site menu's included; that page now
   takes popstate from htmx (AGENTS.md, "Music client-side filtering").
   Every other `hx-push-url` page - the artist and list searches, the
   paginations, the blog - saves the same snapshots. Reproduce on
   `/artists/` (search, then Back) before changing anything. Medium.
8. **A failed filter request is still left ahead of the list in two
   cases.** The engine renders the form's filters as it takes over, but not
   while a search box has focus (a search still being typed must not be
   pushed half-typed), and not at all if the engine never loads. Either
   leaves the sidebar on filters the list does not show until the next
   change. Small.
9. **A `?page=N` music rankings link assumes it starts at row 1.**
   `renderer.adopt` sets the window from 0, so the engine's Load More and
   jump on a server-rendered page 2 repeat or skip rows. Nothing links to
   `?page=` any more, since Load More no longer pushes it. Small.

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
