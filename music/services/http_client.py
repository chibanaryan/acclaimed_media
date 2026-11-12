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

    #: The longest a `Retry-After` is honoured for. A pass holds the
    #: metadata lock, and a service that asks for an hour is down.
    MAX_RETRY_AFTER: float = 60.0

    #: How long a client waits on `Retry-After` in all, beyond its own
    #: backoff. A service that is down says so to every request: honoured
    #: each time, a thousand records would wait two minutes apiece.
    RETRY_AFTER_ALLOWANCE: float = 300.0

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
        # Seconds waited on `Retry-After` beyond our own backoff
        self._retry_after_waited: float = 0.0
        self.rate_limit_lock = threading.Lock()

        # The HTTP status of the last ``get_json`` response, or None when
        # none came back, because get_json's None means a 404 and a throttle
        # alike. Not meaningful on a client shared between threads.
        self.last_status: Optional[int] = None

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

    def _retry_wait(self, response: requests.Response, retry_delay: float) -> float:
        """Seconds to wait before asking again after a retryable status.

        Our own backoff, or the server's `Retry-After` where that is longer
        (in seconds: a date is not read, and backs off as before), up to
        ``MAX_RETRY_AFTER`` a wait and ``RETRY_AFTER_ALLOWANCE`` a client,
        after which the backoff is our own again. It was ignored until
        2026-11-12, so a service that said when to come back was asked
        again after one second and two, and the record given up as a miss.
        """
        try:
            asked = float(response.headers.get("Retry-After", ""))
        except (TypeError, ValueError):
            asked = 0.0
        extra = min(asked, self.MAX_RETRY_AFTER) - retry_delay
        if extra <= 0 or self._retry_after_waited + extra > self.RETRY_AFTER_ALLOWANCE:
            return retry_delay
        self._retry_after_waited += extra
        return retry_delay + extra

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
            self.last_status = None
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
            self.last_status = response.status_code

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
                wait = self._retry_wait(response, retry_delay)
                logger.warning(
                    "%s returned %s (%s); backing off %.1fs",
                    url,
                    response.status_code,
                    reason,
                    wait,
                )
                time.sleep(wait)
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
        ends up at archive.org after a 307. A body that is not an image
        (``config.COVER_CONTENT_TYPES``), or is larger than a cover is, is
        no usable data either.

        The body is streamed, and given up on once it passes
        ``config.COVER_MAX_BYTES``: read whole first, as it was until
        2026-11-10, the ceiling bounded what was stored and not what a
        download could cost the worker running it.
        """
        retry_delay = self.initial_retry_delay

        for attempt in range(self.max_retries):
            self._wait_for_rate_limit()
            last_attempt = attempt == self.max_retries - 1

            try:
                response = self.session.get(url, timeout=self.timeout, stream=True)
                try:
                    # Inside the `try`: a body is read from the network, and
                    # can fail as the request can
                    outcome = self._read_image(url, response)
                finally:
                    # What was not read is not kept waiting on the connection
                    response.close()
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

            if outcome is not self._RETRY:
                return outcome
            if last_attempt:
                logger.warning(
                    "%s still returning %s after %d attempts",
                    url,
                    response.status_code,
                    self.max_retries,
                )
                return None
            time.sleep(self._retry_wait(response, retry_delay))
            retry_delay *= 2

    #: What ``_read_image`` answers for a status worth another attempt.
    _RETRY = object()

    #: How much of a body is read at a time.
    DOWNLOAD_CHUNK_BYTES = 64 * 1024

    def _read_image(self, url: str, response):
        """An open response's image as ``(body, content_type)``, None if it
        has none to keep, or ``_RETRY``."""
        if response.status_code in self.RETRYABLE_STATUSES:
            return self._RETRY
        if response.status_code != 200:
            logger.debug("%s returned %s", url, response.status_code)
            return None

        content_type = response.headers.get("Content-Type", "image/jpeg")
        content_type = content_type.split(";")[0].strip().lower()
        # Only an image, and of a size a cover is: see the config
        if content_type not in config.COVER_CONTENT_TYPES:
            logger.warning("%s is %s, not an image", url, content_type[:60])
            return None

        body = bytearray()
        for chunk in response.iter_content(self.DOWNLOAD_CHUNK_BYTES):
            body.extend(chunk)
            if len(body) > config.COVER_MAX_BYTES:
                logger.warning(
                    "%s is over %d bytes, too large for a cover",
                    url,
                    config.COVER_MAX_BYTES,
                )
                return None
        if not body:
            logger.debug("%s returned an empty body", url)
            return None
        return bytes(body), content_type
