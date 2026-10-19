# Roadmap

What is left, why it matters, and what it costs. Ordered within each group.
`DEVLOG.md` records what has shipped; this file records what has not.

## Music: the last parity gaps

A mechanical diff of the games and music feature sets (every `aria-label`,
`title`, form field and control on each pair of pages) left two real gaps.
**Both are now closed**, and everything else either matches or is genuinely
games-only (platforms, playtime, series) - so there is no open parity item
here, only the notes below on what was deliberately not done.

1. ~~**Album tracking: `ListenedAlbum` / `WantToListenAlbum`.**~~ Done
   2026-10-18. The models, the toggle endpoint, the 48px column on both row
   halves, the Listen Status filter server- and client-side, and the detail
   page button. The button and the status filter were built as shared
   `core/` partials rather than a third copy of games'; games and books are
   untouched and can migrate to them. See AGENTS.md, "Album tracking".
2. ~~**Saved filters.**~~ Done 2026-10-18. `core.models.SavedFilterSetBase`
   with a concrete `music.SavedAlbumFilterSet`, `/api/music/saved-filters/`
   (the section's first **write** endpoint, so CSRF now applies to
   `music/api/`), and three shared `core/includes/` partials - the sidebar
   dropdown, the three modals, and the sheet's collapsible block - driven by
   saved-filter methods added to `core/js/media-list-controls.js` under the
   names games already uses. Games is untouched and can migrate by swapping
   includes. See AGENTS.md, "Saved filters".

   Two things the work turned up, both only visible in a browser:
   `applySavedFilter` must **not** announce `year-reset`/`genres-reset` -
   the mobile sheet answers those by clearing the state, at every width, so
   it wiped the combination just restored - and games'
   `applySavedFilter` had never restored `sortDirection` at all, though it
   had always been stored. Both pinned by source tests.

Not worth doing as parity:

- **Artist detail has no related-acts panel** where developer detail has a
  subsidiary filter. 0 of 629 artists in this corpus have sub-acts, so the
  panel would always be empty. Revisit only if the metadata pass starts
  filling `Artist.parent`.
- **Games' source-lists page still carries its own inline sort control**
  rather than `core/includes/_entity_sort_controls.html`. It looks identical;
  it is the last un-shared duplicate, so it is tidying, not parity.
- **Migrating games and books onto the shared `core/includes/` partials** -
  `_tracking_button.html` and `_status_filter.html`, and now
  `_saved_filters_dropdown.html`, `_saved_filter_modals.html` and
  `_mobile_saved_filters.html` too. All are parameterised for it, and the
  saved-filter three were lifted from games' own markup against the method
  names games already exposes, so that migration is a template change. But
  games' versions are working code with sizeable suites behind them, and the
  duplication costs nothing until one of them changes. The `sortDirection`
  bug is the argument for doing it eventually: it sat in games for as long
  as the feature existed, and the shared copy never had it.

## Music: before it can launch publicly

3. **Nav entry and a `MUSIC_ENABLED` flag.** Today the only gate is
   `StaffOnlyMixin` raising 404 and the absence of any link. A flag gives a
   kill switch independent of staff status. ~2 hours.
4. **Discogs attribution terms.** Needs a human: their docs 403 automated
   fetches. Genres and styles come from Discogs, so the terms decide what the
   site has to display.
5. **Decide whether music gets SEO landing pages.** Games has
   `/games/<genre>/` and `/games/<decade>/`, crawlable and self-canonical,
   built from the same filter machinery. Music could, now that it shares the
   filters - but only once the section is public.

## Data pipeline

6. **Set `DISCOGS_TOKEN` on Heroku.** The metadata refresh is paced by the
   anonymous Discogs tier at 25 requests a minute, which is ~40 minutes for
   1000 albums. A token raises the ceiling and the client paces itself from
   the response headers either way.
7. **Schedule the music metadata refresh.** Games has a weekly refresh on the
   scheduler addon; music is run by hand. An import does not trigger it (on
   either section), which is now visible on the music import page.
8. **The MusicBrainz pass is opt-in and has never run on the new release.**
   `--musicbrainz` fills genres for the albums with no Discogs master - three
   of them in the previous release, unknown in this one.

## Production: the dyno was over its memory quota

