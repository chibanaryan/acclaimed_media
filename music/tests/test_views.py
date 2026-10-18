"""Tests for the music views.

Every music view is staff-only, so the tests authenticate as staff and each
suite also asserts that an anonymous visitor gets 404 rather than 403.
"""

from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from core import constants as core_constants
from core.models import User
from music import config, models, views
from music.views import _decade_options, _filter_title, group_list_appearances


class StaffUserTestMixin:
    """Provides a logged-in staff user, as the books tests do."""

    def setUp(self):
        super().setUp()
        self.staff_user = User.objects.create_user(
            username="musicstaff", password="musicpass", is_staff=True
        )
        self.client.login(username="musicstaff", password="musicpass")


class MusicDataMixin(StaffUserTestMixin):
    """A small but complete ranking: three albums over three lists."""

    def setUp(self):
        super().setUp()
        self.beatles = models.Artist.objects.create(
            name="The Beatles", slug="the-beatles"
        )
        self.young = models.Artist.objects.create(name="Neil Young", slug="neil-young")
        self.horse = models.Artist.objects.create(name="Crazy Horse", parent=self.young)
        self.rock = models.MusicGenre.objects.create(name="Rock")

        self.revolver = models.Album.objects.create(
            name="Revolver", rank=1, artist_credit="The Beatles", year_released=1966
        )
        self.revolver.artists.set([self.beatles])
        self.revolver.genres.set([self.rock])

        self.rust = models.Album.objects.create(
            name="Rust Never Sleeps",
            rank=2,
            artist_credit="Neil Young, Crazy Horse",
            year_released=1979,
        )
        self.rust.artists.set([self.young, self.horse])

        self.kid_a = models.Album.objects.create(
            name="Kid A", rank=3, artist_credit="Radiohead", year_released=2000
        )

        self.publication = models.MusicPublication.objects.create(name="Pitchfork")
        self.all_time = models.MusicList.objects.create(
            name="The Greatest Albums of All Time",
            year=2020,
            publisher=self.publication,
            order=1,
            type=core_constants.LIST_ALLTIME,
        )
        self.decade = models.MusicList.objects.create(
            name="The Best Albums of the 1960s",
            year=2017,
            publisher=self.publication,
            order=2,
            type=core_constants.LIST_DECADE,
        )
        self.misc = models.MusicList.objects.create(
            name="Best of the Past 25 Years",
            year=2010,
            publisher=self.publication,
            order=3,
            type=core_constants.LIST_MISC,
        )

        models.AlbumListMembership.objects.create(
            list=self.all_time, album=self.revolver, rank=1
        )
        models.AlbumListMembership.objects.create(
            list=self.decade, album=self.revolver, rank=2
        )
        models.AlbumListMembership.objects.create(
            list=self.misc, album=self.rust, rank=5
        )


