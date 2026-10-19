"""
Map external genre labels onto our own controlled ``MusicGenre`` vocabulary.

Three sources describe an album's genres, and none of them is good enough on
its own:

* **Discogs styles** cover 99% of the corpus, but the vocabulary belongs to a
  record shop. It mixes in descriptors ("Vocal", "Ballad", "Experimental") and
  some loose tags: "Rock & Roll" on *After the Gold Rush*, "Thrash" on the
  Black Album.
* **Wikidata P136** reads like a critic ("proto-punk", "art punk") but it is
  thin. 533 of 973 albums carry exactly one genre, 139 carry only a generic
  one ("pop music" for *FutureSex/LoveSounds*), and it has *more* distinct
  labels than Discogs (272 against 222).
* **MusicBrainz** genres are community votes, filled by the opt-in
  ``--musicbrainz`` pass.

When every source label became its own genre row, the tree reached 207 leaves,
73 of them holding a single album. So the vocabulary here is **ours**:
``GENRE_VOCABULARY`` names every leaf and the root it hangs from, and each
source label is either one of those names, an alias of one, a root, or a
label we drop on purpose. Nothing else creates a genre row. A label nobody has
classified is ignored and reported by ``rebuild_album_genres``, which is how
the vocabulary grows. That also closes the old per-album fallback, which took
an unmapped style's root from the album's own Discogs genres and so filed
"Bubblegum" under Electronic and "Son" under Jazz, and moved "Post-Modern"
between Classical and Electronic on every run.

The sources then vote (``choose_album_genres``), and ``prune_rare_leaves``
removes the leaves too rare to be worth a filter row.

Why not Wikidata's P279 subclass graph for the hierarchy: walking P279 up to a
root classified only 159 of this corpus's 207 genre entities unambiguously,
filed thrash metal under Rock and mbaqanga under Jazz, and left ska, dub and
ambient music unreachable.
"""

import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from django.utils.text import slugify

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------- vocabulary

