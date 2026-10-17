"""
Normalize Discogs genres and styles into the ``MusicGenre`` hierarchy.

Discogs supplies a two-level vocabulary per album: ``genres``, a small closed
top-level set, and ``styles``, the second level. That is already the shape
``MusicGenre`` models, so styles become leaf genres verbatim - they are
title-cased and presentable as published - and the only work here is deciding
which root each one hangs from.

The root set is deliberately *not* Discogs'. Discogs files Punk and Metal as
styles under Rock, and collapses Funk, Soul and R&B into one "Funk / Soul"
root, which is too coarse for a site ranking acclaimed albums. The roots here
are the ones ``music.templatetags.music_filters.MUSIC_GENRE_CATEGORY_ICONS``
already has icons for.

Most of the mapping is therefore derived rather than written:
``DISCOGS_GENRE_TO_ROOT`` turns an album's own Discogs top-level genre into a
default root, and ``STYLE_TO_ROOT`` only records the corrections where we
split finer than Discogs does, or where a style's default root would be wrong.

Why not Wikidata's P136 and its P279 subclass graph: walking P279 up to a root
classified only 159 of this corpus's 207 genre entities unambiguously, filed
thrash metal under Rock and mbaqanga under Jazz, and left ska, dub and ambient
music unreachable. Two of the genre entities have no English label at all.
"""

import logging
import re
from typing import Dict, Iterable, List, Optional

from django.utils.text import slugify

logger = logging.getLogger(__name__)

# The root genres, in the order the filter should present them. Every name
# here must appear in MUSIC_GENRE_CATEGORY_ICONS or its badge falls back to a
# generic note; music/tests/test_genre_normalizer.py asserts that.
GENRE_HIERARCHY: Dict[str, List[str]] = {
    "Rock": [],
    "Pop": [],
    "Hip Hop": [],
    "Electronic": [],
    "Soul": [],
    "R&B": [],
    "Funk": [],
    "Jazz": [],
    "Blues": [],
    "Folk": [],
    "Country": [],
    "Punk": [],
    "Metal": [],
    "Reggae": [],
    "Classical": [],
    "World": [],
}

ROOT_GENRES = tuple(GENRE_HIERARCHY)

# Discogs' own top-level genre -> our default root. Where Discogs is coarser
# than we are, the default is the most common reading and STYLE_TO_ROOT
# corrects the rest: most "Rock" styles really are Rock, and most
# "Funk / Soul" styles really are Soul.
DISCOGS_GENRE_TO_ROOT: Dict[str, str] = {
    "Rock": "Rock",
    "Pop": "Pop",
    "Hip Hop": "Hip Hop",
    "Electronic": "Electronic",
    "Funk / Soul": "Soul",
    "Jazz": "Jazz",
    "Blues": "Blues",
    "Reggae": "Reggae",
    "Classical": "Classical",
    "Folk, World, & Country": "Folk",
    "Latin": "World",
    "Non-Music": None,
    "Stage & Screen": None,
    "Brass & Military": "Classical",
    "Children's": None,
}

