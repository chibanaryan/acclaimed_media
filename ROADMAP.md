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
   it replaced, so if those rows fail, take the pattern back out rather
   than patch it unheard. It is one file since 2026-11-12,
   `core/includes/_search_combobox.html`, where it was four copies and
   one commit to revert ("The search boxes are comboboxes" shows what a
   plain field and its links were). Music's listen menu took menu roles
   and keys the same day (`media-tracking.js`); the checklist wants rows
   for it too, and a year cell's name (bug 10) is to be decided there.

The browser harnesses used for v905 (`matrix.js`, `musicrace.js`,
`loadmore.js`, `round8.js`-`round10.js`, and `xbrowser.js` for WebKit and
Firefox) were in the ashgabat worktree's `.context/ygrid/`, which is
gitignored: that worktree is gone, and they with it. What they checked in
Chrome is in `scripts/browser_smoke.js`; nothing here runs WebKit or Firefox.
A Firefox run was tried on 2026-11-12: Firefox 156 would not start headless
from the agent's shell ("Could not find profile folder"), driven by
puppeteer or launched bare, so the smoke test still runs Chrome alone.

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

3. **Books' page**, if the section is ever picked up (see "Explicitly
   not doing"). Its client engine went on 2026-11-12: a bundle nothing
   started, with a renderer for slots and routes that do not exist. What
   is left:
   - The sort dropdown calls `updateSort()`, which nothing defines, and the
     direction flip and the jump box are inert (`_book_list_results.html`).
   - The mobile row's title is no link, the read button has no name, and
     every `mdi-book-*` icon is undefined, so the button renders as nothing.
   - The read button's partial ships a `<script>` with every row
     (`_read_button.html`), which keeps two Sets no page defines any more;
     games' copy sends it only with a toggle's answer.
   - `book_detail.html` nests its head blocks in `content` as album detail
     did. The rows take a `highlight` no view passes.
   - `/api/books/all/` and `/api/books/version/` have no caller, and the
     home view builds genre, author and year-bounds context no template
     reads (cached a day).
   - Nothing drops a books cache: no signals, no generation keys. An admin
     edit waits out the TTL, a day for most.
   - The Goodreads import runs two to four queries a row inside one
     request, and the Open Library and Hardcover clients retry on a flat
     one-second sleep and never on a 5xx, where music's `RateLimitedClient`
     backs off.
   - `fetch_book_metadata --json` prints a header and a footer around the
     JSON, and `--json` / `--output` are ignored with `--isbn`.

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
   SQL (measured 2026-11-10 on SQLite). The fifth pass made `list_count` a
   subquery a row and took the sort's `DISTINCT` off; the sixth made the
   genre, platform and series filters an `EXISTS` each, so a filtered list
   has none either (`DEVLOG.md` has both sets of numbers: on Postgres 15
   the list query with two platforms went from 7.4 ms to 2.2 ms). Two
   things are left. Production is Postgres 18 on other hardware and was
   not measured: read `/`'s p50 across a deploy (item 26). And music's
   artist and genre filters still join and `DISTINCT`, on a thousand rows,
   with nothing measured to say it matters.
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
8. **Small leftovers.** The sixth pass took most of this list (the
   "Load Test Data" POST, the three progress streams, the four search
   boxes, the coverage gate's exceptions; `DEVLOG.md`). Left:
    - Music's takeover runs in `csf.init().then(...)` with no `catch`. One
      that only logged would turn an uncaught error, which the smoke test
      fails on, into a console line it does not see; one that did more
      would have to decide what a half-finished takeover leaves.
    - Staff-written markdown (flat pages, articles, posts) is rendered and
      marked safe unsanitized. Fine while only staff write it.
    - `base.html` and `_nav_mobile.html` carry inline script on every page,
      which a static file would let a browser keep. Measured 2026-11-12 on
      the smoke data: 15 to 23 KB of it a page, 5 to 8 KB gzipped, of a
      40 KB gzipped rankings page. Some of it must stay inline (it runs
      before paint, or holds per-request values), so the saving is a few
      kilobytes on a repeat visit.

   Looked at and dropped: `PlayedGame`, `WantToPlayGame` and
   `SavedFilterSet` re-declare the fields of `core.models.UserTrackingBase`
   and `SavedFilterSetBase`, but each names its own `related_name`
   (`played_games`, `saved_filter_sets`), which the bases cannot give them,
   so subclassing would re-declare the same fields.

## Open bugs (found 2026-11-11)

The fourth pass (`DEVLOG.md`) fixed resending a verification (bug 8 as was)
and four of the small leftovers. The fifth, on 2026-11-12, fixed the
platform group ids, the source-lists total, the reversed year range, the
server Load More's focus, the release-group MBID check and the admin's
email rows. The sixth stored IGDB's summary (bug 9 as was; item 30 is its
production step), took `localhost` out of production's `ALLOWED_HOSTS`,
removed the recursive genre walks nothing called and moved each metadata
pass's requests out of its savepoint. Found by the fourth pass's audits
and left:

