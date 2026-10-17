"""
Wikidata client for album metadata.

Every album in the supplied ranking carries a Wikidata QID, which makes
Wikidata the hub of the music pipeline rather than one source among several:
it yields the performers, the genre candidates, the release date and the
label, plus the Discogs and MusicBrainz identifiers that the other clients
are keyed by. Measured against the 502 QIDs in the release, P175 and P577
are on every album, P436 on 500, P1954 on 498 and P136 on 499.

``wbgetentities`` accepts 50 ids per request, so the whole album pass is
about ten round trips. Nothing here touches the database; persistence lives
in ``music.services.metadata_service``.
"""

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, Iterable, List, Optional

from music import config
from music.services.http_client import RateLimitedClient

logger = logging.getLogger(__name__)

# Wikidata time precision codes. 11 is a day, 10 a month, 9 a year.
PRECISION_DAY = 11
PRECISION_MONTH = 10


@dataclass
class AlbumMetadata:
    """Everything one album's Wikidata entity contributes."""

    wikidata_id: str
    page_title: str = ""
    release_date: Optional[date] = None
    record_label_qid: Optional[str] = None
    spotify_album_id: Optional[str] = None
    musicbrainz_release_group_id: Optional[str] = None
    discogs_master_id: Optional[int] = None
    performer_qids: List[str] = field(default_factory=list)
    genre_qids: List[str] = field(default_factory=list)


@dataclass
class ArtistMetadata:
    """A performer entity: its label and its MusicBrainz artist id."""

    wikidata_id: str
    name: str = ""
    musicbrainz_id: Optional[str] = None


def _claim_values(claims: Dict[str, Any], prop: str) -> List[Any]:
    """Return every usable datavalue for ``prop``, best rank first.

    Deprecated claims are dropped and preferred claims sort ahead of normal
    ones, which is the same ordering ``games.services.wiki_page_lookup_service``
    applies to P2816 and P1733.
    """
    ranked = [
        (claim, claim.get("rank", "normal"))
        for claim in claims.get(prop, [])
        if claim.get("rank", "normal") != "deprecated"
    ]
    ranked.sort(key=lambda pair: 0 if pair[1] == "preferred" else 1)

    values = []
    for claim, _rank in ranked:
        datavalue = claim.get("mainsnak", {}).get("datavalue")
        if datavalue is not None and "value" in datavalue:
            values.append(datavalue["value"])
    return values


def _first_claim_value(claims: Dict[str, Any], prop: str) -> Optional[Any]:
    """The best-ranked datavalue for ``prop``, or None."""
    values = _claim_values(claims, prop)
    return values[0] if values else None


def _entity_ids(claims: Dict[str, Any], prop: str) -> List[str]:
    """The QIDs ``prop`` points at, in rank order."""
    return [
        value["id"]
        for value in _claim_values(claims, prop)
        if isinstance(value, dict) and "id" in value
    ]


def _parse_time_value(value: Any) -> Optional[date]:
    """Turn a Wikidata time value into a date, when it is precise enough.

    Wikidata stores partial dates with a precision code, so '+1966-00-00'
    with year precision is a real and common answer. Only day and month
    precision become a date here (a month becomes its first day); a
    year-precision claim adds nothing, since ``Album.year_released`` already
    holds the year.
    """
    if not isinstance(value, dict):
        return None

    precision = value.get("precision", 0)
    if precision < PRECISION_MONTH:
        return None

    timestamp = value.get("time", "")
    # Format: +1966-05-16T00:00:00Z, with a leading sign we do not want.
    parts = timestamp.lstrip("+-")[:10].split("-")
    if len(parts) != 3:
        return None

    try:
        year, month, day = (int(part) for part in parts)
    except ValueError:
        return None

    if precision == PRECISION_MONTH or day == 0:
        day = 1
    if year == 0 or month == 0:
        return None

    try:
        return date(year, month, day)
    except ValueError:
        logger.warning("Unparseable Wikidata date: %s", timestamp)
        return None


