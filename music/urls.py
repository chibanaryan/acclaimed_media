from django.urls import path

from music import views

app_name = "music"

urlpatterns = [
    # Album rankings
    path("", views.AlbumHomePageView.as_view(), name="home"),
    # Album search (HTMX endpoint)
    path("search/", views.AlbumSearchView.as_view(), name="search"),
    # Source lists behind the rankings
    path("lists/", views.MusicListListView.as_view(), name="list-list"),
    # Data import (staff only, like every music route)
    path("import/", views.MusicImportView.as_view(), name="import"),
    # Artist routes (before <slug:slug>/ so "artists" is not read as a slug)
    path("artists/", views.ArtistListView.as_view(), name="artist-list"),
    path(
        "artists/<slug:slug>/", views.ArtistDetailView.as_view(), name="artist-detail"
    ),
    # Album detail (catch-all slug pattern, must be last)
    path("<slug:slug>/", views.AlbumDetailView.as_view(), name="album-detail"),
]
