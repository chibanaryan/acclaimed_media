"""The client-side filter engines order results exactly as the server does.

AGENTS.md asks for this check after any filter change, and it was run by
hand: unit tests on either side cannot catch a divergence, because both can
be self-consistently wrong. Here the server renders each query, Node runs the
real engine files on the same data (`core/tests/js/filter_parity.js`), and
the two orders must match. Skipped where Node is not installed, except in CI.
"""

import datetime
import json
import re
import tempfile
from pathlib import Path

from django.test import TestCase

from core.tests.node import require_node, run_node
from core.tests.utils import clear_all_caches
from games.models import Game, HLTBGameData, Platform, Series, WikipediaGenre
from music import models as music
from music.templatetags.music_filters import artist_links
from music.tests.site import music_site


def run_engines(payloads):
    """Run the harness on ``{section: {"payload", "queries"}}``."""
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
        json.dump(payloads, handle)
    try:
        return run_node("filter_parity.js", handle.name)
    finally:
        Path(handle.name).unlink()


class ParityTestCase(TestCase):
    def setUp(self):
        require_node()
        clear_all_caches()

    def _server_order(self, url, id_pattern):
        clear_all_caches()
        html = self.client.get(url).content.decode()
        return [int(pk) for pk in re.findall(id_pattern, html)]

    def assertSameOrder(self, section, queries, server_url, id_pattern, payload):
        engine = run_engines({section: {"payload": payload, "queries": queries}})
        for query in queries:
            with self.subTest(query=query):
                server = self._server_order(server_url.format(query=query), id_pattern)
                self.assertTrue(server or query, "the unfiltered page listed nothing")
                self.assertEqual(engine[section][query], server)

    def assertReversedRangeIsTheRange(
        self, section, forward, reversed_, server_url, id_pattern, payload
    ):
        """A range written backwards (by hand: no control writes one) is the
        range, on both sides. Each listed nothing, under "2000-1990", and
        the parity above holds as well when both list nothing."""
        engine = run_engines(
            {section: {"payload": payload, "queries": [forward, reversed_]}}
        )
        server = self._server_order(server_url.format(query=forward), id_pattern)
        self.assertTrue(server, "the range listed nothing")
        self.assertEqual(
            self._server_order(server_url.format(query=reversed_), id_pattern), server
        )
        self.assertEqual(engine[section][forward], server)
        self.assertEqual(engine[section][reversed_], server)


class GamesParityTests(ParityTestCase):
    @classmethod
    def setUpTestData(cls):
        root = WikipediaGenre.objects.create(name="Parity Action", slug="parity-action")
        child = WikipediaGenre.objects.create(
            name="Parity Shooter", slug="parity-shooter", parent=root, level=1
        )
        other = WikipediaGenre.objects.create(
            name="Parity Puzzle", slug="parity-puzzle"
        )
        cls.root, cls.child = root, child
        pc = Platform.objects.create(code="PCX", name="Parity PC")
        nes = Platform.objects.create(code="NSX", name="Parity NES")
        cls.pc = pc
        cls.series = Series.objects.create(
            name="Parity Saga", slug="parity-saga", igdb_id=1
        )
        names = [
            "Pokémon Red",
            "pokemon gold",
            "Zelda",
            "zelda II",
            "Ägypten",
            "Doom",
            "DOOM 64",
            "Ōkami",
            "Tetris",
            "'Splosion Man",
            "Ico",
            "Half-Life",
            "Half Life 2",
            "Myst",
            "Rez",
            "Braid",
            "Limbo",
            "Inside",
            "Fez",
            "Celeste",
        ]
        for rank, name in enumerate(names, start=1):
            game = Game.objects.create(
                name=name,
                slug=f"parity-{rank}",
                rank=rank,
                igdb_id=rank,
                year_of_release=1985 + (rank * 3) % 30,
            )
            game.platforms.add(pc if rank % 2 else nes)
            game.wikipedia_genres.add(
                child if rank % 3 == 0 else (root if rank % 3 == 1 else other)
            )
            if rank % 4 == 0:
                game.series.add(cls.series)
            hltb = HLTBGameData.objects.create(
                game=game,
                igdb_id=rank,
                hltb_id=str(rank),
                main_story_hours=(rank * 7) % 45 or None,
                completionist_hours=(rank * 11) % 90 or None,
                is_primary=True,
            )
            game.primary_hltb_game_data = hltb
            game.save()

    def test_the_engine_matches_the_server(self):
        payload = self.client.get("/api/games/all/").json()
        payload = payload.get("data", payload)
        queries = [
            "",
            "q=zelda",
            "q=pokemon",
            "q=half",
            "sort=name",
            "sort=name&dir=desc",
            "sort=year",
            "sort=year&dir=desc",
            "dir=desc",
            "start=1990&end=1999",
            "start=2000",
            # A range written backwards is the range, on both sides
            "start=1999&end=1990",
            # The older year parameters, and two at once: one range on
            # both sides (`resolve_year_range`, `currentFilterParams`)
            "year=1995",
            "decade=1990-99",
            "decade=1990-99&year=1995",
            "decade=1990-99&start=2000",
            "year=1995&end=2005",
            "decade=1995-99",
            f"genres={self.root.id}",
            f"genres={self.child.id}",
            f"platforms={self.pc.id}",
            f"series={self.series.id}",
            "hltb_min=10&hltb_max=30",
            "hltb_min=20",
            "sort=playtime",
            "sort=playtime&dir=desc",
            "hltb_mode=completionist&sort=playtime",
            f"genres={self.root.id}&sort=year&dir=desc",
            f"q=o&platforms={self.pc.id}&start=1990",
        ]
        self.assertSameOrder(
            "games", queries, "/?{query}&partial=true", r'id="game-(\d+)"', payload
        )

    def test_a_reversed_year_range_is_the_range(self):
        payload = self.client.get("/api/games/all/").json()
        self.assertReversedRangeIsTheRange(
            "games",
            "start=1990&end=1999",
            "start=1999&end=1990",
            "/?{query}&partial=true",
            r'id="game-(\d+)"',
            payload.get("data", payload),
        )
        forward = self.client.get("/?start=1990&end=1999")
        backward = self.client.get("/?start=1999&end=1990")
        self.assertEqual(
            backward.context["filter_title"], forward.context["filter_title"]
        )


