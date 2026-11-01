"""Re-adopting album tracking rows after a reimport.

An import keeps every album it can match by Wikidata id, and a kept album's
tracking rows stay attached. An album the release drops is deleted, though,
so the tracking tables keep a Wikidata id alongside their nullable FK: the
rows survive the delete with ``album`` NULL, and when the album comes back
in a later release this pass points them at the new row. A row stored under
a secondary id is renamed to the primary here too. Until then every
``with_listen_status`` annotation reads False for it.

This is games' ``games.services.user_tracking_service`` in bulk. That one
works an album at a time, which is right when it is called for one game
being re-imported; called from this importer's thousand-row loop it would be
roughly four thousand extra queries inside a web request. Here the whole
pass runs once, after the loop, off a map the loop has already built.
"""

from collections import defaultdict
from typing import Dict

from django.db import transaction
from django.db.models import Q

from music import models


def reconnect_tracking_records(id_to_album: Dict[str, models.Album]) -> Dict:
    """Point orphaned tracking rows at the albums that replaced them.

    Args:
        id_to_album: every key a tracking row may be stored under, mapped
            to the album it now belongs to: every Wikidata id each album
            carries, its ``Album.tracking_key``, and the keys a kept album had
            before this release changed its ids. Taking all of
            ``Album.all_wikidata_ids`` rather than only the primary one is
            what lets a row stored under a secondary id find its way home;
            the earlier keys are what rename a row when its album gains or
            loses a QID.

    Returns:
        A dict of counts per model, plus ``users``, whose caches the caller
        drops with the rest of the import's once it has committed.
    """
    stats = {}
    affected_users = set()

    for model_class, label in (
        (models.ListenedAlbum, "listened"),
        (models.WantToListenAlbum, "want"),
    ):
        result = _reconnect_model_records(
            model_class=model_class, id_to_album=id_to_album
        )
        stats[f"{label}_reconnected"] = result["reconnected"]
        stats[f"{label}_merged"] = result["merged"]
        affected_users |= result["users"]

    stats["users"] = affected_users

    return stats


def _reconnect_model_records(*, model_class, id_to_album: Dict) -> Dict:
    """One model's pass: re-point, normalize to the primary id, merge dupes.

    Two rows can end up pointing at one album - the release used to list
    them separately, or a user tracked an album under two of its Wikidata
    ids - and ``unique_together`` on (user, wikidata_id) would reject the
    second once both normalize to the same primary id. The duplicates are
    therefore deleted *before* the survivors are updated, never after.
    """
    rows = list(model_class.objects.filter(wikidata_id__in=id_to_album.keys()))
    if not rows:
        return {"reconnected": 0, "merged": 0, "users": set()}

    # Group by where each row is headed, so duplicates are visible.
    grouped = defaultdict(list)
    for row in rows:
        album = id_to_album[row.wikidata_id]
        grouped[(row.user_id, album.pk)].append(row)

    survivors = []
    duplicates = []
    users = set()
    original_keys = {}
    for group in grouped.values():
        album = id_to_album[group[0].wikidata_id]
        # The QID, or pk:<id> for an album without one; a row is renamed to
        # it when the album gains or loses a QID.
        key = album.tracking_key
        if len(group) == 1 and (
            group[0].album_id == album.pk and group[0].wikidata_id == key
        ):
            # Already right, as every row on a kept album is: rewriting it
            # would only drop its user's caches for nothing.
            continue
        # The earliest record is the one the user actually made; a later
        # duplicate is an artefact of the id change.
        group.sort(key=earliest_first)
        keeper = group[0]
        # The cached sets hold album pks, split by ``owned``: a row only
        # renamed (its album gaining or losing a QID) leaves them right, but
        # a merge can change ``owned``.
        if len(group) > 1 or keeper.album_id != album.pk:
            users.add(keeper.user_id)
        # Ownership is a fact about the user, not about which id they used:
        # merging must not drop a "Have" because the earliest row was a
        # plain "Heard".
        if hasattr(keeper, "owned"):
            keeper.owned = any(row.owned for row in group)
        original_keys[keeper.pk] = keeper.wikidata_id
        keeper.album = album
        keeper.wikidata_id = key
        survivors.append(keeper)
        duplicates.extend(group[1:])

    if not survivors:
        return {"reconnected": 0, "merged": 0, "users": set()}

    # A rename must not collide with the ``unique_together``: if the key is
    # already the user's for another row that stays (two albums sharing a
    # QID, which the release should not do), the survivor keeps its old key
    # and is only re-pointed.
    leaving = {row.pk for row in survivors} | {row.pk for row in duplicates}
    taken = {
        (user_id, key)
        for pk, user_id, key in model_class.objects.filter(
            user_id__in={row.user_id for row in survivors},
            wikidata_id__in={row.wikidata_id for row in survivors},
        ).values_list("pk", "user_id", "wikidata_id")
        if pk not in leaving
    }
    for row in survivors:
        if (row.user_id, row.wikidata_id) in taken:
            row.wikidata_id = original_keys[row.pk]
        taken.add((row.user_id, row.wikidata_id))

    with transaction.atomic():
        if duplicates:
            model_class.objects.filter(pk__in=[row.pk for row in duplicates]).delete()
        fields = ["album", "wikidata_id"]
        if hasattr(model_class, "owned"):
            fields.append("owned")
        model_class.objects.bulk_update(survivors, fields)

    return {
        "reconnected": len(survivors),
        "merged": len(duplicates),
        "users": users,
    }


def earliest_first(row):
    """Sort key putting the row the user actually made first.

    The rule every merge of one user's rows for one album keeps: the
    reconnection pass here and the toggle's write alike.
    """
    return (row.created is None, row.created, row.pk)


def write_tracking_row(model_class, user, album, **fields):
    """Point ``user``'s one row in ``model_class`` for ``album`` at it.

    A row is the album's by its current ``tracking_key`` or by its FK, so
    one under an older key (a QID edited in the admin) is found and renamed,
    and one orphaned by a reimport is re-adopted. The earliest is kept and
    any other deleted first, so the rename cannot collide with the
    ``unique_together``. Callers hold the toggle's per-user lock, so the
    read and the write cannot race.
    """
    rows = sorted(rows_for(model_class, user, album), key=earliest_first)
    if not rows:
        model_class.objects.create(
            user=user, album=album, wikidata_id=album.tracking_key, **fields
        )
        return
    keeper, *extra = rows
    model_class.objects.filter(pk__in=[row.pk for row in extra]).delete()
    keeper.album = album
    keeper.wikidata_id = album.tracking_key
    for name, value in fields.items():
        setattr(keeper, name, value)
    keeper.save()


def rows_for(model_class, user, album):
    """``user``'s rows in ``model_class`` for ``album``, by key or by FK."""
    return model_class.objects.filter(
        Q(wikidata_id=album.tracking_key) | Q(album=album), user=user
    )