#: Root -> {leaf: aliases}. The roots are the filter's top level, in the order
#: it presents them, and every one needs an entry in
#: ``music_filters.MUSIC_GENRE_CATEGORY_ICONS``. A leaf's own name matches
#: itself, so its aliases list only the *other* spellings and near-synonyms
#: that should collapse into it.
#:
#: The roots are deliberately not Discogs': Discogs files Punk and Metal under
#: Rock and collapses Funk, Soul and R&B into one "Funk / Soul", which is too
#: coarse for a site ranking acclaimed albums.
GENRE_VOCABULARY: Dict[str, Dict[str, Tuple[str, ...]]] = {
    "Rock": {
        "Alternative Rock": (),
        "Indie Rock": (),
        "Pop Rock": (),
        "Art Rock": ("experimental rock",),
        "Psychedelic Rock": (
            "psychedelic",
            "psychedelic music",
            "acid rock",
            "neo-psychedelia",
            "psychedelic pop",
        ),
        "Hard Rock": ("arena rock", "boogie rock"),
        "Blues Rock": ("british blues",),
        "Garage Rock": ("garage punk",),
        "Glam Rock": ("glam",),
        "Prog Rock": (
            "progressive rock",
            "symphonic rock",
            "canterbury scene",
            "post-progressive",
        ),
        "Krautrock": (),
        "Space Rock": ("space rock revival",),
        "Post-Rock": (),
        "Noise Rock": (),
        "Noise Pop": (),
        "Shoegaze": ("blackgaze",),
        "Dream Pop": ("ethereal", "ethereal wave"),
        "Jangle Pop": (),
        "Power Pop": (),
        "Britpop": ("post-britpop",),
        "Grunge": (),
        "New Wave": (),
        "Goth Rock": ("gothic rock", "deathrock"),
        "Soft Rock": ("yacht rock",),
        "Roots Rock": ("heartland rock", "pub rock", "swamp rock"),
        "Southern Rock": (),
        "Rock & Roll": ("rockabilly", "psychobilly"),
        "Folk Rock": ("british folk rock",),
        "Country Rock": ("alternative country", "alt-country"),
        "Beat Music": ("mod", "mod revival", "merseybeat"),
        "Math Rock": (),
        "Stoner Rock": (),
        "Slowcore": (),
        "Surf Rock": ("surf",),
    },
    "Pop": {
        "Indie Pop": ("alt-pop",),
        "Art Pop": ("avant-pop", "experimental pop", "progressive pop"),
        "Baroque Pop": ("chamber pop", "orchestral pop", "sunshine pop"),
        "Dance-pop": ("europop",),
        "Traditional Pop": (
            "easy listening",
            "lounge",
            "space-age",
            "music hall",
        ),
        "Chanson": ("french pop",),
    },
    "Hip Hop": {
        "Conscious Hip Hop": ("conscious", "political hip-hop", "progressive rap"),
        "Gangsta Rap": ("gangsta", "mafioso rap", "g-funk"),
        "Boom Bap": ("golden age hip-hop",),
        "Hardcore Hip Hop": ("horrorcore",),
        "Alternative Hip Hop": (
            "experimental hip-hop",
            "underground hip-hop",
            "abstract hip hop",
            "psychedelic rap",
        ),
        "Jazz Rap": ("jazzy hip-hop",),
        "Pop Rap": (),
        "Trap": (),
        "Grime": (),
        "Turntablism": ("cut-up/dj", "beatbox"),
    },
    "Electronic": {
        "Synth-pop": ("synthpop", "electropop", "electroclash"),
        "Ambient": ("new age", "dark ambient", "drone", "berlin school"),
        "Downtempo": ("chill-out",),
        "Trip Hop": (),
        "IDM": ("intelligent dance music", "glitch"),
        "House": (
            "acid",
            "acid house",
            "deep house",
            "garage house",
            "progressive house",
            "electro house",
            "french house",
            "leftfield house",
            "ambient house",
            "hip-house",
            "hip house",
            "gqom",
        ),
        "Techno": ("deep techno", "minimal", "ambient techno"),
        "Electro": (),
        "Industrial": ("industrial rock",),
        "UK Garage": ("2-step garage", "uk funky"),
        "Drum and Bass": ("drum n bass", "jungle"),
        "Dubstep": (),
        "Breakbeat": ("breaks", "broken beat"),
        "Big Beat": (),
        "Trance": (),
        "Darkwave": ("dark wave", "coldwave"),
        "Alternative Dance": (
            "dance-punk",
            "dance-rock",
            "madchester",
            "indietronica",
        ),
        "Plunderphonics": ("sound collage", "mashup"),
    },
    "Soul": {
        "Neo Soul": (),
        "Psychedelic Soul": (),
        "Southern Soul": ("deep soul",),
        "Blue-Eyed Soul": (),
        "Gospel": ("devotional song",),
    },
    "R&B": {
        "Contemporary R&B": ("alternative r&b", "quiet storm", "hip-hop soul"),
        "Rhythm & Blues": ("new orleans rhythm and blues", "doo wop"),
        "New Jack Swing": ("swingbeat",),
    },
    "Funk": {
        "Disco": ("post-disco", "boogie", "eurodisco"),
        "P-Funk": (),
        "Minneapolis Sound": (),
    },
    "Jazz": {
        "Jazz Fusion": ("fusion", "jazz-rock"),
        "Modal Jazz": ("modal",),
        "Hard Bop": ("bop", "bebop"),
        "Post-Bop": (),
        "Cool Jazz": (),
        "Free Jazz": ("avant-garde jazz", "punk jazz"),
        "Spiritual Jazz": (),
        "Soul-Jazz": (),
        "Jazz-Funk": (),
        "Big Band": ("swing",),
        "Vocal Jazz": (),
        "Latin Jazz": ("afro-cuban jazz",),
        "Smooth Jazz": (),
        "Acid Jazz": (),
    },
    "Blues": {
        "Chicago Blues": ("electric blues",),
        "Delta Blues": ("country blues",),
        "Piano Blues": (),
        "Texas Blues": (),
        "Louisiana Blues": (),
        "Memphis Blues": (),
    },
    "Folk": {
        "Indie Folk": ("antifolk", "anti-folk"),
        "Traditional Folk": ("irish folk", "celtic", "british folk"),
        "Psychedelic Folk": (),
    },
    "Country": {
        "Honky Tonk": (),
        "Bluegrass": (),
        "Outlaw Country": (),
    },
    "Punk": {
        "Post-Punk": ("post-punk revival",),
        "Hardcore Punk": ("hardcore",),
        "Post-Hardcore": ("emo",),
        "Pop Punk": (),
        "No Wave": (),
        "Proto-Punk": (),
    },
    "Metal": {
        "Heavy Metal": ("traditional heavy metal",),
        "Thrash Metal": ("thrash", "speed metal", "groove metal"),
        "Alternative Metal": ("funk metal", "nu metal", "rap metal", "rap rock"),
        "Doom Metal": ("traditional doom metal",),
    },
    "Reggae": {
        "Roots Reggae": (),
        "Dub": (),
        "Dancehall": ("ragga",),
        "Ska": ("rocksteady",),
        "Lovers Rock": (),
    },
    "Classical": {
        "Modern Classical": (),
        "Minimalism": ("minimalist",),
    },
    "World": {
        "Afrobeat": (),
        "African": (
            "music of africa",
            "mbaqanga",
            "mbalax",
            "highlife",
            "soukous",
            "worldbeat",
        ),
        "Brazilian": (
            "mpb",
            "música popular brasileira",
            "samba",
            "samba rock",
            "bossa nova",
            "tropicália",
        ),
        "Latin": (
            "afro-cuban",
            "son",
            "bolero",
            "danzon",
            "guajira",
            "trova",
            "pachanga",
            "conjunto",
            "norteño",
            "reggaeton",
        ),
    },
}

