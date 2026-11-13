<!-- Part of the agent documentation. AGENTS.md keeps each section's rules
     and points here for the reasoning, history and measurements behind
     them. Moved out of AGENTS.md, word for word, on 2026-11-12. -->

# Production memory budget

The web dyno is a Basic one: **512 MB for every gunicorn worker together**.
Measured on 2026-10-18 (Python 3.11, Django 5.2), one worker boots at ~110 MB (79 MB of imports, ~30 MB
of it `sentry_sdk`) and plateaus at **~200 MB** once it has rendered a page or
two - flat from ~50 renders out to 1000, so there is no leak to hunt. The
rankings page was 1.4 MB of HTML then, and the ~45 MB a worker never returns
after its first render is allocator arenas, not live data. It is now 690 KB
anonymous and 833 KB logged in (see "Rankings page weight" below). On 3.14
and 6.1 the dyno's metrics show less: a week of 2 workers x 2 threads to
2026-11-02 peaked at 342 MiB RSS for both, with swap under 13 MiB, and ran at
a median of 250 MiB, so a third thread went in on 2026-11-03.

That arithmetic sets the shape of the `Procfile`:

- **`--workers 2`.** 2 x 200 MB leaves ~110 MB of headroom; three workers
  needed ~570 MB and the dyno had been swapping and firing R14 all day.
- **`--worker-class gthread --threads 3`** for concurrency without a third
  heap: threads share their worker's imports and caches, so another thread
  costs only what its in-flight render allocates, where a third process cost
  another ~200 MB. Six requests run at once instead of two, and a long SSE
  import stream holds one thread rather than a whole worker. It ran two
  threads from 2026-10-27 to 11-03. Raise `--threads` only against
  `memory.rss.bytes.max` measured on the dyno.
  The request path was audited for shared state before the switch: the
  per-process caches are `LocMemCache` (locked), the IGDB client and every
  `requests.Session` are per instance, and `RateLimitMiddleware._incr` now
  `add`s before it `incr`s so two threads meeting a new key both count.
- **Database connections are per thread.** `CONN_MAX_AGE` is left at 0, so
  each request opens and closes its own, and the web dyno holds at most
  workers x threads (6) at once, plus an import's background thread and
  the metadata fetch it starts, which runs once the import's own thread is
  done. The fetch's heartbeat closes its connection after each touch, and
  HLTB's executor thread's is closed when the fetch ends. The IGDB
  importer's pool of 8 runs only with batching off (`get_igdb --batch-games
  0`); every caller batches on its own thread, and a pool thread closes its
  connection after each game. A games and a music fetch at once, beside a
  one-off dyno, come to about a dozen of the essential-1 plan's 20.
  `core.services.background.start_background_thread` closes the background
  thread's connection when it finishes; left alone it lingered until the
  cyclic garbage collector reached the thread's wrapper.
- **No `--preload`.** Measured with a fork test: a child touched ~160 MB of
  the parent's pages within 20 requests, because CPython refcounts dirty the
  page holding every object they read. Copy-on-write saved nothing (593 MB
  preloaded vs 585 MB not).
- **`--timeout 600` stays.** The games importer streams progress over SSE and
  a shorter timeout kills that mid-import.
- `--max-requests 2000` is a guard against slow growth, not a memory lever: a
  recycled worker is back at the plateau within ~15 page renders. It was 500
  until 2026-11-09, which recycled each worker about four times inside one
  scraper burst, emptying its page cache each time. Memory was measured flat
  only to 1,000 renders, so check `memory.rss.bytes.max` against it.

**Template indentation is stripped at load.** `core/template_loaders.py`
wraps both loaders, in dev and prod alike, and removes the leading whitespace
of every `.html` source line, which was 36% of the rankings page. Each newline
survives, so rendering is unchanged, except inside `<pre>`/`<textarea>`, which
are left as written. **Do not add markup whose meaning depends on
indentation** - `white-space: pre` in CSS, or indented text in a `<code>`
block - without exempting it there.

**Rankings page weight.** What was cut, and what holds it down:

- **The server renders no grid cards.** The 100 hidden
  `_game_card_grid.html` cards were ~160 KB. Grid mode now shows the list
  rows until the client-side filtering bundle builds a grid from
  `#grid-card-template`: `styles.css` hides the rows only
  `:has(.game-grid)`, `home.html` fetches the bundle at once when
  `gameViewMode` is `grid`, and `filterComponent` renders the grid as soon
  as the bundle is ready (`_needsClientGrid`), without touching the URL.
  Anything that pages a grid (`renderer.loadMore`, `renderer.showRange`)
  builds the whole window when no grid exists yet, because the rows above
  are not cards.
