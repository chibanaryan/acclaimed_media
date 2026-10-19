"""Tests for the controlled music genre vocabulary and the sources' vote.

Two failures shaped this module. Every Discogs style once became its own genre
row, which grew the tree to 207 leaves, 73 of them holding a single album. And
a style nobody had mapped took its root from the album's own Discogs genres,
which filed "Bubblegum" under Electronic and moved "Post-Modern" between
Classical and Electronic on every run. So a label now means only what the
vocabulary says it means, and every label the corpus uses is pinned here.
"""

from unittest import mock

from django.test import SimpleTestCase, TestCase

from music.models import MusicGenre
from music.services import genre_normalizer as gn
from music.templatetags.music_filters import MUSIC_GENRE_CATEGORY_ICONS


def votes(name, labels):
    return gn.votes_from_labels(name, labels)


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

    def test_root_aliases_name_real_roots(self):
        self.assertEqual(set(gn.ROOT_ALIASES) - set(gn.ROOT_GENRES), set())

    def test_hybrids_are_real_leaves_with_real_extra_roots(self):
        for leaf, roots in gn.HYBRID_ROOTS.items():
            with self.subTest(leaf=leaf):
                self.assertIn(leaf, gn.LEAF_PARENT)
                for root in roots:
                    self.assertIn(root, gn.ROOT_GENRES)
                    self.assertNotEqual(root, gn.LEAF_PARENT[leaf])

    def test_every_discogs_genre_implies_real_roots(self):
        for name, roots in gn.DISCOGS_GENRE_ROOTS.items():
            with self.subTest(discogs_genre=name):
                self.assertEqual(set(roots) - set(gn.ROOT_GENRES), set())

    def test_the_hierarchy_lists_every_leaf_once(self):
        leaves = [leaf for names in gn.GENRE_HIERARCHY.values() for leaf in names]
        self.assertEqual(len(leaves), len(set(leaves)))
        self.assertEqual(set(leaves), set(gn.LEAF_PARENT))


class LookupConsistencyTests(SimpleTestCase):
    def test_a_label_classified_two_ways_is_refused(self):
        with mock.patch.dict(gn.ROOT_ALIASES, {"Jazz": ("indie rock",)}):
            with self.assertRaisesRegex(ValueError, "classified twice"):
                gn._build_lookup()

    def test_a_leaf_under_two_roots_is_refused(self):
        with mock.patch.dict(
            gn.GENRE_VOCABULARY, {"Pop": {"Indie Rock": ()}}, clear=False
        ):
            with self.assertRaisesRegex(ValueError, "two roots"):
                gn._build_lookup()

    def test_repeating_the_same_classification_is_allowed(self):
        """'rock music' and 'Rock' both mean the Rock root; that is no conflict."""
        lookup, _ = gn._build_lookup()
        self.assertEqual(lookup["rock"], gn.Canonical(None, ("Rock",)))


class LabelKeyTests(SimpleTestCase):
    def test_spellings_of_one_genre_share_a_key(self):
        for a, b in [
            ("Hip-Hop", "hip hop"),
            ("Rock & Roll", "rock and roll"),
            ("heavy metal music", "Heavy Metal"),
            ("Post Rock", "post-rock"),
            ("P.Funk", "P-Funk"),
            ("Cut-up/DJ", "cut up dj"),
        ]:
            with self.subTest(a=a, b=b):
                self.assertEqual(gn.label_key(a), gn.label_key(b))

    def test_music_alone_is_not_stripped_to_nothing(self):
        self.assertEqual(gn.label_key("Music"), "music")


