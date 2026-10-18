"""Tests for the Discogs style -> MusicGenre normalizer.

The rule that matters most here is that a style's root is global. It was once
taken from the album's own Discogs genre list, which made 'Alternative Rock'
a child of Electronic because OK Computer is tagged "Electronic, Rock" - and
that one row then represented every alternative rock album on the site.
"""

from django.test import SimpleTestCase, TestCase

from music.models import MusicGenre
from music.services import genre_normalizer as gn
from music.templatetags.music_filters import MUSIC_GENRE_CATEGORY_ICONS


class RootSetTests(SimpleTestCase):
    def test_every_root_has_an_icon(self):
        """A root missing from the icon map renders a generic note instead."""
        missing = [
            root for root in gn.ROOT_GENRES if root not in MUSIC_GENRE_CATEGORY_ICONS
        ]
        self.assertEqual(missing, [])

    def test_every_icon_entry_is_a_real_root(self):
        extra = [
            name for name in MUSIC_GENRE_CATEGORY_ICONS if name not in gn.ROOT_GENRES
        ]
        self.assertEqual(extra, [])

    def test_every_mapped_root_is_in_the_hierarchy(self):
        for style, root in gn.STYLE_TO_ROOT.items():
            with self.subTest(style=style):
                self.assertTrue(root is None or root in gn.ROOT_GENRES)

    def test_every_discogs_default_is_in_the_hierarchy(self):
        for name, root in gn.DISCOGS_GENRE_TO_ROOT.items():
            with self.subTest(discogs_genre=name):
                self.assertTrue(root is None or root in gn.ROOT_GENRES)

    def test_every_keyword_target_is_in_the_hierarchy(self):
        for keyword, root in gn.ROOT_KEYWORDS.items():
            with self.subTest(keyword=keyword):
                self.assertIn(root, gn.ROOT_GENRES)


class NameInferenceTests(SimpleTestCase):
    def test_the_rightmost_root_word_wins(self):
        self.assertEqual(gn.root_from_style_name("Pop Rock"), "Rock")
        self.assertEqual(gn.root_from_style_name("Indie Pop"), "Pop")
        self.assertEqual(gn.root_from_style_name("Alternative Rock"), "Rock")

    def test_a_two_word_root_is_matched_before_a_single_word(self):
        """'Hardcore Hip Hop' is hip hop, not hardcore punk."""
        self.assertEqual(gn.root_from_style_name("Hardcore Hip-Hop"), "Hip Hop")

    def test_hyphens_are_treated_as_spaces(self):
        self.assertEqual(gn.root_from_style_name("Jazz-Rock"), "Rock")

    def test_an_unknown_name_yields_nothing(self):
        self.assertIsNone(gn.root_from_style_name("Conscious"))
        self.assertIsNone(gn.root_from_style_name(""))

    def test_case_does_not_matter(self):
        self.assertEqual(gn.root_from_style_name("pop ROCK"), "Rock")