class AlbumHomePageViewTests(MusicDataMixin, TestCase):
    def test_renders_every_album_in_rank_order(self):
        response = self.client.get(reverse("music:home"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual([a.rank for a in response.context["albums"]], [1, 2, 3])

    def test_anonymous_gets_404_not_403(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse("music:home")).status_code, 404)

    def test_non_staff_user_gets_404(self):
        User.objects.create_user(username="plain", password="plainpass")
        self.client.login(username="plain", password="plainpass")
        self.assertEqual(self.client.get(reverse("music:home")).status_code, 404)

    def test_search_matches_the_album_title(self):
        response = self.client.get(reverse("music:home"), {"q": "revolver"})
        self.assertEqual([a.name for a in response.context["albums"]], ["Revolver"])

    def test_search_matches_the_artist_credit(self):
        response = self.client.get(reverse("music:home"), {"q": "crazy horse"})
        self.assertEqual(
            [a.name for a in response.context["albums"]], ["Rust Never Sleeps"]
        )

    def test_search_matches_the_normalized_name(self):
        album = models.Album.objects.create(
            name="Déjà Vu", rank=4, artist_credit="CSN", year_released=1970
        )
        response = self.client.get(reverse("music:home"), {"q": "Deja"})
        self.assertIn(album, response.context["albums"])

    def test_year_range_filters_both_ends(self):
        response = self.client.get(
            reverse("music:home"), {"start": "1970", "end": "1990"}
        )
        self.assertEqual(
            [a.name for a in response.context["albums"]], ["Rust Never Sleeps"]
        )

    def test_a_non_numeric_year_is_ignored(self):
        response = self.client.get(
            reverse("music:home"), {"start": "nineteen", "end": ""}
        )
        self.assertEqual(len(response.context["albums"]), 3)

    def test_artist_filter(self):
        response = self.client.get(
            reverse("music:home"), {"artists": str(self.beatles.id)}
        )
        self.assertEqual([a.name for a in response.context["albums"]], ["Revolver"])

    def test_genre_filter(self):
        response = self.client.get(reverse("music:home"), {"genres": str(self.rock.id)})
        self.assertEqual([a.name for a in response.context["albums"]], ["Revolver"])

    def test_a_non_numeric_id_filter_is_ignored(self):
        response = self.client.get(
            reverse("music:home"), {"artists": "abc", "genres": " , "}
        )
        self.assertEqual(len(response.context["albums"]), 3)

    def test_sort_by_name(self):
        response = self.client.get(reverse("music:home"), {"sort": "name"})
        self.assertEqual(
            [a.name for a in response.context["albums"]],
            ["Kid A", "Revolver", "Rust Never Sleeps"],
        )

    def test_sort_by_year(self):
        response = self.client.get(reverse("music:home"), {"sort": "year"})
        self.assertEqual(
            [a.year_released for a in response.context["albums"]], [1966, 1979, 2000]
        )

    def test_sort_by_list_appearances(self):
        response = self.client.get(
            reverse("music:home"), {"sort": "lists", "dir": "desc"}
        )
        self.assertEqual([a.name for a in response.context["albums"]][0], "Revolver")

    def test_sort_by_list_appearances_ascending_puts_the_unlisted_first(self):
        response = self.client.get(reverse("music:home"), {"sort": "lists"})
        self.assertEqual([a.name for a in response.context["albums"]][0], "Kid A")

    def test_descending_year_keeps_the_rank_tiebreak_ascending(self):
        tie = models.Album.objects.create(
            name="Also 2000", rank=10, artist_credit="Someone", year_released=2000
        )
        response = self.client.get(
            reverse("music:home"), {"sort": "year", "dir": "desc"}
        )
        names = [a.name for a in response.context["albums"]]
        # Both 2000 albums come first, and within them the better rank leads.
        self.assertEqual(names[:2], ["Kid A", tie.name])

    def test_descending_direction_reverses_a_string_sort(self):
        response = self.client.get(
            reverse("music:home"), {"sort": "year", "dir": "desc"}
        )
        self.assertEqual(
            [a.year_released for a in response.context["albums"]], [2000, 1979, 1966]
        )

    def test_descending_direction_reverses_an_expression_sort(self):
        response = self.client.get(
            reverse("music:home"), {"sort": "name", "dir": "desc"}
        )
        self.assertEqual(
            [a.name for a in response.context["albums"]],
            ["Rust Never Sleeps", "Revolver", "Kid A"],
        )

    def test_ascending_direction_is_the_default(self):
        response = self.client.get(reverse("music:home"), {"sort": "year"})
        self.assertEqual(
            [a.year_released for a in response.context["albums"]], [1966, 1979, 2000]
        )

    def test_an_unknown_sort_falls_back_to_rank(self):
        response = self.client.get(reverse("music:home"), {"sort": "bogus"})
        self.assertEqual([a.rank for a in response.context["albums"]], [1, 2, 3])

    def test_context_carries_counts_and_bounds(self):
        response = self.client.get(reverse("music:home"))
        context = response.context
        self.assertEqual(context["album_count"], 3)
        self.assertEqual(context["list_count"], 3)
        self.assertEqual(context["publication_count"], 1)
        self.assertEqual(context["min_year"], 1966)
        self.assertEqual(context["max_year"], 2000)
        self.assertEqual(context["total_count"], 3)
        self.assertEqual(context["loaded_count"], 3)
        self.assertEqual(context["remaining_count"], 0)
        self.assertFalse(context["has_more"])
        self.assertIsNone(context["next_page"])

    def test_context_echoes_the_filter_state(self):
        response = self.client.get(
            reverse("music:home"),
            {"q": "kid", "start": "1990", "end": "2010", "sort": "name", "dir": "desc"},
        )
        context = response.context
        self.assertEqual(context["current_q"], "kid")
        self.assertEqual(context["current_start"], "1990")
        self.assertEqual(context["current_end"], "2010")
        self.assertEqual(context["current_sort"], "name")
        self.assertEqual(context["current_dir"], "desc")
        self.assertTrue(context["is_filtered"])
        self.assertEqual(context["show_rank"], "filtered")

    def test_show_rank_is_alltime_when_unfiltered(self):
        response = self.client.get(reverse("music:home"))
        self.assertFalse(response.context["is_filtered"])
        self.assertEqual(response.context["show_rank"], "alltime")

    def test_query_string_drops_page_and_append(self):
        response = self.client.get(
            reverse("music:home"), {"q": "kid", "page": "1", "append": "true"}
        )
        self.assertEqual(response.context["query_string"], "q=kid")

    def test_highlight_is_parsed_as_an_integer(self):
        response = self.client.get(
            reverse("music:home"), {"highlight": str(self.revolver.id)}
        )
        self.assertEqual(response.context["highlight"], self.revolver.id)

    def test_pagination_reports_more_pages(self):
        for index in range(120):
            models.Album.objects.create(name=f"Filler {index}", rank=100 + index)
        response = self.client.get(reverse("music:home"))
        self.assertTrue(response.context["has_more"])
        self.assertEqual(response.context["next_page"], 2)
        self.assertEqual(response.context["loaded_count"], 100)
        self.assertEqual(response.context["remaining_count"], 23)

    def test_an_out_of_range_page_serves_the_last_page(self):
        response = self.client.get(reverse("music:home"), {"page": "99"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["albums"]), 3)

    def test_htmx_request_targeting_the_results_container(self):
        response = self.client.get(
            reverse("music:home"),
            HTTP_HX_REQUEST="true",
            HTTP_HX_TARGET="album-results-container",
        )
        self.assertTemplateUsed(response, "music/includes/_album_list_results.html")
        self.assertTemplateNotUsed(response, "base.html")

    def test_htmx_request_without_a_target_serves_the_content_partial(self):
        response = self.client.get(reverse("music:home"), HTTP_HX_REQUEST="true")
        self.assertTemplateUsed(response, "music/includes/_album_list_content.html")

    def test_xhr_header_is_treated_as_htmx(self):
        response = self.client.get(
            reverse("music:home"), HTTP_X_REQUESTED_WITH="XMLHttpRequest"
        )
        self.assertTemplateUsed(response, "music/includes/_album_list_content.html")

    def test_partial_query_param_is_treated_as_htmx(self):
        response = self.client.get(reverse("music:home"), {"partial": "true"})
        self.assertTemplateUsed(response, "music/includes/_album_list_content.html")

    def test_append_request_serves_the_append_partial(self):
        response = self.client.get(reverse("music:home"), {"append": "true"})
        self.assertTemplateUsed(response, "music/includes/_album_list_append.html")

    def test_full_page_request_uses_the_base_template(self):
        response = self.client.get(reverse("music:home"))
        self.assertTemplateUsed(response, "music/home.html")
        self.assertTemplateUsed(response, "base.html")

    def test_empty_result_set_renders_the_empty_state(self):
        response = self.client.get(reverse("music:home"), {"q": "nothingmatches"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["albums"]), 0)
        self.assertContains(response, "Nothing here")


class FilterTitleTests(TestCase):
    """The heading describes the filter state, in the site's own wording."""

    def test_unfiltered(self):
        self.assertEqual(_filter_title({}), "Most Acclaimed Albums")

    def test_a_search_query_wins_over_a_year_range(self):
        title = _filter_title({"q": "kid a", "start": "1990", "end": "1999"})
        self.assertEqual(title, "Albums matching \u201ckid a\u201d")

    def test_a_single_year(self):
        self.assertEqual(
            _filter_title({"start": "1966", "end": "1966"}),
            "Most Acclaimed Albums of 1966",
        )

    def test_a_full_decade_reads_as_a_decade(self):
        self.assertEqual(
            _filter_title({"start": "1970", "end": "1979"}),
            "Most Acclaimed Albums of the 1970s",
        )

    def test_an_arbitrary_range_reads_as_a_range(self):
        self.assertEqual(
            _filter_title({"start": "1965", "end": "1972"}),
            "Most Acclaimed Albums, 1965\u20131972",
        )

    def test_a_range_starting_on_a_zero_but_not_a_decade(self):
        self.assertEqual(
            _filter_title({"start": "1970", "end": "1985"}),
            "Most Acclaimed Albums, 1970\u20131985",
        )

    def test_only_a_start_year(self):
        self.assertEqual(
            _filter_title({"start": "1990"}), "Most Acclaimed Albums from 1990"
        )

    def test_only_an_end_year(self):
        self.assertEqual(
            _filter_title({"end": "1990"}), "Most Acclaimed Albums up to 1990"
        )

    def test_the_title_avoids_best_and_top_phrasing(self):
        # Matches the wording rule the games ranking pages follow.
        for params in [
            {},
            {"start": "1970", "end": "1979"},
            {"start": "1966", "end": "1966"},
        ]:
            with self.subTest(params=params):
                title = _filter_title(params).lower()
                self.assertNotIn("best", title)
                self.assertNotIn("top ", title)


class DecadeOptionsTests(MusicDataMixin, TestCase):
    def test_counts_albums_per_decade(self):
        options = _decade_options(1960, 2000, None, None)
        by_label = {entry["label"]: entry["count"] for entry in options}
        self.assertEqual(by_label["1960s"], 1)
        self.assertEqual(by_label["1970s"], 1)
        self.assertEqual(by_label["2000s"], 1)

    def test_marks_the_selected_decade(self):
        options = _decade_options(1960, 2000, "1970", "1979")
        selected = [e["label"] for e in options if e["selected"]]
        self.assertEqual(selected, ["1970s"])

    def test_nothing_is_selected_for_a_partial_range(self):
        options = _decade_options(1960, 2000, "1970", "1975")
        self.assertEqual([e["label"] for e in options if e["selected"]], [])

    def test_albums_without_a_year_are_excluded(self):
        models.Album.objects.create(name="Undated", rank=99)
        options = _decade_options(1960, 2000, None, None)
        self.assertEqual(sum(e["count"] for e in options), 3)

    def test_the_sidebar_renders_the_decade_chips(self):
        response = self.client.get(reverse("music:home"))
        self.assertContains(response, "1960s")
        self.assertContains(response, 'name="decade"')


class AlbumDetailViewTests(MusicDataMixin, TestCase):
    def test_renders_the_album(self):
        response = self.client.get(self.revolver.get_absolute_url())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["album"], self.revolver)
        self.assertContains(response, "Revolver")

    def test_anonymous_gets_404(self):
        self.client.logout()
        self.assertEqual(
            self.client.get(self.revolver.get_absolute_url()).status_code, 404
        )

    def test_unknown_slug_is_404(self):
        self.assertEqual(self.client.get("/music/no-such-album/").status_code, 404)

    def test_list_appearances_are_grouped_by_type(self):
        response = self.client.get(self.revolver.get_absolute_url())
        grouped = response.context["grouped_lists"]
        self.assertEqual([label for label, _ in grouped], ["All time", "Decade"])
        self.assertEqual(response.context["list_appearance_count"], 2)

    def test_the_grouped_lists_actually_render(self):
        # Books groups by a label map that never matches the stored codes, so
        # its equivalent block renders empty. This must not.
        response = self.client.get(self.revolver.get_absolute_url())
        self.assertContains(response, "Source Lists")
        self.assertContains(response, "All time")
        self.assertContains(response, "The Greatest Albums of All Time")

    def test_total_album_count_is_in_context(self):
        response = self.client.get(self.revolver.get_absolute_url())
        self.assertEqual(response.context["total_album_count"], 3)

    def test_related_albums_exclude_the_album_itself(self):
        other = models.Album.objects.create(
            name="Abbey Road", rank=4, artist_credit="The Beatles"
        )
        other.artists.set([self.beatles])
        response = self.client.get(self.revolver.get_absolute_url())
        self.assertEqual(list(response.context["related_albums"]), [other])

    def test_no_related_albums_key_without_artists(self):
        response = self.client.get(self.kid_a.get_absolute_url())
        self.assertIsNone(response.context.get("related_albums"))

    def test_an_album_with_no_list_appearances_renders(self):
        response = self.client.get(self.kid_a.get_absolute_url())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["grouped_lists"], [])

    def test_cover_placeholder_shows_when_there_is_no_cover_art(self):
        response = self.client.get(self.revolver.get_absolute_url())
        self.assertContains(response, "No cover art yet")

    def test_cover_image_renders_when_present(self):
        self.revolver.cover_image_url = "https://example.com/revolver.jpg"
        self.revolver.save()
        response = self.client.get(self.revolver.get_absolute_url())
        self.assertContains(response, "https://example.com/revolver.jpg")


