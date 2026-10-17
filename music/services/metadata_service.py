"""
Orchestrates the album metadata passes and persists what they return.

The clients in ``music.wikidata``, ``music.discogs`` and
``music.musicbrainz`` are pure HTTP; everything that touches the database
lives here, the same split ``games.igdb`` and
``games.services.igdb_importer`` keep.

There are four passes, and they are separate because their costs differ by
two orders of magnitude:

==============  ========  ==============================================
Pass            Requests  Notes
==============  ========  ==============================================
``wikidata``    ~25       Batched 50 ids at a time; seconds, not minutes
``covers``      ~500      No documented rate limit; about two minutes
``discogs``     ~500      25/min anonymous, so about twenty minutes
``musicbrainz`` ~500      Hard 1/sec cap, so about nine minutes; opt-in
==============  ========  ==============================================

Each pass adopts orphaned metadata before fetching. An import replaces every
Album row (``import_handler.import_albums`` deletes them all), and the
metadata tables use ``on_delete=SET_NULL``, so the rows survive as orphans
keyed by their external id. Re-running after an import therefore reconnects
hundreds of covers without a single HTTP request.
"""

import logging
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional

from django.db import transaction

from music import config, models
from music.discogs import DiscogsClient
from music.musicbrainz import CoverArt, CoverArtArchiveClient, MusicBrainzClient
from music.services import genre_normalizer
from music.services.import_handler import _unique_artist_slug, split_artist_credit
from music.wikidata import WikidataClient

logger = logging.getLogger(__name__)

#: How many of a release group's releases to try for cover art. A group can
#: have ninety, and the original pressings sort first, so there is nothing to
#: gain from walking all of them.
MAX_RELEASE_CANDIDATES = 12

#: Tokens that carry no distinguishing information in a band name.
_ARTIST_NOISE_TOKENS = frozenset({"the"})


def normalize_artist_name(name: str) -> str:
    """A comparison key for an artist name.

    Collapses the three ways the same act gets spelled across sources:
    ampersand against 'and', a leading or internal 'the', and punctuation.
    'Bob Marley & The Wailers' and 'Bob Marley and the Wailers' both become
    'bobmarleyandwailers'.
    """
    lowered = name.casefold().replace("&", " and ")
    tokens = re.split(r"[^a-z0-9]+", lowered)
    return "".join(
        token for token in tokens if token and token not in _ARTIST_NOISE_TOKENS
    )


@dataclass
class PassResult:
    """What one pass did, for the command to report."""

    name: str
    processed: int = 0
    skipped: int = 0
    adopted: int = 0
    errors: List[str] = field(default_factory=list)

    def summary(self) -> str:
        parts = [f"{self.processed} processed"]
        if self.adopted:
            parts.append(f"{self.adopted} reconnected")
        if self.skipped:
            parts.append(f"{self.skipped} skipped")
        if self.errors:
            parts.append(f"{len(self.errors)} failed")
        return f"{self.name}: " + ", ".join(parts)


