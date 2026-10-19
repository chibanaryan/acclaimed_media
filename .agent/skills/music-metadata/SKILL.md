---
name: music-metadata
description: Fetch album metadata from Wikidata, Discogs, MusicBrainz and the Cover Art Archive. Use when asked to fetch, import, or refresh music or album metadata, cover art, or music genres.
---

# Album Metadata Fetch

Populates album cover art, genres, artists, release dates and labels for the
`music/` app. Every album in the ranking carries a Wikidata QID, which is the
hub: it supplies the Discogs and MusicBrainz identifiers the other sources are
keyed by, so no title matching is ever needed.

## Basic Usage

```bash
# Wikidata, cover art and Discogs. Skips MusicBrainz enrichment.
python manage.py fetch_album_metadata
```

## Command Options

| Option | Description |
| --- | --- |
| `--album NAME` | One album by name (case-insensitive) |
| `--slug SLUG` | One album by slug |
| `--id N` | One album by primary key |
| `--limit N` | Process at most N albums |
| `--offset N` | Skip the first N albums |
| `--force` | Re-fetch albums that already have data |
| `--skip-existing` | Only albums with no Wikidata record yet |
| `--dry-run` | Report what would be fetched, change nothing |
| `--wikidata-only` | Run only the Wikidata pass |
| `--covers-only` | Run only the cover-art pass |
| `--discogs-only` | Run only the Discogs pass |
| `--musicbrainz` | Run the MusicBrainz enrichment pass |

## Examples

```bash
# One album, re-fetching everything
python manage.py fetch_album_metadata --slug pet-sounds --force

# Just the cheap pass, to pick up new identifiers
python manage.py fetch_album_metadata --wikidata-only

# Backfill cover art after an import (re-adopts stored images, no downloads)
python manage.py fetch_album_metadata --covers-only

# Opt into the slow enrichment pass
python manage.py fetch_album_metadata --musicbrainz
```

## The Passes

They are separate because their costs differ by two orders of magnitude.

| Pass | Requests | Time (500 albums) | What it writes |
| --- | --- | --- | --- |
| `wikidata` | ~25 | ~30s | `WikipediaAlbumData`, both external IDs, `Artist` rows |
| `covers` | ~1000 | ~18 min | `AlbumCover` bytes, `MusicBrainzAlbumData` cover ids |
| `discogs` | ~500 | ~23 min anonymous | `DiscogsAlbumData` (styles and top-level genres) |
| `musicbrainz` | ~500 | ~9 min | release type, exact date, rating, genres (by vote) |

