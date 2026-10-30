"""
URLconf of games.acclaimedmedia.org, and ``ROOT_URLCONF``.

Games keep the paths they had at the apex, so an old link needs only its host
changed (``urls_root`` redirects it).
"""

from django.urls import include, path, re_path
from django.views.generic import RedirectView

from acclaimedgames.urls_common import common_urlpatterns, with_debug_and_static
from games import views
from core.sitemaps import for_site
from games.sitemaps import sitemaps

handler404 = "games.views.custom_404_view"

urlpatterns = [
    # REST API includes (search endpoints now in app modules)
    path("api/", include("games.api.urls", namespace="games-api")),
    path("import/", views.ImportView.as_view(), name="import"),
    path(
        "import/igdb-progress/", views.IGDBProgressView.as_view(), name="igdb-progress"
    ),
    path(
        "import/wikipedia-page-progress/",
        views.WikipediaPageProgressView.as_view(),
        name="wikipedia-page-progress",
    ),
    path(
        "import/batch-progress/",
        views.BatchImportProgressView.as_view(),
        name="batch-import-progress",
    ),
    # Main site routes (Django + HTMX + Alpine.js)
    # Rankings is the homepage
    path("", views.HomePageView.as_view(), name="home"),
    path("download/", views.download_games_csv, name="games-download"),
    # Redirect old URLs to homepage (preserves query params)
    path(
        "rankings/",
        RedirectView.as_view(url="/", permanent=True, query_string=True),
        name="rankings-redirect",
    ),
    path(
        "games/",
        RedirectView.as_view(url="/", permanent=True, query_string=True),
        name="games-redirect",
    ),
    path(
        "games/search/",
        RedirectView.as_view(url="/", permanent=True, query_string=True),
        name="games-search",
    ),
    # SEO ranking pages under /games/ (the bare /games/ redirect above must
    # stay - the client-side filter JS pushes /games/?params URLs whose
    # reloads depend on it). Order matters: browse, then decade (digits+s),
    # then year (digits), then the catch-all slug.
    path("games/browse/", views.BrowseIndexView.as_view(), name="games-browse"),
    re_path(
        r"^games/(?P<decade>\d{3}0)s/$",
        views.DecadeRankingView.as_view(),
        name="games-by-decade",
    ),
    re_path(
        r"^games/(?P<year>\d{4})/$",
        views.YearRankingView.as_view(),
        name="games-by-year",
    ),
    re_path(
        r"^games/(?P<slug>[a-z0-9-]+)/$",
        views.CategoryRankingView.as_view(),
        name="games-by-category",
    ),
    path("game/<slug:slug>/", views.GameDetailView.as_view(), name="game-detail"),
    path(
        "game/<int:igdb_id>/toggle-played/",
        views.TogglePlayedGameView.as_view(),
        name="toggle-played-game",
    ),
    path("developers/", views.DeveloperListView.as_view(), name="developers-list"),
    path(
        "developers/<slug:slug>/",
        views.DeveloperDetailView.as_view(),
        name="developer-detail",
    ),
    path(
        "developer-alias/<int:id>/",
        views.DeveloperRedirectView.as_view(),
        name="developer-alias-redirect",
    ),
    path("lists/", views.ListListView.as_view(), name="list-list"),
    path("news/", views.news_gone, name="news-list"),
    # Blog/Articles
    path("blog/", views.ArticleListView.as_view(), name="article-list"),
    path("blog/<slug:slug>/", views.ArticleDetailView.as_view(), name="article-detail"),
    *common_urlpatterns(for_site("games", sitemaps)),
]

# Books routes - always included, but the views require staff access
# (StaffOnlyMixin / IsStaffOrHide), so the tables and routes exist in
# production before the flag is flipped.
books_urlpatterns = [
    path("api/books/", include("books.api.urls", namespace="books-api")),
    path("books/", include("books.urls", namespace="books")),
]
urlpatterns = with_debug_and_static(books_urlpatterns + urlpatterns)