class GroupListAppearancesTests(MusicDataMixin, TestCase):
    def test_groups_follow_the_shared_importance_order(self):
        memberships = list(
            models.AlbumListMembership.objects.select_related("list__publisher")
        )
        grouped = group_list_appearances(memberships)
        self.assertEqual(
            [label for label, _ in grouped],
            ["All time", "Decade", "Miscellaneous"],
        )

    def test_entries_carry_the_fields_the_template_reads(self):
        membership = models.AlbumListMembership.objects.select_related(
            "list__publisher"
        ).get(list=self.all_time)
        grouped = group_list_appearances([membership])
        entry = grouped[0][1][0]
        self.assertEqual(entry["name"], "The Greatest Albums of All Time")
        self.assertEqual(entry["publication"], "Pitchfork")
        self.assertEqual(entry["type"], core_constants.LIST_ALLTIME)
        self.assertEqual(entry["type_name"], "All time")
        self.assertEqual(entry["year"], 2020)
        self.assertEqual(entry["rank"], 1)

    def test_a_list_without_a_publisher_yields_an_empty_publication(self):
        orphan_list = models.MusicList.objects.create(
            name="Unattributed", year=2001, order=9
        )
        membership = models.AlbumListMembership.objects.create(
            list=orphan_list, album=self.kid_a, rank=1
        )
        grouped = group_list_appearances([membership])
        self.assertEqual(grouped[0][1][0]["publication"], "")

    def test_no_memberships_yields_no_groups(self):
        self.assertEqual(group_list_appearances([]), [])


