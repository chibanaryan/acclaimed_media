"""Cache invalidation for the music section.

Lives here rather than in ``music.views`` so the importer can call it:
``views`` imports ``import_handler``, so the dependency cannot run the other
way. It used to be a private helper on the view, which meant the import page
dropped the cached counts and the ``import_music_data`` management command
did not - and a command-line import left the heading reading "The top 500
most recommended albums across 54 critic lists" for up to 24 hours after the
release grew to 1000.
"""

from django.core.cache import cache

from music import config


def invalidate_music_caches() -> None:
    """Drop every cached filter option and count the section holds.

    ``config.CACHE_KEYS`` is the whole set, so a value that is cached without
    being listed there is a value nothing can invalidate.
    """
    cache.delete_many(list(config.CACHE_KEYS))