# Styles whose root is not what their album's Discogs genre implies. This is
# the hand-maintained part, and it is short by design.
#
# A style mapped to None is dropped: Discogs mixes genuine genres with
# descriptors ("Vocal", "Ballad", "Experimental"), and filing a descriptor as
# a genre makes the filter worse, not richer. The games normalizer drops
# non-genres the same way.
STYLE_TO_ROOT: Dict[str, Optional[str]] = {
    # --- Punk, which Discogs files under Rock ---
    "Punk": "Punk",
    "Punk Rock": "Punk",
    "Post-Punk": "Punk",
    "Hardcore": "Punk",
    "Pop Punk": "Punk",
    "Pop-Punk": "Punk",
    "Post-Hardcore": "Punk",
    "Oi": "Punk",
    "No Wave": "Punk",
    "Anarcho-Punk": "Punk",
    "Riot Grrrl": "Punk",
    # --- Metal, which Discogs also files under Rock ---
    "Heavy Metal": "Metal",
    "Thrash": "Metal",
    "Thrash Metal": "Metal",
    "Death Metal": "Metal",
    "Black Metal": "Metal",
    "Doom Metal": "Metal",
    "Sludge Metal": "Metal",
    "Nu Metal": "Metal",
    "Speed Metal": "Metal",
    "Metalcore": "Metal",
    "Hair Metal": "Metal",
    "Rap Metal": "Metal",
    # --- The three-way split of Discogs' single "Funk / Soul" root ---
    "Funk": "Funk",
    "P.Funk": "Funk",
    "Afrobeat": "World",
    "Disco": "Funk",
    "Soul": "Soul",
    "Neo Soul": "Soul",
    "Psychedelic Soul": "Soul",
    "Southern Soul": "Soul",
    "Smooth Soul": "Soul",
    "Soul-Jazz": "Jazz",
    "Rhythm & Blues": "R&B",
    "Contemporary R&B": "R&B",
    "Swingbeat": "R&B",
    "New Jack Swing": "R&B",
    "Gospel": "Soul",
    "Boogie": "Funk",
    # --- The split of "Folk, World, & Country" ---
    "Folk": "Folk",
    "Folk Rock": "Folk",
    "Country": "Country",
    "Country Rock": "Country",
    "Bluegrass": "Country",
    "Honky Tonk": "Country",
    "Nashville Sound": "Country",
    "Outlaw Country": "Country",
    "Americana": "Country",
    "Cajun": "World",
    "Highlife": "World",
    "Soukous": "World",
    "MPB": "World",
    "Bossa Nova": "World",
    "Samba": "World",
    "Tropicália": "World",
    "Pacific": "World",
    "African": "World",
    "Indian Classical": "World",
    "Hindustani": "World",
    "Celtic": "Folk",
    "Flamenco": "World",
    "Fado": "World",
    "Raï": "World",
    "Ethio-jazz": "Jazz",
    # --- Reggae family ---
    "Ska": "Reggae",
    "Rocksteady": "Reggae",
    "Dub": "Reggae",
    "Roots Reggae": "Reggae",
    "Dancehall": "Reggae",
    "Ragga": "Reggae",
    "Lovers Rock": "Reggae",
    # --- Hip Hop styles Discogs sometimes files elsewhere ---
    "Trip Hop": "Electronic",
    "Turntablism": "Hip Hop",
    "Grime": "Hip Hop",
    "Ragga HipHop": "Hip Hop",
    "Instrumental": None,
    # --- Styles whose name points at the wrong root ---
    # Synth-pop and friends are electronic music, not pop.
    "Synth-pop": "Electronic",
    "Synthpop": "Electronic",
    # 'wave' maps to Electronic for Darkwave and Ethereal Wave, but New Wave
    # is read as rock by almost everyone.
    "New Wave": "Rock",
    "Dream Pop": "Rock",
    "Jangle Pop": "Rock",
    "Power Pop": "Rock",
    "Noise Pop": "Rock",
    "Psychedelic Pop": "Rock",
    "Trip Hop": "Electronic",
    "Jazz-Rock": "Rock",
    "Blues Rock": "Rock",
    "Folk Rock": "Folk",
    "Country Rock": "Country",
    "Punk Rock": "Punk",
    "Pop Punk": "Punk",
    "Pop-Punk": "Punk",
    "Post-Punk": "Punk",
    "Goth Rock": "Rock",
    "Krautrock": "Rock",
    "Sludge Metal": "Metal",
    "Nu Metal": "Metal",
    "Soul-Jazz": "Jazz",
    "Jazz-Funk": "Jazz",
    "Jazzy Hip-Hop": "Hip Hop",
    "Piano Blues": "Blues",
    "Gospel": "Soul",
    "Rock & Roll": "Rock",
    "Rockabilly": "Rock",
    "Rock Opera": "Rock",
    # --- Corrections found by auditing all 153 styles in the release ---
    # Metal subgenres Discogs files under Rock.
    "Alternative Metal": "Metal",
    "Funk Metal": "Metal",
    "Groove Metal": "Metal",
    # Regional blues, which co-occurs with Jazz or Rock more often than Blues.
    "Piano Blues": "Blues",
    "Louisiana Blues": "Blues",
    "Texas Blues": "Blues",
    "Electric Blues": "Blues",
    # Big Band arrives tagged Electronic, of all things.
    "Big Band": "Jazz",
    "Bayou Funk": "Funk",
    "Minneapolis Sound": "Funk",
    "Zydeco": "World",
    # Pop subgenres whose album is tagged Rock first.
    "Baroque Pop": "Pop",
    "Music Hall": "Pop",
    "Europop": "Pop",
    "Psychedelic": "Rock",
    "Synthpunk": "Punk",
    "Darkwave": "Electronic",
    # --- Styles with no root word in their name ---
    # Pinned explicitly rather than left to the album's Discogs genre list,
    # so a style means the same thing on every album. Each root below is the
    # one the real corpus implied, checked by hand.
    "Conscious": "Hip Hop",
    "Gangsta": "Hip Hop",
    "Boom Bap": "Hip Hop",
    "Cut-up/DJ": "Hip Hop",
    "Beatbox": "Hip Hop",
    "Crunk": "Hip Hop",
    "Horrorcore": "Hip Hop",
    "G-Funk": "Hip Hop",
    "Downtempo": "Electronic",
    "Leftfield": "Electronic",
    "Industrial": "Electronic",
    "Big Beat": "Electronic",
    "Breaks": "Electronic",
    "Tribal": "Electronic",
    "Electroclash": "Electronic",
    "Bass Music": "Electronic",
    "Minimal": "Electronic",
    "IDM": "Electronic",
    "Glam": "Rock",
    "Grunge": "Rock",
    "Britpop": "Rock",
    "Shoegaze": "Rock",
    "Ethereal": "Rock",
    "AOR": "Rock",
    "Beat": "Rock",
    "Mod": "Rock",
    "Antifolk": "Rock",
    "Fusion": "Jazz",
    "Modal": "Jazz",
    "Swing": "Jazz",
    "Chanson": "Pop",
    # --- Descriptors, not genres ---
    "Vocal": None,
    "Ballad": None,
    "Experimental": None,
    "Acoustic": None,
    "Lo-Fi": None,
    "Parody": None,
    "Avantgarde": None,
    "Abstract": None,
    "Spoken Word": None,
    "Modern Classical": "Classical",
    "Musique Concrète": "Electronic",
    "Score": None,
    "Soundtrack": None,
    "Theme": None,
    "Novelty": None,
    "Education": None,
    "Interview": None,
    "Monolog": None,
    "Poetry": None,
    "Comedy": None,
    "Field Recording": None,
    "Easy Listening": "Pop",
    "Lounge": "Pop",
    "Space-Age": "Pop",
    "Música Popular Brasileira": "World",
}