class WikidataClient(RateLimitedClient):
    """Batched reads from the Wikidata Action API."""

    default_delay = 1.0

    def fetch_entities(
        self,
        qids: Iterable[str],
        props: str = "claims",
        extra_params: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Return the raw entities for ``qids``, in batches of 50.

        A failed batch is logged and skipped rather than aborting the run, so
        one bad request costs 50 albums their metadata and nothing else.
        """
        qids = list(dict.fromkeys(qids))
        entities: Dict[str, Any] = {}

        for start in range(0, len(qids), config.WIKIDATA_BATCH_SIZE):
            batch = qids[start : start + config.WIKIDATA_BATCH_SIZE]
            params = {
                "action": "wbgetentities",
                "ids": "|".join(batch),
                "props": props,
                "format": "json",
                "languages": "en",
            }
            if extra_params:
                params.update(extra_params)

            payload = self.get_json(config.WIKIDATA_API_URL, params=params)
            if not payload or "entities" not in payload:
                logger.warning(
                    "Wikidata returned no entities for a batch of %d", len(batch)
                )
                continue
            entities.update(payload["entities"])

        return entities

    def fetch_album_metadata(self, qids: Iterable[str]) -> Dict[str, AlbumMetadata]:
        """Read the album properties and the enwiki sitelink for ``qids``."""
        entities = self.fetch_entities(
            qids,
            props="claims|sitelinks",
            extra_params={"sitefilter": "enwiki"},
        )

        results: Dict[str, AlbumMetadata] = {}
        for qid, entity in entities.items():
            if "missing" in entity:
                logger.warning("Wikidata has no entity %s", qid)
                continue
            results[qid] = self._build_album_metadata(qid, entity)
        return results

    def _build_album_metadata(self, qid: str, entity: Dict[str, Any]) -> AlbumMetadata:
        claims = entity.get("claims", {})
        sitelink = entity.get("sitelinks", {}).get("enwiki", {})

        label_qids = _entity_ids(claims, config.WIKIDATA_LABEL_PROPERTY)
        master_id = _first_claim_value(claims, config.WIKIDATA_DISCOGS_MASTER_PROPERTY)

        return AlbumMetadata(
            wikidata_id=qid,
            page_title=sitelink.get("title", ""),
            release_date=_parse_time_value(
                _first_claim_value(claims, config.WIKIDATA_RELEASE_DATE_PROPERTY)
            ),
            record_label_qid=label_qids[0] if label_qids else None,
            spotify_album_id=_first_claim_value(
                claims, config.WIKIDATA_SPOTIFY_PROPERTY
            ),
            musicbrainz_release_group_id=_first_claim_value(
                claims, config.WIKIDATA_MUSICBRAINZ_RELEASE_GROUP_PROPERTY
            ),
            discogs_master_id=self._coerce_master_id(master_id),
            performer_qids=_entity_ids(claims, config.WIKIDATA_PERFORMER_PROPERTY),
            genre_qids=_entity_ids(claims, config.WIKIDATA_GENRE_PROPERTY),
        )

    @staticmethod
    def _coerce_master_id(value: Any) -> Optional[int]:
        """Discogs master ids arrive as strings; keep only clean integers."""
        if value is None:
            return None
        try:
            return int(str(value))
        except ValueError:
            logger.warning("Discogs master id is not a number: %r", value)
            return None

    def fetch_labels(self, qids: Iterable[str]) -> Dict[str, str]:
        """Map QIDs to their English labels, skipping any that have none.

        Two genre entities in this corpus carry no English label at all
        (Q3071, Q3930216), so a caller must be ready for a missing key rather
        than assume the QID round-trips to a name.
        """
        entities = self.fetch_entities(qids, props="labels")

        labels: Dict[str, str] = {}
        for qid, entity in entities.items():
            label = (entity.get("labels", {}).get("en") or {}).get("value")
            if label:
                labels[qid] = label
            else:
                logger.info("Wikidata entity %s has no English label", qid)
        return labels

    def fetch_artists(self, qids: Iterable[str]) -> Dict[str, ArtistMetadata]:
        """Resolve performer QIDs to names and MusicBrainz artist ids.

        Taking P434 from the same request is what lets ``Artist.musicbrainz_id``
        be filled without a single MusicBrainz call.
        """
        entities = self.fetch_entities(qids, props="labels|claims")

        artists: Dict[str, ArtistMetadata] = {}
        for qid, entity in entities.items():
            label = (entity.get("labels", {}).get("en") or {}).get("value")
            if not label:
                logger.info("Skipping artist %s: no English label", qid)
                continue
            artists[qid] = ArtistMetadata(
                wikidata_id=qid,
                name=label,
                musicbrainz_id=_first_claim_value(
                    entity.get("claims", {}),
                    config.WIKIDATA_ARTIST_MUSICBRAINZ_PROPERTY,
                ),
            )
        return artists
