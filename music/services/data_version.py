"""A short hash identifying the current album data.

Shared by the bulk API endpoint and the rankings page: the page renders the
version into the HTML so the client can tell whether the copy it is holding
is still current, which saves the extra round trip a ``version/`` endpoint
would cost. It lives here rather than in ``music.api.views`` so that
``music.views`` does not have to import the API layer.
"""

import hashlib

from django.db.models import Count, Max

from .. import models

# Bumped when the shape of the ``all/`` payload changes, so a client holding
# a copy of it discards that copy rather than reading fields that moved.
SCHEMA_VERSION = 2


def compute_album_data_version():
    """Hash the album data's identity: counts, last change, cover art.

    Cheap enough to compute on every rankings page render: three aggregates.

    The stored-cover-art count is in here deliberately. ``Album.thumbnail``
    reads through to ``primary_musicbrainz_album_data``, and the metadata
    pass writing cover art touches that row rather than the album, so
    ``Album.modified`` alone would leave a client holding a copy in which
    half the covers are missing, with no way to tell that it is stale.
    """
    aggregates = models.Album.objects.aggregate(
        count=Count("id"), modified=Max("modified")
    )
    genre_count = models.MusicGenre.objects.count()
    cover_count = models.MusicBrainzAlbumData.objects.filter(
        cover_art_stored=True
    ).count()
    version_string = (
        f"{SCHEMA_VERSION}:{aggregates['count']}:"
        f"{aggregates['modified']}:{genre_count}:{cover_count}"
    )
    return hashlib.md5(version_string.encode()).hexdigest()[:12]
