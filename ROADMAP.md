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

The browser harnesses used for v905 (`matrix.js`, `musicrace.js`,
`loadmore.js`, `round8.js`-`round10.js`, and `xbrowser.js` for WebKit and
Firefox) were in the ashgabat worktree's `.context/ygrid/`, which is
gitignored: that worktree is gone, and they with it. What they checked in
Chrome is in `scripts/browser_smoke.js`; nothing here runs WebKit or Firefox.

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
5. **The games rankings' list query, on production.** It was the one
   piece of per-request work worth a look: 109 ms of the page's 120 ms of
   SQL (measured 2026-11-10 on SQLite), a `SELECT DISTINCT` over every
   column of every game, joined to the list memberships and grouped for
   their count. Since 2026-11-12 `list_count` is a subquery a row and the
   sort adds no `DISTINCT` (`DEVLOG.md`): on the local copy of production's
   data the first hundred rows with their prefetches went from 124 ms to
   17.5 ms on SQLite and from 54 ms to 20 ms on Postgres 15. Two things are
   left. Production is Postgres 18 on other hardware, and was not measured:
   read `/`'s p50 across a deploy (item 26). And a list filtered by genre,
   platform or series still carries the `DISTINCT` its many-to-many join
   needs (46 ms to 30 ms with two platforms, so less of a gain); an
   `Exists` in place of each join would end it, in three functions that
   the facet counts, the API's list and the landing pages share.
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
    - The 100% coverage gate leaves out five games files that have tests
      and fall short of it, each by name in `.coveragerc` (measured
      2026-11-12): `refresh_all_metadata` 62%, `games/services/
      import_handler.py` 68%, `get_wiki_genres` 70%, `fetch_hltb_data` 80%,
      `fetch_wikipedia_metadata` 81%. Mostly the async fetch loops and the
      three progress streams. The books command has no tests at all.

## Open bugs (found 2026-11-11)

