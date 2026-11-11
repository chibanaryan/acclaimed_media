import logging
import threading
import time
from collections import OrderedDict
from typing import Any, Dict, List, Optional

import requests
from django.conf import settings

from games import config

logger = logging.getLogger(__name__)


# Genre themes that match our curated genre list
# Imported from config for centralized management
genre_themes = config.IGDB_GENRE_THEMES


# Seconds to wait on IGDB, to connect and again for each read. Its
# answers take well under one; the token request has always used the same.
REQUEST_TIMEOUT = 30


class GameNotFound(LookupError):
    """IGDB has no one game under the id asked for: dropped, or merged away."""


# Companies per request: IGDB's page size, past which it drops the rest
COMPANIES_PER_REQUEST = 500
# How far up a company's parents are followed
MAX_PARENT_DEPTH = 10


def _chosen_company_ids(data) -> List[int]:
    """The companies a game is credited to: its developers, or failing
    those its supporting studios, publishers or porters, in that order."""
    roles = {"developer": [], "supporting": [], "publisher": [], "porting": []}
    for involved in data.get("involved_companies", []):
        company_id = involved.get("company") if isinstance(involved, dict) else None
        if not company_id:
            continue
        for role, ids in roles.items():
            if involved.get(role):
                ids.append(company_id)
    for role in ("developer", "supporting", "publisher", "porting"):
        if roles[role]:
            return roles[role]
    return []


