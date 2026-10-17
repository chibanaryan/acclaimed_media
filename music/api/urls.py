"""
Music API URL patterns.

Mirrors the structure of games/api/urls.py and books/api/urls.py.
"""

from django.urls import path

from . import views

app_name = "music-api"

urlpatterns = [
    # Search
    path("search/", views.AlbumSearchAPIView.as_view(), name="album-search"),
    # Albums
    path("", views.AlbumListView.as_view(), name="album-list"),
    # Artists
    path("artists/", views.ArtistListView.as_view(), name="artist-list"),
    path(
        "artists/<slug:slug>/", views.ArtistDetailView.as_view(), name="artist-detail"
    ),
    # Source lists
    path("lists/", views.MusicListListView.as_view(), name="musiclist-list"),
    # Genres
    path("genres/", views.MusicGenreListView.as_view(), name="genre-list"),
    # Metadata
    path("meta/", views.MusicMetaView.as_view(), name="meta"),
    # Album detail - must be last (the slug pattern catches everything)
    path("<slug:slug>/", views.AlbumDetailView.as_view(), name="album-detail"),
]
