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
   results there, and file what fails here. The search boxes became
   comboboxes on 2026-11-10 and were checked the same way, by keyboard and
   against Chrome's accessibility tree: rows 1.11-1.17, 2.10 and 3.6 are
   theirs. A combobox that reads wrongly is worse than the field and links
   it replaced, so if those rows fail, revert that one commit ("The search
   boxes are comboboxes") rather than patch it unheard.

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
   - The read button's partial ships a `<script>` with every row
     (`_read_button.html`); games' copy sends it only with a toggle's answer.

   Its server side was gone over on 2026-11-10 (`DEVLOG.md`). Left there:
   the Goodreads import runs two to four queries a row inside one request,
   and the Open Library and Hardcover clients retry on a flat one-second
   sleep and never on a 5xx, where music's `RateLimitedClient` backs off.

## Open bugs (found 2026-11-10)

The third pass that day fixed what the second had filed here (the HLTB
platform preference, the developers list's direction, undated items, music's
"all loaded" line, the games API's keys, a failed Back followed by the
engine, the accessibility leftovers, the unsubscribe page's `noindex`, and
most of the small leftovers; `DEVLOG.md`). Left, or found by it:

4. **An article's featured image has no box before it loads**, so the text
   below jumps. Only its URL is stored. A 16:9 crop was tried on 2026-11-10
   and reverted: there were no articles locally to check a crop against.
   Store the dimensions, or pick the crop looking at the real images.
5. **The games rankings' list query is the one piece of per-request work
   worth a look.** The three pieces filed here as unmeasured were timed on
   2026-11-10 against a local copy of production's data (SQLite, shared
   caches warm, the whole-page cache emptied for each run, median of six):

   | Page | Time | Queries | In SQL |
   |---|---|---|---|
   | `/developers/` | 65 ms | 4 | 3 ms |
   | `/developers/?page=2&append=true` | 47 ms | 4 | 2 ms |
   | music `/` | 285 ms | 14 | 29 ms |
   | games `/` | 242 ms | 15 | 120 ms |

   None of the three is the cost it was feared to be: the developers list
   is cheap, the album rankings' genre pairs do not show among its queries,
   and the HLTB totals aggregate takes 1 ms. What does show is games' main
   list query, 109 ms of the 120: `SELECT DISTINCT` over every column of
   every game, joined to the list memberships and grouped for
   `COUNT(DISTINCT listmembership.id)`, before the first 100 are taken. A
   correlated subquery for `list_count`, or dropping the `DISTINCT` the
   `GROUP BY` already makes redundant, would narrow it. Not changed: it
   is the query the parity tests order by, the numbers are SQLite's, and
   production's Postgres may plan it differently. Time it there
   (`EXPLAIN ANALYZE` from a one-off dyno) before touching it. The rest of
   each page's time is template rendering, which the page cache answers.
6. **A failed Back, then a failed change, with no engine.** A Back whose
   render fails leaves the old list under the new address, and the engine
   now renders the address's list when it arrives. With the engine's data
   failed too, a control's change that also fails is left in the controls,
   which then match neither the list nor the address
   (`_rollBackIfStranded` returns early while `_listBehindAddress` is set).
   Three failures in a row, in the function that has cost the most review
   rounds; the fix would be to read the controls back from the address.
7. **Three name-searched games hold an HLTB entry a search no longer
   gives.** The 2026-11-10 comparison searched HLTB for the 88 games with
   no usable Wikidata HLTB id. Beside Wordle, which the platform preference
   corrects, three differ from what is stored whether or not the
   preference runs, so the weekly job will move them: Call of Duty: Modern
   Warfare 2 (stored entry 109060, 8.2 h; a search gives 1477, 6.6 h),
   Puyo Puyo (83379, 0.5 h; 9411, 1.2 h) and "Bomberman / Atomic Punk /
   Dynablaster" (1230, 2.4 h; 1244, which is Bomberman II, 2.0 h). The
   last is a wrong match by name. Giving each its HLTB id on Wikidata
   (P2816) settles it for good, since an id is looked up before any name.
8. **Small leftovers.**
    - `populate_platform_years` has no caller; `games/platform_years.py`
      keeps it "for re-applying the whole table after editing it".
    - The games import's "Load Test Data" is hidden without `DEBUG` but
      accepted by the server. It loads the checked-in release, as
      `import_games_data` does, so it was left.
    - The three progress streams in `games/services/import_handler.py`
      (IGDB, Wikipedia, the batch) each carry a copy of the queue and the
      drain loop with its keepalives. The batch's import loop is one now.
    - The four search boxes (two in `_sidebar.html`, two in
      `_nav_mobile.html`) each carry a copy of the combobox's attributes
      and roles, as they each carried a copy of the box before. One include,
      in the style of `core/includes/_search_box.html`, would hold it once.
    - Music's takeover runs in `csf.init().then(...)` with no `catch`. One
      that only logged would turn an uncaught error, which the smoke test
      fails on, into a console line it does not see; one that did more
      would have to decide what a half-finished takeover leaves.
    - Staff-written markdown (flat pages, articles, posts) is rendered and
      marked safe unsanitized. Fine while only staff write it.
    - `PlayedGame`, `WantToPlayGame` and `SavedFilterSet` re-declare the
      fields of `core.models.UserTrackingBase` and `SavedFilterSetBase`,
      which music and books subclass.
    - `base.html` and `_nav_mobile.html` carry about 400 lines of inline
      script on every page, which a static file would let a browser keep.
      Unmeasured.
    - The 100% coverage gate omits every management command and both
      `import_handler.py` modules, about 7,700 lines: the scheduled jobs
      and the import pipelines. Each has tests; none of it is measured.

