"""Drop the music section's cached filter options and counts.

The fix a failed drop's warning names: the import has committed by then, and
this does nothing but retry the drop. Readers' tracked-album sets are not in
it: they cannot be listed, and they expire within five minutes anyway.
"""

from django.core.management.base import BaseCommand, CommandError

from music.services import caching


class Command(BaseCommand):
    help = "Drop the music section's cached filter options and counts."

    def handle(self, *args, **options):
        if not caching.invalidate_music_caches():
            raise CommandError("Caches not cleared; the error is in the log.")
        self.stdout.write(self.style.SUCCESS("Music caches cleared."))
