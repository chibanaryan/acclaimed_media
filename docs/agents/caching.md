<!-- Part of the agent documentation. AGENTS.md keeps each section's rules
     and points here for the reasoning, history and measurements behind
     them. Moved out of AGENTS.md, word for word, on 2026-11-12. -->

# Caching

Three aliases, defined by `core/cache_config.py` (which `settings.py` calls):

- **`default` is shared across processes.** In production it is Django's
  `DatabaseCache` on the existing Postgres (`CACHE_URL=dbcache://cache_table`),
  so the gunicorn workers and any one-off dyno see the same entries. That
  is what makes `music.services.caching` mean anything: under
  `LocMemCache` each process had its own copy and an invalidation reached
  exactly one of them, so a metadata refresh left stale filter options behind
  for up to their 24-hour TTL. Local dev stays on LocMem; `createcachetable
  cache_table` runs in the Heroku release phase and is idempotent.
  The table outlives a deploy, so the games API's page caches
  (`games.api.views.cache_page`, and `/api/games/all/`'s own) are keyed
  on `HEROKU_RELEASE_VERSION`, from
  the app's `runtime-dyno-metadata` lab (enabled 2026-10-26). Before that,
  new code was served old code's output, such as the payload version for up
  to an hour after a `SCHEMA_VERSION` bump. Both are keyed on the games
  data version too, so an import is not answered with the rows from before
  it, the `cache_page` ones at six queries a hit. Only a bare path is kept: a query string
  is the caller's to write, each one was two rows in this table, and a few
  thousand `?q=` values culled the generation keys and the metadata lock
  with them. A request with one is rendered, under DRF's throttle. The key
  is the release, the data version, the host spelt one way
  (`sites.host_key`) and the path, and the value the rendered JSON
  (2026-11-10): Django's `cache_page`, which this was, also keyed on
  `Accept` and on the port in `Host`. An `Accept` that is not plainly JSON
  (the browsable API) is left to DRF and not kept, and only a 200 rendered
  for the canonical host is, since a list's `next` link is absolute. The rest of the alias is not
  prefixed. A whole-alias prefix reset allauth's and the contact form's
  rate-limit counters on every release, and aimed a long job's
  invalidation at the release it started under. The hand-built caches carry
  their own version constants. The same lab gives Sentry
  `HEROKU_SLUG_COMMIT`, which it reads as the release.
- **`local` is per-process, and must stay that way.** It holds the whole
  rendered pages of `core.mixins.AnonymousResponseCacheMixin`. They are large
  and need no cross-process agreement: on the shared backend a crawler would
  push every page's HTML into Postgres and cull the small shared entries
  straight back out. The bodies are stored **deflated** - the rankings page is
  ~1.4 MB of HTML and there are ~50 cacheable URLs between the home page and
  the SEO landing pages, which uncompressed is 60-70 MB in every worker.
  A cached page's **CSRF token cannot be cached with it**. It is masked from
  the secret in one visitor's cookie, so replaying it hands the next visitor a
  token their own cookie will not match - and a cache hit renders no template,
  so nothing calls `get_token` and no cookie is set at all. `base.html`'s
  contact form therefore 403'd for anyone whose first page was a cached one.
  The mixin swaps the token for a NUL-delimited sentinel on the way in and
  mints a fresh one per request on the way out, so the page stays cacheable
  and the secret stays per-visitor. The CSP nonce, the second per-request
  token, gets the same treatment (`_stash_csp_nonce` / `_restore_csp_nonce`):
  the header carries a fresh nonce on every response, so a replayed one
  would put every inline script outside the policy. A third token would
  need a third pair.
- **`ratelimit` is per-process too**, and holds the per-IP counters in
  `games.middleware`. It was carved out of `local` on 2026-10-18: page bodies
  and counters were culling each other out of one 500-entry LocMem, so a crawl
  wide enough to matter evicted the counters meant to stop it. DRF's
  anonymous throttle (`core.throttling.ClientIPAnonRateThrottle`) counts
  there too; on DRF's default it wrote to Postgres on every API hit. Under
  test the alias is a DummyCache, so no counter is ever kept. Django's
  runner does not clear caches between tests, and a test process making 120
  requests in a minute failed unrelated tests with 429s. The tests of the
  limits override `CACHES` with a real backend.

**Every per-IP limit keys on `core.services.client_ip.get_client_ip`**: the
middleware, the contact form guard, DRF's throttle and allauth's limits,
through `ModalAccountAdapter.get_client_ip`. It takes the *last*
`X-Forwarded-For` entry, the one Heroku's router appends. The client writes
everything to its left, so the first entry, which the code read until
2026-10-26, let anyone take a fresh bucket per request or get another
address blocked. allauth's own default was `REMOTE_ADDR`, the router's, so
every visitor shared one bucket. This assumes nothing proxies in front of
the router; a CDN would move the client one entry left. The auth modal
views call allauth's forms directly, so they apply the `signup`,
`reset_password` and `confirm_email` limits themselves, as allauth's views
would.

`MAX_ENTRIES` is set explicitly for all three, since Django's default of 300
culls a third of the cache on almost every write.

**There is deliberately no site-wide `UpdateCacheMiddleware` /
`FetchFromCacheMiddleware`.** Every page varies on `Cookie` - the auth-aware
chrome and the CSRF token see to that - so Django keyed a separate copy of
every page on every visitor's cookie header, while storing nothing at all for
a first-time visitor who has none (it skips the write when the response sets
cookies and the request carried none). Three workers' worth of per-visitor
HTML, at 1.4 MB each for any client that did not send `Accept-Encoding: gzip`,
was most of why the dyno sat over its 512 MB quota. See "Production memory
budget" below.

**Music's bare pages are cached whole for anonymous visitors**, as games'
are (2026-11-03): `/` for five minutes, and the genre and decade landing
pages and `/browse/` for an hour (`music/config.py`). Measured on the
1000-album corpus first, since every cached page spends from the 512 MB
budget below: a rankings page is ~700 KB of HTML and ~90 KB deflated, and
the 23 of them come to ~1.8 MB per worker, against ~430 ms of rendering
each (a hit costs a few ms). A stored page is served only
while the album data version is the one it was rendered from
(`MusicPageCacheMixin`, through the mixin's `get_page_cache_version`), at
three aggregates a hit: the client joins a page's rows to `/api/all/`'s by
position, and keeps only a payload whose version the page names, so a page
from the last release beside the new payload duplicated and dropped
albums, and re-downloaded the payload on every visit. Nothing an import
does reaches another process's `local` cache, so the version is what
retires a page there. It sits in the stored payload, not the key, so a
page keeps one entry: in the key, a pass that moves the version often (a
cover pass, one cover at a time) left a dead 90 KB copy per hit until a
cull. A filtered page, or any signed-in one, is never cached. What the
version does not hash - a genre renamed in place, an artist's name, a
landing genre falling below the threshold - lasts until the TTL.

**Games' cached pages carry their data version too** (2026-11-03), for the
same reason: the engine adopts the rows `/` rendered and pages on from the
payload by position. `HomePageView.get_page_cache_version` is
`games.services.data_version.compute_game_data_version`, six small queries,
which the landing pages inherit, and the page names it
(`window.gameDataVersion`). The other half was the payload: `cache_page`
kept `/api/games/all/` for an hour whatever an import did, and IndexedDB
trusted its copy for five minutes unchecked, so a fresh page could sit
beside the last import's payload. The view now caches it under the version
it computes, and `GameDataCache` keeps only a copy of the page's version and
asks for `?v=<version>`, which keeps the browser's HTTP cache honest. The
server never keys on `?v=`, so the parameter cannot fill the shared cache
with copies of the payload. A payload whose rows were read across an
import's commit is labelled with no version and cached nowhere. The
`/api/games/version/` endpoint went: no page was left without a version.
A payload of another version is still used, so the engine taking over asks
`ClientSideFiltering.followsPage()` and, if not, renders the page's rows from
the payload, as far down as the page had got, rather than continuing them.
The sidebar's genre and series lists, which nothing drops, are kept a day
under keys carrying the same version (`genres_cache_key`,
`series_cache_key`), so the fetch after an import shows its series at once.
That costs a partial render the version's six queries, which a full page
already pays.

**Games' single-facet pages are kept whole too, whatever `highlight` says**
(2026-11-09). Twice a day, from 2026-11-03, a scraper on a residential-proxy
network asked for 3,500-4,800 rows' filter links in five minutes
(`/?start=2002&end=2002&highlight=1695`), one address a request with a
browser's user agent, so the per-IP limit never saw it. It ignores the
`nofollow` and robots.txt rules, and it runs a real browser: it followed the
CSV link, which was only ever an Alpine binding. Each page was a 17-query
render, the six threads filled, and Sentry's uptime check timed out 11 times
in a week. What changed:

- **The key is made from the parsed query** (`rankings.cacheable_facet`):
  with `highlight` and the tracking tags left out (`page_query`: `utm_*`,
  `fbclid`, ..., so a shared link's `/?fbclid=...` is the home page it is,
  as `/games/1998/?fbclid=...` and `/games/browse/?...` are their pages
  since 2026-11-11), nothing (the home page's own key), one year or
  whole decade, one platform id or one genre id, each parameter once, in any
  order, since the scraper replays a list it re-serialises. A year is bounded
  statically, which keeps a shared-cache read off the hit path; a platform or
  genre id is looked up on a miss (`may_store_page`), and a page for one the
  site does not have is rendered, counted and not kept, or any number would
  be a page to keep. A facet's page is kept an hour, as the landing page it
  duplicates is; the unfiltered page keeps its five minutes. Of 100 burst
  URLs, 70 were years, 12 platforms, 4 genres and 10 series, which stay
  rendered: there are 705.
- **`highlight` is the browser's alone on games.** The view puts none in the
  context, no row is rendered `is-highlighted`, `home.html`'s landing script
  reads the id from the address, and Load More's `data-list-url` leaves it
  out, so a page holds nothing of the visitor it was rendered for. The row
  lights up ~300 ms after load, not at first paint. Music still renders its
  highlight: its landing leans on the server's row, and its page cache still
  declines every query string.
- **The CSV control is a button** (`downloadCsv`), on both sites, and asks
  for the list without `highlight` or a whole year range. Still a
  navigation: fetching the file and saving a blob was tried in review and
  dropped, since in-app browsers ignore a scripted blob download. So once
  refusals are on, a refused CSV replaces the page with the 429's one line,
  and Back returns.
- **A render budget counts what is left** (`core/services/render_budget.py`):
  an anonymous page the cache declined or will not keep, and an anonymous
  CSV, against a per-process token bucket (five at once, one a second). Past
  it, it logs as a burst's count passes 10 (WARNING), then 100 and 1,000
  (ERROR, which Sentry takes). It refuses nothing until
  `ANON_RENDER_BUDGET_ENFORCE` is set, which waits on a week of those
  reports: a real visitor to a page that cannot be kept would be refused in
  a burst too. A script's request, which says so in a header (`HX-Request`,
  `X-Requested-With`), is not counted. `?partial=true` or `?append=true`
  without one is (2026-11-10): the address is the caller's to write, it took
  a request round the cache and the budget both, and every script of ours
  sends the header. The apex answers an old filter
  link in `dispatch`, ahead of the cache and the budget.
- **`HEAD` is the `GET` it is served by** (2026-11-10): answered from the
  kept page exactly as `GET` is, and rendered and kept on a miss. It went
  round the cache and the budget, a whole render for a body the server
  drops. The body is still built, since the headers must be the `GET`'s:
  emptied, the page said `Content-Length: 0`.

That is ~200 more keys in `local` at ~60 KB deflated, ~12 MB a worker.
`scripts/browser_smoke.js` pins the landing ("games highlight ..."), which
nothing did before, and `FilteredPagesAreCachedWhateverTheHighlightTests` the
rule.

**A games import drops the day-long caches a release changes**
(`games.cache.release_cache_keys`: the year bounds, the platform list, the
landing pages' lists and the CSV's genre list), at its commit. Nothing
dropped them until 2026-11-11, so a release adding a year left the year
grid a year short, and that year's landing page a 404, for a day.

Music's cache keys all live in `music/config.py` as `CACHE_KEYS`, which
`caching.invalidate_music_caches()` iterates - add a cached value there or it
will not be invalidated. Every key carries `CACHE_VERSION`, so bumping that
string invalidates the whole set.

**Every music cache write goes through `caching.cached` or `set_if_current`,**
wrappers on `core.cache_helpers`. A read that queried just before a commit
would otherwise save the old rows just after the commit's delete, and they
would stay for the key's whole TTL, 24 hours for the filter options. Every drop
first writes a new `CACHE_KEY_GENERATION`, and a read skips its save if that
moved while it was querying. One generation covers the section, so a toggle
costs a concurrent miss its save and nothing more. A hit costs nothing extra; a miss costs one
more read, since `AlbumHomePageView` batches the generation with its keys. A
tiny window remains between the check and the write. Versioned keys
would close it, at a cache read on every unbatched page and a rewrite of the
music cache tests. `music/tests/test_caching.py` fails if a module writes the
cache around the guard.

**Games' invalidated caches use the same guard, a family at a time**
(`games/cache.py`): hero stats, the played and want-to-play id sets and played
counts, and the developer hierarchy and detail. A generation row is written on
every drop, so there is one per family, not per key, which could outgrow the
cache table's budget, and not one for the section, which would have the weekly
refresh cancel every family's saves. A developer save that changes nothing, which
is most of what the IGDB refresh does, drops nothing. They drop through
`core.cache_helpers.drop_on_commit`, not `cache.delete`: `post_save` fires
inside an import's transaction, and a page load before the commit used to put
the old counts back for a day with nothing left to drop them. Keys collect per
thread and flush together at the commit, so an import costs one drop per family
rather than thousands. Hero stats drop when a game, list or publication is created or
deleted, not on every save, which is what the weekly refresh does. And when a game's year
changes, since the year counts are in the family (`core.loaded_values`). Games' facet,
landing and count caches are not converted: nothing invalidates them by event,
so they have no race. Books' are not either, being staff-only in production. A
test of what a signal invalidates takes
`core.tests.utils.CommitHooksRunNowMixin`, since a `TestCase` never commits.

Music's `/cover/` is exempt from rate limiting on the music host
(`SITE_RATE_LIMIT_EXEMPT_PREFIXES`): it is a static asset in all but the URL,
and one rankings page requests up to a hundred of them against a 120/minute
budget.

**A whole-page cache key carries the host.** `AnonymousResponseCacheMixin`
puts `sites.host_key(request)` in front of the view's own key, because a page
links to the other sites by absolute URL built from the host it was
rendered for. The landing page is cached the same way. `host_key` is the
host spelt one way: no port, case or trailing dot. It was `get_host()` until
2026-11-09, and Heroku's router forwards whatever port a caller writes in
`Host`, so `Host: games.acclaimedmedia.org:8443` was a fresh render and a
fresh entry for every page and every port, each pushing a real page out of
the 500.