## Open bugs (found 2026-11-11)

The fourth pass (`DEVLOG.md`) fixed resending a verification (bug 8 as was)
and four of the small leftovers. Found by its audits and left:

9. **Nothing stores IGDB's summary.** Every fetch asks IGDB for `summary`
   and `storyline` and drops them, so a game page's meta description and
   JSON-LD use one stock sentence for every game. A `summary` field on
   `IGDBGameData`, filled by the fetch and read by the page, would give
   each its own; it needs a migration and a forced IGDB pass to fill.
10. **The platform group ids (`mfr-nintendo`, `ff-handheld`) are reachable
    only by hand.** No script writes one, but the server filters by them:
    the heading then names the raw id ("Most Acclaimed mfr-nintendo
    Games"), the engine does not know them, and the CSV's file name
    expands them where the heading does not. Remove them, or make all three
    agree (`games/services/game_filters.py`).
11. **The source-lists total ignores the search in one of its two modes**
    (`games/views/lists.py`): grouped by publication, "of Y lists" counts
    every list; grouped by type it counts the matches.
12. **A reversed year range** (`?start=2000&end=1990`, hand-written) lists
    nothing, on both sides, under a heading reading "2000-1990". Swapping
    it would have to happen in the server's filter and the engine's alike.
13. **Smaller, found and left.**
    - Music's server Load More (before the engine) replaces its button out
      of band, and focus falls to the top of the page; the engine's keeps
      it since this pass (`replaceKeepingFocus`).
    - `ALLOWED_HOSTS` keeps `localhost` and `127.0.0.1` in production;
      nothing exploitable was found.
    - `USE_TZ = False`: every datetime is naive, correct only because
      `TIME_ZONE` is UTC. Turning it on is a migration project.
    - The music rate-limited client paces itself by the wall clock and
      backs off a fixed 1 s / 2 s on a 429 or 503, ignoring `Retry-After`.
    - Recursive genre helpers (`MusicGenre.get_descendants`,
      `WikipediaGenre.get_ancestors`, ...) are kept for one-off use and are
      a query a node; nothing on a request path calls them.
    - The four search boxes still carry a copy each of the combobox markup
      (bug 8's list).
    - An album's release-group MBID (Wikidata P436) is stored as Wikidata
      gives it: unlike an artist's (P434, since this pass), it is not
      checked to be a UUID, so a malformed one replaces a good one and the
      cover pass asks the archive for a group that does not exist.
    - **Changing an account's email in the admin leaves allauth's address
      rows behind.** The old row stays, often primary, and allauth's
      password reset matches any row: whoever holds the old address can
      still reset the password. The new address gets no row, so the login
      says unverified and the modal can only point to the contact form. The
      admin also writes addresses with their capitals, where allauth
      compares lower-case ones, so a mixed-case row escapes its
      one-verified-account rule. The admin's save should sync the rows
      (allauth's `sync_user_email_addresses`, lower-cased, the new address
      primary once confirmed, the old dropped), and staff be told. Six
      review rounds on 2026-11-11 tried repairing the rows from the resend
      instead and kept finding edges; it was taken out.
    - A metadata pass's per-album savepoint spans the album's network
      requests, so a cover pass walking a group's releases at 1 req/s holds
      a connection idle in a transaction, and the album's row lock, for tens
      of seconds. Fetching first and saving in the savepoint would end it.

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

The third 2026-11-10 pass adds no migration. It shipped on 2026-11-11 (v921), after four
review rounds. Items 22 to 25 below are what to check now that it has.

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
    `ANON_RENDER_BUDGET_PER_SECOND` or `_BURST` first. A request that says
    it is a script's (`HX-Request`) is not counted, so a scraper that learnt
    to send the header would pass it; `?partial=true` on its own no longer
    does.
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

22. **The first Sunday after it ships, read both weekly jobs.**
    `fetch_album_metadata` now fails when its Wikidata pass lands nothing,
    so Sentry's cron monitor will alert on an outage it has been reading as
    a good Sunday. Games' Wikipedia phase now sends the credentials it paces
    itself by: it should run with no 429s where it may have been throttled,
    and its timeout is 30 seconds, so a stalled page is a logged failure,
    not a five-minute wait. The HLTB phase will move Wordle and the three
    games in bug 7.
23. **The games API's old cache rows lapse by themselves.** Its keys
    changed shape (`games_api:...`); the rows Django's `cache_page` wrote
    (`views.decorators.cache...`) are never read again and expire within a
    day. Nothing to clear.
24. **`/accounts/signup/` redirects to the modal's sign-up screen.** Check production once for
    accounts whose username contains `@` and is not their own email
    (`User.objects.filter(username__contains="@").exclude(username=F("email"))`):
    each is a name taken through the old page, and may be squatting
    another person's address.
25. **Run the search rows of the assistive-tech checklist** (bug 1) on the
    deployed site, since production is where a screen reader is easiest to
    point.

26. **After the fourth pass ships, check one sign-up end to end.** The
    confirmation link now logs in only the browser that signed up: sign up
    in one browser, open the link there (logged in), and in another
    (verified, with a Log In button). Then read one Sentry event from a
    form post and confirm `password1` is filtered.
27. **The first Sunday after it, read the music job's errors.** An album's
    failure in the cover, Discogs or MusicBrainz pass is now an error line
    and the pass goes on, where it ended the run; a pass that logs many is
    a source down, not many bad albums.

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
