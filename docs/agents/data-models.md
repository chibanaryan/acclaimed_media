<!-- Part of the agent documentation. AGENTS.md keeps each section's rules
     and points here for the reasoning, history and measurements behind
     them. Moved out of AGENTS.md, word for word, on 2026-11-12. -->

# Data Models

Core Django models include:

- **Game** - Video games with ranking, IGDB integration, genres, platforms, and developers.
  `igdb_id` and `slug` are unique where set (`unique_game_igdb_id`,
  `unique_game_slug`, since 2026-11-10): the played toggle finds a game by
  the one and the detail page by the other, and a second row was a 500. A
  slug IGDB gives that another game holds takes the IGDB id as a suffix
  (`Game._free_slug`), and a games file whose rows share a first IGDB id is
  refused with both rows named (`ImportFileError`)
- **Developer** - Game development entities with hierarchical parent-child relationships
  - Uses self-referential `parent` FK for ownership hierarchy
  - Root developers (parent=None) have slugs for URL routing (e.g., Nintendo, Valve)
  - Subsidiary developers (parent=Developer) are child entities (e.g., Nintendo EAD, Respawn)
  - Games link to developers via `Game.developers` M2M field
  - In IGDB's data model, all are "company" records - we add hierarchy on import
  - `igdb_id` and `slug` are unique where set; a subsidiary's slug is NULL or
    `""` (294 rows), so the slug's constraint leaves both out. A slug goes
    to the developer IGDB names for it: a row still holding it, which may
    never be refreshed again, is moved to `<slug>-<its IGDB id>`
- **Platform** - Gaming platforms (PC, PS5, etc.)
- **WikipediaGenre** - Game genres, hierarchical (`parent`, `level`, `path`)
- **Series** - Game series, from IGDB's collections, made or updated by
  `Series.from_igdb`: name and slug are unique, IGDB's names are not, so a
  second collection of a name takes its IGDB id in both
- **IGDBGameData / WikipediaGameData / HLTBGameData** - Fetched metadata, each
  with a `primary_...` pointer on `Game`. They outlive an import, which
  recreates every `Game` and reattaches them. `IGDBGameData.summary` is
  IGDB's summary of the game, for the page's description (2026-11-12, see
  "IGDB Integration"): on the record and not on `Game`, for that reason
- **Publication** - Magazines/websites that publish game lists
- **List/ListMembership** - Published rankings and game positions within them
- **PlayedGame / WantToPlayGame** - Per-user tracking, keyed on the IGDB id so
  it survives an import
- **SavedFilterSet** - A reader's saved filter combinations
- **Article** - Blog posts, at `/blog/`
- **Post** - The older news posts. `/news/` answers 410; subscribers are still
  notified of a new one
- **SiteMetadata** - Per-section "Updated" dates
- **Snippet** - Reusable text snippets

Books-specific models (behind `BOOKS_ENABLED` feature flag):

- **Book** - Book items with ranking, author, genre, and metadata integration
- **Author** - Book authors with hierarchical parent-child relationships (similar to Developer)
- **BookGenre** - Hierarchical book genres with path denormalization
- **BookSeries** - Book series with position tracking
- **BookListMembership** - Book positions within lists
- **ReadBook/WantToReadBook** - User tracking for books (like PlayedGame/WantToPlayGame)
- **WikipediaBookData** - Wikipedia metadata for books

Music-specific models:

- **Album** - Albums with ranking, a derived credit line, credited artists, genres, and Wikidata/MusicBrainz ids. Its slug is unique (`unique_album_slug`)
- **Artist** - Every act in `ArtistInfo.txt`, keyed on the provider's permanent
  `source_id`, with `name_variants` (every name it is credited under, the first
  its own) and `all_wikidata_ids`. Every artist has a slug and a page; there is
  no parent FK and, since `0009`, no relation table
- **AlbumCredit** - the through table of `Album.artists`: the credit order, the
  `variant` the release names and its `credited_name` (Purple Rain: Prince, as
  "Prince and the Revolution"). Read `album.credits.all()` or
  `album.credited_artists`, not `album.artists.all()`, which is alphabetical
- **MusicGenre** - Hierarchical music genres with path denormalization
- **MusicPublication/MusicList/AlbumListMembership** - Album rankings and positions within them
- **WikipediaAlbumData/DiscogsAlbumData/MusicBrainzAlbumData** - fetched metadata on
  `ExternalDataBase`, each with the `primary_…` OneToOne fast-path and the
  `unique_primary_…_per_album` partial constraint. An import keeps every album it
  matches, so its rows stay attached. All use `on_delete=SET_NULL`, so the rows of
  an album a release drops survive it, and every metadata pass re-adopts them by
  external ID if the album comes back
- **AlbumCover** - the cover-art bytes at two sizes, keyed by the Cover Art Archive's
  own release MBID, image id and size rather than by album, so they also outlive
  their album's deletion
- **ListenedAlbum / WantToListenAlbum** - per-user tracking on
  `core.models.UserTrackingBase`, as books' pair is and games' predates. Each
  keeps a nullable `album` FK **and** the album's `wikidata_id`, because an
  import deletes the albums a release drops: the rows survive on `SET_NULL` and
  `music.services.user_tracking_service` re-adopts them by that id if the
  album comes back. The column holds `Album.tracking_key`: the primary QID, or
  `pk:<id>` for an album the release gives none, which the import keeps by
  its artists and title so the pk lasts. Before 2026-11-01 a QID-less album
  had no button and the toggle refused it, so on its page the only button was
  a "More by" row's, for another album (Blumfeld's 'Old Nobody' marked
  'L'Etat Et Moi'). Key a tracking row on `tracking_key`, never on
  `wikidata_id`.
  Mutual exclusivity is enforced by the toggle view, not by a constraint -
  they are separate tables, so no one constraint spans them. "Have" (an album
  the user owns) is a `ListenedAlbum` row with `owned=True`, not a third
  table, so it inherits the reconnection pass and the bulk command unchanged