#: Labels that mean a root and nothing finer, beyond the root's own name.
#: "hip-hop" or "rock music" says which root, and that is all it says.
ROOT_ALIASES: Dict[str, Tuple[str, ...]] = {
    "Rock": (
        "rock music",
        "electronic rock",
        "british rock",
        "french rock",
        "latin rock",
        "chicano rock",
    ),
    "Pop": (
        "pop music",
        "bubblegum",
        "brill building",
        "sophisti-pop",
        "hyperpop",
    ),
    "Hip Hop": (
        "hip-hop",
        "rap",
        "rapping",
        "east coast hip-hop",
        "west coast hip-hop",
        "southern hip-hop",
        "midwest hip-hop",
        "old-school hip-hop",
        "comedy hip-hop",
        "country rap",
        "chipmunk soul",
        "crunk",
        "hyphy",
        "ragga hiphop",
    ),
    "Electronic": (
        "electronica",
        "leftfield",
        "dance",
        "electronic dance music",
        "folktronica",
        "vaporwave",
        "glitch hop",
        "bass music",
        "deconstructed club",
        "tribal",
        "musique concrète",
        "berlin school of electronic",
    ),
    "Soul": ("smooth soul", "philly soul"),
    "Funk": ("bayou funk", "avant-funk", "funk rock", "psychedelic funk"),
    "Jazz": ("contemporary jazz", "future jazz", "nu jazz", "folk jazz", "ethio-jazz"),
    "Blues": ("harmonica blues", "soul blues"),
    "Folk": ("contemporary folk", "folk-pop", "folk punk", "neofolk"),
    "Country": ("country pop", "nashville sound", "americana"),
    "Punk": (
        "punk rock",
        "art punk",
        "glam punk",
        "synthpunk",
        "synth-punk",
        "oi",
        "anarcho-punk",
        "riot grrrl",
    ),
    "Metal": (
        "grindcore",
        "extreme metal",
        "post-metal",
        "death metal",
        "black metal",
        "sludge metal",
        "metalcore",
        "hair metal",
    ),
    "Reggae": ("reggae fusion", "reggae rock"),
    "Classical": ("opera",),
    "World": ("world music", "flamenco", "cajun", "zydeco", "fado", "raï"),
}

