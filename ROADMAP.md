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

## Music genres

4. **Classify the 105 MusicBrainz labels the vocabulary does not know.** The
   first MusicBrainz pass (2026-10-18) brought them in; until each is a
   leaf, an alias, a root or a dropped label in
   `music/services/genre_normalizer.py`, it adds nothing. The big ones are
   `progressive` (18 albums), `pop soul` (14), `ambient pop` (13),
   `piano rock` and `alternative pop` (10 each). The list is
   `heroku run -- python manage.py rebuild_album_genres --dry-run --report`.

## Production memory

Items 5-8 of the previous roadmap shipped on 2026-10-18 (see DEVLOG.md):
the rankings page is 690 KB anonymous and 833 KB logged in, and the dyno
runs gthread with two threads per worker. What is left:

5. **Measure gthread on the dyno.** `memory.rss.bytes.max` and swap over a
   day of traffic decide whether `--threads 3` fits, or whether the next
   step is Standard-2X (1 GB, $50/mo vs Basic's $7).

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
