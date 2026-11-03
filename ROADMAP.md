# Roadmap

What is left, why it matters, and what it costs. Ordered within each group.
`DEVLOG.md` records what has shipped; this file records what has not.

## Open bugs (found 2026-11-01)

Found while shipping v905's filter-engine work and the music metadata refresh
that followed. Four more from the same list were fixed on 2026-11-02, and
the three held back that day on 2026-11-03 (`DEVLOG.md`).
`music/static/music/js/album-client-filtering.js`'s `change` listener has
broken three times when given state, so keep any fix there stateless and pin
it in `scripts/browser_smoke.js` first.

1. **Never tested on real assistive tech or a real iPhone.** The year grid
   and the mobile sheet were checked in Chrome, WebKit and Firefox, plus
   Chrome's accessibility tree, but never with VoiceOver, NVDA or iOS Safari.
   `docs/ASSISTIVE_TECH_CHECKLIST.md` is the script: run it, record the
   results there, and file what fails here.

## Open bugs (found 2026-11-03)

Older bugs the reviews of 2026-11-03's work turned up, already on `main`
before it; none came from it.

2. **Games: a Load More answered by something other than its page sticks.**
   A 200 response without `#load-more-meta` (not the append partial)
   appends its rows and leaves the button loading and disabled for good
   (`utils-loadmore.js`, `appendPageResults`/`handleLoadMore`).
3. **Games: a Load More clicked while Back's server render is on its way**
   (before the engine) fetches from the URL Back has moved to, and if its
   page lands first, the other list's rows go in under the one shown.
4. **Music: a failed request sent before Alpine starts stays ahead.** Enter
   in the search box or a row's genre, sent before the controls exist, that
   fails while the engine's data also fails, leaves the form and controls
   ahead of the list: the controls cannot tell a request they never saw
   from a change of the reader's. So does a saved filter whose blob stores
   its years as strings, or a hand-edited `?genres=5,abc`, which read as
   the reader having moved on.
5. **Music: "Back keeps the artist in the heading" races.** The heading
   reads the form's `artists` field, which only the engine's popstate
   listener restores, so it rests on that listener running first. Under
   three parallel browsers `main` failed the check 10 times in 12; alone it
   passes. Have the controls restore `artists` themselves.
6. **Games' cached bare pages carry no data version.** Music's do since
   2026-11-03 (`get_page_cache_version`): its client joins the page's rows
   to the payload's by position. If the games engine seeds from the server's
   rows the same way, a cached `/` from before an import beside a fresh
   payload repeats and drops games for up to five minutes. Unverified.

The browser harnesses used for v905 are in the ashgabat worktree's
`.context/ygrid/`, which is gitignored and so exists only there:
`matrix.js`, `musicrace.js`, `loadmore.js`, `round8.js`-`round10.js`, and
`xbrowser.js` for WebKit and Firefox.

## Music: after launch

The section is public at `music.acclaimedmedia.org`, beside the games site and
a landing page at the apex (2026-10-30; AGENTS.md, "Domain"). The pages keep a
"Beta" badge while `music.config.MUSIC_BETA` is on.

7. **New brand artwork.** The favicons still read "Acclaimed Video Games"
   (`games/static/games/brand/`), and a page without artwork of its own has
   no `og:image` since the old one was removed; every page title already
   says Acclaimed Media. A new default goes in `base.html`'s `og_image` block,
   and the five templates overriding that block need a `{{ block.super }}`
   branch for items with no art.

## Production memory

The rankings page is 690 KB anonymous and 833 KB logged in, and the dyno
runs gthread with three threads per worker (AGENTS.md, "Production memory
budget").

8. **Check `--threads 3` after a week.** The `Procfile` went from two
   threads per worker to three on 2026-11-03, on a week of gthread at two
   (2026-10-27 to 11-02) that peaked at 342 MiB RSS of the 512 MiB quota,
   with swap never above 13 MiB. Around 2026-11-10, re-read
   `memory.rss.bytes.max` and `memory.swap.bytes.max` from the metrics API
   (AGENTS.md, "Production memory budget"); back to two if the peak nears
   the quota or swap climbs.

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
  errors per page load). Deprioritized by the owner.
