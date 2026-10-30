"""A little of everything, for the browser smoke test on an empty database.

Run with `python manage.py shell < scripts/smoke_seed.py` (CI's `browser`
job). Enough that the rankings pages render rows, the filters have options,
and the detail pages exist; nothing else depends on it.
"""

from games.models import Developer, Game, Platform, Series, WikipediaGenre
from music.models import Album, Artist, MusicGenre

# Not WikipediaGenre: migrations seed the genre tree, so it is never empty
if any(
    model.objects.exists()
    for model in (Album, Artist, Developer, Game, Platform, Series)
):
    raise SystemExit("smoke_seed.py is for an empty database; this one has data.")

action = WikipediaGenre.objects.create(name="Smoke Action", slug="smoke-action")
shooter = WikipediaGenre.objects.create(
    name="Smoke Shooter", slug="smoke-shooter", parent=action, level=1
)
platforms = [
    Platform.objects.create(code=code, name=name)
    for code, name in (("SNES", "Super NES"), ("N64", "Nintendo 64"), ("PC", "PC"))
]
nintendo = Developer.objects.create(name="Nintendo", slug="nintendo", igdb_id=1)
studio = Developer.objects.create(name="Nintendo EAD", igdb_id=2, parent=nintendo)
saga = Series.objects.create(name="Smoke Saga", slug="smoke-saga", igdb_id=1)
for rank in range(1, 41):
    game = Game.objects.create(
        name=f"Smoke Game {rank}",
        slug=f"smoke-game-{rank}",
        rank=rank,
        igdb_id=100 + rank,
        year_of_release=1985 + rank % 35,
    )
    game.platforms.add(*platforms[: 1 + rank % 3])
    game.wikipedia_genres.add(shooter if rank % 2 else action)
    game.developers.add(studio if rank % 2 else nintendo)
    if rank % 5 == 0:
        game.series.add(saga)

rock = MusicGenre.objects.create(name="Smoke Rock", slug="smoke-rock")
artist = Artist.objects.create(name="Smoke Band", slug="smoke-band")
for rank in range(1, 21):
    album = Album.objects.create(
        name=f"Smoke Album {rank}",
        rank=rank,
        artist_credit=artist.name,
        year_released=1965 + rank * 2,
    )
    album.artists.set([artist])
    album.genres.set([rock])

print("seeded")
