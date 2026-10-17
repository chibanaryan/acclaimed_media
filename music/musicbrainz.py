"""
MusicBrainz and Cover Art Archive clients.

These two live together because the cover art is keyed by MusicBrainz
identifiers and both services share one politeness policy, the way
``games.igdb`` keeps everything IGDB in one module.

The two have very different standing in the pipeline:

- **Cover Art Archive** is on the critical path. It is what puts art on the
  page, it needs nothing but the release-group MBID that Wikidata already
  supplied, and it documents no rate limit at all. A 60-album sample found
  front art for every one.
- **MusicBrainz** is enrichment, and opt-in for that reason. It adds the
  release type, a precise first-release date, a rating and a genre fallback,
  but it publishes a hard average of one request per second per IP and
  answers 503 past it, which makes a 500-album pass take about nine minutes.
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from music import config
from music.services.http_client import RateLimitedClient

logger = logging.getLogger(__name__)

#: MusicBrainz search scores run 0-100; below this a match is not trustworthy.
MIN_SEARCH_SCORE = 90


@dataclass
class ReleaseGroup:
    """A MusicBrainz release group, reduced to what the pipeline stores."""

    mbid: str
    title: str = ""
    primary_type: str = ""
    secondary_types: List[str] = field(default_factory=list)
    first_release_date: str = ""
    rating: Optional[float] = None
    rating_votes: Optional[int] = None
    genres: List[str] = field(default_factory=list)
    artist_credit: List[Dict[str, str]] = field(default_factory=list)


@dataclass
class CoverArt:
    """The front cover of a release group, as the Cover Art Archive has it."""

    release_mbid: str
    image_id: str


class MusicBrainzClient(RateLimitedClient):
    """Release-group lookups, held to one request per second."""

    default_delay = config.MUSICBRAINZ_REQUEST_DELAY

    def fetch_release_group(self, mbid: str) -> Optional[ReleaseGroup]:
        """Fetch one release group with credits, genres and ratings."""
        payload = self.get_json(
            f"{config.MUSICBRAINZ_API_URL}/release-group/{mbid}",
            params={
                "inc": "artist-credits+genres+ratings",
                "fmt": "json",
            },
        )
        if not isinstance(payload, dict):
            return None
        return self._build_release_group(mbid, payload)

    def search_release_group(
        self, title: str, artist_credit: str = "", year: Optional[int] = None
    ) -> Optional[str]:
        """Find a release group by title and artist, or None.

        Only for albums whose Wikidata entity carries no P436 - two of the
        502 in this release. An album release is preferred over a single of
        the same name, which is the usual ambiguity: Aretha Franklin's
        'I Never Loved a Man the Way I Love You' is both.
        """
        if not title:
            return None

        terms = [f'release:"{self._escape_lucene(title)}"']
        if artist_credit:
            terms.append(f'artist:"{self._escape_lucene(artist_credit)}"')

        payload = self.get_json(
            f"{config.MUSICBRAINZ_API_URL}/release-group",
            params={"query": " AND ".join(terms), "fmt": "json", "limit": 10},
        )
        if not isinstance(payload, dict):
            return None

        candidates = [
            group
            for group in payload.get("release-groups") or []
            if (group.get("score") or 0) >= MIN_SEARCH_SCORE and group.get("id")
        ]
        if not candidates:
            logger.info("No MusicBrainz release group matched %r", title)
            return None

        def preference(group):
            # An Album beats a Single or EP; then prefer the closest year,
            # then the better score.
            is_album = (group.get("primary-type") or "") == "Album"
            date = group.get("first-release-date") or ""
            year_gap = 0
            if year and date[:4].isdigit():
                year_gap = abs(int(date[:4]) - year)
            return (not is_album, year_gap, -(group.get("score") or 0))

        best = sorted(candidates, key=preference)[0]
        logger.info(
            "Matched %r to release group %s (%s, %s)",
            title,
            best["id"],
            best.get("primary-type"),
            best.get("first-release-date"),
        )
        return best["id"]

    @staticmethod
    def _escape_lucene(value: str) -> str:
        """Escape the Lucene syntax characters a title might contain."""
        for char in ("\\", '"', "+", "-", "!", "(", ")", ":", "^", "~", "*", "?"):
            value = value.replace(char, f"\\{char}")
        return value

    def browse_release_mbids(self, release_group_mbid: str) -> List[str]:
        """The MBIDs of the releases in a group, earliest release first.

        Used only as a cover-art fallback: when the Cover Art Archive has no
        art filed against a release group (or persistently errors on it), its
        individual releases usually do have some.
        """
        payload = self.get_json(
            f"{config.MUSICBRAINZ_API_URL}/release",
            params={
                "release-group": release_group_mbid,
                "fmt": "json",
                "limit": 100,
            },
        )
        if not isinstance(payload, dict):
            return []

        releases = payload.get("releases") or []
        # An undated release sorts last rather than first.
        releases.sort(key=lambda release: release.get("date") or "9999")
        return [release["id"] for release in releases if release.get("id")]

    @staticmethod
    def _build_release_group(mbid: str, payload: Dict[str, Any]) -> ReleaseGroup:
        rating = payload.get("rating") or {}

        # Genres come with vote counts; the most-voted first is the useful
        # ordering, since MusicBrainz happily lists eight for one album.
        genres = sorted(
            (g for g in payload.get("genres") or [] if g.get("name")),
            key=lambda g: g.get("count") or 0,
            reverse=True,
        )

        # Join phrases are the authoritative credit separators: the Velvet
        # Underground and Nico are joined by ' & ', not by the comma the
        # ranking file happens to print.
        credit = [
            {
                "name": entry.get("name") or "",
                "joinphrase": entry.get("joinphrase") or "",
                "artist_mbid": (entry.get("artist") or {}).get("id") or "",
            }
            for entry in payload.get("artist-credit") or []
        ]

        return ReleaseGroup(
            mbid=mbid,
            title=payload.get("title") or "",
            primary_type=payload.get("primary-type") or "",
            secondary_types=list(payload.get("secondary-types") or []),
            first_release_date=payload.get("first-release-date") or "",
            rating=rating.get("value"),
            rating_votes=rating.get("votes-count"),
            genres=[g["name"] for g in genres],
            artist_credit=credit,
        )


class CoverArtArchiveClient(RateLimitedClient):
    """Finds the front cover for a release group."""

    default_delay = config.COVER_ART_REQUEST_DELAY

    def fetch_front_cover(self, release_group_mbid: str) -> Optional[CoverArt]:
        """Return the front-cover identifiers for a release group, or None.

        The JSON listing is requested rather than the ``/front`` redirect
        because the listing names the release the image belongs to and its
        image id, which is what lets any thumbnail size be composed later
        without another request.
        """
        payload = self.get_json(
            f"{config.COVER_ART_ARCHIVE_URL}/release-group/{release_group_mbid}"
        )
        return self._pick_front_cover(payload, release_group_mbid)

    def fetch_release_front_cover(self, release_mbid: str) -> Optional[CoverArt]:
        """Return the front cover filed against one release, or None.

        The fallback path. Two release groups in this corpus return a
        persistent 500 from the release-group endpoint while their releases
        serve art perfectly well.
        """
        payload = self.get_json(
            f"{config.COVER_ART_ARCHIVE_URL}/release/{release_mbid}"
        )
        return self._pick_front_cover(payload, release_mbid)

    def _pick_front_cover(self, payload: Any, mbid: str) -> Optional[CoverArt]:
        """Choose the front image out of a Cover Art Archive listing."""
        if not isinstance(payload, dict):
            return None

        images = payload.get("images") or []
        front = next((image for image in images if image.get("front")), None)
        if front is None:
            logger.debug("No front cover among %d images for %s", len(images), mbid)
            return None

        image_id = front.get("id")
        release_mbid = self._release_mbid_from_image_url(front.get("image") or "")
        if not (image_id and release_mbid):
            logger.warning("Cover art for %s is missing an id or release MBID", mbid)
            return None

        return CoverArt(release_mbid=release_mbid, image_id=str(image_id))

    @staticmethod
    def _release_mbid_from_image_url(url: str) -> Optional[str]:
        """Pull the release MBID out of a Cover Art Archive image URL.

        The listing returns .../release/<release-mbid>/<image-id>.jpg, and
        the release MBID is not given as a field of its own.
        """
        parts = url.split("/release/")
        if len(parts) != 2:
            return None
        mbid = parts[1].split("/")[0]
        return mbid or None