class AlbumMetadataService:
    """Runs the metadata passes over a queryset of albums."""

    def __init__(
        self,
        progress_callback: Optional[Callable[[str, Dict], None]] = None,
        force: bool = False,
    ) -> None:
        self.progress_callback = progress_callback
        self.force = force
        # Opened only if the cover pass needs the release-level fallback.
        self._musicbrainz_client = None

    # ----------------------------------------------------------------- utils

    def _notify(self, event_type: str, data: Dict) -> None:
        if self.progress_callback:
            self.progress_callback(event_type, data)

    @staticmethod
    def _album_qids(album: models.Album) -> List[str]:
        """Every Wikidata ID for an album, primary first.

        Two albums in the release carry two QIDs - the UK and US editions of
        'Let It Bleed' and 'Aftermath' - so the extras matter: one of them is
        where the MusicBrainz and Discogs ids actually live.
        """
        qids = []
        if album.wikidata_id:
            qids.append(album.wikidata_id)
        for qid in album.all_wikidata_ids or []:
            if qid and qid not in qids:
                qids.append(qid)
        return qids

    def _set_primary(self, album: models.Album, record, field_name: str) -> None:
        """Point the album at ``record`` and demote any other primary row."""
        type(record).objects.filter(album=album, is_primary=True).exclude(
            pk=record.pk
        ).update(is_primary=False)
        if not record.is_primary:
            record.is_primary = True
            record.save(update_fields=["is_primary"])
        setattr(album, field_name, record)
        album.save(update_fields=[field_name])

    # -------------------------------------------------------- wikidata pass

    def run_wikidata(self, albums: Iterable[models.Album]) -> PassResult:
        """Fetch album properties, performers and identifiers from Wikidata.

        One batched pass for the albums, then two more to resolve the
        performer, genre and record-label entities those albums referenced.
        """
        result = PassResult(name="Wikidata")
        albums = list(albums)
        if not albums:
            return result

        qid_to_albums: Dict[str, List[models.Album]] = {}
        for album in albums:
            for qid in self._album_qids(album):
                qid_to_albums.setdefault(qid, []).append(album)

        if not qid_to_albums:
            result.errors.append("No album carries a Wikidata ID")
            return result

        self._notify("start", {"pass": "wikidata", "total": len(albums)})

        with WikidataClient() as client:
            metadata = client.fetch_album_metadata(qid_to_albums)

            # Resolve every entity the albums pointed at, in two batched
            # requests rather than one per album.
            performer_qids = {
                qid for meta in metadata.values() for qid in meta.performer_qids
            }
            referenced_qids = {
                qid for meta in metadata.values() for qid in meta.genre_qids
            } | {
                meta.record_label_qid
                for meta in metadata.values()
                if meta.record_label_qid
            }

            artists = client.fetch_artists(performer_qids)
            labels = client.fetch_labels(referenced_qids)

        for index, album in enumerate(albums, start=1):
            try:
                with transaction.atomic():
                    self._save_wikidata(album, metadata, artists, labels)
                result.processed += 1
                self._notify(
                    "progress",
                    {
                        "pass": "wikidata",
                        "current": index,
                        "total": len(albums),
                        "name": album.name,
                    },
                )
            except Exception as exc:  # noqa: BLE001 - one album must not stop the run
                logger.exception("Wikidata pass failed for %s", album.name)
                result.errors.append(f"{album.name}: {exc}")
                self._notify(
                    "error",
                    {"pass": "wikidata", "name": album.name, "message": str(exc)},
                )

        self._notify("complete", {"pass": "wikidata", "processed": result.processed})
        return result

    def _save_wikidata(self, album, metadata, artists, labels) -> None:
        """Write one album's Wikidata results."""
        album_meta = None
        for qid in self._album_qids(album):
            candidate = metadata.get(qid)
            if candidate is None:
                continue
            # Prefer whichever edition actually carries the identifiers.
            if album_meta is None:
                album_meta = candidate
            elif candidate.musicbrainz_release_group_id and not (
                album_meta.musicbrainz_release_group_id
            ):
                album_meta = candidate

        if album_meta is None:
            raise ValueError("Wikidata returned nothing for any of its IDs")

        genre_labels = [labels[qid] for qid in album_meta.genre_qids if qid in labels]
        record_label = (
            labels.get(album_meta.record_label_qid)
            if album_meta.record_label_qid
            else None
        )

        record = self._adopt_or_build_wikipedia_data(album, album_meta)
        record.page_title = album_meta.page_title
        record.release_date = album_meta.release_date
        record.record_label = record_label
        record.spotify_album_id = album_meta.spotify_album_id
        record.primary_genre = genre_labels[0] if genre_labels else None
        record.all_genres = ", ".join(genre_labels) or None
        record.save()

        self._set_primary(album, record, "primary_wikipedia_album_data")

        update_fields = []
        if album_meta.musicbrainz_release_group_id:
            album.musicbrainz_release_group_id = album_meta.musicbrainz_release_group_id
            update_fields.append("musicbrainz_release_group_id")
        if album_meta.discogs_master_id:
            album.discogs_master_id = album_meta.discogs_master_id
            update_fields.append("discogs_master_id")
        if update_fields:
            album.save(update_fields=update_fields)

        self._save_artists(album, album_meta, artists)

    def _adopt_or_build_wikipedia_data(self, album, album_meta):
        """Reuse this album's row, adopt a matching orphan, or make a new one."""
        existing = models.WikipediaAlbumData.collapse_duplicates(
            album, album_meta.wikidata_id
        )
        if existing is not None:
            return existing

        orphan = models.WikipediaAlbumData.objects.filter(
            wikidata_id=album_meta.wikidata_id, album__isnull=True
        ).first()
        if orphan is not None:
            orphan.album = album
            return orphan

        return models.WikipediaAlbumData(
            album=album, wikidata_id=album_meta.wikidata_id
        )

    def _save_artists(self, album, album_meta, artists) -> None:
        """Set the artists M2M to the union of the published credit and P175.

        Neither source is sufficient alone. The published credit is what a
        reader recognizes and what the row templates show, but a comma in it
        is only a guess at a separator. P175 names entities with ids, but it
        names the *canonical* act, which is sometimes coarser than the credit:
        'Band on the Run' is credited to 'Paul McCartney, Wings' and P175 says
        only Wings, so trusting P175 alone loses McCartney the album.
        'Clube da Esquina' loses both of its credited artists the same way.

        So both are kept. Matching is on a normalized name, which collapses
        the punctuation variants that would otherwise double up - P175's
        'Bob Marley & The Wailers' is the credit's 'Bob Marley and the
        Wailers' - and ids are written onto whichever row wins.

        ``Album.artist_credit`` itself is never touched.
        """
        rows = []

        for name in split_artist_credit(album.artist_credit or ""):
            artist = self._resolve_artist(name)
            if artist not in rows:
                rows.append(artist)

        for qid in album_meta.performer_qids:
            meta = artists.get(qid)
            if meta is None:
                continue
            artist = self._resolve_artist(
                meta.name,
                wikidata_id=meta.wikidata_id,
                musicbrainz_id=meta.musicbrainz_id,
            )
            if artist not in rows:
                rows.append(artist)

        if rows:
            album.artists.set(rows)

    def _resolve_artist(
        self,
        name: str,
        wikidata_id: Optional[str] = None,
        musicbrainz_id: Optional[str] = None,
    ):
        """Find or create an artist, then fill in any ids we now know."""
        artist = None
        if wikidata_id:
            artist = models.Artist.objects.filter(wikidata_id=wikidata_id).first()
        if artist is None:
            artist = models.Artist.objects.filter(name=name, parent=None).first()
        if artist is None:
            artist = self._find_artist_by_normalized_name(name)
        if artist is None:
            artist = models.Artist.objects.create(
                name=name, slug=_unique_artist_slug(name)
            )

        changed = []
        if wikidata_id and artist.wikidata_id != wikidata_id:
            artist.wikidata_id = wikidata_id
            changed.append("wikidata_id")
        if musicbrainz_id and artist.musicbrainz_id != musicbrainz_id:
            artist.musicbrainz_id = musicbrainz_id
            changed.append("musicbrainz_id")
        if changed:
            artist.save(update_fields=changed)

        return artist

    @staticmethod
    def _find_artist_by_normalized_name(name: str):
        """Match an existing artist ignoring punctuation, '&' and 'the'."""
        key = normalize_artist_name(name)
        if not key:
            return None
        for artist in models.Artist.objects.filter(parent=None):
            if normalize_artist_name(artist.name) == key:
                return artist
        return None

    # ----------------------------------------------------------- covers pass

    def run_covers(self, albums: Iterable[models.Album]) -> PassResult:
        """Find front cover art for every album with a release-group MBID."""
        result = PassResult(name="Cover art")
        albums = list(albums)

        # An album with no P436 gets one looked up by title and artist, so a
        # gap in Wikidata does not cost it its cover.
        for album in albums:
            if not album.musicbrainz_release_group_id:
                self._resolve_missing_mbid(album, result)

        albums = [a for a in albums if a.musicbrainz_release_group_id]
        if not albums:
            return result

        self._notify("start", {"pass": "covers", "total": len(albums)})

        with CoverArtArchiveClient() as client:
            for index, album in enumerate(albums, start=1):
                record = self._musicbrainz_record(album)

                if not self.force and record.cover_art_image_id:
                    if record.cover_art_stored:
                        result.skipped += 1
                        continue
                    # The image is identified but its bytes are not stored
                    # yet, which is all a re-run after an upgrade needs. No
                    # listing request: the ids are already known.
                    if self._store_known_cover(album, record, client):
                        result.processed += 1
                        continue

                adopted = self._adopt_cover_orphan(album, record)
                if adopted:
                    result.adopted += 1
                    continue

                art = self._find_downloadable_cover(album, client)
                if art is None:
                    result.errors.append(f"{album.name}: no front cover")
                    self._notify(
                        "error",
                        {
                            "pass": "covers",
                            "name": album.name,
                            "message": "no front cover",
                        },
                    )
                    continue

                record.cover_art_release_mbid = art.release_mbid
                record.cover_art_image_id = art.image_id
                record.cover_art_stored = self._store_cover_bytes(album, art, client)
                record.save()
                if not record.cover_art_stored:
                    result.errors.append(f"{album.name}: cover art would not download")
                self._apply_cover(album, record)
                result.processed += 1
                self._notify(
                    "progress",
                    {
                        "pass": "covers",
                        "current": index,
                        "total": len(albums),
                        "name": album.name,
                    },
                )

        if self._musicbrainz_client is not None:
            self._musicbrainz_client.close()
            self._musicbrainz_client = None

        self._notify("complete", {"pass": "covers", "processed": result.processed})
        return result

    def _resolve_missing_mbid(self, album, result) -> None:
        """Search MusicBrainz for a release group this album has no ID for."""
        mbid = self._musicbrainz().search_release_group(
            album.name, album.artist_credit or "", album.year_released
        )
        if not mbid:
            result.errors.append(f"{album.name}: no MusicBrainz release group")
            return
        album.musicbrainz_release_group_id = mbid
        album.save(update_fields=["musicbrainz_release_group_id"])

    def _find_downloadable_cover(self, album, client):
        """The first cover for this album whose bytes actually download.

        The release group's own art is asked for first - it is the image the
        community chose to represent the album - and only if that will not
        download are the group's individual releases tried.
        """
        art = client.fetch_front_cover(album.musicbrainz_release_group_id)
        if art is not None and self._cover_downloads(art, client):
            return art
        return self._front_cover_via_releases(album, client)

    def _cover_downloads(self, art, client) -> bool:
        """Cheap check that the row size is really there, before storing both."""
        if models.AlbumCover.objects.filter(
            release_mbid=art.release_mbid,
            image_id=art.image_id,
            size=models.AlbumCover.ROW_SIZE,
        ).exists():
            return True
        url = (
            f"{config.COVER_ART_ARCHIVE_URL}/release/"
            f"{art.release_mbid}/{art.image_id}-{models.AlbumCover.ROW_SIZE}.jpg"
        )
        return client.get_bytes(url) is not None

    def _front_cover_via_releases(self, album, cover_client):
        """Look for cover art on the group's individual releases.

        The release-group endpoint is the right first question - it is the
        art the community chose to represent the album - but it answers for
        only most albums. Two release groups here return a persistent 500,
        and a group can simply have no art of its own while its releases do.
        Releases are tried earliest first, so the original pressing's sleeve
        wins over a reissue's.

        This costs one MusicBrainz request per album that needs it, at
        1 req/sec, which is why it is a fallback and not the first move.
        """
        mbids = self._release_mbids(album.musicbrainz_release_group_id)
        for release_mbid in mbids[:MAX_RELEASE_CANDIDATES]:
            art = cover_client.fetch_release_front_cover(release_mbid)
            if art is not None and self._cover_downloads(art, cover_client):
                logger.info(
                    "Found cover for %s on release %s", album.name, release_mbid
                )
                return art
        return None

    def _release_mbids(self, release_group_mbid: str) -> List[str]:
        """Browse a group's releases, for the cover-art fallback."""
        return self._musicbrainz().browse_release_mbids(release_group_mbid)

    def _musicbrainz(self) -> MusicBrainzClient:
        """The shared MusicBrainz client, opened on first use.

        Opened lazily because the common path through the cover pass never
        needs it, and opening it would impose the 1 req/sec pacing on a pass
        that otherwise runs at five times that.
        """
        if self._musicbrainz_client is None:
            self._musicbrainz_client = MusicBrainzClient()
        return self._musicbrainz_client

    def _store_known_cover(self, album, record, client) -> bool:
        """Download the bytes for a cover whose identifiers are already known."""
        art = CoverArt(
            release_mbid=record.cover_art_release_mbid,
            image_id=record.cover_art_image_id,
        )
        if not self._store_cover_bytes(album, art, client):
            return False
        record.cover_art_stored = True
        record.save(update_fields=["cover_art_stored"])
        self._apply_cover(album, record)
        return True

    @staticmethod
    def _cover_url(art, size: int) -> str:
        return (
            f"{config.COVER_ART_ARCHIVE_URL}/release/"
            f"{art.release_mbid}/{art.image_id}-{size}.jpg"
        )

    def _store_cover_bytes(self, album, art, client) -> bool:
        """Download and store both sizes of a cover. True if both landed.

        Downloading is also how a cover is *verified*: archive.org serves an
        intermittent 500, and a few items are broken outright, so a URL that
        merely appears in the listing is not evidence of an image. Anything
        that will not download here would have been a broken image on the
        page.

        The two sizes are fetched concurrently. The client's rate-limit lock
        still paces how often a request *starts*, so this overlaps transfer
        time without asking the archive for more than agreed.
        """
        wanted = []
        stored = 0

        for size in models.AlbumCover.SIZES:
            existing = models.AlbumCover.objects.filter(
                release_mbid=art.release_mbid, image_id=art.image_id, size=size
            ).first()
            if existing is not None:
                if existing.album_id != album.pk:
                    existing.album = album
                    existing.save(update_fields=["album"])
                stored += 1
            else:
                wanted.append(size)

        if wanted:
            downloads = self._download_sizes(art, wanted, client)
            for size, downloaded in downloads.items():
                if downloaded is None:
                    logger.warning(
                        "Could not download %s for %s",
                        self._cover_url(art, size),
                        album.name,
                    )
                    continue
                data, content_type = downloaded
                models.AlbumCover.objects.create(
                    album=album,
                    release_mbid=art.release_mbid,
                    image_id=art.image_id,
                    size=size,
                    data=data,
                    content_type=content_type,
                    byte_size=len(data),
                    source_url=self._cover_url(art, size),
                )
                stored += 1

        return stored == len(models.AlbumCover.SIZES)

    def _download_sizes(self, art, sizes, client) -> Dict[int, Any]:
        """Fetch several sizes of one image at once.

        Pure network, no database: the rows are written by the caller on the
        calling thread, so no Django connection is ever touched from a worker.
        """
        if len(sizes) == 1:
            size = sizes[0]
            return {size: client.get_bytes(self._cover_url(art, size))}

        with ThreadPoolExecutor(max_workers=len(sizes)) as pool:
            futures = {
                pool.submit(client.get_bytes, self._cover_url(art, size)): size
                for size in sizes
            }
            return {futures[future]: future.result() for future in futures}

    def _adopt_cover_orphan(self, album, record) -> bool:
        """Copy cover ids off an orphaned row for the same release group."""
        if record.cover_art_image_id:
            return False
        orphan = (
            models.MusicBrainzAlbumData.objects.filter(
                release_group_mbid=album.musicbrainz_release_group_id,
                album__isnull=True,
            )
            .exclude(cover_art_image_id="")
            .first()
        )
        if orphan is None:
            return False

        record.cover_art_release_mbid = orphan.cover_art_release_mbid
        record.cover_art_image_id = orphan.cover_art_image_id
        record.cover_art_stored = models.AlbumCover.objects.filter(
            release_mbid=orphan.cover_art_release_mbid,
            image_id=orphan.cover_art_image_id,
        ).count() == len(models.AlbumCover.SIZES)
        record.save()
        orphan.delete()
        # Re-point the stored bytes, which outlived the deleted album.
        models.AlbumCover.objects.filter(
            release_mbid=record.cover_art_release_mbid,
            image_id=record.cover_art_image_id,
        ).update(album=album)
        self._apply_cover(album, record)
        return True

    def _apply_cover(self, album, record) -> None:
        """Mirror the canonical remote URL onto the album.

        ``Album.cover_image_url`` keeps the *remote* Cover Art Archive URL,
        not our local one: it is what the API serializer exposes and what the
        detail page's Open Graph tags use, and an Open Graph scraper cannot
        reach a staff-gated local route. ``Album.thumbnail`` and
        ``Album.image`` are what the pages render, and they prefer the local
        copy.
        """
        self._set_primary(album, record, "primary_musicbrainz_album_data")
        url = record.cover_art_url(models.AlbumCover.DETAIL_SIZE)
        if url and album.cover_image_url != url:
            album.cover_image_url = url
            album.save(update_fields=["cover_image_url"])

    def _musicbrainz_record(self, album):
        """This album's MusicBrainz row, created if absent."""
        record = models.MusicBrainzAlbumData.objects.filter(
            album=album, release_group_mbid=album.musicbrainz_release_group_id
        ).first()
        if record is not None:
            return record
        return models.MusicBrainzAlbumData.objects.create(
            album=album,
            release_group_mbid=album.musicbrainz_release_group_id,
        )

    # ---------------------------------------------------------- discogs pass

    def run_discogs(self, albums: Iterable[models.Album]) -> PassResult:
        """Fetch Discogs masters and turn their styles into MusicGenre rows."""
        result = PassResult(name="Discogs")
        albums = list(albums)
        without_master = [a for a in albums if not a.discogs_master_id]
        albums = [a for a in albums if a.discogs_master_id]

        for album in without_master:
            result.errors.append(f"{album.name}: no Discogs master ID")

        if not albums:
            return result

        self._notify("start", {"pass": "discogs", "total": len(albums)})

        with DiscogsClient() as client:
            for index, album in enumerate(albums, start=1):
                existing = models.DiscogsAlbumData.objects.filter(
                    album=album, master_id=album.discogs_master_id
                ).first()

                if existing is not None and not self.force:
                    self._apply_genres(album, existing)
                    result.skipped += 1
                    continue

                orphan = models.DiscogsAlbumData.objects.filter(
                    master_id=album.discogs_master_id, album__isnull=True
                ).first()
                if orphan is not None and not self.force:
                    orphan.album = album
                    orphan.save()
                    self._apply_genres(album, orphan)
                    result.adopted += 1
                    continue

                master = client.fetch_master(album.discogs_master_id)
                if master is None:
                    result.errors.append(
                        f"{album.name}: Discogs master "
                        f"{album.discogs_master_id} not found"
                    )
                    self._notify(
                        "error",
                        {
                            "pass": "discogs",
                            "name": album.name,
                            "message": "master not found",
                        },
                    )
                    continue

                record = existing or models.DiscogsAlbumData(
                    album=album, master_id=master.master_id
                )
                record.title = master.title
                record.main_release_year = master.year
                record.genres = master.genres
                record.styles = master.styles
                record.save()

                self._apply_genres(album, record)
                result.processed += 1
                self._notify(
                    "progress",
                    {
                        "pass": "discogs",
                        "current": index,
                        "total": len(albums),
                        "name": album.name,
                    },
                )

        self._notify("complete", {"pass": "discogs", "processed": result.processed})
        return result

    def _apply_genres(self, album, record) -> None:
        """Normalize this album's Discogs styles into its genres M2M.

        An album with a master but no styles still has Discogs' top-level
        genres, so it gets at least a root genre rather than nothing.
        """
        self._set_primary(album, record, "primary_discogs_album_data")

        genres = genre_normalizer.genres_for_album(record.styles, record.genres)
        if not genres:
            genres = [
                genre_normalizer.get_or_create_genre(root)
                for root in dict.fromkeys(
                    filter(
                        None,
                        (
                            genre_normalizer.root_for_discogs_genre(name)
                            for name in record.genres
                        ),
                    )
                )
            ]
        album.genres.set(genres)

    # ------------------------------------------------------ musicbrainz pass

    def run_musicbrainz(self, albums: Iterable[models.Album]) -> PassResult:
        """Enrich with release type, exact dates, ratings and MB genres."""
        result = PassResult(name="MusicBrainz")
        albums = [a for a in albums if a.musicbrainz_release_group_id]
        if not albums:
            return result

        self._notify("start", {"pass": "musicbrainz", "total": len(albums)})

        with MusicBrainzClient() as client:
            for index, album in enumerate(albums, start=1):
                record = self._musicbrainz_record(album)

                if not self.force and record.title:
                    result.skipped += 1
                    continue

                group = client.fetch_release_group(album.musicbrainz_release_group_id)
                if group is None:
                    result.errors.append(f"{album.name}: release group not found")
                    continue

                record.title = group.title
                record.primary_type = group.primary_type
                record.secondary_types = group.secondary_types
                record.first_release_date = group.first_release_date
                record.rating = group.rating
                record.rating_votes = group.rating_votes
                record.all_genres = ", ".join(group.genres) or None
                record.save()

                self._set_primary(album, record, "primary_musicbrainz_album_data")
                result.processed += 1
                self._notify(
                    "progress",
                    {
                        "pass": "musicbrainz",
                        "current": index,
                        "total": len(albums),
                        "name": album.name,
                    },
                )

        self._notify("complete", {"pass": "musicbrainz", "processed": result.processed})
        return result