11. ~~**R14s are constant, not occasional.**~~ Diagnosed and fixed on
    2026-10-18. The roadmap's reading was right: a **baseline footprint
    larger than the quota**, not a leak. Measured, rather than guessed:

    - Production, from the Heroku metrics API over 24 h: RSS pinned at
      496-533 MB in every hourly bucket against a 512 MB quota, swap up to
      86 MB, total peaking at 604 MB (112.6%), and up to 663 k pages paged
      in per hour.
    - One worker locally, prod-shaped settings: 110 MB at boot (79 MB of
      imports, ~30 MB of it `sentry_sdk`), 161 MB after one `GET /`, and a
      **flat plateau at ~200 MB** from 50 renders out to 1000. 3 x 200 MB is
      the 530 MB RSS + 86 MB swap production reported, so the arithmetic
      closed and nothing was left to hunt.
    - `--preload` was measured and rejected: a forked child touched ~160 MB
      of the parent's pages within 20 requests, so copy-on-write saved
      nothing (593 MB vs 585 MB).

    What shipped: `--workers 2` with `--max-requests 500`; the site-wide
    `UpdateCacheMiddleware`/`FetchFromCacheMiddleware` pair deleted (it keyed
    a copy of every page on every visitor's `Cookie` header and stored
    nothing at all for a cookieless first-time visitor - all of the cost,
    none of the benefit); `AnonymousResponseCacheMixin` bodies stored
    deflated, which turns ~50 cacheable URLs x 1.4 MB into ~6 MB per worker;
    the rate-limit counters moved to their own `ratelimit` alias so page
    bodies can no longer cull them; Sentry tracing sampled at 0.1 with
    profiling off; and one needless full copy of each album cover's bytes
    removed from `AlbumCoverView`. See AGENTS.md, "Production memory budget".

    Still open, in the order the measurements favour: the rankings page is
    **1.4 MB of HTML** - 100 games each emitted as both desktop and mobile
    markup - and that render is what leaves ~45 MB of unreturnable arenas in
    every worker. Halving it is the next real lever, then
    `--worker-class gthread` for concurrency without a third heap, then
    Standard-2X (1 GB, $50/mo vs Basic's $7).

13. ~~**Every music page costs 300-450 queries.**~~ Fixed 2026-10-18.
    Measured before and after against the real 1000-album database, logged
    in as staff:

    | page | before | after |
    |---|---|---|
    | `/music/` | 443 | 26 |
    | `/music/?genres=<root>` | 439 | 16 |
    | `/music/artists/` | 305 | 6 |
    | `/music/artists/?append=true` | 205 | 6 |
    | `/api/music/all/` | **1218** | 10 |

    Both N+1s were as the roadmap described, with two corrections worth
    keeping:

    - **The 418 genre selects were not a cache-miss cost.** Only the flat
      `.values()` list is cached; `genre_tree_options()` and the facet
      `_genre_counts()` were never cached, so every request paid all 418.
    - **`/api/music/all/` was worse than any page and went unrecorded**: the
      album loop read `album.thumbnail` while the queryset prefetched only
      `artists` and `genres`, so all 1000 albums lazy-loaded their
      MusicBrainz row. One `select_related`.

    `core/services/genre_tree.py` now answers the whole hierarchy in one
    query, and `ArtistListView` carries a `Prefetch`. Output is
    byte-identical across eleven pages, so no `SCHEMA_VERSION` bump. See
    DEVLOG.md and AGENTS.md, "Music query budgets".

    Left for whoever is next in these files:

    - **`games/api/views.py:753-801` still has its own hand-rolled copy** of
      the descendant walk, and `games/models.py:411-445` caches descendant
      ids per genre with signal invalidation to work around the per-instance
      walk being its hot path. Both can now fold onto the shared helper.
      `books/api/views.py:489` has the identical N+1, unfixed - books is
      deprioritized.
    - **`/` (games home) issues 75 `games_wikipediagenre` selects** of its
      own, inside its 112. Smaller than music's was and not measured
      further.
    - ~~**Mobile Load More on `/music/artists/` appends into the wrong
      container.**~~ Fixed 2026-10-18, along with a second bug in the same
      button: it removed itself after its request and no response sent a
      new one, so only page 2 could ever be loaded, on any width. The append
      response now wraps its rows in a table that `hx-select` lifts the
      `<tr>`s out of, and sends the mobile cards, the loaded count and the
      next button out of band.

## Housekeeping

12. ~~**A POST to any `/music/` URL answers 403, not 404.**~~ Fixed
    2026-10-18 with a `CSRF_FAILURE_VIEW` (`core.views.csrf_failure`) that
    404s a failed check under `/music/` for anyone but staff. The tests use
    `Client(enforce_csrf_checks=True)`, so they now see the production
    answer.

9. `FORUM_ENABLED` is still set as a Heroku config var; the forum was removed
   in 2026-10-17. `MEDIA_URL` / `MEDIA_ROOT` have no consumer either.
10. `.git/hooks/pre-commit.legacy` runs `manage.py test games.tests` on every
    commit, on top of pytest. It has earned its keep - it caught a cache
    isolation bug pytest's conftest hid - but it is undocumented and roughly
    doubles commit time.

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
