<!-- Part of the agent documentation. AGENTS.md keeps each section's rules
     and points here for the reasoning, history and measurements behind
     them. Moved out of AGENTS.md, word for word, on 2026-11-12. -->

# Music Metadata Pipeline

An import runs `/music-metadata` (`python manage.py fetch_album_metadata
--with-musicbrainz`) itself; see "Imports start their metadata fetch".
Nearly every album carries a Wikidata QID, which supplies the Discogs and
MusicBrainz identifiers the other sources are keyed by. Two fallbacks fill
its gaps. An album with no MusicBrainz release group (P436) is searched for
by title and artist in the cover pass. An album with no Discogs master
(P1954), or one Discogs now 404s, takes the master its MusicBrainz release
group links (`MusicBrainzClient.fetch_discogs_master_id`), and
`Album.discogs_master_id` follows the master the data came from. On
2026-11-02 that filled all nine albums Discogs had nothing for, two of them
on dead Wikidata masters, which the Wikidata pass writes back every week;
the Discogs pass then pays one 404 and one MusicBrainz request for each, and
relinks the stored row. The Wikidata pass skips an album the release gives
no QID ('Old Nobody') rather than failing on it.

Each pass keeps an album's failure to that album, in a savepoint
(`AlbumMetadataService._for_one_album`): until 2026-11-11 only the Wikidata
pass did, and one database error ended the cover, Discogs or MusicBrainz
pass and skipped the command's genre rebuild, dates, slugs and cache drop.
**An album's requests are made before its savepoint opens** (2026-11-12):
`_for_one_album` takes a `fetch`, which reads and requests and never
writes, and hands its answer to the step that saves. Inside, a cover pass
walking a group's releases held a connection in a transaction for tens of
seconds. A new pass does the same: network in `fetch`, writes in the step.

Four passes, selectable, because their costs differ by two orders of magnitude:
Wikidata is ~25 batched requests (seconds), cover art ~1000 downloads (~18 min),
Discogs ~500 requests at 25/min anonymous (~23 min), and MusicBrainz ~500 at its
hard 1 req/sec cap (~9 min, opt-in via `--musicbrainz` alone or
`--with-musicbrainz` alongside the rest). Set `DISCOGS_TOKEN` to raise the
Discogs limit (production has one); the client paces itself from the response
headers either way.

**It runs weekly on Heroku Scheduler**, as games' `refresh_all_metadata` does:
a daily job, `python manage.py fetch_album_metadata --weekly --with-musicbrainz
--refresh-stale 125`, where `--weekly` exits at once on any day but Sunday
(UTC) - the add-on has no weekly frequency. It is deliberately not `--force`:
every pass but Wikidata skips records that already landed, so a routine run
costs Wikidata's ~25 requests plus whatever an import left missing, then the
genre rebuild and the cache invalidation - about a minute, nearly all of it
Wikidata's network time. A full re-fetch stays a manual `heroku run:detached`.
The Sunday gate is `core.services.monitoring.skips_today`, for both weekly
commands, on UTC's day.

The command fails (`CommandError`) when the Wikidata pass lands nothing,
inside the cron check-in and after the lock is let go, as games' job does:
that pass attempts every album on every run, so one that lands none could
not run. Until 2026-11-10 it exited 0 with Wikidata down and every album
failed. One album picked with `--slug` that lands nothing is that album's
QID gone, and fails nothing; several that all land nothing are an outage.
With no QID among the albums selected there was nothing to attempt, and the
pass reports them skipped. The other passes attempt only what is missing, and a week's only
cover work can be the two albums with no cover anywhere, so errors on some
albums fail nothing.

`--refresh-stale 125` is the one deliberate re-fetch: the MusicBrainz pass
also re-reads the 125 albums whose rows have the oldest `updated_at`, ~2
minutes at 1 req/sec, so the corpus cycles every eight weeks. Since imports
keep albums in place a MusicBrainz row would otherwise be fetched once and
never again, while its genre tags keep gathering votes; before 2026-10-23 the
orphan bug re-fetched everything after every import, which hid that. Covers
and Discogs are not refreshed: covers do not change, and the Discogs reading
below rests on what we display, not on freshness. Wikidata already re-reads
everything every run.

Decisions worth knowing before changing any of it:

- **A style's root is corrected in place.** `get_or_create_genre` used to
  return an existing genre row untouched, so a style first created under the
  wrong root kept it forever: "Alternative Rock" sat under Electronic for 68
  albums long after the resolution order was fixed, because the fix could not
  reach a row that already existed. It now re-parents a row whose root has
  changed, `level` and `path` with it.
- **Genres are our own vocabulary, voted on by three sources.**
  `music/services/genre_normalizer.py` names every genre the filter offers -
  16 roots and about 125 leaves - and classifies each source label as a leaf,
  an alias of one ("Glam" -> Glam Rock, "thrash metal" -> Thrash Metal), a
  root ("hip-hop", "rock music"), or a label dropped on purpose ("Vocal",
  "Classic Rock"). An unclassified label creates nothing. When every Discogs
  style became a row of its own the tree had 207 leaves, 73 of them holding a
  single album, and an unmapped style took its root from the album's own
  Discogs genres, which filed Bubblegum under Electronic and Son under Jazz.
  Discogs styles are the **base** and are kept whole. Wikidata P136 and
  MusicBrainz genres can only **add**: a leaf another source also names, a
  root two sources support, or a leaf for an agreed root with nothing under
  it. A stricter "two sources must agree" rule was tried and dropped real
  genres, because Wikidata names a single genre for over half the albums
  (*Purple Rain* lost Funk). Leaves held by fewer than `MIN_LEAF_ALBUMS` (3)
  albums are pruned, and their albums keep the root. Wikidata alone is no
  better a source: it has *more* distinct labels than Discogs (272 against
  222), and its P279 graph classified only 159 of 207 genre entities, put
  thrash metal under Rock, and left ska, dub and ambient unreachable.
