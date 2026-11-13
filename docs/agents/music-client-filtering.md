<!-- Part of the agent documentation. AGENTS.md keeps each section's rules
     and points here for the reasoning, history and measurements behind
     them. Moved out of AGENTS.md, word for word, on 2026-11-12. -->

# Music client-side filtering

The album rankings page filters in the browser. `/api/all/` on the music host
(`music-api:album-all-data`) returns the whole corpus
(1000 albums, ~270 KB of JSON, 95 KB gzipped), the bundle holds it in
`sessionStorage` keyed by the data version the page renders into itself, and
`music/static/music/js/` filters, sorts and renders locally. There is no
IndexedDB layer and no `version/` endpoint: at this size neither pays for
itself.

It is progressive enhancement. The page is server-rendered and its HTMX sidebar
filters server-side on its own; the bundle suppresses those requests only once
it has data and a renderer, so a failed or slow bundle leaves a working page.
Load More and the list/grid toggle work either way, and jump-to-rank once the
engine is there: it seeds itself from what the server rendered (`attach()` and
`_syncRendererWithPage()`) rather than re-rendering the page on load - unless
its data is not the version the page names (`followsPage()`), which an import
committing between the page and its payload causes. Then it renders the rows
the page had from the payload, a `?page=N` link's included
(`applyFilters(..., { range })`), since it continues the page's rows by
position. `/api/all/` reads the version before and after its rows, and labels
rows read across a commit with none, which no page names and no tab stores.

Four rules keep the server path and the engine from stepping on each other,
each pinned by `scripts/browser_smoke.js`:

- **Only `commit()` renders.** The engine's form listener and the form's
  `hx-trigger="submit, change[!!detail]"` answer only the `change` that
  `mediaListControls.commit()` sends, which carries a `detail` (htmx passes a
  filter only when it is exactly `true`). A field's own `change` - the search
  box's, on blur - re-rendered during the next click's mousedown, and the
  click landed on nothing.
- **htmx never answers Back on this page.** Its `onpopstate` swaps the whole
  body back in for an entry it pushed, from a snapshot that holds the DOM
  Alpine built (an Alpine error per `x-for` clone) or, once the engine is
  ready, leaving the engine on a detached form. `music/home.html` replaces it
  after htmx installs it: once the engine is ready the engine's popstate
  listener answers every entry, and until then, or if it never loads, an
  entry htmx pushed is reloaded. The form saves no snapshots
  (`hx-history="false"`), nor is it restored by the browser
  (`autocomplete="off"`). Clearing old snapshots instead missed tabs still on
  the old markup, which went on saving them. `core/tests/test_static_bundles.py`
  fails if a vendored htmx stops assigning `window.onpopstate`. And
  `HTMXPushURLMiddleware` pushes no `?append=true` page, which is rows to
  append, not an address.