#: Labels that are deliberately not genres. Discogs mixes descriptors in with
#: its styles, and Wikidata has a few data errors in P136 (a book publisher,
#: a record guide). Filing a descriptor as a genre makes the filter worse, so
#: these are dropped - and listed, so a dropped label is a decision rather
#: than a gap.
DROPPED_LABELS: Tuple[str, ...] = (
    "experimental",
    "avantgarde",
    "avant-garde",
    "abstract",
    "ballad",
    "acoustic",
    "lo-fi",
    "vocal",
    "instrumental",
    "soundtrack",
    "score",
    "theme",
    "stage and screen",
    "parody",
    "novelty",
    "comedy",
    "holiday",
    "christmas",
    "radioplay",
    "speech",
    "spoken word",
    "monolog",
    "poetry",
    "interview",
    "education",
    "field recording",
    "religious",
    "post-modern",
    "contemporary",
    "classic rock",
    "aor",
    "rock opera",
    "noise",
    "outsider",
    "crossover",
    "popular",
    "singer-songwriter",
    "jam band",
    "southern gothic",
    "christgau's record guide: rock albums of the seventies",
    "ticknor and fields",
)

#: Leaves that belong to more than one root. The tree is single-parent, so the
#: leaf sits under the root ``GENRE_VOCABULARY`` gives it; an album tagged
#: with the leaf is *also* tagged with these roots. That is how *Harvest*
#: appears under Rock, Folk and Country, where a single parent left it out of
#: Rock entirely.
HYBRID_ROOTS: Dict[str, Tuple[str, ...]] = {
    "Folk Rock": ("Folk",),
    "Country Rock": ("Country",),
    "Synth-pop": ("Pop",),
    "Jazz-Funk": ("Funk",),
    "Psychedelic Soul": ("Funk",),
    "Alternative Dance": ("Rock",),
}

#: Discogs' closed set of top-level genres, as root evidence. Where Discogs
#: is coarser than we are it implies every root it covers: "Funk / Soul" is
#: evidence for Funk, Soul and R&B alike, and another source decides which.
DISCOGS_GENRE_ROOTS: Dict[str, Tuple[str, ...]] = {
    "Rock": ("Rock", "Punk", "Metal"),
    "Pop": ("Pop",),
    "Hip Hop": ("Hip Hop",),
    "Electronic": ("Electronic",),
    "Funk / Soul": ("Soul", "Funk", "R&B"),
    "Jazz": ("Jazz",),
    "Blues": ("Blues",),
    "Reggae": ("Reggae",),
    "Classical": ("Classical",),
    "Folk, World, & Country": ("Folk", "World", "Country"),
    "Latin": ("World",),
    "Brass & Military": ("Classical",),
    "Non-Music": (),
    "Stage & Screen": (),
    "Children's": (),
}

#: The root set, in the order the filter presents them.
GENRE_HIERARCHY: Dict[str, List[str]] = {
    root: list(leaves) for root, leaves in GENRE_VOCABULARY.items()
}
ROOT_GENRES = tuple(GENRE_HIERARCHY)

# ----------------------------------------------------------------- consensus

#: A leaf held by fewer albums than this is not worth a row in the filter; its
#: albums keep the roots it implied. Before this the tree had 73 leaves with
#: exactly one album.
MIN_LEAF_ALBUMS = 3

#: How many MusicBrainz genres count as its vote. It lists everything anyone
#: has voted for, eight or more for a popular album, most-voted first.
MAX_MUSICBRAINZ_GENRES = 5