- **Jump to rank renders a window, not everything above the target.**
  `BaseMediaListRenderer` tracks `windowStart`/`windowEnd`, and `planJump`
  either scrolls (the target is already rendered), extends the window (the
  target is within a page of it), or replaces it with `JUMP_RADIUS` (50) rows
  either side of the target. `core/includes/_load_previous.html`, above each
  rankings list, gets a Load Previous button whenever rows are left out
  above. Positions are absolute, so anything that finds "the Nth row" on the
  page has to subtract `windowStart`. Focusing the games jump box also starts
  the engine: before, it only loaded the bundle, so every jump took the
  server path, which fetches each page down to the target.
- **Platform and genre spans carry `data-add-platforms` / `data-add-genre`,
  not inline onclicks** (~54 KB). One delegated listener in `base.html`
  re-announces the `add-platforms` / `add-genre` events every filter
  component already answers. Album rows use it too, with `data-item` for the
  highlight.
- **One game status menu per page, not one per button** (~250 KB logged
  in). Each game renders two buttons, one per row half, and each used to
  carry an Alpine component and three `hx-post` items. A button is now only
  its trigger; `games/includes/_played_menu.html` and `played-menu.js` open
  the shared menu beside it and post with `htmx.ajax`, the wrapper as source
  so the body's CSRF header is inherited. The wrapper's
  `onclick="event.stopPropagation()"` keeps the mobile row from navigating,
  so the menu's click listener runs in the **capture** phase.