# A style's root is inferred from its own name before the album's Discogs
# genres are consulted, because the album's genre list is the wrong authority:
# it is per-album and ordered arbitrarily, so 'Alternative Rock' filed under
# Electronic for OK Computer (Discogs lists it as "Electronic, Rock") and that
# one genre row then represented every alternative rock album on the site.
# A style name, by contrast, says what it is: the rightmost word that names a
# root wins, so 'Pop Rock' is Rock while 'Indie Pop' is Pop.
ROOT_KEYWORDS = {
    "rock": "Rock",
    "pop": "Pop",
    "metal": "Metal",
    "punk": "Punk",
    "hardcore": "Punk",
    "jazz": "Jazz",
    "bop": "Jazz",
    "blues": "Blues",
    "soul": "Soul",
    "funk": "Funk",
    "disco": "Funk",
    "r&b": "R&B",
    "hip hop": "Hip Hop",
    "rap": "Hip Hop",
    "reggae": "Reggae",
    "ska": "Reggae",
    "dub": "Reggae",
    "dancehall": "Reggae",
    "ragga": "Reggae",
    "folk": "Folk",
    "country": "Country",
    "bluegrass": "Country",
    "classical": "Classical",
    "house": "Electronic",
    "techno": "Electronic",
    "electro": "Electronic",
    "ambient": "Electronic",
    "garage": "Electronic",
    "wave": "Electronic",
    "idm": "Electronic",
    "dubstep": "Electronic",
    "breakbeat": "Electronic",
}

# Lower-cased lookups, so capitalization drift in either vocabulary does not
# silently create a second genre.
_STYLE_TO_ROOT_CASEFOLD = {
    name.casefold(): root for name, root in STYLE_TO_ROOT.items()
}
_ROOT_CASEFOLD = {name.casefold(): name for name in ROOT_GENRES}
_DISCOGS_GENRE_CASEFOLD = {
    name.casefold(): root for name, root in DISCOGS_GENRE_TO_ROOT.items()
}


def root_for_discogs_genre(discogs_genre: str) -> Optional[str]:
    """Our root genre for one of Discogs' top-level names, or None."""
    return _DISCOGS_GENRE_CASEFOLD.get(discogs_genre.casefold())