def label_key(label: str) -> str:
    """A comparison key that collapses spelling differences between sources.

    Case, hyphens versus spaces, '&' versus 'and', and Wikidata's habit of
    suffixing " music" all vary for the same genre: 'Hip-Hop', 'hip hop';
    'Rock & Roll', 'rock and roll'; 'heavy metal music', 'Heavy Metal'.
    """
    key = label.casefold().replace("&", " and ")
    key = re.sub(r"[-_/.]", " ", key)
    key = re.sub(r"\s+", " ", key).strip()
    if key.endswith(" music") and key != "music":
        key = key[: -len(" music")]
    return key


@dataclass(frozen=True)
class Canonical:
    """What one source label means: a leaf and its roots, or just roots."""

    leaf: Optional[str]
    roots: Tuple[str, ...]


def _build_lookup():
    leaf_roots = {}
    lookup: Dict[str, Optional[Canonical]] = {}

    def add(key_label, value):
        key = label_key(key_label)
        if key in lookup and lookup[key] != value:
            raise ValueError(f"Genre label {key_label!r} is classified twice")
        lookup[key] = value

    for root, leaves in GENRE_VOCABULARY.items():
        add(root, Canonical(None, (root,)))
        for leaf, aliases in leaves.items():
            if leaf in leaf_roots:
                raise ValueError(f"Genre {leaf!r} appears under two roots")
            roots = (root,) + HYBRID_ROOTS.get(leaf, ())
            leaf_roots[leaf] = roots
            canonical = Canonical(leaf, roots)
            add(leaf, canonical)
            for alias in aliases:
                add(alias, canonical)

    for root, aliases in ROOT_ALIASES.items():
        for alias in aliases:
            add(alias, Canonical(None, (root,)))

    for label in DROPPED_LABELS:
        add(label, None)

    return lookup, leaf_roots


_LOOKUP, LEAF_ROOTS = _build_lookup()

#: Leaf -> the root it hangs from in the tree.
LEAF_PARENT: Dict[str, str] = {leaf: roots[0] for leaf, roots in LEAF_ROOTS.items()}


def is_classified(label: str) -> bool:
    """Whether the vocabulary has decided what this label means.

    True for leaves, aliases, roots *and* deliberately dropped labels.
    """
    return label_key(label) in _LOOKUP


def canonicalize(label: str) -> Optional[Canonical]:
    """The leaf and roots a source label means, or None.

    None covers both a label dropped on purpose and one nobody has classified
    yet; ``is_classified`` tells the two apart.
    """
    return _LOOKUP.get(label_key(label))


def roots_for_discogs_genre(discogs_genre: str) -> Tuple[str, ...]:
    """The roots one of Discogs' top-level genres is evidence for."""
    for name, roots in DISCOGS_GENRE_ROOTS.items():
        if name.casefold() == discogs_genre.casefold():
            return roots
    return ()


@dataclass
class SourceVotes:
    """One source's opinion of one album, already in our vocabulary.

    ``leaves`` and ``roots`` are what the source's labels say. Discogs also
    has its top-level genres, which are coarser than our roots ("Funk / Soul"
    covers three), so they go in ``evidence_roots``: they count toward a
    root's votes but never tag an album by themselves. ``fallback_roots``
    holds the one root each of them most often means, for an album about
    which nothing better is known.
    """

    name: str
    leaves: List[str] = field(default_factory=list)
    roots: List[str] = field(default_factory=list)
    evidence_roots: List[str] = field(default_factory=list)
    fallback_roots: List[str] = field(default_factory=list)
    unclassified: List[str] = field(default_factory=list)

    @property
    def all_roots(self) -> set:
        """Every root this source supports, its leaves' and evidence included."""
        implied = {root for leaf in self.leaves for root in LEAF_ROOTS[leaf]}
        return implied | set(self.roots) | set(self.evidence_roots)

    @property
    def has_labels(self) -> bool:
        return bool(self.leaves or self.roots)

    @property
    def is_empty(self) -> bool:
        return not self.has_labels and not self.evidence_roots


