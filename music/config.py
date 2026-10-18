"""
Configuration constants for the Music application.

Centralizes cache timeouts, pagination defaults, and other settings.
Mirrors the structure of games/config.py and books/config.py.
"""

# =============================================================================
# Cache Timeouts (in seconds)
# =============================================================================

CACHE_TIMEOUT_5_MINUTES = 60 * 5  # 300 seconds
CACHE_TIMEOUT_1_HOUR = 60 * 60  # 3600 seconds
CACHE_TIMEOUT_24_HOURS = 60 * 60 * 24  # 86400 seconds
CACHE_TIMEOUT_DEFAULT = CACHE_TIMEOUT_24_HOURS

# Cache version - bump this to invalidate all caches after schema/data changes
CACHE_VERSION = "v1"

# =============================================================================
# Pagination Defaults
# =============================================================================

DEFAULT_PAGE_SIZE = 100
SEARCH_PAGE_SIZE = 100

# =============================================================================
# Year Defaults
# =============================================================================

DEFAULT_MIN_YEAR = 1950  # The supplied rankings start at 1955

# =============================================================================
# Cache Keys
# =============================================================================

# Every key carries CACHE_VERSION, so one bump invalidates the whole set, and
# every key appears in CACHE_KEYS, which `music.views._invalidate_music_caches`
# iterates - a new cached option cannot be added without being invalidated too.
CACHE_KEY_YEAR_STATS = f"{CACHE_VERSION}:album_year_stats"
CACHE_KEY_ARTIST_OPTIONS = f"{CACHE_VERSION}:music_artist_options"
CACHE_KEY_GENRE_OPTIONS = f"{CACHE_VERSION}:music_genre_options"
CACHE_KEY_DECADE_COUNTS = f"{CACHE_VERSION}:music_decade_counts"
CACHE_KEY_HERO_STATS = f"{CACHE_VERSION}:music_hero_stats"
CACHE_KEY_TOTAL_ALBUM_COUNT = f"{CACHE_VERSION}:total_album_count"

CACHE_KEYS = (
    CACHE_KEY_YEAR_STATS,
    CACHE_KEY_ARTIST_OPTIONS,
    CACHE_KEY_GENRE_OPTIONS,
    CACHE_KEY_DECADE_COUNTS,
    CACHE_KEY_HERO_STATS,
    CACHE_KEY_TOTAL_ALBUM_COUNT,
)

# =============================================================================
# Import Settings
# =============================================================================

IMPORT_BATCH_SIZE = 1000

# =============================================================================
# Metadata Pipeline
# =============================================================================

# API endpoints
WIKIDATA_API_URL = "https://www.wikidata.org/w/api.php"
DISCOGS_API_URL = "https://api.discogs.com"
MUSICBRAINZ_API_URL = "https://musicbrainz.org/ws/2"
COVER_ART_ARCHIVE_URL = "https://coverartarchive.org"

# User agent. MusicBrainz rejects requests without one carrying a contact
# address, and Discogs rejects requests without a descriptive one.
MUSIC_USER_AGENT = (
    "AcclaimedGamesBot/1.0 "
    "(https://www.acclaimedvideogames.com/; contact@acclaimedvideogames.com)"
)

# Rate limiting.
# - MusicBrainz publishes a hard average of 1 request/second per IP and
#   answers 503 past it, so leave headroom.
# - The Cover Art Archive documents no rate limiting at all; be polite anyway.
# - Discogs reported X-Discogs-Ratelimit: 25 (per minute) unauthenticated. A
#   token raises that, by an amount the docs would not serve, so the client
#   paces itself from the response headers and treats this as the floor.
MUSICBRAINZ_REQUEST_DELAY = 1.1
COVER_ART_REQUEST_DELAY = 0.2
DISCOGS_REQUEST_DELAY = 2.5

# Wikidata lets wbgetentities take 50 entity ids per request for ordinary
# clients, which turns 500 albums into 10 round trips.
WIKIDATA_BATCH_SIZE = 50

# Wikidata properties read off an album entity.
WIKIDATA_PERFORMER_PROPERTY = "P175"
WIKIDATA_GENRE_PROPERTY = "P136"
WIKIDATA_RELEASE_DATE_PROPERTY = "P577"
WIKIDATA_LABEL_PROPERTY = "P264"
WIKIDATA_MUSICBRAINZ_RELEASE_GROUP_PROPERTY = "P436"
WIKIDATA_DISCOGS_MASTER_PROPERTY = "P1954"
WIKIDATA_SPOTIFY_PROPERTY = "P2205"

# Read off an artist entity, so Artist.musicbrainz_id needs no MusicBrainz call.
WIKIDATA_ARTIST_MUSICBRAINZ_PROPERTY = "P434"

# Cover Art Archive thumbnail sizes. 250 covers the 90px rows at 2x, 500 the
# 300px detail image.
COVER_ART_THUMBNAIL_SIZES = (250, 500, 1200)
