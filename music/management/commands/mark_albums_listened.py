"""Mark albums as listened for one user, in bulk, by Wikidata id.

The listen status is normally set a click at a time by
``music.views.ToggleListenedAlbumView``. Importing a collection from
elsewhere - a RateYourMusic export, say - means setting several hundred at
once, which through the web would be several hundred requests.

The matching stays outside: an export names albums in prose, and deciding
that "E·MO·TION" is our "Emotion" is a judgement call that belongs with
whoever is looking at both lists. This command takes the Wikidata ids that
judgement produced and does only the database half, with the same semantics
the toggle has:

- the delete and the write run in one transaction, so a failure between
  them cannot leave the user tracking nothing;
- the write is an ``update_or_create`` keyed on the ``unique_together``, so
  re-running is harmless and a row orphaned by a reimport is re-adopted;
- marking an album listened clears any want-to-listen row for it, because
  the two are mutually exclusive;
- the per-user caches are dropped in ``transaction.on_commit``.

An id already marked listened is left alone rather than rewritten, so the
``created`` timestamp of a mark the user made themselves survives.
"""

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import User
from music import models
from music.services import caching


class Command(BaseCommand):
    help = (
        "Mark albums as listened for a user, given their Wikidata ids. "
        "Idempotent; clears any want-to-listen row for the same album."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--user",
            required=True,
            help="Username to mark the albums for (case-insensitive)",
        )
        source = parser.add_mutually_exclusive_group(required=True)
        source.add_argument(
            "--ids",
            help="Comma-separated Wikidata ids, e.g. Q212863,Q19003",
        )
        source.add_argument(
            "--ids-file",
            help="File of Wikidata ids, separated by commas or newlines",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would change, write nothing",
        )

    def handle(self, *args, **options):
        user = self._get_user(options["user"])
        wikidata_ids = self._read_ids(options)
        if not wikidata_ids:
            raise CommandError("No Wikidata ids given")

        # Every id each album carries, not just the primary one, so an id
        # the export matched against a secondary still finds its album -
        # the same reason music.services.user_tracking_service does it.
        by_any_id = {}
        for album in models.Album.objects.all():
            for album_id in [album.wikidata_id, *(album.all_wikidata_ids or [])]:
                if album_id:
                    by_any_id[album_id] = album

        albums, unknown = {}, []
        for wikidata_id in wikidata_ids:
            album = by_any_id.get(wikidata_id)
            if album is None:
                unknown.append(wikidata_id)
            else:
                # Keyed on the album, so two of its ids collapse to one mark.
                albums[album.pk] = album

        already = set(
            models.ListenedAlbum.objects.filter(
                user=user, album__in=albums.values()
            ).values_list("album_id", flat=True)
        )
        to_add = [album for pk, album in albums.items() if pk not in already]
        wants = list(
            models.WantToListenAlbum.objects.filter(
                user=user, album__in=albums.values()
            ).values_list("album__name", flat=True)
        )

        self._report(user, wikidata_ids, albums, already, to_add, wants, unknown)
        if options["dry_run"]:
            self.stdout.write(self.style.WARNING("Dry run: nothing written"))
            return

        with transaction.atomic():
            models.WantToListenAlbum.objects.filter(
                user=user, album__in=albums.values()
            ).delete()
            for album in to_add:
                models.ListenedAlbum.objects.update_or_create(
                    user=user,
                    wikidata_id=album.wikidata_id,
                    defaults={"album": album},
                )

        caching.invalidate_listen_caches([user.id])
        self.stdout.write(
            self.style.SUCCESS(
                f"Marked {len(to_add)} album(s) listened for {user.username}; "
                f"{len(already)} already were."
            )
        )

    def _get_user(self, username):
        user = User.objects.filter(username__iexact=username).first()
        if user is None:
            raise CommandError(f"No user named {username!r}")
        return user

    def _read_ids(self, options):
        raw = options["ids"]
        if raw is None:
            path = Path(options["ids_file"])
            if not path.is_file():
                raise CommandError(f"No such file: {path}")
            raw = path.read_text()
        seen = []
        for token in raw.replace(",", "\n").split():
            token = token.strip()
            if token and token not in seen:
                seen.append(token)
        return seen

    def _report(self, user, wikidata_ids, albums, already, to_add, wants, unknown):
        self.stdout.write(f"User:            {user.username} (id {user.id})")
        self.stdout.write(f"Ids given:       {len(wikidata_ids)}")
        self.stdout.write(f"Albums matched:  {len(albums)}")
        self.stdout.write(f"Already marked:  {len(already)}")
        self.stdout.write(f"To mark:         {len(to_add)}")
        if wants:
            self.stdout.write(
                self.style.WARNING(
                    f"Clearing {len(wants)} want-to-listen row(s): "
                    + ", ".join(sorted(wants))
                )
            )
        if unknown:
            self.stdout.write(
                self.style.WARNING(
                    f"{len(unknown)} id(s) match no album: " + ", ".join(unknown)
                )
            )
