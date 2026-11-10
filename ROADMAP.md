# Roadmap

What is left, why it matters, and what it costs. Ordered within each group.
`DEVLOG.md` records what has shipped; this file records what has not.

## Open bugs (found 2026-11-01)

Found while shipping v905's filter-engine work and the music metadata refresh
that followed. Four more from the same list were fixed on 2026-11-02, and
the three held back that day on 2026-11-03 (`DEVLOG.md`). The five older
bugs the 2026-11-03 reviews turned up were fixed the same day, and the two
filed then (the entity pages' Load More, an engine on a payload of another
version) later that day, as were the metadata fetch's restart edges filed
that evening.
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

## Open bugs (found 2026-11-09)

The IGDB lookups, the post notification's unsubscribe link, the games
filters' roll-back and music's remaining stale spells, filed here that day,
were fixed on 2026-11-10 (`DEVLOG.md`).

3. **Books' client code**, if the section is ever picked up (see "Explicitly
   not doing"). `book_detail.html` nests its head blocks in `content` as
   album detail did, and its scripts read storage unguarded. Found
   2026-11-10 and left with it:
   - The sort dropdown calls `updateSort()`, which nothing defines, and the
     direction flip and the jump box are inert (`_book_list_results.html`).
   - `books/home.html` ships the client-side filtering bundle and three
     `<template>`s that nothing starts (`getBookClientSideFiltering` has no
     caller), and its mobile renderer writes to slots the template lacks.
   - The mobile row's title is no link, the read button has no name, and
     every `mdi-book-*` icon is undefined, so the button renders as nothing.
   - `_book_genre_filter.html` is included nowhere.

## Open bugs (found 2026-11-10)

Found by the second improvement pass and left: each is older than the pass,
and either changes what a job matches or needs measuring first.

4. **HowLongToBeat's platform preference never runs.** `fetch_hltb_data` and
   `refresh_all_metadata` read `result.profile_platform`, but
   howlongtobeatpy's entry has `profile_platforms`, a list, so the `hasattr`
   is always false. `platform_matches` would raise on a list if reached,
   matches alias keys as substrings ("PlayStation" matches "PlayStation 4",
   "NES" matches "SNES") and does not know the site's own names ("PC"
   against "Windows PC", "Wii" against "Nintendo Wii"). Two expected
   failures in `games/tests/test_hltb_matching.py` state the right
   behaviour. Fixing it changes which entry some games are given, so
   compare the playtimes before and after on a copy of production.
5. **The developers list's direction is inverted for counts.**
   `/developers/?sort=games`, labelled "Asc", lists the most games first,
   and `&dir=desc` the fewest; the same for `sort=studios`. Rank and name
   read correctly. The two tests are named for what happens
   (`games/tests/test_main_views.py`).
6. **Undated items, the rest.** An undated game's year link goes to
   `?start=None&end=None` from the server and `?start=null&end=null` from
   the renderer, and an undated album's desktop row prints "()" on both
   sides. The descriptions, headings and mobile rows were fixed.
7. **Music's "all loaded" state differs.** The server prints "All N results
   loaded"; `album-client-filtering.js` removes the container.
8. **The games API cache's keys still vary on `Accept`.** A query string no
   longer makes a key (`games.api.views.cache_page`), but Django's
   `cache_page` keys on the `Vary` headers too, and a caller writes those.
   Closing it means keying on the path alone and storing the JSON ourselves.
