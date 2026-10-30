"""
Shared HTTP scaffolding for the music metadata clients.

Four external services feed the music pipeline - Wikidata, Discogs,
MusicBrainz and the Cover Art Archive - and each one wants the same
machinery: a reused session carrying a descriptive User-Agent, a minimum
delay between requests, retries for transient network errors, and a
distinction between "this record has no data" and "the request failed".
Rather than write that four times (as ``games.igdb`` and the two wiki
services each do), it lives here once.
"""

import logging
import threading
import time
from typing import Any, Dict, Optional, Tuple

import requests

from music import config

logger = logging.getLogger(__name__)


class RateLimitedClient:
    """A polite, reusable JSON client with a per-instance request floor.

    Subclasses set ``default_delay`` and may override ``_observe_response``
    to pace themselves from whatever rate-limit headers their service sends.
    """

    #: Minimum seconds between requests when the caller names no delay.
    default_delay: float = 1.0

    #: Network failures worth retrying; anything else is reported and dropped.
    RETRYABLE_ERRORS = (
        requests.ConnectionError,
        requests.Timeout,
        requests.exceptions.ChunkedEncodingError,
    )

    #: Statuses meaning "you are going too fast", not "this is broken".
    THROTTLE_STATUSES = frozenset({429, 503})

    #: Statuses worth retrying. The 5xx entries matter: the Cover Art Archive
    #: is served off archive.org and returns an intermittent 500 for a release
    #: group whose art is perfectly present a second later. Treating that as a
    #: permanent miss cost 26 of 499 albums their covers on the first run.
    RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})

    max_retries: int = 3
    initial_retry_delay: float = 1.0
    timeout: int = 30

    #: How loudly ``get_json`` reports running out of retries. Error reaches
    #: Sentry, so a client whose caller has a fallback lowers it.
    give_up_level: int = logging.ERROR

    def __init__(
        self,
        delay: Optional[float] = None,
        user_agent: Optional[str] = None,
    ) -> None:
        self.delay = self.default_delay if delay is None else delay
        self.user_agent = user_agent or config.MUSIC_USER_AGENT

        self.session = requests.Session()
        self.session.headers.update({"User-Agent": self.user_agent})

        # Rate limiting state. The lock is held across the sleep so that
        # concurrent callers queue rather than all wake at once.
        self.last_request_time: float = 0.0
        self.rate_limit_lock = threading.Lock()

    def __enter__(self) -> "RateLimitedClient":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        self.close()
        return False

    def close(self) -> None:
        """Release the HTTP session."""
        if self.session is not None:
            self.session.close()
            self.session = None

    def _wait_for_rate_limit(self) -> None:
        """Block until ``delay`` has passed since the last request."""
        with self.rate_limit_lock:
            elapsed = time.time() - self.last_request_time
            if elapsed < self.delay:
                time.sleep(self.delay - elapsed)
            self.last_request_time = time.time()

    def _observe_response(self, response: requests.Response) -> None:
        """Hook for subclasses that pace from rate-limit headers."""

    def get_json(
        self,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Optional[Any]:
        """GET ``url`` and decode JSON, or return None.

        None always means "no usable data" - a 404, a throttle that outlasted
        our retries, an HTTP error or an undecodable body - and never raises.
        Callers treat it as a clean miss and move to the next record, because
        one missing cover must not abort a 500-album run.
        """
        retry_delay = self.initial_retry_delay

        for attempt in range(self.max_retries):
            self._wait_for_rate_limit()
            last_attempt = attempt == self.max_retries - 1

            try:
                response = self.session.get(
                    url, params=params, headers=headers, timeout=self.timeout
                )
            except self.RETRYABLE_ERRORS as exc:
                if last_attempt:
                    logger.log(
                        self.give_up_level,
                        "%s failed after %d attempts: %s",
                        url,
                        self.max_retries,
                        exc,
                    )
                    return None
                logger.warning(
                    "Connection error on attempt %d/%d for %s: %s. Retrying in %.1fs",
                    attempt + 1,
                    self.max_retries,
                    url,
                    exc,
                    retry_delay,
                )
                time.sleep(retry_delay)
                retry_delay *= 2
                continue
            except requests.RequestException as exc:
                logger.warning("%s failed (non-retryable): %s", url, exc)
                return None

            self._observe_response(response)

            if response.status_code == 404:
                logger.debug("%s: not found", url)
                return None

            if response.status_code in self.RETRYABLE_STATUSES:
                throttled = response.status_code in self.THROTTLE_STATUSES
                reason = "throttled" if throttled else "server error"
                if last_attempt:
                    logger.log(
                        self.give_up_level,
                        "%s still returning %s (%s) after %d attempts",
                        url,
                        response.status_code,
                        reason,
                        self.max_retries,
                    )
                    return None
                logger.warning(
                    "%s returned %s (%s); backing off %.1fs",
                    url,
                    response.status_code,
                    reason,
                    retry_delay,
                )
                time.sleep(retry_delay)
                retry_delay *= 2
                continue

            try:
                response.raise_for_status()
            except requests.HTTPError as exc:
                logger.warning("%s returned an error: %s", url, exc)
                return None

            try:
                return response.json()
            except ValueError:
                logger.warning("%s returned a body that is not JSON", url)
                return None

    def get_bytes(self, url: str) -> Optional[Tuple[bytes, str]]:
        """GET ``url`` and return ``(body, content_type)``, or None.

        Same contract as :meth:`get_json` - None means no usable data, and
        nothing raises - but follows redirects to a binary body. Used to
        download cover art, where the response is an image and the request
        ends up at archive.org after a 307.
        """
        retry_delay = self.initial_retry_delay

        for attempt in range(self.max_retries):
            self._wait_for_rate_limit()
            last_attempt = attempt == self.max_retries - 1

            try:
                response = self.session.get(url, timeout=self.timeout)
            except self.RETRYABLE_ERRORS as exc:
                if last_attempt:
                    logger.warning("%s failed to download: %s", url, exc)
                    return None
                time.sleep(retry_delay)
                retry_delay *= 2
                continue
            except requests.RequestException as exc:
                logger.warning("%s failed to download (non-retryable): %s", url, exc)
                return None

            if response.status_code in self.RETRYABLE_STATUSES:
                if last_attempt:
                    logger.warning(
                        "%s still returning %s after %d attempts",
                        url,
                        response.status_code,
                        self.max_retries,
                    )
                    return None
                time.sleep(retry_delay)
                retry_delay *= 2
                continue

            if response.status_code != 200 or not response.content:
                logger.debug(
                    "%s returned %s with %d bytes",
                    url,
                    response.status_code,
                    len(response.content or b""),
                )
                return None

            content_type = response.headers.get("Content-Type", "image/jpeg")
            return response.content, content_type.split(";")[0].strip()
