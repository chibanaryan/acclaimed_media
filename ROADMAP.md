# Roadmap

What is left, why it matters, and what it costs. Ordered within each group.
`DEVLOG.md` records what has shipped; this file records what has not.

## Music: before it can launch publicly

1. **Nav entry and a `MUSIC_ENABLED` flag.** Today the only gate is
   `StaffOnlyMixin` raising 404 and the absence of any link. A flag gives a
   kill switch independent of staff status. ~2 hours.
2. **Discogs attribution terms.** Needs a human: their docs 403 automated
   fetches. Genres and styles come from Discogs, so the terms decide what the
   site has to display.
3. **Decide whether music gets SEO landing pages.** Games has
   `/games/<genre>/` and `/games/<decade>/`, crawlable and self-canonical,
   built from the same filter machinery. Music could, now that it shares the
   filters - but only once the section is public.

## Data pipeline

4. **Set `DISCOGS_TOKEN` on Heroku.** The metadata refresh is paced by the
   anonymous Discogs tier at 25 requests a minute, which is ~40 minutes for
   1000 albums. A token raises the ceiling and the client paces itself from
   the response headers either way.
5. **Schedule the music metadata refresh.** Games has a weekly refresh on the
   scheduler addon; music is run by hand. An import does not trigger it (on
   either section), which is now visible on the music import page.
6. **The MusicBrainz pass is opt-in and has never run on the new release.**
   `--musicbrainz` fills genres for the albums with no Discogs master - three
   of them in the previous release, unknown in this one.

## Production memory

The web dyno is back inside its 512 MB quota with two workers, and the
rankings page is down from 1.4 MB of HTML to 870 KB (1.32 MB logged in). See
AGENTS.md, "Production memory budget". What is left, in the order the
measurements favour:

7. **The server-rendered grid**: 100 `_game_card_grid.html` cards, about
   160 KB, hidden unless grid view is on. Dropping them needs a client render
   whenever grid mode is chosen before the client-side filtering bundle has
   loaded, including `gameViewMode === 'grid'` in localStorage on first
   paint. Scroll-to-rank (`utils-loadmore.js`) and the append path read them
   too.
8. **Inline `onclick`s** on every platform and genre span, about 54 KB,
   could become one delegated listener.
9. **One played button per game** rather than a desktop and a mobile copy:
   up to ~300 KB logged in.
10. **Then `--worker-class gthread`** for concurrency without a third heap,
    then Standard-2X (1 GB, $50/mo vs Basic's $7).

## Housekeeping

11. `FORUM_ENABLED` is still set as a Heroku config var; the forum was removed
    in 2026-10-17. `MEDIA_URL` / `MEDIA_ROOT` have no consumer either.
12. `.git/hooks/pre-commit.legacy` runs `manage.py test games.tests` on every
    commit, on top of pytest. It has earned its keep - it caught a cache
    isolation bug pytest's conftest hid - but it is undocumented and roughly
    doubles commit time.
13. `books/api/views.py:489` has the genre-descendant N+1 that music and
    games no longer do (`core/services/genre_tree.py` is the fix) - unfixed
    because books is deprioritized.

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
