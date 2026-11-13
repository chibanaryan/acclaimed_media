<!-- Part of the agent documentation. AGENTS.md keeps each section's rules
     and points here for the reasoning, history and measurements behind
     them. Moved out of AGENTS.md, word for word, on 2026-11-12. -->

# Music Data Import

The album rankings come from four TSV files, three of them the same shape the
games importer takes (`acclaimedgames/test_input_files/music/` holds the current
release):

| File | Columns |
|---|---|
| `ArtistInfo.txt` | id, wikidata_ids, name, then any further name variants |
| `ListData.txt` | publisher, year, type, name, url |
| `WebRankings.txt` | rank, name, credits, year, wikidata_ids |
| `ListPositions.txt` | tab-separated `listIndex:position` pairs, one row per album in rank order |

```bash
python manage.py import_music_data            # uses the checked-in release files
python manage.py import_music_data --dry-run  # list types, name variants, artists removed, albums kept/added/removed
python manage.py import_music_data --artists ... --lists ... --albums ... --positions ...
```

The import runs in one transaction, artists first. Lists, list positions and
credits are replaced; artists and albums are updated in place. Four details
differ from the games files:

- **The list type is validated.** Column 3 is All Time, Decade, EOY or Misc,
  as in the games file, but an unknown word fails the import with its row
  number where games stores whatever letter it starts with
  (`parse_lists_file`). Until the 2026-10-29 release the file had no type
  column and the types were guessed from the titles, which filed "The
  AllMusic Decade in Review" as all-time; a file in that layout now fails
  with a message saying so.
- **Artists are the provider's, by id.** `ArtistInfo.txt` lists every act
  under a permanent index (sparse), then its Wikidata ids (comma-separated,
  optional, read with or without the `Q`), then its names. `WebRankings.txt`
  column 3 is `artist,variant` pairs separated by `;`, in credit order, and
  `VA` last for various artists - see "Artist name variants" below.
  `Album.artist_credit` is derived from the credited names as "A", "A & B",
  "A, B & C", with "Various Artists" as a last name (`credits.credit_text`).
  Either file in its pre-2026-10-28 layout fails with a message saying so.
- **Artists are upserted, not replaced.** Matched on `source_id`; a row that
  predates the ids is adopted by Wikidata id, exact name, then normalized name,
  so pks survive. **Slugs are not kept**: they follow the current names
  (`music.services.artist_slugs`), rebuilt by every import and again after
  every Wikidata pass, and the admin cannot edit them. Same-named acts are
  told apart the way Wikipedia does it: the one whose English Wikipedia
  title (`Artist.wikipedia_title`, from the enwiki sitelink) is the bare
  name keeps the plain slug, the others take their titles
  ("nirvana-british-band"); with no bare-name title the lowest provider id
  keeps the plain slug, and only an act with no usable title is numbered. Names go through unidecode ("royksopp"). A
  replaced slug redirects to the new one (see "Access"). `--dry-run` lists the slugs that
  would change. An artist the file does not list is deleted,
  with its page.
- **A provider id is permanent.** The import trusts that: a row updates
  whichever artist holds its id. One that shares no Wikidata id and no
  normalised name with what is stored is reported - "may have been reused"
  in the import message, `!` in `--dry-run` - but still imported, since a
  rename can do that too.