class CanonicalizeTests(SimpleTestCase):
    def test_a_leaf_matches_itself_with_its_root(self):
        self.assertEqual(
            gn.canonicalize("Indie Rock"), gn.Canonical("Indie Rock", ("Rock",))
        )

    def test_an_alias_collapses_into_its_leaf(self):
        self.assertEqual(gn.canonicalize("Glam").leaf, "Glam Rock")
        self.assertEqual(gn.canonicalize("thrash").leaf, "Thrash Metal")
        self.assertEqual(gn.canonicalize("Ethereal").leaf, "Dream Pop")

    def test_a_root_alias_means_only_the_root(self):
        self.assertEqual(gn.canonicalize("rock music"), gn.Canonical(None, ("Rock",)))
        self.assertEqual(gn.canonicalize("hip-hop"), gn.Canonical(None, ("Hip Hop",)))

    def test_a_hybrid_leaf_carries_its_extra_roots(self):
        self.assertEqual(gn.canonicalize("Folk Rock").roots, ("Rock", "Folk"))

    def test_a_dropped_label_is_classified_but_means_nothing(self):
        self.assertIsNone(gn.canonicalize("Vocal"))
        self.assertTrue(gn.is_classified("Vocal"))

    def test_an_unknown_label_is_not_classified(self):
        self.assertIsNone(gn.canonicalize("Utterly Unknown"))
        self.assertFalse(gn.is_classified("Utterly Unknown"))

    def test_roots_for_discogs_genre(self):
        self.assertEqual(
            gn.roots_for_discogs_genre("funk / soul"), ("Soul", "Funk", "R&B")
        )
        self.assertEqual(gn.roots_for_discogs_genre("Non-Music"), ())
        self.assertEqual(gn.roots_for_discogs_genre("Polka"), ())