def votes_from_labels(name: str, labels: Iterable[str]) -> SourceVotes:
    """Canonicalize one source's labels, keeping their order and dropping repeats."""
    votes = SourceVotes(name=name)
    for label in labels:
        label = (label or "").strip()
        if not label:
            continue
        canonical = canonicalize(label)
        if canonical is None:
            if not is_classified(label):
                votes.unclassified.append(label)
            continue
        if canonical.leaf:
            if canonical.leaf not in votes.leaves:
                votes.leaves.append(canonical.leaf)
        else:
            for root in canonical.roots:
                if root not in votes.roots:
                    votes.roots.append(root)
    return votes


def discogs_votes(styles: Iterable[str], genres: Iterable[str]) -> SourceVotes:
    """Discogs' vote: its styles as labels, its top-level genres as evidence."""
    votes = votes_from_labels("discogs", styles or ())
    for genre in genres or ():
        roots = roots_for_discogs_genre(genre)
        if not roots:
            continue
        if roots[0] not in votes.fallback_roots:
            votes.fallback_roots.append(roots[0])
        for root in roots:
            if root not in votes.evidence_roots:
                votes.evidence_roots.append(root)
    return votes


@dataclass
class AlbumGenres:
    """The genres chosen for one album: leaves, and every root they imply."""

    leaves: List[str] = field(default_factory=list)
    roots: List[str] = field(default_factory=list)

    @property
    def names(self) -> List[str]:
        return self.roots + self.leaves


def choose_album_genres(sources: Sequence[SourceVotes]) -> AlbumGenres:
    """Combine the sources' votes into an album's genres.

    The first source with any labels - Discogs, almost always - is the
    **base**, and its leaves and roots are kept. The others can only add:

    * a leaf another source also names;
    * a root two sources support (Discogs' top-level genres count as
      support);
    * for a supported root with no kept leaf under it, the first leaf any
      source names there. That is how *The Velvet Underground & Nico* gains
      Wikidata's "Proto-Punk", and how an album Discogs files only as
      "Electronic" picks up Wikidata's finer label.

    Nothing outvotes the base. A stricter rule, keeping only leaves two
    sources agreed on, was tried against the real corpus and dropped real
    genres: Wikidata often names a single genre, so it agreed with too little
    of Discogs. *Purple Rain* lost Funk, and *Exile on Main St.* lost Blues
    Rock and Country Rock.
    """
    active = [source for source in sources if not source.is_empty]
    labelled = [source for source in active if source.has_labels]
    if not labelled:
        fallback = active[0].fallback_roots if active else []
        return _with_roots([], set(fallback))

    base = labelled[0]
    leaf_votes = Counter(leaf for source in active for leaf in source.leaves)
    root_votes = Counter(root for source in active for root in source.all_roots)
    agreed_roots = {root for root, votes in root_votes.items() if votes >= 2}

    kept = list(base.leaves)
    for source in active:
        for leaf in source.leaves:
            if leaf not in kept and leaf_votes[leaf] >= 2:
                kept.append(leaf)

    covered = {LEAF_PARENT[leaf] for leaf in kept}
    for source in active:
        for leaf in source.leaves:
            parent = LEAF_PARENT[leaf]
            if leaf not in kept and parent in agreed_roots and parent not in covered:
                kept.append(leaf)
                covered.add(parent)

    return _with_roots(kept, set(base.roots) | agreed_roots)


def _with_roots(leaves: List[str], roots: set) -> AlbumGenres:
    """Order the roots the way the filter does, adding those leaves imply."""
    implied = set(roots)
    for leaf in leaves:
        implied.update(LEAF_ROOTS[leaf])
    return AlbumGenres(
        leaves=list(leaves),
        roots=[root for root in ROOT_GENRES if root in implied],
    )