9. **Smaller, found and left.**
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
    - One request of the cover pass is still made inside its savepoint: a
      row that names a cover whose bytes will not download sends the pass
      to search for another, and only storing the first shows it is gone.

## Open bugs (found 2026-11-12)

The fifth pass (`DEVLOG.md`). Its surveys found little that a reader could
reach, which is its own finding: a crawl of all 3,633 sitemap URLs on a copy
of production's data returned no error, and eslint and ruff's bug rules
found nothing to fix. The sixth pass, the same day, fixed the dark year
grid's labels, two of the three names, the over-long sign-up email, the
payload fingerprint's reach into the API view, `setup_worktree.sh`'s unset
variables and `games/utils.py`'s re-exports. Left of the fifth's list:

10. **Found and left.**
    - **A year cell reads "10" and is named "2010, 12 albums"**, which
      does not hold its label word for word (WCAG 2.5.3, for someone
      driving the page by voice). The fix, "10: 2010, 12 albums",
      lengthens about seventy announcements a page for a command nobody
      has tried: decide it at the assistive-tech run (bug 1).
    - **Album detail's two `COUNT`s** (albums of its year, of its decade)
      were to read the cached year baseline. Left: the shared cache is a
      Postgres table in production, so the read costs the query it saves.
    - **The shared venv is behind the locks**: django-allauth 65.20.1
      where the lock pins 65.21.0, and Django 6.1.2 where it pins 6.1.3
      (2026-11-12; the migration the sixth pass generated says 6.1.2 in
      its header). CI installs the lock; a local run does not test what
      ships until `pip install -r requirements.txt -r requirements-dev.txt`
      is run in the main checkout.
    - **Two `theme` cookies the toggle cannot reach still win where they
      exist**, neither of which this site writes: one with a longer path
      than `/` (another app on a shared address such as `127.0.0.1`), and a
      host's own on a site other than the one the toggle was used on. And
      on an address the cookie is named `theme`, which another local app
      may use. A name of our own (`am_theme`, as the session's is) would
      end all three, at one reset of every reader's choice across sites.

## Open bugs (found 2026-11-12, sixth pass)

The sixth pass (`DEVLOG.md`) worked through the lists above and brought
every file under the coverage gate. The tests written for that ran code no
test had run, and most of this list is what they found and did not fix.
Its two surveys found nothing a reader meets: `html-validate` over sixteen
rendered pages (its 1,800 messages are Alpine-bound attributes and clone
templates), and a fuzz crawl of every GET route on the three hosts with
malformed query parameters (30,063 requests over 127 routes, signed out
and as staff, on a copy of production's data: no 5xx).

11. **Found and left.**
    - **A game's alternate Wikipedia records do not survive an import.**
      A game with two Wikidata ids gets a second, non-primary
      `WikipediaGameData` row for the alternate
      (`fetch_wikipedia_metadata`), which can hold the HLTB id. An import
      orphans every row and takes back only primary ones, and the fetch an
      import starts is missing-only, so the alternate's HLTB id is out of
      reach until a `--force` run, which makes a second row beside the
      orphan. The fix belongs in the import: take non-primary rows back by
      Wikidata id. Read from the code, not reproduced.
    - **The weekly refresh's own copy of the page save**
      (`refresh_all_metadata._save_wikipedia_data_async`) does not take an
      orphaned record of the same page back, so it makes a second row, and
      never stores a Wikiquote title. `WikipediaGameData.attach_page` is
      the one the command and the staff stream share since this pass; the
      weekly job's is async and was left.
    - **The weekly refresh counts a failed save twice**: as a page found
      (or a playtime found) and as an error, so its summary can read "2/3
      pages found (1 errors)" for two games. `fetch_hltb_data` did the
      same and was fixed. Its Wikipedia progress line also skips games
      with no page.
    - **`refresh_all_metadata` has a second infobox parser**
      (`infobox_genres`), thinner than
      `WikiGenreService._scrape_infobox_genres`: "Racing and vehicular
      combat" yields "and" as a genre. The normaliser drops it, so nothing
      wrong is stored. One parser would do.
    - **`aiohttp.BasicAuth` is deprecated** and goes in aiohttp 4.0; the
      weekly refresh's authenticated Wikidata requests use it.
    - **`fetch_wikipedia_metadata`**: `--skip-existing` does what the
      default does; a Wikidata entity that no longer exists gets an empty
      alternate row; two rows for one `(game, wikidata_id)`, which only an
      admin edit can make, abort the run (`MultipleObjectsReturned`).
    - **`get_wiki_genres`**: `--resume` on a file that does not exist
      writes to a new timestamped file, not to that one; a `--game` that
      matches nothing prints "No games to process", not that it was not
      found; `--slug` ignores `--limit` and `--offset`.
    - **`fetch_hltb_data`**: "Results saved to database" prints under
      `--save` even when every save failed, and its CSV is opened outside
      the `try`.
    - **Data the fetchers store and no page shows**: IGDB's first video
      (`IGDBGameData.youtube_video_id`) and the Wikiquote title
      (`WikipediaGameData.wikiquote_page_title`). Show them or stop
      fetching them; `youtube_url` and `wikiquote_url` are read by tests
      alone.
    - **`games/static/games/palestine-flag-xs.png`** is linked from
      nothing in the repository or the local flat pages. An article in
      production could link it, which was not checked, so it stayed.
    - **Music's listen button is a dropdown a row, twice a row**: about
      2 KB of markup a button and an Alpine component each, some 400 KB
      of a signed-in rankings page by a rough count. Games moved to one
      shared menu a page for this reason ("Rankings page weight" in
      AGENTS.md). It would rewrite the shared button, its clone twin, the
      renderer's slots and quick-mark; measure first.
    - **Games' tracking button is still its own**, where music's is the
      shared partial. The saved filters moved this pass and the status
      filter was shared already; the button is games' newer
      one-menu-a-page design, so the shared partial would have to learn
      that first (see "Music: not worth doing as parity").
    - **The listen menu's keys, two edges** (review, round 2): a key
      pressed in the 75 ms a closing menu takes to fade is read as if it
      were open, and focus can land on an item about to vanish; and
      ArrowUp on a closed button opens on the first item, where the menu
      button pattern suggests the last.
    - **A metadata pass reads an album's rows twice**, in its fetch and
      again in its step: three or four cheap queries an album. The second
      read, inside the savepoint, is what lets the step cope with a row
      another run changed in between.
    - **The commit and deploy skills' DEVLOG rules** (eight bullets a
      day, one date header a day, the imperative) are not what DEVLOG has
      looked like since October. One of them is out of date; which is the
      owner's to say.

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
    old address, which can still reset its password. From a one-off dyno:
    `python manage.py repair_email_rows` lists them and changes nothing,
    saying of each row whether it looks like a leftover a password reset
    would go to or a second address the reader added at
    `/accounts/email/`. Then `repair_email_rows --sync <username> ...` for
    the leftovers (the command is the sixth pass's).
28. **Look at the dark theme once on a real screen.** Its links and ranks
    are a lighter green (the accent at 65% lightness, from 50%), which the
    arithmetic and axe-core agree is readable; whether it is the green you
    want is yours to say. One line in `theme/static_src/src/styles.css`,
    and `core/tests/test_theme_contrast.py` says how dark it may go.
29. **The first Sunday after it ships, read the weekly games job** once
    more: it now moves the data version only if a phase changed what the
    pages show, so `/api/games/all/`'s version should change on a Sunday
    that changed something and not otherwise.

30. **The sixth pass's deploy applies `games.0125`**, one added column
    (`IGDBGameData.summary`), with nothing to fail on. The column fills on
    the first Sunday's `refresh_all_metadata`, which refetches every game;
    `heroku run:detached -- python manage.py get_igdb --force` fills it at
    once, in under three minutes on the free tier. Then look at one game
    page's source: its `<meta name="description">` should lead with its
    rank and go on in IGDB's words.
31. **Look at the dark theme's year grid.** Its tiles are a darker amber
    (50% lightness, from 72%), which is what lets their labels be read;
    the rank chart keeps the brighter one. If it is too muted, revert the
    one commit ("Dark theme: a year tile's label can be read on its
    tile") and the labels are as they were.
32. **Staff import page.** Its progress bars have a fill for the first
    time since DaisyUI 5 (thirty-one declarations read variables it no
    longer defines): look at one import. The IGDB button's stream now
    sends a keepalive every 15 seconds, so a batch IGDB is slow to answer
    should no longer be a dropped connection. "Load Test Data" is refused
    on a dyno; `?update_relationships=true` is gone.
33. **CI's Node is pinned at 26** (`NODE_VERSION` in `ci.yml`). Nothing
    bumps it: `/upgrade-deps` has a row for it.

## Music: not worth doing as parity

- **Artist detail has no related-acts panel** where developer detail has a
  subsidiary filter. 0 of 629 artists in this corpus have sub-acts, so the
  panel would always be empty. Revisit only if the metadata pass starts
  filling `Artist.parent`.
- **Migrating games' tracking button onto the shared
  `core/includes/_tracking_button.html`.** The saved-filter three
  (`_saved_filters_dropdown.html`, `_saved_filter_modals.html`,
  `_mobile_saved_filters.html`) moved on 2026-11-12, as a template change,
  and games' status filter was already the shared one. The button is the
  other way round: games' is the newer design, one menu a page
  (`_played_menu.html`, `played-menu.js`), and the shared partial is a
  dropdown a button. Moving games onto it would put back the page weight
  games took out; the shared one should learn games' design first (bug
  11). Books' read button is its own third thing, and books is parked.

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

- **Books.** Its client-side filtering stack, repaired on 2026-10-17 and
  never started by anything, was removed on 2026-11-12, and the server
  renders its list (bug 3 has what is left of the page). Books still has
  no filter UI at all, and its sort controls reference an Alpine `filters`
  variable no component provides (5 console errors per page load). An
  author's page renders a Load More button that
  nothing answers (`author_detail.html`), and the authors list pushes its own
  history entry beside htmx's on every search and sort, so Back takes two
  presses (AGENTS.md, "A page never pushes an entry of its own"). Deprioritized
  by the owner.