class RealVocabularyTests(SimpleTestCase):
    """Every label the real release uses must be classified.

    An unclassified label is ignored, so the album silently loses whatever it
    meant. A new release with new labels fails here; add each one to
    ``genre_normalizer`` (as a leaf, an alias, a root alias or a dropped
    label) and to these lists. ``rebuild_album_genres --report`` lists them.
    """

    # Every Discogs style and Wikidata P136 label on the 1000-album release,
    # as of 2026-10-18.
    DISCOGS_STYLES = [
        "AOR",
        "Abstract",
        "Acid",
        "Acid House",
        "Acid Jazz",
        "Acid Rock",
        "Acoustic",
        "African",
        "Afro-Cuban",
        "Afro-Cuban Jazz",
        "Afrobeat",
        "Alt-Pop",
        "Alternative Metal",
        "Alternative Rock",
        "Ambient",
        "Antifolk",
        "Arena Rock",
        "Art Rock",
        "Avant-garde Jazz",
        "Avantgarde",
        "Ballad",
        "Baroque Pop",
        "Bass Music",
        "Bayou Funk",
        "Beat",
        "Beatbox",
        "Berlin-School",
        "Big Band",
        "Big Beat",
        "Blackgaze",
        "Blues Rock",
        "Bolero",
        "Boogie",
        "Boom Bap",
        "Bop",
        "Bossa Nova",
        "Breakbeat",
        "Breaks",
        "Britpop",
        "Broken Beat",
        "Bubblegum",
        "Cajun",
        "Celtic",
        "Chanson",
        "Chicago Blues",
        "Classic Rock",
        "Coldwave",
        "Conjunto",
        "Conscious",
        "Contemporary",
        "Contemporary Jazz",
        "Contemporary R&B",
        "Country",
        "Country Rock",
        "Crunk",
        "Cut-up/DJ",
        "Dance-pop",
        "Dancehall",
        "Danzon",
        "Darkwave",
        "Deconstructed Club",
        "Deep House",
        "Deep Techno",
        "Delta Blues",
        "Disco",
        "Doo Wop",
        "Downtempo",
        "Dream Pop",
        "Drone",
        "Drum n Bass",
        "Dub",
        "Dubstep",
        "Electric Blues",
        "Electro",
        "Electro House",
        "Electroclash",
        "Ethereal",
        "Europop",
        "Experimental",
        "Flamenco",
        "Folk",
        "Folk Rock",
        "Free Jazz",
        "French House",
        "Funk",
        "Funk Metal",
        "Fusion",
        "Future Jazz",
        "G-Funk",
        "Gangsta",
        "Garage House",
        "Garage Rock",
        "Glam",
        "Glitch",
        "Glitch Hop",
        "Gospel",
        "Goth Rock",
        "Gqom",
        "Grime",
        "Grindcore",
        "Groove Metal",
        "Grunge",
        "Guajira",
        "Hard Bop",
        "Hard Rock",
        "Hardcore",
        "Hardcore Hip-Hop",
        "Harmonica Blues",
        "Heavy Metal",
        "Hip Hop",
        "Hip-House",
        "Holiday",
        "Honky Tonk",
        "Horrorcore",
        "House",
        "Hyperpop",
        "Hyphy",
        "IDM",
        "Indie Pop",
        "Indie Rock",
        "Industrial",
        "Instrumental",
        "Jangle Pop",
        "Jazz-Funk",
        "Jazz-Rock",
        "Jazzy Hip-Hop",
        "Jungle",
        "Krautrock",
        "Latin Jazz",
        "Leftfield",
        "Lo-Fi",
        "Louisiana Blues",
        "Lounge",
        "MPB",
        "Math Rock",
        "Mbalax",
        "Memphis Blues",
        "Minimal",
        "Minimalism",
        "Minneapolis Sound",
        "Mod",
        "Modal",
        "Modern Classical",
        "Music Hall",
        "Musique Concrète",
        "Neo Soul",
        "New Age",
        "New Jack Swing",
        "New Wave",
        "No Wave",
        "Noise",
        "Noise Rock",
        "Norteño",
        "Nu Metal",
        "P.Funk",
        "Pachanga",
        "Parody",
        "Piano Blues",
        "Plunderphonics",
        "Pop Punk",
        "Pop Rap",
        "Pop Rock",
        "Post Bop",
        "Post Rock",
        "Post-Hardcore",
        "Post-Metal",
        "Post-Modern",
        "Post-Punk",
        "Power Pop",
        "Prog Rock",
        "Progressive House",
        "Psychedelic",
        "Psychedelic Rock",
        "Psychobilly",
        "Punk",
        "Radioplay",
        "Ragga HipHop",
        "Reggae",
        "Religious",
        "Rhythm & Blues",
        "Rock & Roll",
        "Rock Opera",
        "Rockabilly",
        "Rocksteady",
        "Roots Reggae",
        "Samba",
        "Score",
        "Shoegaze",
        "Ska",
        "Slowcore",
        "Smooth Jazz",
        "Soft Rock",
        "Son",
        "Soul",
        "Soul-Jazz",
        "Sound Collage",
        "Soundtrack",
        "Southern Rock",
        "Space Rock",
        "Space-Age",
        "Speech",
        "Speed Metal",
        "Spiritual Jazz",
        "Stoner Rock",
        "Surf",
        "Swing",
        "Symphonic Rock",
        "Synth-pop",
        "Synthpunk",
        "Techno",
        "Texas Blues",
        "Theme",
        "Thrash",
        "Trance",
        "Trap",
        "Tribal",
        "Trip Hop",
        "Trova",
        "UK Funky",
        "UK Garage",
        "Vocal",
        "Zydeco",
    ]

    WIKIDATA_LABELS = [
        "2-step garage",
        "Afrobeat",
        "Berlin School of electronic music",
        "Brill Building",
        "British blues",
        "British folk rock",
        "British rock",
        "Britpop",
        "Canterbury scene",
        "Chicago blues",
        "Chicano rock",
        "Christgau's Record Guide: Rock Albums of the Seventies",
        "Christmas music",
        "East Coast hip-hop",
        "Eurodisco",
        "Europop",
        "French house",
        "French pop",
        "French rock",
        "G-funk",
        "Irish folk music",
        "Krautrock",
        "Latin rock",
        "Lo-fi",
        "Madchester",
        "Midwest hip-hop",
        "Minneapolis sound",
        "New Orleans rhythm and blues",
        "Southern Gothic",
        "Southern hip-hop",
        "Southern rock",
        "Texas blues",
        "Ticknor and Fields",
        "West Coast hip-hop",
        "acid house",
        "acid rock",
        "acoustic music",
        "alternative R&B",
        "alternative country",
        "alternative dance",
        "alternative hip-hop",
        "alternative metal",
        "alternative rock",
        "ambient house",
        "ambient music",
        "ambient techno",
        "anti-folk",
        "arena rock",
        "art pop",
        "art punk",
        "art rock",
        "avant-funk",
        "avant-garde jazz",
        "avant-garde music",
        "avant-pop",
        "baroque pop",
        "beat music",
        "blue-eyed soul",
        "bluegrass music",
        "blues",
        "blues rock",
        "boogie rock",
        "boom bap",
        "bossa nova",
        "breakbeat",
        "bubblegum music",
        "chamber pop",
        "chill-out music",
        "chipmunk soul",
        "comedy hip-hop",
        "conscious hip-hop",
        "contemporary R&B",
        "contemporary folk music",
        "cool jazz",
        "country blues",
        "country music",
        "country pop",
        "country rap",
        "country rock",
        "crossover",
        "dance music",
        "dance-pop",
        "dance-punk",
        "dance-rock",
        "dark ambient",
        "dark wave",
        "deathrock",
        "devotional song",
        "disco",
        "downtempo",
        "dream pop",
        "drum and bass",
        "dub music",
        "dubstep",
        "easy listening",
        "electric blues",
        "electro",
        "electro house",
        "electronic dance music",
        "electronic music",
        "electronic rock",
        "electronica",
        "electropop",
        "emo",
        "ethereal wave",
        "experimental hip-hop",
        "experimental music",
        "experimental pop",
        "experimental rock",
        "extreme metal",
        "flamenco",
        "folk jazz",
        "folk music",
        "folk punk",
        "folk rock",
        "folk-pop",
        "folktronica",
        "free jazz",
        "funk",
        "funk metal",
        "funk rock",
        "gangsta rap",
        "garage punk",
        "garage rock",
        "glam punk",
        "glam rock",
        "golden age hip-hop",
        "gospel music",
        "gothic rock",
        "grindcore",
        "grunge",
        "hard rock",
        "hardcore hip-hop",
        "hardcore punk",
        "heartland rock",
        "heavy metal music",
        "hip house",
        "hip-hop",
        "hip-hop soul",
        "honky-tonk",
        "horrorcore",
        "house music",
        "hyperpop",
        "indie folk",
        "indie pop",
        "indie rock",
        "indietronica",
        "industrial music",
        "industrial rock",
        "instrumental music",
        "intelligent dance music",
        "jam band music",
        "jangle pop",
        "jazz",
        "jazz fusion",
        "jazz rap",
        "jazz-funk",
        "leftfield house",
        "lo-fi music",
        "mafioso rap",
        "mashup",
        "math rock",
        "mbaqanga",
        "minimalist music",
        "mod revival",
        "modal jazz",
        "music hall",
        "music of Africa",
        "musique concrète",
        "música popular brasileira",
        "neo soul",
        "neo-psychedelia",
        "neofolk",
        "new age music",
        "new jack swing",
        "new wave",
        "no wave",
        "noise music",
        "noise pop",
        "noise rock",
        "nu jazz",
        "nu metal",
        "old-school hip-hop",
        "opera",
        "orchestral pop",
        "outsider music",
        "plunderphonics",
        "political hip-hop",
        "pop music",
        "pop rap",
        "pop rock",
        "pop-punk",
        "popular music",
        "post-Britpop",
        "post-bop",
        "post-disco",
        "post-hardcore",
        "post-progressive",
        "post-punk",
        "post-punk revival",
        "post-rock",
        "power pop",
        "progressive house",
        "progressive pop",
        "progressive rap",
        "progressive rock",
        "proto-punk",
        "psychedelic folk",
        "psychedelic funk",
        "psychedelic music",
        "psychedelic pop",
        "psychedelic rap",
        "psychedelic rock",
        "psychedelic soul",
        "psychobilly",
        "pub rock",
        "punk jazz",
        "quiet storm",
        "rap metal",
        "rap rock",
        "rapping",
        "reggae",
        "reggae fusion",
        "reggae rock",
        "reggaeton",
        "religious music",
        "rhythm and blues",
        "rock and roll",
        "rock music",
        "rock opera",
        "rockabilly",
        "rocksteady",
        "roots reggae",
        "roots rock",
        "samba rock",
        "shoegaze",
        "singer-songwriter music",
        "ska",
        "slowcore",
        "smooth jazz",
        "soft rock",
        "sophisti-pop",
        "soul",
        "soul blues",
        "space rock",
        "space rock revival",
        "speed metal",
        "spiritual jazz",
        "spoken word",
        "stage and screen",
        "stoner rock",
        "sunshine pop",
        "surf music",
        "swamp rock",
        "symphonic rock",
        "synth-pop",
        "synth-punk",
        "techno",
        "thrash metal",
        "traditional doom metal",
        "traditional folk music",
        "traditional heavy metal",
        "traditional pop",
        "trance",
        "trap music",
        "trip hop",
        "turntablism",
        "underground hip-hop",
        "vaporwave",
        "vocal jazz",
        "world music",
        "worldbeat",
    ]

    def test_every_observed_discogs_style_is_classified(self):
        self.assertEqual(
            [label for label in self.DISCOGS_STYLES if not gn.is_classified(label)],
            [],
        )

    def test_every_observed_wikidata_label_is_classified(self):
        self.assertEqual(
            [label for label in self.WIKIDATA_LABELS if not gn.is_classified(label)],
            [],
        )

    def test_the_styles_the_old_fallback_misfiled(self):
        """Each of these once took its root from the album's Discogs genres."""
        for label, expected in [
            ("Bubblegum", gn.Canonical(None, ("Pop",))),
            ("Hyphy", gn.Canonical(None, ("Hip Hop",))),
            ("Son", gn.Canonical("Latin", ("World",))),
            ("Conjunto", gn.Canonical("Latin", ("World",))),
            ("Mbalax", gn.Canonical("African", ("World",))),
            ("Grindcore", gn.Canonical(None, ("Metal",))),
            ("Doo Wop", gn.Canonical("Rhythm & Blues", ("R&B",))),
        ]:
            with self.subTest(label=label):
                self.assertEqual(gn.canonicalize(label), expected)
        for label in ("Post-Modern", "Radioplay", "Speech", "Religious", "Holiday"):
            with self.subTest(label=label):
                self.assertIsNone(gn.canonicalize(label))

    def test_the_two_vocabularies_meet(self):
        """Discogs' and Wikidata's spellings of one genre land on one leaf."""
        for discogs, wikidata in [
            ("Conscious", "conscious hip-hop"),
            ("Jazzy Hip-Hop", "jazz rap"),
            ("Fusion", "jazz fusion"),
            ("Prog Rock", "progressive rock"),
            ("Hardcore", "hardcore punk"),
            ("Gangsta", "gangsta rap"),
            ("Glam", "glam rock"),
        ]:
            with self.subTest(discogs=discogs):
                self.assertEqual(
                    gn.canonicalize(discogs).leaf, gn.canonicalize(wikidata).leaf
                )