class ResolveStyleTests(SimpleTestCase):
    def test_an_explicit_mapping_wins_over_the_name(self):
        """Synth-pop is electronic music despite its name."""
        self.assertEqual(gn.resolve_style("Synth-pop"), "Electronic")

    def test_an_explicit_none_drops_a_descriptor(self):
        self.assertIsNone(gn.resolve_style("Vocal", ["Rock"]))
        self.assertIsNone(gn.resolve_style("Experimental", ["Rock"]))

    def test_a_style_that_is_itself_a_root_resolves_to_itself(self):
        self.assertEqual(gn.resolve_style("Funk"), "Funk")
        self.assertEqual(gn.resolve_style("Jazz"), "Jazz")

    def test_the_name_is_used_before_the_albums_genres(self):
        """This is the fix for Alternative Rock landing under Electronic."""
        self.assertEqual(
            gn.resolve_style("Alternative Rock", ["Electronic", "Rock"]), "Rock"
        )

    def test_the_same_style_resolves_the_same_way_whatever_the_album(self):
        first = gn.resolve_style("Alternative Rock", ["Electronic", "Rock"])
        second = gn.resolve_style("Alternative Rock", ["Rock"])
        self.assertEqual(first, second)

    def test_the_albums_genres_are_the_last_resort(self):
        """A style nobody has mapped yet still lands somewhere sensible."""
        self.assertEqual(gn.resolve_style("Brand New Substyle", ["Hip Hop"]), "Hip Hop")
        self.assertEqual(gn.resolve_style("Another Unknown", ["Funk / Soul"]), "Soul")

    def test_an_unmappable_style_returns_none(self):
        self.assertIsNone(gn.resolve_style("Totally Unknown Thing", []))

    def test_an_unknown_discogs_genre_does_not_resolve(self):
        self.assertIsNone(gn.resolve_style("Mystery", ["Nonexistent Genre"]))

    def test_case_insensitive_matching(self):
        self.assertEqual(gn.resolve_style("synth-POP"), "Electronic")

    def test_discogs_coarse_roots_split_the_way_we_want(self):
        self.assertEqual(gn.resolve_style("Punk", ["Rock"]), "Punk")
        self.assertEqual(gn.resolve_style("Heavy Metal", ["Rock"]), "Metal")
        self.assertEqual(gn.resolve_style("Soul", ["Funk / Soul"]), "Soul")
        self.assertEqual(gn.resolve_style("Contemporary R&B", ["Funk / Soul"]), "R&B")
        self.assertEqual(gn.resolve_style("Funk", ["Funk / Soul"]), "Funk")
        self.assertEqual(
            gn.resolve_style("Country", ["Folk, World, & Country"]), "Country"
        )
        self.assertEqual(gn.resolve_style("Folk", ["Folk, World, & Country"]), "Folk")

    def test_root_for_discogs_genre(self):
        self.assertEqual(gn.root_for_discogs_genre("Funk / Soul"), "Soul")
        self.assertEqual(gn.root_for_discogs_genre("funk / soul"), "Soul")
        self.assertIsNone(gn.root_for_discogs_genre("Non-Music"))
        self.assertIsNone(gn.root_for_discogs_genre("Unheard Of"))


class ResolveStylesTests(SimpleTestCase):
    def test_order_is_preserved_and_duplicates_dropped(self):
        resolved = gn.resolve_styles(["Punk", "New Wave", "Punk"], ["Rock"])
        self.assertEqual(resolved, [("Punk", "Punk"), ("New Wave", "Rock")])

    def test_dropped_styles_do_not_appear(self):
        resolved = gn.resolve_styles(["Vocal", "Pop Rock"], ["Rock"])
        self.assertEqual(resolved, [("Pop Rock", "Rock")])

    def test_blank_styles_are_ignored(self):
        self.assertEqual(gn.resolve_styles(["", "Funk"], []), [("Funk", "Funk")])

    def test_case_variants_are_treated_as_one(self):
        resolved = gn.resolve_styles(["Funk", "funk"], [])
        self.assertEqual(len(resolved), 1)

    def test_no_styles_yields_nothing(self):
        self.assertEqual(gn.resolve_styles([], ["Rock"]), [])


class GetOrCreateGenreTests(TestCase):
    def test_a_root_is_created_at_level_zero(self):
        genre = gn.get_or_create_genre("Rock")
        self.assertIsNone(genre.parent)
        self.assertEqual(genre.level, 0)
        self.assertEqual(genre.path, "Rock")
        self.assertEqual(genre.slug, "rock")

    def test_a_child_creates_its_parent_first(self):
        child = gn.get_or_create_genre("Post-Punk", parent_name="Punk")
        self.assertEqual(child.parent.name, "Punk")
        self.assertEqual(child.level, 1)
        self.assertEqual(child.path, "Punk > Post-Punk")

    def test_an_existing_genre_is_reused(self):
        first = gn.get_or_create_genre("Rock")
        second = gn.get_or_create_genre("Rock")
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(MusicGenre.objects.count(), 1)

    def test_a_parent_equal_to_the_name_is_ignored(self):
        genre = gn.get_or_create_genre("Rock", parent_name="Rock")
        self.assertIsNone(genre.parent)

    def test_roots_carry_the_hierarchy_order(self):
        rock = gn.get_or_create_genre("Rock")
        world = gn.get_or_create_genre("World")
        self.assertLess(rock.display_order, world.display_order)

    def test_a_leaf_has_no_display_order_of_its_own(self):
        leaf = gn.get_or_create_genre("Post-Punk", parent_name="Punk")
        self.assertEqual(leaf.display_order, 0)


