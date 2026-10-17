"""
Discogs client: the genre source of record for albums.

Discogs is used for genres because it is the only source that supplies both
a curated vocabulary and per-album assignments by exact ID. 498 of the 502
album QIDs in the release carry a Discogs master ID (Wikidata P1954), so no
title matching is needed.

Its vocabulary is already two levels deep, which is the shape ``MusicGenre``
models: ``genres`` is a small closed set of top-level names (only nine of
them appear in this corpus) and ``styles`` is the second level, with names
clean enough to display verbatim - 'Alternative Rock', 'Post-Punk',
'Contemporary R&B'. By comparison, deriving a tree from Wikidata's P279
graph classified only 76% of this corpus unambiguously and put thrash metal
under Rock.

Rate limiting is driven by the response headers rather than a constant: a
live unauthenticated response reported ``X-Discogs-Ratelimit: 25`` per
minute, and a token raises that by an amount the documentation would not
serve to an automated client.
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import requests
from django.conf import settings

from music import config
from music.services.http_client import RateLimitedClient

logger = logging.getLogger(__name__)

#: Pace this much slower than the strict window average. The limit is an
#: average over a rolling minute, so sitting exactly on it earns 429s as soon
#: as any jitter bunches two requests together.
RATE_LIMIT_HEADROOM = 1.15

#: With this few calls left in the window, stop trusting the average and wait
#: a full slot per request until it refills.
RATE_LIMIT_NEARLY_SPENT = 5


@dataclass
class DiscogsMaster:
    """A Discogs master release, reduced to what the pipeline stores."""

    master_id: int
    title: str = ""
    year: Optional[int] = None
    genres: List[str] = field(default_factory=list)
    styles: List[str] = field(default_factory=list)


class DiscogsClient(RateLimitedClient):
    """Reads master releases, pacing itself from the rate-limit headers."""

    default_delay = config.DISCOGS_REQUEST_DELAY

    # A spent Discogs window refills over a rolling minute, so the base
    # class's 1s-then-2s backoff gives up long before it could succeed.
    initial_retry_delay = 15.0
    max_retries = 4

    def __init__(self, token: Optional[str] = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.token = token if token is not None else settings.DISCOGS_TOKEN
        if self.token:
            self.session.headers.update(
                {"Authorization": f"Discogs token={self.token}"}
            )
            logger.info("Using an authenticated Discogs token")
        else:
            logger.info(
                "No DISCOGS_TOKEN set; pacing at %.1fs between requests",
                self.delay,
            )

    def _observe_response(self, response: requests.Response) -> None:
        """Re-pace from ``X-Discogs-Ratelimit`` on every response.

        The limit differs between the anonymous and token tiers and is not
        documented anywhere this client can read, so the server's own numbers
        are the only trustworthy source.

        The delay is never set below the window average: the limit is an
        average over a rolling minute, and pacing even slightly under it
        earns a run of 429s a few dozen requests in.
        """
        limit = self._header_int(response, "X-Discogs-Ratelimit")
        remaining = self._header_int(response, "X-Discogs-Ratelimit-Remaining")
        if limit is None or limit <= 0:
            return

        window_delay = (60.0 / limit) * RATE_LIMIT_HEADROOM
        if remaining is not None and remaining <= RATE_LIMIT_NEARLY_SPENT:
            # Nearly spent: double up until the window refills.
            window_delay *= 2
        self.delay = window_delay

    @staticmethod
    def _header_int(response: requests.Response, name: str) -> Optional[int]:
        raw = response.headers.get(name)
        if raw is None:
            return None
        try:
            return int(raw)
        except ValueError:
            logger.debug("Discogs header %s is not a number: %r", name, raw)
            return None

    def fetch_master(self, master_id: int) -> Optional[DiscogsMaster]:
        """Fetch one master release, or None when Discogs has no such record."""
        payload = self.get_json(f"{config.DISCOGS_API_URL}/masters/{master_id}")
        if not isinstance(payload, dict):
            return None
        return self._build_master(master_id, payload)

    @staticmethod
    def _build_master(master_id: int, payload: Dict[str, Any]) -> DiscogsMaster:
        year = payload.get("year")
        return DiscogsMaster(
            master_id=master_id,
            title=payload.get("title") or "",
            year=year if isinstance(year, int) and year > 0 else None,
            genres=[g for g in (payload.get("genres") or []) if g],
            styles=[s for s in (payload.get("styles") or []) if s],
        )