def root_from_style_name(style: str) -> Optional[str]:
    """Infer a root from the style's own name, or None.

    The rightmost word that names a root wins, which is how these names are
    built: the qualifier comes first and the genre last. 'Pop Rock' is a kind
    of rock, 'Indie Pop' a kind of pop.
    """
    words = re.split(r"[^a-z0-9&]+", style.casefold().replace("-", " "))
    words = [w for w in words if w]

    # Two-word roots first, so 'Hardcore Hip Hop' is Hip Hop and not Punk.
    for index in range(len(words) - 1, 0, -1):
        pair = f"{words[index - 1]} {words[index]}"
        if pair in ROOT_KEYWORDS:
            return ROOT_KEYWORDS[pair]

    for word in reversed(words):
        if word in ROOT_KEYWORDS:
            return ROOT_KEYWORDS[word]
    return None


def resolve_style(style: str, discogs_genres: Iterable[str] = ()) -> Optional[str]:
    """Return the root genre a Discogs style belongs under, or None to drop it.

    Resolution order:

    1. An explicit ``STYLE_TO_ROOT`` entry wins, including an explicit None.
    2. A style that *is* one of our roots is its own root ("Funk", "Jazz").
    3. The style's own name, which is global and so cannot make the same
       style mean different things on different albums.
    4. Only then the album's Discogs top-level genres.

    Returning None means "not a genre worth filtering on", which is different
    from a style we have never seen - that case returns None too, but logs,
    because an unmapped style is a gap in the mapping rather than a decision.
    """
    key = style.casefold()

    if key in _STYLE_TO_ROOT_CASEFOLD:
        return _STYLE_TO_ROOT_CASEFOLD[key]

    if key in _ROOT_CASEFOLD:
        return _ROOT_CASEFOLD[key]

    from_name = root_from_style_name(style)
    if from_name:
        return from_name

    for discogs_genre in discogs_genres:
        root = root_for_discogs_genre(discogs_genre)
        if root:
            return root

    logger.info(
        "Discogs style %r has no root (album genres: %s)",
        style,
        list(discogs_genres) or "none",
    )
    return None


def resolve_styles(
    styles: Iterable[str], discogs_genres: Iterable[str] = ()
) -> List[tuple]:
    """Map each style to ``(style, root)``, dropping the ones with no root.

    The style keeps its published spelling and becomes the leaf genre; the
    root is what it hangs from. Order is preserved and duplicates removed, so
    the first-listed style stays the most prominent.
    """
    discogs_genres = list(discogs_genres)
    resolved = []
    seen = set()

    for style in styles:
        if not style or style.casefold() in seen:
            continue
        seen.add(style.casefold())
        root = resolve_style(style, discogs_genres)
        if root:
            resolved.append((style, root))

    return resolved


def get_or_create_genre(name: str, parent_name: Optional[str] = None):
    """Get or create a ``MusicGenre``, creating its parent first if needed.

    Mirrors ``games.services.genre_normalizer.get_or_create_genre``: the
    parent is ensured recursively so ``level`` and ``path`` are always
    consistent, rather than relying on a later pass to repair them.
    """
    from music.models import MusicGenre

    existing = MusicGenre.objects.filter(name=name).first()
    if existing is not None:
        return existing

    parent = None
    level = 0
    path = name

    if parent_name and parent_name != name:
        parent = get_or_create_genre(parent_name)
        level = parent.level + 1
        path = f"{parent.path} > {name}"

    return MusicGenre.objects.create(
        name=name,
        slug=slugify(name),
        parent=parent,
        level=level,
        path=path,
        display_order=_root_display_order(name),
    )


def _root_display_order(name: str) -> int:
    """Roots sort in GENRE_HIERARCHY order; children sort by name after them."""
    if name in ROOT_GENRES:
        return ROOT_GENRES.index(name)
    return 0


def genres_for_album(styles: Iterable[str], discogs_genres: Iterable[str] = ()) -> list:
    """Return the ``MusicGenre`` rows an album's Discogs data implies.

    Both the leaf style and its root are returned, so filtering by a root
    genre finds the album without needing to walk the tree at query time -
    the same denormalization the games genre filter relies on.
    """
    genres = []
    for style, root in resolve_styles(styles, discogs_genres):
        root_genre = get_or_create_genre(root)
        if root_genre not in genres:
            genres.append(root_genre)
        leaf = get_or_create_genre(style, parent_name=root)
        if leaf not in genres:
            genres.append(leaf)
    return genres