class GenresForAlbumTests(TestCase):
    def test_both_the_root_and_the_leaf_are_returned(self):
        genres = gn.genres_for_album(["Post-Punk"], ["Rock"])
        self.assertEqual([g.name for g in genres], ["Punk", "Post-Punk"])

    def test_a_style_that_is_a_root_yields_only_the_root(self):
        genres = gn.genres_for_album(["Soul"], ["Funk / Soul"])
        self.assertEqual([g.name for g in genres], ["Soul"])

    def test_several_styles_under_one_root_share_it(self):
        genres = gn.genres_for_album(["Pop Rock", "Art Rock"], ["Rock"])
        self.assertEqual([g.name for g in genres], ["Rock", "Pop Rock", "Art Rock"])
        self.assertEqual(MusicGenre.objects.filter(name="Rock").count(), 1)

    def test_styles_under_different_roots_bring_both_roots(self):
        genres = gn.genres_for_album(["Punk", "Synth-pop"], ["Rock"])
        self.assertEqual([g.name for g in genres], ["Punk", "Electronic", "Synth-pop"])

    def test_dropped_styles_contribute_nothing(self):
        self.assertEqual(gn.genres_for_album(["Vocal"], []), [])

    def test_no_styles_yields_nothing(self):
        self.assertEqual(gn.genres_for_album([], []), [])


class RealVocabularyTests(SimpleTestCase):
    """Every style the real 500-album release actually uses must resolve.

    An unmapped style is a silent gap: the album simply loses that genre. The
    games app has needed four migrations to clean up strays that reached
    production the same way, so this is pinned rather than trusted.
    """

    # Styles observed across all 498 Discogs masters in the checked-in
    # release, as of 2026-10-17.
    OBSERVED = [
        "Indie Rock",
        "Alternative Rock",
        "Pop Rock",
        "Art Rock",
        "Psychedelic Rock",
        "Blues Rock",
        "New Wave",
        "Rock & Roll",
        "Hard Rock",
        "Garage Rock",
        "Glam",
        "Soft Rock",
        "Classic Rock",
        "Noise Rock",
        "Power Pop",
        "Dream Pop",
        "Grunge",
        "Prog Rock",
        "Post Rock",
        "Jangle Pop",
        "Britpop",
        "Krautrock",
        "Psychedelic",
        "Shoegaze",
        "Acid Rock",
        "Jazz-Rock",
        "Ethereal",
        "Rockabilly",
        "AOR",
        "Beat",
        "Space Rock",
        "Rock Opera",
        "Mod",
        "Goth Rock",
        "Antifolk",
        "Math Rock",
        "Stoner Rock",
        "Arena Rock",
        "Indie Pop",
        "Dance-pop",
        "Baroque Pop",
        "Alt-Pop",
        "Chanson",
        "Europop",
        "Music Hall",
        "Conscious",
        "Hardcore Hip-Hop",
        "Boom Bap",
        "Gangsta",
        "Pop Rap",
        "Jazzy Hip-Hop",
        "G-Funk",
        "Grime",
        "Cut-up/DJ",
        "Hip Hop",
        "Horrorcore",
        "Crunk",
        "Beatbox",
        "Ragga HipHop",
        "Synth-pop",
        "Downtempo",
        "Electro",
        "Leftfield",
        "Ambient",
        "Trip Hop",
        "House",
        "IDM",
        "Breakbeat",
        "French House",
        "UK Garage",
        "Techno",
        "Industrial",
        "Big Beat",
        "Breaks",
        "Tribal",
        "Acid House",
        "Electro House",
        "Electroclash",
        "Dubstep",
        "Bass Music",
        "Minimal",
        "Deep House",
        "Musique Concrète",
        "Darkwave",
        "Soul",
        "Neo Soul",
        "Gospel",
        "Contemporary R&B",
        "Rhythm & Blues",
        "New Jack Swing",
        "Funk",
        "Disco",
        "Minneapolis Sound",
        "P.Funk",
        "Boogie",
        "Bayou Funk",
        "Fusion",
        "Modal",
        "Soul-Jazz",
        "Avant-garde Jazz",
        "Post Bop",
        "Jazz-Funk",
        "Swing",
        "Contemporary Jazz",
        "Big Band",
        "Spiritual Jazz",
        "Free Jazz",
        "Piano Blues",
        "Louisiana Blues",
        "Electric Blues",
        "Texas Blues",
        "Folk Rock",
        "Folk",
        "Celtic",
        "Country Rock",
        "Country",
        "Punk",
        "Post-Punk",
        "Hardcore",
        "Post-Hardcore",
        "Pop Punk",
        "No Wave",
        "Synthpunk",
        "Heavy Metal",
        "Thrash",
        "Alternative Metal",
        "Funk Metal",
        "Speed Metal",
        "Groove Metal",
        "Nu Metal",
        "Reggae",
        "Dub",
        "Roots Reggae",
        "Ska",
        "Dancehall",
        "Rocksteady",
        "Modern Classical",
        "African",
        "Afrobeat",
        "Zydeco",
        "MPB",
    ]

    # Styles that are production or format descriptors, not genres.
    DELIBERATELY_DROPPED = [
        "Abstract",
        "Acoustic",
        "Avantgarde",
        "Ballad",
        "Experimental",
        "Instrumental",
        "Lo-Fi",
        "Parody",
        "Score",
        "Soundtrack",
        "Theme",
        "Vocal",
    ]

    def test_every_observed_style_resolves_to_a_root(self):
        unresolved = [
            style for style in self.OBSERVED if gn.resolve_style(style) is None
        ]
        self.assertEqual(unresolved, [])

    def test_the_dropped_styles_are_dropped_on_purpose(self):
        kept = [
            style
            for style in self.DELIBERATELY_DROPPED
            if gn.resolve_style(style, ["Rock"]) is not None
        ]
        self.assertEqual(kept, [])

    def test_the_spot_checks_that_the_audit_corrected(self):
        """Roots the Discogs-genre default got wrong before the name rule."""
        for style, expected in [
            ("Alternative Metal", "Metal"),
            ("Funk Metal", "Metal"),
            ("Groove Metal", "Metal"),
            ("Piano Blues", "Blues"),
            ("Texas Blues", "Blues"),
            ("Louisiana Blues", "Blues"),
            ("Big Band", "Jazz"),
            ("Zydeco", "World"),
            ("Afrobeat", "World"),
            ("Minneapolis Sound", "Funk"),
            ("Grime", "Hip Hop"),
            ("Ska", "Reggae"),
            ("Dub", "Reggae"),
            ("New Wave", "Rock"),
            ("Synth-pop", "Electronic"),
            ("Folk Rock", "Folk"),
            ("Country Rock", "Country"),
        ]:
            with self.subTest(style=style):
                self.assertEqual(gn.resolve_style(style, ["Rock"]), expected)


