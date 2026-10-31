"""The games app's views, by page.

Split out of a single 4,000-line module on 2026-10-26. Every name is
re-exported here, so `games.views.X` - in urls.py, the 404 handler
setting and the tests - keeps working. Patch a name in the module that
reads it (`games.views.rankings._get_year_bounds`), not here.
"""

from ._helpers import (
    _get_year_bounds,
    _get_hero_stats,
    _facet_cache_key,
    _genre_ids_with_games_or_descendant_games,
    _get_played_game_ids,
    _get_want_to_play_game_ids,
)
from .filter_titles import (
    _join_names,
    _build_time_window,
    _build_platform_segment,
    _build_genre_subtitle,
    _build_filter_title,
)
from .download import (
    download_games_csv,
)
from .rankings import (
    _order_games,
    HomePageView,
    _landing_itemlist_json,
    SeoRankingPageView,
    CategoryRankingView,
    YearRankingView,
    DecadeRankingView,
    BrowseIndexView,
)
from .game_pages import (
    GameDetailView,
    _game_json_ld,
    TogglePlayedGameView,
)
from .developers import (
    DeveloperListView,
    StudioListView,
    DeveloperDetailView,
    DeveloperRedirectView,
)
from .lists import (
    ListListView,
)
from .content import (
    ContactFormView,
    ContactThankYouView,
    PageDetailView,
    news_gone,
    ArticleListView,
    ArticleDetailView,
    NotFoundView,
    custom_404_view,
    robots_txt,
    UnsubscribeView,
)
from .imports import (
    ImportView,
    IGDBProgressView,
    WikipediaPageProgressView,
    BatchImportProgressView,
)
from .auth import (
    _referer_redirect_url,
    _rate_limited_form,
    _send_confirmation,
    AuthModalLoginView,
    AuthModalSignupView,
    AuthModalForgotPasswordView,
    AuthModalResendVerificationView,
    EmailConfirmationView,
    AuthModalProfileView,
    AuthLogoutView,
)

__all__ = [
    "_get_year_bounds",
    "_get_hero_stats",
    "_facet_cache_key",
    "_genre_ids_with_games_or_descendant_games",
    "_get_played_game_ids",
    "_get_want_to_play_game_ids",
    "_join_names",
    "_build_time_window",
    "_build_platform_segment",
    "_build_genre_subtitle",
    "_build_filter_title",
    "download_games_csv",
    "_order_games",
    "HomePageView",
    "_landing_itemlist_json",
    "SeoRankingPageView",
    "CategoryRankingView",
    "YearRankingView",
    "DecadeRankingView",
    "BrowseIndexView",
    "GameDetailView",
    "_game_json_ld",
    "TogglePlayedGameView",
    "DeveloperListView",
    "StudioListView",
    "DeveloperDetailView",
    "DeveloperRedirectView",
    "ListListView",
    "ContactFormView",
    "ContactThankYouView",
    "PageDetailView",
    "news_gone",
    "ArticleListView",
    "ArticleDetailView",
    "NotFoundView",
    "custom_404_view",
    "robots_txt",
    "UnsubscribeView",
    "ImportView",
    "IGDBProgressView",
    "WikipediaPageProgressView",
    "BatchImportProgressView",
    "_referer_redirect_url",
    "_rate_limited_form",
    "_send_confirmation",
    "AuthModalLoginView",
    "AuthModalSignupView",
    "AuthModalForgotPasswordView",
    "AuthModalResendVerificationView",
    "EmailConfirmationView",
    "AuthModalProfileView",
    "AuthLogoutView",
]