class VotesFromLabelsTests(SimpleTestCase):
    def test_order_is_kept_and_repeats_dropped(self):
        result = votes("wikidata", ["glam rock", "Glam", "art rock"])
        self.assertEqual(result.leaves, ["Glam Rock", "Art Rock"])

    def test_root_labels_become_roots(self):
        result = votes("wikidata", ["rock music", "hip-hop", "rock"])
        self.assertEqual(result.roots, ["Rock", "Hip Hop"])

    def test_unknown_labels_are_collected_and_dropped_ones_are_not(self):
        result = votes("wikidata", ["Utterly Unknown", "Vocal", "", None, "  "])
        self.assertEqual(result.unclassified, ["Utterly Unknown"])
        self.assertTrue(result.is_empty)

    def test_all_roots_includes_the_leaves_roots(self):
        result = votes("discogs", ["Folk Rock", "Disco"])
        self.assertEqual(result.all_roots, {"Rock", "Folk", "Funk"})


class DiscogsVotesTests(SimpleTestCase):
    def test_top_level_genres_are_evidence_not_labels(self):
        result = gn.discogs_votes(["Pop Rock"], ["Rock", "Funk / Soul", "Polka"])
        self.assertEqual(result.leaves, ["Pop Rock"])
        self.assertEqual(result.roots, [])
        self.assertEqual(
            result.evidence_roots, ["Rock", "Punk", "Metal", "Soul", "Funk", "R&B"]
        )
        self.assertEqual(result.fallback_roots, ["Rock", "Soul"])

    def test_evidence_alone_is_not_empty(self):
        result = gn.discogs_votes([], ["Jazz", "Jazz"])
        self.assertFalse(result.has_labels)
        self.assertFalse(result.is_empty)
        self.assertEqual(result.fallback_roots, ["Jazz"])

    def test_nothing_at_all(self):
        self.assertTrue(gn.discogs_votes(None, None).is_empty)