After any run that includes `wikidata`, `discogs` or `musicbrainz`, the
command runs `rebuild_album_genres`, which derives every album's genres from
what the passes stored. See [Genres](#genres).

Wikidata is batched 50 entity IDs per request, which is why it is seconds
rather than minutes. The default run omits `musicbrainz`: it is enrichment,
and its hard 1 req/sec cap would dominate a routine refresh.

## Data Sources

| Source | Auth | Rate limit | Coverage of the 502 QIDs |
| --- | --- | --- | --- |
| Wikidata | none | 1 req/sec, batched 50 | P175 502, P577 502, P436 500, P1954 498, P136 499 |
| Cover Art Archive | none | none documented | front art for essentially all |
| Discogs | optional token | 25/min anon, more with a token | 498 master IDs |
| MusicBrainz | none | **hard 1 req/sec**, 503 past it | 500 release groups |

Set `DISCOGS_TOKEN` (free, from discogs.com/settings/developers) to raise the
Discogs limit. The client reads `X-Discogs-Ratelimit` off each response and
paces from it either way, so the token changes speed and nothing else.

## Genres

Genres are **our own controlled vocabulary**, and the three sources vote on
which of its genres an album gets. `music/services/genre_normalizer.py` holds
all of it:

| Table | What it holds |
| --- | --- |
| `GENRE_VOCABULARY` | root -> {leaf: aliases}; the only genres that exist |
| `ROOT_ALIASES` | labels that mean only a root ("hip-hop", "rock music") |
| `DROPPED_LABELS` | descriptors and data errors, dropped on purpose |
| `HYBRID_ROOTS` | leaves that also tag a second root on the album |
| `DISCOGS_GENRE_ROOTS` | Discogs' top-level genres, as evidence for roots |

Labels are compared by `label_key`, which folds case, hyphens, `&`/`and` and
Wikidata's " music" suffix, so `Hip-Hop`, `hip hop` and `hip-hop music` are
one key.

**The vote** (`choose_album_genres`). Discogs styles are the base and are
kept whole. Wikidata P136 and MusicBrainz genres (top 5 by votes) only add:
a leaf another source also names, a root two sources support, or a leaf for
an agreed root that has none. Nothing outvotes Discogs. Wikidata names a
single genre for over half the corpus, so letting it veto dropped real
genres. Leaves with fewer than `MIN_LEAF_ALBUMS` albums are then pruned
corpus-wide, and their albums keep the root.

**Rebuilding.** No network, seconds:

```bash
python manage.py rebuild_album_genres --dry-run --report   # diff, pruned leaves, unclassified labels
python manage.py rebuild_album_genres                       # apply
```

**Adding to the taxonomy.** A new release brings new labels. They show up
under "Unclassified labels" in the report, and
`music/tests/test_genre_normalizer.py::RealVocabularyTests` fails until each
is classified. Add each label as a leaf, an alias, a root alias or a dropped
label, then add it to that test's `DISCOGS_STYLES` / `WIKIDATA_LABELS` list.
Renaming a leaf is safe: the rebuild renames a row whose name has become an
alias, so the genre's id - which `?genres=` URLs and saved filters hold -
carries over.

A new **root** genre also needs an entry in
`music_filters.MUSIC_GENRE_CATEGORY_ICONS` and a re-run of
`./scripts/build_mdi_subset.sh` — the icon font is a subset, so an unlisted
glyph renders as a blank box.

## Cover Art

Cover art is **downloaded and served from our own origin**, not hotlinked.

The Cover Art Archive is the right source, but it answers with a 307 to
archive.org, which returns an intermittent 500 on images that are present a
moment later — measured at roughly one request in ten, with a few items broken
outright. On a list page showing a hundred covers that guarantees visible
breakage on every load.

So the pass downloads two sizes (250px for rows, 500px for the detail page)
into `AlbumCover` and `music.views.AlbumCoverView` serves them with a
year-long immutable cache. Downloading doubles as verification: art that will
not download is rejected and the next candidate tried.

Three fallbacks, in order, each added because a real album needed it:

1. the release group's own front cover
2. **any release in the group**, earliest first — two groups return a
   persistent 500 at the group level while their releases serve art fine
3. a **MusicBrainz search** by title and artist, for albums whose Wikidata
   entity has no P436 at all

`Album.cover_image_url` keeps the *remote* URL: it is what the API exposes and
what Open Graph scrapers read, and a scraper cannot reach a staff-gated local
route. `Album.thumbnail` and `Album.image` are what the pages render, and they
prefer the local copy.

## Gotchas

**SQLite ignores varchar length; PostgreSQL does not.** Any text from an
external source must go through `metadata_service.fit()` before it is saved,
or a run that passes locally will abort partway through on Heroku. Fiona
Apple's "When the Pawn..." has a 444-character title, which both Discogs and
MusicBrainz return in full, against `varchar(300)` columns.

**The passes are resumable.** If a run dies partway, re-running without
`--force` skips what already landed and continues, so a failure costs only the
records after it.

## Re-running After an Import

`import_music_data` deletes every `Album` row, but the metadata tables use
`on_delete=SET_NULL`, so their rows survive as orphans keyed by external ID.
Re-running the fetch re-adopts them:

```bash
python manage.py import_music_data
python manage.py fetch_album_metadata   # reconnects, downloads nothing
```

## Result Format

```python
{
    "WikipediaAlbumData": {
        "page_title": "Abbey Road",
        "wikidata_id": "Q173643",
        "release_date": date(1969, 9, 26),   # P577, day or month precision only
        "record_label": "Apple Records",     # P264, label resolved
        "spotify_album_id": "0ETFjACtuP2ADo6LFhL6HN",
        "all_genres": "rock music",          # P136 labels, a genre vote
    },
    "DiscogsAlbumData": {
        "master_id": 24047,
        "genres": ["Rock"],                  # Discogs top level, verbatim
        "styles": ["Pop Rock"],              # the base genre vote
    },
    "MusicBrainzAlbumData": {
        "release_group_mbid": "9162580e-...",
        "primary_type": "Album",
        "first_release_date": "1969-09-26",  # text: partial dates are valid
        "rating": 4.5,
        "cover_art_release_mbid": "f04cce33-...",
        "cover_art_image_id": "25254108559",
        "cover_art_stored": True,
    },
}
```

## Related

- `/igdb` and `/wikipedia` - the games equivalents this is modelled on
- `python manage.py import_music_data` - loads the ranking release itself