def prune_rare_leaves(
    assignments: Dict[int, AlbumGenres], min_albums: int = MIN_LEAF_ALBUMS
) -> Tuple[Dict[int, AlbumGenres], Dict[str, int]]:
    """Drop leaves held by fewer than ``min_albums`` albums, corpus-wide.

    An album keeps the roots a dropped leaf implied, so it stays reachable
    from the filter; it just is not given a row of its own to sit in.
    Returns the pruned assignments and the leaves dropped, with their counts.
    """
    counts = Counter(leaf for genres in assignments.values() for leaf in genres.leaves)
    rare = {leaf: count for leaf, count in counts.items() if count < min_albums}
    pruned = {}
    for album_id, genres in assignments.items():
        roots = set(genres.roots)
        for leaf in genres.leaves:
            if leaf in rare:
                roots.update(LEAF_ROOTS[leaf])
        kept = [leaf for leaf in genres.leaves if leaf not in rare]
        pruned[album_id] = _with_roots(kept, roots)
    return pruned, rare


# ------------------------------------------------------------------ rows


def get_or_create_genre(name: str, parent_name: Optional[str] = None):
    """Get or create a ``MusicGenre``, creating its parent first if needed.

    Mirrors ``games.services.genre_normalizer.get_or_create_genre``: the
    parent is ensured recursively so ``level`` and ``path`` are always
    consistent, rather than relying on a later pass to repair them.

    An existing row whose parent disagrees with ``parent_name`` is moved.
    Returning it untouched is how "Alternative Rock" stayed filed under
    Electronic for 68 albums: the row was created from an album whose
    Discogs genres happened to lead with Electronic, and every later pass -
    including the ones after the resolution order was fixed - found the row
    by name and left it alone. A mapping fix that cannot reach the rows it
    was written for is not a fix.
    """
    from music.models import MusicGenre

    existing = MusicGenre.objects.filter(name=name).first()
    if existing is not None:
        if parent_name and parent_name != name:
            parent = get_or_create_genre(parent_name)
            if existing.parent_id != parent.id:
                reparent_genre(existing, parent)
        return existing

    parent = None
    level = 0
    path = name

    if parent_name and parent_name != name:
        parent = get_or_create_genre(parent_name)
        level = parent.level + 1
        path = f"{parent.path} > {name}"

    # External style names are not length-bounded by anything we control, and
    # SQLite would store an over-long one while PostgreSQL raises DataError.
    return MusicGenre.objects.create(
        name=name[: _max_length("name")],
        slug=slugify(name)[: _max_length("slug")],
        parent=parent,
        level=level,
        path=path[: _max_length("path")],
        display_order=_root_display_order(name),
    )


def get_or_create_canonical_genre(name: str):
    """The row for a root or vocabulary leaf, in its vocabulary position."""
    return get_or_create_genre(name, LEAF_PARENT.get(name))


def reparent_genre(genre, parent) -> None:
    """Move a genre under ``parent``, keeping ``level`` and ``path`` true.

    Both are denormalized for the filter tree, so moving a row without them
    leaves a style that renders at the wrong depth or under the wrong
    heading.
    """
    genre.parent = parent
    genre.level = parent.level + 1 if parent else 0
    path = f"{parent.path} > {genre.name}" if parent else genre.name
    genre.path = path[: _max_length("path")]
    genre.save(update_fields=["parent", "level", "path"])

    for child in genre.children.all():
        reparent_genre(child, genre)


def _max_length(field_name: str) -> int:
    from music.models import MusicGenre

    return MusicGenre._meta.get_field(field_name).max_length


def _root_display_order(name: str) -> int:
    """Roots sort in GENRE_HIERARCHY order; children sort by name after them."""
    if name in ROOT_GENRES:
        return ROOT_GENRES.index(name)
    return 0
