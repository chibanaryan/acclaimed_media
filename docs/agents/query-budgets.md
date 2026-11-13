<!-- Part of the agent documentation. AGENTS.md keeps each section's rules
     and points here for the reasoning, history and measurements behind
     them. Moved out of AGENTS.md, word for word, on 2026-11-12. -->

# Music and games query budgets

The album rankings cost 443 queries and the artists page 305, measured
against the 1000-album corpus. Both were one-shape N+1s, and both are now
pinned by `music/tests/test_views.py::MusicQueryBudgetTests`. Paths are the
music host's (they were under `/music/` when these were measured), and the
search row is pinned by growth, in `music/tests/test_api.py`:

| page | before | after |
|---|---|---|
| `/` | 443 | 26 |
| `/?genres=<root>` | 439 | 16 |
| `/artists/` | 305 | 6 |
| `/api/all/` | 1218 | 13: 10, and its version read twice since 2026-11-03 |
| `/api/search/?q=` | 3, and one more a result (23 for twenty) | 3 (2026-11-09) |

- **`core/services/genre_tree.py` answers the hierarchy in one query.**
  `descendants_by_id(pairs)` maps every genre id to the ids below it from a
  single `(id, parent_id)` fetch. `MusicGenre.get_descendant_ids` still
  exists for one-off use, but nothing on a hot path calls it:
  `prefetch_related("children")` populates only the rows it fetched, so
  recursing into a child instance's own `children` is a query per node.
  The map is returned in **arrival** order, not the post-order the walk
  resolves nodes in, because callers iterate it to build the counts dict
  the page serializes - and that dict's order has to stay the manager's.
  It carries a cycle guard.
- **Deliberately uncached, in both sections.** Music's needs the whole
  table, where ~200 round trips to the shared cache lose to one SELECT of
  200 two-column rows. Games used to cache descendant ids per genre with
  signal invalidation, and that cache went stale: the filter's key
  (`genre_descendants:<id>`) was not one the signal deleted (`:<id>:True` /
  `:False`), so a re-parented genre filtered by its old tree for 24 hours.
  In production the shared cache is itself a Postgres table, so a hit costs
  a query anyway. `games.services.query_filters.genre_descendant_map()` is
  now one uncached SELECT of ~60 rows, and the signal is gone.
- **`ArtistListView` prefetches `albums` with the MusicBrainz row joined.**
  Needed because both row halves read `artist.albums.first` - the mobile
  card block runs it a second time, which is why it was 200 album selects
  for 100 rows. `{% with best=artist.albums.first %}` does resolve off the
  prefetch cache (measured), so no template change was needed.
- **`/api/all/` had the worst N+1 on the site and nothing recorded
  it**: the album loop reads `album.thumbnail` while the queryset prefetched
  only `artists` and `genres`, so 1000 albums each lazy-loaded their
  MusicBrainz row.
- **Add a filter dimension here and the facet passes multiply.** Build the
  map once per request - `AlbumHomePageView._descendants` and games'
  `HomePageView._genre_descendants` - and pass it in; every consumer
  (`apply_genre_filter` included) takes an optional `descendants=` and
  builds its own only when called standalone.
- **Games' `/` is pinned by
  `games/tests/test_main_views.py::GamesHomeGenreQueryBudgetTests`.** On a
  cold cache it cost 109 queries, 75 of them `games_wikipediagenre`:
  `get_landing_genres` filters once per root genre, and every filter walked
  `children` a query per node. Now 38, and `/?genres=<root>` 109 -> 39,
  each plus the six of the page's data version since 2026-11-03.
  `/api/games/all/` uses `descendants_by_id` too, in place of its own copy
  of the walk.
- **`with_list_count()` is a subquery a row, on games and music**
  (2026-11-12). It was `Count("lists", distinct=True)`: a join to every
  membership, grouped over every column of every game, and `_order_games`
  put a `DISTINCT` on every sort, all before the page's hundred rows were
  taken. That one query was 109 ms of games' 120 ms of SQL. The filters
  that join many-to-many (genres, platforms, series) added their own
  `distinct()` then, and are an `EXISTS` each now (below); an unfiltered
  list has no row twice. On the local copy
  of production's data the first hundred rows with their prefetches went
  from 124 ms to 17.5 ms on SQLite and 54 ms to 20 ms on Postgres 15 (the
  list query itself, 35 ms to 1.1 ms). Pinned by
  `games/tests/test_game_filters.py::RankingsListQueryTests`.
- **A many-to-many filter is an `EXISTS`, not a join** (2026-11-12):
  `query_filters._related_to_any`, for genres, platforms and series. A
  join lists a game once per id it matches, so each filter ended in
  `.distinct()` over every column. On Postgres 15 the list query with two
  platforms went from 7.4 ms to 2.2 ms, about what the unfiltered one
  costs. Write a new filter on a many-to-many the same way.
- **The rest are pinned by growth, not by count**
  (`games/tests/test_query_budgets.py`). Each test renders a page, adds more
  of what it lists, and requires the same query count, so an N+1 fails it
  while an unrelated added query does not. It covers game detail,
  `/developers/` in every sort, `/api/unified-search/`, `/api/games/all/`,
  a decade landing page and music's `/lists/`. Game detail was the one that
  grew: it prefetched one level of each developer's parents, and
  `display_root_developer` queried the rest a level at a time. It now uses
  `with_relations()`, which joins four.

**The games filters are one function**, `games.services.game_filters.
apply_game_filters(qs, params, skip=...)`. It is used by the list, the year,
genre and platform counts (each skipping its own dimension), the CSV download
and the landing pages, as `apply_album_filters` is for albums. The five copies
it replaced had drifted:
- The counts and the CSV searched `name` only, so "pokemon" listed the
  Pokémon games while the counts and the download left them out.
- The counts ignored series and playtime, which the client engine's counts
  always applied, so the server's first render and the client disagreed.
- The CSV ignored the sort.
- The list, the heading and the CSV's file name each had their own
  precedence for `decade`, `year`, `start` and `end`, so
  `?decade=1990-99&year=1995` listed the 1990s under a heading that said
  1995. `query_filters.resolve_year_range` is the one rule, the browser's
  (`currentFilterParams`): a start or an end beats a year, which beats a
  decade. Only a hand-written URL carries two (2026-11-10).
- A range written backwards (`?start=2000&end=1990`, by hand: no control
  writes one) listed nothing, on both sides and both sites, under a
  heading reading "2000-1990". It is the range (2026-11-12):
  `query_params.ordered_range`, in `resolve_year_range` and music's
  `year_window`, and in the browser `getFiltersFromURL`, music's
  `_filtersFrom` and `AlbumFilterEngine.filter`.
- `?platforms=` is platform ids and nothing else. It also took group ids
  (`mfr-nintendo`, `ff-nintendo-home`) until 2026-11-12, which no page
  ever wrote into a link: the heading named the raw id, the engine did
  not know them and the CSV's file name expanded them. The server's copy
  of the platform hierarchy went with them; the sidebar's two
  (`filter-subcomponents.js` and `client-filter.js`'s fallback) are held
  equal by `ClientPlatformHierarchyParityTests`.

Facet cache keys hash every filter parameter except the skipped dimension's
(`facet_params`).