@music_site
class MusicParityTests(ParityTestCase):
    @classmethod
    def setUpTestData(cls):
        rock = music.MusicGenre.objects.create(name="Parity Rock", slug="parity-rock")
        punk = music.MusicGenre.objects.create(
            name="Parity Punk", slug="parity-punk", parent=rock, level=1
        )
        jazz = music.MusicGenre.objects.create(name="Parity Jazz", slug="parity-jazz")
        cls.rock, cls.punk = rock, punk
        artists = [
            music.Artist.objects.create(name=name, slug=f"parity-artist-{n}")
            for n, name in enumerate(["Björk", "The Beatles", "Sigur Rós", "Nas"])
        ]
        cls.artist = artists[0]
        publication = music.MusicPublication.objects.create(name="Parity Mag")
        lists = [
            music.MusicList.objects.create(
                name=f"Parity List {n}", publisher=publication, year=2000 + n, type="A"
            )
            for n in range(3)
        ]
        names = [
            "Ágætis byrjun",
            "Abbey Road",
            "abbey road (remaster)",
            "Illmatic",
            "Homogenic",
            "Post",
            "Revolver",
            "Takk...",
            "( )",
            "Kid A",
            "Vespertine",
            "Debut",
            "Help!",
            "It Was Written",
            "Valtari",
        ]
        for rank, name in enumerate(names, start=1):
            year = 1966 + (rank * 5) % 40
            album = music.Album.objects.create(
                name=name,
                rank=rank,
                artist_credit=artists[rank % 4].name,
                year_released=year,
                release_date=(
                    datetime.date(year, 1 + rank % 12, 1) if rank % 3 else None
                ),
            )
            album.artists.set([artists[rank % 4]])
            album.genres.set(
                [punk if rank % 3 == 0 else (rock if rank % 3 == 1 else jazz)]
            )
            for game_list in lists[: 1 + rank % 3]:
                music.AlbumListMembership.objects.create(
                    album=album, list=game_list, rank=rank
                )
        # Credited under another of an artist's names, and with others: the
        # artist filter finds it by the artist, the search by the name.
        cls.artist.name_variants = ["Björk", "The Sugarcubes"]
        cls.artist.save()
        variant = music.Album.objects.create(
            name="Life's Too Good",
            rank=len(names) + 1,
            artist_credit="The Sugarcubes & Various Artists",
            various_artists=True,
            year_released=1988,
        )
        music.AlbumCredit.objects.create(
            album=variant,
            artist=cls.artist,
            variant=1,
            credited_name="The Sugarcubes",
        )
        variant.genres.set([rock])
        # An artist whose own name has quotes, credited as another: the
        # link's title must keep them inside the attribute.
        cls.quoted = music.Artist.objects.create(
            name='Bonnie "Prince" Billy',
            slug="parity-bpb",
            name_variants=['Bonnie "Prince" Billy', "Palace Brothers"],
        )
        cls.quoted_album = music.Album.objects.create(
            name="There Is No-One What Will Take Care of You",
            rank=len(names) + 2,
            artist_credit="Palace Brothers",
            year_released=1993,
        )
        music.AlbumCredit.objects.create(
            album=cls.quoted_album,
            artist=cls.quoted,
            variant=1,
            credited_name="Palace Brothers",
        )
        cls.quoted_album.genres.set([rock])
        music.AlbumListMembership.objects.create(
            album=cls.quoted_album, list=lists[0], rank=2
        )
        music.AlbumListMembership.objects.create(album=variant, list=lists[0], rank=1)

    def test_the_engine_matches_the_server(self):
        payload = self.client.get("/api/all/").json()
        payload = payload.get("data", payload)
        queries = [
            "",
            "q=abbey",
            "q=agaetis",
            "q=bjork",
            "q=sigur ros",
            "q=sugarcubes",
            "q=various",
            "sort=name",
            "sort=name&dir=desc",
            "sort=year",
            "sort=year&dir=desc",
            "sort=lists",
            "sort=lists&dir=desc",
            "start=1970&end=1989",
            # A range written backwards is the range, on both sides
            "start=1989&end=1970",
            f"genres={self.rock.id}",
            f"genres={self.punk.id}",
            f"artists={self.artist.slug}",
            f"genres={self.rock.id}&sort=year&dir=desc",
        ]
        self.assertSameOrder(
            "music",
            queries,
            "/?{query}&partial=true",
            r'id="music-(\d+)"',
            payload,
        )

    def test_a_reversed_year_range_is_the_range(self):
        payload = self.client.get("/api/all/").json()
        self.assertReversedRangeIsTheRange(
            "music",
            "start=1970&end=1989",
            "start=1989&end=1970",
            "/?{query}&partial=true",
            r'id="music-(\d+)"',
            payload.get("data", payload),
        )
        forward = self.client.get("/?start=1970&end=1989")
        backward = self.client.get("/?start=1989&end=1970")
        self.assertEqual(
            backward.context["filter_title"], forward.context["filter_title"]
        )
        self.assertEqual(backward.context["filters"], forward.context["filters"])
        api = self.client.get("/api/?start=1989&end=1970").json()
        self.assertEqual(
            api["count"], self.client.get("/api/?start=1970&end=1989").json()["count"]
        )
        self.assertGreater(api["count"], 0)

    def test_a_credit_is_found_without_its_accents(self):
        # The parity above holds just as well when both sides find nothing,
        # which is how "bjork" passed it while finding no Björk anywhere.
        for query, credit in (("bjork", "Björk"), ("sigur ros", "Sigur Rós")):
            with self.subTest(query=query):
                expected = list(
                    music.Album.objects.filter(artist_credit=credit).values_list(
                        "id", flat=True
                    )
                )
                self.assertTrue(expected)
                self.assertCountEqual(
                    self._server_order(
                        f"/?q={query}&partial=true", r'id="music-(\d+)"'
                    ),
                    expected,
                )

    def test_the_renderer_writes_the_servers_credit_line(self):
        # Each credit under its credited name, linked to the artist, and
        # "Various Artists" last - `artist_links` and `_artistCreditHtml`.
        # Compared as written, escapes and all: the renderer's escaper is
        # Django's (core/tests/test_escape_html.py). It went through the DOM
        # once, which leaves quotes alone, and the two had to be unescaped.
        payload = self.client.get("/api/all/").json()
        payload = payload.get("data", payload)
        client = run_engines(
            {"music": {"payload": payload, "queries": [], "credits": True}}
        )["musicCredits"]
        self.assertIn(
            'title="Bonnie &quot;Prince&quot; Billy">Palace Brothers</a>',
            client[str(self.quoted_album.id)],
        )
        for album in music.Album.objects.with_relations():
            with self.subTest(album=album.name):
                self.assertEqual(client[str(album.id)], str(artist_links(album)))

    def test_the_renderer_writes_the_servers_grid_cover(self):
        """A card rendered in the browser names the same two files as the
        page's own: it set no `srcset`, so after a filter change or a Load
        More a 2x screen showed the 250px cover stretched.

        One album for each shape a cover URL takes: our stored copy, the
        Cover Art Archive's, and a fallback URL with no sizes to choose.
        """
        albums = list(music.Album.objects.order_by("rank")[:4])
        shapes = {
            "stored": {"cover_art_stored": True},
            "remote": {"cover_art_stored": False},
        }
        for album, (shape, fields) in zip(albums, shapes.items()):
            record = music.MusicBrainzAlbumData.objects.create(
                album=album,
                release_group_mbid=f"group-{shape}",
                cover_art_release_mbid=f"release-{shape}",
                cover_art_image_id=f"1234{album.rank}",
                is_primary=True,
                **fields,
            )
            album.primary_musicbrainz_album_data = record
            album.save()
        fallback, bare = albums[2], albums[3]
        fallback.cover_image_url = "https://example.org/covers/fallback-500.jpg"
        fallback.save()

        payload = self.client.get("/api/all/").json()
        payload = payload.get("data", payload)
        client = run_engines(
            {"music": {"payload": payload, "queries": [], "credits": True}}
        )["musicCovers"]

        html = self.client.get("/?view=grid").content.decode()
        for album in music.Album.objects.filter(pk__in=[a.pk for a in albums[:3]]):
            with self.subTest(album=album.name):
                expected = f"{album.thumbnail} 1x, {album.image} 2x"
                self.assertEqual(client[str(album.id)], expected)
        # The stored and the remote shapes do name a larger file
        stored = music.Album.objects.get(pk=albums[0].pk)
        self.assertNotEqual(stored.thumbnail, stored.image)
        self.assertIn("-500.jpg 2x", client[str(stored.id)])
        # An album with no cover has no srcset on either side
        self.assertNotIn(str(bare.id), client)
        self.assertNotIn("None 1x", html)
