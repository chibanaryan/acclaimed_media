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
| `discogs` | ~500 | ~23 min anonymous | `DiscogsAlbumData`, `MusicGenre` rows and links |
| `musicbrainz` | ~500 | ~9 min | release type, exact date, rating, MB genres |

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

Genres come from Discogs, not Wikidata. Discogs publishes a curated two-level
vocabulary - a closed set of top-level `genres` and a second level of `styles`
- which is the shape `MusicGenre` already models, and it assigns them per
album by exact master ID.

`music/services/genre_normalizer.py` maps Discogs styles onto our own 16 root
genres, which are finer than Discogs': Discogs files Punk and Metal as styles
under Rock, and collapses Funk, Soul and R&B into one "Funk / Soul".

A style's root is resolved **globally**, never from the album in hand:

1. an explicit `STYLE_TO_ROOT` entry, including `None` to drop a descriptor
2. a style that is itself a root
3. the rightmost root word in the style's own name (`Pop Rock` is Rock)
4. only then the album's Discogs top-level genres

Order matters. When the album's genre list came first, `Alternative Rock`
landed under Electronic because OK Computer is tagged "Electronic, Rock", and
that one row then represented every alternative rock album on the site.

**Adding to the taxonomy.** Run the Discogs pass, then dump what it saw:

```bash
python manage.py shell -c "
from collections import Counter
from music.models import DiscogsAlbumData
styles = Counter()
for record in DiscogsAlbumData.objects.all():
    styles.update(record.styles)
print(len(styles)); [print(f'{n:4d}  {s}') for s, n in styles.most_common()]
"
```

`music/tests/test_genre_normalizer.py::RealVocabularyTests` pins every style
the current release uses, so a new release with new styles fails there rather
than silently dropping genres. Add the style to `STYLE_TO_ROOT` and to that
test's `OBSERVED` list.

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
        "all_genres": "rock music",          # P136 labels, provenance only
    },
    "DiscogsAlbumData": {
        "master_id": 24047,
        "genres": ["Rock"],                  # Discogs top level, verbatim
        "styles": ["Pop Rock"],              # the genre source of record
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
