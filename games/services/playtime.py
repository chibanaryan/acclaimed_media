"""
Which HowLongToBeat hours the site presents as a time to beat.

HLTB's averages mean "time to finish" only for a game that has a finish
line. For League of Legends, World of Warcraft or Rocket League they are how
long people played before they stopped, so a playtime column, sort or filter
that mixed the two put a 1162-hour MOBA at the top of "longest" and a
five-hour car-football game under "short". Those games are flagged
``HLTBGameData.is_open_ended`` and are left out of everything here. Their
detail page still shows the hours, labelled as time invested.
"""

from django.db.models import Q, Sum

from games.models import HLTBGameData

PREFIX = "primary_hltb_game_data__"

MODE_FIELDS = {
    "main": "main_story_hours",
    "completionist": "completionist_hours",
}


def hours_field(mode, prefix=PREFIX):
    """The hours column for a completion mode; anything but 100% is Main."""
    return prefix + MODE_FIELDS.get(mode, MODE_FIELDS["main"])


def shown_q(prefix=PREFIX):
    """Rows whose hours are a time to beat."""
    return Q(**{f"{prefix}is_open_ended": False})


def shown_record(data):
    """``data`` (an ``HLTBGameData`` or None), or None if it is open-ended."""
    if data is None or data.is_open_ended:
        return None
    return data


def shown_hours(data, mode="main"):
    """
    The hours ``data`` (an ``HLTBGameData`` or None) shows for ``mode``, or
    None when it has none to show as a time to beat.
    """
    data = shown_record(data)
    if data is None:
        return None
    return getattr(data, MODE_FIELDS.get(mode, MODE_FIELDS["main"]))


def backlog_hours(user, want_to_play_count):
    """
    Total Main and 100% hours across ``user``'s want-to-play list, for the
    profile page. Open-ended games are left out: one MMO would add ~470h.
    """
    if not want_to_play_count:
        return {"main": None, "completionist": None}
    game_ids = user.want_to_play_games.filter(game__isnull=False).values_list(
        "game_id", flat=True
    )
    return HLTBGameData.objects.filter(
        shown_q(prefix=""), game_id__in=game_ids, is_primary=True
    ).aggregate(
        main=Sum(MODE_FIELDS["main"]),
        completionist=Sum(MODE_FIELDS["completionist"]),
    )