class ArtistListViewTests(MusicDataMixin, TestCase):
    def test_lists_only_artists_with_albums(self):
        models.Artist.objects.create(name="No Albums", slug="no-albums")
        response = self.client.get(reverse("music:artist-list"))
        names = [a.name for a in response.context["artists"]]
        self.assertNotIn("No Albums", names)
        self.assertIn("The Beatles", names)

    def test_anonymous_gets_404(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse("music:artist-list")).status_code, 404)

    def test_search_filters_by_name(self):
        response = self.client.get(reverse("music:artist-list"), {"q": "beatles"})
        self.assertEqual([a.name for a in response.context["artists"]], ["The Beatles"])

    def test_default_sort_is_album_count_descending(self):
        for index in range(3):
            album = models.Album.objects.create(
                name=f"Beatles {index}", rank=50 + index, artist_credit="The Beatles"
            )
            album.artists.set([self.beatles])
        response = self.client.get(reverse("music:artist-list"))
        self.assertEqual(response.context["artists"][0].name, "The Beatles")

    def test_sort_by_name(self):
        response = self.client.get(
            reverse("music:artist-list"), {"sort": "name", "dir": "asc"}
        )
        self.assertEqual(
            [a.name for a in response.context["artists"]],
            ["Crazy Horse", "Neil Young", "The Beatles"],
        )

    def test_album_count_sort_keeps_the_name_tiebreak_ascending(self):
        # Two acts with one album each must come back A-Z, even though the
        # primary sort is descending.
        response = self.client.get(reverse("music:artist-list"))
        names = [a.name for a in response.context["artists"]]
        self.assertEqual(names, sorted(names, key=str.lower))

    def test_context_carries_the_filter_state_and_counts(self):
        response = self.client.get(reverse("music:artist-list"), {"q": "neil"})
        self.assertEqual(response.context["current_q"], "neil")
        self.assertEqual(response.context["current_sort"], "albums")
        self.assertEqual(response.context["current_dir"], "desc")
        self.assertEqual(response.context["total_count"], 1)
        self.assertEqual(response.context["loaded_count"], 1)
        self.assertFalse(response.context["has_more"])

    def test_htmx_request_serves_the_results_partial(self):
        response = self.client.get(reverse("music:artist-list"), HTTP_HX_REQUEST="true")
        self.assertTemplateUsed(
            response, "music/artists/includes/_artist_list_results.html"
        )

    def test_append_request_serves_the_append_partial(self):
        response = self.client.get(reverse("music:artist-list"), {"append": "true"})
        self.assertTemplateUsed(
            response, "music/artists/includes/_artist_list_append.html"
        )

    def test_pagination_reports_more_pages(self):
        for index in range(120):
            artist = models.Artist.objects.create(
                name=f"Act {index:03d}", slug=f"act-{index:03d}"
            )
            album = models.Album.objects.create(name=f"LP {index}", rank=200 + index)
            album.artists.set([artist])
        response = self.client.get(reverse("music:artist-list"))
        self.assertTrue(response.context["has_more"])
        self.assertEqual(response.context["next_page"], 2)

    def test_an_empty_search_renders_the_empty_state(self):
        response = self.client.get(reverse("music:artist-list"), {"q": "zzzznope"})
        self.assertEqual(response.context["total_count"], 0)
        self.assertEqual(response.context["loaded_count"], 0)
        self.assertContains(response, "No artists found")


