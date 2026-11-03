"""The metadata fetch a music import starts (see ``core.services.post_import``).

It is the Sunday job's routine run without ``--refresh-stale``: every pass
but Wikidata skips what has already landed, so a release that mostly repeats
the last costs about a minute, plus a few seconds for each album it adds. It
ends, as every run does, with the genre rebuild, the release dates, the
artist slugs and the cache drop.
"""

import logging

from django.core.management import call_command

from core.services import post_import

logger = logging.getLogger(__name__)

COMMAND = "fetch_album_metadata"


def refresh_after_import(stdout):
    """Run the fetch; the steps that failed, as ``post_import`` expects."""
    try:
        call_command(COMMAND, with_musicbrainz=True, stdout=stdout)
    except Exception:
        logger.exception("%s after a music import failed", COMMAND)
        return [COMMAND]
    return []


def schedule():
    """Start the fetch on a background thread; the line to show staff."""
    return post_import.schedule_after_commit("music", refresh_after_import)


def run_in_foreground(command):
    """Run the fetch on an import command's output."""
    post_import.run_in_foreground("music", refresh_after_import, command)


def hold():
    """The lock for other metadata work (``post_import.hold``), or ``None``."""
    return post_import.hold("music", refresh_after_import)


def resume():
    """Restart a fetch its worker took down; the line to show staff, or ``None``."""
    return post_import.resume_if_cut_short("music", refresh_after_import)


def run_weekly(command, work):
    """The weekly job's ``work``, never beside a fetch."""
    post_import.run_weekly("music", refresh_after_import, command, work)