class ChooseAlbumGenresTests(SimpleTestCase):
    def choose(self, *sources):
        return gn.choose_album_genres(sources)

    def test_the_base_source_is_kept_whole(self):
        """Purple Rain: Wikidata's lone "rock and roll" must not cost it Funk."""
        genres = self.choose(
            gn.discogs_votes(
                ["Minneapolis Sound", "Funk", "Pop Rock"], ["Rock", "Funk / Soul"]
            ),
            votes("wikidata", ["rock and roll"]),
        )
        self.assertEqual(genres.roots, ["Rock", "Funk"])
        self.assertEqual(genres.leaves, ["Minneapolis Sound", "Pop Rock"])

    def test_another_sources_leaf_needs_a_second_vote(self):
        genres = self.choose(
            gn.discogs_votes(["Indie Rock"], ["Rock"]),
            votes("wikidata", ["indie rock", "space rock"]),
            votes("musicbrainz", ["space rock"]),
        )
        self.assertEqual(genres.leaves, ["Indie Rock", "Space Rock"])

    def test_a_single_extra_opinion_in_a_covered_root_is_dropped(self):
        """The Sophtware Slump: Wikidata's "space rock" alone adds nothing."""
        genres = self.choose(
            gn.discogs_votes(["Downtempo", "Indie Rock"], ["Electronic", "Rock"]),
            votes("wikidata", ["indie rock", "space rock"]),
        )
        self.assertEqual(genres.leaves, ["Downtempo", "Indie Rock"])

    def test_an_agreed_root_with_no_leaf_takes_the_first_one_named(self):
        """The Velvet Underground & Nico gains Wikidata's Proto-Punk.

        Discogs' "Rock" is evidence for Punk, so Wikidata's punk label makes
        two votes for the root, and Discogs has no leaf there of its own.
        """
        genres = self.choose(
            gn.discogs_votes(["Garage Rock", "Art Rock"], ["Rock"]),
            votes("wikidata", ["art rock", "proto-punk", "art pop"]),
        )
        self.assertEqual(genres.leaves, ["Garage Rock", "Art Rock", "Proto-Punk"])
        self.assertEqual(genres.roots, ["Rock", "Punk"])

    def test_evidence_alone_does_not_tag_an_album(self):
        """OK Computer is "Electronic, Rock" on Discogs, with only rock styles."""
        genres = self.choose(
            gn.discogs_votes(["Alternative Rock"], ["Electronic", "Rock"]),
            votes("wikidata", ["alternative rock", "art rock"]),
        )
        self.assertNotIn("Electronic", genres.roots)

    def test_an_agreed_root_is_kept_without_a_leaf(self):
        genres = self.choose(
            gn.discogs_votes(["Contemporary R&B"], ["Funk / Soul", "Pop"]),
            votes("wikidata", ["pop music"]),
        )
        self.assertEqual(genres.roots, ["Pop", "R&B"])
        self.assertEqual(genres.leaves, ["Contemporary R&B"])

    def test_a_hybrid_leaf_tags_every_root_it_belongs_to(self):
        """Harvest belongs under Rock as well as Folk and Country."""
        genres = self.choose(
            gn.discogs_votes(["Folk Rock", "Country Rock"], ["Rock"]),
            votes("wikidata", ["country rock", "folk rock"]),
        )
        self.assertEqual(genres.roots, ["Rock", "Folk", "Country"])

    def test_a_lone_source_is_trusted(self):
        genres = self.choose(
            gn.discogs_votes([], []),
            votes("wikidata", []),
            votes("musicbrainz", ["soul", "southern soul"]),
        )
        self.assertEqual(genres.names, ["Soul", "Southern Soul"])

    def test_the_base_is_the_first_source_with_labels(self):
        """An album whose Discogs master has no styles is based on Wikidata."""
        genres = self.choose(
            gn.discogs_votes([], ["Jazz"]),
            votes("wikidata", ["modal jazz"]),
        )
        self.assertEqual(genres.names, ["Jazz", "Modal Jazz"])

    def test_with_only_evidence_the_fallback_root_is_used(self):
        genres = self.choose(gn.discogs_votes([], ["Funk / Soul"]))
        self.assertEqual(genres.names, ["Soul"])

    def test_no_data_at_all_yields_nothing(self):
        self.assertEqual(self.choose().names, [])
        self.assertEqual(self.choose(votes("wikidata", ["Vocal"])).names, [])