The fourth pass (`DEVLOG.md`) fixed resending a verification (bug 8 as was)
and four of the small leftovers. The fifth, on 2026-11-12, fixed the
platform group ids, the source-lists total, the reversed year range, the
server Load More's focus, the release-group MBID check and the admin's
email rows (bugs 10 to 12 as were, and three of 13's). Found by the fourth
pass's audits and left:

9. **Nothing stores IGDB's summary.** Every fetch asks IGDB for `summary`
   and `storyline` and drops them, so a game page's meta description and
   JSON-LD use one stock sentence for every game. A `summary` field on
   `IGDBGameData`, filled by the fetch and read by the page, would give
   each its own; it needs a migration and a forced IGDB pass to fill.
10. **Smaller, found and left.**
    - `ALLOWED_HOSTS` keeps `localhost` and `127.0.0.1` in production;
      nothing exploitable was found.
    - `USE_TZ = False`: every datetime is naive, correct only because
      `TIME_ZONE` is UTC. Turning it on is a migration project.
    - The music rate-limited client paces itself by the wall clock and
      backs off a fixed 1 s / 2 s on a 429 or 503, ignoring `Retry-After`.
      Honouring it was tried on 2026-11-12 and taken out at its second
      review round. What an implementation has to get right: a service that
      is down says so to every request, so the waits need a ceiling a pass
      and not only a wait (a thousand records at two minutes apiece hold
      the metadata lock for a day and a half); that ceiling has to refill
      on a success, or a long pass with the odd honest throttle stops
      honouring them; `float("nan")` parses, and `time.sleep` refuses it,
      out of methods documented never to raise; and the cover pass shares
      one client between two threads.
    - Recursive genre helpers (`MusicGenre.get_descendants`,
      `WikipediaGenre.get_ancestors`, ...) are kept for one-off use and are
      a query a node; nothing on a request path calls them.
    - The four search boxes still carry a copy each of the combobox markup
      (bug 8's list).
    - A metadata pass's per-album savepoint spans the album's network
      requests, so a cover pass walking a group's releases at 1 req/s holds
      a connection idle in a transaction, and the album's row lock, for tens
      of seconds. Fetching first and saving in the savepoint would end it.

## Open bugs (found 2026-11-12)

The fifth pass (`DEVLOG.md`). Its surveys found little that a reader could
reach, which is its own finding: a crawl of all 3,633 sitemap URLs on a copy
of production's data returned no error, and eslint and ruff's bug rules
found nothing to fix. What it found and left:

11. **Found and left.**
    - **The year grid's labels on its warmer tiles, in the dark theme.**
      axe-core measured the label (`#e4e4e7`) at 2.9:1 to 4.4:1 on the
      heatmap's mid and high colours (`#b0792d`, `#a4712b`, `#886029`): 85
      tiles on the two rankings pages of the smoke data. A darker label on
      a warm tile, or a lighter one's shadow, would fix it; the grid's fade
      is the CSS that cost the most frames to get right (AGENTS.md, "A
      selected year range reads as one shape"), so look at real frames.
    - **Three names that do not hold their label word for word** (WCAG
      2.5.3, for someone driving the page by voice): a year cell reads "10"
      and is named "2010, 12 albums"; the sort's direction reads "Desc" and
      is named "Descending order: switch to ascending"; the games mobile
      bar's Music icon reads "Beta" and is named "Music (beta)".
    - **Sign-up with an email over 150 characters** sets the username to
      it (`ModalAccountAdapter.populate_username`), which the column does
      not hold: a `DataError` on Postgres. The profile form refuses one
      since this pass; the adapter should fall back to allauth's generated
      name, as it does for a name that breaks the rules.
    - **`post_import.payload_fingerprint` calls the API view's own
      `_payload`**, through a lazy import. If that method came to read its
      request, the fingerprint would be None every week and the version
      would move every Sunday, which the tests would catch
      (`RefreshMovesTheDataVersionTests`). Moving the payload's builder
      into `games/services` for the view and the job to share would end
      the coupling.
    - **Album detail's two `COUNT`s** (albums of its year, of its decade)
      were to read the cached year baseline. Left: the shared cache is a
      Postgres table in production, so the read costs the query it saves.
    - **The shared venv has django-allauth 65.20.1**, where the lock pins
      65.21.0 (2026-11-12). CI installs the lock; a local run does not test
      what ships until `pip install -r requirements.txt -r
      requirements-dev.txt` is run in the main checkout.
    - `scripts/setup_worktree.sh` runs under `set -e` alone. `-u` needs
      `${CLAUDE_PROJECT_DIR:-}` and `${CLAUDE_ENV_FILE:-}`, and care with
      an empty array under macOS's bash 3.2; it runs at every session's
      start, so it was left.
    - `games/utils.py` re-exports six names only tests read; their patches
      could name the service modules.
    - **Two `theme` cookies the toggle cannot reach still win where they
      exist**, neither of which this site writes: one with a longer path
      than `/` (another app on a shared address such as `127.0.0.1`), and a
      host's own on a site other than the one the toggle was used on. And
      on an address the cookie is named `theme`, which another local app
      may use. A name of our own (`am_theme`, as the session's is) would
      end all three, at one reset of every reader's choice across sites.

## Music: after launch

The section is public at `music.acclaimedmedia.org`, beside the games site and
a landing page at the apex (2026-10-30; AGENTS.md, "Domain"). The pages keep a
"Beta" badge while `music.config.MUSIC_BETA` is on.

12. **New brand artwork.** The favicons still read "Acclaimed Video Games"
   (`games/static/games/brand/`), and a page without artwork of its own has
   no `og:image` since the old one was removed; every page title already
   says Acclaimed Media. A new default goes in `base.html`'s `og_image` block,
   and the five templates overriding that block need a `{{ block.super }}`
   branch for items with no art.

## Production: after the 2026-11-09 and 2026-11-10 passes ship

The third 2026-11-10 pass adds no migration. It shipped on 2026-11-11 (v921), after four
review rounds. Items 20 to 23 below are what to check now that it has.

The rankings page is 690 KB anonymous and 833 KB logged in, and the dyno
runs gthread with three threads per worker (AGENTS.md, "Production memory
budget"). `--threads 3` was checked on 2026-11-09: over 72 hours the two
workers peaked at 333 MiB RSS of the 512 MiB quota and swap was 0 but for
one 6.9 MiB reading, so it stays.

13. **Watch the two burst windows after the deploy.** A scraper asks for
   3,500-4,800 filtered pages in five minutes at about 04:00 and 21:00 UTC,
   and Sentry's uptime check timed out 11 times in the week to 2026-11-09
   (AGENTS.md, "Caching"). After the deploy, read the uptime monitor across
   the next two windows, `/`'s p50 inside them, and `heroku logs` for
   "Autorestarting worker" during one.
14. **Read a week of render-budget reports, then decide on
    `ANON_RENDER_BUDGET_ENFORCE`.** The budget only logs: "Anonymous renders
    over budget", at 10 in a burst (WARNING, the logs) and 100 and 1,000
    (ERROR, Sentry). If the only bursts are the scraper's windows, turn it
    on; if ordinary traffic reaches 100, raise
    `ANON_RENDER_BUDGET_PER_SECOND` or `_BURST` first. A request that says
    it is a script's (`HX-Request`) is not counted, so a scraper that learnt
    to send the header would pass it; `?partial=true` on its own no longer
    does.
15. **Check memory under `--max-requests 2000`.** It was 500 until
    2026-11-09, and memory was measured flat only to 1,000 renders. The page
    cache also holds ~200 more pages, ~12 MB a worker. After a few days read
    `memory.rss.bytes.max` and `memory.swap.bytes.max` from the metrics API;
    back to 1,000 if the peak climbs towards the quota. An import's metadata
    fetch spends ~85 MB in one worker while it runs, so read a week that
    held one.
16. **Merge the rest of the Dependabot queue.** #32, Django 6.1.3, a
    security release, was merged on 2026-11-12 and shipped with the fifth
    pass. #31 (five Python minor and patch bumps) was green that day and
    waits. #30 (npm) fails `audit`, `css` and `browser`, so it needs its
    CSS rebuilt and read; it will also want rebasing over the fifth pass,
    which took two PostCSS plugins out of `package.json`.
17. **The next deploy applies two migrations**, `games.0124` and
    `music.0015`: unique constraints on game, developer and album slugs
    and on game and developer IGDB ids. Production had no duplicates on
    2026-11-10; if a release imported since then has one, the release
    phase fails on it and names the constraint. `/deploy` backs up first.
18. **The first Sunday after the deploy, read the weekly games job.**
    `refresh_all_metadata` now fails when a phase could not run at all, so
    Sentry's cron monitor will alert on a phase that has been failing
    quietly. The job's output names the phase.
19. **Check one notification email's headers** once a post goes out: Gmail
    and Apple Mail should show their own Unsubscribe control
    (`List-Unsubscribe-Post`), and the footer link should ask before it
    unsubscribes.

20. **The first Sunday after it ships, read both weekly jobs.**
    `fetch_album_metadata` now fails when its Wikidata pass lands nothing,
    so Sentry's cron monitor will alert on an outage it has been reading as
    a good Sunday. Games' Wikipedia phase now sends the credentials it paces
    itself by: it should run with no 429s where it may have been throttled,
    and its timeout is 30 seconds, so a stalled page is a logged failure,
    not a five-minute wait. The HLTB phase will move Wordle and the three
    games in bug 7.
21. **The games API's old cache rows lapse by themselves.** Its keys
    changed shape (`games_api:...`); the rows Django's `cache_page` wrote
    (`views.decorators.cache...`) are never read again and expire within a
    day. Nothing to clear.
22. **`/accounts/signup/` redirects to the modal's sign-up screen.** Check production once for
    accounts whose username contains `@` and is not their own email
    (`User.objects.filter(username__contains="@").exclude(username=F("email"))`):
    each is a name taken through the old page, and may be squatting
    another person's address.
23. **Run the search rows of the assistive-tech checklist** (bug 1) on the
    deployed site, since production is where a screen reader is easiest to
    point.

24. **After the fourth pass ships, check one sign-up end to end.** The
    confirmation link now logs in only the browser that signed up: sign up
    in one browser, open the link there (logged in), and in another
    (verified, with a Log In button). Then read one Sentry event from a
    form post and confirm `password1` is filtered.
25. **The first Sunday after it, read the music job's errors.** An album's
    failure in the cover, Discogs or MusicBrainz pass is now an error line
    and the pass goes on, where it ended the run; a pass that logs many is
    a source down, not many bad albums.

26. **After the fifth pass ships, read `/`'s p50 on games across the
    deploy**, and the same inside one burst window. The list query should
    be most of the difference (bug 5). If it is not, `EXPLAIN (ANALYZE)` the
    page's list query from a one-off dyno: the plan to expect is an index
    scan on `rank` under the limit, with the list count's subquery run a
    hundred times.
27. **Repair the accounts whose email was changed in the admin before
    2026-11-12.** The admin now puts allauth's rows in step when an email
    changes, and only then: an account changed earlier keeps a row for its
    old address, which can still reset its password. List them from a
    one-off dyno, in a command and not `manage.py shell` (AGENTS.md):
    `EmailAddress.objects.exclude(email__iexact=F("user__email"))`. Each is
    either a secondary address its reader added at `/accounts/email/`, to
    leave, or an old one, for `core.services.account_email
    .sync_address_rows(user)`.
28. **Look at the dark theme once on a real screen.** Its links and ranks
    are a lighter green (the accent at 65% lightness, from 50%), which the
    arithmetic and axe-core agree is readable; whether it is the green you
    want is yours to say. One line in `theme/static_src/src/styles.css`,
    and `core/tests/test_theme_contrast.py` says how dark it may go.
29. **The first Sunday after it ships, read the weekly games job** once
    more: it now moves the data version only if a phase changed what the
    pages show, so `/api/games/all/`'s version should change on a Sunday
    that changed something and not otherwise.

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