class ReparentingTests(TestCase):
    """A mapping fix has to reach the rows it was written for.

    `get_or_create_genre` used to return an existing row untouched, so
    "Alternative Rock" stayed filed under Electronic for 68 albums long
    after the resolution order was corrected: the row had been created from
    an album whose Discogs genres led with Electronic, and every later pass
    found it by name and left it alone.
    """

    def test_an_existing_genre_is_moved_when_its_root_changes(self):
        electronic = gn.get_or_create_genre("Electronic")
        stale = gn.get_or_create_genre("Alternative Rock", parent_name="Electronic")
        self.assertEqual(stale.parent_id, electronic.id)

        fixed = gn.get_or_create_genre("Alternative Rock", parent_name="Rock")
        fixed.refresh_from_db()
        self.assertEqual(fixed.parent.name, "Rock")
        self.assertEqual(fixed.level, 1)
        self.assertEqual(fixed.path, "Rock > Alternative Rock")

    def test_moving_a_genre_moves_its_children(self):
        gn.get_or_create_genre("Electronic")
        parent = gn.get_or_create_genre("Alternative Rock", parent_name="Electronic")
        child = MusicGenre.objects.create(
            name="Slacker Rock", parent=parent, level=2, path="x"
        )

        gn.get_or_create_genre("Alternative Rock", parent_name="Rock")
        child.refresh_from_db()
        self.assertEqual(child.level, 2)
        self.assertEqual(child.path, "Rock > Alternative Rock > Slacker Rock")

    def test_a_genre_already_in_the_right_place_is_left_alone(self):
        gn.get_or_create_genre("Rock")
        first = gn.get_or_create_genre("Pop Rock", parent_name="Rock")
        again = gn.get_or_create_genre("Pop Rock", parent_name="Rock")
        self.assertEqual(first.id, again.id)
        self.assertEqual(again.parent.name, "Rock")

    def test_the_real_mapping_puts_alternative_rock_under_rock(self):
        self.assertEqual(gn.resolve_style("Alternative Rock"), "Rock")
