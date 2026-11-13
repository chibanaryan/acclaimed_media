<!-- Part of the agent documentation. AGENTS.md keeps each section's rules
     and points here for the reasoning, history and measurements behind
     them. Moved out of AGENTS.md, word for word, on 2026-11-12. -->

# API Architecture

Django REST Framework powers the API at `/api/` with endpoints:
- `/api/games/` - List and search games
- `/api/games/search/` - Game search for navbar
- `/api/games/<slug>/` - Game details with lists appearances
- `/api/games/all/` - Every game in one payload, for client-side filtering
  (cached under the data version; see "Caching"). Built by
  `games/services/all_data_payload.py`, for the view and for the weekly
  refresh's fingerprint alike
- `/api/developers/` - List of all developers with games, their studios'
  counted, as the developers page counts them. It counted direct games
  until 2026-11-12, and left out 42 parents (Microsoft, CD Projekt)
- `/api/developers/<slug>/` - Developer details by slug
- `/api/developers/by-id/<igdb_id>/` - Developer details by IGDB ID
- `/api/developer-aliases/` and `/api/developer-aliases/<igdb_id>/` - The
  same two views, under their older names
- `/api/lists/` - Source lists
- `/api/publications/` and `/api/publications/<pk>/` - Publications
- `/api/platforms/` - Gaming platforms
- `/api/genres/` and `/api/genres/tree/` - Game genres, flat and as a tree
  (also at `/api/wikipedia-genres/...` for backwards compatibility)
- `/api/snippets/<slug>/` and `/api/pages/<url>/` - A text snippet, a flat page
- `/api/meta/` - Metadata about the database
- `/api/unified-search/` - Unified search for games, developers, and series.
  A name is found as typed or without its accents
  (`games.models.name_search_q`), the latter only for a query unidecode
  has a spelling for throughout: it drops an emoji, and "the folded name
  contains nothing" is every row, so "🎮🎮" was answered with the top of
  the rankings until 2026-11-12. `/developers/?q=` uses the same clause
- `/api/saved-filters/` and `/api/saved-filters/<pk>/` - A reader's saved
  filter combinations: the games API's only writes, behind a session and CSRF

Books API endpoints (behind `BOOKS_ENABLED` feature flag):
- `/api/books/` - List and search books
- `/api/books/search/` - Book search
- `/api/books/<slug>/` - Book details with lists appearances
- `/api/books/all/` - Bulk endpoint with gzip compression. Nothing calls
  it or `version/` since the books page's client engine was removed
  (2026-11-12)
- `/api/books/version/` - The data version the bulk payload is kept under
- `/api/books/authors/` - List authors
- `/api/books/authors/<slug>/` - Author details with book list
- `/api/books/authors/by-id/<goodreads_id>/` - The same, by Goodreads id
- `/api/books/lists/` - Source lists
- `/api/books/genres/` and `/api/books/genres/tree/` - Book genres, flat and
  as a tree
- `/api/books/meta/` - Metadata about the database
- `/api/books/unified-search/` - Unified book search

Music API endpoints, on `music.acclaimedmedia.org` (at `/api/` on the
apex until 2026-10-30, which now redirects):
- `/api/` - List and filter albums; `?genres=` includes the styles under a
  genre, as the page's filter does (2026-11-11)
- `/api/<slug>/` - Album details with list appearances
- `/api/search/` - Album search
- `/api/artists/` and `/api/artists/<slug>/` - Artists
- `/api/lists/` - Source lists
- `/api/genres/` - Music genres
- `/api/meta/` - Counts and year/decade distributions
- `/api/all/` - Every album in one payload, for client-side filtering
- `/api/unified-search/` - Albums and artists together, for the sidebar
  and mobile search boxes. `order` puts the group with the better match on
  top - exact name, then a word starting with the query, then a substring,
  and last an album found only through its credit line - with artists
  winning a tie (`core/services/search_ranking.py`, which games'
  `/api/unified-search/` uses too). Artists are ordered by
  match, then album count; albums by rank, except an exact title, which
  comes first (by match alone, "Beatles" put Meet the Beatles! at #820 above
  Abbey Road at #4). Albums always came first until 2026-10-29, and an album
  matches on its credit, so "Beatles" filled the five album rows and the
  band sat below the dropdown's fold
- `/api/saved-filters/` and `/api/saved-filters/<pk>/` - a
  reader's saved filter combinations. The only endpoints in `music/api/`
  that **write**, so the only ones CSRF applies to

**Note:** these endpoints carry no `cache_page` decorator, and `/api/all/`,
the heavy one, was measured on 2026-11-09 and left that way. It takes 319 ms
at the median in production (games' cached payload: 54 ms), but is asked for
about 330 times a week, two an hour. An entry kept an hour under its data
version would hit two times in three and save about a CPU-minute a week, for
a generation-guarded cache entry (it would have to be written through
`caching.set_if_current`, hold its version inside one key so a cover pass
does not leave a dead 270 KB row per cover, and drop with `CACHE_KEYS`). Look
again if the traffic grows tenfold.

**Note:** every view in `music/api/` names `SessionAuthentication` (through
`MusicReadAPIMixin` or `MusicWriteAPIMixin`), as books' `StaffReadAPIMixin` does.
`REST_FRAMEWORK`'s `DEFAULT_AUTHENTICATION_CLASSES` is empty project-wide, so a
view that names no authenticator sees a signed-in user as anonymous. On music's
reads that matters to the throttle: `AnonRateThrottle` skips an authenticated
request, so dropping it would put signed-in readers under the 60/minute limit.
On books, whose views declare `permission_classes = [IsStaffOrHide]`, it 404s
staff. The books API shipped that way until 2026-10-17 - its whole read API
was unreachable from a browser - and the tests missed it because
`APIClient.force_authenticate` bypasses authentication entirely. Test API
access with a real session login.