- **Classifying a label is not free, even when the label is rare.** Discogs'
  top-level genres count as a vote, and they are coarse: "Rock" supports
  Punk and Metal, "Folk, World, & Country" supports World. So one
  MusicBrainz tag read as a World or Punk leaf can tag an album on its own
  ("tejano" as Latin put Marty Robbins under World). Read the per-album diff
  from `rebuild_album_genres --dry-run --report`, not just the counts.
- **The tree stays two levels and single-parent; hybrids tag extra roots.**
  `HYBRID_ROOTS` gives Folk Rock, Country Rock, Synth-pop and a few others a
  second root on the *album*, not a second parent on the genre, so *Harvest*
  is under Rock, Folk and Country, while the shared tree, `genre_tree.py` and
  the client payload keep assuming one parent.
- **Genres are rebuilt offline, corpus-wide.** The passes only store what
  they fetch. `python manage.py rebuild_album_genres` (run automatically at
  the end of `fetch_album_metadata`) derives every album's genres from the
  stored rows in seconds, with no network. `--dry-run --report` shows the
  diff, the pruned leaves and any unclassified label - a new release's new
  labels show up there and fail `RealVocabularyTests`. The rebuild renames
  an alias's row in place, so its id survives, and remaps
  `SavedAlbumFilterSet` genre ids that point at deleted rows.
- **Cover art is downloaded, not hotlinked.** The Cover Art Archive redirects to
  archive.org, which 500s on roughly one request in ten and has a few items
  broken outright, so a hundred-cover page broke visibly on every load. The bytes
  live in `AlbumCover` and `music.views.AlbumCoverView` serves them. Downloading
  doubles as verification, and there are three fallbacks: the release group's own
  art, then any release in the group (earliest first), then a MusicBrainz search
  by title and artist for albums whose Wikidata entity has no P436. A download
  is kept only as an image under 5 MB (`COVER_CONTENT_TYPES`,
  `COVER_MAX_BYTES`), and `AlbumCoverView` serves only those types: the
  bytes are served from this origin with the type the remote sent, so an
  error page answered with a 200 would otherwise be our HTML. The download
  is streamed and given up on past the ceiling (`get_bytes`), so the ceiling
  bounds what a download costs a worker, not only what is stored.
- **A `front` flag is not a sleeve.** The archive tags each image with types,
  and a front can also be `Obi`, `Sticker` or `Spine` (a Japanese pressing,
  shrink-wrap, a cassette J-card) or `Back`/`Medium` (a photo of the whole
  package - "It Takes a Nation of Millions" showed its jewel case and disc).
  `musicbrainz.cover_quality` ranks them; anything short of a clean scan sends
  the pass on through the releases for one, and keeps the best it found
  rather than none. A cassette's J-card is tagged a plain `Front`, so the
  release walk also puts cassette releases last (`inc=media` on the browse).
  An audit of 1000 covers found 27 non-plain fronts, 18 of them harmless
  `Booklet`/`Track` scans. Re-pick an album with
  `--covers-only --force --slug <slug>`, since a stored cover is otherwise skipped.

`Album.cover_image_url` keeps the remote URL for the API, and as the fallback;
`Album.thumbnail` and `Album.image` are what the pages render and prefer the local
copy. `Album.image_og` is `image` made absolute on `CANONICAL_ORIGIN`, for
Open Graph and the JSON-LD.

### Discogs API terms

Discogs' [API Terms of Use](https://support.discogs.com/hc/en-us/articles/360009334593-API-Terms-of-Use)
(last updated 2025-05-27; their site 403s automated fetches, so read it in a
browser) ask for two notices, both rendered and both pinned by
`music/tests/test_discogs_attribution.py`:

- **The non-affiliation notice, verbatim and prominently**: "This application
  uses Discogs’ API but is not affiliated with, sponsored or endorsed by
  Discogs. ‘Discogs’ is a trademark of Zink Media, LLC." `base.html` renders
  `music/includes/_discogs_notice.html` at the foot of every music page.
- **"Data provided by Discogs" directly beside the data**, linking to the
  discogs.com page that holds it, never `rel="nofollow"`.
  `core/includes/_data_credit.html` is the one markup for it. Album detail
  puts it under the genre badges, linked to `Album.discogs_master_url`. The
  list pages put one "Genres use data provided by Discogs" line beside the
  genre filter (the shared `_genre_filter.html` / `_mobile_filter_genres.html`
  take `data_credit_text` / `data_credit_url`, so games shows none) and
  above an artist's albums. Rows and cards carry no per-row credit, which
  would add ~100 links of HTML to every page.

We use no **Restricted Data** (user, marketplace and image data): covers come
from the Cover Art Archive, and genres and styles are not in the restricted
list, so the ban on commercial use of Restricted Data does not bite. The terms
also say content may not be displayed "more than six (6) hours older" than
discogs.com, nor stored "longer than is necessary". Our reading: what the site
displays is its own genre vocabulary, derived by `rebuild_album_genres` from
three voting sources, not Discogs content verbatim; the verbatim
`DiscogsAlbumData` rows are kept as provenance and to rebuild offline. The
weekly Heroku Scheduler job does **not** refresh them: without `--force` the
Discogs pass skips albums that already have a row, so each master is fetched
once and re-fetched only by a manual
`fetch_album_metadata --discogs-only --force`. The reading therefore rests on
what we display, not on how fresh the stored copy is. Revisit this if Discogs
content is ever shown as-is.