9. **Accessibility, the rest** (beside bug 1's real-device pass):
   - The search boxes have labels but no combobox semantics (`role`,
     `aria-expanded`, `aria-controls`, arrow keys).
   - `text-base-content/50` remains on the auth partials' fine print,
     "(optional)" and its hint in `_signup_form.html`, "No file selected" on
     the import page, `_mobile_filter_sheet.html` and
     `_mobile_saved_filters.html` (one line each).
   - On the server path a reader that does read an inserted `role="status"`
     hears the count twice: once there, once from `#live-announcer`.
   - `filter-component.js` adds document-level listeners (around its
     `init()`) that `destroy()` does not remove.
10. **An article's featured image has no box before it loads**, so the text
    below jumps. Only its URL is stored. A 16:9 crop was tried on 2026-11-10
    and reverted: there were no articles locally to check a crop against.
    Store the dimensions, or pick the crop looking at the real images.
11. **Per-request work nothing has measured.** The developers list loads
    and prefetches every developer on each request and each Load More
    (`games/views/developers.py`), the album rankings read every album's
    genre pairs on every render (`music/views.py`), and the games rankings
    run the HLTB totals aggregate on every render. Measure before caching:
    each cached value spends from the 512 MB budget and needs dropping.
12. **The unsubscribe page's canonical link carries the token.** `base.html`
    has no robots block to say `noindex` with. The address is in no page,
    only in the email.
13. **Small leftovers.**
    - `_refresh_wikipedia` in `refresh_all_metadata.py` is dead: only
      `_refresh_wikipedia_async` is called.
    - Nothing dispatches `reset-search-state` (four listeners).
    - `RateLimitedClient.get_bytes` reads a cover's whole body before
      `COVER_MAX_BYTES` is checked, so the ceiling bounds what is stored,
      not what a download can cost a worker. Streaming it means reading
      inside the retry loop's `try`, and closing what is not read.
    - `populate_platform_years` has no caller; `games/platform_years.py`
      keeps it "for re-applying the whole table after editing it".
    - `test_progress_callback_with_event_key` (`games/tests/test_imports.py`)
      asserts nothing about the callback it exercises.
    - `games/static/games/css/mdi-subset.css` lacks 43 of `base.html`'s
      icon mappings. The font is unaffected: the build reads both files.
    - The games import's "Load Test Data" is hidden without `DEBUG` but
      accepted by the server. It loads the checked-in release, as
      `import_games_data` does, so it was left.
    - The shared venv has no `fonttools`, which the dev lock pins: run
      `pip install -r requirements-dev.txt` in the main checkout before
      rebuilding the icon font.

## Music: after launch

The section is public at `music.acclaimedmedia.org`, beside the games site and
a landing page at the apex (2026-10-30; AGENTS.md, "Domain"). The pages keep a
"Beta" badge while `music.config.MUSIC_BETA` is on.

14. **New brand artwork.** The favicons still read "Acclaimed Video Games"
   (`games/static/games/brand/`), and a page without artwork of its own has
   no `og:image` since the old one was removed; every page title already
   says Acclaimed Media. A new default goes in `base.html`'s `og_image` block,
   and the five templates overriding that block need a `{{ block.super }}`
   branch for items with no art.

## Production: after the 2026-11-09 and 2026-11-10 passes ship

The rankings page is 690 KB anonymous and 833 KB logged in, and the dyno
runs gthread with three threads per worker (AGENTS.md, "Production memory
budget"). `--threads 3` was checked on 2026-11-09: over 72 hours the two
workers peaked at 333 MiB RSS of the 512 MiB quota and swap was 0 but for
one 6.9 MiB reading, so it stays.

15. **Watch the two burst windows after the deploy.** A scraper asks for
   3,500-4,800 filtered pages in five minutes at about 04:00 and 21:00 UTC,
   and Sentry's uptime check timed out 11 times in the week to 2026-11-09
   (AGENTS.md, "Caching"). After the deploy, read the uptime monitor across
   the next two windows, `/`'s p50 inside them, and `heroku logs` for
   "Autorestarting worker" during one.
16. **Read a week of render-budget reports, then decide on
    `ANON_RENDER_BUDGET_ENFORCE`.** The budget only logs: "Anonymous renders
    over budget", at 10 in a burst (WARNING, the logs) and 100 and 1,000
    (ERROR, Sentry). If the only bursts are the scraper's windows, turn it
    on; if ordinary traffic reaches 100, raise
    `ANON_RENDER_BUDGET_PER_SECOND` or `_BURST` first. HTMX partials are not
    counted, so a scraper that learnt to send `HX-Request` would pass it.
17. **Check memory under `--max-requests 2000`.** It was 500 until
    2026-11-09, and memory was measured flat only to 1,000 renders. The page
    cache also holds ~200 more pages, ~12 MB a worker. After a few days read
    `memory.rss.bytes.max` and `memory.swap.bytes.max` from the metrics API;
    back to 1,000 if the peak climbs towards the quota. An import's metadata
    fetch spends ~85 MB in one worker while it runs, so read a week that
    held one.
18. **Merge the Dependabot queue.** #32 is Django 6.1.3, a security release;
    #31 and #30 wait with it. #32 and #31 were green on 2026-11-10
    (`/upgrade-deps`).
19. **The next deploy applies two migrations**, `games.0124` and
    `music.0015`: unique constraints on game, developer and album slugs
    and on game and developer IGDB ids. Production had no duplicates on
    2026-11-10; if a release imported since then has one, the release
    phase fails on it and names the constraint. `/deploy` backs up first.
20. **The first Sunday after the deploy, read the weekly games job.**
    `refresh_all_metadata` now fails when a phase could not run at all, so
    Sentry's cron monitor will alert on a phase that has been failing
    quietly. The job's output names the phase.
21. **Check one notification email's headers** once a post goes out: Gmail
    and Apple Mail should show their own Unsubscribe control
    (`List-Unsubscribe-Post`), and the footer link should ask before it
    unsubscribes.

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