class ArtistDetailViewTests(MusicDataMixin, TestCase):
    def test_renders_the_artist_and_their_albums(self):
        response = self.client.get(self.beatles.get_absolute_url())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["artist"], self.beatles)
        self.assertEqual(response.context["albums_count"], 1)
        self.assertEqual(response.context["best_album"], self.revolver)
        self.assertContains(response, "Revolver")

    def test_anonymous_gets_404(self):
        self.client.logout()
        self.assertEqual(
            self.client.get(self.beatles.get_absolute_url()).status_code, 404
        )

    def test_unknown_slug_is_404(self):
        self.assertEqual(self.client.get("/music/artists/nobody/").status_code, 404)

    def test_an_artist_with_no_albums_renders_the_empty_state(self):
        artist = models.Artist.objects.create(name="Silent", slug="silent")
        response = self.client.get(artist.get_absolute_url())
        self.assertEqual(response.context["albums_count"], 0)
        self.assertIsNone(response.context["best_album"])
        self.assertContains(response, "No ranked albums")

    def test_subsidiary_acts_are_listed(self):
        response = self.client.get(self.young.get_absolute_url())
        self.assertContains(response, "Crazy Horse")
        self.assertContains(response, "Related acts")

    def test_external_links_render_when_ids_are_set(self):
        self.beatles.wikidata_id = "Q1299"
        self.beatles.musicbrainz_id = "b10bbbfc-cf9e-42e0-be17-e2c3e1d2600d"
        self.beatles.save()
        response = self.client.get(self.beatles.get_absolute_url())
        self.assertContains(response, "wikidata.org/wiki/Q1299")
        self.assertContains(response, "musicbrainz.org/artist/")