class PruneRareLeavesTests(SimpleTestCase):
    def test_a_rare_leaf_is_dropped_and_its_roots_kept(self):
        assignments = {
            1: gn.AlbumGenres(leaves=["Indie Rock", "Folk Rock"], roots=["Rock"]),
            2: gn.AlbumGenres(leaves=["Indie Rock"], roots=["Rock"]),
        }
        pruned, rare = gn.prune_rare_leaves(assignments, min_albums=2)
        self.assertEqual(rare, {"Folk Rock": 1})
        self.assertEqual(pruned[1].leaves, ["Indie Rock"])
        self.assertEqual(pruned[1].roots, ["Rock", "Folk"])
        self.assertEqual(pruned[2].names, ["Rock", "Indie Rock"])

    def test_the_default_threshold(self):
        assignments = {
            i: gn.AlbumGenres(leaves=["Grunge"], roots=["Rock"])
            for i in range(gn.MIN_LEAF_ALBUMS - 1)
        }
        _, rare = gn.prune_rare_leaves(assignments)
        self.assertIn("Grunge", rare)


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

    def test_a_canonical_genre_lands_in_its_vocabulary_position(self):
        self.assertEqual(
            gn.get_or_create_canonical_genre("Folk Rock").parent.name, "Rock"
        )
        self.assertIsNone(gn.get_or_create_canonical_genre("Folk").parent)


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

    def test_the_real_vocabulary_puts_alternative_rock_under_rock(self):
        self.assertEqual(gn.LEAF_PARENT["Alternative Rock"], "Rock")
