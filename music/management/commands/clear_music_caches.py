"""Drop the music section's cached values, readers' tracked-album sets included.

The fix a failed drop's warning names: the write has committed by then, and
this does nothing but retry the drop.
"""

from django.core.management.base import BaseCommand, CommandError

from music.models import ListenedAlbum, WantToListenAlbum
from music.services import caching


class Command(BaseCommand):
    help = "Drop the music section's cached values, for every reader too."

    def handle(self, *args, **options):
        readers = set()
        for model_class in (ListenedAlbum, WantToListenAlbum):
            readers.update(
                model_class.objects.order_by()
                .values_list("user_id", flat=True)
                .distinct()
            )
        if not caching.invalidate_release_caches(readers):
            raise CommandError("Caches not cleared; the error is in the log.")
        self.stdout.write(self.style.SUCCESS("Music caches cleared."))