class IgbdApi:
    """
    Client for interacting with the IGDB (Internet Game Database) API.

    Handles authentication, caching, and data retrieval from IGDB API endpoints.
    """

    def __init__(
        self, client_id: str, client_secret: str, use_pro_tier: bool = False
    ) -> None:
        """
        Initialize the IGDB API client.

        Args:
            client_id: IGDB API client ID
            client_secret: IGDB API client secret
            use_pro_tier: Whether to use Pro tier endpoints and rate limits
        """
        self.client_id: str = client_id
        self.client_secret: str = client_secret
        self.use_pro_tier: bool = use_pro_tier

        self.headers: Dict[str, str] = {}
        # LRU caches with size limits to prevent memory leaks
        self.company_cache: OrderedDict[int, Dict[str, Any]] = OrderedDict()
        self.game_cache: OrderedDict[int, Dict[str, Any]] = OrderedDict()
        self.company_cache_max_size: int = config.IGDB_COMPANY_CACHE_MAX_SIZE
        self.game_cache_max_size: int = config.IGDB_GAME_CACHE_MAX_SIZE
        # Bounded dictionaries (populated once from IGDB API, finite size)
        self.release_date_statuses: Dict[str, int] = {}
        self.themes: Dict[int, str] = {}

        # Thread safety locks
        self.rate_limit_lock: threading.Lock = threading.Lock()
        self.cache_lock: threading.Lock = threading.Lock()

        # Rate limiting and batch size based on tier
        if use_pro_tier:
            # Pro tier: 3000 requests/second
            # Using configured rate to stay safely below the limit
            self.min_request_interval: float = 1.0 / config.IGDB_PRO_TIER_RATE_LIMIT
            self.max_batch_size: int = config.IGDB_PRO_TIER_BATCH_SIZE
        else:
            # Free tier: 4 requests/second
            # Using configured rate to stay safely below the limit
            self.min_request_interval: float = 1.0 / config.IGDB_FREE_TIER_RATE_LIMIT
            self.max_batch_size: int = config.IGDB_FREE_TIER_BATCH_SIZE
        self.last_request_time: float = 0.0

        self._get_auth_token()
        self._get_release_statuses()
        self._get_themes()

    def _get_from_company_cache(self, company_id: int) -> Optional[Dict[str, Any]]:
        """
        Get company from cache with LRU update (moves to end).
        Thread-safe.
        """
        if company_id in self.company_cache:
            # Move to end (most recently used)
            value = self.company_cache.pop(company_id)
            self.company_cache[company_id] = value
            return value
        return None

    def _set_in_company_cache(self, company_id: int, value: Dict[str, Any]) -> None:
        """
        Set company in cache with LRU eviction if at max size.
        Thread-safe.
        """
        if company_id in self.company_cache:
            # Update existing: move to end
            self.company_cache.pop(company_id)
        elif len(self.company_cache) >= self.company_cache_max_size:
            # Evict oldest (first item)
            self.company_cache.popitem(last=False)
        self.company_cache[company_id] = value

    def _get_from_game_cache(self, game_id: int) -> Optional[Dict[str, Any]]:
        """
        Get game from cache with LRU update (moves to end).
        Thread-safe.
        """
        if game_id in self.game_cache:
            # Move to end (most recently used)
            value = self.game_cache.pop(game_id)
            self.game_cache[game_id] = value
            return value
        return None

    def _set_in_game_cache(self, game_id: int, value: Dict[str, Any]) -> None:
        """
        Set game in cache with LRU eviction if at max size.
        Thread-safe.
        """
        if game_id in self.game_cache:
            # Update existing: move to end
            self.game_cache.pop(game_id)
        elif len(self.game_cache) >= self.game_cache_max_size:
            # Evict oldest (first item)
            self.game_cache.popitem(last=False)
        self.game_cache[game_id] = value

    def _get_endpoint_url(self, endpoint: str) -> str:
        """
        Get the full URL for an IGDB API endpoint.

        Args:
            endpoint: Endpoint name (e.g., 'games', 'companies', 'genres')

        Returns:
            Full URL for the endpoint, using Pro tier path if enabled
        """
        if self.use_pro_tier:
            return f"https://api.igdb.com/pro/v4/{endpoint}/"
        else:
            return f"https://api.igdb.com/v4/{endpoint}/"

    def _wait_for_rate_limit(self) -> None:
        """
        Enforce rate limiting by sleeping if necessary.

        Thread-safe implementation that ensures requests are spaced at least
        min_request_interval apart, respecting the IGDB API's 4 requests/second
        limit (using 3.8 for safety).
        """
        with self.rate_limit_lock:
            elapsed = time.time() - self.last_request_time
            if elapsed < self.min_request_interval:
                sleep_time = self.min_request_interval - elapsed
                time.sleep(sleep_time)
            self.last_request_time = time.time()

    def _make_request_with_retry(
        self, url: str, data: str, max_retries: int = 3
    ) -> Optional[requests.Response]:
        """
        Make an API request with rate limiting and exponential backoff for retries.

        Args:
            url: The API endpoint URL
            data: The request body/data
            max_retries: Maximum number of retries on 429 errors (default: 3)

        Returns:
            The response object if successful, None if all retries fail
        """
        retry_count = 0
        while retry_count <= max_retries:
            self._wait_for_rate_limit()
            try:
                # With a timeout, as every other fetcher has: a connection
                # IGDB accepts and then never answers held its thread, and
                # the metadata lock with it, for good.
                response = requests.post(
                    url, headers=self.headers, data=data, timeout=REQUEST_TIMEOUT
                )

                # Handle rate limiting (429 Too Many Requests)
                if response.status_code == 429:
                    if retry_count < max_retries:
                        wait_time = (
                            2**retry_count
                        )  # Exponential backoff: 1s, 2s, 4s, etc.
                        logger.warning(
                            "Rate limited by IGDB API. Retrying in %d seconds... "
                            "(attempt %d/%d)",
                            wait_time,
                            retry_count + 1,
                            max_retries + 1,
                        )
                        time.sleep(wait_time)
                        retry_count += 1
                        continue
                    else:
                        logger.error(
                            "Rate limited by IGDB API. Max retries (%d) exceeded.",
                            max_retries,
                        )
                        return None

                return response

            except requests.RequestException as exc:
                logger.warning("Request failed: %s", exc)
                return None

        return None  # pragma: no cover - defensive return, loop exits via other paths

    def _get_auth_token(self) -> bool:
        """
        Authenticate with IGDB API and store access token in headers.

        Returns:
            bool: True if authentication was successful, False otherwise
        """
        # Check if credentials are set (not default "XXX")
        if self.client_id == "XXX" or self.client_secret == "XXX":
            logger.warning(
                "IGDB credentials not configured. "
                "Set IGDB_CLIENT_ID and IGDB_CLIENT_SECRET environment variables."
            )
            return False

        # The credentials go in the form body, not the query string: a
        # failed raise_for_status() puts the URL in its message, and that
        # message is logged (and so sent to Sentry).
        token_url = "https://id.twitch.tv/oauth2/token"
        credentials = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "client_credentials",
        }

        try:
            response = requests.post(
                token_url, data=credentials, timeout=REQUEST_TIMEOUT
            )
            response.raise_for_status()
            data = response.json()
        except requests.RequestException as exc:
            logger.warning("Failed to authenticate with IGDB API: %s", exc)
            return False
        except ValueError as exc:
            logger.warning("Invalid JSON response from IGDB auth: %s", exc)
            return False

        if data.get("access_token"):
            self.headers = {
                "Client-Id": self.client_id,
                "Authorization": f'Bearer {data["access_token"]}',
            }
            return True
        else:
            logger.warning("IGDB authentication failed: no access token returned")
            return False

    def _get_themes(self) -> None:
        """
        Fetch and cache theme data from IGDB API.

        Themes are stored in self.themes as a dict mapping theme IDs to names.
        """
        # Check if headers are properly set (not just empty dict)
        if not self.headers or "Authorization" not in self.headers:
            logger.debug("Skipping IGDB themes fetch: authentication not available")
            self.themes = {}
            return

        try:
            res = self._make_request_with_retry(
                self._get_endpoint_url("themes"),
                data="limit 500; fields name;",
            )
            if res is None:
                self.themes = {}
                return
            res.raise_for_status()
            results = res.json()
        except Exception as exc:
            logger.warning("Unable to load IGDB themes: %s", exc)
            self.themes = {}
            return

        self.themes = {x["id"]: x["name"] for x in results}

    def _get_release_statuses(self) -> None:
        """
        Fetch and cache release date status data from IGDB API.

        Release statuses are stored in self.release_date_statuses as a dict
        mapping status names to their IDs.
        """
        # Check if headers are properly set (not just empty dict)
        if not self.headers or "Authorization" not in self.headers:
            logger.debug(
                "Skipping IGDB release statuses fetch: " "authentication not available"
            )
            self.release_date_statuses = {}
            return

        try:
            res = self._make_request_with_retry(
                self._get_endpoint_url("release_date_statuses"),
                data="fields name;",
            )
            if res is None:
                self.release_date_statuses = {}
                return
            res.raise_for_status()
            results = res.json()
        except Exception as exc:
            logger.warning("Unable to load IGDB release statuses: %s", exc)
            self.release_date_statuses = {}
            return

        self.release_date_statuses = {x["name"]: x["id"] for x in results}

    def get_companies_by_ids(
        self, company_ids: list, cache_results: bool = True
    ) -> Dict[int, Dict[str, Any]]:
        """
        Batch fetch multiple companies from IGDB API by IDs.

        This method fetches company data for multiple IDs in a single request,
        significantly reducing the number of API calls needed.

        Args:
            company_ids: List of IGDB company IDs to fetch
            cache_results: Whether to use/store results in cache (default: True)

        Returns:
            Dict mapping company IDs to company data dicts with id, name, slug,
            parent fields. Companies not found or with errors are omitted.
        """
        if not company_ids:
            return {}

        # Check cache for already-fetched companies
        companies_dict = {}
        ids_to_fetch = []

        for company_id in company_ids:
            if cache_results:
                with self.cache_lock:
                    cached = self._get_from_company_cache(company_id)
                    if cached is not None:
                        companies_dict[company_id] = cached
                        continue
            ids_to_fetch.append(company_id)

        if not ids_to_fetch:
            return companies_dict

        # Batch fetch companies, at most a page per request: one request
        # capped at `limit 500` silently dropped the rest of a Pro-tier
        # batch's companies
        results = []
        for start in range(0, len(ids_to_fetch), COMPANIES_PER_REQUEST):
            chunk = ids_to_fetch[start : start + COMPANIES_PER_REQUEST]
            ids_str = ",".join(str(cid) for cid in chunk)
            try:
                res = self._make_request_with_retry(
                    self._get_endpoint_url("companies"),
                    data=(
                        f"where id = ({ids_str}); fields id,name,slug,parent; "
                        f"limit {COMPANIES_PER_REQUEST};"
                    ),
                )
                if res is None:
                    continue
                res.raise_for_status()
                results.extend(res.json())
            except Exception as exc:
                logger.warning("Unable to load IGDB companies %s: %s", chunk, exc)

        # Process results and update cache
        for company_data in results:
            company_id = company_data["id"]
            companies_dict[company_id] = company_data
            if cache_results:
                with self.cache_lock:
                    self._set_in_company_cache(company_id, company_data)

        return companies_dict

    def _company_tree(self, company_ids, cache_results) -> Dict[int, Dict[str, Any]]:
        """``company_ids`` and every parent above them, by id.

        A parent IGDB does not return is asked for once, not on every round.
        """
        companies = self.get_companies_by_ids(
            list(dict.fromkeys(company_ids)), cache_results
        )
        asked = set(company_ids)
        for _ in range(MAX_PARENT_DEPTH):  # a cycle cannot loop for ever
            parent_ids = {
                c.get("parent")
                for c in companies.values()
                if c.get("parent") and c.get("parent") not in asked
            }
            if not parent_ids:
                break
            asked |= parent_ids
            companies.update(self.get_companies_by_ids(list(parent_ids), cache_results))
        return companies

    def _game_data(self, data, company_ids, companies) -> Dict[str, Any]:
        """One game's answer from IGDB, as the importers read it.

        The single and batch lookups were two copies of this until
        2026-11-11, and had drifted: the single one read an involved
        company's flags by key and raised on any IGDB left out.
        """

        def chain(company_id: int, seen: set) -> Optional[dict]:
            """The company with its parents, as nested dicts."""
            if company_id in seen:
                return None  # a cycle
            seen.add(company_id)
            company = companies.get(company_id)
            if not company:
                return None
            parent_id = company.get("parent")
            return {
                "id": company_id,
                "name": company["name"],
                "slug": company.get("slug", ""),
                "parent": chain(parent_id, seen) if parent_id else None,
            }

        developers = [dev for dev in (chain(cid, set()) for cid in company_ids) if dev]

        theme_names = [
            self.themes.get(x)
            for x in data.get("themes", [])
            if self.themes.get(x) in genre_themes
        ]
        genre_names = [
            genre["name"]
            for genre in data.get("genres", [])
            if isinstance(genre, dict) and "name" in genre
        ]

        cover = data.get("cover")
        if cover and isinstance(cover, dict) and "url" in cover:
            cover_filename = cover["url"].split("/")[-1]
        else:
            cover_filename = None

        series = [
            {
                "id": collection["id"],
                "name": collection.get("name", ""),
                "slug": collection.get("slug", ""),
            }
            for collection in data.get("collections", [])
            if isinstance(collection, dict) and "id" in collection
        ]

        videos = data.get("videos", [])
        youtube_video_id = None
        if videos and isinstance(videos[0], dict):
            youtube_video_id = videos[0].get("video_id")

        return {
            "cover": cover_filename,
            "developers": developers,
            "genres": list(set(theme_names + genre_names)),
            "series": series,
            "storyline": data.get("storyline"),
            "summary": data.get("summary"),
            "url": data.get("url"),
            "slug": data.get("slug"),
            "youtube_video_id": youtube_video_id,
        }

    def get_games_info_by_ids(
        self, game_ids: list, cache_results: bool = True
    ) -> Dict[int, Dict[str, Any]]:
        """
        Batch fetch multiple games from IGDB API by IDs.

        This method fetches game data for multiple IDs in a single request,
        with field expansion for covers, genres, and companies. This significantly
        reduces the number of API calls needed.

        Args:
            game_ids: List of IGDB game IDs to fetch
            cache_results: Whether to use/store results in cache (default: True)

        Returns:
            Dict mapping game IDs to game data dicts with keys:
                - cover: Cover art filename
                - developers: List of developer dicts with id, name, slug, parent
                - genres: List of genre names (combination of genres and themes)
                - storyline: Game storyline text
                - summary: Game summary text
                - url: IGDB URL for the game
                - slug: IGDB slug for the game
            Games not found or with errors are omitted.
        """
        if not game_ids:
            return {}

        # Check cache for already-fetched games
        games_dict = {}
        ids_to_fetch = []

        for game_id in game_ids:
            if cache_results:
                with self.cache_lock:
                    cached = self._get_from_game_cache(game_id)
                    if cached is not None:
                        games_dict[game_id] = cached
                        continue
            ids_to_fetch.append(game_id)

        if not ids_to_fetch:
            return games_dict

        # Batch fetch games with field expansion
        ids_str = ",".join(str(gid) for gid in ids_to_fetch)
        try:
            res = self._make_request_with_retry(
                self._get_endpoint_url("games"),
                data=(
                    f"where id = ({ids_str}); "
                    "fields slug,cover.*,genres.*,first_release_date,"
                    "summary,storyline,url,themes,involved_companies.*,"
                    "collections.*,videos.*; "
                    "limit 500;"
                ),
            )
            if res is None:
                logger.warning("Failed to fetch batch game data after retries")
                return games_dict
            res.raise_for_status()
            results = res.json()
        except Exception as exc:
            logger.warning("Unable to load IGDB games %s: %s", ids_to_fetch, exc)
            return games_dict

        # Every game's chosen companies, and their parents, in a few requests
        chosen = {data["id"]: _chosen_company_ids(data) for data in results}
        companies = self._company_tree(
            [cid for ids in chosen.values() for cid in ids], cache_results
        )

        for data in results:
            game_id = data["id"]
            game_data = self._game_data(data, chosen[game_id], companies)
            games_dict[game_id] = game_data
            if cache_results:
                with self.cache_lock:
                    self._set_in_game_cache(game_id, game_data)

        return games_dict

    def get_game_info_by_id(
        self, game_id: int, cache_results: bool = True, _reauthenticated: bool = False
    ) -> Optional[Dict[str, Any]]:
        """
        Fetch comprehensive game information from IGDB API by game ID.

        Thread-safe implementation with cache locking. This method retrieves game
        data including cover art, developers, genres, and metadata. It intelligently
        selects developers from involved companies, preferring actual developers
        over supporters, publishers, and porters in that order.

        Args:
            game_id: IGDB game ID to fetch
            cache_results: Whether to use/store results in cache (default: True)

        Returns:
            Dict containing game data with keys:
                - cover: Cover art filename
                - developers: List of developer dicts with id, name, slug, parent
                - genres: List of genre names (combination of genres and themes)
                - storyline: Game storyline text
                - summary: Game summary text
                - url: IGDB URL for the game
                - slug: IGDB slug for the game
            Returns None if the game cannot be fetched or authentication fails.

        Raises:
            GameNotFound: IGDB answered, and not with one game: the id has
                been dropped or merged away.
        """
        # Check cache first (thread-safe)
        if cache_results:
            with self.cache_lock:
                cached = self._get_from_game_cache(game_id)
                if cached is not None:
                    return cached

        # Get game data from API with field expansion for cover, genres, and collections
        res = self._make_request_with_retry(
            self._get_endpoint_url("games"),
            data=(
                "where id="
                f"{game_id}; fields slug,cover.*,genres.*,first_release_date,"
                "summary,storyline,url,themes,involved_companies.*,"
                "collections.*,videos.*;"
            ),
        )

        if res is None:
            logger.warning(
                "Failed to fetch game data for game ID %s after retries", game_id
            )
            return None

        if res.status_code == 401:
            # One new token, once. IGDB answering 401 to a token it has
            # just issued recursed here until the stack ran out.
            if _reauthenticated or not self._get_auth_token():
                logger.warning("IGDB refused game ID %s: 401", game_id)
                return None
            return self.get_game_info_by_id(
                game_id, cache_results, _reauthenticated=True
            )

        # An error's body is not a list of games: read as one, a 500's
        # `{"message": ...}` was "IGDB returned 1 games" and a 503's
        # two-key body a game IGDB had dropped.
        try:
            res.raise_for_status()
            results = res.json()
        except (requests.RequestException, ValueError) as exc:
            logger.warning("Unable to load IGDB game %s: %s", game_id, exc)
            return None
        if not isinstance(results, list):
            logger.warning("IGDB answered game %s with no list of games", game_id)
            return None

        if len(results) != 1:
            # An id IGDB has dropped or merged answers with an empty list.
            # Raised, as the `assert` this replaces was, and to the same
            # callers: the importers count the game as failed and say why,
            # and the admin's Save keeps the edit and says so.
            raise GameNotFound(
                f"IGDB returned {len(results)} games for game ID {game_id}"
            )
        data = results[0]

        company_ids = _chosen_company_ids(data)
        companies = self._company_tree(company_ids, cache_results)
        game_data = self._game_data(data, company_ids, companies)

        if cache_results:
            with self.cache_lock:
                self._set_in_game_cache(game_id, game_data)

        return game_data


def get_api(use_pro_tier: bool = None) -> Optional[IgbdApi]:
    """
    Create and return an IGDB API client instance.

    Args:
        use_pro_tier: Whether to use Pro tier. If None, reads from settings.

    Returns:
        IgbdApi: Configured IGDB API client, or None if initialization fails
    """
    try:
        if use_pro_tier is None:
            use_pro_tier = getattr(settings, "IGDB_USE_PRO_TIER", False)
        return IgbdApi(
            settings.IGDB_CLIENT_ID, settings.IGDB_CLIENT_SECRET, use_pro_tier
        )
    except (ValueError, KeyError, AttributeError) as e:
        log = logger.debug if getattr(settings, "DEBUG", False) else logger.error
        log("Failed to initialize IGDB API: %s", e)
        return None
    except requests.RequestException as e:
        log = logger.info if getattr(settings, "DEBUG", False) else logger.error
        log("Network error initializing IGDB API: %s", e)
        return None
