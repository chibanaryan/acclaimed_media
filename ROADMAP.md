# Roadmap

What is left, why it matters, and what it costs. Ordered within each group.
`DEVLOG.md` records what has shipped; this file records what has not.

## Music: launch

1. **Set `MUSIC_ENABLED=true` on Heroku.** That is the launch: reads go
   public, the media switcher and mobile nav gain a Music entry, and the
   sitemap gains the albums, artists and the `/music/genres/<slug>/` and
   `/music/<decade>s/` landing pages. Everything it needs is built, including
   Discogs' attribution (AGENTS.md, "Discogs API terms"). Unsetting it hides
   the section again.
2. **An anonymous page cache for music**, once it is public. Games' rankings
   and landing pages use `AnonymousResponseCacheMixin`; music's have none.
   It must sit after `MusicVisibleMixin` in the MRO, and every cached page
   spends from the 512 MB budget, so measure before adding it.

## Production memory

The rankings page is 690 KB anonymous and 833 KB logged in, and the dyno
runs gthread with two threads per worker (AGENTS.md, "Production memory
budget").

3. **Measure gthread on the dyno.** `memory.rss.bytes.max` and swap over a
   day of traffic decide whether `--threads 3` fits, or whether the next
   step is Standard-2X (1 GB, $50/mo vs Basic's $7).

## Housekeeping

4. `BOOKS_ENABLED` is two flags that never meet: the setting is read by
   nothing, and `games.context_processors.feature_flags` reads the raw env
   var instead. `MUSIC_ENABLED` is the working pattern to copy.

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
