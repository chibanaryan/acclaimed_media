"""
Music-specific template filters and tags.

Re-exports the shared filters from ``core.templatetags.core_filters`` so a
music template needs only ``{% load music_filters %}``.
"""

from django import template
from django.urls import reverse
from django.utils.html import format_html_join
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
# root set the Discogs style mapping normalizes to, so they have to match
# music.services.genre_normalizer.GENRE_HIERARCHY exactly - a name that does
# not match silently renders the fallback icon instead.
MUSIC_GENRE_CATEGORY_ICONS = {
    "Blues": "mdi-guitar-acoustic",
    "Classical": "mdi-music-clef-treble",
    "Country": "mdi-guitar-pick",
    "Electronic": "mdi-waveform",
    "Folk": "mdi-guitar-acoustic",
    "Funk": "mdi-music-note-eighth",
    "Hip Hop": "mdi-microphone-variant",
    "Jazz": "mdi-saxophone",
    "Metal": "mdi-guitar-electric",
    "Pop": "mdi-star-four-points",
    "Punk": "mdi-flash",
    "R&B": "mdi-music-note",
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


@register.filter
def artist_display_name(artist):
    """Artist name, qualified by its parent act when it has one."""
    parent = getattr(artist, "parent", None)
    if parent is not None:
        return f"{artist.name} ({parent.name})"
    return artist.name


@register.filter
def format_artist_list(artists, max_display=3):
    """Join artist names, summarizing the tail: 'A, B & 2 more'."""
    names = [a.name for a in artists]
    if not names:
        return ""
    if len(names) <= max_display:
        if len(names) == 1:
            return names[0]
        return f"{', '.join(names[:-1])} & {names[-1]}"
    shown = ", ".join(names[:max_display])
    return f"{shown} & {len(names) - max_display} more"


@register.simple_tag
def artist_links(album, link_class="link link-hover"):
    """Render an album's artists as links, or the raw credit if unlinkable.

    Falls back to ``artist_credit`` so a credit that was never parsed into
    artists (or whose artists have no slug) still shows the published text
    rather than nothing.

    ``link_class`` follows the games templates' split: rows use the quiet
    ``link link-hover``, as a game row's developers do, and the detail page's
    properties table uses ``link link-accent``, as its developer row does.
    """
    artists = [a for a in album.artists.all() if a.slug]
    if not artists:
        return album.artist_credit
    return format_html_join(
        mark_safe('<span class="text-base-content/30">, </span>'),
        '<a href="{}" class="{}">{}</a>',
        (
            (
                reverse("music:artist-detail", kwargs={"slug": a.slug}),
                link_class,
                a.name,
            )
            for a in artists
        ),
    )


@register.simple_tag
def album_rank_url(album):
    """Link to the rankings page scrolled to this album."""
    base = reverse("music:home")
    return f"{base}?highlight={album.id}"


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