- **Alpine skips the filter UI the visitor cannot see** (2026-10-25). At
  Lighthouse's 4x mobile throttle, Alpine's init on `/` was one ~920 ms task,
  and nearly all of it went to two invisible things: the `display:none`
  desktop sidebar (~530 ms) and the never-opened mobile sheet (~340 ms). The
  100 rows cost nothing, because they carry no directives. The sheet's contents
  now sit in `<template x-if="hasOpenedBefore">`. The sidebar
  (`#desktop-filter-sidebar` in `_advanced_filters.html`) is `x-ignore`d
  by an inline script on a narrow first load, then `Alpine.initTree`d if
  the window widens past 962px. Both lean on `mobile-filter-opened`, which
  makes `filterComponent` re-send the facet counts that the late components
  missed. Alpine init dropped to ~90 ms. The sidebar div must carry no
  directives of its own, since `initTree` would run them a second time.
  The album page does the same (`#album-filter-sidebar`, music's sheet):
  the script is the shared `core/includes/_defer_hidden_sidebar.html`, and
  `mediaListControls.refreshFacetCounts()` answers `mobile-filter-opened`
  through the engine's `republishFacets()` once it is ready. Its form keeps
  working while ignored, because `commit()` writes the fields itself. At 4x,
  the album rankings went from ~360 ms of Alpine init to ~75 ms on a phone.

**Filter-change speed** (2026-10-26). A decade click took ~290 ms to
reach the list on a fast machine and ~710 ms at a 4x CPU slowdown, and
almost none of that was filtering. Now it is ~60 ms and ~250 ms, with
every click's INP under 200 ms even at 4x. Four things mattered:

- **The trailing debounce** (150 ms in games, 250 ms in music's
  `mediaListControls`) made every single click wait.
  `_debouncedFilter` is now `debounceLeading` (`utils-base.js`): the first
  change applies at once and a burst still collapses into one trailing
  update. It runs through `afterNextPaint`, because doing the update in
  the click's own task held back the paint INP measures, at 300-400 ms on a
  slow CPU. It leads only once the client engine is ready
  (`clientFilterReady`, music's `clientEngine` setting): before that each
  update is a server render, and a leading fetch could land after a newer
  client render. A burst's trailing run replaces the history entry the
  leading one pushed (music: `historyReplace` on the `change` event's detail), and is skipped
  when it would render the same filters again. When the games engine
  finishes loading it takes over: it cancels what is queued, aborts a server
  render in flight, and pushes if the filters are not the ones the URL last
  got (`_urlFilterKey`, kept by `_writeHistory`, the one place a URL is
  written), since replacing would lose the page Back should reach. A push
  of the filters `_urlFilterKey` already holds becomes a replace, so Clear
  All from a jumped list no longer pushes `/` over `/`.
  `scripts/browser_smoke.js` holds the engine's data and that render to pin it.
  Music's engine aborts an HTMX filter request or Load More it overtakes and
  answers it. It keeps no record of what it last rendered: three attempts at
  skipping a repeated commit each broke something (a typed search, a `?q=`
  link, Clear All on a jumped list). Only `pushUrl` guards, statelessly, against
  pushing the URL it is on: a search used to leave two entries. A games
  Load More or server jump fetches from the list's own address, which the
  server renders onto the button (`data-list-url`), not from the URL: Back
  moves the URL before its render replaces the list, and a page fetched
  meanwhile went in under the wrong list. A response with no
  `#load-more-meta` is a failed page, not rows to append. One whose button
  has gone is dropped
  (`utils-loadmore.js`), unless the list is still the one it was asked
  for: `filterComponent._urlFilterKey`, the filters the URL was last
  written with, is unchanged, on the same visit of them (`_urlFilterVisit`,
  since a sort and Back bring the filters back while the list went back to
  its top), and no server render is on its way (`serverListKey`,
  `engineForSameList`). Not the filters asked for, which run
  ahead of the list while a change is on its way, and not the URL, which
  the takeover rewrites into its normal form. Then the engine answers it,
  wherever it lands or fails, so no render that replaces the button has
  to: the takeover of the page's own filters, a list/grid toggle, a client
  jump, the engine's Load More. A jump becomes the engine's jump, and a
  Load More renders to the row the click asked for, not one page past the
  100 a render leaves. A filter change or Back changes the key, so both are
  dropped: a late server jump used to jump on the filter's list. Asking at
  render time instead needed every render to remember, and a pending jump
  to be forgotten once answered. A page that lands moves its button past
  its rows before anything that can throw (`appendPageResults`): left
  asking for the same page, a retry appended it twice; if the rows
  themselves throw part-way, the button stays off.
- **Sidebar bindings scanned the page's reactive arrays.** Every
  platform, genre and series row called `find()`/`filter()` over
  `platforms`/`genres`/`seriesList`. Each scan read, and subscribed to,
  every item through Alpine's proxy, and a year change re-evaluates every
  row, so one change cost ~90 ms of Alpine effects. The components now
  build index maps once (`indexBy`, `buildGenreIndex`) and read
  `list[i]`, which tracks only that item. The structure of these lists is
  fixed for the page's life; only `filtered_count` changes.
- **The desktop series getter sorted `seriesList` in place**, writing
  every index of the reactive array on each read. It sorts a copy.
- **The chart animation is frame-capped** (`MAX_FRAME_STEP_MS` in
  `rank-distribution.js`), so a busy main thread pauses the morph rather
  than skipping to its end.

**A failed server filter request rolls the games controls back** (2026-11-10),
as music's do. Before the engine loads, a request that failed left the year
grid and the sidebar on the filters asked for over a list still showing the
old ones. The list carries `#game-rendered-filters`, the server's echo of
its filters as a query `getFiltersFromURL` reads (no `highlight`: the page
is kept whole), and `filterComponent._rollBackIfStranded` reads it back
into `filters`. Not while the engine may still come, since its takeover
renders the filters asked for and pushes them; `init()` answering false is
now reported (`_engineUnavailable`), which is what rolls back then. And not
once the reader has changed something since the request was sent. The
heading, the tab and the address are moved only by a render, so the
controls are all there is to undo. Two more limits, each a bug in the first
version: only while the address is still the list's (Back moves it before
its render, so a failed Back is left alone, and so is a failure after one),
and a search box with focus keeps its text. That text is never rewritten:
Alpine's `$watch` fires on any write, so putting the same text back read as
a new search, which failed, and was put back, three times a second. smoke:
"games failed request, engine failed first / after", "games failed Back
without the engine", "games failed search keeps the typing".

A failed Back is left alone by the roll-back, so its list stays the one it
left, under the address it went to (`_listBehindAddress`). If the engine's
data then arrives, the takeover renders the address's list and writes no
history (2026-11-10). It used to find the filters equal to the address's
and adopt the rows as that list, so Load More continued the 1990s with the
whole ranking's second page. The flag, not a comparison of the filters with
`#game-rendered-filters`: the playtime mode moves the address with no
render, so those differ on a list that is the right one. smoke: "games
failed Back, then the engine".

Measure with real clicks, at 1x and 4x, through the Event Timing API
(`interactionId` entries) plus a MutationObserver on
`#game-list-container`. Puppeteer's `mouse.click` hits nothing off-screen,
so scroll a sidebar control into view first.

Anything that grows the rendered page, the boot imports, or a per-process
cache is spending from that 512 MB twice over. The metadata fetch an import
starts spends ~85 MB in one worker while it runs (see "Imports start their
metadata fetch"); a week's peak of 342 MiB leaves room for one. The lock is
per section, so a games and a music import together would run two: stagger
them. `heroku ps`, and the
metrics API (`api.metrics.heroku.com/apps/<id>/formation/web/metrics/memory
?start_time=..&end_time=..&step=1h&process_type=web`, with
`memory.rss.bytes.max` and `memory.swap.bytes.max`), are how to check it.
