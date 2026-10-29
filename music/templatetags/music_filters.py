"""
Music-specific template filters and tags.

Re-exports the shared filters from ``core.templatetags.core_filters`` so a
music template needs only ``{% load music_filters %}``.
"""

from django import template
from django.template.defaultfilters import date as format_date
from django.urls import reverse
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from core import constants as core_constants
from core.templatetags.core_filters import (
    format_decade,
    format_duration,
    from_now,
    markdown,
    pagination_pages,
    pagination_url,
    tojson,
)
from music import config
from music.services.credits import artist_summary, credit_separator

register = template.Library()

# Shared filters, re-registered on this library.
register.filter("from_now", from_now)
register.filter("tojson", tojson)
register.filter("format_duration", format_duration)
register.filter("markdown", markdown)
register.filter("format_decade", format_decade)
register.simple_tag(pagination_pages, name="pagination_pages")
register.simple_tag(pagination_url, name="pagination_url", takes_context=True)

# DaisyUI badge class per list type. These match the games source-lists page
# exactly, so a type badge means the same colour across the whole site.
LIST_TYPE_BADGE_CLASSES = {
    core_constants.LIST_ALLTIME: "badge-info",
    core_constants.LIST_DECADE: "badge-success",
    core_constants.LIST_MISC: "badge-warning",
    core_constants.LIST_EOY: "badge-error",
}

DEFAULT_GENRE_ICON = "mdi-music-note"

# Root music genres mapped to a Material Design icon. These names are the
# root set the genre vocabulary normalizes to, so they have to match
# music.services.genre_normalizer.GENRE_HIERARCHY exactly - a name that does
# not match silently renders the fallback icon instead.
MUSIC_GENRE_CATEGORY_ICONS = {
    "Blues": "mdi-piano",
    "Classical": "mdi-music-clef-treble",
    "Country": "mdi-violin",
    "Electronic": "mdi-waveform",
    "Folk": "mdi-guitar-acoustic",
    "Funk": "mdi-music-clef-bass",
    "Hip Hop": "mdi-boombox",
    "Jazz": "mdi-saxophone",
    "Metal": "mdi-skull",
    "Pop": "mdi-star-four-points",
    "Punk": "mdi-flash",
    "R&B": "mdi-microphone-variant",
    "Reggae": "mdi-palm-tree",
    "Rock": "mdi-guitar-electric",
    "Soul": "mdi-heart-pulse",
    "World": "mdi-earth",
}


@register.filter
def get_list_type_label(type_code):
    """Human-readable label for a list type code (A/D/E/M)."""
    return core_constants.get_list_type_label(type_code)


@register.filter
def get_list_type_badge_class(type_code):
    """DaisyUI badge modifier for a list type code."""
    return LIST_TYPE_BADGE_CLASSES.get(type_code, "badge-ghost")


@register.filter
def music_genre_icon(genre):
    """Material Design icon class for a genre, falling back to a note.

    Accepts a ``MusicGenre`` or a bare name. A child genre inherits its root
    ancestor's icon so a tree reads consistently.
    """
    if genre is None:
        return DEFAULT_GENRE_ICON
    if isinstance(genre, str):
        return MUSIC_GENRE_CATEGORY_ICONS.get(genre, DEFAULT_GENRE_ICON)

    icon_name = getattr(genre, "icon_name", "")
    if icon_name:
        return icon_name

    name = getattr(genre, "name", "")
    if name in MUSIC_GENRE_CATEGORY_ICONS:
        return MUSIC_GENRE_CATEGORY_ICONS[name]

    path = getattr(genre, "path", "") or ""
    root_name = path.split(" > ")[0] if path else name
    return MUSIC_GENRE_CATEGORY_ICONS.get(root_name, DEFAULT_GENRE_ICON)


def _artist_link(artist, link_class, name=None):
    """One artist's name, linked to their page when they have one.

    ``name`` is the name an album credits them under, when that is not their
    own: "Prince and the Revolution" links to Prince's page, titled "Prince".
    """
    text = name or artist.name
    if not artist.slug:
        return format_html("{}", text)
    title = format_html(' title="{}"', artist.name) if text != artist.name else ""
    return format_html(
        '<a href="{}" class="{}"{}>{}</a>',
        artist.get_absolute_url(),
        link_class,
        title,
        text,
    )


def _joined(parts):
    """Rendered names joined in the credit style: "A, B & C"."""
    joined = []
    for index, part in enumerate(parts):
        separator = credit_separator(index, len(parts))
        if separator:
            joined.append(
                format_html('<span class="text-base-content/30">{}</span>', separator)
            )
        joined.append(part)
    return mark_safe("".join(joined))


@register.simple_tag
def artist_links(album, link_class="link link-hover"):
    """Render an album's credit line, each name linked, in credit order.

    Each credit shows the name the album is credited under and links to the
    artist's page, so "Prince and the Revolution" goes to Prince. Joined the
    way ``artist_credit`` is, with the separators dimmed, and a various-artists
    credit ends in "Various Artists", unlinked: alone on a compilation, after
    the names on a soundtrack ("Jimmy Cliff & Various Artists"). Mirrored by
    the client renderer's ``_artistCreditHtml``.

    ``link_class`` follows the games templates' split: rows use the quiet
    ``link link-hover``, as a game row's developers do, and the detail page's
    properties table uses ``link link-accent``, as its developer row does.
    """
    credits = album.credits.all()
    if not credits:
        return album.artist_credit
    parts = [_artist_link(credit.artist, link_class, credit.name) for credit in credits]
    if album.various_artists:
        parts.append(format_html("{}", config.VARIOUS_ARTISTS))
    return _joined(parts)


@register.simple_tag
def artist_names(artists, link_class="link link-hover"):
    """Artists by their own names, linked and joined in the credit style."""
    return _joined([_artist_link(artist, link_class) for artist in artists])


register.simple_tag(artist_summary, name="artist_summary")


@register.simple_tag
def album_rank_url(album):
    """Link to the rankings page scrolled to this album."""
    base = reverse("music:home")
    return f"{base}?highlight={album.id}"


@register.filter
def release_date_label(album):
    """'May 16, 1966', 'May 1966', or just the year, as precisely as known.

    A month-precise date is stored as the 1st, so only a "day" shows a day.
    A date in another year than the published one shows the year alone,
    since the row's year links to that year's rankings.
    """
    released = album.release_date
    if not released or released.year != album.year_released:
        return album.year
    if album.release_date_precision == "day":
        return format_date(released, "F j, Y")
    return format_date(released, "F Y")


@register.simple_tag
def album_year_url(album):
    """Link to the rankings page filtered to this album's release year."""
    base = reverse("music:home")
    if album.year_released is None:
        return base
    return (
        f"{base}?start={album.year_released}&end={album.year_released}"
        f"&highlight={album.id}"
    )
