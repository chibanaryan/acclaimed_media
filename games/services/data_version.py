"""A short hash identifying the current game data.

Shared by the bulk API endpoint and the rankings page, as music's is: the
page renders the version into the HTML, and a cached page is served only
while it is still current, since the client joins the page's rows to the
payload's by position. It lives here rather than in ``games.api.views`` so
that ``games.views`` does not have to import the API layer.
"""

import hashlib

from django.db.models import Count, Max, Sum

from .. import models

# Schema version - increment when API response format changes
# v2: Changed st->dv, studios/companies->developers (commit ac84d07c)
# v3: Added 'i' (IGDB ID) field for played game filtering
# v4: Added 'lc' (list_count) field for displaying list appearances
# v5: Added 'ys' (year_start) and 'ye' (year_end) to platforms for sorting
# v6: Force cache refresh after list_count data update
# v7: Added 'pt' (playtime) field for HLTB filtering
# v8: Added 'ptc' (playtime_completionist) field for HLTB 100% filtering
# v9: Updated HLTB bucket boundaries (short: 0-10h, medium: 10-30h, long: 30+h)
# v10: Removed game_modes - no longer supported
# v11: Populated platform year_start/year_end data for all 74 platforms
# v12: Added remaining prod platform year ranges and refreshed cached platform data
# v13: Open-ended games (HLTBGameData.is_open_ended) send no 'pt'/'ptc'
# v14: 'ni', each game's position in the server's name order
SCHEMA_VERSION = "14"


def compute_game_data_version():
    """Hash the game data's identity: counts, last change, playtimes.

    Six small queries, read on every rankings page render and on every hit
    of a cached one.

    The game count is in here because a deleted game moves no ``modified``,
    and the page's rows and the payload's are joined by position.
    """
    games = models.Game.objects.aggregate(count=Count("id"), modified=Max("modified"))
    game_modified = games["modified"].isoformat() if games["modified"] else ""

    # Get genre count (changes if genres are added/modified)
    genre_count = models.WikipediaGenre.objects.count()

    # Get series count (changes if series are added/removed)
    series_count = models.Series.objects.count()

    # Count games with series assignments
    games_with_series = models.Game.objects.filter(series__isnull=False).count()

    # The playtimes the payload serves. An HLTB save leaves Game.modified
    # alone, and the weekly refresh saves every row whether or not anything
    # changed, so fingerprint the values rather than updated_at
    hltb = models.Game.objects.aggregate(
        main=Sum("primary_hltb_game_data__main_story_hours"),
        completionist=Sum("primary_hltb_game_data__completionist_hours"),
    )
    # The open-ended set itself, not a sum a swap could preserve
    open_ended_ids = (
        models.Game.objects.filter(primary_hltb_game_data__is_open_ended=True)
        .order_by("id")
        .values_list("id", flat=True)
    )
    hltb_fingerprint = (
        f"{hltb['main']}:{hltb['completionist']}:"
        + hashlib.md5(",".join(map(str, open_ended_ids)).encode()).hexdigest()
    )

    # Combine into version string and hash it
    version_string = (
        f"{SCHEMA_VERSION}:{games['count']}:{game_modified}:{genre_count}"
        f":{series_count}:{games_with_series}:{hltb_fingerprint}"
    )
    return hashlib.md5(version_string.encode()).hexdigest()[:12]
