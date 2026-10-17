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

CACHE_KEY_YEAR_STATS = "album_year_stats"

# =============================================================================
# Import Settings
# =============================================================================

IMPORT_BATCH_SIZE = 1000