- **Albums are upserted, not replaced.** `match_albums` pairs each row with
  the stored album carrying any of its Wikidata ids (`Album.wikidata_qids`,
  the primary and every id in `all_wikidata_ids`), primary id first; an album
  is claimed by one row at most, so a split row gets a new album. A matched
  album has its rank, name, year, ids and credits rewritten and keeps its pk
  and slug - and so its metadata pointers, genres, release date, covers and
  tracking rows. A row no id matches then tries `models.release_identity`
  (its artists' provider ids, whether it is a compilation, and its title
  without accents, case, punctuation or spaces) and its year against the albums still
  unclaimed, provided the row or the album has no QID to disagree; a row
  matching two albums is new. That keeps an album
  without a QID, which was recreated every import until 2026-11-01, and one
  the release gives or takes a QID. Albums the file drops are deleted
  (before any are created, so a new album can take a dropped one's slug). The message, `--dry-run` and the staff import page all report
  "N kept, N added, N removed". Until 2026-10-23 every import deleted every
  album, and the next metadata run spent ~22 minutes re-fetching MusicBrainz
  for all of them.

Unranked lists record every member at rank 1, matching the games convention.

**An import re-adopts tracking rows.** A kept album keeps its
`ListenedAlbum` / `WantToListenAlbum` rows outright. An album the release
drops is deleted and its rows wait on `SET_NULL`, so `import_albums` still
runs `music.services.user_tracking_service.reconnect_tracking_records` as the
safety net: when the album comes back it reconnects them by Wikidata id -
normalising a secondary id to the primary, renaming a kept album's rows when
it gains or loses a QID (`pk:<id>` to the QID, or back), and merging two rows
that now point at one album, earliest kept. A row on a QID-less album the
release drops is keyed on a pk that is gone, so it stays orphaned. A row that is already right is skipped,
so its user's caches are not dropped for nothing; the users whose rows a
removal orphaned have theirs dropped instead, since their cached sets name
the deleted pks. `import_batch` drops them with the section's keys, in one
call, once it has committed: dropped inside the transaction, a page load
before it commits would refill them from the old rows. The pass is behind a
one-query existence check, so an untracked database pays nothing.

**Imports start their metadata fetch** (2026-11-03). A kept album needs
none - its rows, genres and covers never left it - so after a release that
mostly repeats the last, `fetch_album_metadata --with-musicbrainz` skips
nearly everything: about a minute of Wikidata and the corpus-wide rebuilds,
plus a few seconds for each added album, which renders with placeholder
artwork and no genres until it lands. An album returning from an earlier
release has its old rows waiting as orphans, and every pass adopts them by
external id before fetching: Wikidata and Discogs by their ids, and covers and
MusicBrainz by `release_group_mbid` through `_musicbrainz_record`, which
adopts the *whole* row - title, dates, genres and cover ids - rather than
making an empty one and letting the cover pass copy only the cover ids across.

So an import runs that fetch itself (`music/services/post_import.py`), and a
games import runs games' (`games/services/post_import.py`): IGDB, Wikipedia
and HLTB, each missing-only. A games import recreates every `Game` and
reattaches the stored IGDB, Wikipedia and HLTB rows; the slug, developers and
series live on `Game`, so it carries them across too, keyed by the IGDB record
each came from (`_igdb_fields_by_record`), and a kept game is whole the moment
the import commits. Only to a game whose primary id is that record's: one the
release gives a new primary id reattaches its old id's record, which is
another IGDB game, so it carries nothing and is fetched. Until 2026-11-03 it did not: every game linked to
`/games/None/` until a forced IGDB pass restored them, under three minutes on
the free tier, or until Sunday if the fetch died. "Missing" for IGDB is
`Game.objects.needing_igdb()`: no IGDB row, one but no slug, which a fetch
cut short leaves, or one for another of the game's ids; the button, its count
and `get_igdb` all use it.

- **The commands fetch in the foreground**, after the import's own output;
  `--no-metadata` skips it, and `--dry-run` never fetches.
- **The staff pages fetch on a background thread**
  (`core.services.post_import.schedule_after_commit`), started once the
  import commits and only when the games file was part of it. The page says
  so: music's summary, games' success message or the streamed import's toast
  (a `metadata` event). Open the page again to watch the counts fall; the
  lines never say "reload", since music's import result is the POST's page.
- **One fetch per section at a time**, across workers and dynos, the
  commands' included: a `cache.add` lock on the shared `default` alias. An
  import while one runs starts none, says so, and asks the running one to go
  round again when it finishes. Skipping it was not enough: the running round
  works from the rows it read as it began, so it would leave the games or
  albums the later import added without their metadata.
- **Every metadata pass but a manual command's takes that lock**: the
  import page's IGDB and Wikipedia buttons and the weekly jobs
  (`refresh_all_metadata --weekly`, `fetch_album_metadata --weekly`) take
  it through `post_import.hold` and `run_weekly`, so none runs beside an import's fetch and
  doubles the rate limit and the connections. A button pressed while it is
  held says so and starts nothing; a weekly job waits up to an hour, then
  gives up the week at ERROR, and runs without the lock if the cache
  fails. One that held it while an import asked for a fetch runs that fetch
  before letting go. Only the weekly music run takes
  it: an import's music fetch *is* `fetch_album_metadata`, run under it.
- **The lock's `add` cannot be won twice.** On the database cache an `add`
  over an expired row is a SELECT then an UPDATE, so two imports in the
  same instant after a lapse could both take it. `_add` first deletes the
  row only if it has expired, which leaves an INSERT the primary key fails.
- **The lock lives two minutes, and a heartbeat touches it every 30 s.** A
  first version held it for the longest fetch, two hours, so a fetch killed
  with its worker told every import in that time that it would go again.
  The heartbeat only touches (a `set` could recreate the lock just after the
  fetch released it), so a lock the cache culls stays culled. A release
  re-checks for an import that asked as it let go, and an import that asks
  tries the lock once more after, in case the fetch let go in between.
- **A failure is reported, not hidden.** Each job returns the steps that
  failed; they are logged at ERROR, for Sentry, since staff were told the
  fetch was under way, and the commands print them as warnings, never as a
  failed import. `get_igdb` reports a service it cannot start (expired
  credentials) and returns normally, and one whose requests start failing
  part way catches each batch's error, so the slugs are the test: more than
  `SLUGLESS_TOLERANCE` (10) games left without one counts as `get_igdb`
  failing. Fewer is only a warning: IGDB can stop returning a game, and
  counting that a failure would alert on every import.
- **HLTB's saves leave a connection on asgiref's executor thread**, which
  outlives the fetch: `fetch_hltb_data` saves through `sync_to_async`, and
  outside an async server that runs on one thread for the process's life.
  `games.services.post_import` closes it there afterwards.
- **A games fetch moves the data version twice**: as soon as the IGDB pass
  has given the added games slugs, raised part way or not, and again at the end.
  `get_igdb` saves slugs with `update_fields`, which leaves `modified` alone,
  and Wikipedia's genres for the added games move nothing the version reads,
  so a page or `/api/games/all/` payload cached during the fetch would go on
  serving `/games/None/` links, or the new games without genres. Each move
  touches one game's `modified`, which moves `Max(modified)` as well as all
  1400 would.
- **It runs inside a web worker**, so it spends from the 512 MB budget (see
  "Production memory budget"). Either fetch peaked at ~173 MB for a whole
  process that idles at ~87 MB, so ~85 MB on top of a worker for a minute
  or three. Music's did not, at first: the Wikidata pass held every album's
  and artist's raw entity until the last batch landed, ~415 MB, and
  `WikidataClient.fetch_entities` now keeps only the claims its callers
  read (`keep_claims`), as each batch arrives.
- **A deploy or a worker recycle kills the thread** (it is a daemon), and the
  lock lapses within two minutes. Each round sets a pending marker as it
  starts and clears it before letting go, so the marker without the lock is
  a fetch that died, and the import page's next load restarts it
  (`post_import.resume_if_cut_short`), saying so; staff reload that page to
  watch a fetch land anyway. The marker counts restarts, and a restart cut
  short too is left to the Sunday job, at ERROR and said once on the page:
  a fetch that takes its worker down would otherwise take one down on every
  reload. The page reads the marker again under the lock, so two loads
  cannot both restart a fetch. A button's or a weekly job's hold runs a
  fetch owed when it lets go: one an import asked for meanwhile, or one cut
  short. It is missing-only, so after the weekly work it costs little, and
  the weekly's own step failures are warnings that cannot say whether it
  did the fetch's work. A weekly job drops only a given-up marker, the one
  the page said was left to it; if its work raised, it leaves the fetch to
  the page. An import's request starts the count afresh. One rule decides what is owed, and at what count
  (`_owed`), and the fetch's rounds, the page and a hold all let go through
  `_let_go`, which takes the lock back for an import that asked as it went. A start that
  fails is logged and reported, never as a failed import, since the release
  is live by then. A fetch whose thread or heartbeat will not start leaves
  the marker at the count it was to run at, so the page's next load tries
  it again; the page says that, never "reload", since music's import result
  is the POST's page. "Run it by hand" is said when the marker could not
  be written, the cache being down. A hold whose lock
  the cache culled and another fetch or hold then took leaves everything
  owed, marker included, to that holder, since the marker may be its own.
- **`METADATA_AFTER_IMPORT`** turns all of it off. It is off under test,
  where there is no network; the tests of the feature turn it on and patch
  the fetch. `scripts/setup_cloud.sh` passes `metadata=False`, having no
  credentials.

The import pages keep their manual controls: games' "Metadata Operations"
buttons, and music's missing counts with the command to run.

**A cache error does not fail a committed import.** The release is live by the
time `import_batch` drops the caches, and staff told it failed would re-run
it, so `invalidate_release_caches` logs the error and returns `False`, and
the import returns a warning: an amber alert on the staff page, `style.WARNING`
from the command. The fix it names is `python manage.py clear_music_caches`,
which does only that, readers' sets included, and exits non-zero if it fails
too. `fetch_album_metadata`
and `rebuild_album_genres` get the same protection from
`invalidate_music_caches`, and print the same warning, so a cache error no
longer stops the weekly job before its dates and slugs. If the database connection
itself has died, the staff page's own queries after the import can still fail;
the release stands.

The import stamps `SiteMetadata` under the `music` key, which the rankings
heading reads as "Updated: ...". `SiteMetadata` is keyed per section, so
games and music carry their own dates.

### Artist name variants

Since the 2026-10-28 release an artist carries every name it is credited
under, and a credit names the artist *and* the name: `8,1` is artist 8,
Prince, under name 1, "Prince and the Revolution". Most credits are `,0`,
the artist's own name. This replaced the relation tags of 2026-10-23
(alias/project/collaboration/featuring/backed-by, `ArtistRelation` and an
`ArtistGraph` roll-up), in which Prince and the Revolution was an artist of
its own tagged as a project of Prince; those acts were deleted by the
import, and their pages 404 (music was still the staff beta).

- **An album belongs to exactly the artists it credits**, under whatever
  name, so there is no walk and no expansion: `?artists=` is a plain join on
  both sides, an artist's page and counts come from one read of
  `AlbumCredit` (`credits.album_ids_by_artist`), and "More by" is the credited
  artists. Nobody "appears on" anything any more.
- **The credit line shows the credited name and links to the artist**:
  "Prince and the Revolution" goes to `/artists/prince/`, titled
  "Prince". `artist_links` server-side, `_artistCreditHtml` client-side, from
  the `"cv"` names `/api/all/` sends for the albums that need them.
  Album detail adds an "Artist:" row naming the artist when the credit uses
  another name.
- **`VA` is the last credit**, alone on a compilation and after the named
  artists on a soundtrack ("Jimmy Cliff & Various Artists"). It sets
  `Album.various_artists` (`"va"` in the payload) and is rendered unlinked.
- **Some variants are unused**: kept for albums outside the ranking, or left
  over from the tag system ("The Velvet Underground & Nico" - that album is
  credited to each artist separately). "Also credited as", on the artist
  page and row, and the artist search therefore read the names credits
  actually use (`AlbumCredit.credited_name`, `credits.variant_names_by_artist`),
  not `Artist.name_variants`.
- The release's Wikidata ids describe the artist, not its names, so there is
  not one per name. The first is `Artist.wikidata_id`, which the Wikidata
  pass reads for the MusicBrainz id.
- **Albums credited with other artists are listed apart**, under "With
  other artists" on the artist page and `with_other_artists` in the API
  (`credits.split_by_credit`): Getz/Gilberto on Stan Getz's. A `VA` tail
  names nobody else. They still count, in the total and the chart.
- **No artist pk is public.** The pks were handed out in the provider's
  entry order, which he does not want visible. `?artists=` takes slugs
  only - a pk would let anyone read the order back one link at a time - and
  a hidden form field carries it through later filter changes;
  `/api/all/` keys its artists table by slug and lists slugs in
  `"ar"`; no artist serializer has an `id`. A slug rebuild touches its
  albums' `modified`, so the payload version moves with it.
- The provider mentions a members list per artist for a future "See also";
  no file carries it yet.

The credit line's separators are `credit_separator` on both sides;
`core/tests/test_filter_parity.py` renders every album's line through both
and requires them equal.

The Wikidata pass no longer touches album credits. It reads each artist's
MusicBrainz id (P434) and English Wikipedia title off the artist's own QID
and stores only those, so an artist with no label is not skipped. A genre's
or a record label's name is the `en` label, else the language-neutral `mul`
one (`wikidata.LABEL_LANGUAGES`): Wikidata has moved names that read the
same in every language there and dropped their `en` label. Until 2026-11-02
the pass read `en` alone, dropped punk rock, and skipped 27 artists,
Radiohead and Rihanna among them.