- **Taking over, the engine renders the form's filters if they are not the
  ones the list was rendered with** (`formAhead`): what a filter request that
  failed before then leaves behind. It compares with
  `#album-rendered-filters`, the server's echo of the request, not with the
  URL, which the server cleans up (`?artists=Prince` is `prince`, a repeated
  parameter its last value), and leaves out a search still being typed -
  unless the form's last request was that search and failed, which it
  renders whatever has focus, and pushes, the search's own commit having
  been spent. It is that search only while the box holds exactly what htmx
  sent, untrimmed: compared trimmed, "pink " typed after a failed "pink"
  was rendered and pushed mid-word. Putting the form back on the URL
  instead lost a click in flight and the search being typed. With no
  engine to come (its data failed, or the bundle is missing), a failed
  request puts the controls, the form and the heading back on that echo
  instead (`mediaListControls.rollBackToTheList`, through
  `renderedFiltersId` and the `client-engine-failed` event), so the click
  is lost but nothing claims a filter the list does not show - unless the
  reader has changed something since the failed request: a change still
  in a debounce lives only in `filters`, and one queued behind the request
  is sent by htmx from the form as it stands then, so a roll-back would
  lose it or send the old filters in its place. `_movedOnFrom` reads what
  was sent, and the list's echo, back into the controls' terms
  (`_filtersFrom`, the rules Back reads the URL by, genre ids kept as the
  server's `parse_id_list` keeps them), and the reader has moved on only
  if `filters`, or else the form's named fields, differ from both. Against
  what was sent alone, a request sent before Alpine started the controls
  (a row's genre) read as a newer change, since the controls start on the
  list. The engine keeps the failed request's parameters on
  `csf.failedParams`, which controls starting after it failed answer as
  they start. A record of what the controls held as the request went out
  cannot stand in: a queued request is sent after a newer click's debounce
  began, and Enter and a row's genre send without a commit.
- **The jump box waits for the engine**, which alone answers it: it renders
  disabled (`jump_awaits_engine`) and the bundle switches it on.

Before the engine, a filter request aborts a server Load More in flight: the
button shares the form's `hx-sync` queue (`#album-filters:abort`). Without it
the page landed after the filter's render, appended to the list it replaced,
and put its own button back out of band. A `?page=N` link renders rows from
`N`'s start, which `#album-list-container[data-window-start]` tells the
engine; `adopt()` takes the start, and the takeover draws Load Previous.

A status change under a status filter takes out only the row that left and
moves the later positions up one (`dropIfFilteredOut`,
`AlbumListRenderer.removeItem`), re-rendering nothing, so quick-mark costs the
same 900 rows down as at the top.

Two payload fields exist to keep the client and the server agreeing exactly:

- `nn` is `name_normalized`, the `unidecode(name)` column the server's `q`
  searches alongside `name` and `artist_credit`, and `cn` is
  `artist_credit_normalized`, the same for the credit line, so "bjork" finds
  Björk (`credits.album_search_q`, 2026-11-04). Sent rather than recomputed,
  because reimplementing unidecode in the browser would be a second copy of the
  rule that drifts. `cn` is sent only for the albums that have one. The
  query is never folded for matching, on either side, only for ranking
  (`search_ranking`). The
  artist search folds the same way, through `Artist.name_normalized` and
  `AlbumCredit.credited_name_normalized`; the import fills the latter itself,
  since it bulk-creates credits.
- `ni` is the album's position in the server's own `Lower(name)` ordering. No
  JavaScript comparator reproduces a database collation: `localeCompare` files
  "Ágætis byrjun" next to the A's while SQLite sorts it past Z, and punctuation
  is weighted differently again. The client sorts alphabetically by this
  integer, which also stops local SQLite disagreeing with production Postgres.

The "Release Date" sort (`?sort=year`, kept for old links and saved filters)
is `year_released`, then `release_date` within the year (undated last in both
directions), then rank - `RELEASE_ORDER` in `music/views.py`,
`_compareReleaseDates` on the client, which reads the payload's `rd`. The
year leads because it is the published one every filter and row shows.
`Album.release_date` is derived from Wikidata P577, else MusicBrainz's first
release, by `music.services.release_dates.refresh_release_dates` at the end of
any `fetch_album_metadata` run with a Wikidata or MusicBrainz pass. An album
an import adds has none until that run, as it has no genres; a kept album
keeps both.

`release_date_precision` ("day", "month", or blank) matters because a
month-precise date is stored as the 1st: the artist page's rows show
"May 16, 1966" only for "day", else "May 1966" (`release_date_label`, passed
to the row as `year_text`). Blank reads as a month - it is what a Wikidata row
fetched before the precision was stored carries until its next pass.

The genre filter expands a selected genre to its descendants on both sides,
as `games.services.query_filters.apply_genre_filter` does: picking "Rock"
means rock, including the Discogs styles filed under it. `expand_genre_ids`
does it server-side and `AlbumFilterEngine._expandGenres` in the browser,
from the descendant ids the payload already carries.

The count beside a genre is a **distinct** count across that genre's whole
subtree, so it is exactly what selecting the row gives. Summing a root and
its children instead - which is what the shared tree does when a section does
not supply subtree counts - double-counts an album tagged both "Classical"
and "Modern Classical", and the sidebar claimed Classical had two albums when
it had one. Music passes `genre_counts_include_descendants` to turn the
summing off.

The parity check is automated, for music and games alike:
`core/tests/test_filter_parity.py` renders a spread of filter and sort
combinations on the server, runs the real engine files under Node on the same
data (`core/tests/js/filter_parity.js`), and requires the same order. Unit
tests cannot catch a divergence here, because both sides can be
self-consistently wrong. On its first run it found games' name sort comparing
with `localeCompare` against the database's collation. Games now send `ni` as
music does, and the server sorts by `Lower(name)`. The test skips where Node
is missing, but not in CI, where the test jobs install Node and a missing one
fails (`core/tests/node.py:require_node`): a skip there was a pass nobody
saw. Add a query there when adding a filter or a sort.