class AlbumSearchViewTests(MusicDataMixin, TestCase):
    def test_returns_matching_albums(self):
        response = self.client.get(reverse("music:search"), {"q": "revolver"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Revolver")

    def test_matches_on_the_artist_credit(self):
        response = self.client.get(reverse("music:search"), {"q": "radiohead"})
        self.assertContains(response, "Kid A")

    def test_no_query_returns_nothing(self):
        response = self.client.get(reverse("music:search"))
        self.assertEqual(len(response.context["albums"]), 0)
        self.assertContains(response, "No albums found")

    def test_anonymous_gets_404(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse("music:search")).status_code, 404)


class MusicListListViewTests(MusicDataMixin, TestCase):
    def test_lists_every_source_in_order(self):
        response = self.client.get(reverse("music:list-list"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [source.order for source in response.context["music_lists"]], [1, 2, 3]
        )

    def test_anonymous_gets_404(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse("music:list-list")).status_code, 404)

    def test_album_count_is_annotated(self):
        response = self.client.get(reverse("music:list-list"))
        counts = {s.name: s.album_count for s in response.context["music_lists"]}
        self.assertEqual(counts["The Greatest Albums of All Time"], 1)

    def test_search_matches_the_list_name(self):
        response = self.client.get(reverse("music:list-list"), {"q": "1960s"})
        self.assertEqual(len(response.context["music_lists"]), 1)

    def test_search_matches_the_publication_name(self):
        response = self.client.get(reverse("music:list-list"), {"q": "pitchfork"})
        self.assertEqual(len(response.context["music_lists"]), 3)

    def test_type_filter(self):
        response = self.client.get(
            reverse("music:list-list"), {"type": core_constants.LIST_DECADE}
        )
        self.assertEqual(
            [s.name for s in response.context["music_lists"]],
            ["The Best Albums of the 1960s"],
        )

    def test_an_unknown_type_filter_is_ignored(self):
        response = self.client.get(reverse("music:list-list"), {"type": "Z"})
        self.assertEqual(len(response.context["music_lists"]), 3)

    def test_sort_by_year(self):
        response = self.client.get(reverse("music:list-list"), {"sort": "year"})
        self.assertEqual(
            [s.year for s in response.context["music_lists"]], [2020, 2017, 2010]
        )

    def test_sort_by_album_count(self):
        response = self.client.get(reverse("music:list-list"), {"sort": "albums"})
        self.assertEqual(response.context["music_lists"][0].album_count, 1)

    def test_sort_by_publication(self):
        response = self.client.get(reverse("music:list-list"), {"sort": "publication"})
        self.assertEqual(
            [s.year for s in response.context["music_lists"]], [2020, 2017, 2010]
        )

    def test_context_carries_the_type_summary(self):
        response = self.client.get(reverse("music:list-list"))
        summary = {
            entry["code"]: entry["count"] for entry in response.context["list_types"]
        }
        self.assertEqual(summary[core_constants.LIST_ALLTIME], 1)
        self.assertEqual(summary[core_constants.LIST_DECADE], 1)
        self.assertEqual(summary[core_constants.LIST_MISC], 1)
        self.assertEqual(summary[core_constants.LIST_EOY], 0)
        self.assertEqual(response.context["total_count"], 3)
        self.assertEqual(response.context["current_sort"], "order")

    def test_htmx_request_serves_the_results_partial(self):
        response = self.client.get(reverse("music:list-list"), HTTP_HX_REQUEST="true")
        self.assertTemplateUsed(
            response, "music/lists/includes/_list_list_results.html"
        )

    def test_an_empty_result_set_renders_the_empty_state(self):
        response = self.client.get(reverse("music:list-list"), {"q": "zzzznope"})
        self.assertEqual(len(response.context["music_lists"]), 0)
        self.assertContains(response, "No lists found")

    def test_a_list_without_a_publisher_renders(self):
        models.MusicList.objects.create(name="Unattributed", year=2001, order=9)
        response = self.client.get(reverse("music:list-list"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["music_lists"]), 4)


class AlbumCoverViewTests(StaffUserTestMixin, TestCase):
    """Serving our own stored copy of a cover.

    The remote Cover Art Archive URL redirects to archive.org, which 500s
    intermittently, so a page of a hundred covers shows several broken images
    on every load. These are served from here instead.
    """

    def setUp(self):
        super().setUp()
        self.cover = models.AlbumCover.objects.create(
            release_mbid="f04cce33-b9a0-4bed-af11-f84d649652b2",
            image_id="25254108559",
            size=250,
            data=b"\xff\xd8binary",
            content_type="image/jpeg",
            byte_size=8,
        )
        self.url = reverse(
            "music:cover",
            kwargs={
                "release_mbid": self.cover.release_mbid,
                "image_id": self.cover.image_id,
                "size": 250,
            },
        )

    def test_the_bytes_are_served_with_their_content_type(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/jpeg")
        self.assertEqual(response.content, b"\xff\xd8binary")
        # Computed from the bytes actually served, not the stored count.
        self.assertEqual(response["Content-Length"], "8")

    def test_the_response_is_cached_immutably(self):
        """The URL carries identifiers that never change for an image."""
        response = self.client.get(self.url)
        self.assertIn("immutable", response["Cache-Control"])
        self.assertIn("max-age=31536000", response["Cache-Control"])

    def test_an_unknown_cover_is_404(self):
        url = reverse(
            "music:cover",
            kwargs={"release_mbid": "nope", "image_id": "nope", "size": 250},
        )
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_the_wrong_size_is_404(self):
        url = reverse(
            "music:cover",
            kwargs={
                "release_mbid": self.cover.release_mbid,
                "image_id": self.cover.image_id,
                "size": 1200,
            },
        )
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_anonymous_gets_404(self):
        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_a_non_staff_user_gets_404(self):
        User.objects.create_user(username="plaincover", password="plainpass")
        self.client.login(username="plaincover", password="plainpass")
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_the_cover_route_is_not_read_as_an_album_slug(self):
        """It sits above the catch-all <slug:slug>/ pattern."""
        models.Album.objects.create(name="Cover", slug="cover", rank=1)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)


class GenreGroupingTests(TestCase):
    """The genre filter presents a two-level taxonomy, so it uses optgroups."""

    def test_children_are_grouped_under_their_root(self):
        rock = {
            "id": 1,
            "name": "Rock",
            "level": 0,
            "parent_id": None,
            "albums_count": 10,
        }
        punk = {
            "id": 2,
            "name": "Punk",
            "level": 0,
            "parent_id": None,
            "albums_count": 4,
        }
        post_punk = {
            "id": 3,
            "name": "Post-Punk",
            "level": 1,
            "parent_id": 2,
            "albums_count": 3,
        }
        groups = views.group_genre_options([rock, punk, post_punk])
        self.assertEqual([g["root"]["name"] for g in groups], ["Rock", "Punk"])
        self.assertEqual(
            [o["name"] for o in groups[1]["options"]], ["Punk", "Post-Punk"]
        )

    def test_a_root_is_selectable_as_well_as_a_label(self):
        rock = {
            "id": 1,
            "name": "Rock",
            "level": 0,
            "parent_id": None,
            "albums_count": 10,
        }
        groups = views.group_genre_options([rock])
        self.assertEqual(groups[0]["options"], [rock])

    def test_an_orphaned_child_becomes_its_own_group(self):
        """A parent filtered out for having no albums must not lose its child."""
        child = {
            "id": 3,
            "name": "Post-Punk",
            "level": 1,
            "parent_id": 99,
            "albums_count": 3,
        }
        groups = views.group_genre_options([child])
        self.assertEqual(groups[0]["root"]["name"], "Post-Punk")

    def test_children_sort_after_their_root_then_by_name(self):
        rock = {
            "id": 1,
            "name": "Rock",
            "level": 0,
            "parent_id": None,
            "albums_count": 10,
        }
        b = {"id": 2, "name": "B Rock", "level": 1, "parent_id": 1, "albums_count": 1}
        a = {"id": 3, "name": "A Rock", "level": 1, "parent_id": 1, "albums_count": 1}
        groups = views.group_genre_options([rock, b, a])
        self.assertEqual(
            [o["name"] for o in groups[0]["options"]], ["Rock", "A Rock", "B Rock"]
        )

    def test_no_options_means_no_groups(self):
        self.assertEqual(views.group_genre_options([]), [])

    def test_the_album_count_is_selected_for_display(self):
        """Annotating without selecting left the template rendering a blank."""
        genre = models.MusicGenre.objects.create(name="Rock")
        album = models.Album.objects.create(name="A", rank=1)
        album.genres.set([genre])
        options = views._cached_genre_options()
        self.assertEqual(options[0]["albums_count"], 1)


class ClientSideFilteringContextTests(MusicDataMixin, TestCase):
    """What the rankings page hands the client-side filtering bundle."""

    def test_client_side_filtering_is_enabled(self):
        # The bundle's <script> and the <template> elements it clones are
        # both gated on this flag.
        response = self.client.get(reverse("music:home"))
        self.assertTrue(response.context["enable_client_filtering"])

    def test_the_album_data_version_is_rendered_into_the_page(self):
        # This is what lets the client tell a stale copy of the bulk payload
        # from a current one, which is why there is no version/ endpoint.
        response = self.client.get(reverse("music:home"))
        version = response.context["album_data_version"]
        self.assertEqual(len(version), 12)
        self.assertContains(response, f'window.albumDataVersion = "{version}"')

    def test_the_row_templates_are_declared_for_cloning(self):
        response = self.client.get(reverse("music:home"))
        self.assertContains(response, 'id="desktop-row-template"')
        self.assertContains(response, 'id="mobile-row-template"')


class MusicCacheInvalidationTests(MusicDataMixin, TestCase):
    """Every cached key has to be reachable from one invalidation call."""

    def test_the_decade_counts_are_cached(self):
        views._cached_decade_counts()
        self.assertIsNotNone(cache.get(config.CACHE_KEY_DECADE_COUNTS))

    def test_a_second_call_does_not_re_run_the_aggregate(self):
        views._cached_decade_counts()
        with self.assertNumQueries(0):
            views._cached_decade_counts()

    def test_decade_options_still_mark_the_selected_chip(self):
        # Only the counts are cached; which chip is selected is per request.
        first = _decade_options(1960, 1979, "1960", "1969")
        second = _decade_options(1960, 1979, None, None)
        self.assertTrue(first[0]["selected"])
        self.assertFalse(second[0]["selected"])

    def test_invalidation_clears_every_declared_key(self):
        for key in config.CACHE_KEYS:
            cache.set(key, "stale", 60)
        views._invalidate_music_caches()
        for key in config.CACHE_KEYS:
            with self.subTest(key=key):
                self.assertIsNone(cache.get(key))

    def test_every_cached_key_is_declared_for_invalidation(self):
        # Renders the page and the detail page, so each helper populates its
        # key, then checks nothing was cached under a key the invalidation
        # list does not know about.
        self.client.get(reverse("music:home"))
        self.client.get(
            reverse("music:album-detail", kwargs={"slug": self.revolver.slug})
        )
        populated = [key for key in config.CACHE_KEYS if cache.get(key) is not None]
        self.assertEqual(sorted(populated), sorted(config.CACHE_KEYS))

    def test_every_key_carries_the_cache_version(self):
        # One of them did not, so bumping CACHE_VERSION would have left the
        # year bounds stale while invalidating everything else.
        for key in config.CACHE_KEYS:
            with self.subTest(key=key):
                self.assertTrue(key.startswith(f"{config.CACHE_VERSION}:"))
